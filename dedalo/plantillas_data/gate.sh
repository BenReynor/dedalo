#!/usr/bin/env bash
# gate.sh — Check orchestrator (plugin-based).
# Each check in gate_checks/*.sh returns 0=OK, 1=FAIL and prints [GATE] ✓/✗.
# Order: numeric by prefix (01_, 02_, ...). Add/clean checks freely.
#
# Environment detection (Python, venv, DB/migrations/tests/backend commands)
# is centralized in gate_checks/_env.sh and is overridable.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKS_DIR="$SCRIPT_DIR/gate_checks"

# Load the shared environment (PROYECTO, PY_BACKEND, commands...)
if [ -f "$CHECKS_DIR/_env.sh" ]; then
    source "$CHECKS_DIR/_env.sh"
elif [ -f "$SCRIPT_DIR/_env.sh" ]; then
    source "$SCRIPT_DIR/_env.sh"
else
    # Backward-compat: without _env.sh we define the minimum.
    # fail/ok are also mandatory: without them, a failing check causes
    # "fail: command not found" (rc=127) which the loop ignores (no set -e)
    # and the gate ended up printing "✅ TODO OK" with rc=0.
    case "$SCRIPT_DIR" in
        */.dedalo/scripts) PROYECTO="$(dirname "$(dirname "$SCRIPT_DIR")")" ;;
        *) PROYECTO="$SCRIPT_DIR" ;;
    esac
    fail() { echo "[GATE] ✗ $1"; exit 1; }
    ok()   { echo "[GATE] ✓ $1"; }
fi

export PROYECTO

# ---- Load checks ----
if [ ! -d "$CHECKS_DIR" ]; then
    echo "[GATE] ⚠ No existe $CHECKS_DIR — se asume OK"
    exit 0
fi

shopt -s nullglob
checks=("$CHECKS_DIR"/*.sh)
shopt -u nullglob

# Exclude _env.sh (it is not a check).
# set -u with bash<4.4 (macOS /bin/bash, 3.2) blows up when expanding "${arr[@]}"
# on an empty array: same guard `${arr[@]+"${arr[@]}"}` as in dedalo.sh.
impl=()
for c in ${checks[@]+"${checks[@]}"}; do
    [ "$(basename "$c")" != "_env.sh" ] && impl+=("$c")
done
checks=(${impl[@]+"${impl[@]}"})

if [ ${#checks[@]} -eq 0 ]; then
    echo "[GATE] ⚠ Sin checks en $CHECKS_DIR — se asume OK"
    exit 0
fi

# ---- Run checks in order (subshell isolates variables per check) ----
for check in "${checks[@]}"; do
    nombre="$(basename "$check")"
    if ( source "$check" ); then
        :
    else
        rc=$?
        [ $rc -eq 0 ] || fail "Check falló: $nombre"
    fi
done

echo ""
echo "[GATE] ✅ TODO OK"
exit 0