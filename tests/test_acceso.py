"""Tests for the shortcut installed by `dedalo/acceso.sh`.

The launcher it generates is dynamic (it searches the disk for the project
marker). With more than one checkout around — an old copy left in place — the
first one `find` listed used to win, so the shortcut opened stale code.
"""

import os
import shutil
import subprocess

import pytest

from tests.test_portabilidad import RAIZ


def _proyecto(base, nombre, version):
    """Fake checkout: the launcher only needs the markers and lanzar.sh."""
    proy = base / nombre
    pkg = proy / "dedalo"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "icono.svg").write_text("<svg/>", encoding="utf-8")
    (proy / "pyproject.toml").write_text(
        f'[project]\nname = "{nombre}"\nversion = "{version}"\n',
        encoding="utf-8")
    lanzar = proy / "lanzar.sh"
    lanzar.write_text('#!/usr/bin/env bash\necho "LAUNCH:$(dirname "$0")"\n',
                      encoding="utf-8")
    lanzar.chmod(0o755)
    return proy


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_el_acceso_prefiere_la_version_mas_nueva(tmp_path):
    home = tmp_path / "home"
    escritorio = home / "Escritorio"
    escritorio.mkdir(parents=True)
    _proyecto(escritorio, "viejo", "2.0.1")
    nuevo = _proyecto(escritorio, "nuevo", "2.0.2")

    env = {**os.environ, "HOME": str(home)}
    env.pop("XDG_CONFIG_HOME", None)
    subprocess.run(["bash", str(RAIZ / "dedalo" / "acceso.sh")],
                   env=env, check=True, capture_output=True, text=True)

    out = subprocess.run([str(home / ".local" / "bin" / "dedalo")],
                         env=env, check=True, capture_output=True, text=True)
    assert f"LAUNCH:{nuevo}" in out.stdout, out.stdout + out.stderr
