#!/usr/bin/env python3
"""Unified loop state, shared by the GUI, the MCP server and the engine.

Single source of truth: `~/.config/dedalo/loops.json`, a JSON map
`{nombre: {"pid", "pgid", "inicio", "origen"}}`. It replaces the old
`mcp_loops.json` (which only the MCP server read) so that the GUI sees the
loops the MCP started and the MCP sees the loops the GUI started: neither can
launch a duplicate for a project that already has one running.

Liveness is decided by the process (the engine also holds an exclusive
`flock` for its whole lifetime), so an entry left behind by a crash is
detected and cleaned up on the next read.
"""

import json
import os
import subprocess
import time

from . import configuracion as cfg

# Project name -> {pid, pgid, inicio, origen}. Written atomically with 0o600.
RUTA = os.path.join(cfg.CONFIG_DIR, "loops.json")
# Old file (MCP-only). It is read once for a transparent migration.
_RUTA_LEGACY = os.path.join(cfg.CONFIG_DIR, "mcp_loops.json")

_POSIX = os.name == "posix"

# Sentinel returned by `adquirir` on platforms without flock: a valid,
# truthy handle that keeps the "already acquired" contract without a lock.
SIN_LOCK = object()


def _leer():
    for ruta in (RUTA, _RUTA_LEGACY):
        try:
            with open(ruta, encoding="utf-8") as f:
                datos = json.load(f)
            if isinstance(datos, dict):
                return datos
        except (OSError, ValueError):
            continue
    return {}


def _escribir(datos):
    """Atomic, private write (temp + os.replace), like the project registry."""
    try:
        os.makedirs(cfg.CONFIG_DIR, exist_ok=True, mode=0o700)
        tmp = f"{RUTA}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, RUTA)
    except OSError:
        pass


def _zombie(pid):
    """True if `pid` is a zombie (Linux /proc). Never reaps: waitpid here
    would steal the exit status from the GUI's QProcess."""
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as f:
            return f.read().rsplit(")", 1)[1].split()[0] == "Z"
    except (OSError, IndexError):
        return False

def vivo(pid):
    """Whether `pid` is alive (signal 0). PermissionError counts as alive.

    A zombie is dead: a loop launched by the MCP server stays a zombie after
    it exits until reaped, and signal 0 still succeeds on it, so
    `detener_loop` reported "sigue vivo" and the loop looked like running.
    """
    if not pid:
        return False
    try:
        pid = int(pid)
    except (ValueError, TypeError):
        return False
    if _zombie(pid):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False
    return True


def cargar():
    """Raw map (only live entries): drops stale entries left by a crash."""
    datos = _leer()
    muertos = [n for n, e in datos.items() if not vivo((e or {}).get("pid"))]
    if muertos:
        for n in muertos:
            datos.pop(n, None)
        _escribir(datos)
    return datos


def estado(nombre):
    """State of a project's loop: running, pid, origin and start timestamp."""
    ent = cargar().get(nombre) or {}
    pid = ent.get("pid")
    return {
        "corriendo": bool(pid and vivo(pid)),
        "pid": int(pid) if pid else None,
        "pgid": int(ent["pgid"]) if ent.get("pgid") else None,
        "origen": ent.get("origen") or "",
        "inicio": ent.get("inicio"),
    }


def registrar(nombre, pid, origen="", pgid=None):
    """Records a running loop for `nombre` (idempotent per pid)."""
    if not nombre or not pid:
        return
    if pgid is None and _POSIX:
        try:
            pgid = os.getpgid(int(pid))
        except (ProcessLookupError, PermissionError, OSError):
            pgid = None
    datos = cargar()
    datos[nombre] = {
        "pid": int(pid),
        "pgid": int(pgid) if pgid else None,
        "inicio": time.time(),
        "origen": origen,
    }
    _escribir(datos)


def olvidar(nombre):
    """Removes the entry for `nombre` if present."""
    datos = _leer()
    if nombre in datos:
        datos.pop(nombre, None)
        _escribir(datos)


def matar(pid, espera=5):
    """TERM→KILL for the whole process group of `pid`.

    The engine is started with its own session/group, so killpg takes down the
    agent hanging off it too. Returns True if the process ended.
    """
    if not pid:
        return False
    pid = int(pid)
    if _POSIX:
        import signal

        try:
            pgid = os.getpgid(pid)
        except (ProcessLookupError, PermissionError, OSError):
            pgid = None
        objetivo = pgid if pgid else pid
        for sig, pausa in ((signal.SIGTERM, espera), (signal.SIGKILL, 0)):
            try:
                os.killpg(objetivo, sig)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(objetivo, sig)
                except OSError:
                    return not vivo(pid)
            if pausa:
                for _ in range(int(pausa)):
                    time.sleep(1)
                    if not vivo(pid):
                        return True
        return not vivo(pid)
    try:
        p = subprocess.Popen(["taskkill", "/PID", str(pid), "/T", "/F"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.wait(timeout=10)
    except (OSError, subprocess.SubprocessError):
        return not vivo(pid)
    return not vivo(pid)


def _ruta_lock(nombre):
    carpeta = os.path.join(cfg.CONFIG_DIR, "loops")
    try:
        os.makedirs(carpeta, exist_ok=True, mode=0o700)
    except OSError:
        pass
    seguro = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(nombre))
    return os.path.join(carpeta, seguro + ".lock")


def adquirir(nombre):
    """Exclusive, non-blocking lock held for the loop's whole lifetime.

    Returns a handle to keep open until the loop ends, or None if another loop
    already holds it. The kernel releases the lock when the process dies, so a
    crash cannot leave a stale lock behind. On platforms without `fcntl`
    it degrades to `SIN_LOCK` (always acquired; liveness then relies on the
    pid registry).
    """
    if not _POSIX:
        return SIN_LOCK
    try:
        import fcntl
    except ImportError:
        return SIN_LOCK
    try:
        fh = open(_ruta_lock(nombre), "w")
    except OSError:
        return SIN_LOCK
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def liberar(handle):
    """Releases a lock handle returned by `adquirir` (no-op for SIN_LOCK)."""
    if handle is None or handle is SIN_LOCK:
        return
    try:
        handle.close()
    except (OSError, AttributeError):
        pass
