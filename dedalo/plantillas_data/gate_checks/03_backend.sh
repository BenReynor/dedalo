#!/usr/bin/env bash
# 03_backend.sh — Starts the backend and checks that it responds + endpoints.
#
# Configurable via _env.sh / environment:
#   SERVE_CMD    command to start the backend ("" = check is skipped)
#   SERVE_URL    base URL to call (e.g.: http://localhost:8000)
#   TOKEN_URL    login endpoint to obtain a token ("" = no auth)
#   USUARIO/CLAVE login credentials
#   ENDPOINTS    list "ep1 ep2 ..." (joined as $SERVE_URL/api/$ep)
#
# If endpoints.txt exists at the root, it takes priority over ENDPOINTS.
set -uo pipefail

# `ok` is defined by gate.sh when it loads us with `source`. If this check runs
# standalone (by hand, or from another script) it doesn't have it and `ok` would
# be "command not found" (rc=127); since there is no `set -e` here, the check
# would continue and end with exit 0, i.e. green without having checked anything.
if ! command -v ok >/dev/null 2>&1; then
    ok() { echo "[GATE] ✓ $1"; }
fi

# endpoints.txt at the root wins
EPS=()
if [ -f "${PROYECTO:-}/endpoints.txt" ]; then
    while IFS= read -r e; do [ -n "$e" ] && EPS+=("$e"); done < "${ESTADO_DIR:-$PROYECTO}/endpoints.txt"
else
    # ENDPOINTS comes from _env.sh, space-separated
    for e in ${ENDPOINTS:-}; do EPS+=("$e"); done
fi

if [ -z "${SERVE_CMD:-}" ]; then
    echo "[GATE] ⚠ SERVE_CMD no configurado, se omite el check de backend"
    exit 0
fi

# --- HTTP with diagnostics --------------------------------------------------
# `curl -s` returns 0 even if the response is 404 or 500, so without looking at
# the code the check went green with a broken backend. Blindly adding -f doesn't
# work either: it aborts with "HTTP 404" and drops the body, which is exactly
# where FastAPI and Django explain the real reason ("detail": "not found").
#
# _http <curl args...> leaves the code in HTTP_CODE and the body in HTTP_BODY.
# A 000 means there was no HTTP response (connection refused, timeout...).
HTTP_CODE="000"
HTTP_BODY=""
_TIMEOUT_CONEXION=2
_TIMEOUT_TOTAL=5
_http() {
    local salida
    # The caps matter for the port probe: a listener that accepts but never
    # answers would otherwise hang the whole gate forever.
    salida="$(curl -s --connect-timeout "$_TIMEOUT_CONEXION" \
        --max-time "$_TIMEOUT_TOTAL" -w $'\n%{http_code}' "$@" 2>/dev/null)"
    HTTP_CODE="${salida##*$'\n'}"
    HTTP_BODY="${salida%$'\n'*}"
    [ -n "$HTTP_CODE" ] || HTTP_CODE="000"
}

# Body on a single line and truncated, so the diagnostics fit in the log.
_resumen() {
    printf '%s' "${1:-}" | tr '\n' ' ' | cut -c1-200
}

# Did the backend respond? Any HTTP response counts (200, 401, 404...):
# a 404 on the root is a healthy server that just has no "/" route, which is
# the most normal thing in FastAPI/Express. What indicates it did not start
# is a 000.
_responde() {
    _http "$1"
    [ "$HTTP_CODE" != "000" ]
}

# Do not kill by port: that would take down the user's own backend (or the
# test runner) when it happens to listen on SERVE_URL. Reuse a healthy server;
# fail if the port is occupied but does not answer HTTP.
BASE_URL="${SERVE_URL:-http://localhost:8000}"
PUERTO="$(echo "$BASE_URL" | sed -E 's|.*:([0-9]+).*|\1|')"
if [ "$PUERTO" = "$BASE_URL" ]; then PUERTO=""; fi

_es_local() {
    case "${1:-}" in
        http://localhost[:/]*|https://localhost[:/]*|\
        http://127.0.0.1[:/]*|https://127.0.0.1[:/]*|\
        http://0.0.0.0[:/]*|https://0.0.0.0[:/]*|\
        http://\[::1\][:/]*|https://\[::1\][:/]*) return 0 ;;
    esac
    return 1
}

BPID=""
_parar_backend() {
    [ -n "${BPID:-}" ] || return 0
    set +m
    kill -TERM -- -"$BPID" 2>/dev/null || kill -TERM "$BPID" 2>/dev/null
    _i=0
    while [ "$_i" -lt 5 ] && kill -0 "$BPID" 2>/dev/null; do
        _i=$((_i + 1))
        sleep 1
    done
    if kill -0 "$BPID" 2>/dev/null; then
        kill -KILL -- -"$BPID" 2>/dev/null || kill -KILL "$BPID" 2>/dev/null
    fi
    wait "$BPID" 2>/dev/null
    BPID=""
}

REUTILIZAR=0
if _responde "$BASE_URL/"; then
    echo "[GATE] ⚠ ya hay un backend respondiendo en $BASE_URL; se reutiliza sin liberar el puerto"
    REUTILIZAR=1
fi

if [ "$REUTILIZAR" -eq 0 ]; then
    if [ -n "$PUERTO" ] && _es_local "$BASE_URL" && command -v lsof >/dev/null 2>&1; then
        PIDS="$(lsof -ti :"$PUERTO" 2>/dev/null | tr '\n' ' ')"
        if [ -n "$PIDS" ]; then
            echo "[GATE] ✗ puerto $PUERTO ocupado por PID(s) $PIDS y no responde HTTP en $BASE_URL"
            echo "[GATE]   libéralo o cambia SERVE_URL; el gate no mata procesos por puerto"
            exit 1
        fi
    fi
    # Job control puts the backend in its OWN process group, so cleanup can
    # kill the server and its children without touching any other process.
    set -m
    eval "$SERVE_CMD" >/dev/null 2>&1 &
    BPID=$!
    trap _parar_backend EXIT
fi

# Wait for it to respond (up to 15 s). `seq` does not exist on BSD/macOS.
_espera=0
while [ "$_espera" -lt 15 ]; do
    _responde "$BASE_URL/" && break
    _espera=$((_espera + 1))
    sleep 1
done
if ! _responde "$BASE_URL/"; then
    echo "[GATE] ✗ backend no responde en $BASE_URL"
    exit 1
fi
ok "backend responde en $BASE_URL"

# Token (if TOKEN_URL is configured)
TOKEN=""
CONTENT_TYPE="application/json"
if [ -n "${TOKEN_URL:-}" ]; then
    BODY="{}"
    if [ -n "${USUARIO:-}" ]; then
        BODY="{\"username\":\"$USUARIO\",\"password\":\"${CLAVE:-}\"}"
    fi
    _http -X POST "$TOKEN_URL" -H "Content-Type: $CONTENT_TYPE" -d "$BODY"
    TOKEN="$(printf '%s' "$HTTP_BODY" | ( ${PY_BACKEND:-python3} -c "import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get('access') or d.get('token') or d.get('token_type',''))
except Exception:
    print('')" 2>/dev/null ) )"
    if [ -z "$TOKEN" ]; then
        # A 401 here usually means bad credentials: the body says so.
        echo "[GATE] ✗ no se obtuvo token en $TOKEN_URL (HTTP $HTTP_CODE)"
        [ -n "$HTTP_BODY" ] && echo "[GATE]   respuesta: $(_resumen "$HTTP_BODY")"
        exit 1
    fi
    ok "token JWT en $TOKEN_URL"
fi

# Test endpoints
if [ ${#EPS[@]} -eq 0 ]; then
    echo "[GATE] ⚠ sin endpoints configurados; solo comprobación de arranque"
    exit 0
fi
ERR=0
for ep in "${EPS[@]}"; do
    # Supports absolute or relative URLs (/api/ is prepended)
    case "$ep" in
        http*) url="$ep" ;;
        *) url="$BASE_URL/api/$ep" ;;
    esac
    if [ -n "$TOKEN" ]; then
        _http -H "Authorization: Bearer $TOKEN" "$url"
    else
        _http "$url"
    fi
    # Only 2xx is a healthy endpoint. 3xx is usually a miswritten route (missing
    # trailing slash) and 4xx/5xx is a broken endpoint: in both cases, red.
    if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
        ok "$url"
    else
        echo "[GATE] ✗ $url (HTTP $HTTP_CODE)"
        [ -n "$HTTP_BODY" ] && echo "[GATE]   respuesta: $(_resumen "$HTTP_BODY")"
        ERR=1
    fi
done
[ "$ERR" -eq 1 ] && exit 1
exit 0