"""Main control panel window (orchestration).

Each tab's UI lives in `paneles.py`; here we only connect signals,
manage the processes (loop/gate), the persisted configuration and the
monitoring (temperature and internet).
"""

import json
import os
import re
import subprocess
import sys
import time

from PySide6.QtCore import QProcess, QSettings, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from . import configuracion as cfg
from . import (
    consentimiento,
    loop_launch,
    loops_estado,
    modelos,
    net,
    plantillas,
    sensor,
)
from .gate import argv_gate
from .i18n import IDIOMAS, NOMBRES_IDIOMA, idioma, set_idioma, t
from .paneles import (
    AvisoTemperatura,
    LoopPill,
    PanelEjecucion,
    PanelGit,
    PanelIncidencias,
    PanelLecciones,
    PanelLogs,
    PanelMapa,
    PanelPlan,
    PanelSeguridad,
    _BtnDanger,
    fase_actual,
)
from .paneles_metricas import PanelMetricas
from .proceso import Proceso, Trabajo
from .proyectos import (
    RegistroCorrupto,
    cargar,
    descartar_registro_corrupto,
    guardar,
    guardar_config_proyecto,
    leer_config_proyecto,
    leer_modelos,
    leer_seguridad,
    leer_sidebar_ancho,
    leer_tema,
    leer_webhooks,
    verificar_registro,
)
from .temas import NOMBRES, inicializar_temas, obtener_temas
from .webhooks import WebhookManager


def _argv_motor(frozen, args):
    """Command (program, argv) that launches the loop engine (see loop_launch)."""
    return loop_launch.argv_motor(frozen, args)


def _raiz_codigo():
    """Root of the GUI repo: `dedalo` is one of its subdirectories."""
    return loop_launch.raiz_codigo()


class Ventana(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("Dédalo — control panel"))
        self.resize(cfg.ANCHO, cfg.ALTO)
        self.setMinimumSize(cfg.ANCHO_MIN, cfg.ALTO_MIN)
        # Restores the size and state (maximized/restored) of the last session
        self._settings = QSettings("dedalo", "panel")
        geo = self._settings.value("ventana/geometria")
        if geo:
            self.restoreGeometry(geo)

        self.proyectos = cargar()
        if not self.proyectos:
            candidato = os.getcwd()
            # Only auto-registers the current directory if it looks like a real
            # Dédalo project (has plan.md + dedalo.sh + .git) and it is NOT the
            # GUI's own folder. Prevents starting inside the app's repo from
            # registering itself as a "project" (source of confusion).
            parece_proyecto = (
                os.path.isfile(os.path.join(candidato, "plan.md"))
                and os.path.isfile(os.path.join(candidato, "dedalo.sh"))
                and os.path.isdir(os.path.join(candidato, ".git"))
            )
            dir_gui = os.path.dirname(os.path.abspath(__file__))
            if parece_proyecto and os.path.abspath(candidato) != dir_gui:
                self.proyectos[os.path.basename(candidato)] = {"ruta": candidato}
            guardar(self.proyectos, leer_tema())

        self.loop = None
        self.gate = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tail_log)
        self.timer_temp = QTimer(self)
        self.timer_temp.timeout.connect(self._comprobar_temp)
        self.timer_net = QTimer(self)
        self.timer_net.timeout.connect(self._comprobar_net)
        self._aviso_abierto = None
        self._nombre_activo = ""
        self._log_tam = 0
        self._log_marca = 0
        self._log_inicio = 0
        self._revision_pendiente = False
        self.tema = leer_tema()
        self.seguridad = leer_seguridad()
        self.webhooks_config = leer_webhooks()
        self._modelos = []
        self._sel_modelos = leer_modelos()
        self._lanzamiento = dict(cfg.LAUNCH_DEFECTO)
        self._inicio_loop_ts = None
        self._iter_actual = 0
        self._worker_sesiones_limpieza = None

        # Webhook manager
        self.webhook = WebhookManager(self.webhooks_config)
        self.webhook.error.connect(lambda plataforma, msg: self.statusBar().showMessage(
            t("Webhook {plataforma}: {msg}", plataforma=plataforma, msg=msg), 8000))

        # Use persisted sidebar width (or default)
        self._ancho_sidebar = leer_sidebar_ancho()

        self._ui()
        self._aplicar_tema(self.tema)
        self._cargar_proyecto()
        self._cargar_modelos_en_fondo()
        self._sondear_sesiones_en_fondo()
        self._iniciar_vigilancia()
        self._comprobar_net()
        self.timer_net.start(cfg.TIMER_NET_MS)

        # Timer to detect pending review (when revision_manual is enabled)
        self.timer_revision = QTimer(self)
        self.timer_revision.timeout.connect(self._comprobar_revision_pendiente)
        self.timer_revision.start(1000)

        # Timer for metrics
        self.timer_metricas = QTimer(self)
        self.timer_metricas.timeout.connect(self._actualizar_metricas)
        self.timer_metricas.start(cfg.TIMER_METRICAS_MS)

        # Auto-reload plan.md if it changes on disk (loop/external)
        self.timer_plan = QTimer(self)
        self.timer_plan.timeout.connect(self._refrescar_plan)
        self.timer_plan.start(2000)

        # Auto-reload lecciones.md if it changes on disk
        self.timer_lecciones = QTimer(self)
        self.timer_lecciones.timeout.connect(self._refrescar_lecciones)
        self.timer_lecciones.start(2000)

        # Auto-reload incidencias.jsonl if it changes on disk
        self.timer_incidencias = QTimer(self)
        self.timer_incidencias.timeout.connect(self._refrescar_incidencias)
        self.timer_incidencias.start(2000)

        # Shared state sync: an AI connected over MCP can install a project or
        # start/stop a loop behind our back. This timer makes the panel SEE
        # those changes (project appears, loop shows as running) and prevents
        # launching a duplicate loop from the GUI.
        self._worker_externo = None
        self.timer_estado = QTimer(self)
        self.timer_estado.timeout.connect(self._sincronizar_estado)
        self.timer_estado.start(2000)

    def _sincronizar_estado(self):
        self._refrescar_proyectos()
        self._refrescar_loop_externo()

    def _refrescar_proyectos(self):
        """Adds projects created by others (e.g. an AI over MCP) to the combo
        without disturbing the current selection; refreshes their paths."""
        try:
            reg = cargar()
        except (RegistroCorrupto, OSError, ValueError):
            return
        if not isinstance(reg, dict):
            return
        nuevos = [n for n in reg if n not in self.proyectos]
        cambiados = {n: d for n, d in reg.items()
                     if n in self.proyectos and self.proyectos.get(n) != d}
        if not nuevos and not cambiados:
            return
        self.proyectos.update(reg)
        for n in nuevos:
            self.cmb.blockSignals(True)
            self.cmb.addItem(n)
            self.cmb.blockSignals(False)
        if nuevos:
            self.estado.setText(
                t("[auto] New project(s) detected: {lista}",
                  lista=", ".join(nuevos)))

    def _refrescar_loop_externo(self):
        """Mirrors (in the panel) a loop started outside this GUI (MCP/CLI).

        If one is running for the current project and this GUI has no local
        loop, the panel shows it as running (start disabled, stop enabled) and
        tails its log; when it ends, the panel returns to the idle state.
        """
        p = self._proyecto_actual()
        if not p:
            return
        nombre = p[0]
        # Our own loop, if any, is authoritative for the local process state.
        local = bool(self.loop) and self.loop.state() != QProcess.NotRunning
        externo = loops_estado.estado(nombre)
        corriendo = externo["corriendo"]
        if corriendo and not local:
            if not self._loop_externo:
                self._loop_externo = True
                self.pan_logs.panel_loop.appendPlainText(
                    t("[mcp] A loop started by an external agent is running "
                      "(pid {pid}); following it.", pid=externo["pid"] or "?"))
                self.timer.start(cfg.TIMER_TAIL_MS)
            self.pan_ejec.establecer_running(True)
        elif self._loop_externo and not corriendo:
            # The external loop finished: back to the idle state.
            self._loop_externo = False
            self.timer.stop()
            self.pan_ejec.establecer_running(False)
            self.pan_ejec.b_iniciar.setEnabled(True)
            self.pan_ejec.b_detener.setEnabled(False)
            self._set_fase_loop(0, 0, corriendo=False)
            self.pan_plan.cargar(os.path.join(p[1], "plan.md"))
            self.pan_lecciones.cargar(os.path.join(p[1], "lecciones.md"))
            self.pan_git.cargar(p[1])

    def _refrescar_plan(self):
        self.pan_plan._recargar_si_cambio()

    def _refrescar_lecciones(self):
        self.pan_lecciones._recargar_si_cambio()

    def _refrescar_incidencias(self):
        self.pan_incidencias._recargar_si_cambio()

    def _sondear_sesiones_en_fondo(self):
        """Queries in the background whether each installed CLI has a session.

        Agents without login are flagged in the combo instead of failing on
        the loop's first iteration. The result is cached in modelos.
        """
        modelos.invalidar_cache()
        w = Trabajo(modelos.estado_agentes)
        w.conectar(self._sesiones_agentes_sondeadas)
        w.liberar(self, "_worker_sesiones")
        w.start()
        self._worker_sesiones = w

    def _sesiones_agentes_sondeadas(self, _estado):
        """Repaints the combos when the session probe arrives."""
        self.pan_ejec.refrescar_agentes()

    def _cargar_modelos_en_fondo(self):
        """Queries opencode/models.dev without blocking startup."""
        w = Trabajo(modelos.lista_modelos)
        w.conectar(self._modelos_cargados)
        w.liberar(self, "_worker_modelos")
        w.start()
        self._worker_modelos = w

    def _modelos_cargados(self, lista):
        nuevos = lista or [cfg.MODELO_SUGERIDO]
        self._modelos = nuevos
        for sel in (self.pan_ejec.cmb_agente, self.pan_ejec.cmb_revisor):
            sel.activar_catalogo_global()
        self.pan_ejec.agregar_catalogo(nuevos)
        self.pan_ejec.info_modelos(len(nuevos),
                                   len(modelos.nombres_proveedores()))
        self._aplicar_sel_modelos()

    # ---------- UI ----------

    def _ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        barra = QHBoxLayout()
        barra.addWidget(QLabel(t("Project:")))
        self.cmb = QComboBox()
        self.cmb.addItems(sorted(self.proyectos))
        # Reopen the last active project (instead of the first alphabetical)
        prev = self._settings.value("proyecto/activo", "")
        if prev and prev in self.proyectos:
            self.cmb.setCurrentText(prev)
        self.cmb.currentTextChanged.connect(self._cambiar_proyecto)
        barra.addWidget(self.cmb, 1)
        b_agregar = QPushButton(t("Add…"))
        b_agregar.clicked.connect(self._agregar_proyecto)
        b_quitar = _BtnDanger(t("Remove"))
        b_quitar.clicked.connect(self._quitar_proyecto)
        barra.addWidget(b_agregar)
        barra.addWidget(b_quitar)
        barra.addStretch()
        barra.addWidget(QLabel(t("Theme:")))
        self.cmb_tema = QComboBox()
        self.cmb_tema.addItems(NOMBRES)
        if self.tema in NOMBRES:
            self.cmb_tema.setCurrentText(self.tema)
        self.cmb_tema.currentTextChanged.connect(self._cambiar_tema)
        barra.addWidget(self.cmb_tema)
        barra.addSpacing(12)
        barra.addWidget(QLabel(t("Language:")))
        self.cmb_idioma = QComboBox()
        for cod in IDIOMAS:
            self.cmb_idioma.addItem(NOMBRES_IDIOMA[cod], cod)
        self.cmb_idioma.setCurrentIndex(IDIOMAS.index(idioma()))
        self.cmb_idioma.currentIndexChanged.connect(self._cambiar_idioma)
        barra.addWidget(self.cmb_idioma)
        root.addLayout(barra)

        # ===== BODY: sidebar + content =====
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(0)
        cuerpo.setContentsMargins(0, 0, 0, 0)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(self._ancho_sidebar)
        self._sidebar_items = []
        self.stack = QStackedWidget()
        cuerpo.addWidget(self.sidebar)
        cuerpo.addWidget(self.stack, 1)
        root.addLayout(cuerpo, 1)

        self.pan_plan = PanelPlan()
        self.pan_plan.guardado.connect(
            lambda ruta: self.estado.setText(t("plan.md saved ({ruta})", ruta=ruta)))
        self.pan_lecciones = PanelLecciones()
        self.pan_lecciones.guardado.connect(
            lambda ruta: self.estado.setText(
                t("lecciones.md saved ({ruta})", ruta=ruta)))
        self.pan_incidencias = PanelIncidencias()
        self.pan_ejec = PanelEjecucion()
        self.pan_ejec.iniciar.connect(self._iniciar_loop)
        self.pan_ejec.detener.connect(self._detener_loop)
        self.pan_ejec.gate.connect(self._ejecutar_gate)
        self.pan_ejec.refrescar_modelos.connect(self._refrescar_modelos)
        self.pan_ejec.modelos_modificados.connect(self._guardar_sel_modelos)
        # Navigator signals
        self.pan_ejec.cmb_nav.currentTextChanged.connect(self._guardar_sel_modelos)
        # Connect review panel
        self.pan_ejec.panel_revision.aprobado.connect(self._revision_aprobada)
        self.pan_ejec.panel_revision.rechazado.connect(self._revision_rechazada)
        self.pan_git = PanelGit()
        self.pan_git.revertir_commit.connect(self._ejecutar_revert)
        self.pan_git.limpiar_git.connect(self._limpiar_git_framework)
        self.pan_logs = PanelLogs()
        self.pan_mapa = PanelMapa()
        self.pan_metricas = PanelMetricas()
        self.pan_seg = PanelSeguridad(self.seguridad, self.webhooks_config)
        self.pan_seg.guardar_ajustes.connect(self._guardar_seguridad)

        self._secciones = [
            (t("Plan"), self.pan_plan),
            (t("🧠 Lessons"), self.pan_lecciones),
            (t("⚠ Incidents"), self.pan_incidencias),
            (t("Run"), self.pan_ejec),
            (t("Logs"), self.pan_logs),
            (t("🗺 Map"), self.pan_mapa),
            (t("Git"), self.pan_git),
            (t("📊 Metrics"), self.pan_metricas),
            (t("🛡 Security"), self.pan_seg),
        ]
        for i, (nombre, panel) in enumerate(self._secciones):
            self.sidebar.addItem(nombre)
            self.stack.addWidget(panel)
            # Ctrl+1..7 shortcuts per section
            atajo = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            atajo.activated.connect(
                lambda _n=i: self._cambiar_seccion(_n))
        self.sidebar.setCurrentRow(0)
        self.sidebar.currentRowChanged.connect(self._cambiar_seccion)

        # ===== STATUS BAR =====
        self.barra_estado = QStatusBar()
        self.estado = QLabel(t("No project"))
        self.barra_estado.addWidget(self.estado)
        self.pill_loop = LoopPill()
        self.barra_estado.addPermanentWidget(self.pill_loop)
        self.setStatusBar(self.barra_estado)

    def _cambiar_seccion(self, indice: int):
        """Switches the visible section (sidebar ↔ stack, with Ctrl+N shortcuts)."""
        if 0 <= indice < self.stack.count():
            self.stack.setCurrentIndex(indice)
            self.sidebar.setCurrentRow(indice)

    def _set_fase_loop(self, iter_actual=0, total=0, corriendo=True):
        """Updates the pipeline stepper and the loop status pill."""
        p = self._proyecto_actual()
        ruta_log = os.path.join(p[1], "progreso.log") if p else ""
        fase = fase_actual(ruta_log) if corriendo else ""
        self.pan_ejec.pipeline.setFase(fase)
        if not corriendo:
            self.pan_ejec.pipeline.setPendiente()
        self.pill_loop.setEstado(iter_actual, total, fase, corriendo)

    def _aplicar_tema(self, nombre):
        temas = obtener_temas()
        if nombre in temas:
            QApplication.instance().setStyleSheet(temas[nombre])
        self.pan_ejec.pipeline.set_tema(nombre)

    # ---------- Thermal monitoring ----------

    def _iniciar_vigilancia(self):
        seg = self.seguridad
        activo = bool(seg.get("activo"))
        ver = bool(seg.get("ver"))
        self.pan_seg.set_visibilidad_temp(ver)
        if (activo or ver) and sensor.leer_temperatura() is not None:
            self.timer_temp.start(cfg.TIMER_TEMP_MS)
        else:
            self.timer_temp.stop()
        self._comprobar_temp()

    def _comprobar_temp(self):
        temp = sensor.leer_temperatura()
        self.pan_seg.actualizar_temp(temp, self.seguridad.get("umbral", 85))
        seg = self.seguridad
        if not seg.get("activo") or temp is None:
            return
        if temp >= float(seg.get("umbral", 85)):
            if not self._aviso_abierto or not self._aviso_abierto.isVisible():
                self._abrir_aviso(temp)
        elif self._aviso_abierto is not None:
            self._aviso_abierto._continuar()

    def _abrir_aviso(self, temp):
        aviso = AvisoTemperatura(temp, self.seguridad.get("segundos", 5), self)
        self._aviso_abierto = aviso
        aviso.finished.connect(self._aviso_terminado)
        aviso.show()
        aviso.raise_()
        aviso.activateWindow()

    def _aviso_terminado(self, _codigo):
        aviso = self._aviso_abierto
        self._aviso_abierto = None
        if aviso and aviso.apagar:
            self._apagar_aplicacion()

    def _apagar_aplicacion(self):
        self.estado.setText(t("🔥 Shut down due to overheating"))
        if self.loop and self.loop.state() == QProcess.Running:
            self._detener_loop()
        self.timer.stop()
        self.timer_temp.stop()
        self.estado.setText(t("🔥 Shut down due to overheating. See you later."))
        QTimer.singleShot(1200, QApplication.instance().quit)

    def _guardar_seguridad(self, datos):
        """Receives dict with keys: seguridad, webhooks"""
        if isinstance(datos, dict) and "seguridad" in datos:
            self.seguridad = datos["seguridad"]
            self.webhooks_config = datos.get("webhooks", self.webhooks_config)
            if hasattr(self, 'webhook'):
                self.webhook.configurar(self.webhooks_config)
        else:
            # Compatibility: only seguridad
            self.seguridad = datos
        guardar(self.proyectos, self.tema, self.seguridad, self.webhooks_config)
        self._guardar_config_proyecto()
        self._iniciar_vigilancia()
        self.estado.setText(t("Settings saved"))

    # ---------- Projects ----------

    def _cargar_config_proyecto(self, nombre):
        """Loads the project's theme/security/webhooks/models/launch config.

        Global values act as the base and what is stored in
        proyectos[nombre]["config"] wins over that base.
        """
        local = leer_config_proyecto(nombre)
        self.tema = local.get("tema") or leer_tema()
        seg = leer_seguridad()
        seg.update(local.get("seguridad") or {})
        self.seguridad = seg
        wb = leer_webhooks()
        wb.update(local.get("webhooks") or {})
        self.webhooks_config = wb
        mod = leer_modelos()
        mod.update(local.get("modelos") or {})
        self._sel_modelos = mod
        lanz = dict(cfg.LAUNCH_DEFECTO)
        lanz.update(local.get("lanzamiento") or {})
        self._lanzamiento = lanz
        self.webhook.configurar(self.webhooks_config)

    def _guardar_config_proyecto(self):
        """Persists the active project's config (theme, models, launch,
        security and webhooks)."""
        if not self._nombre_activo:
            return
        conf = {
            "tema": self.tema,
            "modelos": self._sel_modelos,
            "lanzamiento": self._lanzamiento,
            "seguridad": self.seguridad,
            "webhooks": self.webhooks_config,
        }
        guardar_config_proyecto(self.proyectos, self._nombre_activo, conf)

    def _capturar_lanzamiento(self):
        """Saves the current state of the launch widgets."""
        self._lanzamiento = self.pan_ejec.config()

    def _cambiar_tema(self, nombre):
        self.tema = nombre
        guardar(self.proyectos, nombre)
        self._guardar_config_proyecto()
        self._aplicar_tema(nombre)

    def _cambiar_idioma(self, _indice):
        """Persists the chosen language and offers to restart to apply it."""
        cod = self.cmb_idioma.currentData()
        if cod == idioma():
            return
        self._settings.setValue("idioma", cod)
        resp = QMessageBox.question(
            self, t("Language"),
            t("The interface language will change on the next start. "
              "Restart Dédalo now?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if resp == QMessageBox.Yes:
            self._reiniciar_aplicacion()
        else:
            self.estado.setText(
                t("Language saved; restart to apply it"))

    def _reiniciar_aplicacion(self):
        """Relaunches the application and quits the current instance."""
        if getattr(sys, "frozen", False):
            QProcess.startDetached(sys.executable, [])
        else:
            QProcess.startDetached(sys.executable, ["-m", "dedalo"])
        QApplication.instance().quit()

    def _proyecto_actual(self):
        nombre = self.cmb.currentText()
        if not nombre:
            return None
        info = self.proyectos.get(nombre) or {}
        ruta = info.get("ruta") or ""
        return (nombre, ruta) if ruta else None

    def _cambiar_proyecto(self, n):
        if self.loop and self.loop.state() == QProcess.Running:
            prev = self.cmb.findText(self._nombre_activo)
            if prev >= 0:
                self.cmb.blockSignals(True)
                self.cmb.setCurrentIndex(prev)
                self.cmb.blockSignals(False)
            QMessageBox.warning(self, t("Dédalo running"),
                                t("Stop the loop before switching projects."))
            return
        # Persist the outgoing project's config before switching
        self._capturar_lanzamiento()
        self._guardar_config_proyecto()
        self._nombre_activo = n
        self._settings.setValue("proyecto/activo", n)
        guardar(self.proyectos, self.tema)
        self._cargar_proyecto()

    def _cargar_proyecto(self):
        p = self._proyecto_actual()
        if not p:
            self.estado.setText(t("No project"))
            self.pan_plan.clear()
            self.pan_lecciones.cargar(None)
            self.pan_incidencias.cargar(None)
            self.pan_git.cargar(None)
            self.pan_mapa.cargar(None)
            self.pan_logs.panel_loop.clear()
            self.pan_logs.panel_gate.clear()
            return
        nombre, ruta = p
        self._nombre_activo = nombre
        self._log_tam = 0
        self._cargar_config_proyecto(nombre)
        self.cmb_tema.blockSignals(True)
        self.cmb_tema.setCurrentText(self.tema)
        self.cmb_tema.blockSignals(False)
        self._aplicar_tema(self.tema)
        self.pan_seg.aplicar_config(self.seguridad, self.webhooks_config)
        self._iniciar_vigilancia()
        self.estado.setText(t("Project: {nombre} — {ruta}", nombre=nombre, ruta=ruta))
        self.pan_plan.cargar(os.path.join(ruta, "plan.md"))
        self.pan_lecciones.cargar(os.path.join(ruta, "lecciones.md"))
        self.pan_incidencias.cargar(os.path.join(ruta, "incidencias.jsonl"))
        self.pan_git.cargar(ruta)
        self.pan_mapa.cargar(os.path.join(ruta, "mapeo.txt"))
        self.pan_ejec.actualizar_ramas(ruta)
        self.pan_ejec.aplicar_config(self._lanzamiento)
        self.pan_logs.panel_gate.clear()
        self.pan_logs.panel_loop.clear()
        self._log_marca = self._log_inicio = self._tam_log(ruta)
        self._tail_log()

        # instalar() is idempotent: it propagates NEW scripts and gate_checks
        # from the template without touching what already exists (plan.md,
        # lecciones.md and custom checks are never overwritten). It is always
        # called so an old project receives the new checks.
        creados = plantillas.instalar(ruta)
        if creados:
            self.pan_logs.panel_loop.appendPlainText(
                t("[auto-provision] Templates installed: {lista}",
                  lista=", ".join(creados)))
            # If plan.md/lecciones.md were missing, reload them into the UI
            if "plan.md" in creados or "lecciones.md" in creados:
                self.pan_plan.cargar(os.path.join(ruta, "plan.md"))
                self.pan_lecciones.cargar(os.path.join(ruta, "lecciones.md"))

        desactualizados = plantillas._desactualizados(ruta)
        if desactualizados:
            plantillas.actualizar(ruta)
            self.pan_logs.panel_loop.appendPlainText(
                t("[auto-update] Templates updated: {lista}",
                  lista=", ".join(desactualizados)))

        self.pan_ejec.b_gate.setEnabled(
            os.path.exists(os.path.join(ruta, "gate.sh")))
        if not self.loop or self.loop.state() != QProcess.Running:
            self.pan_ejec.b_iniciar.setEnabled(True)
        self._aplicar_sel_modelos()
        # If an external agent (MCP/CLI) has a loop running for this project,
        # reflect it now instead of waiting for the sync timer.
        self._refrescar_loop_externo()

    def _agregar_proyecto(self):
        ruta = QFileDialog.getExistingDirectory(
            self, t("Select the project root"))
        if not ruta:
            return
        nombre = os.path.basename(ruta)
        creados = plantillas.instalar(ruta)
        git = plantillas.inicializar_git(ruta)
        self.proyectos[nombre] = {"ruta": ruta}
        guardar(self.proyectos, self.tema)
        self.cmb.addItem(nombre)
        self.cmb.setCurrentText(nombre)
        detalles = []
        if creados:
            detalles.append("· " + "\n  · ".join(creados))
        if git["repo"] == "creado":
            detalles.append(
                t("git initialized (branch master) with {n} files",
                  n=git["archivos"]))
        elif git["repo"] == "no-disponible":
            detalles.append(
                t("⚠ git not available: check that it is installed and your "
                  "identity is configured (git config user.name/user.email)"))
        if detalles:
            QMessageBox.information(
                self, t("Project ready"),
                t("The project was prepared:\n\n  · {detalles}"
                  "\n\nPress '▶ Start loop' whenever you want to start.",
                  detalles="\n  · ".join(detalles)))
        else:
            QMessageBox.information(
                self, t("Project"), t("It already had all the Dédalo files."))

    def _quitar_proyecto(self):
        nombre = self.cmb.currentText()
        if not nombre or nombre not in self.proyectos:
            return
        if self.loop and self.loop.state() == QProcess.Running:
            QMessageBox.warning(self, t("Dédalo running"),
                                t("Stop the loop before removing a project."))
            return
        info = self.proyectos.get(nombre) or {}
        ruta = info.get("ruta") or ""
        if ruta:
            resp = QMessageBox.question(
                self, t("Remove project"),
                t("Remove the project from the list?\n\nIts dedalo files will "
                  "also be deleted from disk:\n"
                  "  · dedalo.sh, gate.sh, mapear.sh\n"
                  "  · plan.md, lecciones.md and progreso.log\n\n"
                  "The rest of the project's code is NOT touched."),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if resp != QMessageBox.Yes:
                return
        else:
            # Project without a path (orphan config): just remove it from the list
            resp = QMessageBox.question(
                self, t("Remove project"),
                t("This project has no valid path associated "
                  "(orphan config).\n\nRemove it from the list?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if resp != QMessageBox.Yes:
                return
        if self.proyectos.pop(nombre, None) is not None:
            eliminados = plantillas.quitar(ruta) if ruta else []
            # exacto: this is the one place where the list must shrink.
            guardar(self.proyectos, self.tema, exacto=True)
            # If the removed project was the active one, forget it in the
            # settings too: without this, closeEvent/_cambiar_proyecto would
            # re-save its config (and an orphan entry) when reopening the GUI.
            if getattr(self, "_nombre_activo", "") == nombre:
                self._nombre_activo = ""
                if hasattr(self, "_settings"):
                    self._settings.setValue("proyecto/activo", "")
            self.cmb.blockSignals(True)
            self.cmb.removeItem(self.cmb.currentIndex())
            self.cmb.blockSignals(False)
            if eliminados:
                QMessageBox.information(
                    self, t("Project removed"),
                    t("Removed from the list and deleted:\n  · {lista}",
                      lista="\n  · ".join(eliminados)))
            elif not ruta:
                QMessageBox.information(
                    self, t("Project removed"),
                    t("Removed from the list."))

    # ---------- Models ----------

    def _aplicar_sel_modelos(self):
        sug = modelos.sugerido(self._modelos)
        self.pan_ejec.aplicar_modelos({
            "tarea": self._sel_modelos.get("tarea") or sug,
            "revisor": self._sel_modelos.get("revisor") or sug,
        })

    def _guardar_sel_modelos(self, *_):
        self._sel_modelos = self.pan_ejec.modelos_seleccion()
        self._guardar_config_proyecto()
        guardar(self.proyectos, self.tema,
                seguridad=self.seguridad, modelos=self._sel_modelos)

    def _refrescar_modelos(self):
        modelos.invalidar_cache()
        nuevos = modelos.lista_modelos() or [cfg.MODELO_SUGERIDO]
        self._modelos = nuevos
        for sel in (self.pan_ejec.cmb_agente, self.pan_ejec.cmb_revisor):
            sel.activar_catalogo_global()
        self.pan_ejec.agregar_catalogo(nuevos)
        self.pan_ejec.info_modelos(
            len(nuevos), len(modelos.nombres_proveedores()))
        # invalidar_cache() also forgot the session probe: relaunch it.
        self.pan_ejec.refrescar_agentes()
        self._aplicar_sel_modelos()
        self.estado.setText(t("Models refreshed"))
        self._guardar_sel_modelos()

    # ---------- Internet ----------

    def _comprobar_net(self):
        net.verificar_async()
        self.pan_ejec.nota_net(net.ultimo_estado())

    # ---------- Loop ----------

    def _consentimiento_gate(self, ruta):
        """Asks for approval the first time a repo's gate is run.

        The gate runs project code (gate_checks/*.sh|.py) without a sandbox:
        a cloned repo can bring arbitrary commands. It lists what is going to
        be run and, if the user accepts, it is remembered by content hash (if
        the checks change, it is asked again).

        Returns True if the loop can be started.
        """
        if consentimiento.concedido(ruta, os.environ):
            return True
        fichas = consentimiento.ficheros(ruta)
        detalle = "\n".join(f"  • {f}" for f in fichas) or t("  (none)")
        resp = QMessageBox.warning(
            self, t("Run the project's gate"),
            t("The gate will run code from this repository with your "
              "permissions, without a sandbox:\n\n"
              "{detalle}\n\n"
              "Run it only if you trust this project. Trust and run?",
              detalle=detalle),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resp != QMessageBox.Yes:
            return False
        try:
            consentimiento.confiar(ruta)
        except OSError:
            pass
        return True

    def _iniciar_loop(self):
        p = self._proyecto_actual()
        if not p:
            return
        estado_net = net.ultimo_estado()
        if estado_net is None:
            # Not known yet: refresh in the background instead of blocking the
            # UI thread (the check can take up to 2×TIMEOUT_INTERNET seconds).
            # Optimistic: the loop itself aborts on start if there is no
            # network, and the warning appears as soon as the state is known.
            net.verificar_async()
        elif not estado_net:
            QMessageBox.warning(
                self, t("No internet"),
                t("There is no internet connection.\n\nThe opencode AI models "
                  "cannot respond and the loop will stop on start. "
                  "Connect to the network and try again."))
            return
        ruta = p[1]
        if not self._consentimiento_gate(ruta):
            return
        # Shared registry: never launch a duplicate for a project that already
        # has a loop running (e.g. one an AI started over MCP).
        est_loop = loops_estado.estado(self._nombre_activo)
        if est_loop["corriendo"]:
            QMessageBox.information(
                self, t("Dédalo running"),
                t("A loop is already running for this project "
                  "(started by {origen}). Stop it before launching another.",
                  origen=est_loop["origen"] or "?"))
            self._refrescar_loop_externo()
            return
        self._capturar_lanzamiento()
        self._guardar_config_proyecto()
        conf = self._lanzamiento
        nav_conf = self.pan_ejec.navegador_config()

        base_env = dict(e.split("=", 1) for e in QProcess.systemEnvironment()
                        if "=" in e)
        plan = loop_launch.preparar(conf, nav_conf, base_env,
                                    nombre=self._nombre_activo, origen="gui")
        detectados = plan["detectados"]
        if not detectados:
            self.estado.setText(
                t("No CLI agent with a session was detected (opencode, codex or claude)"))
            panel = self.pan_logs.panel_loop
            panel.clear()
            panel.appendPlainText(
                t("> loop (python engine)  (no usable agents: install or "
                  "log into opencode, codex or claude)"))
            self.pan_ejec.b_iniciar.setEnabled(True)
            return

        agente_tarea = plan["agente_tarea"]
        agente_revisor = plan["agente_revisor"]
        modelo_tarea = plan["modelo_tarea"]
        modelo_revisor = plan["modelo_revisor"]
        programa, args_motor = plan["programa"], plan["argv"]
        env = [f"{k}={v}" for k, v in plan["env"].items()]

        panel = self.pan_logs.panel_loop
        panel.clear()
        panel.appendPlainText(
            f"> loop {' '.join(args_motor) or 'loop'}  "
            f"(agent={agente_tarea}, task model={modelo_tarea or 'n/a'}, "
            f"reviewer={agente_revisor}, reviewer model="
            f"{modelo_revisor or 'n/a'}, "
            f"nav={'on' if nav_conf['activo'] else 'off'}, "
            f"dual={conf['dual']}, "
            f"cost/iter={conf['costo_iter']} USD, iter={conf['iteraciones']})")
        self.loop = Proceso(panel, on_fin=self._loop_fin)
        self.loop.setWorkingDirectory(ruta)
        self.loop.setEnvironment(env)
        self.loop.start(programa, args_motor)
        self.pan_ejec.b_iniciar.setEnabled(False)
        self.pan_ejec.b_detener.setEnabled(True)
        self.pan_ejec.b_gate.setEnabled(False)
        self.cmb.setEnabled(False)
        self.timer.start(cfg.TIMER_TAIL_MS)
        self._inicio_loop_ts = time.time()
        self._log_marca = self._log_inicio = self._tam_log(ruta)
        self._iter_actual = 0
        self._set_fase_loop(0, int(conf['iteraciones'] or 0), corriendo=True)

        # Webhook: start
        self._webhook_enviar("inicio", {
            "proyecto": self._nombre_activo,
            "modelo_tarea": conf['agente'],
            "modelo_revisor": conf['revisor'],
        })

    def _limpiar_sesiones_proyecto(self, ruta_proyecto, desde_ms):
        """Deletes the opencode sessions the loop created in the project.

        Criteria: directory == project and created after the run started.
        Note: dedalo.sh also cleans up on exit (trap EXIT); this covers
        manual stopping (the GUI sends SIGTERM; only if it does not finish
        in a few seconds does it escalate to SIGKILL; the bash trap never runs).

        It runs inside a `Trabajo` because they are `subprocess.run` with
        timeout=120 s: one to list and one per session to delete, so with 10
        sessions that was up to 22 min. On the UI thread it froze the window
        right after clicking Stop, and the buttons stayed disabled until it
        finished.

        Returns how many it deleted and does NOT touch any widget: the log
        text is written by `_limpiar_sesiones_hecho` (already on the UI thread).
        """
        if not ruta_proyecto:
            return 0
        # modelos.ruta_binario covers PATH + fallback ~/.opencode/bin (with
        # .exe/.cmd suffixes on Windows); this duplicated lookup existed before.
        binario = modelos.ruta_binario("opencode")
        if not binario:
            return 0

        def _ejecutar(*args):
            try:
                return subprocess.run(
                    [binario, *args],
                    capture_output=True, text=True, timeout=120,
                    cwd=ruta_proyecto,
                )
            except (subprocess.TimeoutExpired, OSError):
                return None

        res = _ejecutar("session", "list", "--format", "json")
        if not res or res.returncode != 0:
            return 0
        try:
            sesiones = json.loads(res.stdout or "[]")
        except json.JSONDecodeError:
            return 0
        ids = [
            s["id"] for s in sesiones
            if s.get("directory") == ruta_proyecto
            and int(s.get("created") or 0) >= desde_ms
        ]
        for id_ in ids:
            _ejecutar("session", "delete", id_)
        return len(ids)

    def _limpiar_sesiones_hecho(self, borradas):
        """UI slot: reflects in the log what the cleanup thread deleted."""
        if borradas:
            self.pan_logs.panel_loop.appendPlainText(
                f"[dedalo] 🧹 opencode sessions deleted: {borradas}")

    def _programar_limpiar_sesiones(self, ruta_proyecto):
        """Launches session cleanup in the background.

        `desde_ms` is computed here, on the UI thread, so it is the real
        instant of the stop and not the moment the background thread gets
        to read it.
        """
        if not ruta_proyecto:
            return
        if self._worker_sesiones_limpieza is not None \
                and self._worker_sesiones_limpieza.isRunning():
            return
        desde_ms = int(self._inicio_loop_ts * 1000) if self._inicio_loop_ts else 0
        worker = Trabajo(
            lambda: self._limpiar_sesiones_proyecto(ruta_proyecto, desde_ms))
        worker.conectar(self._limpiar_sesiones_hecho)
        worker.liberar(self, "_worker_sesiones_limpieza")
        worker.start()
        self._worker_sesiones_limpieza = worker

    def _loop_fin(self):
        p = self._proyecto_actual()
        self.pan_ejec.b_iniciar.setEnabled(True)
        self.pan_ejec.b_detener.setEnabled(False)
        if p:
            self.pan_ejec.b_gate.setEnabled(
                os.path.exists(os.path.join(p[1], "gate.sh")))
        self.cmb.setEnabled(True)
        self.timer.stop()
        self._revision_pendiente = False
        self.pan_ejec.panel_revision.ocultar()
        self._set_fase_loop(0, 0, corriendo=False)
        if p:
            self.pan_plan.cargar(os.path.join(p[1], "plan.md"))
            self.pan_lecciones.cargar(os.path.join(p[1], "lecciones.md"))
            self.pan_git.cargar(p[1])
            self.pan_mapa.cargar(os.path.join(p[1], "mapeo.txt"))

        # Webhook: end
        if self._inicio_loop_ts:
            duracion_min = (time.time() - self._inicio_loop_ts) / 60.0
        else:
            duracion_min = 0.0
        # Parse the log for the summary (only THIS run: from _log_inicio)
        if p:
            log = os.path.join(p[1], "progreso.log")
            try:
                with open(log, "rb") as f:
                    f.seek(self._log_inicio)
                    contenido = f.read().decode("utf-8", "replace")
                hechas = contenido.count("✔ commit:") + contenido.count("✔ tarea completada")
                bloqueadas = contenido.count("tarea bloqueada")
                total = hechas + bloqueadas
                # Cost: exact per iteration if present, otherwise accumulated
                costes_iter = re.findall(r"Costo iteración \d+:\s*([\d.]+)\s*USD", contenido)
                if costes_iter:
                    coste = round(sum(float(c) for c in costes_iter), 2)
                else:
                    costes = re.findall(r"Costo estimado acumulado:\s*([\d.]+)\s*USD", contenido)
                    coste = float(costes[-1]) if costes else 0.0
            except Exception:
                hechas = bloqueadas = total = 0
                coste = 0.0
            self._webhook_enviar("fin", {
                "hechas": hechas,
                "total": total,
                "coste": coste,
                "duracion_min": round(duracion_min, 1),
            })

        # Session cleanup goes last and in the background: the event loop
        # must be repainted and usable before launching it.
        if p:
            self._programar_limpiar_sesiones(p[1])

    def _detener_loop(self):
        if self.loop and self.loop.state() == QProcess.Running:
            self.pan_logs.panel_loop.appendPlainText(
                "[manual] " + t("stopping the loop…"))
            self.loop.terminate()
            # No `waitForFinished(5000)`: it blocks the UI thread for five
            # seconds on the button the user just pressed. The timer does
            # the escalation to SIGKILL.
            if self.loop.state() != QProcess.NotRunning:
                QTimer.singleShot(5000, self._loop_forzar_kill)
            return
        # No local loop: it may be one started by an external agent (MCP/CLI).
        p = self._proyecto_actual()
        if p and self._loop_externo:
            est = loops_estado.estado(p[0])
            if est["corriendo"]:
                self.pan_logs.panel_loop.appendPlainText(
                    "[manual] " + t("stopping the external loop (pid {pid})…",
                                    pid=est["pid"] or "?"))
                loops_estado.matar(est["pid"], espera=5)
                loops_estado.olvidar(p[0])
            self._loop_externo = False
            self.timer.stop()
            self.pan_ejec.establecer_running(False)
            self.pan_ejec.b_iniciar.setEnabled(True)
            self.pan_ejec.b_detener.setEnabled(False)
            self._set_fase_loop(0, 0, corriendo=False)

    def _loop_forzar_kill(self):
        """Escalates to SIGKILL if the loop ignores the timer's SIGTERM."""
        if self.loop and self.loop.state() == QProcess.Running:
            self.pan_logs.panel_loop.appendPlainText(
                "[manual] " + t("the loop is not responding to SIGTERM; "
                                "forcing with SIGKILL…"))
            self.loop.kill()

    def _tail_log(self):
        p = self._proyecto_actual()
        if not p:
            return
        log = os.path.join(p[1], "progreso.log")
        try:
            tam = os.path.getsize(log)
        except OSError:
            return
        if tam == self._log_tam:
            return  # no changes: neither reread nor repaint
        self._log_tam = tam
        inicio = max(0, tam - cfg.TAIL_LOG_BYTES)
        try:
            with open(log, "rb") as f:
                f.seek(inicio)
                datos = f.read().decode("utf-8", "replace")
        except OSError:
            return
        if inicio > 0 and "\n" in datos:
            datos = datos[datos.index("\n") + 1:]  # discards the cut line
        self.pan_logs.panel_loop.setPlainText(datos)
        self.pan_logs.panel_loop.ensureCursorVisible()

        # Detect events ONLY in what is new since the last read (edge-triggered:
        # avoids resending the same webhook on every refresh). Do not use `datos`
        # (the tail window) because it repeats content already seen each refresh.
        if self._log_marca > tam:
            self._log_marca = tam  # log truncated/rotated
        if tam > self._log_marca:
            try:
                with open(log, "rb") as f:
                    f.seek(self._log_marca)
                    nuevo = f.read().decode("utf-8", "replace")
            except OSError:
                nuevo = ""
            self._log_marca = tam
            self._procesar_eventos_log(nuevo)

        # Pill and stepper: current iteration + detected phase
        corriendo = bool(self.loop) and self.loop.state() == QProcess.Running
        its = re.findall(r"== Iteración\s+(\d+)", datos)
        if its:
            self._iter_actual = max(int(x) for x in its)
        if corriendo:
            total = int(self._lanzamiento.get("iteraciones") or 0)
            self._set_fase_loop(self._iter_actual, total, corriendo=True)

    def _procesar_eventos_log(self, texto):
        """Triggers webhooks/notifications from a NEW fragment of the log."""
        bajo = texto.lower()
        if "tokens/cuota agotados" in bajo or "cuota agotada" in bajo:
            self._webhook_enviar("tokens", {})
        elif "error crítico" in bajo or "abortado:" in bajo:
            self._webhook_enviar("error", {"detalle": t("See progreso.log")})
        if "tarea bloqueada" in bajo:
            self._notificar_tarea_bloqueada(texto)

    def _tam_log(self, ruta):
        """Size of progreso.log in bytes (0 if it does not exist)."""
        try:
            return os.path.getsize(os.path.join(ruta, "progreso.log"))
        except OSError:
            return 0

    def _notificar_tarea_bloqueada(self, log_texto):
        # Extract the task name from the log
        m = re.search(r"tarea bloqueada[:\s]+([^\n]+)", log_texto, re.IGNORECASE)
        tarea = m.group(1).strip() if m else t("unknown")
        self.estado.setText(t("⚠ Blocked task: {tarea}", tarea=tarea))
        # Alert sound: fire-and-forget. `notify-send` can hang for up to its
        # timeout; running it with subprocess.run would block the UI thread.
        try:
            subprocess.Popen(
                ["notify-send", "Dédalo",
                 t("Blocked task: {tarea}", tarea=tarea)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL)
        except Exception:
            pass
        # Beep
        try:
            sys.stdout.write('\a')
            sys.stdout.flush()
        except Exception:
            pass

        # Webhook: blocked
        self._webhook_enviar("bloqueada", {"tarea": tarea})

    def _comprobar_revision_pendiente(self):
        """Detects whether dedalo.sh is waiting for a manual review."""
        if not self.loop or self.loop.state() != QProcess.Running:
            if self._revision_pendiente:
                self._revision_pendiente = False
                self.pan_ejec.panel_revision.ocultar()
            return
        if not self.pan_ejec.revision_manual_activa():
            return
        p = self._proyecto_actual()
        if not p:
            return
        ruta = p[1]
        dir_revision = os.path.join(ruta, ".dedalo_review")
        archivo_esperando = os.path.join(dir_revision, "waiting")
        archivo_diff = os.path.join(dir_revision, "diff.txt")
        archivo_tarea = os.path.join(dir_revision, "tarea.txt")

        if os.path.exists(archivo_esperando) and not self._revision_pendiente:
            # Read task and diff
            tarea = ""
            try:
                with open(archivo_tarea, encoding="utf-8") as f:
                    tarea = f.read().strip()
            except OSError:
                pass
            self._revision_pendiente = True
            self.pan_ejec.panel_revision.mostrar_revision(ruta, tarea, archivo_diff, os.path.join(dir_revision, "decision"))
            self.pan_logs.panel_loop.appendPlainText(
                t("\n[GUI] ⏸ Manual review required for: {tarea}", tarea=tarea))

        elif not os.path.exists(archivo_esperando) and self._revision_pendiente:
            # The review is no longer pending (it was resolved)
            self._revision_pendiente = False
            self.pan_ejec.panel_revision.ocultar()

    def _revision_aprobada(self):
        self._revision_pendiente = False
        self.estado.setText(t("✓ Diff approved, continuing loop…"))

    def _revision_rechazada(self, motivo):
        self._revision_pendiente = False
        self.estado.setText(t("✗ Diff rejected: {motivo}…", motivo=motivo[:60]))
        self.pan_logs.panel_loop.appendPlainText(
            t("[GUI] Rejected: {motivo}", motivo=motivo))

    # ---------- Gate ----------

    def _ejecutar_gate(self):
        p = self._proyecto_actual()
        if not p:
            return
        _, ruta = p
        panel = self.pan_logs.panel_gate
        panel.clear()
        programa, args = argv_gate(getattr(sys, "frozen", False))
        panel.appendPlainText("> " + " ".join([programa, *args]))
        env = loop_launch.filtrar_entorno(os.environ)
        if not getattr(sys, "frozen", False):
            env["PYTHONPATH"] = _raiz_codigo() + (
                os.pathsep + env["PYTHONPATH"]
                if env.get("PYTHONPATH") else "")
        self.gate = Proceso(panel)
        self.gate.setWorkingDirectory(ruta)
        self.gate.setEnvironment([f"{k}={v}" for k, v in env.items()])
        self.gate.start(programa, args)

    # ---------- Webhooks ----------

    def _webhook_enviar(self, evento: str, datos: dict):
        """Sends the webhook if the event is enabled."""
        if hasattr(self, 'webhook') and self.webhook:
            # Add project if not present
            if "proyecto" not in datos:
                datos["proyecto"] = self._nombre_activo
            self.webhook.enviar(evento, datos)

    # ---------- Metrics ----------

    def _actualizar_metricas(self):
        p = self._proyecto_actual()
        if p:
            self.pan_metricas.cargar(p[1])

    # ---------- Rollback (Revert commit) ----------

    def _ejecutar_revert(self, sha: str):
        p = self._proyecto_actual()
        if not p:
            return
        _, ruta = p

        # Confirm
        resp = QMessageBox.question(
            self, t("Revert commit"),
            t("Revert commit {sha}?\n\n"
              "It will run: git revert --no-commit {sha_full} && "
              "git commit -m 'revert: ...'\n"
              "This creates a new commit that undoes the changes.",
              sha=sha[:8], sha_full=sha),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resp != QMessageBox.Yes:
            return

        self.estado.setText(t("Reverting commit {sha}...", sha=sha[:8]))
        worker = Trabajo(lambda: self._git_revert(ruta, sha))
        worker.conectar(lambda ok: self._post_revert(ok, sha))
        worker.liberar(self, "_worker_revert")
        worker.start()
        self._worker_revert = worker

    def _git_revert(self, ruta: str, sha: str) -> bool:
        try:
            import subprocess
            # Revert without committing
            r1 = subprocess.run(["git", "revert", "--no-commit", sha],
                                cwd=ruta, capture_output=True, text=True, timeout=30)
            if r1.returncode != 0:
                return False
            # Commit of the revert
            r2 = subprocess.run(["git", "commit", "-m", f"revert: {sha[:8]}"],
                                cwd=ruta, capture_output=True, text=True, timeout=30)
            return r2.returncode == 0
        except Exception:
            return False

    def closeEvent(self, event):
        """Saves size/position/state and the active project's config. Cleans up timers and processes."""
        if hasattr(self, "pan_ejec"):
            self._capturar_lanzamiento()
            self._guardar_config_proyecto()
        self._settings.setValue("ventana/geometria", self.saveGeometry())
        # Stop timers
        for temporizador in (self.timer, self.timer_temp, self.timer_net,
                             self.timer_revision, self.timer_metricas,
                             self.timer_plan, self.timer_lecciones,
                             self.timer_incidencias, self.timer_estado):
            temporizador.stop()
        # Terminate the loop process if running (SIGTERM and, if it does not die, SIGKILL)
        if self.loop and self.loop.state() == QProcess.Running:
            self.loop.terminate()
            if not self.loop.waitForFinished(5000):
                self.loop.kill()
                self.loop.waitForFinished(1000)
        super().closeEvent(event)

    def _post_revert(self, ok: bool, sha: str):
        if ok:
            self.estado.setText(t("✓ Commit {sha} reverted", sha=sha[:8]))
            p = self._proyecto_actual()
            if p:
                self.pan_git.cargar(p[1])
                self.pan_plan.cargar(os.path.join(p[1], "plan.md"))
                self.pan_mapa.cargar(os.path.join(p[1], "mapeo.txt"))
                self._tail_log()
        else:
            self.estado.setText(t("✗ Error reverting {sha}", sha=sha[:8]))
            QMessageBox.warning(self, t("Error"),
                                t("Could not revert commit {sha}", sha=sha[:8]))

    def _limpiar_git_framework(self):
        """Ensures .gitignore has the Dédalo block and stops tracking the framework."""
        p = self._proyecto_actual()
        if not p:
            return
        _, ruta = p
        resp = QMessageBox.question(
            self, t("Framework out of git"),
            t("It will run:\n"
              "1) Add the Dédalo block to the project's .gitignore\n"
              "2) git rm --cached of dedalo.sh, gate.sh, gate_checks/, plan.md,\n"
              "   lecciones.md, mapeo.txt, progreso.log, metrics.jsonl, etc.\n\n"
              "The files REMAIN on disk (dedalo needs them); they just stop "
              "being in the git repo.\nContinue?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if resp != QMessageBox.Yes:
            return

        def trabajo():
            modificado = plantillas.asegurar_gitignore(ruta)
            salidos = plantillas.quitar_framework_del_git(ruta)
            return (modificado, len(salidos))

        self.estado.setText(t("Applying framework cleanup in git..."))
        worker = Trabajo(trabajo)
        worker.conectar(self._post_limpiar_git_framework)
        worker.liberar(self, "_worker_limpiar")
        worker.start()
        self._worker_limpiar = worker

    def _post_limpiar_git_framework(self, res):
        modificado, salidos = res
        if salidos or modificado:
            self.estado.setText(
                t("✓ .gitignore updated and {salidos} files stopped being "
                  "tracked (left uncommitted; commit in the project's repo "
                  "if you want to persist it)", salidos=salidos))
            msg = (t("· .gitignore updated: {modificado}", modificado=modificado)
                   + "\n" + t("· files out of tracking: {salidos}", salidos=salidos))
            QMessageBox.information(self, t("Framework out of git"), msg)
        else:
            self.estado.setText(t("Nothing to clean (it was already clean)"))
        p = self._proyecto_actual()
        if p:
            self.pan_git.cargar(p[1])

def _resolver_registro_corrupto(exc):
    """Asks the user what to do with a corrupted registry.

    Returns True if we should keep starting up (they accepted starting from
    scratch, with the data safe in the .corrupto copy), False if it must exit.
    """
    caja = QMessageBox()
    caja.setIcon(QMessageBox.Critical)
    caja.setWindowTitle(t("Corrupted projects registry"))
    caja.setText(
        t("Could not read the projects registry:\n{ruta}", ruta=exc.ruta)
    )
    caja.setInformativeText(
        t("It may be truncated or hand-edited. A full copy has been saved "
          "to:\n{copia}\n\n"
          "If you quit now, the file stays where it is and you can repair it "
          "or restore it by hand. If you prefer to continue, the project list "
          "will start empty (your data is still in the copy).", copia=exc.copia)
    )
    salir = caja.addButton(t("Quit and repair it by hand"),
                           QMessageBox.RejectRole)
    seguir = caja.addButton(
        t("Start from scratch (copy preserved)"), QMessageBox.DestructiveRole
    )
    caja.setDefaultButton(salir)
    caja.exec()
    return caja.clickedButton() is seguir


def main():
    app = QApplication(sys.argv)
    # Sets the WM_CLASS/app name so that the desktop launcher
    # (StartupWMClass=dedalo) groups the window and its icon in the dock well.
    app.setApplicationName("dedalo")
    app.setDesktopFileName("dedalo")

    # Active UI language: DEDALO_IDIOMA (tests/overrides) wins over the
    # persisted setting, which defaults to English.
    entorno = os.environ.get("DEDALO_IDIOMA", "").strip()
    if entorno:
        set_idioma(entorno)
    else:
        set_idioma(QSettings("dedalo", "panel").value("idioma", "en"))

    # The project registry is the user's complete state (projects, theme,
    # webhooks, models). If its JSON is corrupted we must STOP here:
    # Ventana.__init__ loads the registry and, if it comes out empty, saves it
    # again, so a broken JSON used to become "all projects deleted" silently
    # at startup.
    try:
        verificar_registro()
    except RegistroCorrupto as exc:
        if not _resolver_registro_corrupto(exc):
            return
        descartar_registro_corrupto()

    inicializar_temas()
    icono = os.path.join(os.path.dirname(__file__), "icono.svg")
    if os.path.exists(icono):
        app.setWindowIcon(QIcon(icono))
    ventana = Ventana()
    ventana.show()
    sys.exit(app.exec())
