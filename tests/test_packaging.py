"""Tests for packaging: generated icons and the PyInstaller spec.

The macOS build cannot be run on Linux, so what is covered here is what can be
checked on any OS: that the spec is valid Python, that the committed icons are
readable and that the generator still works (if it breaks, the Windows/macOS
build would fail when it finds a corrupt .ico/.icns).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
PACKAGING = RAIZ / "packaging"


def test_spec_es_python_sintactico():
    """The spec can only be checked with compile(): PyInstaller injects
    SPECPATH/Analysis/EXE... at runtime."""
    fuente = (PACKAGING / "dedalo.spec").read_text(encoding="utf-8")
    compile(fuente, "dedalo.spec", "exec")
    assert "BUNDLE" in fuente and "icono.icns" in fuente, (
        "falta el bundle .app de macOS en la spec")
    assert "icono.ico" in fuente, "Windows necesita un .ico, no un .svg"


def test_iconos_generados_son_validos():
    Image = pytest.importorskip("PIL.Image")

    icns = Image.open(PACKAGING / "icono.icns")
    assert icns.format == "ICNS"
    pixeles = {s[0] * s[2] for s in icns.info["sizes"]}
    assert max(pixeles) >= 512, f"icns demasiado pequeño: {pixeles}"

    ico = Image.open(PACKAGING / "icono.ico")
    assert ico.format == "ICO"
    assert max(ancho for ancho, _ in ico.info["sizes"]) == 256


def test_build_windows_smk_checkea_el_motor_empaquetado():
    """The Windows build smoke test must validate the `--dedalo-loop` branch
    of the entrypoint (if someone removes it, the zip is produced but the
    packaged engine is left unverified)."""
    fuente = (PACKAGING / "build_windows.sh").read_text(encoding="utf-8")
    assert "--dedalo-loop" in fuente
    assert "Compress-Archive" in fuente
    assert "ABORTADO: agente no disponible" in fuente


def test_make_iconos_regenera_desde_el_svg(tmp_path, monkeypatch):
    """Runs the real generator against a temporary destination: if the SVG or
    the path change unexpectedly, the build finds out here and not in CI."""
    Image = pytest.importorskip("PIL.Image")
    pytest.importorskip("PySide6.QtSvg")

    ruta = PACKAGING / "make_iconos.py"
    spec = importlib.util.spec_from_file_location("make_iconos_prueba", ruta)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod, "ICNS", tmp_path / "icono.icns")
    monkeypatch.setattr(mod, "ICO", tmp_path / "icono.ico")
    monkeypatch.setattr(mod, "PNG", tmp_path / "icono.png")
    mod.generar()

    assert Image.open(tmp_path / "icono.icns").format == "ICNS"
    assert Image.open(tmp_path / "icono.ico").format == "ICO"
    png = Image.open(tmp_path / "icono.png")
    assert png.format == "PNG" and png.size == (256, 256)   # icono del AppImage
