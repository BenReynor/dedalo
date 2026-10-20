#!/usr/bin/env python3
"""Tests for dedalo.sh signals: "Detener" has to stop the loop.

Regression of `trap limpiar_sesiones EXIT TERM INT`, which had three failures:

  1. A trap does not stop a script. Bash runs the handler and continues with the
     loop, so the GUI had to wait 5 s and resort to SIGKILL.
  2. With EXIT and TERM/INT on the same line, cleanup ran TWICE for a single
     signal (one in the signal's trap and another on exit).
  3. The costliest one: with the agent in the FOREGROUND, bash postpones the trap
     handler until the child finishes, because that is how a non-interactive
     shell works. Translated: "Detener" did nothing while opencode kept
     working, which is exactly when stopping is most urgent.

These tests scaffold a real git project and a fake agent and send a real SIGTERM,
measuring that the script finishes soon and that no grandchildren remain alive.
"""

import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RAIZ = Path(__file__).resolve().parent.parent
TMPDIR = Path(os.environ.get("TMPDIR", "/tmp"))

from dedalo import plantillas, rutas  # noqa: E402

pytestmark = pytest.mark.skipif(
    # On Windows the module has no os.killpg/os.getpgid and processes have no
    # POSIX group: even if Git Bash exists, this suite is not valid.
    shutil.which("bash") is None or os.name == "nt",
    reason="bash no disponible o sin semántica POSIX de señales")


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T", *args],
                   cwd=cwd, check=True, capture_output=True)


def _script_que_registra_y_espera(destino):
    """Writes its PID to `destino` and waits indefinitely."""
    return f'echo "$$" >> {destino}\nexec sleep 600\n'


def _agente_falso(dir_bin, rapido=False):
    """Fake agent. `rapido` makes it exit with 0 instead of hanging.

    It has to know how to respond to `session list` / `session delete`, because
    dedalo.sh invokes them in `limpiar_sesiones` on exit. Otherwise the test
    hangs during cleanup and it looks like SIGTERM does not work.
    """
    dir_bin.mkdir(parents=True, exist_ok=True)
    if rapido:
        cuerpo = f'echo "$$" >> {dir_bin}/pids.txt\nexit 0\n'
    else:
        cuerpo = _script_que_registra_y_espera(dir_bin / "pids.txt")
    bin = dir_bin / "opencode"
    bin.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        if [ "$1" = "session" ]; then
            case "$2" in
                list) echo "[]"; exit 0 ;;
                delete) exit 0 ;;
            esac
        fi
        {cuerpo}"""), encoding="utf-8")
    bin.chmod(0o755)
    return bin


def _escenario(tmp_path, agente_rapido=False):
    """Project with the framework copied, a one-task plan and a fake agent."""
    proyecto = tmp_path / "proyecto"
    proyecto.mkdir()
    _git("init", "-q", "-b", "master", cwd=proyecto)
    (proyecto / "plan.md").write_text(
        "# PLAN\n\n- [ ] #1 hacer algo\n      criterio: algo existe\n",
        encoding="utf-8")
    # Real installation: scripts and checks go under `.dedalo/` and the
    # generated .gitignore keeps the whole directory out of the repo (the
    # gate's `ruff check .` would otherwise lint the port's .py checks and the
    # baseline would abort). The plan.md written above is never overwritten.
    plantillas.instalar(str(proyecto))
    _git("add", "-A", cwd=proyecto)
    _git("commit", "-q", "-m", "base", cwd=proyecto)

    dir_bin = tmp_path / "bin"
    _agente_falso(dir_bin, rapido=agente_rapido)
    # GitHub runners' ICMP is blocked (and `ping` exists, so
    # hay_internet's curl fallback does not kick in): without these stubs these
    # tests would depend on the REAL network and abort with "sin internet".
    _stub_red(dir_bin, "ping")
    _stub_red(dir_bin, "curl")
    return proyecto, dir_bin


def _stub_red(dir_bin, nombre):
    """Fake ping/curl so `hay_internet` does not depend on the real network."""
    stub = dir_bin / nombre
    stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)


def _entorno(dir_bin):
    return {
        "PATH": f"{dir_bin}{os.pathsep}{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/tmp"),
        "MAX_ITER": "1",
        "REVISION_DUAL": "0",
        "REVISION_MANUAL": "0",
        "TIMEOUT_POR_TAREA": "600",
        "TIMEOUT_NAVEGADOR": "600",
        "MAX_COSTO": "0",
        "VOZ": "0",
        "CLI_OPENCODE": str(dir_bin / "opencode"),
        # Without pinning the agent, auto-detection may choose claude based on
        # the PATH and the test would not look at the fake binary.
        "AGENTE_TAREA": "opencode",
        "DEDALO_GATE_CONSENT": "1",
    }


def _arrancar(proyecto, env, marca):
    """Starts dedalo.sh and waits for the `marca` file to appear."""
    proc = subprocess.Popen(
        ["bash", rutas.dedalo_sh(str(proyecto)), "plan.md"],
        cwd=str(proyecto), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        # Own session: this way SIGTERM reaches the script and its whole family without
        # touching pytest, which shares a process group with this test.
        start_new_session=True,
    )
    limite = time.time() + 90
    while time.time() < limite and proc.poll() is None:
        if Path(marca).exists():
            return proc
        time.sleep(0.2)
    return proc


def _parar(proc, sig=signal.SIGTERM, timeout=25):
    """Sends the signal to the whole group and waits for the exit."""
    t0 = time.time()
    os.killpg(os.getpgid(proc.pid), sig)
    try:
        salida = proc.communicate(timeout=timeout)[0]
        return proc.returncode, salida or "", time.time() - t0
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        salida = proc.communicate()[0]
        return None, salida or "", time.time() - t0


def _pids_de(fichero):
    return [int(x) for x in Path(fichero).read_text().split() if x.strip()]


def _vivos(pids):
    return [p for p in pids if Path(f"/proc/{p}").exists()]


def test_sigterm_para_el_loop_y_no_deja_nietos(tmp_path):
    """SIGTERM with the agent working: it exits in 143 and no one stays alive."""
    proyecto, dir_bin = _escenario(tmp_path)
    env = _entorno(dir_bin)
    pids_txt = dir_bin / "pids.txt"

    proc = _arrancar(proyecto, env, pids_txt)
    assert pids_txt.exists(), "el agente nunca llegó a lanzarse"
    time.sleep(1.0)  # so it is already inside the sleep

    rc, salida, elapsed = _parar(proc, signal.SIGTERM)

    assert rc == 143, f"se esperaba exit 143, hubo {rc}:\n{salida[-2000:]}"
    assert elapsed < 20, (
        f"tardó {elapsed:.1f}s en parar, con el agente durmiendo 600 s")

    pids = _pids_de(pids_txt)
    assert pids, "no se pudo saber el pid del agente"
    time.sleep(1.0)
    supervivientes = _vivos(pids)
    assert not supervivientes, (
        f"el agente seguía vivo tras detener el loop: {supervivientes}")


def test_sigint_sale_con_130(tmp_path):
    """SIGINT uses the conventional code 130, not 143."""
    proyecto, dir_bin = _escenario(tmp_path)
    env = _entorno(dir_bin)
    pids_txt = dir_bin / "pids.txt"

    proc = _arrancar(proyecto, env, pids_txt)
    assert pids_txt.exists(), "el agente nunca llegó a lanzarse"
    time.sleep(1.0)

    rc, salida, _ = _parar(proc, signal.SIGINT)

    assert rc == 130, f"se esperaba exit 130, hubo {rc}:\n{salida[-2000:]}"


def test_una_sola_limpieza_por_senal(tmp_path):
    """The handler runs once: the log cannot repeat the cleanup."""
    proyecto, dir_bin = _escenario(tmp_path)
    env = _entorno(dir_bin)
    pids_txt = dir_bin / "pids.txt"

    proc = _arrancar(proyecto, env, pids_txt)
    assert pids_txt.exists(), "el agente nunca llegó a lanzarse"
    time.sleep(1.0)

    rc, salida, _ = _parar(proc, signal.SIGTERM)
    assert rc == 143, salida[-2000:]

    log = Path(rutas.log(str(proyecto)))
    texto = log.read_text(errors="replace") if log.exists() else ""
    # With the previous bug two cleanups appeared: one from the signal's trap and
    # another from the EXIT that came after.
    limpiezas = texto.count("Sesiones opencode eliminadas")
    assert limpiezas <= 1, (
        f"la limpieza se ejecutó {limpiezas} veces para una sola señal:\n"
        f"{texto[-2000:]}")


def test_no_quedan_ficheros_de_pid(tmp_path):
    """Neither by signal nor by normal exit should the PID file be left behind."""
    previos = set(TMPDIR.glob("dedalo_hijo.*.pid"))

    proyecto, dir_bin = _escenario(tmp_path)
    env = _entorno(dir_bin)
    pids_txt = dir_bin / "pids.txt"
    proc = _arrancar(proyecto, env, pids_txt)
    assert pids_txt.exists(), "el agente nunca llegó a lanzarse"
    time.sleep(1.0)

    rc, salida, _ = _parar(proc, signal.SIGTERM)
    assert rc == 143, salida[-2000:]

    nuevos = set(TMPDIR.glob("dedalo_hijo.*.pid")) - previos
    assert not nuevos, f"quedaron ficheros de PID tras parar: {nuevos}"


def test_gate_interruptible_no_deja_huerfanos(tmp_path):
    """The gate is also a process tree that has to be closed.

    The gate runs as the left side of a pipe, that is, in a subshell, so
    its PID does not reach the parent: that is why _matar_hijo also looks for it in a
    file. Here the agent finishes fine and the gate hangs, which is the
    real case: the gate launches the project's tests, which can take minutes.
    """
    proyecto, dir_bin = _escenario(tmp_path, agente_rapido=True)

    # Slow gate. It is replaced BEFORE starting so gate_intacto accepts it
    # (it compares against the copy the script makes at startup).
    pids_gate = tmp_path / "gate_pids.txt"
    Path(rutas.gate_sh(str(proyecto))).write_text(
        "#!/usr/bin/env bash\n"
        + _script_que_registra_y_espera(pids_gate), encoding="utf-8")

    env = _entorno(dir_bin)
    proc = _arrancar(proyecto, env, pids_gate)
    assert pids_gate.exists(), "el gate nunca llegó a ejecutarse"
    time.sleep(1.0)

    rc, salida, elapsed = _parar(proc, signal.SIGTERM)

    assert rc == 143, f"se esperaba exit 143, hubo {rc}:\n{salida[-2000:]}"
    assert elapsed < 20, f"tardó {elapsed:.1f}s en parar con el gate colgado"

    pids = _pids_de(pids_gate)
    assert pids, "no se pudo saber el pid del gate"
    time.sleep(1.0)
    supervivientes = _vivos(pids)
    assert not supervivientes, (
        f"el gate seguía vivo tras detener el loop: {supervivientes}")
