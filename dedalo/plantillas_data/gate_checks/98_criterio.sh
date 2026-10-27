#!/usr/bin/env bash
# 98_criterio.sh — Natural-language criteria JUDGE (goal-worker pattern).
#
# Dédalo extracts the "criterio: ..." line from the first pending task in
# plan.md and exports it as CRITERIO. This check does NOT need per-project
# scripts: you write the condition in natural language and a judge (cheap
# model) evaluates it against the real state of the repo.
#
#   · Empty CRITERIO → skipped (normal deterministic gate).
#   · The judge uses opencode with MODELO_JUEZ (def: cheap model) and returns
#     {"met": true|false, "reason": "..."} or VERDICT: PASS/FAIL.
#   · Max 2 calls: if the judge cannot respond (quota/timeout), it fails
#     SOFT (⚠) so as not to block the loop because of the provider.
#
# Configurable via environment: CRITERIO, AGENTE_JUEZ (opencode|codex|claude|auto),
# MODELO_JUEZ (opencode only), OPENCODE_AGENT_JUEZ, CLI_OPENCODE/CLI_CODEX/
# CLI_CLAUDE, AGENTE_TAREA, AGENTES_PREFERIDOS, TIMEOUT_JUEZ (def 120 s).
set -uo pipefail

if [ -z "${CRITERIO:-}" ]; then
    echo "[GATE] ⚠ sin CRITERIO (no hay línea 'criterio:' en la tarea), se omite el juez"
    exit 0
fi

TIMEOUT_JUEZ="${TIMEOUT_JUEZ:-120}"
MODELO_JUEZ="${MODELO_JUEZ:-opencode/nemotron-3.5-lightning-free}"
OPENCODE_AGENT="${OPENCODE_AGENT_JUEZ:-build}"

# Judge agent: AGENTE_JUEZ (opencode|codex|claude|auto). "auto" and empty
# follow the task agent if its CLI is available, and otherwise the first
# available one. MODELO_JUEZ only applies to opencode.
AGENTE="${AGENTE_JUEZ:-auto}"
case "$AGENTE" in
    auto|"")
        if [ -n "${AGENTE_TAREA:-}" ] && [ "${AGENTE_TAREA}" != "auto" ]; then
            _cand="$AGENTE_TAREA"
        else
            _cand=""
        fi
        _pick=""
        for _a in $_cand ${AGENTES_PREFERIDOS:-opencode codex claude}; do
            [ -z "$_a" ] || [ "$_a" = "auto" ] && continue
            case "$_a" in
                opencode) _b="${CLI_OPENCODE:-opencode}" ;;
                codex)    _b="${CLI_CODEX:-codex}" ;;
                claude)   _b="${CLI_CLAUDE:-claude}" ;;
                *)        continue ;;
            esac
            command -v "$_b" >/dev/null 2>&1 && { _pick="$_a"; break; }
        done
        # _cand first ONLY if its CLI exists; otherwise fall back to the list.
        if [ -z "$_pick" ] && [ -n "$_cand" ]; then
            case "$_cand" in
                opencode) command -v "${CLI_OPENCODE:-opencode}" >/dev/null 2>&1 && _pick="$_cand" ;;
                codex)    command -v "${CLI_CODEX:-codex}" >/dev/null 2>&1 && _pick="$_cand" ;;
                claude)   command -v "${CLI_CLAUDE:-claude}" >/dev/null 2>&1 && _pick="$_cand" ;;
            esac
        fi
        AGENTE="${_pick:-opencode}"
        ;;
esac

case "$AGENTE" in
    opencode) CLI="${CLI_OPENCODE:-opencode}" ;;
    codex)    CLI="${CLI_CODEX:-codex}" ;;
    claude)   CLI="${CLI_CLAUDE:-claude}" ;;
    *)        CLI="${CLI_OPENCODE:-opencode}"; AGENTE="opencode" ;;
esac

if ! command -v "$CLI" >/dev/null 2>&1; then
    echo "[GATE] ⚠ $AGENTE no disponible para el juez; se omite (CRITERIO='${CRITERIO:0:60}…')"
    exit 0
fi
if [ "$AGENTE" != "opencode" ]; then
    echo "[GATE] juez: agente=$AGENTE (MODELO_JUEZ no aplica a $AGENTE)"
fi
GATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROYECTO_J="$GATE_DIR"
[ "$(basename "$PROYECTO_J")" = "gate_checks" ] && PROYECTO_J="$(dirname "$PROYECTO_J")"

# Current state of the repo: pending diff + located tests, so the judge
# evaluates against facts and not assumptions.
ESTADO=""
if git -C "$PROYECTO_J" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    ESTADO="$(git -C "$PROYECTO_J" status --porcelain | head -30)"
fi
DETECTADO=""
[ -f "$PROYECTO_J/mapeo.txt" ] && DETECTADO="$(grep -E '^# ' "$PROYECTO_J/mapeo.txt" | head -5)"

PROMPT_JUEZ="Eres el JUEZ de una tarea de Dédalo. Evalúas si el CRITERIO de la tarea se cumple en el ESTADO ACTUAL del repo.
CRITERIO: ${CRITERIO}

ESTADO ACTUAL (git status):
${ESTADO:-<árbol limpio>}

${DETECTADO:+- Mapa del proyecto (mapeo.txt): 
$DETECTADO
}
${GATE_CHECKS_OK:+Checks automáticos ya ejecutados en este gate: OK: ${GATE_CHECKS_OK}; fallaron: ${GATE_CHECKS_FALLO:--}.
}Si el criterio pide que compile, pasen los tests, tsc o el build, eso lo verifica el propio gate (lista de arriba y checks posteriores): no lo evalúes ni rechaces por no poder ejecutarlo. Lee los archivos clave y juzga el resto del criterio. NO modifiques nada: solo evalúa.

Respondes ÚNICAMENTE con JSON en la última línea, sin markdown:
{\"met\": true, \"reason\": \"<por qué se cumple, máx 120 caracteres>\"}   o
{\"met\": false, \"reason\": \"<qué falta, máx 120 caracteres>\"}"

# Portable time limit, same criterion as _timeout() in dedalo.sh:
# GNU timeout > gtimeout (Homebrew) > pure bash fallback (base macOS ships
# none of them and a direct `timeout` would exit with rc=127: the judge would
# always be skipped). The fallback returns 124 (like GNU) when the cap is hit.
_juez_timeout() {
    local segs="$1" pid i=0
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "$segs" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout "$segs" "$@"
    else
        "$@" &
        pid=$!
        while kill -0 "$pid" 2>/dev/null; do
            [ "$i" -ge "$segs" ] && break
            i=$((i + 1))
            sleep 1
        done
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
            return 124
        fi
        wait "$pid"
        return $?
    fi
}

# Invocation according to the judge's agent. The --model flag only exists in
# opencode; codex and claude are configured on their own and do not accept the
# flag, so MODELO_JUEZ is ignored for them.
# `--dir` pins the judge to the project: without it, `opencode run` attaches to
# an already-running opencode server and would evaluate ANOTHER repo (that
# server's project), giving a verdict about the wrong tree. Only added when
# this opencode build supports the flag.
DIR_ARGS=()
if [ "$AGENTE" = "opencode" ] && "$CLI" run --help 2>&1 | grep -q -- "--dir"; then
    DIR_ARGS=(--dir "$PROYECTO_J")
fi

run_juez() {
    case "$AGENTE" in
        opencode)
            if [ -n "$MODELO_JUEZ" ]; then
                _juez_timeout "$TIMEOUT_JUEZ" "$CLI" run \
                    ${DIR_ARGS[@]+"${DIR_ARGS[@]}"} \
                    --agent "$OPENCODE_AGENT" --model "$MODELO_JUEZ" "$PROMPT_JUEZ" 2>&1
            else
                _juez_timeout "$TIMEOUT_JUEZ" "$CLI" run \
                    ${DIR_ARGS[@]+"${DIR_ARGS[@]}"} \
                    --agent "$OPENCODE_AGENT" "$PROMPT_JUEZ" 2>&1
            fi
            ;;
        codex)
            # The flags go in an array: quoting "${CODEX_FLAGS:-}" would pass
            # an empty argument that the CLI would take as the prompt.
            local -a flags=()
            [ -n "${CODEX_FLAGS:-}" ] && read -r -a flags <<< "$CODEX_FLAGS"
            _juez_timeout "$TIMEOUT_JUEZ" "$CLI" exec --skip-git-repo-check \
                ${flags[@]+"${flags[@]}"} "$PROMPT_JUEZ" 2>&1
            ;;
        claude)
            local -a flags=()
            [ -n "${CLAUDE_FLAGS:-}" ] && read -r -a flags <<< "$CLAUDE_FLAGS"
            _juez_timeout "$TIMEOUT_JUEZ" "$CLI" -p --output-format text \
                ${flags[@]+"${flags[@]}"} "$PROMPT_JUEZ" 2>&1
            ;;
        *)
            _juez_timeout "$TIMEOUT_JUEZ" "$CLI" run --agent "$OPENCODE_AGENT" "$PROMPT_JUEZ" 2>&1
            ;;
    esac
}

SALIDA="$(run_juez)"
RC=$?

if [ "$RC" -eq 124 ]; then
    echo "[GATE] ⚠ juez agotó el timeout (${TIMEOUT_JUEZ}s); se omite (no bloqueante)"
    exit 0
fi
if [ "$RC" -ne 0 ]; then
    echo "[GATE] ⚠ juez salió con rc=$RC (¿cuota o red?); se omite (no bloqueante)"
    exit 0
fi

# Parse verdict: {"met": true|false} o VERDICT: PASS|FAIL
VEREDICTO="$(printf '%s\n' "$SALIDA" | grep -oE '"met"[[:space:]]*:[[:space:]]*(true|false)' | tail -1)"
if [ -z "$VEREDICTO" ]; then
    VEREDICTO="$(printf '%s\n' "$SALIDA" | grep -oE 'VERDICT[[:space:]]*:[[:space:]]*(PASS|FAIL)' | tail -1)"
fi
RAZON="$(printf '%s\n' "$SALIDA" | grep -oE '"reason"[[:space:]]*:[[:space:]]*"[^"]*"' | tail -1 | sed -E 's/"reason"[[:space:]]*:[[:space:]]*"//; s/"$//')"

case "$VEREDICTO" in
    *true*|*PASS*)
        echo "[GATE] ✓ juez: criterio cumplido{${RAZON:+ — $RAZON}}"
        exit 0
        ;;
    *false*|*FAIL*)
        echo "[GATE] ✗ juez: criterio NO cumplido (${RAZON:-sin detalle})"
        exit 1
        ;;
    *)
        echo "[GATE] ⚠ juez sin veredicto legible; se omite (no bloqueante)"
        exit 0
        ;;
esac