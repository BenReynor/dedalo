# 98_criterio.py — Natural-language criteria JUDGE (goal-worker).
# Port of 98_criterio.sh for the portable orchestrator (Windows without bash).
#
# Dédalo extracts the "criterio: ..." line from the first pending task and
# exports it as CRITERIO. A judge (cheap model) evaluates whether it is met
# against the real state of the repo. Empty CRITERIO -> skipped.
#
# Configurable: CRITERIO, AGENTE_JUEZ (opencode|codex|claude|auto), MODELO_JUEZ,
# OPENCODE_AGENT_JUEZ, CLI_OPENCODE/CLI_CODEX/CLI_CLAUDE, AGENTE_TAREA,
# AGENTES_PREFERIDOS, TIMEOUT_JUEZ (def 120 s).
import os
import re
import shutil
import subprocess

CLIS = {
    "opencode": "CLI_OPENCODE",
    "codex": "CLI_CODEX",
    "claude": "CLI_CLAUDE",
}

# Cache of the `opencode run --dir` capability, per binary.
_DIR_SOPORTADO = {}


def _cli(agente):
    return os.environ.get(CLIS[agente], agente)


def _elegir_agente():
    agente = os.environ.get("AGENTE_JUEZ", "auto")
    if agente not in ("", "auto"):
        return agente
    tarea = os.environ.get("AGENTE_TAREA", "")
    cand = tarea if tarea and tarea != "auto" else ""
    preferidos = os.environ.get("AGENTES_PREFERIDOS", "opencode codex claude")
    for a in (cand + " " + preferidos).split():
        if not a or a == "auto" or a not in CLIS:
            continue
        if shutil.which(_cli(a)):
            return a
    return "opencode"


def _prompt(env, criterio):
    estado = ""
    try:
        p = subprocess.run(["git", "-C", env.proyecto, "status", "--porcelain"],
                           capture_output=True, text=True)
        if p.returncode == 0:
            estado = "\n".join(p.stdout.splitlines()[:30])
    except OSError:
        pass
    detectado = ""
    ruta_mapeo = os.path.join(env.proyecto, "mapeo.txt")
    if os.path.isfile(ruta_mapeo):
        with open(ruta_mapeo, encoding="utf-8", errors="replace") as f:
            cabeceras = [ln for ln in f.read().splitlines() if ln.startswith("# ")][:5]
        detectado = "\n".join(cabeceras)
    return (
        "Eres el JUEZ de una tarea de Dédalo. Evalúas si el CRITERIO de la "
        "tarea se cumple en el ESTADO ACTUAL del repo.\n"
        f"CRITERIO: {criterio}\n\n"
        "ESTADO ACTUAL (git status):\n"
        f"{estado or '<árbol limpio>'}\n\n"
        + (f"- Mapa del proyecto (mapeo.txt): \n{detectado}\n" if detectado else "")
        + "Corre los tests relevantes (pytest/vitest/npm test...) si el criterio "
        "lo exige y lee los archivos clave. NO modifiques nada: solo evalúa.\n\n"
        "Respondes ÚNICAMENTE con JSON en la última línea, sin markdown:\n"
        '{"met": true, "reason": "<por qué se cumple, máx 120 caracteres>"}   o\n'
        '{"met": false, "reason": "<qué falta, máx 120 caracteres>"}'
    )


def _soporta_dir(cli):
    """Does this `opencode run` accept `--dir`? Probed once, cached.

    Without `--dir`, `opencode run` attaches to an already-running opencode
    server and runs inside THAT server's directory (its project): the judge
    would evaluate the wrong repository. Older builds lack the flag.
    """
    global _DIR_SOPORTADO
    if cli in _DIR_SOPORTADO:
        return _DIR_SOPORTADO[cli]
    soportado = False
    try:
        p = subprocess.run([cli, "run", "--help"], capture_output=True,
                           text=True, timeout=20)
        soportado = "--dir" in (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        soportado = False
    _DIR_SOPORTADO[cli] = soportado
    return soportado


def _invocar(agente, cli, prompt, modelo, timeout, proyecto):
    if agente == "opencode":
        args = [cli, "run"]
        if proyecto and _soporta_dir(cli):
            args += ["--dir", proyecto]
        args += ["--agent", os.environ.get("OPENCODE_AGENT_JUEZ", "build")]
        if modelo:
            args += ["--model", modelo]
        args.append(prompt)
    elif agente == "codex":
        args = [cli, "exec", "--skip-git-repo-check"]
        args += os.environ.get("CODEX_FLAGS", "").split()
        args.append(prompt)
    else:  # claude
        args = [cli, "-p", "--output-format", "text"]
        args += os.environ.get("CLAUDE_FLAGS", "").split()
        args.append(prompt)
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout, cwd=proyecto or None)
        return (p.stdout or "") + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired:
        return "", 124
    except OSError:
        return "", 127


def run(env):
    criterio = os.environ.get("CRITERIO", "")
    if not criterio:
        env.aviso("sin CRITERIO (no hay línea 'criterio:' en la tarea), se omite el juez")
        return 0

    timeout = int(os.environ.get("TIMEOUT_JUEZ", "120") or 120)
    modelo = os.environ.get("MODELO_JUEZ", "opencode/nemotron-3.5-lightning-free")
    agente = _elegir_agente()
    cli = _cli(agente)

    if not shutil.which(cli):
        env.aviso(f"{agente} no disponible para el juez; se omite "
                  f"(CRITERIO='{criterio[:60]}…')")
        return 0
    if agente != "opencode":
        print(f"[GATE] juez: agente={agente} (MODELO_JUEZ no aplica a {agente})")

    salida, rc = _invocar(agente, cli, _prompt(env, criterio), modelo, timeout,
                          getattr(env, "proyecto", "") or "")
    if rc == 124:
        env.aviso(f"juez agotó el timeout ({timeout}s); se omite (no bloqueante)")
        return 0
    if rc != 0:
        env.aviso(f"juez salió con rc={rc} (¿cuota o red?); se omite (no bloqueante)")
        return 0

    m = re.findall(r'"met"\s*:\s*(true|false)', salida)
    if not m:
        m = re.findall(r"VERDICT\s*:\s*(PASS|FAIL)", salida)
    veredicto = m[-1] if m else ""
    r = re.findall(r'"reason"\s*:\s*"([^"]*)"', salida)
    razon = r[-1] if r else ""

    if "true" in veredicto or "PASS" in veredicto:
        print("[GATE] \u2713 juez: criterio cumplido" + (f" — {razon}" if razon else ""))
        return 0
    if "false" in veredicto or "FAIL" in veredicto:
        env.fail(f"juez: criterio NO cumplido ({razon or 'sin detalle'})")
        return 1
    env.aviso("juez sin veredicto legible; se omite (no bloqueante)")
    return 0
