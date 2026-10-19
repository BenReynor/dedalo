"""Tests for the shortcut installed by `dedalo/acceso.sh`.

The launcher it generates is dynamic (it searches the disk for the project
marker), which made it ambiguous when more than one checkout was around: the
first one `find` listed used to win, so the shortcut opened stale code.

The generated launcher now pins the checkout that installed it and only falls
back to the search (newest version first) when that checkout is gone.
"""

import os
import shutil
import subprocess

import pytest

from tests.test_portabilidad import RAIZ

# acceso.sh installs a Linux desktop shortcut (.desktop + xdg-user-dir): the
# script makes no sense on Windows and Git Bash cannot run it there.
pytestmark = pytest.mark.skipif(os.name == "nt",
                                reason="Linux desktop shortcut installer")


def _proyecto(base, nombre, version):
    """Fake checkout: the launcher only needs the markers and lanzar.sh."""
    proy = base / nombre
    pkg = proy / "dedalo"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "icono.svg").write_text("<svg/>", encoding="utf-8")
    shutil.copy(RAIZ / "dedalo" / "acceso.sh", pkg / "acceso.sh")
    (proy / "pyproject.toml").write_text(
        f'[project]\nname = "{nombre}"\nversion = "{version}"\n',
        encoding="utf-8")
    lanzar = proy / "lanzar.sh"
    lanzar.write_text('#!/usr/bin/env bash\necho "LAUNCH:$(dirname "$0")"\n',
                      encoding="utf-8")
    lanzar.chmod(0o755)
    return proy


def _instalar(proy, home):
    env = {**os.environ, "HOME": str(home)}
    env.pop("XDG_CONFIG_HOME", None)
    subprocess.run(["bash", str(proy / "dedalo" / "acceso.sh")],
                   env=env, check=True, capture_output=True, text=True)
    return env


def _lanzar(home, env):
    return subprocess.run([str(home / ".local" / "bin" / "dedalo")],
                          env=env, check=True, capture_output=True, text=True)


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_el_acceso_usa_el_proyecto_que_lo_instalo(tmp_path):
    """Two checkouts on disk: the shortcut must open the one that installed it,
    even if the other one has a higher version."""
    home = tmp_path / "home"
    escritorio = home / "Escritorio"
    escritorio.mkdir(parents=True)
    viejo = _proyecto(escritorio, "viejo", "2.0.1")
    _proyecto(escritorio, "nuevo", "2.0.2")

    env = _instalar(viejo, home)
    out = _lanzar(home, env)
    assert f"LAUNCH:{viejo}" in out.stdout, out.stdout + out.stderr


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_el_acceso_cae_en_la_version_mas_nueva_si_desaparece(tmp_path):
    """Moving/renaming the pinned checkout must keep the shortcut working."""
    home = tmp_path / "home"
    escritorio = home / "Escritorio"
    escritorio.mkdir(parents=True)
    viejo = _proyecto(escritorio, "viejo", "2.0.1")
    nuevo = _proyecto(escritorio, "nuevo", "2.0.2")

    env = _instalar(viejo, home)
    (viejo / "lanzar.sh").unlink()
    out = _lanzar(home, env)
    assert f"LAUNCH:{nuevo}" in out.stdout, out.stdout + out.stderr
