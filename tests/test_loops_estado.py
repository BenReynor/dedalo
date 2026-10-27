"""Tests for the shared loop registry (`dedalo.loops_estado`).

It is the single source of truth the GUI and the MCP server both read, so an
external AI (MCP) and the panel see the same running state and cannot launch a
duplicate loop for the same project.
"""

import os
import subprocess
import sys

import pytest

from dedalo import loops_estado as le


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    """Redirects the registry and the lock directory to a temp path."""
    monkeypatch.setattr(le, "RUTA", str(tmp_path / "loops.json"))
    monkeypatch.setattr(le, "_RUTA_LEGACY", str(tmp_path / "loops_legacy.json"))
    monkeypatch.setattr(le.cfg, "CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path


def _pid_muerto():
    """A pid that is guaranteed not to be alive (a finished child)."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_registrar_estado_olvidar(aislado):
    le.registrar("p1", os.getpid(), origen="gui")
    est = le.estado("p1")
    assert est["corriendo"] is True
    assert est["pid"] == os.getpid()
    assert est["origen"] == "gui"
    le.olvidar("p1")
    assert le.estado("p1")["corriendo"] is False


def test_pid_muerto_se_limpia(aislado):
    le.registrar("p2", _pid_muerto(), origen="mcp")
    est = le.estado("p2")
    assert est["corriendo"] is False
    assert est["pid"] is None
    # The stale entry must have been dropped from the file, not just reported.
    assert "p2" not in le._leer()


def test_proyecto_desconocido_no_corre(aislado):
    assert le.estado("no-existe")["corriendo"] is False


@pytest.mark.skipif(not le._POSIX, reason="fcntl/flock is POSIX-only")
def test_lock_es_exclusivo(aislado):
    h1 = le.adquirir("p1")
    assert h1 is not None
    # A second acquisition (even in the same process) must fail.
    assert le.adquirir("p1") is None
    le.liberar(h1)
    h2 = le.adquirir("p1")
    assert h2 is not None
    le.liberar(h2)


@pytest.mark.skipif(le._POSIX, reason="on POSIX the real lock is used")
def test_lock_degradado_sin_flock(aislado):
    """Without fcntl there is no real lock: it degrades to SIN_LOCK (truthy)."""
    h1 = le.adquirir("p1")
    h2 = le.adquirir("p1")
    assert h1 is le.SIN_LOCK and h2 is le.SIN_LOCK
    le.liberar(h1)


def test_lock_por_nombre_es_independiente(aislado):
    h1 = le.adquirir("p1")
    h2 = le.adquirir("p2")
    assert h1 is not None and h2 is not None
    le.liberar(h1)
    le.liberar(h2)


def test_matar_pid_muerto_devuelve_true(aislado):
    assert le.matar(_pid_muerto()) is True


def test_matar_pid_vacio_devuelve_false(aislado):
    assert le.matar(None) is False


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="zombie detection reads /proc")
def test_vivo_considera_muerto_a_un_zombie():
    """An exited child nobody reaped yet is a zombie: signal 0 still works on
    it, but the loop is over (detener_loop said "sigue vivo" forever)."""
    import time
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    fin = time.time() + 10
    while time.time() < fin:
        try:
            with open(f"/proc/{proc.pid}/stat") as f:
                if f.read().rsplit(")", 1)[1].split()[0] == "Z":
                    break
        except OSError:
            break
        time.sleep(0.05)
    try:
        assert le.vivo(proc.pid) is False
    finally:
        proc.wait()
