"""Centralized configuration for the Dédalo panel.

Constants shared by all modules: paths, default values, timeouts and sizes.
Edit here instead of scattered throughout the code.
"""

import os

APLICACION = "dedalo"
# `DEDALO_CONFIG_DIR` lets tests (and portable installs) keep the panel
# settings out of the real home; child processes inherit it through the
# environment, unlike an in-process monkeypatch.
CONFIG_DIR = (os.environ.get("DEDALO_CONFIG_DIR")
              or os.path.join(os.path.expanduser("~"), ".config", APLICACION))
REGISTRO = os.path.join(CONFIG_DIR, "proyectos.json")
CATALOGO_MODELOS = os.path.join(CONFIG_DIR, "models_dev.json")

# ----- Window -----
# Initial and minimum size: below ANCHO_MIN x ALTO_MIN the panels become
# illegible; the layout readjusts between those limits (the inner panels
# use splitters/scroll and grow with the window).
ANCHO = 1180
ALTO = 780
ANCHO_MIN = 960
ALTO_MIN = 600
TEMA_DEFECTO = "Zinc/Amber Oscuro"
FUENTE_MONO = "JetBrains Mono"
FUENTE_UI = "Outfit"

# ----- Cockpit (navigation and motion) -----
# Vertical navigation sidebar (width in px). Dark by default in the theme.
SIDEBAR_ANCHO = 220
# UI motion: pill/batch with subtle animation. False = static (reduced motion).
MOTION = True

# ----- Thermal safety -----
SEGURIDAD_DEFECTO = {
    "activo": True,
    "ver": False,
    "umbral": 85,
    "segundos": 5,
}

# ----- Launch default values -----
LAUNCH_DEFECTO = {
    "hasta": "22:00",
    "iteraciones": 40,
    "padre": "master",
    "trabajo": "",
    "costo_max": 0,
    "costo_iter": 0.50,
    "dual": True,
    "push": True,
    "voz": False,
}

# ----- Navigator (context search before each task) -----
NAVEGADOR_DEFECTO = False
MODELO_NAVEGADOR_SUGERIDO = "opencode/big-pickle"

# ----- Webhooks (push notifications) -----
WEBHOOK_DEFECTO = {
    "telegram_token": "",
    "telegram_chat_id": "",
    "discord_webhook_url": "",
    "whatsapp_api_url": "",
    "whatsapp_token": "",
    "whatsapp_phone_id": "",
    "eventos": {
        "inicio": True,
        "bloqueada": True,
        "fin": True,
        "tokens": True,
        "error": True,
    },
}

# ----- Models -----
MODELO_SUGERIDO = "opencode/big-pickle"

# ----- Available CLI agents -----
# AGENTES_CONOCIDOS are the CLIs that dedalo knows how to invoke. AGENTE_DEFECTO
# "auto" = use the first installed one according to AGENTES_PREFERIDOS.
AGENTES_CONOCIDOS = ("opencode", "codex", "claude")
AGENTES_PREFERIDOS = ("opencode", "codex", "claude")
AGENTES_DISPONIBLES = AGENTES_CONOCIDOS + ("auto",)
AGENTE_DEFECTO = "auto"

# ----- Timeouts (seconds) -----
TIMEOUT_INTERNET = 3
TIMEOUT_OPENCODE = 20
TIMEOUT_GIT = 20
TIMEOUT_SENSORES = 5
TIMEOUT_CATALOGO = 15
TIMEOUT_NAVEGADOR = 60

# ----- Timers (ms) -----
TIMER_TAIL_MS = 1000
TIMER_TEMP_MS = 1000
TIMER_NET_MS = 15000
TIMER_METRICAS_MS = 5000
TAIL_LOG_BYTES = 4000
