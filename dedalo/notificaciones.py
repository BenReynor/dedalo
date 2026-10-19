"""Push notifications for Telegram, Discord and WhatsApp (no Qt).

The GUI sends asynchronously through `webhooks.WebhookManager`; the engine
calls this module directly, so a loop started by MCP or the CLI reports its
task progress too (the GUI is not necessarily open then). Everything here is
best effort: a notification must never break the loop.
"""

import json
import urllib.request
from typing import Any

PLANTILLAS = {
    "inicio": "🚀 *Loop iniciado*\nProyecto: `{proyecto}`\nModelo tarea: `{modelo_tarea}`\nModelo revisor: `{modelo_revisor}`",
    "externo": "🚀 *Loop iniciado por MCP/CLI*\nProyecto: `{proyecto}`\nOrigen: `{origen}`\nModelo tarea: `{modelo_tarea}`\nModelo revisor: `{modelo_revisor}`",
    "tarea": "✅ *Tarea completada*\nProyecto: `{proyecto}`\nTarea: `{tarea}`\nIteración: {iteracion}\nRama: `{rama}`{commit}",
    "bloqueada": "⚠ *Tarea bloqueada*\nProyecto: `{proyecto}`\nTarea: `{tarea}`",
    "fin": "✅ *Loop finalizado*\nProyecto: `{proyecto}`\nTareas: {hechas}/{total}\nCoste: ${coste:.2f}\nDuración: {duracion_min:.1f} min",
    "tokens": "💸 *Tokens/cuota agotados*\nProyecto: `{proyecto}`\nEl loop se ha detenido.",
    "error": "💥 *Error crítico*\nProyecto: `{proyecto}`\nDetalle: `{detalle}`",
}


class _Faltantes(dict):
    """Renders unknown placeholders as an empty string instead of raising."""

    def __missing__(self, clave):
        return ""


EVENTOS = ("inicio", "externo", "tarea", "bloqueada", "fin",
           "tokens", "error")


def normalizar(config: dict[str, Any] | None) -> dict[str, Any]:
    """Fills absent event switches with the GUI default (enabled).

    The panel renders a missing switch as checked, so an older config that
    predates a new event (e.g. `externo` or `tarea`) must behave as enabled
    instead of silently dropping those notifications.
    """
    normal = dict(config or {})
    eventos = dict(normal.get("eventos") or {})
    for evento in EVENTOS:
        eventos.setdefault(evento, True)
    normal["eventos"] = eventos
    return normal


def leer_config() -> dict[str, Any]:
    """Global webhook configuration (the GUI and the engine share it)."""
    from .proyectos import leer_webhooks

    return normalizar(leer_webhooks())


def esta_activo(config: dict[str, Any], evento: str) -> bool:
    """Is the event enabled AND is at least one platform configured?"""
    if not config.get("eventos", {}).get(evento, False):
        return False
    return any([
        config.get("telegram_token") and config.get("telegram_chat_id"),
        config.get("discord_webhook_url"),
        config.get("whatsapp_api_url") and config.get("whatsapp_token"),
    ])


def formatear(evento: str, datos: dict[str, Any]) -> str:
    plantilla = PLANTILLAS.get(evento, "{evento}: {datos}")
    try:
        return plantilla.format_map(_Faltantes(datos))
    except (KeyError, ValueError, IndexError):
        return f"{evento}: {datos}"


def sanitizar(config: dict[str, Any], mensaje: str) -> str:
    """Hides tokens and embedded URLs before showing/logging an error.

    The Telegram token travels in the URL itself and urllib may include it in
    the exception message, so it is masked here.
    """
    if not mensaje:
        return ""
    for clave in ("telegram_token", "whatsapp_token",
                  "discord_webhook_url", "whatsapp_api_url"):
        secreto = config.get(clave)
        if secreto:
            mensaje = mensaje.replace(str(secreto), "***")
    return mensaje


def _telegram(config, texto):
    token = config["telegram_token"]
    chat_id = config["telegram_chat_id"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            return f"HTTP {resp.status}"
    return "OK"


def _discord(config, texto):
    url = config["discord_webhook_url"]
    data = json.dumps({"content": texto}).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status not in (200, 204):
            return f"HTTP {resp.status}"
    return "OK"


def _whatsapp(config, texto):
    url = config["whatsapp_api_url"].rstrip("/") + "/messages"
    token = config["whatsapp_token"]
    phone_id = config.get("whatsapp_phone_id", "")
    to = config.get("whatsapp_to", "")
    if not phone_id or not to:
        return "Falta phone_id o to"
    data = json.dumps({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": texto},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            return f"HTTP {resp.status}"
    return "OK"


_PLATAFORMAS = (
    ("telegram", _telegram,
     lambda c: bool(c.get("telegram_token") and c.get("telegram_chat_id"))),
    ("discord", _discord, lambda c: bool(c.get("discord_webhook_url"))),
    ("whatsapp", _whatsapp,
     lambda c: bool(c.get("whatsapp_api_url") and c.get("whatsapp_token"))),
)


def enviar_texto(config: dict[str, Any], texto: str,
                 solo: str | None = None) -> list[tuple[str, str]]:
    """Sends `texto` to every configured platform.

    Returns `[(plataforma, "OK" | error)]`; never raises.
    """
    resultados = []
    for nombre, enviar_uno, configurada in _PLATAFORMAS:
        if solo and nombre != solo:
            continue
        if not configurada(config):
            continue
        try:
            resultados.append((nombre, enviar_uno(config, texto)))
        except Exception as e:  # noqa: BLE001 - notifications are best effort
            resultados.append((nombre, sanitizar(config, str(e))))
    return resultados


def enviar(evento: str, datos: dict[str, Any] | None = None,
           config: dict[str, Any] | None = None) -> list[tuple[str, str]]:
    """Formats and sends an event. Silent no-op when it is disabled or fails."""
    datos = dict(datos or {})
    if config is None:
        try:
            config = leer_config()
        except Exception:
            return []
    if not esta_activo(config, evento):
        return []
    return enviar_texto(config, formatear(evento, datos))
