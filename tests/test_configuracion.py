#!/usr/bin/env python3
"""Tests for configuracion.py - coherent defaults."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dedalo import configuracion as cfg  # noqa: E402


def test_dimensiones_coherentes():
    assert cfg.ANCHO_MIN <= cfg.ANCHO
    assert cfg.ALTO_MIN <= cfg.ALTO


def test_agentes_y_defecto():
    assert cfg.AGENTE_DEFECTO in cfg.AGENTES_DISPONIBLES


def test_fichas_desactivadas_por_defecto():
    assert cfg.LAUNCH_DEFECTO["fichas"] is False


def test_eventos_webhook():
    assert set(cfg.WEBHOOK_DEFECTO["eventos"]) == {
        "inicio", "bloqueada", "fin", "tokens", "error"}
