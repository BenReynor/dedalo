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


def test_lock_es_exclusivo(aislado):
    h1 = le.adquirir("p1")
    assert h1 is not None
    # A second acquisition (even in the same process) must fail.
    assert le.adquirir("p1") is None
    le.liberar(h1)
    h2 = le.adquirir("p1")
    assert h2 is not None
    le.liberar(h2)


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
