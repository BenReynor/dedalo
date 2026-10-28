#!/usr/bin/env bash
# dedalo.sh — Autonomous loop for AI agents, with git by branches.
#
# ⚠️ DEPRECATED (manual use / reference). The loop that the GUI launches today is the
# native engine: dedalo/loop.py (python -m dedalo.loop), identical in
# log, observability and behavior, and native (it doesn't need bash to
# start; the gate, gate.sh/gate_checks, is still bash in both).
# This script is kept in the template because many tests run it as
# cross-check and for whoever prefers to run the loop by hand in a
# POSIX terminal. Behavior fixes go to loop.py; do NOT edit this
# script as source of truth except for parity.
#
# Branch workflow (per task):
#   dedalo/<fecha>                          <- run base branch (child of RAMA_BASE)
#   └── dedalo/tareas/<fecha>/t<N>          <- one branch per task (git does not
#                                                  allow branches under the name
#                                                  dedalo/<fecha>, which already
#                                                  exists as a ref, so they are
#                                                  grouped under dedalo/tareas/)
#        · gate OK + reviewer PASS -> merge (--ff-only) to the base and it is deleted
#        · gate KO or reviewer FAIL -> retry; if exhausted, it is deleted without touching the base
#   master never receives commits from the loop.
#
# For each task in plan.md:
#   1. Creates the task branch and runs the configured agent (AGENTE_TAREA).
#   2. Verifies with gate.sh (checks in gate_checks/*.sh).
#   3. DUAL GATE: if the gate passed, a second agent (AGENTE_REVISOR) reviews the
#      diff cold and requires "VERDICT: PASS" before committing.
#   4. If everything passes: commits ONLY that task's changes, merges and marks [x].
#   5. If it fails: retries and, when exhausted, deletes the branch and marks [B].
#
# Usage:
#   ./dedalo.sh [plan] [--hasta HH:MM] [--push] [--padre <rama>]
#   MAX_ITER=60 ./dedalo.sh plan.md
#
# Environment variables (optional):
#   AGENTE_TAREA      agent that implements (opencode|codex|claude). def: auto
#   AGENTES_PREFERIDOS preference order for auto and reviewer. def: "opencode codex claude"
#   CLI_OPENCODE      opencode binary (def: opencode)
#   CLI_CODEX         codex binary (def: codex)
#   CLI_CLAUDE        claude binary (def: claude)
#   MODELO_TAREA      provider/model model for the task (opencode only). def: empty
#   AGENTE_REVISOR    diff reviewer agent; empty = auto (prefers a different one).
#   MODELO_REVISOR    provider/model model for the diff reviewer (opencode only).
#   MODELO_JUEZ       cheap model for the criteria judge (98_criterio.sh, opencode).
#                     def: opencode/nemotron-3.5-lightning-free
#   OPENCODE_AGENT_JUEZ opencode agent for the judge (def: build)
#   CRITERIO          extracted from plan.md (line "criterio:" under the task) and
#                     exported to the gate so it shows in the checks.
#   NAVEGADOR         "1" enables the automatic navigator before each task.
#   MODELO_NAVEGADOR  provider/model model for the navigator (opencode only).
#   OPENCODE_AGENT_TAREA opencode agent for the task (def: build)
#   OPENCODE_AGENT_NAV   opencode agent for the navigator (def: navigate)
#   CODEX_FLAGS       extra flags for codex exec ("" by default)
#   CLAUDE_FLAGS      extra flags for claude -p ("" by default)
#   REVISION_DUAL     "1" enables the dual gate (def), "0" turns it off.
#   REVISION_MANUAL   "1" pauses before commit and waits for GUI approval, "0" automatic.
#   TIMEOUT_REVISION_MANUAL  maximum seconds waiting for manual approval before
#                     marking the task [B] and continuing (0 = wait indefinitely). def: 1800.
#   REVISION_APRUEBA_AGENTE  "1" allows an APPROVE issued by an agent (origen=mcp)
#                     to settle the manual review; "0" (def) ignores it and waits for a person.
#   MAX_COSTO         budget in USD (0 = no limit). Estimated cost per iteration.
#   COSTO_POR_ITER    estimated USD cost per task+review (def 0.50).
#   VOZ               "1" enables alerts when you get blocked/finish (notify-send, spd-say).
#
# Project memory (lecciones.md):
#   · It is injected into the agent before each task so it doesn't repeat past errors
#     (single-error correction).
#   · When a task gets blocked an automatic lesson is added.
#
# Portable: it infers its root from its own location; copies gate.sh, mapear.sh and
# dedalo.sh to the root of any project.
set -uo pipefail

# This script writes JSON (metrics.jsonl) and does decimal arithmetic, so
# it must NOT depend on the user's locale: with es_ES, bash and awk print
# "0,500000" and "printf" rejects "0.500000" ("invalid number"), which left
# metrics.jsonl as invalid JSON and the cost cap uncounted.
# LC_ALL=C does not change any format we use (numeric dates) and makes
# the `sort` of file lists comparable.
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Current layout: <proyecto>/.dedalo/scripts/dedalo.sh
# Legacy layout:  <proyecto>/dedalo.sh
case "$SCRIPT_DIR" in
    */.dedalo/scripts) PROYECTO="$(dirname "$(dirname "$SCRIPT_DIR")")" ;;
    *) PROYECTO="$SCRIPT_DIR" ;;
esac
if [ -d "$PROYECTO/.dedalo" ]; then
    SCRIPTS_DIR="$PROYECTO/.dedalo/scripts"
    ESTADO_DIR="$PROYECTO/.dedalo/estado"
    REVIEW_DIR="$PROYECTO/.dedalo/review"
else
    SCRIPTS_DIR="$PROYECTO"
    ESTADO_DIR="$PROYECTO"
    REVIEW_DIR="$PROYECTO/.dedalo_review"
fi
GATE="$SCRIPTS_DIR/gate.sh"
MAPEAR="$SCRIPTS_DIR/mapear.sh"
MAPA="$ESTADO_DIR/mapeo.txt"
LOG="$ESTADO_DIR/progreso.log"
PLAN="$PROYECTO/plan.md"
LECCIONES="$PROYECTO/lecciones.md"
LOG_REL="${LOG#"$PROYECTO"/}"
MAPA_REL="${MAPA#"$PROYECTO"/}"
SCRIPTS_REL="${SCRIPTS_DIR#"$PROYECTO"/}"
if [ "$SCRIPTS_REL" = "." ]; then
    SCRIPTS_REL="dedalo.sh, gate.sh, mapear.sh y gate_checks/"
else
    SCRIPTS_REL="${SCRIPTS_REL}/*"
fi
MAX_ITER="${MAX_ITER:-40}"
TIMEOUT_POR_TAREA="${TIMEOUT_POR_TAREA:-900}"
TIMEOUT_NAVEGADOR="${TIMEOUT_NAVEGADOR:-60}"
MAX_REINTENTOS=2
AGENTE_TAREA="${AGENTE_TAREA:-}"
AGENTES_PREFERIDOS="${AGENTES_PREFERIDOS:-opencode codex claude}"
MODELO_TAREA="${MODELO_TAREA:-}"
MODELO_NAVEGADOR="${MODELO_NAVEGADOR:-opencode/big-pickle}"
NAVEGADOR="${NAVEGADOR:-0}"
AGENTE_REVISOR="${AGENTE_REVISOR:-}"
MODELO_REVISOR="${MODELO_REVISOR:-}"
MODELO_JUEZ="${MODELO_JUEZ:-opencode/nemotron-3.5-lightning-free}"
JUEZ_AGENTE_JUEZ="${OPENCODE_AGENT_JUEZ:-build}"
REVISION_DUAL="${REVISION_DUAL:-1}"
REVISION_MANUAL="${REVISION_MANUAL:-0}"
TIMEOUT_REVISION_MANUAL="${TIMEOUT_REVISION_MANUAL:-1800}"
REVISION_APRUEBA_AGENTE="${REVISION_APRUEBA_AGENTE:-0}"
VOZ="${VOZ:-0}"
MAX_COSTO="${MAX_COSTO:-0}"
COSTO_POR_ITER="${COSTO_POR_ITER:-0.50}"
RAMA_BASE="${RAMA_BASE:-master}"
PUSH=""
HASTA=""
CONTROL="plan\.md|lecciones\.md|CONTEXTO\.md|progreso\.log|gate\.sh|dedalo\.sh|mapear\.sh|mapeo\.txt|endpoints\.txt|metrics\.jsonl|incidencias\.jsonl|gate_checks(/.*)?|\.dedalo(/.*)?|\.dedalo_review(/.*)?"

# ---------------------------------------------------------------------------
# POSIX utilities (work the same on GNU/Linux and BSD/macOS)
# ---------------------------------------------------------------------------

# awk with locale C to format decimals. Necessary even if the script already
# exports LC_ALL=C: if the script is sourced from another process with its own
# LC_ALL, the precedence is inverted. NOTE: `export LC_NUMERIC=C` does NOT work,
# because LC_ALL takes priority over LC_NUMERIC in child processes.
num() { LC_ALL=C awk "$@"; }

# Epoch in milliseconds. GNU `date +%s%3N` gives nanoseconds. On BSD/macOS:
# - it usually returns only seconds or may return "17915175853N" (literal N)
# - detect and degrade to perl (Time::HiRes) or to seconds with a zero suffix.
ahora_ms() {
    local ns
    ns="$(date +%s%3N 2>/dev/null || true)"
    case "$ns" in
        ''|*%N*|*N)
            # checks whether it is purely digits (GNU %3N)
            if [[ "$ns" =~ ^[0-9]+$ ]]; then
                printf '%s\n' "$ns"
                return 0
            fi
            ns=""
            ;;
        *)
            if [[ "$ns" =~ ^[0-9]+$ ]]; then
                printf '%s\n' "$ns"
                return 0
            fi
            ns=""
            ;;
    esac
    if command -v perl >/dev/null 2>&1; then
        if perl -MTime::HiRes=time -e 'printf "%d\n", int(time * 1000)' 2>/dev/null; then
            return 0
        fi
    fi
    printf '%s000\n' "$(date +%s)"
}

# `ping -W` means SECONDS on GNU and MILLISECONDS on BSD: it is decided once
# according to the OS to avoid leaving a ping hung for 2000 s on Linux.
PING_FLAGS="-c1 -W2"
case "$(uname -s 2>/dev/null || echo unknown)" in
    Darwin) PING_FLAGS="-c1 -W2000" ;;
esac

un_ping() {
    command -v ping >/dev/null 2>&1 || return 1
    # shellcheck disable=SC2086
    ping $PING_FLAGS 8.8.8.8 >/dev/null 2>&1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        # `shift 2` without checking $#: if --hasta/--padre/--trabajo came as
        # the LAST argument, shift did not advance and the while looped forever
        # (verified: 100% CPU, rc 124 with timeout). 64 = EX_USAGE.
        --hasta) [[ $# -ge 2 ]] || { echo "dedalo.sh: falta valor tras $1" >&2; exit 64; }
                 HASTA="$2"; shift 2 ;;
        --push) PUSH="1"; shift ;;
        --padre) [[ $# -ge 2 ]] || { echo "dedalo.sh: falta valor tras $1" >&2; exit 64; }
                 RAMA_BASE="$2"; shift 2 ;;
        --trabajo) [[ $# -ge 2 ]] || { echo "dedalo.sh: falta valor tras $1" >&2; exit 64; }
                   RAMA_TRABAJO="$2"; shift 2 ;;
        -h|--help) sed -n '1,22p' "$0"; exit 0 ;;
        *) PLAN="$1"; shift ;;
    esac
done
[[ "$PLAN" != /* ]] && PLAN="$PROYECTO/$PLAN"

FECHA="$(date +%Y-%m-%d)"
RAMA_RUN="dedalo/$FECHA"
RAMA_TRABAJO="${RAMA_TRABAJO:-}"

# Run start mark (epoch ms) for cleaning opencode sessions.
INICIO_MS="$(ahora_ms)"
SESIONES_LIMPIADAS=0

logx() { echo "[$(date '+%F %H:%M:%S')] $*" >> "$LOG"; }
hora_limite() { [[ -n "$HASTA" && "$(date +%H:%M)" > "$HASTA" ]]; }

hay_internet() {
    local i
    for i in 1 2 3; do
        un_ping && return 0
        # If there is no `ping` binary (or it is restricted by permissions), try HTTP.
        if ! command -v ping >/dev/null 2>&1; then
            command -v curl >/dev/null 2>&1 \
                && curl -s -m 3 https://1.1.1.1 >/dev/null 2>&1 && return 0
        fi
        sleep 2
    done
    return 1
}

alerta() {
    [ "$VOZ" = "1" ] || return 0
    command -v notify-send >/dev/null 2>&1 && notify-send "Dédalo" "$1" 2>/dev/null
    command -v spd-say >/dev/null 2>&1 && spd-say "$1" >/dev/null 2>&1
    printf '\a' 2>/dev/null || true
}

# Checks whether the output indicates token/quota exhaustion of the AI provider.
tokens_agotados() {
    local archivo="$1"
    grep -qiE \
        -e "insufficient_quota" \
        -e "rate_limit_exceeded" \
        -e "quota.exceeded" \
        -e "credit.balance.is.too.low" \
        -e "billing.hard.limit" \
        -e "RESOURCE_EXHAUSTED" \
        -e "tokens?.exhausted" \
        -e "out.of.tokens" \
        -e "no.quota" \
        -e "quota.depleted" \
        -e "monthly.limit" \
        -e "usage.limit" \
        "$archivo" >/dev/null 2>&1
}

# Detects whether the agent's output indicates a REAL lack of authentication.
# Anti-false-positive strategy:
#   1. Examines the COMPLETE stderr (where CLIs write real errors).
#   2. Examines only the LAST 40 lines of stdout (agent narrative
#      is usually long; real CLI errors appear at the end).
#   3. HIGH-CONFIDENCE, anchored patterns:
#        - "Please run .* login", "run .* auth login"
#        - "Authentication Error", "authentication_error"
#        - "invalid_api_key", "missing_api_key"
#        - "401 Unauthorized" / "HTTP 401" (NOT "401" alone)
#   4. They do NOT match: bare "401", bare "unauthorized", "OPENAI_API_KEY" in
#      narrative, mentions in old logs, etc.
#   5. CORROBORATION: aborts ONLY if there is suspicion AND the iteration produced
#      no change (no work = real failure; with work = false positive).
# Usage: sin_autenticacion <stderr_file> <stdout_file> <iteracion_sin_trabajo>
#   iteracion_sin_trabajo: MANDATORY. 1 = the iteration changed nothing
#   (see iteracion_sin_trabajo), 0 = the iteration produced real work.
#   Without corroboration (0) it NEVER aborts: the pattern is considered narrative.
sin_autenticacion() {
    local stderr_file="$1" stdout_file="$2" corroborar="$3"
    # HIGH-CONFIDENCE patterns (anchored, not loose):
    # - "Please run .../login" or "Please run ... login"
    # - "run ... auth login"
    # - "Authentication Error", "authentication_error"
    # - "invalid.?api.?key", "missing.?api.?key" (with or without dashes/spaces)
    # - "401 Unauthorized", "HTTP 401" (NOT "401" alone)
    # - "Please set your api key"
    local patron='(Please run .*/login|Please run .* login|run .* auth login|Authentication Error|authentication_error|invalid[ _.-]?api[ _.-]?key|missing[ _.-]?api[ _.-]?key|401 Unauthorized|HTTP 401|Please set your api key)'
    local detectado=0
    # 1. complete stderr
    if [ -f "$stderr_file" ] && grep -qiE "$patron" "$stderr_file"; then
        detectado=1
    fi
    # 2. last 40 lines of stdout
    if [ $detectado -eq 0 ] && [ -f "$stdout_file" ] && tail -40 "$stdout_file" | grep -qiE "$patron"; then
        detectado=1
    fi
    # CORROBORATION: only aborts if there is a pattern AND corroborar=1 (iteration with no
    # work). With corroborar=0 (iteration with work) the pattern is only the agent's
    # narrative → false positive → does not abort.
    [ "$detectado" = "1" ] && [ "$corroborar" = "1" ]
}

# Detects the first available agent (opencode -> codex -> claude).
# The order and the binaries are configurable:
#   AGENTES_PREFERIDOS="codex opencode"  (preference order)
#   CLI_OPENCODE/CLI_CODEX/CLI_CLAUDE      (binary for each agent)
detectar_agente() {
    local i
    for i in ${AGENTES_PREFERIDOS:-opencode codex claude}; do
        [ "$i" = "auto" ] && continue
        # agente_ok, NOT cli_agente: the latter only returns the name and
        # always exits with rc=0, so it "detected" the first in the list
        # even if it was not installed (and then the final agente_ok aborted).
        agente_ok "$i" && { echo "$i"; return 0; }
    done
    echo ""
}

# Returns an agent's binary (or empty if it is not installed).
cli_agente() {
    local agente="$1"
    case "$agente" in
        opencode) echo "${CLI_OPENCODE:-opencode}" ;;
        codex)    echo "${CLI_CODEX:-codex}" ;;
        claude)   echo "${CLI_CLAUDE:-claude}" ;;
        *) echo "" ;;
    esac
}

# `--dir <PROYECTO>` pins an opencode run to this project's directory. Without
# it, `opencode run` attaches to an already-running opencode server and works
# inside THAT server's project (the wrong repository), so the agent would read
# and edit the wrong tree. Only used when the installed build advertises the
# flag; the probe result is cached in _OPENCODE_DIR.
_OPENCODE_DIR=""
opencode_dir_ok() {
    if [ -z "$_OPENCODE_DIR" ]; then
        local bin
        bin="$(cli_agente opencode)"
        if [ -n "$bin" ] && "$bin" run --help 2>&1 | grep -q -- "--dir"; then
            _OPENCODE_DIR="1"
        else
            _OPENCODE_DIR="0"
        fi
    fi
    [ "$_OPENCODE_DIR" = "1" ]
}

agente_ok() {
    local bin
    bin="$(cli_agente "$1")" || return 1
    [ -n "$bin" ] && command -v "$bin" >/dev/null 2>&1
}

# PID of the process being waited on right now (the agent, the gate...).
# The traps need it to kill it: otherwise, the GUI's SIGTERM only reaches the
# shell and the opencode below keeps burning tokens until TIMEOUT_POR_TAREA.
AGENTE_PID=""

# File with that same PID. The gate runs as the left side of a pipe
# (`ejecutar_esperando bash "$GATE" | tee ...`), and that runs in a subshell where
# AGENTE_PID does not propagate to the parent. With the file, _matar_hijo finds it
# in both cases.
#
# It is computed here, at the top level, and not on demand inside a function:
# an assignment made inside `$(...)` is lost in the subshell, and then the
# parent would not even know the file name to delete it on exit. `$$` is the original
# script's pid also inside subshells, so they all coincide.
PID_HIJO="${TMPDIR:-/tmp}/dedalo_hijo.$$.pid"

# Kills the process being waited on and its grandchildren.
#
# The direct child is `timeout`, and the agent hangs from it. That is why the
# children are killed too: if we only kill `timeout`, the agent is orphaned
# continuing with the socket and the token. A margin is given for clean shutdown
# and then SIGKILL to whoever is still alive.
_matar_hijo() {
    local pid="$AGENTE_PID" kids="" i
    if [ -z "$pid" ] && [ -r "$PID_HIJO" ]; then
        pid="$(cat "$PID_HIJO" 2>/dev/null || true)"
    fi
    # Without a numeric pid there is nothing to kill (avoids `kill` with garbage).
    case "$pid" in ''|*[!0-9]*) return 0 ;; esac
    if command -v pgrep >/dev/null 2>&1; then
        kids="$(pgrep -P "$pid" 2>/dev/null || true)"
    fi
    [ -n "$kids" ] && kill -TERM $kids 2>/dev/null
    kill -TERM "$pid" 2>/dev/null
    for i in 1 2 3 4 5; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
        [ -n "$kids" ] && kill -KILL $kids 2>/dev/null
        kill -KILL "$pid" 2>/dev/null
    fi
    AGENTE_PID=""
    : > "$PID_HIJO"
    return 0
}

# `timeout` with portability: GNU timeout > gtimeout (Homebrew coreutils)
# > pure-bash fallback. macOS does not ship `timeout` (BSD), and without this EVERY
# agent launch would exit with rc=127 there.
#
# The fallback launches the command in the background and kills it after the
# seconds have passed, returning 124 as GNU timeout does (the script detects that
# code to warn about the hung task).
#
# CAREFUL with the `exec` of the GNU branch: ejecutar_esperando() calls this as
# `"$@" &`, so the subshell gets REPLACED by timeout and the process
# tree is identical to before (AGENTE_PID points to timeout, not to an
# intermediate wrapper that would hide the agent from _matar_hijo). That is why
# exec is only done when we are in a subshell ($BASHPID != $$): a foreground
# call must not replace the script.
_timeout() {
    local segs="$1" pid i=0 j
    shift
    if command -v timeout >/dev/null 2>&1; then
        if [ "$BASHPID" != "$$" ]; then
            exec timeout "$segs" "$@"
        fi
        timeout "$segs" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        if [ "$BASHPID" != "$$" ]; then
            exec gtimeout "$segs" "$@"
        fi
        gtimeout "$segs" "$@"
    else
        "$@" &
        pid=$!
        while kill -0 "$pid" 2>/dev/null; do
            if [ "$i" -ge "$segs" ]; then
                kill -TERM "$pid" 2>/dev/null || true
                j=0
                while kill -0 "$pid" 2>/dev/null && [ "$j" -lt 1 ]; do
                    sleep 1
                    j=$((j + 1))
                done
                kill -KILL "$pid" 2>/dev/null || true
                wait "$pid" 2>/dev/null || true
                return 124
            fi
            i=$((i + 1))
            sleep 1
        done
        wait "$pid"
        return $?
    fi
}

# Marks the first pending task in plan.md with the given mark ([x] or [B]).
#
# `sed -i "0,/pattern/"` is a GNU extension: on macOS (BSD sed) it does not even compile,
# and task marking would silently fail. awk + cat does the same with
# POSIX, and `cat > file` (instead of mv of the temp) preserves the inode and
# the permissions of the user's plan.md.
marcar_plan() {
    local marca="$1" tmp
    tmp="$(mktemp)" || return 1
    awk -v nueva="- [$marca]" '
        !hecho && $0 ~ /^- \[ \]/ { sub(/^- \[ \]/, nueva); hecho = 1 }
        { print }
    ' "$PLAN" > "$tmp" && cat "$tmp" > "$PLAN"
    rm -f "$tmp"
}

# Commits the plan marks and the lessons on the run branch.
#
# `marcar_plan` and `registrar_leccion` run after the task commit; without this
# the remote plan keeps every task as pending and the work tree stays dirty.
commit_memoria() {
    local asunto cambios
    asunto="dedalo: plan y lecciones (iter $iter)"
    cambios="$(cd "$PROYECTO" && git status --porcelain -- plan.md lecciones.md 2>/dev/null)"
    [ -n "$cambios" ] || return 0
    if ( cd "$PROYECTO" && git add -- plan.md lecciones.md \
        && git commit -q -m "$asunto" ); then
        logx "memoria commiteada: $asunto"
        echo "[dedalo] ✔ commit: $asunto"
    fi
}

# Runs a command in the background and waits for it to finish.
#
# It is the key point of the bug: with the child in the FOREGROUND, bash defers the trap
# until the child finishes (that is how a non-interactive shell does it), so the
# SIGTERM handler did not run until minutes later, when opencode had already
# finished. In the background `wait` is interrupted by the signal, so
# the trap runs instantly and can close the whole process tree.
ejecutar_esperando() {
    local rc
    "$@" &
    AGENTE_PID=$!
    printf '%s' "$AGENTE_PID" > "$PID_HIJO"
    wait "$AGENTE_PID"
    rc=$?
    AGENTE_PID=""
    : > "$PID_HIJO"
    return "$rc"
}

# Stops the loop on SIGTERM/SIGINT: kills whatever is running, cleans the
# sessions once and exits with the conventional code (128+signal).
#
# Before: `trap limpiar_sesiones EXIT TERM INT`. Two failures in one line:
#   1. A trap does not stop the script. Bash runs the handler and continues with the
#      loop, so the GUI had to resort to SIGKILL after 5 s.
#   2. With EXIT and TERM/INT together, the cleanup ran TWICE for a
#      single signal (one in the signal trap and another on exit).
# `trap - ... EXIT` prevents the handler from re-entering and the cleanup from duplicating.
_terminar() {
    trap - TERM INT EXIT
    _matar_hijo
    _cerrar
    exit "${1:-143}"
}

# Common close for both exits: loop end, break, error or signal.
_cerrar() {
    trap - EXIT
    limpiar_sesiones
    [ -n "$PID_HIJO" ] && rm -f "$PID_HIJO"
    return 0
}

# Cleans the opencode sessions that this run has created in the project.
# Criterion: directory == PROYECTO and time_created >= the run's INICIO_MS.
# It runs on exit (full loop, break, error or manual stop).
limpiar_sesiones() {
    local bin ids id n=0
    bin="$(cli_agente opencode)"
    [ -n "$bin" ] || return 0
    command -v "$bin" >/dev/null 2>&1 || return 0
    command -v jq >/dev/null 2>&1 || return 0
    # `_timeout` (portable) because this function is on the shutdown path: if
    # the CLI hangs, the script could neither clean nor exit, and
    # "Stop" from the GUI would stop responding. Losing the cleanup is better
    # than not exiting.
    ids="$(_timeout 20 "$bin" session list --format json 2>/dev/null | jq -r \
        --arg dir "$PROYECTO" --argjson desde "$INICIO_MS" \
        '.[] | select(.directory == $dir and .created >= $desde) | .id')"
    [ -n "$ids" ] || return 0
    while IFS= read -r id; do
        [ -z "$id" ] && continue
        _timeout 20 "$bin" session delete "$id" >/dev/null 2>&1
        n=$((n + 1))
    done <<< "$ids"
    SESIONES_LIMPIADAS=$n
    [ "$n" -gt 0 ] && echo "[dedalo] 🧹 Sesiones opencode eliminadas: $n" | tee -a "$LOG"
    return 0
}
# The code goes inside the string because `trap` does not accept arguments: the
# handler runs as is, so _terminar receives 143/130 as $1.
trap '_terminar 143' TERM
trap '_terminar 130' INT
trap _cerrar EXIT

# Runs a task with any agent. Returns its exit code.
#   $1 = agent (opencode|codex|claude)
#   $2 = output file
#   $3 = model (opencode only; empty = uses config)
#   "$@" = prompt (string)
run_agente() {
    local agente="$1" salida="$2" modelo="${3:-}" bin
    shift 3
    # "auto" only arrives here if someone invokes run_agente directly: it is
    # resolved as the already-detected task agent (or the first available one).
    if [ -z "$agente" ] || [ "$agente" = "auto" ]; then
        agente="${AGENTE_TAREA:-}"
        [ -z "$agente" ] || [ "$agente" = "auto" ] && agente="$(detectar_agente)"
    fi
    bin="$(cli_agente "$agente")"
    [ -n "$bin" ] || { echo "[dedalo] ✗ agente desconocido: $agente" | tee -a "$LOG"; return 1; }
    local t0 t1 dur rc=0
    t0=$(ahora_ms)
    local salida_err="${salida}.err"
    case "$agente" in
        opencode)
            local -a dir_args=()
            opencode_dir_ok && dir_args=(--dir "$PROYECTO")
            if [ -n "$modelo" ]; then
                ejecutar_esperando _timeout "$TIMEOUT_POR_TAREA" "$bin" run \
                    ${dir_args[@]+"${dir_args[@]}"} \
                    --agent "${OPENCODE_AGENT_TAREA:-build}" --model "$modelo" "$@" \
                    > "$salida" 2> "$salida_err"
            else
                ejecutar_esperando _timeout "$TIMEOUT_POR_TAREA" "$bin" run \
                    ${dir_args[@]+"${dir_args[@]}"} \
                    --agent "${OPENCODE_AGENT_TAREA:-build}" "$@" \
                    > "$salida" 2> "$salida_err"
            fi
            rc=$?
            ;;
        codex)
            # CAREFUL: the flags go in an array. Quoted "${CODEX_FLAGS:-}"
            # would add an EMPTY argument at the end and the CLI would take it as the
            # prompt, leaving the real prompt as the second positional.
            local -a flags=()
            [ -n "${CODEX_FLAGS:-}" ] && read -r -a flags <<< "$CODEX_FLAGS"
            ejecutar_esperando _timeout "$TIMEOUT_POR_TAREA" "$bin" exec --skip-git-repo-check \
                ${flags[@]+"${flags[@]}"} "$@" > "$salida" 2> "$salida_err"
            rc=$?
            ;;
        claude)
            local -a flags=()
            [ -n "${CLAUDE_FLAGS:-}" ] && read -r -a flags <<< "$CLAUDE_FLAGS"
            ejecutar_esperando _timeout "$TIMEOUT_POR_TAREA" "$bin" -p --output-format text \
                ${flags[@]+"${flags[@]}"} "$@" > "$salida" 2> "$salida_err"
            rc=$?
            ;;
        *)
            echo "[dedalo] ✗ agente desconocido: $agente" | tee -a "$LOG"
            return 1
            ;;
    esac
    t1=$(ahora_ms)
    dur=$((t1 - t0))
    _registrar_metrica "$agente" "$modelo" "$dur" "$rc" "$salida"
    return $rc
}

_registrar_metrica() {
    local agente="$1" modelo="$2" dur_ms="$3" rc="$4" salida="$5"
    local metric_file="${ESTADO_DIR:-$PROYECTO}/metrics.jsonl"
    local tokens_in=0 tokens_out=0 costo=0
    case "$agente" in
        opencode)
            local usage="$(grep -o '"usage":{"input_tokens":[0-9]*,"output_tokens":[0-9]*}' "$salida" 2>/dev/null | tail -1)"
            if [ -n "$usage" ]; then
                tokens_in=$(echo "$usage" | grep -o '"input_tokens":[0-9]*' | cut -d: -f2)
                tokens_out=$(echo "$usage" | grep -o '"output_tokens":[0-9]*' | cut -d: -f2)
            fi
            ;;
        codex)
            local usage="$(grep -o 'tokens_used: [0-9]*' "$salida" 2>/dev/null | tail -1)"
            if [ -n "$usage" ]; then
                tokens_out=$(echo "$usage" | cut -d' ' -f2)
            fi
            ;;
        claude)
            local usage="$(grep -o '"usage":{"input_tokens":[0-9]*,"output_tokens":[0-9]*}' "$salida" 2>/dev/null | tail -1)"
            if [ -n "$usage" ]; then
                tokens_in=$(echo "$usage" | grep -o '"input_tokens":[0-9]*' | cut -d: -f2)
                tokens_out=$(echo "$usage" | grep -o '"output_tokens":[0-9]*' | cut -d: -f2)
            fi
            ;;
    esac
    case "$modelo" in
        *opus*|*sonnet*|*haiku*) costo=$(num -v ti="$tokens_in" -v to="$tokens_out" 'BEGIN{printf "%.6f", (ti*15 + to*75)/1000000}') ;;
        *gpt-4*|*gpt-4o*) costo=$(num -v ti="$tokens_in" -v to="$tokens_out" 'BEGIN{printf "%.6f", (ti*30 + to*60)/1000000}') ;;
        *gpt-3.5*) costo=$(num -v ti="$tokens_in" -v to="$tokens_out" 'BEGIN{printf "%.6f", (ti*0.5 + to*1.5)/1000000}') ;;
        *) costo=$(num -v ti="$tokens_in" -v to="$tokens_out" 'BEGIN{printf "%.6f", (ti*1 + to*3)/1000000}') ;;
    esac
    printf '{"ts":"%s","iter":%s,"agente":"%s","modelo":"%s","dur_ms":%d,"rc":%d,"tokens_in":%d,"tokens_out":%d,"costo_usd":%.6f,"tarea":"%s"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${iter:-0}" "$agente" "${modelo:-default}" "$dur_ms" "$rc" "$tokens_in" "$tokens_out" "$costo" "${TAREA:-}" \
        >> "$metric_file"
}

# Context navigator prior to the task (agent-agnostic).
run_navegador() {
    local salida="$1" modelo="$2" tarea="$3" agente="${4:-$AGENTE_TAREA}" bin extra
    local prompt="Tarea: ${tarea}
Repo: ${PROYECTO}
Encuentra archivos, tests y endpoints relevantes. Lista concisa (máx 30 líneas):
ARCHIVOS: ruta/archivo.py
TESTS: ruta/test.py::test_x
ENDPOINTS: GET /api/...
MODELOS: Modulo.servicio"
    bin="$(cli_agente "$agente")"
    [ -n "$bin" ] || return 1
    local t0 t1 dur rc=0
    t0=$(ahora_ms)
    local salida_err="${salida}.err"
    case "$agente" in
        opencode)
            local -a nav_dir=()
            opencode_dir_ok && nav_dir=(--dir "$PROYECTO")
            ejecutar_esperando _timeout "$TIMEOUT_NAVEGADOR" "$bin" run \
                ${nav_dir[@]+"${nav_dir[@]}"} \
                --agent "${OPENCODE_AGENT_NAV:-navigate}" --model "$modelo" "$prompt" \
                > "$salida" 2> "$salida_err"
            rc=$?
            ;;
        codex)
            ejecutar_esperando _timeout "$TIMEOUT_NAVEGADOR" "$bin" exec \
                --skip-git-repo-check "$prompt" > "$salida" 2> "$salida_err"
            rc=$?
            ;;
        claude)
            ejecutar_esperando _timeout "$TIMEOUT_NAVEGADOR" "$bin" -p \
                --output-format text "$prompt" > "$salida" 2> "$salida_err"
            rc=$?
            ;;
        *)
            return 1
            ;;
    esac
    t1=$(ahora_ms)
    dur=$((t1 - t0))
    _registrar_metrica "$agente" "$modelo" "$dur" "$rc" "$salida"
    return $rc
}

elegir_revisor() {
    local preferido="${AGENTE_REVISOR:-}"
    local tarea="${AGENTE_TAREA:-}"
    local a
    # Explicit choice (the GUI sends the detected agent when resolving "auto"):
    # it wins even if it is the same one that implements, because that is what the
    # user asked for; we do not replace it with another.
    if [ -n "$preferido" ] && [ "$preferido" != "auto" ]; then
        agente_ok "$preferido" && { echo "$preferido"; return 0; }
    fi
    # "auto" or empty = fresh eyes: an agent different from the task one.
    for a in ${AGENTES_PREFERIDOS:-codex claude opencode}; do
        [ -z "$a" ] && continue
        [ "$a" = "auto" ] && continue
        agente_ok "$a" || continue
        [ "$a" != "$tarea" ] && { echo "$a"; return 0; }
    done
    # Only one agent is available: let the same one that implemented review, or the
    # gate would be left without review.
    agente_ok "$tarea" && { echo "$tarea"; return 0; }
    echo ""
}

diff_revision() {
    # Diff of the iteration for the reviewer, excluding the framework's CONTROL
    # files (plan.md, progreso.log, mapeo.txt…): they are traceability of
    # dedalo itself, not "changes unrelated" to the task.
    # New files are marked intent-to-add (git add -N) so that
    # `git diff` includes them; otherwise, the reviewer only saw tracked files.
    local -a archivos=()
    local linea
    git -C "$PROYECTO" add -N -A 2>/dev/null
    # CAREFUL: the paths go as SEPARATE pathspecs. Passing the multiline list
    # as a single quoted argument ("$ARCHIVOS_DIFF") turns it into
    # a literal pathspec with line breaks, which matches no file:
    # with two or more modified files the reviewer received an EMPTY diff and
    # approved without having seen anything. See tests/test_revisor_diff.py.
    # AND CAREFUL: `read -a` splits by spaces ONLY the line it reads, so with
    # `<<<` over a multiline list it would keep only the first file.
    while IFS= read -r linea; do
        [ -n "$linea" ] || continue
        archivos+=("$linea")
    done < <(git -C "$PROYECTO" diff --name-only | grep -vE "^($CONTROL)$")
    if [ ${#archivos[@]} -eq 0 ]; then
        echo "(sin cambios fuera de archivos CONTROL)"
        return 0
    fi
    git -C "$PROYECTO" diff --stat -- ${archivos[@]+"${archivos[@]}"}
    echo '#----- diff (excluye archivos CONTROL del framework) -----#'
    git -C "$PROYECTO" diff -- ${archivos[@]+"${archivos[@]}"}
}

revisar_diff() {
    local rev="$1" rev_out vdiff
    rev_out="$(mktemp)"
    vdiff="$(diff_revision)"
    local PROMPT_REV="Eres el REVISOR en modo dedalo. Si la tarea nombra una skill, cárgala y comprueba que el diff sigue sus reglas; no cargues otras.
Revisas el diff COMPLETO de una tarea, en frío, sin haber participado de ella.
Tarea: ${TAREA}

${vdiff}

Evalúa SOLO: (1) la tarea satisface su criterio, (2) no rompe nada obvio del proyecto,
(3) sin secretos, (4) sin scope creep (cambios ajenos a la tarea).
Responde con 2 o 3 líneas de razones y, EN LA ÚLTIMA LÍNEA, exactamente: VERDICT: PASS o VERDICT: FAIL"
    run_agente "$rev" "$rev_out" "$MODELO_REVISOR" "$PROMPT_REV"
    # We no longer dump the reviewer's output into progreso.log: it contaminated
    # the auth detection with loose words ("unauthorized", "401", etc.)
    # that the reviewer could mention when evaluating the diff.

    # The reviewer without a session: if there is no VERDICT in the output, it means it
    # could not review (possible lack of auth). If there IS a verdict, the reviewer
    # worked and any mention of auth is a false positive (narrative).
    local rev_sin_veredicto=0
    grep -q "VERDICT:" "$rev_out" || rev_sin_veredicto=1
    if sin_autenticacion "${rev_out}.err" "$rev_out" "$rev_sin_veredicto"; then
        echo "[dedalo] ✗✗ revisor ($rev) no está autenticado — deteniendo loop" | tee -a "$LOG"
        logx "ABORTADO: revisor sin autenticacion ($rev)"
        alerta "El revisor no está autenticado"
        exit 7
    fi

    # Check token/quota exhaustion in the reviewer's output
    if tokens_agotados "$rev_out"; then
        echo "[dedalo] ✗ Tokens/cuota agotados del proveedor IA (revisor) — deteniendo loop" | tee -a "$LOG"
        logx "ABORTADO: tokens/cuota agotados (revisor)"
        alerta "Tokens agotados, se detiene el dedalo"
        exit 5
    fi

    if grep -q "VERDICT: PASS" "$rev_out"; then
        echo "[dedalo] ✔ revisor ($rev): PASS"
        grep -iE "VERDICT:" "$rev_out" | tail -1
        rm -f "$rev_out" "${rev_out}.err"
        REVISOR_FEEDBACK=""
        return 0
    fi
    echo "[dedalo] ✗ revisor ($rev): FAIL"
    local veredicto_linea
    veredicto_linea="$(grep -iE "VERDICT:" "$rev_out" | tail -1)"
    echo "$veredicto_linea"
    # Extract feedback (everything before the VERDICT)
    REVISOR_FEEDBACK="$(sed -n '1,/VERDICT:/p' "$rev_out" | sed '$d' | sed '/^[[:space:]]*$/d' | paste -sd ' ' -)"
    rm -f "$rev_out" "${rev_out}.err"
    return 1
}

snapshot() {
    # Excludes compiled/caches (see .gitignore) so they never enter the
    # diff or get committed even if the project has no .gitignore.
    # core.quotepath=false prevents git status --porcelain from quoting
    # NON-ASCII characters (accents, ñ) in the names.
    # CAREFUL: SPACES do get quoted in porcelain v1 even if the flag is
    # set ("mi modulo.py"); revertir() normalizes them by removing the quotes.
    git -C "$PROYECTO" -c core.quotepath=false status --porcelain \
        | sed 's/^...//' \
        | grep -vE '(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|node_modules|\.venv|venv)/|\.pyc$|\.pyo$' \
        | sort > "$1"
}

# Did the current iteration not produce real work?
# Compares the BEFORE (before the agent) and AFTER snapshots.
# The CONTROL files (plan.md, progreso.log, metrics.jsonl, gate...) are
# excluded on BOTH sides: the loop itself writes them on every iteration, so
# without filtering them the absence of work would NEVER be detected and the
# authentication check would always abort on any pattern (false positive).
# The comparison is SYMMETRIC: additions (comm -13) and removals (comm -23). A file
# that disappears from the agent's status is also work (it deleted it).
# Returns 0 (true) if there was NO work, 1 (false) if there were changes.
iteracion_sin_trabajo() {
    local antes despues nuevos borrados
    antes="$(grep -vE "^($CONTROL)$" "$BEFORE" | sort -u)"
    despues="$(grep -vE "^($CONTROL)$" "$AFTER" | sort -u)"
    nuevos="$(comm -13 <(printf '%s\n' "$antes") <(printf '%s\n' "$despues"))"
    borrados="$(comm -23 <(printf '%s\n' "$antes") <(printf '%s\n' "$despues"))"
    [ -z "$nuevos" ] && [ -z "$borrados" ]
}

revertir() {
    # Revert all working-tree changes on the task branch back to the base commit.
    # The task branch was created from the base, so HEAD == base commit.
    # Use git status --porcelain (v1 format). Parse: first 3 chars = status,
    # rest = path (may be quoted if it contains spaces).
    # Change types:
    #   ??  untracked (new file by agent) → remove
    #    D / D  deleted in worktree → restore from HEAD
    #    M / M  / T / etc. modified → restore from HEAD
    # Skip CONTROL files (plan.md, progreso.log, etc.)
    git -C "$PROYECTO" status --porcelain \
        | grep -vE "^.. ($CONTROL)$" \
        | while IFS= read -r line; do
            status="${line:0:2}"
            file="${line:3}"
            # Strip surrounding double quotes if present (git quotes paths with spaces)
            file="${file#\"}"; file="${file%\"}"
            case "$status" in
                "??")
                    # New file created by the agent (untracked): delete it
                    rm -rf "$PROYECTO/$file" 2>/dev/null
                    ;;
                " D"|"D "|"D")
                    # File deleted by the agent: restore from HEAD
                    git -C "$PROYECTO" checkout -- "$file" 2>/dev/null
                    ;;
                *)
                    # Any other worktree modification (M, T, etc.): restore
                    git -C "$PROYECTO" checkout -- "$file" 2>/dev/null
                    ;;
            esac
        done
}

# --- Gate integrity: the agent must not be able to alter gate.sh/gate_checks ---
# The pristine gate is backed up at the start of the run; if the agent modifies it,
# it is restored and the attempt is voided (the gate is framework code, not the project's).
GATE_BACKUP_DIR="$(mktemp -d)"
backup_gate() {
    rm -rf "$GATE_BACKUP_DIR"
    mkdir -p "$GATE_BACKUP_DIR"
    cp -f "$GATE" "$GATE_BACKUP_DIR/" 2>/dev/null
    [ -d "$SCRIPTS_DIR/gate_checks" ] && cp -rf "$SCRIPTS_DIR/gate_checks" "$GATE_BACKUP_DIR/" 2>/dev/null
}

gate_intacto() {
    diff -q "$GATE" "$GATE_BACKUP_DIR/gate.sh" >/dev/null 2>&1 || return 1
    local f
    for f in "$PROYECTO"/gate_checks/*.sh; do
        [ -f "$f" ] || continue
        diff -q "$f" "$GATE_BACKUP_DIR/gate_checks/$(basename "$f")" >/dev/null 2>&1 || return 1
    done
    return 0
}

# First-use consent: the gate runs repo code (gate_checks/)
# without a sandbox, so an unknown project does not start without approval.
# Opt-in via environment (DEDALO_GATE_CONSENT=1, ideal in CI) or via terminal.
# The native engine (loop.py) also remembers the approval by content hash.
consentimiento_gate() {
    local dir="$SCRIPTS_DIR/gate_checks"
    [ -d "$dir" ] || return 0
    if [ "${DEDALO_GATE_CONSENT:-0}" = "1" ]; then
        logx "GATE: checks aprobados por entorno (DEDALO_GATE_CONSENT=1)"
        return 0
    fi
    echo "[dedalo] ⚠ El gate va a ejecutar código del repo SIN sandbox:"
    ls -1 "$dir" 2>/dev/null | sed 's/^/  • /'
    if [ -t 0 ]; then
        printf '[dedalo] ¿Confiar y ejecutar el gate? [y/N] '
        read -r resp
        case "$resp" in
            y|Y|yes|YES|s|S|si|SI|sí|SÍ)
                logx "GATE: checks aprobados por el usuario"
                return 0 ;;
        esac
    fi
    echo "[dedalo] ✗ gate_checks sin consentimiento; abortando."
    echo "[dedalo]   Aprueba con DEDALO_GATE_CONSENT=1 o desde la GUI."
    logx "ABORTADO: gate_checks sin consentimiento"
    exit 3
}

restaurar_gate() {
    cp -f "$GATE_BACKUP_DIR/gate.sh" "$GATE" 2>/dev/null
    [ -d "$GATE_BACKUP_DIR/gate_checks" ] && cp -rf "$GATE_BACKUP_DIR/gate_checks/." "$SCRIPTS_DIR/gate_checks/" 2>/dev/null
}

# Project memory: adds a lesson to lecciones.md (single-error
# correction). The agent uses it in the next task so it doesn't repeat the failure.
registrar_leccion() {
    local titulo="$1" sintoma="$2" causa="$3" prevencion="$4"
    {   printf '\n## %s — %s\n- Síntoma: %s\n- Causa: %s\n- Prevención: %s\n' \
            "$(date '+%Y-%m-%d %H:%M')" "$titulo" "$sintoma" "$causa" "$prevencion"
    } >> "$LECCIONES"
}

proxima_tarea() {
    local l
    while IFS= read -r l || [ -n "$l" ]; do
        if [[ "$l" == "- [ ] "* ]]; then
            echo "${l#- \[ \] }"
            return 0
        fi
    done < "$PLAN"
    return 1
}

# Returns the acceptance criterion of the FIRST pending task (- [ ]).
# plan.md format: line "criterio: ..." indented under the task.
criterio_tarea() {
    local l en_tarea=0
    while IFS= read -r l || [ -n "$l" ]; do
        if [[ "$l" == "- [ ] "* ]]; then
            # Inline criterion on the task's own line
            if [[ "$l" =~ criterio:[[:space:]]+(.*)$ ]]; then
                echo "${BASH_REMATCH[1]}"
                return 0
            fi
            en_tarea=1
            continue
        fi
        if [[ "$l" == "- ["* ]]; then
            [ "$en_tarea" -eq 1 ] && return 1
            continue
        fi
        if [ "$en_tarea" -eq 1 ]; then
            # An unindented line cuts the task block
            [[ "$l" =~ ^[[:space:]] ]] || return 1
            if [[ "$l" =~ criterio:[[:space:]]*(.*)$ ]]; then
                echo "${BASH_REMATCH[1]}"
                return 0
            fi
        fi
    done < "$PLAN"
    return 1
}

esperar_revision_manual() {
    # Only if REVISION_MANUAL=1
    [ "$REVISION_MANUAL" = "1" ] || return 0

    local dir_revision="${REVIEW_DIR:-$PROYECTO/.dedalo_review}"
    mkdir -p "$dir_revision"

    # Write diff and task for the GUI
    git -C "$PROYECTO" diff --stat > "$dir_revision/diff.txt"
    git -C "$PROYECTO" diff >> "$dir_revision/diff.txt"
    echo "$TAREA" > "$dir_revision/tarea.txt"
    echo "waiting" > "$dir_revision/waiting"

    echo "[dedalo] ⏸ Esperando revisión manual en $dir_revision..."
    logx "ESPERANDO REVISIÓN MANUAL: $TAREA"

    local decision="" esperado=0 origen=""
    while true; do
        while [ ! -f "$dir_revision/decision" ]; do
            sleep 2
            esperado=$((esperado + 2))

            # Infrastructure criterion: if the network goes down, abort like the rest of the loop.
            if [ $((esperado % 30)) -eq 0 ] && ! hay_internet; then
                echo "[dedalo] ✗ sin internet durante la revisión manual: abortando." | tee -a "$LOG"
                logx "ABORTADO: sin internet durante revisión manual"
                alerta "Sin internet, se aborta el dedalo"
                rm -f "$dir_revision/waiting" "$dir_revision/decision"
                exit 4
            fi

            if [ "$TIMEOUT_REVISION_MANUAL" -gt 0 ] && [ "$esperado" -ge "$TIMEOUT_REVISION_MANUAL" ]; then
                echo "[dedalo] ✗ timeout de revisión manual (${TIMEOUT_REVISION_MANUAL}s): tarea bloqueada." | tee -a "$LOG"
                logx "REVISIÓN MANUAL: timeout sin respuesta"
                alerta "Revisión manual sin respuesta, tarea marcada como bloqueada"
                rm -f "$dir_revision/waiting" "$dir_revision/decision"
                return 2
            fi
        done
        decision="$(cat "$dir_revision/decision")"

        # Origin of the decision: the GUI writes "# origen=gui" and the MCP server
        # "# origen=mcp" (answer at the end of the file). No mark = human.
        origen=""
        while IFS= read -r linea; do
            case "$linea" in
                "# origen="*) origen="${linea#\# origen=}"; break ;;
            esac
        done <<< "$decision"
        origen="$(printf '%s' "$origen" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"

        # Security: an agent cannot approve its own work. By default
        # (REVISION_APRUEBA_AGENTE=0) an APPROVE with origen=mcp is ignored and it
        # keeps waiting for human approval; with 1 it is accepted.
        case "$decision" in
            APPROVE*)
                if [ "$origen" = "mcp" ] && [ "${REVISION_APRUEBA_AGENTE:-0}" != "1" ]; then
                    echo "[dedalo] ⚠ aprobación emitida por un agente ignorada (política REVISION_APRUEBA_AGENTE=0); sigue esperando aprobación humana." | tee -a "$LOG"
                    logx "REVISIÓN MANUAL: APROBACIÓN POR AGENTE IGNORADA (política)"
                    rm -f "$dir_revision/waiting" "$dir_revision/decision"
                    echo "waiting" > "$dir_revision/waiting"
                    continue
                fi
                ;;
        esac
        break
    done
    rm -f "$dir_revision/waiting" "$dir_revision/decision"

    local quien="origen=humano"
    [ -n "$origen" ] && quien="origen=$origen"
    case "$decision" in
        APPROVE*)
            echo "[dedalo] ✔ Diff aprobado manualmente"
            logx "REVISIÓN MANUAL: APROBADO ($quien)"
            return 0
            ;;
        REJECT*)
            local motivo="${decision#REJECT}"
            motivo="$(printf '%s' "$motivo" | grep -v '^# origen=')"
            motivo="${motivo#$'\n'}"
            motivo="$(printf '%s' "$motivo" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
            echo "[dedalo] ✗ Diff rechazado: $motivo"
            logx "REVISIÓN MANUAL: RECHAZADO - $motivo ($quien)"
            RECHAZO_MOTIVO="$motivo"
            return 1
            ;;
        *)
            echo "[dedalo] ⚠ Decisión desconocida: $decision"
            return 1
            ;;
    esac
}

# ---- Agent autodetection if none was specified (or "auto" was requested) ----
# "auto" and empty mean the same: use the first available agent according to
# AGENTES_PREFERIDOS. The GUI sends "auto" by default, so resolving only the
# empty case left the loop without an agent (agente_ok "auto" → aborts with exit 2).
if [ -z "$AGENTE_TAREA" ] || [ "$AGENTE_TAREA" = "auto" ]; then
    AGENTE_TAREA="$(detectar_agente)"
    if [ -z "$AGENTE_TAREA" ]; then
        echo "[dedalo] ✗ No se encontró ningún agente (opencode, codex, claude)." | tee -a "$LOG"
        exit 2
    fi
    echo "[dedalo] Agente autodetectado: $AGENTE_TAREA"
fi

# Before launching the loop: if the agent's binary does not exist, abort now.
if ! agente_ok "$AGENTE_TAREA"; then
    BIN="$(cli_agente "$AGENTE_TAREA")"
    # ${VAR^^} is bash 4+; macOS's /bin/bash is 3.2. `tr` is POSIX.
    CLI_ENV="$(printf '%s' "$AGENTE_TAREA" | tr '[:lower:]' '[:upper:]')"
    echo "[dedalo] ✗✗ agente '$AGENTE_TAREA' no encontrado (busqué '$BIN')." \
         "Instálalo o configura el PATH (o CLI_${CLI_ENV}) y relanza." | tee -a "$LOG"
    logx "ABORTADO: agente no disponible ($AGENTE_TAREA)"
    exit 2
fi

REVISOR="$(elegir_revisor)"
COSTO_TOTAL=0
RECHAZO_MOTIVO=""
logx "== DEDALO INICIADO (agente=$AGENTE_TAREA, modelo=$MODELO_TAREA, revisor=${REVISOR:-ninguno}, modelo_rev=$MODELO_REVISOR, dual=$REVISION_DUAL, manual=$REVISION_MANUAL, max_iter=$MAX_ITER, hasta=${HASTA:-sin limite}, base=$RAMA_BASE, costo_max=$MAX_COSTO) =="

echo "[dedalo] Agente de tarea: ${AGENTE_TAREA} ${MODELO_TAREA:+($MODELO_TAREA)}"
echo "[dedalo] Revisor dual:    ${REVISOR:-NINGUNO} ${MODELO_REVISOR:+($MODELO_REVISOR)} (dual=$REVISION_DUAL)"

echo "[dedalo] Comprobando internet…"
if ! hay_internet; then
    echo "[dedalo] ✗ SIN INTERNET. Los modelos IA no pueden responder; abortando."
    logx "ABORTADO: sin internet"
    alerta "Sin internet, se aborta el dedalo"
    exit 4
fi
logx "Internet OK"

# First-use consent for the gate (see loop.py/consentimiento.py):
# the gate runs repo code without a sandbox, so an unknown repo is not
# run without explicit approval (environment or interactive terminal).
consentimiento_gate

# Backup of the pristine gate BEFORE the agent can touch anything.
backup_gate

echo "[dedalo] Baseline: gate.sh..."
if ! bash "$GATE"; then
    echo "El repo NO pasa la verificación baseline. Corrige y relanza."
    logx "ABORTADO: baseline falló"
    alerta "Baseline falló, el dedalo no arranca"
    exit 1
fi
logx "Baseline GATE OK"

if [ -f "$MAPEAR" ]; then
    bash "$MAPEAR" > "$MAPA" 2>/dev/null && logx "mapeo.txt regenerado" || echo "[dedalo] ⚠ no se pudo generar mapeo.txt"
fi

if git -C "$PROYECTO" rev-parse --verify "$RAMA_RUN" >/dev/null 2>&1; then
    git -C "$PROYECTO" checkout -q "$RAMA_RUN"
    echo "[dedalo] Reusando rama $RAMA_RUN"
else
    if ! git -C "$PROYECTO" checkout -q -b "$RAMA_RUN" "$RAMA_BASE"; then
        echo "[dedalo] ✗ no se pudo crear $RAMA_RUN desde $RAMA_BASE (¿árbol sucio?)."
        logx "ABORTADO: no se pudo crear la rama base"
        exit 1
    fi
    echo "[dedalo] Rama base: $RAMA_RUN (desde $RAMA_BASE)"
fi
logx "Rama base: $RAMA_RUN"

# --- Work branch (--trabajo): where the real work is done ---
#   · if it matches the main branch (master/main) → it works right there
#   · if it does not exist → it is created from the base branch (parent)
#   · if it exists (local or origin) → it is used as is
#   · if it is deleted mid-run → it returns to the base branch to finish
if [[ -n "${RAMA_TRABAJO:-}" && "$RAMA_TRABAJO" != "$RAMA_RUN" ]]; then
    if [[ "$RAMA_TRABAJO" == "master" || "$RAMA_TRABAJO" == "main" ]]; then
        git -C "$PROYECTO" checkout -q "$RAMA_TRABAJO" 2>/dev/null \
            || git -C "$PROYECTO" checkout -q -b "$RAMA_TRABAJO" "$RAMA_RUN"
        echo "[dedalo] Trabajando en la rama principal $RAMA_TRABAJO (sin rama paralela)"
    elif git -C "$PROYECTO" rev-parse --verify -q "$RAMA_TRABAJO" >/dev/null 2>&1; then
        git -C "$PROYECTO" checkout -q "$RAMA_TRABAJO"
        echo "[dedalo] Trabajando en la rama existente $RAMA_TRABAJO"
    elif git -C "$PROYECTO" rev-parse --verify -q "origin/$RAMA_TRABAJO" >/dev/null 2>&1; then
        git -C "$PROYECTO" checkout -q -b "$RAMA_TRABAJO" "origin/$RAMA_TRABAJO"
        echo "[dedalo] Trabajando en $RAMA_TRABAJO (seguimiento de origin/$RAMA_TRABAJO)"
    else
        git -C "$PROYECTO" checkout -q -b "$RAMA_TRABAJO" "$RAMA_RUN"
        echo "[dedalo] Creada la rama de trabajo $RAMA_TRABAJO (desde $RAMA_RUN)"
    fi
    logx "Rama de trabajo: $RAMA_TRABAJO"
else
    RAMA_TRABAJO="$RAMA_RUN"
    logx "Rama de trabajo (default): $RAMA_TRABAJO"
fi

iter=0
while (( iter < MAX_ITER )); do
    if hora_limite; then
        logx "Hora límite ($HASTA) alcanzada."
        echo "[dedalo] ⏰ Hora límite alcanzada."
        alerta "Hora límite alcanzada"
        break
    fi
    if [ "$MAX_COSTO" -gt 0 ] && num -v t="$COSTO_TOTAL" -v m="$MAX_COSTO" 'BEGIN{exit !(t>=m)}'; then
        logx "Presupuesto agotado (${COSTO_TOTAL}/${MAX_COSTO} USD)."
        echo "[dedalo] 💸 Presupuesto agotado (${COSTO_TOTAL}/${MAX_COSTO} USD)."
        alerta "Presupuesto agotado"
        break
    fi

    if ! hay_internet; then
        logx "SIN INTERNET: loop detenido para no lanzar tareas sin modelo disponible."
        echo "[dedalo] ✗ SIN INTERNET. Deteniendo el loop (los modelos IA no responden)."
        alerta "Sin internet, se detiene el dedalo"
        break
    fi

    if ! TAREA="$(proxima_tarea)"; then
        logx "No quedan tareas pendientes en $(basename "$PLAN")."
        echo "[dedalo] ✔ No quedan tareas pendientes."
        break
    fi

    iter=$((iter + 1))
    COSTO_ITER_ACTUAL=0
    RAMA_TAREA="dedalo/tareas/$FECHA/t$iter"
    CRITERIO="$(criterio_tarea || true)"
    logx "== Iteración $iter: $TAREA (rama $RAMA_TAREA)${CRITERIO:+ | criterio: $CRITERIO} =="
    echo "[dedalo] [$iter/$MAX_ITER] $TAREA -> $RAMA_TAREA"
    [ -n "$CRITERIO" ] && echo "[dedalo]   criterio: $CRITERIO"

    git -C "$PROYECTO" checkout -q "$RAMA_RUN" 2>/dev/null
    if git -C "$PROYECTO" rev-parse --verify -q "$RAMA_TAREA" >/dev/null 2>&1 \
            && [ "$(git -C "$PROYECTO" branch --show-current)" != "$RAMA_TAREA" ]; then
        git -C "$PROYECTO" branch -q -D "$RAMA_TAREA"
        echo "[dedalo] ⚠ rama huérfana $RAMA_TAREA eliminada (run anterior)"
    fi
    git -C "$PROYECTO" checkout -q -b "$RAMA_TAREA" "$RAMA_RUN"
    BEFORE="$(mktemp)"; AFTER="$(mktemp)"; OUT="$(mktemp)"
    snapshot "$BEFORE"

    hecho=0
    # `seq` does not exist on BSD/macOS. The counter increments on ENTERING the loop so
    # that a `continue` keeps advancing the attempt.
    intento=0
    while [ "$intento" -lt "$MAX_REINTENTOS" ]; do
        intento=$((intento + 1))
        PRE=""
        [ "$intento" -gt 1 ] && PRE="El intento anterior no pasó la verificación: no repitas tu cambio, corrígelo. "
        COSTO_ITER_ACTUAL="$(num -v t="$COSTO_ITER_ACTUAL" -v a="$COSTO_POR_ITER" 'BEGIN{printf "%.2f", t+a}')"

        # --- PROJECT MEMORY (single-error correction) ---
        LECCIONES_CONTEXTO=""
        if [ -f "$LECCIONES" ] && [ -s "$LECCIONES" ]; then
            LECCIONES_CONTEXTO="$(cat "$LECCIONES")"
        fi

        # --- AUTOMATIC NAVIGATOR (looks for context before the task) ---
        if [ "$NAVEGADOR" = "1" ] && agente_ok "$AGENTE_TAREA" && [ -n "$MODELO_NAVEGADOR" ]; then
            NAV_OUT="$(mktemp)"
            run_navegador "$NAV_OUT" "$MODELO_NAVEGADOR" "$TAREA" "$AGENTE_TAREA"
            # The navigator must not abort the loop over auth: its output is only context.
            # If it fails due to auth, there is simply no context.
            if [ -s "$NAV_OUT" ]; then
                NAV_CONTEXTO="$(cat "$NAV_OUT")"
            else
                NAV_CONTEXTO=""
            fi
            rm -f "$NAV_OUT" "${NAV_OUT}.err"
        else
            NAV_CONTEXTO=""
        fi

        PROMPT="Estás en MODO DEDALO. Si la tarea o su criterio nombran una skill, cárgala con tu herramienta de skills antes de empezar y sigue sus reglas; no cargues otras.
Tarea actual (solo esta): ${TAREA}
${PRE}Criterio de aceptación que debe cumplir tu trabajo (el gate lo verificará): ${CRITERIO:-<sin criterio explícito; usa los tests/mapeo.txt como contrato>}
Lee plan.md y ${LOG_REL} antes de tocar nada. Lee también ${MAPA_REL} (mapa módulos→tests): localiza el/los test del código que vas a tocar y úsalos como contrato.
${NAV_CONTEXTO}${LECCIONES_CONTEXTO:+MEMORIA DEL PROYECTO (lecciones aprendidas, evita repetir estos errores):
${LECCIONES_CONTEXTO}
}
Ejecuta ÚNICAMENTE esta tarea.
NO hagas commits, NO crees, cambies ni borres ramas: el script gestiona git.
NO edites ${SCRIPTS_REL}, plan.md, ${LOG_REL}, lecciones.md, endpoints.txt, .env ni SECURITY.md.
Al terminar, responde con un resumen conciso de qué cambiaste y qué tests corriste."

        run_agente "$AGENTE_TAREA" "$OUT" "$MODELO_TAREA" "$PROMPT"
        rc=$?
        if [ "$rc" -eq 124 ]; then
            echo "[dedalo] ⚠ timeout: ${AGENTE_TAREA} tardó más de ${TIMEOUT_POR_TAREA}s" | tee -a "$LOG"
            alerta "Tiempo agotado en una tarea"
        elif [ "$rc" -eq 126 ] || [ "$rc" -eq 127 ]; then
            # The agent's binary does not exist or is not executable: without an agent there
            # is no loop. Before, it continued and marked the task [x] without work.
            echo "[dedalo] ✗✗ ${AGENTE_TAREA} no se pudo ejecutar (rc=$rc):" \
                 "binario no encontrado o sin permisos de ejecución." | tee -a "$LOG"
            logx "ABORTADO: agente no ejecutable (rc=$rc)"
            alerta "El agente no se pudo ejecutar; revisa PATH/instalación"
            exit 6
        elif [ "$rc" -ne 0 ]; then
            echo "[dedalo] ⚠ ${AGENTE_TAREA} salió con rc=$rc" | tee -a "$LOG"
        fi
        cat "$OUT" >> "$LOG"
        cat "$OUT"

        # Tree snapshot after the agent. It goes BEFORE the authentication
        # check because the corroboration needs to know if the agent
        # changed anything; and it is used later to revert this attempt if the
        # dual reviewer or the manual review rejects it.
        snapshot "$AFTER"

        # Agent installed but WITHOUT a session: it is not a task failure, it is
        # configuration. Without this cut the loop would mark every task [B] and
        # keep burning iterations without ever being able to work.
        # CORROBORATION: only aborts if there is auth suspicion AND the iteration
        # changed nothing (no work = real failure; with work = false positive).
        # NO `local`: this is at the top-level of the script (inside the
        # while), and `local` outside a function leaves the variable UNCREATED →
        # `set -u` aborted on the next line with "unbound variable" and
        # any iteration with real work ended the run with exit 1.
        iter_sin_trabajo=0
        iteracion_sin_trabajo && iter_sin_trabajo=1
        if sin_autenticacion "${OUT}.err" "$OUT" "$iter_sin_trabajo"; then
            echo "[dedalo] ✗✗ $AGENTE_TAREA no está autenticado (CLI instalado, sin sesión)." \
                 "Haz login del agente y relanza (opencode: 'opencode auth login' · claude: '/login' · codex: 'codex login')." | tee -a "$LOG"
            logx "ABORTADO: agente sin autenticacion ($AGENTE_TAREA)"
            alerta "El agente no está autenticado; revisa su login"
            exit 7
        fi

        # Check token/quota exhaustion in the agent's output
        if tokens_agotados "$OUT"; then
            echo "[dedalo] ✗ Tokens/cuota agotados del proveedor IA — deteniendo loop" | tee -a "$LOG"
            logx "ABORTADO: tokens/cuota agotados"
            alerta "Tokens agotados, se detiene el dedalo"
            exit 5
        fi

        if [ "$(git -C "$PROYECTO" branch --show-current)" != "$RAMA_TAREA" ]; then
            echo "[dedalo] ✗✗ el agente cambió de rama. Abortando: requiere revisión humana." | tee -a "$LOG"
            logx "ABORTADO: se detectó cambio de rama no autorizado"
            alerta "El agente cambió de rama, se aborta el run"
            exit 3
        fi

        # CRITERIO and MODELO_JUEZ travel to the gate (98_criterio.sh reads them)
        export CRITERIO MODELO_JUEZ OPENCODE_AGENT_JUEZ

        # Gate integrity: if the agent altered gate.sh/gate_checks/*.sh,
        # restore the pristine one and void this attempt (the contaminated gate
        # is not run; it is a code injection vector).
        if ! gate_intacto; then
            restaurar_gate
            echo "[dedalo] ✗ el agente alteró gate.sh/gate_checks: gate restaurado, intento anulado." | tee -a "$LOG"
            logx "GATE ALTERADO por el agente (intento $intento), restaurado"
            PRE="No edites gate.sh ni gate_checks/*.sh (son del framework). Tu cambio a esos archivos se descartó. "
            continue
        fi

        logx "GATE: ejecutando gate.sh (intento $intento)"
        GATE_OUT="$(mktemp)"
        # tee: the gate's output is seen live AND saved for feedback
        if ejecutar_esperando bash "$GATE" 2>&1 | tee "$GATE_OUT"; then
            if [ "$REVISION_DUAL" = "1" ] && [ -n "$REVISOR" ]; then
                COSTO_ITER_ACTUAL="$(num -v t="$COSTO_ITER_ACTUAL" -v a="$COSTO_POR_ITER" 'BEGIN{printf "%.2f", t+a/2}')"
                if revisar_diff "$REVISOR"; then
                    # Dual gate passed, now verify manual review if it is enabled
                    esperar_revision_manual
                    rc_rev=$?
                    if [ "$rc_rev" -eq 0 ]; then
                        hecho=1
                        break
                    elif [ "$rc_rev" -eq 2 ]; then
                        logx "Revisión manual: timeout, tarea marcada [B]"
                        break
                    else
                        # Rejected: revert changes before retrying
                        revertir "$BEFORE" "$AFTER"
                        PRE="El diff fue rechazado en revisión manual: ${RECHAZO_MOTIVO}. Corrige esto en tu siguiente intento. "
                        logx "REVISIÓN MANUAL RECHAZADO, reintentando..."
                    fi
                else
                    logx "REVISOR FAIL (intento $intento)"
                    echo "[dedalo] ✗ el revisor rechazó el diff (intento $intento/$MAX_REINTENTOS)"
                    # Inject reviewer feedback into the next attempt
                    if [ -n "$REVISOR_FEEDBACK" ]; then
                        PRE="El revisor rechazó el diff anterior: ${REVISOR_FEEDBACK}. Corrige esto en tu siguiente intento. "
                        logx "Feedback del revisor inyectado para siguiente intento"
                    fi
                fi
            else
                # Without a dual gate, verify manual review
                esperar_revision_manual
                rc_rev=$?
                if [ "$rc_rev" -eq 0 ]; then
                    hecho=1
                    break
                elif [ "$rc_rev" -eq 2 ]; then
                    logx "Revisión manual: timeout, tarea marcada [B]"
                    break
                else
                    revertir "$BEFORE" "$AFTER"
                    PRE="El diff fue rechazado en revisión manual: ${RECHAZO_MOTIVO}. Corrige esto en tu siguiente intento. "
                    logx "REVISIÓN MANUAL RECHAZADO, reintentando..."
                fi
            fi
        else
            logx "GATE FALLÓ tras el agente (intento $intento)"
            echo "[dedalo] ✗ la tarea no pasó el gate (intento $intento/$MAX_REINTENTOS)"
            # Capture the gate's output to give it to the agent in the
            # next attempt ("pipe_output" pattern): so it knows WHAT failed.
            cat "$GATE_OUT" >> "$LOG"
            GATE_FEEDBACK="$(grep -vE '^\[GATE\] (✓|⚠)' "$GATE_OUT" | tail -15 | tr '\n' ' ' | cut -c1-500)"
            if [ -n "$GATE_FEEDBACK" ]; then
                PRE="El gate falló con: ${GATE_FEEDBACK}. El detalle completo está en progreso.log. Corrige esto en tu siguiente intento. "
                logx "Feedback del gate inyectado para siguiente intento"
            fi
        fi
        rm -f "$GATE_OUT"
    done

    logx "Costo iteración ${iter}: ${COSTO_ITER_ACTUAL} USD"
    snapshot "$AFTER"

    if [ "$hecho" -eq 1 ]; then
        CHANGED="$(comm -13 <(sort "$BEFORE") <(sort "$AFTER") | grep -vE "^($CONTROL)$")"
        if [ -n "$CHANGED" ]; then
            # Short subject (<50 chars, see git) + body with the full task
            SUBJETO="dedalo: $(printf '%s' "$TAREA" | cut -c1-40)"
            # $CHANGED may contain line breaks and spaces: use an array to
            # protect paths with spaces and avoid word-splitting.
            # mapfile is bash 4+; we use a portable while.
            changed_arr=()
            while IFS= read -r line; do
                [ -n "$line" ] && changed_arr+=("$line")
            done <<< "$CHANGED"
            if ( cd "$PROYECTO" && git add -- "${changed_arr[@]}" && git commit -q -m "$SUBJETO" -m "$TAREA" ); then
                logx "commit en $RAMA_TAREA: $SUBJETO"
                echo "[dedalo] ✔ commit: $SUBJETO"
            fi
        else
            logx "tarea completada sin cambios nuevos"
            echo "[dedalo] ✔ tarea completada sin cambios nuevos"
        fi
        # Only if the merge --ff-only succeeds is it marked [x] and the branch deleted.
        # If it fails, the branch is kept for diagnosis and marked [B] with a lesson.
        if git -C "$PROYECTO" checkout -q "$RAMA_RUN" \
            && git -C "$PROYECTO" merge -q --ff-only "$RAMA_TAREA" 2>/dev/null; then
            git -C "$PROYECTO" branch -q -d "$RAMA_TAREA"
            logx "mergeada $RAMA_TAREA -> $RAMA_RUN"
            # Update mapeo.txt automatically after a completed task
            bash "$MAPEAR" > "$MAPA" 2>/dev/null && logx "mapeo.txt actualizado tras $TAREA"
            marcar_plan x
        else
            echo "[dedalo] ⚠ merge fallido; rama $RAMA_TAREA conservada y tarea marcada [B]." | tee -a "$LOG"
            marcar_plan B
            registrar_leccion \
                "Merge fallido: ${TAREA}" \
                "git merge --ff-only $RAMA_TAREA -> $RAMA_RUN falló; rama conservada." \
                "La rama de la tarea sigue en $RAMA_TAREA; revisar conflictos o historial." \
                "Resolver el merge manualmente o ajustar la base si es necesario."
            logx "lección registrada (merge fallido)"
        fi
    else
        git -C "$PROYECTO" checkout -q "$RAMA_RUN"
        git -C "$PROYECTO" branch -q -D "$RAMA_TAREA"
        revertir "$BEFORE" "$AFTER"
        marcar_plan B
        logx "tarea BLOQUEADA: $TAREA (rama $RAMA_TAREA descartada)"
        echo "[dedalo] ✗ tarea bloqueada tras $MAX_REINTENTOS intentos. Marcada [B] en plan.md"
        alerta "Tarea bloqueada: $TAREA"
        registrar_leccion \
            "Tarea bloqueada: ${TAREA}" \
            "El agente no cumplió el criterio tras $MAX_REINTENTOS intentos." \
            "gate.sh/revisor fallaron en la iteración ${iter}." \
            "Reformular la tarea en plan.md, dividirla en pasos más pequeños o revisar los criterios."
        logx "lección registrada en lecciones.md (tarea bloqueada)"
    fi

    commit_memoria

    COSTO_TOTAL="$(num -v t="$COSTO_TOTAL" -v a="$COSTO_ITER_ACTUAL" 'BEGIN{printf "%.2f", t+a}')"
    logx "Costo estimado acumulado: $COSTO_TOTAL USD"
    echo "[dedalo] 💰 Costo estimado acumulado: ${COSTO_TOTAL} USD"

    rm -f "$BEFORE" "$AFTER" "$OUT" "${OUT}.err"
done

# --- Integrate the work into the target branch (--trabajo different from the run) ---
# The loop commits on RAMA_RUN (the run's base branch); if working on
# another branch was requested, the whole run is left integrated there at the end.
if [ -n "${RAMA_TRABAJO:-}" ] && [ "$RAMA_TRABAJO" != "$RAMA_RUN" ]; then
    echo "[dedalo] Integrando $RAMA_RUN -> $RAMA_TRABAJO"
    if git -C "$PROYECTO" checkout -q "$RAMA_TRABAJO" && \
       git -C "$PROYECTO" merge -q --no-ff "$RAMA_RUN" -m "dedalo: integrar $RAMA_RUN" 2>/dev/null; then
        logx "integrado $RAMA_RUN -> $RAMA_TRABAJO"
    else
        echo "[dedalo] ⚠ no se pudo integrar en $RAMA_TRABAJO; el trabajo queda en $RAMA_RUN" | tee -a "$LOG"
    fi
fi

# Try to create a repo on GitHub if there are credentials and no remote origin
# Preferred way: gh CLI (uses keyring credentials, no token on the
# command line or in logs). Fallback: GITHUB_TOKEN via API.
_asegurar_remote_origin() {
    if ! git -C "$PROYECTO" remote get-url origin >/dev/null 2>&1; then
        local repo_name="$(basename "$PROYECTO")"
        local owner=""
        if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
            owner="$(gh api user --jq .login 2>/dev/null)"
            if [ -n "$owner" ] && gh repo create "$owner/$repo_name" --private >/dev/null 2>&1; then
                echo "[dedalo] ✔ repo creado en GitHub: $owner/$repo_name"
                # https remote: uses gh's credential helper (keyring), not SSH.
                git -C "$PROYECTO" remote add origin "https://github.com/$owner/$repo_name.git"
                logx "repo creado y remote origin configurado: https://github.com/$owner/$repo_name.git"
                return 0
            fi
            echo "[dedalo] ⚠ no se pudo crear repo con gh (respuesta API)" | tee -a "$LOG"
        elif [ -n "${GITHUB_TOKEN:-}" ]; then
            owner="$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/user | grep -o '"login":"[^"]*"' | cut -d'"' -f4)"
            if [ -n "$owner" ]; then
                echo "[dedalo] Creando repo GitHub: $owner/$repo_name ..."
                local create_resp="$(curl -s -X POST -H "Authorization: Bearer $GITHUB_TOKEN" \
                    -H "Accept: application/vnd.github+json" \
                    "https://api.github.com/user/repos" \
                    -d "{\"name\":\"$repo_name\",\"private\":true,\"auto_init\":false}")"
                if echo "$create_resp" | grep -q '"ssh_url"'; then
                    local ssh_url="$(echo "$create_resp" | grep -o '"ssh_url":"[^"]*"' | cut -d'"' -f4)"
                    git -C "$PROYECTO" remote add origin "$ssh_url"
                    logx "repo creado y remote origin configurado: $ssh_url"
                    echo "[dedalo] ✔ repo creado en GitHub: $owner/$repo_name"
                    return 0
                fi
                echo "[dedalo] ⚠ no se pudo crear repo (respuesta API: $create_resp)" | tee -a "$LOG"
            fi
        else
            registrar_leccion \
                "GitHub: remote origin ausente" \
                "No hay gh autenticado ni GITHUB_TOKEN para crear repo automático." \
                "Crea el repo manualmente en GitHub y ejecuta: git remote add origin <url>"
            logx "lección registrada: remote origin ausente (sin credenciales)"
        fi
    fi
}

if [ -n "$PUSH" ]; then
    _asegurar_remote_origin
    PUSH_RAMA="${RAMA_TRABAJO:-$RAMA_RUN}"
    ORIGIN_URL="$(git -C "$PROYECTO" remote get-url origin 2>/dev/null)"
    if [ -n "$ORIGIN_URL" ]; then
        # Safeguard: never push the base branch (protected) by accident.
        if [ "$PUSH_RAMA" = "$RAMA_BASE" ] || [ "$PUSH_RAMA" = "master" ] || [ "$PUSH_RAMA" = "main" ]; then
            echo "[dedalo] ✗ push abortado: '$PUSH_RAMA' es la rama base; el trabajo debe ir en una rama dedalo/*." | tee -a "$LOG"
            logx "push abortado: '$PUSH_RAMA' es rama base"
        else
            # Visibility: make clear which remote it pushes to before doing it.
            echo "[dedalo] push → origin ($ORIGIN_URL) rama $PUSH_RAMA"
            logx "push: origin ($ORIGIN_URL) $PUSH_RAMA"
            if git -C "$PROYECTO" push -u origin "$PUSH_RAMA"; then
                logx "push: origin/$PUSH_RAMA"
                echo "[dedalo] ✔ push OK: origin/$PUSH_RAMA"
                echo "[dedalo] abre el PR de $PUSH_RAMA -> $RAMA_BASE"
            else
                echo "[dedalo] ⚠ falló el push a origin/$PUSH_RAMA. El trabajo queda local." | tee -a "$LOG"
            fi
        fi
    else
        echo "[dedalo] ℹ sin remote origin (repo no creado). Trabajo queda local." | tee -a "$LOG"
    fi
fi

echo ""
echo "== RESUMEN (final de progreso.log) =="
tail -25 "$LOG"
logx "== DEDALO FINALIZADO (iter=$iter, rama=$RAMA_RUN, costo≈$COSTO_TOTAL) =="
alerta "Dédalo finalizado"
exit 0