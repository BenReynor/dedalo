#!/usr/bin/env python3
"""Agents of the native loop (port of dedalo.sh): run the task,
navigator and reviewer agents; auth/token detection; metrics to
metrics.jsonl; reviewer selection. No PySide dependencies.

The `cfg` object is the Configuration defined in loop.py (reads the
environment like the script). Here only attributes are read, without importing
loop.py (no cycles).
"""

import datetime
import json
import os
import re
import shutil
import subprocess

from .loop_proceso import run_con_timeout
from .loop_util import ahora_ms, logx
from .modelos import ALIAS_CLAUDE

UTC = datetime.timezone.utc

# Cache of the `opencode run --dir` capability, per binary (probed once per process).
_DIR_SOPORTADO = {}

# HIGH-CONFIDENCE pattern of missing auth (no bare "401" nor
# "unauthorized" in narrative). Same as sin_autenticacion().
_PATRON_AUTH = re.compile(
    r"(Please run .*/login|Please run .* login|run .* auth login|"
    r"Authentication Error|authentication_error|invalid[ _.-]?api[ _.-]?key|"
    r"missing[ _.-]?api[ _.-]?key|401 Unauthorized|HTTP 401|"
    r"Please set your api key)", re.IGNORECASE)

# `.` stands for any separator (space, _, .), as in the grep -E it was ported from.
_PATRON_TOKENS = re.compile(
    r"insufficient_quota|rate_limit_exceeded|quota.exceeded|"
    r"credit.balance.is.too.low|billing.hard.limit|RESOURCE_EXHAUSTED|"
    r"tokens?.exhausted|out.of.tokens|no.quota|quota.depleted|"
    r"monthly.limit|usage.limit|requires.usage.credits|"
    r"usage.credits.to.continue", re.IGNORECASE)

_USAGE = re.compile(
    r"\"usage\":\s*\{[^}]*\"input_tokens\":\s*(\d+)[^}]*"
    r"\"output_tokens\":\s*(\d+)")


def cli_agente(agente, cfg):
    """Agent binary according to CLI_* (same as cli_agente())."""
    if agente == "opencode":
        return cfg.environ.get("CLI_OPENCODE") or "opencode"
    if agente == "codex":
        return cfg.environ.get("CLI_CODEX") or "codex"
    if agente == "claude":
        return cfg.environ.get("CLI_CLAUDE") or "claude"
    return ""


def agente_ok(agente, cfg):
    """Does the agent binary exist and is it executable? (command -v)."""
    binario = cli_agente(agente, cfg)
    if not binario:
        return False
    resolved = shutil.which(binario) if os.sep not in binario else binario
    return resolved is not None and os.access(resolved, os.X_OK)


def detectar_agente(cfg):
    """First available agent according to AGENTES_PREFERIDOS (opencode→codex→
    claude), same as the script."""
    for a in (cfg.agentes_preferidos or "opencode codex claude").split():
        if a == "auto":
            continue
        if agente_ok(a, cfg):
            return a
    return ""


def soporta_dir(binario, cwd=None):
    """Does `opencode run` accept `--dir`? Probed once and cached per binary.

    Without `--dir`, `opencode run` attaches to an already-running opencode
    server and executes inside THAT server's directory (its project), ignoring
    the cwd we pass: the agent would read and modify the wrong repository. With
    `--dir <proyecto>` the run always targets the project we intend. Older
    opencode builds lack the flag, so it is only added when the help lists it.
    """
    if binario in _DIR_SOPORTADO:
        return _DIR_SOPORTADO[binario]
    soportado = False
    try:
        p = subprocess.run([binario, "run", "--help"], capture_output=True,
                           text=True, timeout=20, cwd=cwd or None)
        soportado = "--dir" in (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        soportado = False
    _DIR_SOPORTADO[binario] = soportado
    return soportado


def _argv_opencode(binario, cfg, subagente, modelo, prompt, dir_trabajo=None):
    """argv for `opencode run`, pinning the working directory to the project.

    Both the task agent and the reviewer go through here; the navigator builds
    its own argv but follows the same rule. `dir_trabajo` lets the ficha
    observer run in an isolated temporary directory instead of the repo.
    """
    directorio = dir_trabajo or cfg.proyecto
    args = [binario, "run", "--agent", subagente]
    if soporta_dir(binario, directorio or None):
        args += ["--dir", directorio]
    if modelo:
        args += ["--model", modelo]
    args.append(prompt)
    return args


# Commands the claude TASK agent may run without asking, per gate template.
# git is never allowed: the loop owns branches and commits.
CLAUDE_BASH_POR_PLANTILLA = {
    "python": ("pytest", "python", "python3", "ruff"),
    "node": ("npm", "npx", "node"),
    "web": ("node",),
    "rust": ("cargo",),
    "go": ("go", "gofmt"),
    "java": ("mvn", "gradle"),
    "kotlin": ("gradle",),
    "csharp": ("dotnet",),
    "cpp": ("cmake", "make", "ctest"),
    "shell": ("bash", "shellcheck"),
    "ruby": ("bundle", "ruby", "rspec", "rake"),
    "php": ("php", "composer"),
    "swift": ("swift",),
    "dart": ("dart", "flutter"),
}
# Tools denied to read-only roles (reviewer, judge, navigator, ficha).
CLAUDE_SOLO_LECTURA = ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash")


def modelo_claude(seleccion):
    """Model id for `claude --model`, or "" if the selection is not Claude's.

    Accepts the aliases (haiku/sonnet/opus), `anthropic/<id>` from the model
    selector and bare `claude-*` ids. Anything else (e.g. `opencode/...`) is
    ignored so the CLI falls back to its own default.
    """
    sel = (seleccion or "").strip()
    if sel.startswith("anthropic/"):
        sel = sel.split("/", 1)[1]
    if sel in ALIAS_CLAUDE or sel.startswith("claude-"):
        return sel
    return ""


def bash_permitidos(proyecto):
    """Bash commands for the task agent, from the project's gate templates."""
    from . import plantillas

    stacks = plantillas.plantillas_de(proyecto) or plantillas.detectar_stacks(proyecto)
    cmds = []
    for stack in stacks:
        for c in CLAUDE_BASH_POR_PLANTILLA.get(stack, ()):
            if c not in cmds:
                cmds.append(c)
    return cmds


def flags_claude(rol, proyecto="", modelo="", extra=""):
    """claude -p flags for a role: "tarea" may edit, any other is read-only.

    Every role runs with `--strict-mcp-config` so the nested agent never loads
    the user's MCP servers (tokens, and it must not drive its own loop). The
    list always ends in a non-variadic option so a positional prompt, as the
    judge passes it, is never swallowed by `--allowedTools`.
    """
    flags = ["--strict-mcp-config"]
    if rol == "tarea":
        cmds = bash_permitidos(proyecto) if proyecto else []
        if cmds:
            flags += ["--allowedTools", *[f"Bash({c}:*)" for c in cmds]]
        flags += (extra or "").split()
        flags += ["--permission-mode", "acceptEdits"]
    else:
        flags += ["--disallowedTools", *CLAUDE_SOLO_LECTURA]
        flags += ["--permission-mode", "default"]
    modelo = modelo_claude(modelo)
    if modelo:
        flags += ["--model", modelo]
    return flags


def argv_claude(binario, cfg, rol, modelo=""):
    """argv for `claude -p`; the prompt goes through stdin (see run_agente)."""
    return [binario, "-p", "--output-format", "text",
            *flags_claude(rol, cfg.proyecto, modelo,
                          cfg.environ.get("CLAUDE_FLAGS", ""))]


def elegir_revisor(cfg):
    """Reviewer: preferred if it is a concrete one; if it is "auto"/empty,
    another agent different from the task one; as a last resort, the same one."""
    tarea = cfg.agente_tarea or ""
    preferido = cfg.agente_revisor or ""
    if preferido and preferido != "auto":
        if agente_ok(preferido, cfg):
            return preferido
    for a in (cfg.agentes_preferidos or "opencode codex claude").split():
        if not a or a == "auto":
            continue
        if agente_ok(a, cfg) and a != tarea:
            return a
    if tarea and agente_ok(tarea, cfg):
        return tarea
    return ""


def sin_autenticacion(stderr_file, stdout_file, corroborar):
    """REAL auth suspicion: pattern in full stderr or in the last 40
    lines of stdout, corroborated with a no-work iteration."""

    def _detecta(ruta, slceroh=False, cola=40):
        try:
            with open(ruta, encoding="utf-8", errors="replace") as f:
                if cola is None:
                    texto = f.read()
                else:
                    texto = "".join(f.readlines()[-cola:])
        except OSError:
            return False
        return bool(_PATRON_AUTH.search(texto))

    detectado = (_detecta(stderr_file, cola=None)  # full stderr
                 or (stdout_file and os.path.exists(stdout_file)
                     and _detecta(stdout_file, cola=40)))
    return detectado and bool(corroborar)


def tokens_agotados(archivo):
    """Does the agent output indicate exhausted quota/tokens? (grep -qiE)."""
    try:
        with open(archivo, encoding="utf-8", errors="replace") as f:
            texto = f.read()
    except OSError:
        return False
    return bool(_PATRON_TOKENS.search(texto))


def costo_por_modelo(modelo, tokens_in, tokens_out):
    """Same case (model → rate) as the script's _registrar_metrica
    (USD, unscaled; the %.6f is done by whoever writes the metric)."""
    if any(m in (modelo or "") for m in ("opus", "sonnet", "haiku")):
        return (tokens_in * 15 + tokens_out * 75) / 1_000_000
    if "gpt-4" in (modelo or "") or "gpt-4o" in (modelo or ""):
        return (tokens_in * 30 + tokens_out * 60) / 1_000_000
    if "gpt-3.5" in (modelo or ""):
        return (tokens_in * 0.5 + tokens_out * 1.5) / 1_000_000
    return (tokens_in * 1 + tokens_out * 3) / 1_000_000


def _leer_fichero(ruta):
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def extraer_tokens(texto, agente):
    """(tokens_in, tokens_out) from the output, like the script's grep does."""
    tin = tout = 0
    if agente == "codex":
        m = list(re.finditer(r"tokens_used:\s*(\d+)", texto))
        if m:
            tout = int(m[-1].group(1))
        return tin, tout
    usos = list(_USAGE.finditer(texto))
    if usos:
        m = usos[-1]  # tail -1
        tin, tout = int(m.group(1)), int(m.group(2))
    return tin, tout


def registrar_metrica(cfg, agente, modelo, dur_ms, rc, salida, tarea, iteracion,
                      fase=""):
    """Append of a line to metrics.jsonl (6 decimals and UTC ts, like the
    script's printf; without depending on the locale)."""
    texto = _leer_fichero(salida)
    tin, tout = extraer_tokens(texto, agente)
    costo = costo_por_modelo(modelo, tin, tout)
    ts = datetime.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    datos = {
        "ts": ts, "iter": int(iteracion), "agente": agente,
        "modelo": modelo or "default", "dur_ms": int(dur_ms), "rc": int(rc),
        "tokens_in": int(tin), "tokens_out": int(tout),
        "costo_usd": round(costo, 6), "tarea": tarea,
    }
    if fase:
        datos["fase"] = fase
    linea = json.dumps(datos, ensure_ascii=False)
    try:
        with open(cfg.metrics, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass


def run_agente(cfg, agente, salida, modelo, prompt, tarea, iteracion, *,
               cwd=None, timeout=None, dir_trabajo=None, fase="", env=None,
               rol="tarea"):
    """Runs a task with an agent and returns its exit code (run_agente).

    Opens the output files (stdout/salida, stderr/salida.err) like the
    `> "$salida" 2> "$salida_err"` redirect of the script, records the metric
    and passes the proc to `vivo` so the signals kill it. Returns
    (rc, agente_pid_dict).

    `cwd`/`timeout`/`dir_trabajo` are used by the ficha observer to run in a
    temporary directory, without the real repo and with a shorter timeout.
    """
    agente = (agente or cfg.agente_tarea or "").strip()
    if not agente or agente == "auto":
        agente = detectar_agente(cfg) or ""
    binario = cli_agente(agente, cfg)
    if not binario or not agente_ok(agente, cfg):
        logx(cfg.log, f"ABORTADO: agente no disponible ({agente})")
        return 2, None
    flags = (cfg.environ.get("CODEX_FLAGS") or "").split() \
        if agente == "codex" else []
    entrada = None
    if agente == "opencode":
        cmd = _argv_opencode(
            binario, cfg,
            cfg.environ.get("OPENCODE_AGENT_TAREA") or "build", modelo, prompt,
            dir_trabajo=dir_trabajo)
    elif agente == "codex":
        cmd = [binario, "exec", "--skip-git-repo-check",
               *flags, prompt]
    elif agente == "claude":
        cmd = argv_claude(binario, cfg, rol, modelo)
        entrada = prompt.encode("utf-8")
    else:
        logx(cfg.log, f"ABORTADO: agente desconocido ({agente})")
        return 2, None

    salida_err = salida + ".err"
    vivo = {}
    t0 = ahora_ms()
    entorno = env if env is not None else cfg.environ
    with open(salida, "wb") as fout, open(salida_err, "wb") as ferr:
        rc, _salida, _t = run_con_timeout(
            cmd, timeout or cfg.timeout_por_tarea, env=entorno,
            cwd=cwd or cfg.proyecto, stdout=fout, stderr=ferr, vivo=vivo,
            entrada=entrada)
    dur = ahora_ms() - t0
    registrar_metrica(cfg, agente, modelo, dur, rc, salida, tarea, iteracion,
                      fase=fase)
    return rc, vivo


def run_navegador(cfg, salida, modelo, tarea, agente):
    """Context navigator prior to the task; agent rc (run_navegador).
    A failure here only means less context: it does not abort the loop."""
    binario = cli_agente(agente, cfg)
    if not binario or not agente_ok(agente, cfg):
        return 1, {}
    prompt = (f"Tarea: {tarea}\n"
              f"Repo: {cfg.proyecto}\n"
              "Encuentra archivos, tests y endpoints relevantes. Lista concisa "
              "(máx 30 líneas):\n"
              "ARCHIVOS: ruta/archivo.py\n"
              "TESTS: ruta/test.py::test_x\n"
              "ENDPOINTS: GET /api/...\n"
              "MODELOS: Modulo.servicio")
    entrada = None
    if agente == "opencode":
        cmd = _argv_opencode(
            binario, cfg,
            cfg.environ.get("OPENCODE_AGENT_NAV") or "navigate", modelo, prompt)
    elif agente == "codex":
        cmd = [binario, "exec", "--skip-git-repo-check", prompt]
    elif agente == "claude":
        cmd = argv_claude(binario, cfg, "lectura", modelo)
        entrada = prompt.encode("utf-8")
    else:
        return 1, {}
    salida_err = salida + ".err"
    vivo = {}
    t0 = ahora_ms()
    with open(salida, "wb") as fout, open(salida_err, "wb") as ferr:
        rc, _s, _t = run_con_timeout(
            cmd, cfg.timeout_navegador, env=cfg.environ, cwd=cfg.proyecto,
            stdout=fout, stderr=ferr, vivo=vivo, entrada=entrada)
    dur = ahora_ms() - t0
    registrar_metrica(cfg, agente, modelo, dur, rc, salida, tarea, 0)
    return rc, vivo


def revisar_diff(cfg, rev, tarea, vdiff):
    """Dual reviewer of the diff (revisar_diff + script tail).

    Returns (result, feedback):
      result: "pass" | "fail" | "sin_auth" | "sin_tokens"
      feedback:  reasons prior to the VERDICT (to inject into the next
                 attempt) when fail.
    """
    rev_out = cfg.tmp("rev_out")
    ruta_ctx = getattr(cfg, "contexto", "")
    contexto = _leer_fichero(ruta_ctx).strip() if ruta_ctx else ""
    contexto_block = (f"Contexto del proyecto (respétalo al juzgar):\n"
                      f"{contexto}\n\n" if contexto else "")
    prompt = ("Eres el REVISOR en modo dedalo. Usa únicamente las skills "
              "que tu sesión ya tenga cargadas; no intentes cargar ninguna otra.\n"
              "Revisas el diff COMPLETO de una tarea, en frío, sin haber "
              "participado de ella.\n"
              f"{contexto_block}"
              f"Tarea: {tarea}\n\n{vdiff}\n\n"
              "Evalúa SOLO: (1) la tarea satisface su criterio, (2) no rompe "
              "nada obvio del proyecto,\n(3) sin secretos, (4) sin scope creep "
              "(cambios ajenos a la tarea).\n"
              "Responde con 2 o 3 líneas de razones y, EN LA ÚLTIMA LÍNEA, "
              "exactamente: VERDICT: PASS o VERDICT: FAIL")
    rc, _vivo = run_agente(cfg, rev, rev_out, cfg.modelo_revisor,
                           prompt, tarea, 0, rol="revisor")
    texto = _leer_fichero(rev_out)
    sin_veredicto = "VERDICT:" not in texto
    if sin_autenticacion(rev_out + ".err", rev_out, int(sin_veredicto)):
        logx(cfg.log, f"ABORTADO: revisor sin autenticacion ({rev})")
        return "sin_auth", None
    if (tokens_agotados(rev_out + ".err")
            or (sin_veredicto and tokens_agotados(rev_out))):
        logx(cfg.log, "ABORTADO: tokens/cuota agotados (revisor)")
        return "sin_tokens", None
    if re.search(r"VERDICT:\s*PASS", texto):
        return "pass", None
    veredicto = ""
    for linea in reversed(texto.splitlines()):
        if re.search(r"VERDICT:", linea):
            veredicto = linea
            break
    razones = [li for li in texto.splitlines()
               if re.search(r"VERDICT:", li) is None]
    feedback = " ".join(li for li in razones if li.strip()).strip()
    return "fail", feedback or (veredicto or "sin veredicto claro")
