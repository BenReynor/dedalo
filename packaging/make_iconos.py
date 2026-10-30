#!/usr/bin/env python3
"""Generates packaging/icono.icns (macOS), packaging/icono.ico (Windows) and
packaging/icono.png (256 px, the AppImage icon) from dedalo/icono.svg.

Usage:
    python3 packaging/make_iconos.py

Run at the end of the build (build_linux.sh/build_macos.sh) and there is a
test that checks the generated files are still valid; if you change the
SVG, run it again and commit both files.

No screen or QApplication needed: it paints the SVG onto an offscreen QImage.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
SVG = RAIZ / "dedalo" / "icono.svg"
ICNS = Path(__file__).resolve().parent / "icono.icns"
ICO = Path(__file__).resolve().parent / "icono.ico"
# appimagetool only accepts a PNG/XPM icon (and needs .DirIcon) since 2026.
PNG = Path(__file__).resolve().parent / "icono.png"
TAMANOS = [16, 32, 64, 128, 256, 512, 1024]


def _png(svg: QSvgRenderer, tam: int) -> Image.Image:
    img = QImage(tam, tam, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    pintor = QPainter(img)
    svg.render(pintor, QRectF(0, 0, tam, tam))
    pintor.end()
    buf = QBuffer()
    buf.open(QBuffer.WriteOnly)
    if not img.save(buf, "PNG"):
        raise RuntimeError(f"no pude pintar el icono a {tam}x{tam}")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def generar() -> None:
    svg = QSvgRenderer(str(SVG))
    if not svg.isValid():
        raise RuntimeError(f"SVG inválido: {SVG}")
    iconos = {tam: _png(svg, tam) for tam in TAMANOS}

    # .icns: Pillow writes ic07..ic14 (embedded PNGs); pass the exact sizes
    # so it does not have to rescale.
    iconos[1024].save(ICNS, append_images=[iconos[t] for t in TAMANOS])

    # .ico: same, with the sizes Windows expects (up to 256).
    chicos = [t for t in TAMANOS if t <= 256]
    iconos[256].save(ICO, sizes=[(t, t) for t in chicos],
                     append_images=[iconos[t] for t in chicos])

    iconos[256].save(PNG)

    for ruta in (ICNS, ICO, PNG):
        try:
            nombre = ruta.relative_to(RAIZ)
        except ValueError:          # temporary destination (tests)
            nombre = ruta
        print(f"{nombre}  {ruta.stat().st_size} bytes")


if __name__ == "__main__":
    try:
        generar()
    except Exception as exc:  # noqa: BLE001 — clear message and exit != 0
        print(f"make_iconos: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
