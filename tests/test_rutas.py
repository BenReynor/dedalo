#!/usr/bin/env python3
"""Tests for the `.dedalo/` layout: migration of old projects and helpers."""

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from dedalo import plantillas, rutas  # noqa: E402
from dedalo.loop import Config  # noqa: E402

# On Windows `bash` is usually the WSL stub (no distribution) and these scripts
# are POSIX; the rest of the module is portable Python.
SIN_BASH = pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt",
    reason="requiere bash POSIX")


def _proyecto():
    return tempfile.mkdtemp(prefix="dedalo-rutas-")


def test_asegurar_crea_arbol_y_log():
    tmp = _proyecto()
    try:
        assert rutas.es_nuevo(tmp) is False
        info = rutas.asegurar(tmp)
        assert rutas.es_nuevo(tmp) is True
        for directorio in (rutas.dir_scripts(tmp), rutas.dir_estado(tmp),
                           os.path.join(tmp, ".dedalo", "review")):
            assert os.path.isdir(directorio)
        assert os.path.isfile(rutas.log(tmp))
        assert "progreso.log" in info["creados"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_asegurar_migra_ficheros_del_root():
    tmp = _proyecto()
    try:
        for nombre in ("gate.sh", "dedalo.sh", "mapear.sh", "progreso.log",
                       "metrics.jsonl", "mapeo.txt"):
            with open(os.path.join(tmp, nombre), "w", encoding="utf-8") as f:
                f.write("contenido")
        os.makedirs(os.path.join(tmp, "gate_checks"))
        with open(os.path.join(tmp, "gate_checks", "01_x.sh"), "w",
                  encoding="utf-8") as f:
            f.write("exit 0\n")
        os.makedirs(os.path.join(tmp, ".dedalo_review"))
        with open(os.path.join(tmp, ".dedalo_review", "waiting"), "w",
                  encoding="utf-8") as f:
            f.write("")

        info = rutas.asegurar(tmp)

        for nombre in ("gate.sh", "dedalo.sh", "mapear.sh", "gate_checks",
                       "progreso.log", "metrics.jsonl", "mapeo.txt",
                       ".dedalo_review"):
            assert nombre in info["migrados"]
            assert not os.path.exists(os.path.join(tmp, nombre))
        assert os.path.isfile(os.path.join(rutas.dir_scripts(tmp), "gate.sh"))
        assert os.path.isfile(os.path.join(rutas.gate_checks(tmp), "01_x.sh"))
        assert os.path.isfile(os.path.join(rutas.dir_estado(tmp), "progreso.log"))
        assert os.path.isfile(os.path.join(rutas.dir_review(tmp), "waiting"))
        with open(rutas.log(tmp), encoding="utf-8") as f:
            assert f.read() == "contenido", "no debe perder el log existente"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_asegurar_es_idempotente():
    tmp = _proyecto()
    try:
        rutas.asegurar(tmp)
        segundo = rutas.asegurar(tmp)
        assert segundo["migrados"] == []
        assert segundo["creados"] == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_resuelve_layout_legacy_y_nuevo():
    tmp = _proyecto()
    try:
        assert rutas.gate_sh(tmp) == os.path.join(tmp, "gate.sh")
        assert rutas.log(tmp) == os.path.join(tmp, "progreso.log")
        assert rutas.dir_review(tmp) == os.path.join(tmp, ".dedalo_review")

        rutas.asegurar(tmp)

        assert rutas.gate_sh(tmp) == os.path.join(tmp, ".dedalo", "scripts",
                                                  "gate.sh")
        assert rutas.log(tmp) == os.path.join(tmp, ".dedalo", "estado",
                                              "progreso.log")
        assert rutas.dir_review(tmp) == os.path.join(tmp, ".dedalo", "review")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_config_usa_el_layout_del_proyecto():
    tmp = _proyecto()
    try:
        cfg = Config(_args(tmp), proyecto=tmp)
        assert cfg.gate == os.path.join(tmp, "gate.sh")

        rutas.asegurar(tmp)
        cfg = Config(_args(tmp), proyecto=tmp)
        assert cfg.gate == os.path.join(tmp, ".dedalo", "scripts", "gate.sh")
        assert cfg.log == os.path.join(tmp, ".dedalo", "estado", "progreso.log")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _args(proyecto):
    class _Args:
        plan = os.path.join(proyecto, "plan.md")
        padre = ""
        push = ""
        hasta = ""
        trabajo = ""

    return _Args()


def test_instalar_usa_el_arbol_nuevo():
    tmp = _proyecto()
    try:
        creados = plantillas.instalar(tmp)
        assert ".dedalo/scripts/gate.sh" in creados
        assert ".dedalo/scripts/gate_checks/01_db.sh" in creados
        assert ".dedalo/estado/progreso.log" in creados
        assert "plan.md" in creados
        # Project content stays at the root and the framework is gitignored
        assert os.path.isfile(os.path.join(tmp, "plan.md"))
        assert not os.path.exists(os.path.join(tmp, "gate.sh"))
        with open(os.path.join(tmp, ".gitignore"), encoding="utf-8") as f:
            assert ".dedalo/" in f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_quitar_limpia_el_arbol_nuevo():
    tmp = _proyecto()
    try:
        plantillas.instalar(tmp)
        plantillas.quitar(tmp)
        assert not os.path.exists(os.path.join(tmp, ".dedalo"))
        assert not os.path.exists(os.path.join(tmp, "plan.md"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@SIN_BASH
def test_env_sh_detecta_la_raiz_desde_dedalo_scripts():
    tmp = _proyecto()
    try:
        plantillas.instalar(tmp)
        env_sh = os.path.join(rutas.gate_checks(tmp), "_env.sh")
        r = subprocess.run(
            ["bash", "-c", f'source "{env_sh}"; printf %s "$PROYECTO"'],
            capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        assert os.path.realpath(r.stdout) == os.path.realpath(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@SIN_BASH
def test_gate_sh_funciona_desde_dedalo_scripts():
    tmp = _proyecto()
    try:
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        plantillas.instalar(tmp)
        gate = rutas.gate_sh(tmp)
        r = subprocess.run(["bash", gate], capture_output=True, text=True,
                           timeout=120, cwd=tmp)
        assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
        assert "TODO OK" in r.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@SIN_BASH
def test_mapear_sh_usa_la_raiz_del_proyecto():
    tmp = _proyecto()
    try:
        plantillas.instalar(tmp)
        mapear = rutas.mapear_sh(tmp)
        r = subprocess.run(["bash", mapear], capture_output=True, text=True,
                           timeout=60)
        assert r.returncode == 0, r.stderr
        # macOS /var is a symlink to /private/var: accept both forms.
        assert tmp in r.stdout or os.path.realpath(tmp) in r.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
