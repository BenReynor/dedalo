#!/usr/bin/env python3
"""Subprocess control of the native loop.

Port of `_timeout`/`_matar_hijo`/`limpiar_sesiones` of dedalo.sh:
execution with a time cap and killing the whole process GROUP (the direct
child is usually `timeout` and the agent hangs off it; it only works if the
group is killed). In Python there is no need for the intermediate PID file: the
Popen keeps the process and cleanup lives in the engine; the same sentinel
`124` from GNU timeout is kept so the loop recognizes the cutoff.
"""

import json
import os
import signal
import subprocess
import time

_POSIX = os.name == "posix"

RC_TIMEOUT = 124  # same sentinel as GNU timeout / the script's _timeout


def _golpe_grupo(proc, espera=5):
    """SIGTERM to the process group; if still alive after `espera`s, SIGKILL."""
    def _kill(sig):
        if _POSIX:
            try:
                os.killpg(proc.pid, sig)
                return
            except (ProcessLookupError, PermissionError):
                return
        try:
            proc.kill()
        except OSError:
            pass

    _kill(signal.SIGTERM)
    for _ in range(espera):
        if proc.poll() is not None:
            return
        time.sleep(1)
    if proc.poll() is None:
        _kill(signal.SIGKILL)


def matar_grupo(proc, espera=5):
    """Kills a process and its WHOLE group (children included), TERM→KILL.

    For the engine's signal path: the loop's SIGTERM/SIGINT handler
    needs to kill the agent even while `run_con_timeout` is still blocked. The
    same running proc is passed; `espera=0` cuts instantly (direct KILL).
    """
    return _golpe_grupo(proc, espera)


def run_con_timeout(cmd, timeout, *, env=None, cwd=None,
                    stdout=None, stderr=None, vivo=None, entrada=None):
    """Runs `cmd` with a `timeout`-second cap.

    Returns `(returncode, salida, timed_out)`:
      · timed_out True if it exceeded the cap → returncode = RC_TIMEOUT (124) and
        the whole group was TERM→KILL'd, like the script's `_timeout` does.
      · `salida` = (stdout_bytes, stderr_bytes); if `stdout`/`stderr` are
        files or None, returns None in that position (like communicate).
      · Starts the child in its OWN session/group (start_new_session), so
        that `killpg(pid)` also takes down the agent hanging off it.
      · `vivo`: optional dictionary; filled with {"proc": Popen} BEFORE
        blocking so a signal handler can kill the group.
      · `entrada`: bytes for the child's stdin. Without it stdin is /dev/null,
        never the parent's: under the GUI that is an open pipe, and
        `claude -p` waits 3 s on it before every call.
    """
    kwargs = dict(env=env, cwd=cwd, stdout=stdout, stderr=stderr,
                  stdin=subprocess.PIPE if entrada is not None
                  else subprocess.DEVNULL)
    if _POSIX:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    if vivo is not None:
        vivo["proc"] = proc
    timed_out = False
    try:
        try:
            salida = proc.communicate(input=entrada, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _golpe_grupo(proc)
            salida = proc.communicate()
    finally:
        if proc.poll() is None:
            _golpe_grupo(proc, espera=0)
    rc = RC_TIMEOUT if timed_out else proc.returncode
    return rc, salida, timed_out


def limpiar_sesiones(binario, proyecto, desde_ms, log, log_resultado=None):
    """Deletes the opencode sessions created by this run in `proyecto`.

    Port of the script's `limpiar_sesiones()` with the same criterion
    (directory == proyecto and created >= desde_ms), but WITHOUT dependency on
    `jq` (the JSON is parsed with the stdlib). Each CLI call goes with a
    20 s cap: this function is on the stop path and cannot
    hang. Returns the number of deleted sessions.
    """
    if not binario or not os.path.exists(binario):
        return 0
    if not proyecto or not os.path.isdir(str(proyecto)):
        return 0

    def _session_list():
        rc, salida, _t = run_con_timeout(
            [binario, "session", "list", "--format", "json"], 20,
            cwd=str(proyecto),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if rc != 0 and not salida[0]:
            return []
        try:
            datos = json.loads(salida[0].decode("utf-8", "replace") or "[]")
        except ValueError:
            return []
        if not isinstance(datos, list):
            return []
        return datos

    borradas = 0
    for sesion in _session_list():
        if not isinstance(sesion, dict):
            continue
        if (sesion.get("directory") == str(proyecto)
                and sesion.get("created", 0) >= desde_ms):
            sid = sesion.get("id")
            if not sid:
                continue
            run_con_timeout([binario, "session", "delete", str(sid)], 20,
                            cwd=str(proyecto),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
            borradas += 1
    if borradas and log:
        mensaje = (
            f"[dedalo] Sesiones opencode eliminadas: {borradas}"
        )
        if log_resultado is not None:
            log_resultado(mensaje)
        else:
            try:
                with open(log, "a", encoding="utf-8") as f:
                    f.write(mensaje + "\n")
            except OSError:
                pass
    return borradas
