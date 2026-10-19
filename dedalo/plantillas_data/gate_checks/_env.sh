#!/usr/bin/env bash
# _env.sh — Centralized environment detection. NOT run on its own.
#
# This script is sourced from gate.sh, mapear.sh and the checks so that all
# of them share the same variables. Everything is overridable per project: if
# your project is not Python/Django, export your own paths/commands.
#
# Variables it defines (and the user can override):
#   PROYECTO        project root
#   BACKEND_DIR     backend root (applies migrate/migrations/tests)
#   FRONTEND_DIR    frontend root (optional; "" = no frontend)
#   PY_BACKEND      backend Python interpreter
#   PY_FRONTEND     frontend Python interpreter
#   DB_CHECK_CMD    DB check command ("" = none)
#   MIGRATE_CHECK   migrations command ("" = none)
#   TEST_CMD        tests command ("" = none)
#   SERVE_CMD       command that starts the backend to test endpoints
#   SERVE_URL       base URL to test endpoints ("" = not tested)
#   TOKEN_URL       login URL for token ("" = no token)
#   USUARIO/CLAVE   login credentials ("" = no auth). Default dev-only
#                   (admin/admin123) applied ONLY for a localhost backend.
#   ENDPOINTS       list of endpoints ("/api/...") separated by spaces

if [ -z "${PROYECTO:-}" ] || [ "$PROYECTO" = "" ]; then
    PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
    # <proyecto>/.dedalo/scripts/gate_checks/_env.sh (new) or
    # <proyecto>/gate_checks/_env.sh (legacy)
    [ "$(basename "$PROYECTO")" = "gate_checks" ] && PROYECTO="$(dirname "$PROYECTO")"
    if [ "$(basename "$PROYECTO")" = "scripts" ] && \
       [ "$(basename "$(dirname "$PROYECTO")")" = ".dedalo" ]; then
        PROYECTO="$(dirname "$(dirname "$PROYECTO")")"
    fi
    PROYECTO="${PROYECTO:-$(pwd)}"
fi
if [ -d "$PROYECTO/.dedalo" ]; then
    SCRIPTS_DIR="${SCRIPTS_DIR:-$PROYECTO/.dedalo/scripts}"
    ESTADO_DIR="${ESTADO_DIR:-$PROYECTO/.dedalo/estado}"
    REVIEW_DIR="${REVIEW_DIR:-$PROYECTO/.dedalo/review}"
else
    SCRIPTS_DIR="${SCRIPTS_DIR:-$PROYECTO}"
    ESTADO_DIR="${ESTADO_DIR:-$PROYECTO}"
    REVIEW_DIR="${REVIEW_DIR:-$PROYECTO/.dedalo_review}"
fi
export PROYECTO SCRIPTS_DIR ESTADO_DIR REVIEW_DIR

# ---- Backend / Frontend ----
BACKEND_DIR="${BACKEND_DIR:-}"
[ -z "$BACKEND_DIR" ] && [ -d "$PROYECTO/Backend" ] && BACKEND_DIR="$PROYECTO/Backend"
[ -z "$BACKEND_DIR" ] && BACKEND_DIR="$PROYECTO"

FRONTEND_DIR="${FRONTEND_DIR:-}"
[ -z "$FRONTEND_DIR" ] && [ -d "$PROYECTO/frontend" ] && FRONTEND_DIR="$PROYECTO/frontend"

# ---- Python ----
PY_BACKEND="${PY_BACKEND:-}"
[ -z "$PY_BACKEND" ] && [ -x "$PROYECTO/.venv/bin/python" ] && PY_BACKEND="$PROYECTO/.venv/bin/python"
[ -z "$PY_BACKEND" ] && [ -x "$BACKEND_DIR/venv/bin/python" ] && PY_BACKEND="$BACKEND_DIR/venv/bin/python"
[ -z "$PY_BACKEND" ] && [ -x "$BACKEND_DIR/.venv/bin/python" ] && PY_BACKEND="$BACKEND_DIR/.venv/bin/python"
[ -z "$PY_BACKEND" ] && command -v python3 >/dev/null 2>&1 && PY_BACKEND="python3"

PY_FRONTEND="${PY_FRONTEND:-}"
[ -z "$PY_FRONTEND" ] && [ -x "$FRONTEND_DIR/venv/bin/python" ] && PY_FRONTEND="$FRONTEND_DIR/venv/bin/python"
[ -z "$PY_FRONTEND" ] && PY_FRONTEND="${PY_BACKEND:-python3}"

# ---- Optional commands (overridable) ----
DB_CHECK_CMD="${DB_CHECK_CMD:-}"
MIGRATE_CHECK="${MIGRATE_CHECK:-}"
TEST_CMD="${TEST_CMD:-}"
SERVE_CMD="${SERVE_CMD:-}"
SERVE_URL="${SERVE_URL:-}"
TOKEN_URL="${TOKEN_URL:-}"
USUARIO="${USUARIO:-}"
CLAVE="${CLAVE:-}"
ENDPOINTS="${ENDPOINTS:-}"

# Stack auto-detection (only if nothing was configured manually)
if [ -n "$PY_BACKEND" ] && [ -f "$BACKEND_DIR/manage.py" ]; then
    # Django
    MIGRATE_CHECK="${MIGRATE_CHECK:-cd \"$BACKEND_DIR\" && \"$PY_BACKEND\" manage.py migrate --check}"
    TEST_CMD="${TEST_CMD:-cd \"$BACKEND_DIR\" && \"$PY_BACKEND\" -m pytest -q}"
    DB_CHECK_CMD="${DB_CHECK_CMD:-command -v pg_isready >/dev/null 2>&1 && pg_isready -q}"
    if [ -z "$SERVE_CMD" ] && [ -z "$ENDPOINTS" ]; then
        SERVE_CMD="cd \"$BACKEND_DIR\" && \"$PY_BACKEND\" manage.py runserver 8000 --noreload"
        SERVE_URL="${SERVE_URL:-http://localhost:8000}"
        TOKEN_URL="${TOKEN_URL:-http://localhost:8000/api/token/}"
        # Dev-only scaffold credentials. They are NEVER sent outside the local
        # machine: only applied when the target is localhost. For a remote URL,
        # USUARIO/CLAVE must be set explicitly.
        case "${SERVE_URL}${TOKEN_URL}" in
            *//localhost*|*//127.0.0.1*|*//0.0.0.0*|*//\[::1\]*)
                USUARIO="${USUARIO:-admin}"
                CLAVE="${CLAVE:-admin123}" ;;
        esac
        if [ -z "$USUARIO" ]; then
            echo "[GATE] ⚠ USUARIO/CLAVE no configurados para un backend remoto; define credenciales o el login fallará."
        fi
        ENDPOINTS="${ENDPOINTS:-productos/productos/ ventas/clientes/ usuarios/usuarios/ caja/caja/ kardex/movimientos/ compras/compras/ config/config/}"
    fi
elif [ -n "$PY_BACKEND" ]; then
    # Generic Python
    TEST_CMD="${TEST_CMD:-cd \"$BACKEND_DIR\" && \"$PY_BACKEND\" -m pytest -q}"
fi

export BACKEND_DIR FRONTEND_DIR PY_BACKEND PY_FRONTEND
export DB_CHECK_CMD MIGRATE_CHECK TEST_CMD SERVE_CMD SERVE_URL TOKEN_URL
export USUARIO CLAVE ENDPOINTS

# Shared utilities for checks/scripts
fail() { echo "[GATE] ✗ $1"; exit 1; }
ok()   { echo "[GATE] ✓ $1"; }

# Runs a space/newline-separated list of dots or commands.
# Usage: run_cmds "name" "list"
run_cmds() {
    local nombre="$1" lista="$2" cmd rc
    if [ -z "$lista" ]; then
        echo "[GATE] ⚠ $nombre: sin comando configurado, se omite"
        return 0
    fi
    while IFS= read -r cmd; do
        [ -z "$cmd" ] && continue
        # Allows "command|ok_message" and "(command) || fails"
        if eval "$cmd" >/dev/null 2>&1; then
            ok "OK"
        else
            rc=$?
            # The command already printed the error if it did; if not, generic
            echo "[GATE] ✗ $nombre"
            return 1
        fi
    done <<< "$lista"
    return 0
}