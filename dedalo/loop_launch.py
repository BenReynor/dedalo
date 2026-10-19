#!/usr/bin/env python3
"""Loop launch preparation (shared by the GUI and the MCP).

Extracts from app.py the building of the engine's COMMAND and ENVIRONMENT so
that the Qt panel and the MCP server (`dedalo.mcp_server`) launch the same
process with the same configuration. No PySide dependencies: the MCP
server imports this module without dragging in Qt.

The environment contract is that of dedalo.sh / loop.Config: same variables
MAX_ITER, AGENTE_TAREA, AGENTES_PREFERIDOS, MODELO_*, NAVEGADOR, REVISION_DUAL,
VOZ, MAX_COSTO, COSTO_POR_ITER, REVISION_MANUAL and CLI_<AGENTE>.

For security, the engine environment is not the caller's full environment: only
an allowlist of names crosses over (`filtrar_entorno`), so unrelated secrets
exported in the user's shell never reach the engine, the gate or the agents.
"""

import os
import sys

from . import configuracion as cfg
from . import modelos

# Environment variable for each agent CLI (dedalo.sh supports them).
MAPA_CLI = {
    "opencode": "CLI_OPENCODE",
    "codex": "CLI_CODEX",
    "claude": "CLI_CLAUDE",
}

# Environment ALLOWLIST: only these variables (and the names/dedalo keys added
# below) cross from the GUI/MCP into the engine and, from there, into the gate
# and the agent CLIs. Everything else the user may have exported in their shell
# (arbitrary secrets: AWS_*, DATABASE_URL, tokens for unrelated services…) is
# dropped, so a prompt-injected agent cannot exfiltrate it via `env`.
VARS_ENTORNO = frozenset({
    # Process / session basics.
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "PWD", "TMPDIR", "TEMP", "TMP",
    "LANG", "LANGUAGE", "TERM", "COLORTERM", "HOSTNAME", "TZ", "PYTHONPATH",
    # XDG and display: keyring (secret-service), notify-send and the agent TUI.
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME",
    "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "DISPLAY", "WAYLAND_DISPLAY",
    "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
    # Proxies and TLS.
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "all_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE",
    "REQUESTS_CA_BUNDLE", "GIT_SSL_CAINFO",
    # Git / SSH (push and auth).
    "GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS", "SSH_AUTH_SOCK",
    "SSH_AGENT_PID", "GITHUB_TOKEN", "GH_TOKEN", "GH_HOST",
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
    # Engine overrides that are not secrets.
    "MODELO_JUEZ", "TIMEOUT_JUEZ", "CRITERIO", "SKIP_RUFF",
    # Opt-in agent API keys (the agents normally keep their own session).
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY",
    "DEEPSEEK_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY", "XAI_API_KEY",
    "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "OLLAMA_HOST",
})

# Prefixes always allowed: the engine contract (DEDALO_*), the agent paths
# (CLI_*), the locale (LC_*) and the agent CLIs' own settings.
PREFIJOS_ENTORNO = ("DEDALO_", "CLI_", "LC_", "OPENCODE_", "CODEX_", "CLAUDE_")


def filtrar_entorno(environ):
    """Keeps only the allowlisted variables of `environ` (see `VARS_ENTORNO`).

    `DEDALO_ENTORNO_EXTRA` (space- or comma-separated names) adds more names
    for advanced setups, without touching the code.
    """
    extra = set()
    for trozo in environ.get("DEDALO_ENTORNO_EXTRA", "").replace(",", " ").split():
        extra.add(trozo)
    return {
        clave: valor
        for clave, valor in environ.items()
        if clave in VARS_ENTORNO or clave in extra
        or clave.startswith(PREFIJOS_ENTORNO)
    }


def raiz_codigo():
    """Repo root of the GUI: `dedalo` is a subdirectory of it."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def entorno_python(env, frozen=False):
    """Point PYTHONPATH at THIS framework checkout, replacing inherited entries.

    The engine and the gate start with cwd=<project>, where the `dedalo`
    package is not importable, so they need the framework root on the path.
    The inherited value is discarded on purpose: if the parent exported an old
    checkout (another copy of `dedalo`), it would be imported instead of the
    installed package and the engine would run stale code.
    """
    if frozen:
        env.pop("PYTHONPATH", None)
    else:
        env["PYTHONPATH"] = raiz_codigo()
    return env


def argv_motor(frozen, args):
    """Command (program, argv) that launches the loop engine.

    In the source code: `python -m dedalo.loop [args]`. In the
    PyInstaller binary `-m` does not resolve the module (it is packaged in the
    exe): the entrypoint interprets `--dedalo-loop` and calls
    `loop.main(argv[1:])`.
    """
    if frozen:
        return sys.executable, ["--dedalo-loop"] + list(args)
    return sys.executable, ["-m", "dedalo.loop"] + list(args)


def args_cli(conf):
    """Engine command-line arguments from the config."""
    args = []
    if conf.get("hasta"):
        args += ["--hasta", conf["hasta"]]
    if conf.get("padre"):
        args += ["--padre", conf["padre"]]
    if conf.get("trabajo"):
        args += ["--trabajo", conf["trabajo"]]
    if conf.get("push"):
        args.append("--push")
    return args


def resolver_agentes(conf, detectados):
    """(agente_tarea, agente_revisor) resolving "auto" with what was detected.

    A selector in "auto" is not the agent's name: it is resolved here with the
    same preference list dedalo.sh uses, so that the log and the
    launch reason match what actually runs.
    """
    auto = detectados[0] if detectados else ""
    tarea = auto if conf.get("agente_cli", cfg.AGENTE_DEFECTO) == "auto" \
        else conf["agente_cli"]
    revisor = auto if conf.get("revisor_cli", cfg.AGENTE_DEFECTO) == "auto" \
        else conf["revisor_cli"]
    return tarea, revisor


def construir_entorno(conf, nav, detectados, environ, frozen=None):
    """Environment (dict) for the engine process.

    `environ` is the base environment (the QProcess one in the GUI, os.environ
    in the MCP); it is passed through `filtrar_entorno`, so only the allowlisted
    variables reach the engine and the agents. `nav` = {"activo": bool,
    "modelo": str}. `detectados` is the list of operational agents
    (modelos.agentes_operativos()).
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    env = filtrar_entorno(environ)

    # The CLI agent is passed explicitly. If it is not in the PATH (e.g. GUI
    # opened without ~/.opencode/bin) its absolute path is resolved to CLI_<AGENTE>
    # (which dedalo.sh already supports) and its dir is added to the subprocess PATH.
    dirs_extra = set()
    for clave, var in MAPA_CLI.items():
        binario = modelos.ruta_binario(clave)
        if binario:
            env[var] = binario
            dirs_extra.add(os.path.dirname(binario))
    if dirs_extra:
        # os.pathsep: with a fixed ":" the loop's PATH got corrupted on Windows
        # (which separates with ";").
        env["PATH"] = os.pathsep.join(sorted(dirs_extra)) + (
            os.pathsep + env["PATH"] if env.get("PATH") else "")

    agente_tarea, agente_revisor = resolver_agentes(conf, detectados)
    env["MAX_ITER"] = str(conf.get("iteraciones", cfg.LAUNCH_DEFECTO["iteraciones"]))
    env["AGENTE_TAREA"] = agente_tarea
    env["AGENTE_REVISOR"] = agente_revisor
    # AGENTES_PREFERIDOS only with usable agents: if the reviewer is in
    # "auto", dedalo.sh looks for another one in this list, and it must not fall back
    # on a CLI installed but without a session (it would abort the loop).
    env["AGENTES_PREFERIDOS"] = " ".join(detectados)
    # The judge follows the task agent unless explicitly chosen.
    env["AGENTE_JUEZ"] = agente_tarea
    # Only pass MODELO_* if the selection is a full provider/model AND the agent
    # is opencode (codex and claude do not accept --model here).
    modelo_tarea = (conf.get("agente", "") if "/" in conf.get("agente", "")
                    and agente_tarea == "opencode" else "")
    modelo_revisor = (conf.get("revisor", "") if "/" in conf.get("revisor", "")
                      and agente_revisor == "opencode" else "")
    env["MODELO_TAREA"] = modelo_tarea
    env["MODELO_REVISOR"] = modelo_revisor
    env["NAVEGADOR"] = "1" if nav.get("activo") else "0"
    env["MODELO_NAVEGADOR"] = (nav.get("modelo") or "") if nav.get("activo") else ""
    env["REVISION_DUAL"] = "1" if conf.get("dual", True) else "0"
    env["VOZ"] = "1" if conf.get("voz", False) else "0"
    env["MAX_COSTO"] = str(conf.get("costo_max", 0))
    env["COSTO_POR_ITER"] = str(
        conf.get("costo_iter", cfg.LAUNCH_DEFECTO["costo_iter"]))
    env["REVISION_MANUAL"] = "1" if conf.get("revision_manual", False) else "0"
    return env


def preparar(conf, nav=None, environ=None, frozen=None, nombre="", origen=""):
    """Full engine launch plan.

    Returns a dict with:
      · detectados: usable CLI agents (empty ⇒ the caller aborts)
      · agente_tarea / agente_revisor / modelo_tarea / modelo_revisor
      · env: environment (dict) already with PATH, CLI_* and PYTHONPATH (if not frozen)
      · programa / argv: command to run

    `nombre` (registry key) and `origen` ("gui"/"mcp") are exported to the
    engine as `DEDALO_PROYECTO_NOMBRE`/`DEDALO_ORIGEN`: with them the engine
    registers itself in the shared loop registry (`loops_estado`) under the
    same name the panel uses, so both sides see the same running state.
    """
    if environ is None:
        environ = dict(os.environ)
    else:
        environ = dict(environ)
    nav = nav or {}
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))

    detectados = modelos.agentes_operativos()
    env = construir_entorno(conf, nav, detectados, environ, frozen)
    if nombre:
        env["DEDALO_PROYECTO_NOMBRE"] = str(nombre)
    if origen:
        env["DEDALO_ORIGEN"] = str(origen)
    entorno_python(env, frozen)
    agente_tarea, agente_revisor = resolver_agentes(conf, detectados)
    programa, argv = argv_motor(frozen, args_cli(conf))
    modelo_tarea = (conf.get("agente", "") if "/" in conf.get("agente", "")
                    and agente_tarea == "opencode" else "")
    modelo_revisor = (conf.get("revisor", "") if "/" in conf.get("revisor", "")
                      and agente_revisor == "opencode" else "")
    return {
        "detectados": detectados,
        "agente_tarea": agente_tarea,
        "agente_revisor": agente_revisor,
        "modelo_tarea": modelo_tarea,
        "modelo_revisor": modelo_revisor,
        "env": env,
        "programa": programa,
        "argv": argv,
    }


def config_de_proyecto(nombre):
    """Merged launch config (defaults + what was saved) of a project.

    The MCP server uses it to launch with the same settings the user
    left in the GUI (`proyectos[nombre]["config"]["lanzamiento"]`). Returns
    `(conf, nav)`, where nav replicates the GUI's `navegador_config()`.
    """
    from . import proyectos as proy

    local = proy.leer_config_proyecto(nombre)
    lanz = dict(cfg.LAUNCH_DEFECTO)
    lanz.update(local.get("lanzamiento") or {})
    lanz.setdefault("agente", "")
    lanz.setdefault("revisor", "")
    lanz.setdefault("agente_cli", cfg.AGENTE_DEFECTO)
    lanz.setdefault("revisor_cli", cfg.AGENTE_DEFECTO)
    lanz.setdefault("revision_manual", False)
    nav = {"activo": bool(lanz.get("nav")), "modelo": lanz.get("nav_modelo") or ""}
    return lanz, nav
