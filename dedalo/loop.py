#!/usr/bin/env python3
"""Dedalo loop engine in Python (port of dedalo.sh, W2 F3).

Replaces the bash script while keeping the SAME log contract (the GUI parses
it with metricas.py regexes) and the same observable behavior. The gate runs as
a portable Python subprocess (dedalo.gate): it runs .py checks and delegates
.sh checks to bash if available (so on Unix the usual behavior is preserved and
on Windows it works without Git Bash). gate.sh and gate_checks/ remain framework
code.

Usage (direct and from the GUI; current directory = project):
    python -m dedalo.loop [plan.md] [--hasta HH:MM] [--push]
                                  [--padre rama] [--trabajo rama]

No PySide dependencies (no loop_* imports Qt): the engine runs even on Windows
with the same Python that packages the GUI, without Git Bash.
"""

import filecmp
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from . import (
    consentimiento,
    ficha,
    loop_launch,
    loops_estado,
    mapeo,
    net,
    notificaciones,
    rutas,
)
from .gate import argv_gate
from .loop_agentes import (
    agente_ok,
    bash_permitidos,
    cli_agente,
    detectar_agente,
    elegir_revisor,
    modelo_claude,
    revisar_diff,
    run_agente,
    run_navegador,
    sin_autenticacion,
    tokens_agotados,
)
from .loop_args import parse_args
from .loop_git import (
    borrar_rama,
    cambios_entre,
    checkout,
    commit_tarea,
    diff_para_revisor,
    merge_ff,
    preparar_ramas,
    rama_existe,
    registrar_leccion,
    revertir,
    run_git,
    snapshot,
)
from .loop_proceso import limpiar_sesiones, matar_grupo, run_con_timeout
from .loop_util import ahora_ms, alerta, hora_limite, incidencia, logx, suma_coste
from .plan import Plan

GATE_TIMEOUT = 43200  # 12 h: the bash gate has no cap of its own (like the script)
HIJO = {"proc": None}  # current agent/gate process (the signals kill it)
_RECHAZO_MOTIVO = {"txt": ""}  # global variable in the style of the script's ${RECHAZO_MOTIVO}


class Config:
    """Configuration of the run read from the environment (same defaults as the
    script). Instantiated in main() and passed to all functions."""

    def __init__(self, args, environ=None, proyecto=None):
        env = environ if environ is not None else os.environ
        self.environ = env
        self.proyecto = str(proyecto) if proyecto else os.getcwd()
        self.plan_md = args.plan
        self.gate = rutas.gate_sh(self.proyecto)
        self.mapear = rutas.mapear_sh(self.proyecto)
        self.mapa = rutas.mapeo(self.proyecto)
        self.log = rutas.log(self.proyecto)
        self.lecciones = rutas.proyecto_archivo(self.proyecto, "lecciones.md")
        self.contexto = rutas.proyecto_archivo(self.proyecto, "CONTEXTO.md")
        self.incidencias = rutas.incidencias(self.proyecto)
        self.metrics = rutas.metrics(self.proyecto)
        self.ultimo_motivo = None  # dict of the last failure of the current task

        self.max_iter = int(env.get("MAX_ITER", "40"))
        self.timeout_por_tarea = int(env.get("TIMEOUT_POR_TAREA", "900"))
        self.timeout_navegador = int(env.get("TIMEOUT_NAVEGADOR", "60"))
        self.max_reintentos = 2  # hardcoded in the script (not passed via env)
        self.agente_tarea = env.get("AGENTE_TAREA", "") or ""
        self.agentes_preferidos = env.get("AGENTES_PREFERIDOS",
                                          "opencode codex claude") or ""
        self.modelo_tarea = env.get("MODELO_TAREA", "") or ""
        self.modelo_navegador = env.get("MODELO_NAVEGADOR",
                                        "opencode/big-pickle") or ""
        self.navegador = env.get("NAVEGADOR", "0")
        self.agente_revisor = env.get("AGENTE_REVISOR", "") or ""
        self.revisor = ""  # resolved in run() (elegir_revisor)
        self.modelo_revisor = env.get("MODELO_REVISOR", "") or ""
        self.modelo_juez = env.get(
            "MODELO_JUEZ", "opencode/nemotron-3.5-lightning-free") or ""
        self.opencode_agente_juez = env.get("OPENCODE_AGENT_JUEZ", "build") or ""
        self.revision_dual = env.get("REVISION_DUAL", "1")
        self.revision_manual = env.get("REVISION_MANUAL", "0")
        self.timeout_revision_manual = int(
            env.get("TIMEOUT_REVISION_MANUAL", "1800"))
        # Security: an agent (MCP origin) may only APPROVE its own diff when
        # explicitly opted in. Default is safe: agent approvals are ignored.
        self.revision_aprueba_agente = env.get("REVISION_APRUEBA_AGENTE", "0")
        # Opt-in JSON ficha per accepted task. Off by default: it costs an
        # extra agent call, so the GUI must enable it explicitly per project.
        self.ficha_activa = env.get("FICHA_ACTIVA", "0")
        self.agente_ficha = env.get("AGENTE_FICHA", "auto") or "auto"
        self.modelo_ficha = env.get("MODELO_FICHA", "") or ""
        self.timeout_ficha = int(env.get("TIMEOUT_FICHA", "120"))
        # Pause before rerunning a gate whose judge did not answer (network).
        self.espera_juez = float(env.get("ESPERA_JUEZ", "10"))
        self.ficha_max_diff = int(env.get("FICHA_MAX_DIFF", "12000"))
        self.ficha_max_salida = int(env.get("FICHA_MAX_SALIDA", "20000"))
        self.ficha_diff_completo = env.get("FICHA_DIFF_COMPLETO", "0") == "1"
        fichas_dir = (env.get("FICHAS_DIR") or rutas.dir_fichas(self.proyecto))
        if not os.path.isabs(fichas_dir):
            fichas_dir = os.path.join(self.proyecto, fichas_dir)
        self.fichas_dir = fichas_dir
        self.fichas_index = os.path.join(fichas_dir, "index.jsonl")
        self.voz = env.get("VOZ", "0")
        self.max_costo = float(env.get("MAX_COSTO", "0") or 0)
        self.costo_por_iter = env.get("COSTO_POR_ITER", "0.50")
        self.rama_base = args.padre or env.get("RAMA_BASE", "master") or "master"
        self.push = args.push
        self.hasta = args.hasta or ""
        self.rama_trabajo = args.trabajo or ""
        self.inicio_ms = ahora_ms()
        # Shared loop registry identity (set by the GUI/MCP launchers). Without
        # a name, fall back to the project folder name so a manual
        # `python -m dedalo.loop` also registers itself.
        self.nombre = (env.get("DEDALO_PROYECTO_NOMBRE")
                       or os.path.basename(self.proyecto.rstrip("/\\")) or "")
        self.origen = env.get("DEDALO_ORIGEN", "cli") or "cli"

    def tmp(self, sufijo=""):
        """New temporary path (equivalent to mktemp; unique per call)."""
        fd, ruta = tempfile.mkstemp(suffix=("-" + sufijo if sufijo else ""))
        os.close(fd)
        return ruta


def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _append_log(cfg, texto):
    """Equivalent to `cat << EOF >> "$LOG"` (without timestamp, raw)."""
    try:
        with open(cfg.log, "a", encoding="utf-8") as f:
            f.write(texto if texto.endswith("\n") else texto + "\n")
    except OSError:
        pass


def _incidencia(cfg, tipo, motivo, tarea="", iteracion=0, rama=""):
    """Records a structured incident and remembers the last reason.

    `incidencias.jsonl` is independent of `progreso.log` (prose): one
    JSON line per failure/abort, for the GUI's incidents panel and final
    summary. `cfg.ultimo_motivo` allows a blocked task to inherit the real
    reason for its last failure (gate/reviewer), instead of a generic text."""
    incidencia(cfg.incidencias, tipo, motivo, tarea, iteracion, rama)
    cfg.ultimo_motivo = {"tipo": tipo, "motivo": motivo or "",
                         "iteracion": iteracion, "tarea": tarea or ""}


def mensaje(cfg, s):
    """Equivalent to `echo "<s>" | tee -a "$LOG"` of the script: console + log."""
    print(s)
    _append_log(cfg, s)


def _proteger_salidas():
    """In a --windowed binary (Windows), sys.stdout/stderr can be None and the
    first print() would crash. They are redirected to devnull; what matters (the
    log with timestamp) already goes to progreso.log. No-op when a console exists.

    With an inherited console (Git Bash/cmd/PowerShell on Windows) the streams
    are not None but their encoding is the locale (cp1252) and the first ✗ of
    the engine died with UnicodeEncodeError: they are switched to utf-8 with
    errors="replace" so no print kills the process."""
    for nombre in ("stdout", "stderr"):
        s = getattr(sys, nombre, None)
        if s is None:
            setattr(sys, nombre, open(
                os.devnull, "w", encoding="utf-8", errors="replace"))
        elif hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def rama_run_nombre():
    """`dedalo/$(date +%Y-%m-%d_%H-%M-%S)` from the script."""
    return "dedalo/" + time.strftime("%Y-%m-%d_%H-%M-%S")


# Times the gate is rerun when the judge could not give an opinion.
REINTENTOS_JUEZ = 2
# "[GATE] ⚠" lines of 98_criterio (.py and .sh) meaning the judge did not judge.
_JUEZ_SIN_OPINION = re.compile(
    r"\[GATE\] ⚠ (juez agotó el timeout[^;]*|juez salió con rc=\d+"
    r"|juez sin veredicto legible|\S+ no disponible para el juez"
    r"|sin CRITERIO)")


def _juez_no_opino(salida_gate):
    """Why the judge gave no verdict (short text), or "" if it did judge.

    98_criterio only warns in those cases ("no bloqueante") so a manual gate
    run is not blocked by a flaky judge; the loop must not take that as a
    pass, or a task is marked done with its criterio never checked.
    """
    m = _JUEZ_SIN_OPINION.search(salida_gate or "")
    return m.group(1) if m else ""


_ANSI = re.compile(r"\x1b(\[[0-9;?]*[A-Za-z]|\([AB0-2])")
_RUIDO_GATE = re.compile(r"^\[GATE\] (✓|⚠|❌|✗ \S+: \S+ falló$)")
_LINEA_ERROR = re.compile(r"\berror\b|✗|FAILED|panicked", re.I)


def _resumen_gate(salida, limite=1200):
    """Retry feedback from a failed gate: error lines first, then the tail.

    Only the tail used to be kept, so a Rust/TS failure reached the agent as
    "cargo check falló" plus the per-check recap, without the error itself.
    """
    lineas = [_ANSI.sub("", li).strip() for li in salida.splitlines()]
    utiles = [li for li in lineas if li and not _RUIDO_GATE.match(li)]
    errores = [li for li in utiles if _LINEA_ERROR.search(li)]
    return " ".join(dict.fromkeys(errores + utiles[-15:]))[:limite]

def _checks_del_gate(cfg, rel_scripts):
    """Prompt line naming the gate checks, so the agent verifies the same way.

    Without it the agent checked with its own commands (e.g. `python -m
    pytest`, which adds the cwd to sys.path) and handed over work the gate's
    plain `pytest` rejected.
    """
    try:
        nombres = os.listdir(rutas.gate_checks(cfg.proyecto))
    except OSError:
        return ""
    checks = sorted({os.path.splitext(n)[0] for n in nombres
                     if n.endswith((".py", ".sh")) and not n.startswith("_")})
    if not checks:
        return ""
    return (f"El gate correrá estos checks ({rel_scripts}/gate_checks/): "
            f"{', '.join(checks)}. Léelos y verifica tu trabajo con sus mismos "
            "comandos antes de terminar.\n")


def _comandos_permitidos(cfg):
    """Prompt line with the Bash commands Claude's task role may run.

    Claude's allowlist matches the command prefix (`Bash(cargo:*)`), so
    `source ~/.cargo/env && cargo …`, `PATH=… cargo` or an absolute path all
    asked for approval nobody gives in -p mode: the agent never compiled and
    handed in code that did not build (seen on ARGUS).
    """
    if cfg.agente_tarea != "claude":
        return ""
    cmds = bash_permitidos(cfg.proyecto)
    if not cmds:
        return ""
    return ("Comandos Bash permitidos (ya están en el PATH): "
            f"{', '.join(cmds)}. Escríbelos por su nombre, uno por llamada: sin "
            "source, export, PATH=, rutas absolutas, cd, && ni pipes, o se "
            "rechazarán. Para una subcarpeta usa la opción del propio comando "
            "(p. ej. cargo --manifest-path src-tauri/Cargo.toml, npm --prefix "
            "web).\n")

def _mapear(cfg):
    """Regenerates mapeo.txt (silent: a map failure never stops the loop)."""
    try:
        mapeo.generar(cfg.proyecto, cfg.mapa, env=cfg.environ)
    except OSError:
        pass


def backup_gate(cfg):
    """Copies gate.sh and gate_checks/ to a temporary directory (backup_gate())."""
    dir_backup = tempfile.mkdtemp(prefix="dedalo-gate-")
    if os.path.exists(cfg.gate):
        shutil.copyfile(cfg.gate, os.path.join(dir_backup, "gate.sh"))
    src = rutas.gate_checks(cfg.proyecto)
    if os.path.isdir(src):
        shutil.copytree(src, os.path.join(dir_backup, "gate_checks"))
    return dir_backup


def gate_intacto(dir_backup, cfg):
    """Did the agent modify gate.sh or gate_checks/*.{sh,py}? (gate_intacto())."""
    backup_gate_sh = os.path.join(dir_backup, "gate.sh")
    if os.path.exists(cfg.gate) != os.path.exists(backup_gate_sh):
        return False
    if os.path.exists(cfg.gate) and not filecmp.cmp(
            cfg.gate, backup_gate_sh, shallow=False):
        return False
    proyecto_checks = rutas.gate_checks(cfg.proyecto)
    backup_checks = os.path.join(dir_backup, "gate_checks")
    if not os.path.isdir(backup_checks):
        return True
    for f in sorted(os.listdir(backup_checks)):
        # Covers both the bash checks and the Python port ones (Windows).
        if not f.endswith((".sh", ".py")):
            continue
        original = os.path.join(backup_checks, f)
        if not os.path.isfile(original):
            continue
        actual = os.path.join(proyecto_checks, f)
        if not os.path.exists(actual) or not filecmp.cmp(actual, original,
                                                         shallow=False):
            return False
    return True


def restaurar_gate(dir_backup, cfg):
    """Restores gate.sh/gate_checks from the backup (restaurar_gate())."""
    backup_gate_sh = os.path.join(dir_backup, "gate.sh")
    if os.path.exists(backup_gate_sh):
        shutil.copyfile(backup_gate_sh, cfg.gate)
    backup_checks = os.path.join(dir_backup, "gate_checks")
    if os.path.isdir(backup_checks):
        destino = rutas.gate_checks(cfg.proyecto)
        shutil.rmtree(destino, ignore_errors=True)
        shutil.copytree(backup_checks, destino)


def _notificar(cfg, evento, **datos):
    """Push notification for the project. Never raises: it must not stop the loop."""
    if getattr(cfg, "origen", "") == "gui" and evento in (
            "inicio", "fin", "tokens", "error", "bloqueada"):
        # The GUI already derives these from the log it is tailing; sending
        # them from the engine too would duplicate every message.
        return
    try:
        resultados = notificaciones.enviar(
            evento, {"proyecto": cfg.nombre or os.path.basename(cfg.proyecto),
                     **datos},
            proyecto=cfg.nombre or "")
        for plataforma, estado in (resultados or []):
            if estado != "OK" and getattr(cfg, "log", ""):
                logx(cfg.log, f"⚠ notificación {evento} ({plataforma}) "
                              f"falló: {estado}")
    except Exception as e:  # noqa: BLE001
        if getattr(cfg, "log", ""):
            logx(cfg.log, f"⚠ notificación {evento} falló: {e}")


def _run_gate(cfg, criterio):
    """`python -m dedalo.gate 2>&1 | tee "$GATE_OUT"`.

    Returns (rc, path_with_the_gate_output). The output is shown on the console
    and is used as feedback to the agent if the gate fails. The gate mutates the
    repository (e.g. 98_criterio launches the judge).

    The gate is the portable orchestrator (gate.py): it runs the .py checks and,
    if bash is available, prefers the equivalent .sh ones. In the frozen binary
    it is launched as `dedalo --dedalo-gate`.
    """
    gate_out = cfg.tmp("gate")
    env = dict(cfg.environ)
    env["CRITERIO"] = criterio or ""
    env["MODELO_JUEZ"] = cfg.modelo_juez
    env["OPENCODE_AGENT_JUEZ"] = cfg.opencode_agente_juez
    # A claude judge follows the task model unless MODELO_JUEZ names a Claude one.
    loop_launch.entorno_juez(env, modelo_claude(cfg.modelo_juez) or cfg.modelo_tarea)
    if not getattr(sys, "frozen", False):
        # `python -m dedalo.gate` starts with cwd=project: without this,
        # an interpreter without the installed package (development) won't find it.
        # Inherited entries are replaced so a stale copy of the package is never
        # imported instead of this checkout.
        env["PYTHONPATH"] = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
    with open(gate_out, "wb") as ftee:
        rc, _salida, _t = run_con_timeout(
            argv_gate(), GATE_TIMEOUT, env=env, cwd=cfg.proyecto,
            stdout=ftee, stderr=subprocess.STDOUT, vivo=HIJO)
    contenido = _leer(gate_out)
    if contenido:
        sys.stdout.write(contenido)
        if contenido[-1] != "\n":
            print()
    return rc, gate_out


def proxima_tarea(plan_md):
    """First line `- [ ] ` (column 0) without the prefix; None if none are left."""
    for linea in _leer(plan_md).splitlines():
        if linea.startswith("- [ ] "):
            return linea[len("- [ ] "):]
    return None


def criterio_tarea(plan_md):
    """Criterion of the FIRST pending task (inline or indented), port of
    criterio_tarea(): `- [ ] ` box with an inline criterion, or an indented line
    under the first pending one; cut when seeing `- [x]`/`- [B]` or a line with no
    indent."""
    en_tarea = 0
    rx_inline = re.compile(r"criterio:[ \t]+(.*)$")
    rx_indent = re.compile(r"criterio:[ \t]*(.*)$")
    for linea in _leer(plan_md).splitlines():
        if linea.startswith("- [ ] "):
            m = rx_inline.search(linea)
            if m:
                return m.group(1).strip()
            en_tarea = 1
            continue
        if linea.startswith("- ["):
            if en_tarea:
                return None
            continue
        if en_tarea:
            if not re.match(r"[ \t]", linea):
                return None
            m = rx_indent.search(linea)
            if m:
                return m.group(1).strip()
    return None


def _instalar_senales(cfg):
    """SIGTERM→143 / SIGINT→130 (like the script's traps): kills the current
    process group, cleans up opencode sessions and exits."""
    if threading.current_thread() is not threading.main_thread():
        return

    def _manejar(sig, _frame):
        try:
            proc = HIJO.get("proc")
            if proc is not None and proc.poll() is None:
                matar_grupo(proc, espera=0)
            limpiar_sesiones(cli_agente("opencode", cfg), cfg.proyecto,
                             cfg.inicio_ms, cfg.log)
        finally:
            os._exit(128 + sig)

    signal.signal(signal.SIGTERM, _manejar)
    signal.signal(signal.SIGINT, _manejar)


def _marcar(cfg, estado):
    """marcar_primera on the plan (the script's marcar_plan)."""
    p = Plan(cfg.plan_md)
    p.cargar()
    return p.marcar_primera(estado)


def _commit_memoria(cfg, tarea, iteracion):
    """Commits plan marks and lessons on the run branch.

    `_marcar` and `registrar_leccion` run after the task commit, so without
    this the remote plan keeps every task as pending and the working tree
    stays dirty after a successful run.
    """
    archivos = []
    for ruta in (cfg.plan_md, cfg.lecciones):
        if os.path.exists(ruta):
            archivos.append(os.path.relpath(ruta, cfg.proyecto))
    if not archivos:
        return
    rc, salida, _ = run_git(cfg.proyecto, "status", "--porcelain", "--",
                            *archivos)
    if rc != 0 or not salida.strip():
        return
    asunto = f"dedalo: plan y lecciones (iter {iteracion})"
    if commit_tarea(cfg.proyecto, archivos, asunto, tarea) == 0:
        logx(cfg.log, f"memoria commiteada: {asunto}")
        print(f"[dedalo] ✔ commit: {asunto}")


def _resumen_bloqueadas(cfg):
    """Summary lines of the [B] tasks in plan.md with their last reason.

    The reason is looked up in `incidencias.jsonl` (last incident per task), so
    the closing answers "what was left undone and why" without digging into the log."""
    try:
        p = Plan(cfg.plan_md)
        p.cargar()
        bloqueadas = [t["texto"] for t in p.tareas
                      if t["estado"] == "bloqueada"]
    except Exception:
        bloqueadas = []
    if not bloqueadas:
        return []
    motivos = {}
    for li in _leer(cfg.incidencias).splitlines():
        try:
            d = json.loads(li)
        except ValueError:
            continue
        if d.get("tarea"):
            motivos[d["tarea"]] = d.get("motivo", "")
    lineas = ["", "== TAREAS SIN COMPLETAR =="]
    for t in bloqueadas:
        m = motivos.get(t, "")
        lineas.append(f"- [B] {t}" + (f" — {m}" if m else ""))
    return lineas


def run(cfg):
    """Full loop; returns the exit code (0-7, like the script)."""
    _proteger_salidas()
    _RECHAZO_MOTIVO["txt"] = ""
    _instalar_senales(cfg)

    # Autodetection: "auto" and empty = first available agent.
    if not cfg.agente_tarea or cfg.agente_tarea == "auto":
        cfg.agente_tarea = detectar_agente(cfg)
        if not cfg.agente_tarea:
            mensaje(cfg, "[dedalo] ✗ No se encontró ningún agente "
                         "(opencode, codex, claude).")
            return 2
        print(f"[dedalo] Agente autodetectado: {cfg.agente_tarea}")

    if not agente_ok(cfg.agente_tarea, cfg):
        binario = cli_agente(cfg.agente_tarea, cfg)
        cli_env = cfg.agente_tarea.upper()
        mensaje(cfg, f"[dedalo] ✗✗ agente '{cfg.agente_tarea}' no "
                     f"encontrado (busqué '{binario}'). Instálalo o configura "
                     f"el PATH (o CLI_{cli_env}) y relanza.")
        logx(cfg.log, f"ABORTADO: agente no disponible ({cfg.agente_tarea})")
        _notificar(cfg, "error", detalle=f"agente no disponible: {cfg.agente_tarea}")
        _incidencia(cfg, "aborto_agente",
                    f"agente '{cfg.agente_tarea}' no disponible en el PATH")
        return 2

    cfg.revisor = elegir_revisor(cfg)
    inicio_run = time.time()
    if cfg.origen != "gui":
        _notificar(cfg, "externo", origen=cfg.origen,
                   modelo_tarea=cfg.modelo_tarea or "auto",
                   modelo_revisor=cfg.modelo_revisor or "ninguno")
    logx(cfg.log,
         f"== DEDALO INICIADO (agente={cfg.agente_tarea}, "
         f"modelo={cfg.modelo_tarea}, revisor={cfg.revisor or 'ninguno'}, "
         f"modelo_rev={cfg.modelo_revisor}, dual={cfg.revision_dual}, "
         f"manual={cfg.revision_manual}, fichas={cfg.ficha_activa}, "
         f"max_iter={cfg.max_iter}, "
         f"hasta={cfg.hasta or 'sin limite'}, base={cfg.rama_base}, "
         f"costo_max={cfg.max_costo}) ==")

    print(f"[dedalo] Agente de tarea: {cfg.agente_tarea}"
          + (f" ({cfg.modelo_tarea})" if cfg.modelo_tarea else ""))
    print(f"[dedalo] Revisor dual:    {cfg.revisor or 'NINGUNO'}"
          + (f" ({cfg.modelo_revisor})" if cfg.modelo_revisor else "")
          + f" (dual={cfg.revision_dual})")

    print("[dedalo] Comprobando internet…")
    if not net.hay_internet():
        print("[dedalo] ✗ SIN INTERNET. Los modelos IA no pueden "
              "responder; abortando.")
        logx(cfg.log, "ABORTADO: sin internet")
        _notificar(cfg, "error", detalle="sin conexión a internet")
        _incidencia(cfg, "aborto_internet", "sin conexión a internet")
        alerta(cfg.voz, "Sin internet, se aborta el dedalo")
        return 4
    logx(cfg.log, "Internet OK")

    if not consentimiento.concedido(cfg.proyecto, cfg.environ):
        fichas = consentimiento.ficheros(cfg.proyecto)
        mensaje(cfg, "[dedalo] ⚠ El gate va a ejecutar código del repo SIN "
                     "sandbox: " + ", ".join(fichas))
        if sys.stdin is not None and sys.stdin.isatty():
            try:
                resp = input("[dedalo] ¿Confiar y ejecutar el gate? [y/N] ")
            except EOFError:
                resp = ""
            if resp.strip().lower() in ("y", "yes", "s", "si", "sí"):
                consentimiento.confiar(cfg.proyecto)
                logx(cfg.log, "GATE: checks aprobados por el usuario")
            else:
                mensaje(cfg, "[dedalo] ✗ gate no aprobado; abortando.")
                logx(cfg.log, "ABORTADO: gate_checks sin consentimiento")
                _notificar(cfg, "error", detalle="gate_checks sin consentimiento")
                _incidencia(cfg, "aborto_consentimiento",
                            "el usuario no aprobó los gate_checks")
                return 3
        else:
            print(f"[dedalo] ✗ gate_checks sin consentimiento (sin terminal). "
                  f"Aprueba con {consentimiento.CONSENT_ENV}=1 o desde la GUI.")
            logx(cfg.log, "ABORTADO: gate_checks sin consentimiento")
            _notificar(cfg, "error", detalle="gate_checks sin consentimiento (no interactivo)")
            _incidencia(cfg, "aborto_consentimiento",
                        "gate_checks sin consentimiento (no interactivo)")
            return 3

    dir_gate = backup_gate(cfg)
    print("[dedalo] Baseline: gate.sh...")
    rc_base, _ = _run_gate(cfg, "")
    if rc_base != 0:
        print("El repo NO pasa la verificación baseline. Corrige y relanza.")
        logx(cfg.log, "ABORTADO: baseline falló")
        _notificar(cfg, "error", detalle="el repo no pasa el gate baseline")
        _incidencia(cfg, "aborto_baseline", "el repo no pasa el gate baseline")
        alerta(cfg.voz, "Baseline falló, el dedalo no arranca")
        return 1
    logx(cfg.log, "Baseline GATE OK")

    _mapear(cfg)
    if os.path.exists(cfg.mapa) and os.path.getsize(cfg.mapa) > 0:
        logx(cfg.log, "mapeo.txt regenerado")
    else:
        print("[dedalo] ⚠ no se pudo generar mapeo.txt")

    rama_run = rama_run_nombre()
    rama_trabajo, msgs = preparar_ramas(cfg.proyecto, cfg.rama_base,
                                        rama_run, cfg.rama_trabajo)
    for m in msgs:
        print(m)
    if rama_trabajo is None:
        logx(cfg.log, "ABORTADO: no se pudo crear la rama base")
        _notificar(cfg, "error", detalle="no se pudo crear la rama base")
        _incidencia(cfg, "aborto_rama", "no se pudo crear la rama base")
        return 1
    logx(cfg.log, f"Rama base: {rama_run}")
    if cfg.rama_trabajo and cfg.rama_trabajo != rama_run:
        logx(cfg.log, f"Rama de trabajo: {rama_trabajo}")
    else:
        logx(cfg.log, f"Rama de trabajo (default): {rama_trabajo}")

    iteracion = 0
    costo_total = "0.00"
    while iteracion < cfg.max_iter:
        if hora_limite(cfg.hasta):
            logx(cfg.log, f"Hora límite ({cfg.hasta}) alcanzada.")
            print("[dedalo] ⏰ Hora límite alcanzada.")
            alerta(cfg.voz, "Hora límite alcanzada")
            break
        if cfg.max_costo > 0 and float(costo_total) >= cfg.max_costo:
            logx(cfg.log, f"Presupuesto agotado ({costo_total}/"
                          f"{cfg.max_costo} USD).")
            print(f"[dedalo] 💸 Presupuesto agotado ({costo_total}/"
                  f"{cfg.max_costo} USD).")
            alerta(cfg.voz, "Presupuesto agotado")
            _notificar(cfg, "error", detalle="presupuesto agotado")
            break
        if not net.hay_internet():
            logx(cfg.log, "SIN INTERNET: loop detenido para no lanzar tareas "
                          "sin modelo disponible.")
            print("[dedalo] ✗ SIN INTERNET. Deteniendo el loop "
                  "(los modelos IA no responden).")
            alerta(cfg.voz, "Sin internet, se detiene el dedalo")
            _notificar(cfg, "error", detalle="sin internet (loop detenido)")
            break

        tarea = proxima_tarea(cfg.plan_md)
        if tarea is None:
            logx(cfg.log, f"No quedan tareas pendientes en "
                          f"{os.path.basename(cfg.plan_md)}.")
            print("[dedalo] ✔ No quedan tareas pendientes.")
            break

        iteracion += 1
        costo_iter = "0.00"
        fecha_run = rama_run.split("/")[1]
        rama_tarea = f"dedalo/tareas/{fecha_run}/t{iteracion}"
        criterio = criterio_tarea(cfg.plan_md) or ""
        logx(cfg.log, f"== Iteración {iteracion}: {tarea} (rama {rama_tarea})"
                      + (f" | criterio: {criterio}" if criterio else "") + " ==")
        print(f"[dedalo] [{iteracion}/{cfg.max_iter}] {tarea} -> {rama_tarea}")
        if criterio:
            print(f"[dedalo]   criterio: {criterio}")

        checkout(cfg.proyecto, rama_run)
        if rama_existe(cfg.proyecto, rama_tarea):
            _, actual, _ = run_git(cfg.proyecto, "branch", "--show-current")
            if actual.strip() != rama_tarea:
                borrar_rama(cfg.proyecto, rama_tarea, fuerza=True)
                print(f"[dedalo] ⚠ rama huérfana {rama_tarea} eliminada "
                      "(run anterior)")
        checkout(cfg.proyecto, rama_tarea, crear=True, desde=rama_run)

        before = cfg.tmp("before")
        after = cfg.tmp("after")
        out = cfg.tmp("out")
        snapshot(cfg.proyecto, before)
        hecho = 0
        gate_out = None
        gate_rc = 1
        gate_salida = ""
        salida_tarea = ""
        resultado_revision = "no_ejecutado"
        feedback_revision = ""
        revisor_modo = "no_ejecutado"
        merge_ok = False
        commit_hash = ""
        commit_msg = ""
        cfg.ultimo_motivo = None

        # Feedback for the NEXT attempt: set at the end of a failed attempt
        # (gate, reviewer, manual review...) and consumed by the next prompt.
        # It used to be reset at the top of every attempt, so none of it ever
        # reached the agent.
        pre = ""
        fallos_gate = []  # "[GATE] ✗" lines of failed attempts, for lecciones.md
        for intento in range(1, cfg.max_reintentos + 1):
            if intento > 1 and not pre:
                pre = ("El intento anterior no pasó la verificación: no repitas "
                       "tu cambio, corrígelo. ")
            costo_iter = suma_coste(costo_iter, cfg.costo_por_iter)
            lecciones_ctx = ""
            if os.path.exists(cfg.lecciones) and \
                    os.path.getsize(cfg.lecciones) > 0:
                lecciones_ctx = _leer(cfg.lecciones)
            contexto_ctx = ""
            if os.path.exists(cfg.contexto) and \
                    os.path.getsize(cfg.contexto) > 0:
                contexto_ctx = _leer(cfg.contexto)
            nav_ctx = ""
            if (cfg.navegador == "1" and agente_ok(cfg.agente_tarea, cfg)
                    and cfg.modelo_navegador):
                nav = cfg.tmp("nav")
                run_navegador(cfg, nav, cfg.modelo_navegador, tarea,
                              cfg.agente_tarea)
                if os.path.getsize(nav) > 0:
                    nav_ctx = _leer(nav)
                try:
                    os.unlink(nav)
                    os.unlink(nav + ".err")
                except OSError:
                    pass

            criterio_texto = criterio or "<sin criterio explícito; usa los tests/mapeo.txt como contrato>"
            contexto_block = ("CONTEXTO DEL PROYECTO (de qué trata, requisitos, "
                              "filosofía y estructura — respétalo):\n"
                              + contexto_ctx + "\n"
                              if contexto_ctx else "")
            memoria_ctx = ("MEMORIA DEL PROYECTO (lecciones aprendidas, evita "
                           "repetir estos errores):\n" + lecciones_ctx + "\n"
                           if lecciones_ctx else "")
            rel_log = os.path.relpath(cfg.log, cfg.proyecto)
            rel_mapa = os.path.relpath(cfg.mapa, cfg.proyecto)
            rel_scripts = os.path.relpath(os.path.dirname(cfg.gate), cfg.proyecto)
            prompt = (f"Estás en MODO DEDALO. Usa únicamente las skills que "
                      f"tu sesión ya tenga cargadas; no intentes cargar ninguna "
                      f"otra.\nTarea actual (solo esta): {tarea}\n"
                      f"{pre}Criterio de aceptación que debe cumplir tu trabajo "
                      f"(el gate lo verificará): {criterio_texto}\n"
                      f"Lee plan.md y {rel_log} antes de tocar nada. Lee también "
                      f"{rel_mapa} (mapa módulos→tests): localiza el/los test del "
                      "código que vas a tocar y úsalos como contrato.\n"
                      f"{nav_ctx}{contexto_block}{memoria_ctx}"
                      f"{_checks_del_gate(cfg, rel_scripts)}"
                      f"{_comandos_permitidos(cfg)}"
                      "Ejecuta ÚNICAMENTE esta tarea.\n"
                      "NO hagas commits, NO crees, cambies ni borres ramas: el "
                      "script gestiona git.\n"
                      f"NO edites {rel_scripts}/*, plan.md, {rel_log}, "
                      "lecciones.md, CONTEXTO.md, "
                      "endpoints.txt, .env ni SECURITY.md.\n"
                      "Al terminar, responde con un resumen conciso de qué "
                      "cambiaste y qué tests corriste.")

            pre = ""  # consumed: later failures set it again
            rc, _vivo = run_agente(cfg, cfg.agente_tarea, out,
                                   cfg.modelo_tarea, prompt, tarea, iteracion)
            if rc == 124:
                mensaje(cfg, f"[dedalo] ⚠ timeout: {cfg.agente_tarea} tardó "
                             f"más de {cfg.timeout_por_tarea}s")
                alerta(cfg.voz, "Tiempo agotado en una tarea")
            elif rc in (126, 127):
                mensaje(cfg, f"[dedalo] ✗✗ {cfg.agente_tarea} no se pudo "
                             f"ejecutar (rc={rc}): binario no encontrado o sin "
                             f"permisos de ejecución.")
                logx(cfg.log, f"ABORTADO: agente no ejecutable (rc={rc})")
                _notificar(cfg, "error", detalle=f"agente no ejecutable (rc={rc})")
                _incidencia(cfg, "aborto_agente_ejecucion",
                            f"{cfg.agente_tarea} no ejecutable (rc={rc})",
                            tarea=tarea, iteracion=iteracion, rama=rama_tarea)
                alerta(cfg.voz, "El agente no se pudo ejecutar; revisa PATH/instalación")
                return 6
            elif rc != 0:
                mensaje(cfg, f"[dedalo] ⚠ {cfg.agente_tarea} salió con rc={rc}")

            contenido = _leer(out)
            salida_tarea = contenido
            if rc == 0 or contenido:
                print(contenido, end="")
            _append_log(cfg, contenido)

            snapshot(cfg.proyecto, after)
            nuevos, borrados = cambios_entre(before, after)
            iter_sin_trabajo = 0
            if not nuevos and not borrados:
                iter_sin_trabajo = 1
            if sin_autenticacion(out + ".err", out, iter_sin_trabajo):
                mensaje(cfg, f"[dedalo] ✗✗ {cfg.agente_tarea} no está "
                             f"autenticado (CLI instalado, sin sesión). Haz "
                             f"login del agente y relanza (opencode: 'opencode "
                             f"auth login' · claude: '/login' · codex: 'codex "
                             f"login').")
                logx(cfg.log, f"ABORTADO: agente sin autenticacion ({cfg.agente_tarea})")
                _notificar(cfg, "error", detalle=f"agente sin autenticación: {cfg.agente_tarea}")
                _incidencia(cfg, "aborto_autenticacion",
                            f"{cfg.agente_tarea} sin sesión iniciada",
                            tarea=tarea, iteracion=iteracion, rama=rama_tarea)
                alerta(cfg.voz, "El agente no está autenticado; revisa su login")
                return 7
            # stdout is the agent's own narrative: only trust a quota match there
            # when the call actually failed or did nothing.
            if (tokens_agotados(out + ".err")
                    or ((rc != 0 or iter_sin_trabajo) and tokens_agotados(out))):
                mensaje(cfg, "[dedalo] ✗ Tokens/cuota agotados del proveedor "
                             "IA — deteniendo loop")
                logx(cfg.log, "ABORTADO: tokens/cuota agotados")
                _notificar(cfg, "tokens")
                _incidencia(cfg, "aborto_tokens", "tokens/cuota agotados",
                            tarea=tarea, iteracion=iteracion, rama=rama_tarea)
                alerta(cfg.voz, "Tokens agotados, se detiene el dedalo")
                return 5

            if rc != 0 and iter_sin_trabajo:
                # The agent failed and left nothing: a green gate here would only
                # prove the previous state, so the attempt must not count as
                # done (it used to mark the task [x] with no work at all).
                logx(cfg.log, f"AGENTE FALLÓ sin cambios (rc={rc}, intento "
                              f"{intento}): no se ejecuta el gate")
                _incidencia(cfg, "agente_fallo",
                            f"{cfg.agente_tarea} salió con rc={rc} sin cambios",
                            tarea=tarea, iteracion=iteracion, rama=rama_tarea)
                pre = (f"Tu ejecución anterior terminó con error (rc={rc}) sin "
                       "cambiar nada. Completa la tarea. ")
                continue

            _, actual, _ = run_git(cfg.proyecto, "branch", "--show-current")
            if actual.strip() != rama_tarea:
                mensaje(cfg, "[dedalo] ✗✗ el agente cambió de rama. "
                             "Abortando: requiere revisión humana.")
                logx(cfg.log, "ABORTADO: se detectó cambio de rama no autorizado")
                _notificar(cfg, "error", detalle="el agente cambió de rama")
                _incidencia(cfg, "aborto_rama_agente",
                            "el agente cambió de rama (requiere revisión humana)",
                            tarea=tarea, iteracion=iteracion, rama=rama_tarea)
                alerta(cfg.voz, "El agente cambió de rama, se aborta el run")
                return 3

            if not gate_intacto(dir_gate, cfg):
                restaurar_gate(dir_gate, cfg)
                mensaje(cfg, "[dedalo] ✗ el agente alteró gate.sh/gate_checks: "
                             "gate restaurado, intento anulado.")
                logx(cfg.log, f"GATE ALTERADO por el agente (intento {intento}), "
                              "restaurado")
                pre = "No edites gate.sh ni gate_checks/*.sh (son del framework). Tu cambio a esos archivos se descartó. "
                continue

            logx(cfg.log, f"GATE: ejecutando gate.sh (intento {intento})")
            rc_gate, gate_out = _run_gate(cfg, criterio)
            gate_salida = _leer(gate_out)
            # A green gate whose judge could not give an opinion has not
            # verified the criterio: rerun only the gate (not the agent).
            for reintento in range(1, REINTENTOS_JUEZ + 1):
                if not (rc_gate == 0 and criterio
                        and _juez_no_opino(gate_salida)):
                    break
                logx(cfg.log, f"JUEZ NO DISPONIBLE: repitiendo el gate "
                              f"({reintento}/{REINTENTOS_JUEZ})")
                time.sleep(cfg.espera_juez)
                rc_gate, gate_out = _run_gate(cfg, criterio)
                gate_salida = _leer(gate_out)
            if rc_gate == 0 and criterio and _juez_no_opino(gate_salida):
                motivo = _juez_no_opino(gate_salida)
                mensaje(cfg, "[dedalo] ✗ el juez no pudo verificar el criterio "
                             f"({motivo}) — deteniendo loop sin marcar la tarea")
                logx(cfg.log, f"ABORTADO: juez no disponible ({motivo})")
                _notificar(cfg, "error", detalle=f"juez no disponible: {motivo}")
                _incidencia(cfg, "aborto_juez", f"juez no disponible: {motivo}",
                            tarea=tarea, iteracion=iteracion, rama=rama_tarea)
                alerta(cfg.voz, "El juez no responde, se detiene el dedalo")
                return 8
            gate_rc = rc_gate
            if rc_gate == 0:
                if cfg.revision_dual == "1" and cfg.revisor:
                    revisor_modo = "dual"
                    costo_iter = suma_coste(costo_iter,
                                            float(cfg.costo_por_iter) / 2)
                    vstat, vdiff = diff_para_revisor(cfg.proyecto)
                    resultado, feedback = revisar_diff(
                        cfg, cfg.revisor, tarea,
                        f"{vstat}\n{vdiff}" if vdiff else vstat,
                        gate_ok="\n".join(
                            li for li in gate_salida.splitlines()
                            if li.startswith("[GATE] ✓")))
                    resultado_revision = resultado or "fail"
                    feedback_revision = feedback or ""
                    if resultado == "sin_auth":
                        mensaje(cfg, f"[dedalo] ✗✗ revisor ({cfg.revisor}) "
                                     "no está autenticado — deteniendo loop")
                        logx(cfg.log, f"ABORTADO: revisor sin autenticacion ({cfg.revisor})")
                        _notificar(cfg, "error", detalle=f"revisor sin autenticación: {cfg.revisor}")
                        _incidencia(cfg, "aborto_autenticacion",
                                    f"revisor {cfg.revisor} sin sesión iniciada",
                                    tarea=tarea, iteracion=iteracion,
                                    rama=rama_tarea)
                        alerta(cfg.voz, "El revisor no está autenticado")
                        return 7
                    if resultado == "sin_tokens":
                        mensaje(cfg, "[dedalo] ✗ Tokens/cuota agotados del "
                                     "proveedor IA (revisor) — deteniendo loop")
                        logx(cfg.log, "ABORTADO: tokens/cuota agotados (revisor)")
                        _notificar(cfg, "tokens")
                        _incidencia(cfg, "aborto_tokens",
                                    "tokens/cuota agotados (revisor)",
                                    tarea=tarea, iteracion=iteracion,
                                    rama=rama_tarea)
                        alerta(cfg.voz, "Tokens agotados, se detiene el dedalo")
                        return 5
                    if resultado == "pass":
                        print(f"[dedalo] ✔ revisor ({cfg.revisor}): PASS")
                        logx(cfg.log, f"REVISOR PASS ({cfg.revisor}, intento {intento})")
                        rc_manual = _esperar_revision_manual(cfg, tarea)
                        if rc_manual == 4:
                            return 4
                        if rc_manual == 0:
                            resultado_revision = "pass"
                            feedback_revision = ""
                            hecho = 1
                            break
                        if rc_manual == 2:
                            logx(cfg.log, "Revisión manual: timeout, tarea "
                                          "marcada [B]")
                            _incidencia(cfg, "revision_timeout",
                                        "timeout en revisión manual del diff",
                                        tarea=tarea, iteracion=iteracion,
                                        rama=rama_tarea)
                            break
                        revertir(cfg.proyecto)
                        pre = (f"El diff fue rechazado en revisión manual: "
                               f"{_RECHAZO_MOTIVO['txt']}. Corrige esto en tu "
                               "siguiente intento. ")
                        logx(cfg.log, "REVISIÓN MANUAL RECHAZADO, reintentando...")
                    else:
                        logx(cfg.log, f"REVISOR FAIL (intento {intento})")
                        _incidencia(cfg, "revisor_fail",
                                    feedback or "el revisor rechazó el diff",
                                    tarea=tarea, iteracion=iteracion,
                                    rama=rama_tarea)
                        print(f"[dedalo] ✗ revisor ({cfg.revisor}): FAIL")
                        if feedback:
                            pre = (f"El revisor rechazó el diff anterior: "
                                   f"{feedback}. Corrige esto en tu siguiente "
                                   "intento. ")
                            logx(cfg.log, "Feedback del revisor inyectado para "
                                          "siguiente intento")
                else:
                    revisor_modo = ("manual" if cfg.revision_manual == "1"
                                    else "gate")
                    resultado_revision = "pendiente"
                    rc_manual = _esperar_revision_manual(cfg, tarea)
                    if rc_manual == 4:
                        return 4
                    if rc_manual == 0:
                        resultado_revision = "pass"
                        feedback_revision = ""
                        hecho = 1
                        break
                    if rc_manual == 2:
                        logx(cfg.log, "Revisión manual: timeout, tarea "
                                      "marcada [B]")
                        _incidencia(cfg, "revision_timeout",
                                    "timeout en revisión manual del diff",
                                    tarea=tarea, iteracion=iteracion,
                                    rama=rama_tarea)
                        break
                    revertir(cfg.proyecto)
                    pre = (f"El diff fue rechazado en revisión manual: "
                           f"{_RECHAZO_MOTIVO['txt']}. Corrige esto en tu "
                           "siguiente intento. ")
                    logx(cfg.log, "REVISIÓN MANUAL RECHAZADO, reintentando...")
            else:
                logx(cfg.log, f"GATE FALLÓ tras el agente (intento {intento})")
                print(f"[dedalo] ✗ la tarea no pasó el gate "
                      f"(intento {intento}/{cfg.max_reintentos})")
                fb = _leer(gate_out)
                _append_log(cfg, fb)
                resumen_gate = _resumen_gate(fb)
                fallos_gate += [li for li in fb.splitlines()
                                if li.startswith("[GATE] ✗")][:3]
                _incidencia(cfg, "gate_fail",
                            resumen_gate or "gate falló sin detalle",
                            tarea=tarea, iteracion=iteracion, rama=rama_tarea)
                if resumen_gate:
                    pre = (f"El gate falló con: {resumen_gate}. El detalle "
                           "completo está en progreso.log. Corrige esto en tu "
                           "siguiente intento. ")
                    logx(cfg.log, "Feedback del gate inyectado para siguiente "
                                  "intento")
                try:
                    os.unlink(gate_out)
                    gate_out = None
                except OSError:
                    pass

        logx(cfg.log, f"Costo iteración {iteracion}: {costo_iter} USD")
        snapshot(cfg.proyecto, after)

        if hecho == 1:
            nuevos, _b = cambios_entre(before, after)
            if nuevos:
                subj = "dedalo: " + tarea[:40]
                rc_c = commit_tarea(cfg.proyecto, nuevos, subj, tarea)
                if rc_c == 0:
                    commit_msg = subj
                    _, head, _ = run_git(cfg.proyecto, "rev-parse", "HEAD")
                    commit_hash = head.strip()
                    logx(cfg.log, f"commit en {rama_tarea}: {subj}")
                    print(f"[dedalo] ✔ commit: {subj}")
                else:
                    logx(cfg.log, f"⚠ commit falló en {rama_tarea} (rc={rc_c})")
            else:
                logx(cfg.log, "tarea completada sin cambios nuevos")
                print("[dedalo] ✔ tarea completada sin cambios nuevos")

            if (checkout(cfg.proyecto, rama_run) == 0
                    and merge_ff(cfg.proyecto, rama_tarea) == 0):
                merge_ok = True
                borrar_rama(cfg.proyecto, rama_tarea)
                logx(cfg.log, f"mergeada {rama_tarea} -> {rama_run}")
                _mapear(cfg)
                logx(cfg.log, f"mapeo.txt actualizado tras {tarea}")
                _marcar(cfg, "x")
                if fallos_gate:
                    # Kept short: lecciones.md goes into every later prompt.
                    registrar_leccion(
                        cfg.lecciones, f"Corregida en reintento: {tarea}",
                        "El gate falló antes de pasar.",
                        "; ".join(dict.fromkeys(fallos_gate))[:300],
                        "Verifica con los mismos checks del gate antes de "
                        "terminar.")
                    logx(cfg.log, "lección registrada (gate corregido en reintento)")
                _notificar(cfg, "tarea", tarea=tarea, iteracion=iteracion,
                           rama=rama_run,
                           commit=(f"\nCommit: `{commit_msg}`"
                                   if commit_msg else ""))
            else:
                mensaje(cfg, f"[dedalo] ⚠ merge fallido; rama {rama_tarea} "
                             "conservada y tarea marcada [B].")
                _marcar(cfg, "B")
                _incidencia(cfg, "merge_fail",
                            f"git merge --ff-only {rama_tarea} -> {rama_run} "
                            "falló; rama conservada",
                            tarea=tarea, iteracion=iteracion, rama=rama_tarea)
                registrar_leccion(
                    cfg.lecciones, f"Merge fallido: {tarea}",
                    f"git merge --ff-only {rama_tarea} -> {rama_run} falló; "
                    "rama conservada.",
                    "La rama de la tarea sigue en "
                    f"{rama_tarea}; revisar conflictos o historial.",
                    "Resolver el merge manualmente o ajustar la base si es "
                    "necesario.")
                logx(cfg.log, "lección registrada (merge fallido)")
        else:
            checkout(cfg.proyecto, rama_run)
            borrar_rama(cfg.proyecto, rama_tarea, fuerza=True)
            revertir(cfg.proyecto)
            _marcar(cfg, "B")
            _notificar(cfg, "bloqueada", tarea=tarea)
            logx(cfg.log, f"tarea BLOQUEADA: {tarea} (rama {rama_tarea} "
                          "descartada)")
            print(f"[dedalo] ✗ tarea bloqueada tras {cfg.max_reintentos} "
                  "intentos. Marcada [B] en plan.md")
            alerta(cfg.voz, f"Tarea bloqueada: {tarea}")
            motivo = cfg.ultimo_motivo or {}
            detalle = (
                f"{motivo.get('tipo', 'fallo')} en la iteración {iteracion}: "
                f"{motivo.get('motivo') or 'sin detalle'}"
                if motivo else
                f"gate.sh/revisor fallaron en la iteración {iteracion}.")
            _incidencia(cfg, "bloqueada", detalle,
                        tarea=tarea, iteracion=iteracion, rama=rama_tarea)
            registrar_leccion(
                cfg.lecciones, f"Tarea bloqueada: {tarea}",
                "El agente no cumplió el criterio tras "
                f"{cfg.max_reintentos} intentos.",
                detalle,
                "Reformular la tarea en plan.md, dividirla en pasos más "
                "pequeños o revisar los criterios.")
            logx(cfg.log, "lección registrada en lecciones.md (tarea bloqueada)")

        _commit_memoria(cfg, tarea, iteracion)

        if hecho == 1 and merge_ok:
            ficha.generar(
                cfg, tarea=tarea, criterio=criterio, iteracion=iteracion,
                rama=rama_run, commit=commit_hash, commit_msg=commit_msg,
                gate_rc=gate_rc, gate_salida=gate_salida,
                salida_agente=salida_tarea,
                resultado_revision=resultado_revision,
                feedback_revision=feedback_revision, merge_ok=True,
                revisor_modo=revisor_modo)

        try:
            if gate_out:
                os.unlink(gate_out)
        except OSError:
            pass

        costo_total = suma_coste(costo_total, costo_iter)
        logx(cfg.log, f"Costo estimado acumulado: {costo_total} USD")
        print(f"[dedalo] 💰 Costo estimado acumulado: {costo_total} USD")
        for f in (before, after, out, out + ".err"):
            try:
                os.unlink(f)
            except OSError:
                pass

    # --- Integrate work into the destination branch (--trabajo different from run) ---
    if cfg.rama_trabajo and cfg.rama_trabajo != rama_run:
        print(f"[dedalo] Integrando {rama_run} -> {cfg.rama_trabajo}")
        if (checkout(cfg.proyecto, cfg.rama_trabajo) == 0 and
                run_git(cfg.proyecto, "merge", "-q", "--no-ff", rama_run,
                        "-m", f"dedalo: integrar {rama_run}")[0] == 0):
            logx(cfg.log, f"integrado {rama_run} -> {cfg.rama_trabajo}")
        else:
            mensaje(cfg, f"[dedalo] ⚠ no se pudo integrar en "
                         f"{cfg.rama_trabajo}; el trabajo queda en {rama_run}")

    if cfg.push:
        asegurar_remote_origin(cfg)
        rc, url, _ = run_git(cfg.proyecto, "remote", "get-url", "origin")
        if rc == 0:
            push_rama = cfg.rama_trabajo or rama_run
            # Safeguard: never push the (protected) base branch by accident.
            if push_rama in (cfg.rama_base, "master", "main"):
                mensaje(cfg, f"[dedalo] ✗ push abortado: '{push_rama}' es la "
                             "rama base; el trabajo debe ir en una rama dedalo/*.")
                logx(cfg.log, f"push abortado: '{push_rama}' es rama base")
            else:
                # Visibility: make clear which remote it is pushed to before doing it.
                print(f"[dedalo] push → origin ({url.strip()}) rama "
                      f"{push_rama}")
                logx(cfg.log, f"push: origin ({url.strip()}) {push_rama}")
                if run_git(cfg.proyecto, "push", "-u", "origin", push_rama,
                           timeout=300)[0] == 0:
                    logx(cfg.log, f"push: origin/{push_rama}")
                    print(f"[dedalo] ✔ push OK: origin/{push_rama}")
                    print(f"[dedalo] abre el PR de {push_rama} -> "
                          f"{cfg.rama_base}")
                else:
                    mensaje(cfg, f"[dedalo] ⚠ falló el push a origin/"
                                 f"{push_rama}. El trabajo queda local.")
        else:
            mensaje(cfg, "[dedalo] ℹ sin remote origin (repo no creado). "
                         "Trabajo queda local.")

    print()
    resumen = _resumen_bloqueadas(cfg)
    if resumen:
        print("\n".join(resumen))
        _append_log(cfg, "\n".join(resumen))
    print("== RESUMEN (final de progreso.log) ==")
    print("\n".join(_leer(cfg.log).splitlines()[-25:]))
    logx(cfg.log, f"== DEDALO FINALIZADO (iter={iteracion}, "
                  f"rama={rama_run}, costo≈{costo_total}) ==")
    if cfg.origen != "gui":
        try:
            p_plan = Plan(cfg.plan_md)
            p_plan.cargar()
            pend, hechas, bloqueadas = p_plan.conteo()
        except Exception:  # noqa: BLE001
            pend = hechas = bloqueadas = 0
        _notificar(cfg, "fin", hechas=hechas, total=pend + hechas + bloqueadas,
                   coste=float(costo_total),
                   duracion_min=(time.time() - inicio_run) / 60.0)
    alerta(cfg.voz, "Dédalo finalizado")
    return 0


def _gh_api_owner(token):
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {token}",
                 "User-Agent": "dedalo"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return (json.load(r) or {}).get("login") or ""
    except Exception:
        return ""


def _gh_api_crear_repo(owner, nombre, token):
    data = json.dumps({"name": nombre, "private": True,
                       "auto_init": False}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/user/repos", data=data,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "User-Agent": "dedalo"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return b"ssh_url" in r.read()
    except Exception:
        return False


def asegurar_remote_origin(cfg):
    """Port of _asegurar_remote_origin(): creates a GitHub repo if there is no
    origin (gh preferred, fallback GITHUB_TOKEN via API)."""
    rc, _, _ = run_git(cfg.proyecto, "remote", "get-url", "origin")
    if rc == 0:
        return
    nombre = os.path.basename(os.path.normpath(cfg.proyecto))
    env = cfg.environ
    if shutil.which("gh"):
        st = subprocess.run(["gh", "auth", "status"], capture_output=True,
                            env=env)
        if st.returncode == 0:
            owner = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                                   capture_output=True, text=True,
                                   env=env).stdout.strip()
            if owner:
                crea = subprocess.run(
                    ["gh", "repo", "create", f"{owner}/{nombre}", "--private"],
                    capture_output=True, env=env)
                if crea.returncode == 0:
                    print(f"[dedalo] ✔ repo creado en GitHub: "
                          f"{owner}/{nombre}")
                    run_git(cfg.proyecto, "remote", "add", "origin",
                            f"https://github.com/{owner}/{nombre}.git")
                    logx(cfg.log, "repo creado y remote origin configurado: "
                                  f"https://github.com/{owner}/{nombre}.git")
                    return
            mensaje(cfg, "[dedalo] ⚠ no se pudo crear repo con gh "
                         "(respuesta API)")
    token = env.get("GITHUB_TOKEN", "") or ""
    if token:
        print(f"[dedalo] Creando repo GitHub: {nombre} ...")
        owner = _gh_api_owner(token)
        if owner and _gh_api_crear_repo(owner, nombre, token):
            url = f"git@github.com:{owner}/{nombre}.git"
            run_git(cfg.proyecto, "remote", "add", "origin", url)
            print(f"[dedalo] ✔ repo creado en GitHub: {owner}/{nombre}")
            logx(cfg.log, f"repo creado y remote origin configurado: {url}")
        else:
            mensaje(cfg, "[dedalo] ⚠ no se pudo crear repo (respuesta "
                         "API)")
    else:
        registrar_leccion(
            cfg.lecciones, "GitHub: remote origin ausente",
            "No hay gh autenticado ni GITHUB_TOKEN para crear repo "
            "automático.",
            "Crea el repo manualmente en GitHub y ejecuta: "
            "git remote add origin <url>",
            "dedalo.sh tiene asistencia para crear el repo con "
            "gh/GITHUB_TOKEN.")
        logx(cfg.log, "lección registrada: remote origin ausente (sin "
                      "credenciales)")


def _origen_decision(crudo):
    """Origin marker of the review decision file ("mcp", "gui" or "").

    The writer adds a `# origen=<quien>` line (GUI: `gui`, MCP tool: `mcp`).
    Files without a marker (older clients, manual writes) return "" and are
    treated as human, so the historical behavior is preserved."""
    for linea in crudo.splitlines()[1:]:
        linea = linea.strip()
        if linea.startswith("# origen="):
            return linea[len("# origen="):].strip().lower()
    return ""


def _motivo_rechazo(crudo):
    """REJECT reason: everything after the word REJECT, without the origin
    marker line (`# origen=...` and any other `#` bookkeeping line)."""
    lineas = crudo.splitlines()
    if not lineas or not lineas[0].strip().upper().startswith("REJECT"):
        return ""
    partes = [lineas[0].strip()[len("REJECT"):]]
    partes += [ln for ln in lineas[1:] if not ln.strip().startswith("#")]
    return "\n".join(partes).strip()


def _esperar_revision_manual(cfg, tarea):
    """Port of esperar_revision_manual(): returns 0 approved, 2 timeout,
    1 rejected (leaves the reason in _RECHAZO_MOTIVO), 4 no internet
    (aborts the run like the script's `exit 4`)."""
    if cfg.revision_manual != "1":
        return 0
    dir_rev = rutas.dir_review(cfg.proyecto)
    os.makedirs(dir_rev, exist_ok=True)
    _, diff_all, _ = run_git(cfg.proyecto, "diff", "--stat")
    _, diff_full, _ = run_git(cfg.proyecto, "diff")
    with open(os.path.join(dir_rev, "diff.txt"), "w", encoding="utf-8") as f:
        f.write(diff_all + "\n" + diff_full)
    with open(os.path.join(dir_rev, "tarea.txt"), "w", encoding="utf-8") as f:
        f.write(tarea)
    with open(os.path.join(dir_rev, "waiting"), "w", encoding="utf-8") as f:
        f.write("waiting")
    print(f"[dedalo] ⏸ Esperando revisión manual en {dir_rev}...")
    logx(cfg.log, f"ESPERANDO REVISIÓN MANUAL: {tarea}")

    decision_path = os.path.join(dir_rev, "decision")
    esperado = 0
    while True:
        while not os.path.exists(decision_path):
            time.sleep(2)
            esperado += 2
            if esperado % 30 == 0 and not net.hay_internet():
                mensaje(cfg, "[dedalo] ✗ sin internet durante la revisión "
                             "manual: abortando.")
                logx(cfg.log, "ABORTADO: sin internet durante revisión manual")
                _notificar(cfg, "error", detalle="sin internet durante la revisión manual")
                alerta(cfg.voz, "Sin internet, se aborta el dedalo")
                for f in ("waiting", "decision"):
                    try:
                        os.unlink(os.path.join(dir_rev, f))
                    except OSError:
                        pass
                return 4
            if (cfg.timeout_revision_manual > 0
                    and esperado >= cfg.timeout_revision_manual):
                mensaje(cfg, f"[dedalo] ✗ timeout de revisión manual "
                             f"({cfg.timeout_revision_manual}s): tarea "
                             f"bloqueada.")
                logx(cfg.log, "REVISIÓN MANUAL: timeout sin respuesta")
                alerta(cfg.voz, "Revisión manual sin respuesta, tarea marcada "
                                "como bloqueada")
                for f in ("waiting", "decision"):
                    try:
                        os.unlink(os.path.join(dir_rev, f))
                    except OSError:
                        pass
                return 2
        crudo = _leer(decision_path)
        origen = _origen_decision(crudo)
        if (crudo.strip().upper().startswith("APPROVE") and origen == "mcp"
                and cfg.revision_aprueba_agente != "1"):
            # Policy: an agent must not approve its own work. Ignore the
            # decision and keep waiting so a human can still approve in the GUI.
            mensaje(cfg, "[dedalo] ⚠ aprobación emitida por un agente ignorada "
                         "(política REVISION_APRUEBA_AGENTE=0); sigue esperando "
                         "aprobación humana.")
            logx(cfg.log, "REVISIÓN MANUAL: APROBACIÓN POR AGENTE IGNORADA "
                          "(política)")
            _incidencia(cfg, "revision_agente",
                        "aprobación por agente ignorada", tarea)
            for f in ("waiting", "decision"):
                try:
                    os.unlink(os.path.join(dir_rev, f))
                except OSError:
                    pass
            with open(os.path.join(dir_rev, "waiting"), "w",
                      encoding="utf-8") as f:
                f.write("waiting")
            continue
        break
    for f in ("waiting", "decision"):
        try:
            os.unlink(os.path.join(dir_rev, f))
        except OSError:
            pass
    quien = f"origen={origen}" if origen else "origen=humano"
    if crudo.startswith("APPROVE"):
        print("[dedalo] ✔ Diff aprobado manualmente")
        logx(cfg.log, f"REVISIÓN MANUAL: APROBADO ({quien})")
        return 0
    if crudo.startswith("REJECT"):
        motivo = _motivo_rechazo(crudo)
        print(f"[dedalo] ✗ Diff rechazado: {motivo}")
        logx(cfg.log, f"REVISIÓN MANUAL: RECHAZADO - {motivo} ({quien})")
        _RECHAZO_MOTIVO["txt"] = motivo
        return 1
    print(f"[dedalo] ⚠ Decisión desconocida: {crudo}")
    return 1


_LOCK = {"handle": None}


def main(argv=None):
    args = parse_args(argv)
    cfg = Config(args)
    if cfg.nombre:
        # Single-run guard: an exclusive lock held for the whole run. A second
        # engine for the same project (another GUI click, an MCP call or a
        # manual launch) cannot take it and aborts instead of duplicating work.
        handle = loops_estado.adquirir(cfg.nombre)
        if handle is None:
            print(f"[dedalo] ✗ Ya hay un bucle corriendo para '{cfg.nombre}'. "
                  f"Deténlo antes de lanzar otro.")
            logx(cfg.log, f"ABORTADO: ya hay un bucle en marcha ({cfg.nombre})")
            return 5
        _LOCK["handle"] = handle
        loops_estado.registrar(cfg.nombre, os.getpid(), origen=cfg.origen)
    try:
        return run(cfg)
    finally:
        if cfg.nombre:
            loops_estado.olvidar(cfg.nombre)
        loops_estado.liberar(_LOCK.pop("handle", None))


if __name__ == "__main__":
    sys.exit(main())
