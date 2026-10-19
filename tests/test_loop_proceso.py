#!/usr/bin/env python3
"""Tests for loop_proceso.py - subprocess control of the native loop.

The timeout tests assume POSIX (start_new_session + killpg). On Windows the
native engine is still in the future; the helpers do not crash on import, but
these scenarios are skipped.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dedalo.loop_proceso import (
    RC_TIMEOUT,
    limpiar_sesiones,
    run_con_timeout,
)

POSIX = os.name == "posix"

pytestmark = pytest.mark.skipif(
    not POSIX, reason="muerte de grupos de procesos: POSIX")


def test_comando_normal_exit_code():
    rc, salida, timed_out = run_con_timeout(["sh", "-c", "exit 3"], 10)
    assert rc == 3
    assert timed_out is False
    assert salida == (None, None)


def test_comando_con_stdout_pipe():
    rc, (out, _err), timed_out = run_con_timeout(
        ["sh", "-c", "echo hola"], 10, stdout=subprocess.PIPE)
    assert rc == 0
    assert timed_out is False
    assert out.strip() == b"hola"


def test_timeout_devuelve_124():
    t0 = __import__("time").monotonic()
    rc, _salida, timed_out = run_con_timeout(["sleep", "30"], 1)
    elapsed = __import__("time").monotonic() - t0
    assert timed_out is True
    assert rc == RC_TIMEOUT
    assert elapsed < 8  # TERM kills before the 5s grace


def test_timeout_mata_tambien_al_hijo_colgado():
    # The direct child leaves a grandchild waiting in the same group: if we
    # only killed the first one, the grandchild would be left orphaned (bug that
    # _matar_hijo solves with pgrep; here killpg covers the whole group).
    t0 = __import__("time").monotonic()
    rc, (out, _err), timed_out = run_con_timeout(
        ["sh", "-c", "sleep 60 & echo $!; wait"],
        1, stdout=subprocess.PIPE)
    elapsed = __import__("time").monotonic() - t0
    assert timed_out is True
    assert rc == RC_TIMEOUT
    assert elapsed < 8
    nieto = int(out.strip())
    vivo = True
    for _ in range(10):
        try:
            os.kill(nieto, 0)
        except (ProcessLookupError, PermissionError):
            vivo = False
            break
        __import__("time").sleep(0.2)
    assert vivo is False, "el nieto quedó huérfano con vida"


def _stub_opencode(dir_bin, sesiones, log_ruta):
    """Creates a fake `opencode` that responds to `session list/delete`.

    The JSON of `session list` travels through the SESIONES_JSON environment
    variable (the stub inherits the test's environment), and each
    `session delete <id>` is recorded in `log_ruta` to be able to check what
    was deleted.
    """
    os.environ["SESIONES_JSON"] = json.dumps([
        {"id": k, "directory": dir_, "created": c}
        for k, dir_, c in sesiones["lista"]
    ])
    dir_bin.mkdir(parents=True, exist_ok=True)
    texto = (
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = session ] && [ \"$2\" = list ]; then\n"
        "  printf '%s\\n' \"$SESIONES_JSON\"\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = session ] && [ \"$2\" = delete ]; then\n"
        "  echo \"$3\" >> '{LOG}'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    ).replace("{LOG}", log_ruta)
    binario = dir_bin / "opencode"
    binario.write_text(texto, encoding="utf-8")
    binario.chmod(0o755)
    return str(binario)


def test_limpiar_sesiones_filtra_y_borra(tmp_path):
    if not shutil.which("bash"):
        pytest.skip("bash obligatorio para el stub")
    proy = str(tmp_path / "proyecto")
    (tmp_path / "proyecto").mkdir()
    log_ruta = str(tmp_path / "deleted.log")
    stub = _stub_opencode(
        tmp_path / "bin", {
            "lista": [
                ("a1", proy, 2000),
                ("b2", "/otro", 2000),
                ("c3", proy, 500),
            ],
        }, log_ruta)
    n = limpiar_sesiones(stub, proy, desde_ms=1000, log=str(tmp_path / "run.log"))
    assert n == 1
    with open(log_ruta, encoding="utf-8") as f:
        borradas = f.read().split()
    assert borradas == ["a1"]
    with open(tmp_path / "run.log", encoding="utf-8") as f:
        assert "Sesiones opencode eliminadas: 1" in f.read()


def test_limpiar_sesiones_sin_binario():
    assert limpiar_sesiones("", "/proy", 0, None) == 0
    assert limpiar_sesiones("/no/existe/opencode", "/proy", 0, None) == 0


def test_limpiar_sesiones_json_invalido_no_revienta(tmp_path):
    if not shutil.which("bash"):
        pytest.skip("bash obligatorio para el stub")
    binario = tmp_path / "opencode"
    binario.write_text(
        "#!/usr/bin/env bash\necho 'no-soy-json'\nexit 0\n", encoding="utf-8")
    binario.chmod(0o755)
    assert limpiar_sesiones(str(binario), "/proy", 0, None) == 0


def test_limpiar_sesiones_corre_en_el_proyecto(tmp_path):
    """The CLI is invoked with cwd=<project>: opencode scopes its sessions by
    the working directory, so running from the caller's cwd lists (and could
    delete) sessions of an unrelated project."""
    if not shutil.which("bash"):
        pytest.skip("bash obligatorio para el stub")
    proy = tmp_path / "proyecto"
    proy.mkdir()
    cwd_log = tmp_path / "cwd.log"
    binario = tmp_path / "opencode"
    binario.write_text(
        "#!/usr/bin/env bash\n"
        f'printf \'%s\\n\' "$PWD" >> "{cwd_log}"\n'
        'echo "[]"\n', encoding="utf-8")
    binario.chmod(0o755)
    limpiar_sesiones(str(binario), str(proy), 0, None)
    assert cwd_log.read_text(encoding="utf-8").split() == [str(proy)]
