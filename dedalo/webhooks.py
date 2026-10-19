"""Webhooks for push notifications: Telegram, Discord, WhatsApp.

This is the GUI face of `notificaciones`: it keeps the same public API and
sends asynchronously (QThread) so the window never blocks. The formatting and
the HTTP calls live in the Qt-free module, which the engine uses directly.
"""

from typing import Any

from PySide6.QtCore import QObject, Qt, Signal

from . import notificaciones
from .proceso import Trabajo


class WebhookManager(QObject):
    """Manages the sending of notifications to Telegram, Discord, WhatsApp."""

    enviado = Signal(str, str)      # platform, state
    error = Signal(str, str)        # platform, error

    PLANTILLAS = notificaciones.PLANTILLAS

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__()
        self.config = config or {}
        self._workers: set[Trabajo] = set()

    def configurar(self, config: dict[str, Any]):
        self.config = config

    def _sanitizar(self, mensaje: str) -> str:
        return notificaciones.sanitizar(self.config, mensaje)

    def esta_activo(self, evento: str) -> bool:
        """Checks whether the event is enabled and a platform is configured."""
        return notificaciones.esta_activo(self.config, evento)

    def enviar(self, evento: str, datos: dict[str, Any]):
        """Sends the notification asynchronously (does not block the UI).

        Each send is an independent QThread and ALL of them stay referenced
        in `self._workers` until they finish. With a single shared attribute,
        two overlapping events clobbered each other: the second send reassigned
        the attribute and the first QThread was left without a Python
        reference. Since `Trabajo` is created with `parent=None`, the collector
        could free it while running and the application aborted with
        "QThread: Destroyed while thread is still running".
        """
        if not self.esta_activo(evento):
            return

        texto = self._formatear(evento, datos)

        worker = Trabajo(lambda: self._enviar_todas(texto))
        self._workers.add(worker)
        worker.finished.connect(
            lambda w=worker: self._workers.discard(w),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.start()

    def _pendientes(self) -> int:
        """Number of sends still in flight (diagnostics and tests)."""
        return sum(1 for w in self._workers if w.isRunning())

    def _formatear(self, evento: str, datos: dict[str, Any]) -> str:
        return notificaciones.formatear(evento, datos)

    def _enviar_todas(self, texto: str):
        for plataforma, estado in notificaciones.enviar_texto(self.config, texto):
            if estado == "OK":
                self.enviado.emit(plataforma, "OK")
            else:
                self.error.emit(plataforma, self._sanitizar(str(estado)))

    def _configurada(self, plataforma: str) -> bool:
        """Checks whether the platform has the minimum keys to send."""
        if plataforma == "telegram":
            return bool(self.config.get("telegram_token")
                        and self.config.get("telegram_chat_id"))
        if plataforma == "discord":
            return bool(self.config.get("discord_webhook_url"))
        if plataforma == "whatsapp":
            return bool(self.config.get("whatsapp_api_url")
                        and self.config.get("whatsapp_token"))
        return False

    def probar(self, plataforma: str) -> bool:
        """Sends a test message to a specific platform."""
        if not self._configurada(plataforma):
            return False

        texto = "🧪 *Test de webhook* desde Dédalo GUI"
        for nombre, estado in notificaciones.enviar_texto(
                self.config, texto, solo=plataforma):
            if estado == "OK":
                self.enviado.emit(nombre, "OK")
            else:
                self.error.emit(nombre, self._sanitizar(str(estado)))
        return True
