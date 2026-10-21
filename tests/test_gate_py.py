#!/usr/bin/env python3
"""Tests for the portable orchestrator gate.py (port of gate.sh).

Mirror of tests/test_gate.py, but for the Python engine: it does NOT depend on
bash, so it also runs on Windows. Where the path without Git Bash matters, the
.py branch is forced by passing `bash=""` (empty string = "no bash"; `None`
means autodetect).

Verified contract (the same one loop.py consumes):
  · a check that fails -> rc != 0 and NEVER "[GATE] ✅ TODO OK";
  · a check that blows up -> rc != 0 (not a false green);
  · all OK -> rc 0 + "[GATE] ✅ TODO OK";
  · no checks or no gate_checks/ -> rc 0 with a warning;
  · with bash the .sh is preferred; without bash the .py is used.
"""

import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dedalo import gate  # noqa: E402

CHECK_FALLA = "def run(env):\n    env.fail('algo va mal')\n    return 1\n"
CHECK_OK = "def run(env):\n    env.ok('todo en orden')\n    return 0\n"
CHECK_REVIENTA = "def run(env):\n    raise RuntimeError('boom')\n"


def _escenario(tmp_path, checks):
    proyecto = tmp_path / "proyecto"
    (proyecto / "gate_checks").mkdir(parents=True)
    for nombre, cuerpo in checks.items():
        (proyecto / "gate_checks" / nombre).write_text(cuerpo, encoding="utf-8")
    return proyecto


def test_gate_falla_si_algun_check_falla(tmp_path, capsys):
    proyecto = _escenario(tmp_path, {"01_falla.py": CHECK_FALLA})
    rc = gate.correr(str(proyecto), bash="")
    salida = capsys.readouterr().out
    assert rc != 0, salida
    assert "TODO OK" not in salida, salida


def test_gate_pasa_si_todos_los_checks_pasan(tmp_path, capsys):
    proyecto = _escenario(tmp_path, {"01_ok.py": CHECK_OK})
    rc = gate.correr(str(proyecto), bash="")
    salida = capsys.readouterr().out
    assert rc == 0, salida
    assert "TODO OK" in salida, salida


def test_gate_check_que_revienta_no_da_verde(tmp_path, capsys):
    """A check with an exception must give rc != 0, not a silent false green."""
    proyecto = _escenario(tmp_path, {"01_boom.py": CHECK_REVIENTA})
    rc = gate.correr(str(proyecto), bash="")
    salida = capsys.readouterr().out
    assert rc != 0, salida
    assert "TODO OK" not in salida, salida


def test_gate_separa_un_check_que_falla_de_uno_que_pasa(tmp_path, capsys):
    """An early failure is not hidden behind a later check that passes."""
    proyecto = _escenario(tmp_path, {"01_falla.py": CHECK_FALLA,
                                     "02_ok.py": CHECK_OK})
    rc = gate.correr(str(proyecto), bash="")
    salida = capsys.readouterr().out
    assert rc != 0, salida
    assert "TODO OK" not in salida, salida
    assert "01_falla.py" in salida, salida


def test_gate_sin_checks_no_falla(tmp_path, capsys):
    proyecto = _escenario(tmp_path, {})
    rc = gate.correr(str(proyecto), bash="")
    salida = capsys.readouterr().out
    assert rc == 0, salida
    assert "se asume OK" in salida, salida


def test_gate_sin_dir_checks_avisa_y_no_falla(tmp_path, capsys):
    proyecto = tmp_path / "p"
    proyecto.mkdir()
    rc = gate.correr(str(proyecto), bash="")
    salida = capsys.readouterr().out
    assert rc == 0, salida
    assert "se asume OK" in salida, salida


def test_gate_check_sin_run_se_omite_avisando(tmp_path, capsys):
    proyecto = _escenario(tmp_path, {"01_x.py": "x = 1\n"})
    rc = gate.correr(str(proyecto), bash="")
    salida = capsys.readouterr().out
    assert rc == 0, salida
    assert "sin función run()" in salida, salida


@pytest.mark.skipif(shutil.which("bash") is None, reason="sin bash")
def test_prefiere_sh_con_bash_y_py_sin_bash(tmp_path, capsys):
    """With bash the .sh check wins; without bash the .py with the same prefix is used."""
    proyecto = _escenario(tmp_path, {"01_x.py": CHECK_FALLA})
    (proyecto / "gate_checks" / "01_x.sh").write_text(
        'ok "sh gana"\n', encoding="utf-8")
    # With bash -> the .sh runs (green even though the .py would fail).
    assert gate.correr(str(proyecto), bash=shutil.which("bash")) == 0
    capsys.readouterr()
    # Without bash -> the .py runs (red).
    assert gate.correr(str(proyecto), bash="") != 0


def test_env_django_define_db_check_por_defecto(tmp_path):
    """Django backend (manage.py): DB_CHECK takes the pg_isready from _env.sh.

    Regression: the Django branch called `_db_por_defecto`, which did not
    exist, and blew up with NameError. It only activates with manage.py, which
    is why no test covered it until now."""
    from dedalo import gate_env
    proyecto = tmp_path / "p"
    (proyecto / "Backend").mkdir(parents=True)
    (proyecto / "Backend" / "manage.py").write_text("", encoding="utf-8")
    env = gate_env.detectar(str(proyecto),
                            environ={"PY_BACKEND": "/usr/bin/python3"})
    assert env.db_check is not None
    assert "pg_isready" in env.db_check.shell


def _proyecto_django(tmp_path):
    proyecto = tmp_path / "p"
    (proyecto / "Backend").mkdir(parents=True)
    (proyecto / "Backend" / "manage.py").write_text("", encoding="utf-8")
    return proyecto


def test_es_local_detecta_hosts_locales():
    from dedalo.gate_env import _es_local
    assert _es_local("http://localhost:8000")
    assert _es_local("http://127.0.0.1:8000/api/token/")
    assert _es_local("http://0.0.0.0:8000")
    assert not _es_local("https://miservidor.com")
    assert not _es_local("http://10.0.0.5:8000")
    assert not _es_local("")


def test_credenciales_dev_solo_para_localhost(tmp_path):
    """admin/admin123 is a development scaffold: NEVER to a remote host."""
    from dedalo import gate_env
    proyecto = _proyecto_django(tmp_path)

    local = gate_env.detectar(str(proyecto), environ={
        "PY_BACKEND": "/usr/bin/python3",
        "SERVE_URL": "http://localhost:8000"})
    assert local.usuario == "admin" and local.clave == "admin123"

    remoto = gate_env.detectar(str(proyecto), environ={
        "PY_BACKEND": "/usr/bin/python3",
        "SERVE_URL": "https://produccion.example.com",
        "TOKEN_URL": "https://produccion.example.com/api/token/"})
    assert remoto.usuario == "" and remoto.clave == ""


def test_credenciales_explicitas_se_respetan(tmp_path):
    from dedalo import gate_env
    proyecto = _proyecto_django(tmp_path)
    env = gate_env.detectar(str(proyecto), environ={
        "PY_BACKEND": "/usr/bin/python3",
        "SERVE_URL": "https://produccion.example.com",
        "USUARIO": "ana", "CLAVE": "secreta"})
    assert env.usuario == "ana" and env.clave == "secreta"


def test_entorno_detener_limpia_el_grupo_lanzado(tmp_path):
    """The backend check may only stop the group it started itself."""
    from dedalo import gate_env

    env = gate_env.Entorno(
        proyecto=str(tmp_path), backend_dir=str(tmp_path), frontend_dir="",
        py_backend=sys.executable, py_frontend="", db_check=None,
        migrate_check=None, test_cmd=None,
        serve_cmd=gate_env.Comando(
            argv=[sys.executable, "-c", "import time; time.sleep(60)"]),
        serve_url="", token_url="", usuario="", clave="", endpoints=[])
    proc = env.lanzar(env.serve_cmd)
    assert proc is not None and proc.poll() is None
    assert env.detener(proc, espera=1) is True
    assert proc.poll() is not None
