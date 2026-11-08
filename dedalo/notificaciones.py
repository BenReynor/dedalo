"""Push notifications for Telegram, Discord and WhatsApp (no Qt).

The GUI sends asynchronously through `webhooks.WebhookManager`; the engine
calls this module directly, so a loop started by MCP or the CLI reports its
task progress too (the GUI is not necessarily open then). Everything here is
best effort: a notification must never break the loop.
"""

import json
import time
import urllib.error
import urllib.request
from typing import Any

PLANTILLAS = {
    "inicio": "🚀 *Loop iniciado*\nProyecto: `{proyecto}`\nModelo tarea: `{modelo_tarea}`\nModelo revisor: `{modelo_revisor}`",
    "externo": "🚀 *Loop iniciado por MCP/CLI*\nProyecto: `{proyecto}`\nOrigen: `{origen}`\nModelo tarea: `{modelo_tarea}`\nModelo revisor: `{modelo_revisor}`",
    "tarea": "✅ *Tarea completada*\nProyecto: `{proyecto}`\nTarea: `{tarea}`\nIteración: {iteracion}\nRama: `{rama}`{commit}",
    "bloqueada": "⚠ *Tarea bloqueada*\nProyecto: `{proyecto}`\nTarea: `{tarea}`",
    "fin": "✅ *Loop finalizado*\nProyecto: `{proyecto}`\nTareas: {hechas}/{total}\nCoste: ${coste:.2f}\nDuración: {duracion_min:.1f} min",
    "plan_crecio": "📝 *El plan creció*\nProyecto: `{proyecto}`\nTareas nuevas: {n}\n{titulos}",
    "tokens": "💸 *Tokens/cuota agotados*\nProyecto: `{proyecto}`\nEl loop se ha detenido.{reanuda}",
    "error": "💥 *Error crítico*\nProyecto: `{proyecto}`\nDetalle: `{detalle}`",
}


class _Faltantes(dict):
    """Renders unknown placeholders as an empty string instead of raising."""

    def __missing__(self, clave):
        return ""


EVENTOS = ("inicio", "externo", "tarea", "bloqueada", "fin",
           "plan_crecio", "tokens", "error")


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


def leer_config(proyecto: str | None = None) -> dict[str, Any]:
    """Webhook configuration: global, with the project's overrides on top.

    The GUI saves project-level settings; the engine must honor them too, so a
    loop started from MCP/CLI notifies like the same loop started from the GUI.
    """
    from .proyectos import leer_config_proyecto, leer_webhooks

    config = dict(leer_webhooks() or {})
    if proyecto:
        local = (leer_config_proyecto(proyecto) or {}).get("webhooks") or {}
        eventos = dict(config.get("eventos") or {})
        eventos.update(local.get("eventos") or {})
        config.update(local)
        config["eventos"] = eventos
    return normalizar(config)


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


_ESPERAS_REINTENTO = (1, 3, 10)  # seconds before each new attempt
_MAX_ENCOLADOS = 10
_ENCOLADOS: dict[str, list[str]] = {}  # undelivered texts, per platform


def _transitorio(error: Exception) -> bool:
    """A network failure or a server-side error, worth trying again."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500 or error.code == 429
    return isinstance(error, OSError)  # URLError, reset, timeout…


def _con_reintentos(enviar_uno, config: dict[str, Any], texto: str) -> str:
    for espera in (*_ESPERAS_REINTENTO, None):
        try:
            return enviar_uno(config, texto)
        except Exception as e:  # noqa: BLE001
            if espera is None or not _transitorio(e):
                raise
            time.sleep(espera)
    return "OK"  # unreachable: the last attempt returns or raises


def _vaciar_encolados(nombre: str, enviar_uno, config: dict[str, Any]) -> None:
    """Delivers what earlier failures left queued, stopping at the first error."""
    # Taken out atomically: the panel sends from several threads at once.
    cola = _ENCOLADOS.pop(nombre, [])
    while cola:
        try:
            if enviar_uno(config, cola[0]) != "OK":
                break
        except Exception:  # noqa: BLE001 - it stays queued for the next time
            break
        cola.pop(0)
    if cola:
        _ENCOLADOS.setdefault(nombre, [])[:0] = cola


def _enviar_con_garantias(nombre: str, enviar_uno, config: dict[str, Any],
                          texto: str) -> str:
    """Retries transient failures; if they persist, queues the text."""
    try:
        estado = _con_reintentos(enviar_uno, config, texto)
    except Exception as e:  # noqa: BLE001 - notifications are best effort
        estado = sanitizar(config, str(e))
        if _transitorio(e):
            cola = _ENCOLADOS.setdefault(nombre, [])
            cola.append(texto)
            del cola[:-_MAX_ENCOLADOS]
            estado += " (encolada para el siguiente aviso)"
        return estado
    if estado == "OK":
        _vaciar_encolados(nombre, enviar_uno, config)
    return estado


def enviar_texto(config: dict[str, Any], texto: str,
                 solo: str | None = None) -> list[tuple[str, str]]:
    """Sends `texto` to every configured platform.

    Returns `[(plataforma, "OK" | error)]`; never raises. `solo` is the panel's
    "test this platform" button: one attempt, so the user sees the result now.
    """
    resultados = []
    for nombre, enviar_uno, configurada in _PLATAFORMAS:
        if solo and nombre != solo:
            continue
        if not configurada(config):
            continue
        if not solo:
            resultados.append((nombre, _enviar_con_garantias(
                nombre, enviar_uno, config, texto)))
            continue
        try:
            resultados.append((nombre, enviar_uno(config, texto)))
        except Exception as e:  # noqa: BLE001 - notifications are best effort
            resultados.append((nombre, sanitizar(config, str(e))))
    return resultados


def enviar(evento: str, datos: dict[str, Any] | None = None,
           config: dict[str, Any] | None = None,
           proyecto: str | None = None) -> list[tuple[str, str]]:
    """Formats and sends an event. Silent no-op when it is disabled or fails."""
    datos = dict(datos or {})
    if config is None:
        try:
            config = leer_config(proyecto)
        except Exception:
            return []
    if not esta_activo(config, evento):
        return []
    return enviar_texto(config, formatear(evento, datos))
