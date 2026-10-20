#!/usr/bin/env python3
"""Dédalo MCP (Model Context Protocol) server.

Exposes project state and loop actions (install, gate, start/stop, resolve manual
review) to an MCP client —e.g. a "pilot" agent— over stdio (JSON-RPC). It is a
non-Qt process: it only imports modules without PySide, so it can run headless.

Transport: stdio (no ports opened). Start:

    python -m dedalo.mcp_server

The loop's manual review is resolved by writing to
`<proyecto>/.dedalo_review/decision` (APPROVE / "REJECT <motivo>"), which is
exactly what `resolver_revision` does: the pilot agent takes the human's seat
when the loop pauses.

Security note: `iniciar_loop` launches the engine in the background with
`start_new_session=True` and its stdout/stderr go to /dev/null —NEVER to the
server's stdio, as that would corrupt the JSON-RPC channel.
"""

import json
import os
import subprocess
import sys

from . import (
    loop_launch,
    loop_proceso,
    loops_estado,
    modelos,
    net,
    plantillas,
    proyectos,
    rutas,
)
from .gate import argv_gate

try:
    from mcp.server.mcpserver import MCPServer
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "El servidor MCP necesita la dependencia opcional 'mcp'. "
        "Instálala con: pip install 'dedalo[mcp]'"
    ) from exc

# Curated program manual: delivered as `instructions` in initialize
# (context shown to MCP clients by the model) and as resource
# `dedalo://manual`. Embedded in the code so it's available in the
# packaged/frozen app where docs/ are not distributed.
MANUAL = """\
Dédalo is a desktop panel (PySide6) and an MCP server for orchestrating CLI
AI agents (opencode, codex, claude) that work autonomously on a project,
iterating task by task on `plan.md`.

HOW THE LOOP WORKS
- Takes the first pending task from `plan.md`, passes it to an agent and,
  after executing it, runs the project's "gate" (tests + lint).
- Only commits if the gate passes; if it fails, the iteration does not commit.
- With `revision_manual` active, the loop PAUSES before committing and waits for
  a decision (APPROVE / REJECT) from a human or a pilot agent.
- If there is no internet, the loop stops.

PROJECT FILES (same as exposed at dedalo://{nombre}/{fichero})
- plan.md ......... tasks: `- [ ]` pending, `- [x]` done, `- [B]` blocked.
- lecciones.md .... lessons accumulated across iterations.
- CONTEXTO.md ..... summary state / continuity notes.
- progreso.log .... iteration trace (text).
- metrics.jsonl ... metrics per iteration (one JSON line each).
- incidencias.jsonl structured incidents (one JSON line each).
- mapeo.txt ....... project map/index.

CONCEPTS
- "project": directory registered in Dédalo (name -> path).
- "gate": project verification command (tests + lint).
- "manual review": loop pause awaiting diff approval.
- "task agent" / "reviewer agent": CLIs assigned to execute and to review.

TYPICAL FLOW WITH THESE TOOLS
1. listar_proyectos / estado_proyecto: what's there and in what state.
2. leer_plan / leer_contexto / leer_lecciones / cola_log: context.
3. instalar_proyecto: create and register a new project (optional).
4. iniciar_loop: start the loop in background (returns pid).
5. estado_loop / cola_log: follow progress.
6. resolver_revision(APPROVE|REJECT): resolve a pending review.
7. correr_gate: validate manually; detener_loop: stop the loop.

The full text of this manual is in the resource `dedalo://manual`.
"""

mcp = MCPServer("dedalo", instructions=MANUAL)

# Files a client can read via resource dedalo://{name}/{file}.
FICHEROS_RECURSO = (
    "plan.md",
    "lecciones.md",
    "CONTEXTO.md",
    "progreso.log",
    "metrics.jsonl",
    "incidencias.jsonl",
    "mapeo.txt",
)

# Loops launched from THIS process: name → subprocess.Popen. The persisted
# state (pid/origin) lives in `loops_estado` and is shared with the GUI, so a
# restarted MCP server (or the GUI) can still see/stop it.
_LOOPS: dict[str, subprocess.Popen] = {}
RC_TIMEOUT_LOOP = loop_proceso.RC_TIMEOUT


def _json(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _ruta_de(nombre):
    """Project path in the registry (raises ValueError if it does not exist)."""
    proy = proyectos.cargar().get(nombre)
    if not proy or not proy.get("ruta"):
        raise ValueError(f"proyecto desconocido: {nombre!r}")
    return proy["ruta"]


def _leer_texto(ruta):
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _cola(texto, lineas):
    return "\n".join(texto.splitlines()[-lineas:])


def _leer_jsonl(ruta):
    """List of dicts from a .jsonl; ignores corrupt or empty lines."""
    if not os.path.isfile(ruta):
        return []
    datos = []
    with open(ruta, encoding="utf-8", errors="replace") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                obj = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                obj["_crudo"] = linea
                datos.append(obj)
    return datos


def _ruta_de_fichero(nombre, fichero):
    """Resolves a project file to its current location (`.dedalo/` or legacy)."""
    proyecto = _ruta_de(nombre)
    if fichero in rutas.PROYECTO or fichero == ".gitignore":
        return rutas.proyecto_archivo(proyecto, fichero)
    if fichero in rutas.ESTADO_LEGACY:
        return rutas.estado(proyecto, fichero)
    return os.path.join(proyecto, fichero)


def _estado_loop(nombre):
    """Dict with the project's loop state: running, pid, origin, pending review.

    The running state comes from `loops_estado`, the shared registry the GUI
    also reads/writes, so this reflects loops started by EITHER the MCP or the
    GUI (not just this process's own children).
    """
    est = loops_estado.estado(nombre)
    fondo = rutas.dir_review(_ruta_de(nombre))
    pendiente = os.path.isfile(os.path.join(fondo, "waiting"))
    tarea = ""
    tarea_ruta = os.path.join(fondo, "tarea.txt")
    if pendiente and os.path.isfile(tarea_ruta):
        try:
            with open(tarea_ruta, encoding="utf-8", errors="replace") as f:
                tarea = f.read().strip()
        except OSError:
            tarea = ""
    return {
        "nombre": nombre,
        "corriendo": est["corriendo"],
        "pid": est["pid"],
        "origen": est["origen"],
        "revision_pendiente": pendiente,
        "tarea_en_revision": tarea,
    }


# ---------------------------------------------------------------------------
# READ tools
# ---------------------------------------------------------------------------

def listar_proyectos() -> str:
    """Lists the registered projects: name, path and whether the path exists."""
    reg = proyectos.cargar()
    return json.dumps([
        {"nombre": n, "ruta": d.get("ruta", ""), "existe": os.path.isdir(d.get("ruta", ""))}
        for n, d in reg.items()
    ], ensure_ascii=False, indent=2)


def estado_proyecto(nombre: str) -> str:
    """Summary of a project: plan, lessons, context and loop state."""
    ruta = _ruta_de(nombre)
    from .plan import Plan as _Plan
    p = _Plan(rutas.proyecto_archivo(ruta, "plan.md"))
    p.cargar()
    pend, hechas, bloq = p.conteo()
    lecciones = rutas.proyecto_archivo(ruta, "lecciones.md")
    contexto = rutas.proyecto_archivo(ruta, "CONTEXTO.md")
    return json.dumps({
        "nombre": nombre,
        "ruta": ruta,
        "existe": os.path.isdir(ruta),
        "plan": {"pendientes": pend, "hechas": hechas, "bloqueadas": bloq},
        "lecciones": {"existe": os.path.isfile(lecciones),
                      "bytes": os.path.getsize(lecciones) if os.path.isfile(lecciones) else 0},
        "contexto": {"existe": os.path.isfile(contexto),
                     "bytes": os.path.getsize(contexto) if os.path.isfile(contexto) else 0},
        "loop": _estado_loop(nombre),
    }, ensure_ascii=False, indent=2)


def leer_fichero(nombre: str, fichero: str) -> str:
    """Returns the content of an allowed project file.

    `fichero` must be in the whitelist (plan.md, lecciones.md,
    CONTEXTO.md, progreso.log, metrics.jsonl, incidencias.jsonl, mapeo.txt).
    """
    if fichero not in FICHEROS_RECURSO:
        raise ValueError(
            f"fichero no permitido: {fichero!r}. Permitidos: {list(FICHEROS_RECURSO)}")
    return _leer_fichero(nombre, fichero)


def _leer_fichero(nombre, fichero):
    ruta = _ruta_de_fichero(nombre, fichero)
    if not os.path.isfile(ruta):
        return ""
    with open(ruta, encoding="utf-8", errors="replace") as f:
        return f.read()


def leer_incidencias(nombre: str, limite: int = 50) -> str:
    """Latest structured incidents (incidencias.jsonl) of the project."""
    datos = _leer_incidencias(nombre, limite)
    return json.dumps(datos, ensure_ascii=False, indent=2)


def _leer_incidencias(nombre, limite):
    ruta = _ruta_de_fichero(nombre, "incidencias.jsonl")
    incidencias = _leer_jsonl(ruta)
    for inc in incidencias:
        inc.pop("_crudo", None)
    return incidencias[-max(1, int(limite)):]


def resumen_metricas(nombre: str) -> str:
    """Project metrics summary (progreso.log + metrics.jsonl)."""
    from .metricas import parsear_log as _parsear
    ruta = _ruta_de_fichero(nombre, "progreso.log")
    datos = _parsear(ruta)
    return json.dumps({
        "resumen": datos.get("resumen", {}),
        "iteraciones": datos.get("iteraciones", [])[-25:],
    }, ensure_ascii=False, indent=2)


def cola_log(nombre: str, lineas: int = 60) -> str:
    """Last `lineas` lines of progreso.log."""
    ruta = _ruta_de_fichero(nombre, "progreso.log")
    if not os.path.isfile(ruta):
        return ""
    return _cola(_leer_fichero(nombre, "progreso.log"), lineas)


def estado_agentes() -> str:
    """State of each CLI agent: installed, path and whether it has a session."""
    return json.dumps(modelos.estado_agentes(), ensure_ascii=False, indent=2)


def listar_modelos() -> str:
    """Known models (opencode catalog) with the suggested one first."""
    return json.dumps({
        "sugerido": modelos.sugerido(modelos.lista_modelos()),
        "modelos": modelos.lista_modelos(),
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# ACTION tools
# ---------------------------------------------------------------------------

def instalar_proyecto(ruta: str, nombre: str = "") -> str:
    """Installs the templates in `ruta`, initializes git and registers the project."""
    ruta = os.path.abspath(os.path.expanduser(ruta))
    os.makedirs(ruta, exist_ok=True)
    creados = plantillas.instalar(ruta)
    git = plantillas.inicializar_git(ruta)
    nombre = (nombre or os.path.basename(ruta.rstrip(os.sep))).strip()
    proyectos.registrar(nombre, ruta)
    return json.dumps({"nombre": nombre, "ruta": ruta,
                       "creados": creados, "git": git},
                      ensure_ascii=False, indent=2)


def correr_gate(nombre: str, timeout_s: int = 1800) -> str:
    """Runs the project gate (blocking, with timeout) and returns its output."""
    ruta = _ruta_de(nombre)
    argv = argv_gate(getattr(sys, "frozen", False))
    env = loop_launch.filtrar_entorno(os.environ)
    loop_launch.entorno_python(env, getattr(sys, "frozen", False))
    try:
        out = subprocess.run(argv, cwd=ruta, env=env,
                             capture_output=True, text=True,
                             timeout=max(1, int(timeout_s)))
        return json.dumps({"rc": out.returncode, "stdout": out.stdout,
                           "stderr": out.stderr},
                          ensure_ascii=False, indent=2)
    except subprocess.TimeoutExpired as e:
        return json.dumps({"rc": -1, "timeout": True,
                           "stdout": (e.stdout or "") if isinstance(e.stdout, str) else "",
                           "stderr": (e.stderr or "") if isinstance(e.stderr, str) else ""},
                          ensure_ascii=False, indent=2)


def iniciar_loop(nombre: str) -> str:
    """Launches the loop in the background for the project (returns the pid)."""
    _ruta_de(nombre)
    if _estado_loop(nombre)["corriendo"]:
        return json.dumps({"iniciado": False, "motivo": "ya está corriendo",
                           **_estado_loop(nombre)}, ensure_ascii=False, indent=2)
    if not net.hay_internet():
        return json.dumps({"iniciado": False,
                           "motivo": "sin conexión a internet"},
                          ensure_ascii=False, indent=2)
    conf, nav = loop_launch.config_de_proyecto(nombre)
    plan = loop_launch.preparar(conf, nav, nombre=nombre, origen="mcp")
    if not plan["detectados"]:
        return json.dumps({"iniciado": False, "detectados": [],
                           "motivo": "ningún agente CLI con sesión"},
                          ensure_ascii=False, indent=2)
    proc = subprocess.Popen(
        [plan["programa"]] + plan["argv"], cwd=_ruta_de(nombre),
        env=plan["env"], stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=(os.name != "nt"))
    _LOOPS[nombre] = proc
    # Register immediately so the GUI (which reads the same file) sees the loop
    # even before the engine has finished booting; the engine re-registers
    # itself with the same pid once it holds its lock.
    loops_estado.registrar(nombre, proc.pid, origen="mcp")
    conf, _ = loop_launch.config_de_proyecto(nombre)
    return json.dumps({
        "nombre": nombre, "pid": proc.pid,
        "agente_tarea": plan["agente_tarea"],
        "agente_revisor": plan["agente_revisor"],
        "revision_manual": bool(conf.get("revision_manual")),
    }, ensure_ascii=False, indent=2)


def estado_loop(nombre: str) -> str:
    """Loop state: running, pid, pending manual review and its task."""
    return json.dumps(_estado_loop(nombre), ensure_ascii=False, indent=2)


def detener_loop(nombre: str, espera_s: int = 5) -> str:
    """Stops the project loop (TERM→KILL for its whole process group)."""
    estado = _estado_loop(nombre)
    if not estado["pid"]:
        return json.dumps({"nombre": nombre, "detenido": False,
                           "motivo": "no estaba corriendo"},
                          ensure_ascii=False, indent=2)
    proc = _LOOPS.pop(nombre, None)
    if proc and proc.poll() is None:
        loop_proceso.matar_grupo(proc, espera=max(0, int(espera_s)))
    else:
        loops_estado.matar(estado["pid"], espera=max(0, int(espera_s)))
    loops_estado.olvidar(nombre)
    return json.dumps({"nombre": nombre, "pid": estado["pid"], "detenido": True},
                      ensure_ascii=False, indent=2)


def resolver_revision(nombre: str, decision: str, motivo: str = "") -> str:
    """Resolves the pending manual review by writing `.dedalo_review/decision`.

    `decision`: "APPROVE" (accept the diff) or "REJECT" (reject; uses `motivo`).
    It is what lets a pilot agent take the human's seat when the
    loop pauses awaiting approval.

    The file carries a `# origen=mcp` marker so the loop can audit
    who decided and apply the `REVISION_APRUEBA_AGENTE` policy: by default
    (0) the loop IGNORES an APPROVE issued by an agent and keeps waiting for a
    person. With `REVISION_APRUEBA_AGENTE=1` the agent may approve.
    """
    decision = decision.strip().upper()
    if decision not in ("APPROVE", "REJECT"):
        raise ValueError("decision debe ser APPROVE o REJECT")
    fondo = rutas.dir_review(_ruta_de(nombre))
    os.makedirs(fondo, exist_ok=True)
    texto = ("APPROVE" if decision == "APPROVE"
             else "REJECT " + (motivo or "").strip()) + "\n# origen=mcp\n"
    destino = os.path.join(fondo, "decision")
    # 0o600: the decision is sensitive and only the same user's loop reads it.
    fd = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(texto)
    return json.dumps({"nombre": nombre, "decision": decision,
                       "detalle": texto.strip()}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Resources: dedalo://{nombre}/{fichero}
# ---------------------------------------------------------------------------

def leer_contexto(nombre: str) -> str:
    """Returns the content of the project's `CONTEXTO.md` (alias of leer_fichero)."""
    return _leer_fichero(nombre, "CONTEXTO.md")


def leer_plan(nombre: str) -> str:
    """Returns the content of the project's `plan.md`."""
    return _leer_fichero(nombre, "plan.md")


def leer_lecciones(nombre: str) -> str:
    """Returns the content of the project's `lecciones.md`."""
    return _leer_fichero(nombre, "lecciones.md")


def leer_recurso(nombre: str, fichero: str) -> str:
    """Content of an allowed project file (read via resource)."""
    if fichero not in FICHEROS_RECURSO:
        raise ValueError(f"fichero no permitido: {fichero!r}")
    return _leer_fichero(nombre, fichero)


def manual() -> str:
    """Dédalo manual: what the program is and how to use it (resource dedalo://manual)."""
    return MANUAL


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _registrar(server):
    for fn in (listar_proyectos, estado_proyecto, leer_fichero, leer_plan,
               leer_lecciones, leer_contexto, leer_incidencias, resumen_metricas,
               cola_log, estado_agentes, listar_modelos, instalar_proyecto,
               correr_gate, iniciar_loop, estado_loop, detener_loop,
               resolver_revision):
        server.tool()(fn)
    server.resource("dedalo://{nombre}/{fichero}",
                    name="fichero_proyecto",
                    description="Lee un fichero permitido del proyecto",
                    mime_type="text/markdown")(leer_recurso)
    server.resource("dedalo://manual",
                    name="manual",
                    title="Manual de Dédalo",
                    description="Qué es Dédalo y cómo usarlo",
                    mime_type="text/markdown")(manual)
    return server


_MCPSERVER = None


def servidor():
    """The MCPServer with the tools and resources registered (singleton)."""
    global _MCPSERVER
    if _MCPSERVER is None:
        from mcp.server.mcpserver import MCPServer
        _MCPSERVER = _registrar(MCPServer("dedalo", instructions=MANUAL))
    return _MCPSERVER


def main():
    """Starts the MCP server over stdio."""
    servidor().run(transport="stdio")


if __name__ == "__main__":
    main()
