"""Startup splash: what Dédalo is doing while the panel loads, with a real
progress bar.

Building the main window used to take ~10 s with nothing on screen: it asks
every installed agent CLI (claude, codex, opencode) one after another whether
it has a session. `precalentar_agentes` now runs those probes in parallel
before the window is built (it reads the same cache), and the splash reports
each one as it finishes.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from . import modelos
from .i18n import t

_ESTILO = """
QWidget#carga { background: #18181b; border: 1px solid #3f3f46; border-radius: 14px; }
QLabel { color: #e4e4e7; }
QLabel#titulo { font-size: 20px; font-weight: 700; color: #fcd34d; }
QLabel#paso { color: #a1a1aa; }
QProgressBar { background: #27272a; border: none; border-radius: 5px; height: 10px; }
QProgressBar::chunk { border-radius: 5px; background: qlineargradient(
    x1:0, y1:0, x2:1, y2:0, stop:0 #fcd34d, stop:1 #f97316); }
"""


class PantallaCarga(QWidget):
    """Frameless window with the icon, the current step and a progress bar."""

    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint)
        self.setObjectName("carga")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_ESTILO)
        self.setFixedSize(380, 250)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)
        icono = QLabel(alignment=Qt.AlignCenter)
        ruta = os.path.join(os.path.dirname(__file__), "icono.svg")
        if os.path.exists(ruta):
            icono.setPixmap(QIcon(ruta).pixmap(84, 84))
        titulo = QLabel("Dédalo", objectName="titulo", alignment=Qt.AlignCenter)
        self.lbl_paso = QLabel(objectName="paso", alignment=Qt.AlignCenter)
        self.barra = QProgressBar(textVisible=False, maximum=100)
        lay.addWidget(icono)
        lay.addWidget(titulo)
        lay.addStretch(1)
        lay.addWidget(self.lbl_paso)
        lay.addWidget(self.barra)
        pantalla = QApplication.primaryScreen()
        if pantalla is not None:
            self.move(pantalla.availableGeometry().center() - self.rect().center())

    def paso(self, texto: str, valor: int) -> None:
        """Shows a step and its progress (0-100) and repaints right away."""
        self.lbl_paso.setText(texto)
        self.barra.setValue(max(self.barra.value(), min(100, int(valor))))
        QApplication.processEvents()


def precalentar_agentes(avance=None, desde=0, hasta=100) -> None:
    """Probes every installed agent's session in parallel (fills the cache
    that `modelos.agentes_operativos()` reads while the window is built).

    `avance(texto, valor)` is called as each probe finishes, with `valor`
    spread between `desde` and `hasta`. Qt events keep flowing while waiting so
    the splash stays responsive.
    """
    agentes = modelos.agentes_instalados()
    if not agentes:
        return
    hechos = 0
    with ThreadPoolExecutor(max_workers=len(agentes)) as pool:
        pendientes = {pool.submit(modelos.sesion_agente, a): a for a in agentes}
        if avance:
            avance(t("Checking agents: {agentes}…", agentes=", ".join(agentes)),
                   desde)
        while pendientes:
            listos, _ = wait(pendientes, timeout=0.05, return_when=FIRST_COMPLETED)
            for fut in listos:
                agente = pendientes.pop(fut)
                hechos += 1
                if avance:
                    estado = fut.result() if fut.exception() is None else None
                    marca = {True: "✓", False: "✗"}.get(estado, "?")
                    avance(t("Agent {agente} {marca}", agente=agente, marca=marca),
                           desde + (hasta - desde) * hechos / len(agentes))
            QApplication.processEvents()
            if not listos:
                time.sleep(0.01)
