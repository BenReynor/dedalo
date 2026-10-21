"""Widgets for the panel tabs and the overheat warning.

Each class builds its UI and exposes signals/methods; the window (app.py) only
orchestrates: connects signals, manages processes and updates state.
"""

import json
import os
import re
import subprocess

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import configuracion as cfg
from . import modelos, plan, rutas
from .i18n import t
from .modelos import PROVEEDORES_CATALOGO
from .paneles_webhooks import PanelWebhooks
from .proceso import PanelTarea, Trabajo
from .selector_modelo import SelectorModelo


def _fuente_monospace(objeto):
    from PySide6.QtGui import QFont
    fuente = QFont(objeto.font())
    fuente.setFamily(cfg.FUENTE_MONO)
    objeto.setFont(fuente)


def _escribir_privado(ruta, texto):
    """Writes a review decision file with 0o600 (it is user-sensitive data).

    Swallows OSError like the previous plain `open()` did, so a failed write
    never breaks the UI."""
    try:
        fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
    except OSError:
        pass


def _fuente_ui(objeto):
    from PySide6.QtGui import QFont
    fuente = QFont(objeto.font())
    fuente.setFamily(cfg.FUENTE_UI)
    objeto.setFont(fuente)


def _numero(texto, defv, tipo=float, minimo=None):
    """Parses a tolerant numeric text (ignores weird characters)."""
    try:
        valor = tipo(re.sub(r"[^\d.-]", "", texto or "").strip() or defv)
    except ValueError:
        valor = defv
    if minimo is not None:
        valor = max(minimo, valor)
    return valor


class _LabelMuted(QLabel):
    """Label with secondary text color."""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setProperty("status", "muted")


class _LabelStatus(QLabel):
    """Label with semantic status (success/warning/error/info)."""
    def __init__(self, text="", status="info", parent=None):
        super().__init__(text, parent)
        self.setProperty("status", status)


class _BtnPrimary(QPushButton):
    """Primary button (main action)."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)


class _BtnGhost(QPushButton):
    """Secondary (ghost) button."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("ghost", True)


class _BtnDanger(QPushButton):
    """Destructive (danger) button."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("danger", True)


class _BtnDangerGhost(QPushButton):
    """Subtle destructive button (red border/text, transparent background).

    For risky actions in tables (revert, delete) where a solid red block
    would be visually too heavy.
    """
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("danger_ghost", True)


class _BtnSmallGhost(QPushButton):
    """Compact ghost button (tables/lists), consistent with the theme."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("ghost", True)
        self.setProperty("small", True)


# ─── COCKPIT: pipeline, pill and phase detection ──────────────────

# Canonical order of the loop phases (mirrors dedalo.sh)
PIPELINE_FASES = ["Plan", "Agente", "Gate", "Revisor", "Commit"]


def _sincronizar_modelo(selector, cmb_cli):
    """The model selector only applies to opencode.

    codex and claude take their model from their own account, so the selector is
    disabled with a note: it prevents the GUI from offering an opencode model
    that the script later silently ignores.
    """
    if selector is None or cmb_cli is None:
        return
    actual = cmb_cli.currentData() or "auto"
    es_opencode = actual not in ("codex", "claude")
    selector.setEnabled(es_opencode)
    if not es_opencode:
        selector.setToolTip(
            t("{actual} does not accept --model here: the model configured "
              "in its own account is used", actual=actual))


def fase_actual(log_ruta: str) -> str:
    """Deduces the current loop phase from progreso.log (last ~40 lines).

    The program decides the phase: reviewer/gate/commit are detected by
    markers dedalo.sh already emits. Returns PIPELINE_FASES or "" if not running.
    """
    if not log_ruta or not os.path.isfile(log_ruta):
        return ""
    try:
        with open(log_ruta, encoding="utf-8", errors="replace") as f:
            lineas = f.readlines()[-40:]
    except OSError:
        return ""
    texto = "\n".join(lineas)
    if re.search(r"DEDALO FINALIZADO|ABORTADO|tarea BLOQUEADA", texto):
        return ""
    if re.search(r"sin login|no hay sesión|credenciales|API key inválida|"
                 r"no autenticado|autenticarse", texto):
        return "Gate"
    if re.search(r"ESPERANDO REVISIÓN MANUAL|REVISIÓN MANUAL", texto):
        return "Revisor"
    if re.search(r"revisor.*(PASS|FAIL)|VERDICT:", texto):
        return "Revisor"
    if re.search(r"GATE|gate\.sh|gate_checks", texto):
        return "Gate"
    if re.search(r"commit en|commit:", texto):
        return "Commit"
    if re.search(r"== Iteración", texto):
        return "Agente"
    if re.search(r"DEDALO INICIADO|-- Iteración", texto):
        return "Agente"
    return ""


class PipelineLoop(QWidget):
    """Painted pipeline flow: rounded nodes joined by connectors.

    Colors from the active theme (temas.colores_tema) so it matches the
    QSS. With cfg.MOTION the active node "breathes" (soft expanding halo).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pipeline_loop")
        self._tema_actual = cfg.TEMA_DEFECTO
        from .temas import colores_tema
        self._colores = colores_tema(self._tema_actual)
        self._estados = {nombre: "idle" for nombre in PIPELINE_FASES}
        self._pulso = 0.0
        self.setMinimumHeight(44)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        _fuente_ui(self)
        self._timer_pulso = QTimer(self)
        self._timer_pulso.setInterval(60)
        self._timer_pulso.timeout.connect(self._tick_pulso)
        if cfg.MOTION:
            self._timer_pulso.start()
        self.update()

    # ---- Public API -------------------------------------------------

    def set_tema(self, nombre: str):
        from .temas import colores_tema
        self._tema_actual = nombre
        self._colores = colores_tema(nombre)
        self.update()

    def setPendiente(self):
        for nombre in PIPELINE_FASES:
            self._estados[nombre] = "idle"
        self.update()

    def setFase(self, fase: str):
        """Marks the current phase as 'active', the earlier ones as 'ok'."""
        if not fase or fase not in self._estados:
            self.setPendiente()
            return
        alcanzada = False
        for nombre in PIPELINE_FASES:
            if nombre == fase:
                self._estados[nombre] = "active"
                alcanzada = True
            elif alcanzada:
                self._estados[nombre] = "idle"
            else:
                self._estados[nombre] = "ok"
        self.update()

    def setOk(self):
        for nombre in PIPELINE_FASES:
            self._estados[nombre] = "ok"
        self.update()

    def setFail(self):
        for nombre in PIPELINE_FASES:
            self._estados[nombre] = "fail"
        self.update()

    # ---- Animation / painting -----------------------------------------

    def _tick_pulso(self):
        self._pulso = (self._pulso + 0.05) % 1.0
        self.update()

    def paintEvent(self, evento):
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QColor, QFont, QPainter, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self._colores
        w, h = self.width(), self.height()

        margen = 14.0
        separacion = 28.0
        n = len(PIPELINE_FASES)
        pill_w = max(54.0, min(88.0, (w - 2 * margen - (n - 1) * separacion) / n))
        pill_h = 30.0
        cy = h / 2.0

        def centro(i):
            return margen + i * (pill_w + separacion) + pill_w / 2.0

        # Connectors (line + small node at the midpoint)
        p.setPen(QPen(c["border"], 2.0))
        for i in range(1, n):
            x0 = centro(i - 1) + pill_w / 2.0 + 3.0
            x1 = centro(i) - pill_w / 2.0 - 3.0
            if x1 <= x0:
                continue
            previo = self._estados[PIPELINE_FASES[i - 1]]
            if previo == "ok":
                color_linea = c["success"]
            elif previo == "active":
                color_linea = c["accent"]
            else:
                color_linea = c["border"]
            p.setPen(QPen(color_linea, 2.0))
            p.setBrush(color_linea)
            p.drawLine(QPointF(x0, cy), QPointF(x1, cy))
            p.setPen(QPen(c["bg_panel"], 1.0))
            p.drawEllipse(QPointF((x0 + x1) / 2.0, cy), 4.0, 4.0)

        # Nodes
        for i, nombre in enumerate(PIPELINE_FASES):
            estado = self._estados[nombre]
            cx = centro(i)
            rect = QRectF(cx - pill_w / 2.0, cy - pill_h / 2.0, pill_w, pill_h)

            if estado == "active" and cfg.MOTION:
                g = 9.0 * self._pulso
                halo = QColor(c["accent"])
                halo.setAlphaF(max(0.0, 0.30 * (1.0 - self._pulso)))
                p.setPen(Qt.NoPen)
                p.setBrush(halo)
                p.drawRoundedRect(rect.adjusted(-g, -g, g, g),
                                  pill_h / 2.0 + g, pill_h / 2.0 + g)

            if estado == "active":
                p.setPen(QPen(c["accent_claro"], 1.5))
                p.setBrush(c["accent"])
                color_tx = c["text_inverse"]
            elif estado == "ok":
                relleno = QColor(c["success"])
                relleno.setAlphaF(0.14)
                p.setPen(QPen(c["success"], 1.2))
                p.setBrush(relleno)
                color_tx = c["success"]
            elif estado == "fail":
                relleno = QColor(c["error"])
                relleno.setAlphaF(0.14)
                p.setPen(QPen(c["error"], 1.2))
                p.setBrush(relleno)
                color_tx = c["error"]
            else:
                p.setPen(QPen(c["border"], 1.0))
                p.setBrush(c["bg_sunken"])
                color_tx = c["text_tertiary"]
            p.drawRoundedRect(rect, pill_h / 2.0, pill_h / 2.0)

            fuente = QFont(self.font())
            fuente.setBold(estado == "active")
            p.setFont(fuente)
            p.setPen(color_tx)
            p.drawText(rect, Qt.AlignCenter, nombre)


class LoopPill(QLabel):
    """Loop status pill: '● 3/40 · phase: Gate'.

    With cfg.MOTION the pill "breathes" (amber opacity, QPropertyAnimation).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pill_loop")
        self.setProperty("running", False)
        self.setText(t("Loop stopped"))
        self._efecto = QGraphicsOpacityEffect(self)
        self._efecto.setOpacity(1.0)
        self.setGraphicsEffect(self._efecto)
        self._anim = QPropertyAnimation(self._efecto, b"opacity", self)
        self._anim.setDuration(2000)
        self._anim.setStartValue(0.55)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        if not cfg.MOTION:
            self._anim.stop()

    def _set_running(self, corriendo: bool):
        self.setProperty("running", corriendo)
        self.style().unpolish(self)
        self.style().polish(self)
        if not cfg.MOTION:
            self._efecto.setOpacity(1.0)
            return
        if corriendo:
            if not self._anim.state() == QPropertyAnimation.Running:
                self._anim.start()
        else:
            self._anim.stop()
            self._efecto.setOpacity(1.0)

    def setEstado(self, iter_actual: int, total: int, fase: str, corriendo: bool):
        self._set_running(corriendo)
        if corriendo:
            itxt = f"{iter_actual}/{total}" if total else str(iter_actual)
            ftext = t(" · phase: {fase}", fase=fase) if fase else ""
            self.setText(f"● {itxt}{ftext}")
        else:
            self.setText(t("Loop stopped"))


class AvisoTemperatura(QDialog):
    """Overheat warning with countdown.

    If nobody clicks the buttons before it reaches 0, the application shuts down.
    """

    def __init__(self, temp, segundos, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("⚠ PC too hot"))
        self.setModal(True)
        self._segundos = max(1, int(segundos))
        self._restante = self._segundos
        self._apagar = None

        v = QVBoxLayout(self)
        v.setSpacing(16)
        v.setContentsMargins(24, 24, 24, 24)

        self.lbl_temp = QLabel(
            t("⚠ Critical temperature: <b>{temp} °C</b>", temp=temp))
        self.lbl_temp.setWordWrap(True)
        v.addWidget(self.lbl_temp)

        self.lbl_conteo = QLabel(
            t("The application will shut down in <b>{restante}</b> s.",
              restante=self._restante))
        v.addWidget(self.lbl_conteo)

        h = QHBoxLayout()
        h.setSpacing(12)
        b_continuar = _BtnPrimary(t("Continue"))
        b_continuar.clicked.connect(self._continuar)
        b_apagar = _BtnDanger(t("Shut down now"))
        b_apagar.clicked.connect(self._apagar_ahora)
        h.addWidget(b_continuar)
        h.addWidget(b_apagar)
        v.addLayout(h)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)

    def _tick(self):
        self._restante -= 1
        if self._restante <= 0:
            self.timer.stop()
            self._apagar = True
            self.accept()
        else:
            self.lbl_conteo.setText(
                t("The application will shut down in <b>{restante}</b> s.",
                  restante=self._restante))

    def _continuar(self):
        self.timer.stop()
        self._apagar = False
        self.accept()

    def _apagar_ahora(self):
        self.timer.stop()
        self._apagar = True
        self.accept()

    @property
    def apagar(self):
        return self._apagar is True


class KanbanWidget(QWidget):
    """Kanban view of tasks: 3 columns (Pending, Done, Blocked)."""

    tarea_seleccionada = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._plan = None

        h = QHBoxLayout(self)
        h.setSpacing(8)
        h.setContentsMargins(0, 0, 0, 0)

        self.col_pend = self._crear_columna(t("Pending"), "#3b82f6")
        self.col_hecha = self._crear_columna(t("Done"), "#22c55e")
        self.col_bloq = self._crear_columna(t("Blocked"), "#ef4444")

        h.addWidget(self.col_pend, 1)
        h.addWidget(self.col_hecha, 1)
        h.addWidget(self.col_bloq, 1)

    def _crear_columna(self, titulo, color_acento):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setProperty("class", "kanban-col")
        frame.setStyleSheet("""
            QFrame[class="kanban-col"] {
                background-color: transparent;
                border-radius: 8px;
                border: 1px solid transparent;
            }
        """)
        v = QVBoxLayout(frame)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # Header with title + counter
        header = QHBoxLayout()
        header.setSpacing(8)
        lbl = QLabel(titulo)
        lbl.setStyleSheet(f"color: {color_acento}; font-weight: 600; font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;")
        header.addWidget(lbl)
        header.addStretch()
        badge = QLabel("0")
        badge.setProperty("class", "kanban-badge")
        badge.setStyleSheet(f"""
            QLabel[class="kanban-badge"] {{
                background: {color_acento};
                color: white;
                font-size: 10px;
                font-weight: 600;
                padding: 2px 6px;
                border-radius: 10px;
                min-width: 18px;
                text-align: center;
            }}
        """)
        badge.setAlignment(Qt.AlignCenter)
        header.addWidget(badge)
        frame.header_layout = header
        frame.badge = badge
        v.addLayout(header)

        lista = QListWidget()
        lista.setSelectionMode(QAbstractItemView.SingleSelection)
        lista.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lista.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: 1px solid {color_acento}40;
                border-radius: 6px;
                outline: none;
            }}
            QListWidget::item {{
                background: palette(base);
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 8px 10px;
                margin: 2px;
                color: palette(text);
            }}
            QListWidget::item:selected {{
                background: palette(highlight);
                color: palette(highlighted-text);
                border-color: palette(highlight);
            }}
            QListWidget::item:hover:!selected {{
                background: palette(alternate-base);
            }}
        """)
        lista.itemClicked.connect(lambda item: self.tarea_seleccionada.emit(item.text()))
        v.addWidget(lista, 1)

        frame.lista = lista
        frame.color_acento = color_acento
        return frame

    def cargar(self, plan_obj):
        self._plan = plan_obj
        self._actualizar()

    def _actualizar(self):
        for col in (self.col_pend, self.col_hecha, self.col_bloq):
            col.lista.clear()
            col.badge.setText("0")
        if not self._plan:
            return
        pend = hecha = bloq = 0
        for tarea in self._plan.tareas:
            item = QListWidgetItem(tarea["texto"])
            item.setToolTip(t("Line {linea}", linea=tarea["linea"]))
            # Visual states
            if tarea["estado"] == "pendiente":
                self.col_pend.lista.addItem(item)
                pend += 1
            elif tarea["estado"] == "hecha":
                # Visual strikethrough
                font = item.font()
                font.setStrikeOut(True)
                item.setFont(font)
                item.setForeground(Qt.gray)
                self.col_hecha.lista.addItem(item)
                hecha += 1
            elif tarea["estado"] == "bloqueada":
                # Red + bold
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setForeground(Qt.red)
                self.col_bloq.lista.addItem(item)
                bloq += 1
        # Update badges
        self.col_pend.badge.setText(str(pend))
        self.col_hecha.badge.setText(str(hecha))
        self.col_bloq.badge.setText(str(bloq))

    def clear(self):
        for col in (self.col_pend, self.col_hecha, self.col_bloq):
            col.lista.clear()
            col.badge.setText("0")


class PanelPlan(QWidget):
    """plan.md editor with task counter and Kanban view."""

    guardado = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._plan = None
        self._modificado = False
        self._huella_guardada = None

        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        self.lbl_conteo = _LabelMuted("")
        v.addWidget(self.lbl_conteo)

        # Splitter: Kanban on top, editor below
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setHandleWidth(4)
        self.splitter.setChildrenCollapsible(False)

        self.kanban = KanbanWidget()
        self.kanban.tarea_seleccionada.connect(self._en_editor_seleccionar)
        self.splitter.addWidget(self.kanban)

        self.editor = QPlainTextEdit()
        _fuente_monospace(self.editor)
        self.editor.textChanged.connect(self._actualizar_conteo)
        self.splitter.addWidget(self.editor)
        self.splitter.setSizes([200, 400])
        v.addWidget(self.splitter, 1)

        h = QHBoxLayout()
        h.setSpacing(8)
        b_recargar = _BtnGhost(t("Reload"))
        b_recargar.clicked.connect(lambda: self.cargar())
        b_guardar = _BtnPrimary(t("Save plan.md"))
        b_guardar.clicked.connect(self.guardar)
        h.addStretch()
        h.addWidget(b_recargar)
        h.addWidget(b_guardar)
        v.addLayout(h)

    def _en_editor_seleccionar(self, texto):
        """Scrolls the editor to the line of the task selected in Kanban."""
        if not self._plan:
            return
        for i, linea in enumerate(self.editor.toPlainText().splitlines(), 1):
            if texto in linea:
                cursor = self.editor.textCursor()
                cursor.movePosition(cursor.Start)
                for _ in range(i - 1):
                    cursor.movePosition(cursor.Down)
                self.editor.setTextCursor(cursor)
                self.editor.ensureCursorVisible()
                break

    def cargar(self, ruta=None):
        if ruta is not None:
            self._plan = plan.Plan(ruta) if ruta else None
        if not self._plan:
            self.clear()
            return
        if not self._plan.existe():
            self.editor.setPlainText(t(
                "# PLAN\n\n- [ ] your first task — criterion: ...\n"))
            self.lbl_conteo.setText(t("plan.md does not exist yet"))
            self.kanban.clear()
            self._modificado = False
            self._huella_guardada = None
            return
        self.editor.setPlainText(self._plan.cargar())
        self.kanban.cargar(self._plan)
        self._modificado = False
        self._huella_guardada = self._huella_plan()

    def _huella_plan(self):
        """(mtime, size) of plan.md on disk; None if it cannot be read."""
        if not self._plan:
            return None
        try:
            return (os.path.getmtime(self._plan.ruta),
                    os.path.getsize(self._plan.ruta))
        except OSError:
            return None

    def _recargar_si_cambio(self):
        """Reloads plan.md if it changed on disk; never overwrites unsaved edits."""
        if not self._plan or self._modificado:
            return
        huella = self._huella_plan()
        if huella is None or huella == self._huella_guardada:
            return
        self.editor.setPlainText(self._plan.cargar())
        self.kanban.cargar(self._plan)
        self._modificado = False
        self._huella_guardada = huella
        self.guardado.emit(self._plan.ruta)

    def guardar(self):
        if not self._plan:
            return
        self._plan.guardar(self.editor.toPlainText())
        self.lbl_conteo.setText(
            f"plan.md guardado ({self._plan.ruta})")
        self.kanban.cargar(self._plan)
        self._modificado = False
        self._huella_guardada = self._huella_plan()
        self.guardado.emit(self._plan.ruta)

    def clear(self):
        self.editor.clear()
        self.lbl_conteo.setText("")
        self.kanban.clear()

    def _actualizar_conteo(self):
        if not self._plan:
            return
        self._plan.texto = self.editor.toPlainText()
        self._modificado = True
        pend, hecho, bloqueada = self._plan.conteo()
        self.lbl_conteo.setText(
            t("Pending: {pend}   ·   Done: {hecho}   ·   "
              "Blocked: {bloqueada}",
              pend=pend, hecho=hecho, bloqueada=bloqueada))
        self.kanban._actualizar()


class PanelLecciones(QWidget):
    """Project memory (lecciones.md): editor + new lesson + auto-reload.

    The content is injected into the agent on every task (single correction of
    errors); dedalo also adds lessons when tasks get blocked.
    """

    guardado = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ruta = None
        self._modificado = False
        self._huella_guardada = None

        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        h = QHBoxLayout()
        lbl = QLabel(t("🧠 Project memory"))
        _fuente_ui(lbl)
        lbl.setStyleSheet("font-weight: 600; font-size: 13px;")
        h.addWidget(lbl)
        self.lbl_estado = _LabelMuted("")
        h.addWidget(self.lbl_estado)
        h.addStretch()
        self.lbl_apunte = _LabelMuted(
            t("Injected into the agent before every task; it adds an entry "
              "automatically when a task gets blocked."))
        h.addWidget(self.lbl_apunte)
        v.addLayout(h)

        self.editor = QPlainTextEdit()
        _fuente_monospace(self.editor)
        self.editor.textChanged.connect(self._marcar_modificado)
        v.addWidget(self.editor, 1)

        h = QHBoxLayout()
        h.setSpacing(8)
        b_nueva = _BtnPrimary(t("＋ New lesson"))
        b_nueva.clicked.connect(self._nueva_leccion)
        b_recargar = _BtnGhost(t("Reload"))
        b_recargar.clicked.connect(lambda: self.cargar())
        b_guardar = _BtnGhost(t("Save lecciones.md"))
        b_guardar.clicked.connect(self.guardar)
        h.addWidget(b_nueva)
        h.addStretch()
        h.addWidget(b_recargar)
        h.addWidget(b_guardar)
        v.addLayout(h)

    def _marcar_modificado(self):
        if self._ruta:
            self._modificado = True

    def _nueva_leccion(self):
        """Appends a lesson template to the end of the editor and focuses it."""
        from datetime import datetime
        bloque = t(
            "\n## {fecha} — Brief lesson title\n"
            "- Symptom: what failed.\n"
            "- Cause: why it failed.\n"
            "- Prevention: what to do to avoid repeating it.\n",
            fecha=datetime.now().strftime("%Y-%m-%d %H:%M"))
        texto = self.editor.toPlainText()
        if texto and not texto.endswith("\n"):
            bloque = "\n" + bloque
        self.editor.appendPlainText(bloque.strip("\n"))
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.End)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        self._modificado = True

    def cargar(self, ruta=None):
        if ruta is not None:
            self._ruta = ruta or None
        if not self._ruta:
            self.editor.clear()
            self.lbl_estado.setText("")
            return
        if not os.path.isfile(self._ruta):
            self.editor.setPlainText(
                t("# Lessons learned — project memory\n\n"))
            self.lbl_estado.setText(t("lecciones.md does not exist yet"))
            self._modificado = False
            self._huella_guardada = None
            return
        with open(self._ruta, encoding="utf-8", errors="replace") as f:
            self.editor.setPlainText(f.read())
        self._modificado = False
        self._huella_guardada = self._huella()
        self.lbl_estado.setText(self._ruta)

    def _huella(self):
        if not self._ruta:
            return None
        try:
            return (os.path.getmtime(self._ruta), os.path.getsize(self._ruta))
        except OSError:
            return None

    def _recargar_si_cambio(self):
        """Reloads lecciones.md if it changed on disk; never overwrites unsaved edits."""
        if not self._ruta or self._modificado:
            return
        huella = self._huella()
        if huella is None or huella == self._huella_guardada:
            return
        with open(self._ruta, encoding="utf-8", errors="replace") as f:
            self.editor.setPlainText(f.read())
        self._modificado = False
        self._huella_guardada = huella
        self.lbl_estado.setText(t("🔄 reloaded ({ruta})", ruta=self._ruta))

    def guardar(self):
        if not self._ruta:
            return
        with open(self._ruta, "w", encoding="utf-8") as f:
            f.write(self.editor.toPlainText())
        self._modificado = False
        self._huella_guardada = self._huella()
        self.lbl_estado.setText(
            t("lecciones.md saved ({ruta})", ruta=self._ruta))
        self.guardado.emit(self._ruta)


class PanelIncidencias(QWidget):
    """Loop incidents (incidencias.jsonl): failures and blocks, in a table.

    One JSON line per incident (ts, iteration, task, type, reason). The panel
    reloads itself when the file changes on disk, just like PanelLecciones.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ruta = None
        self._huella_guardada = None

        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        h = QHBoxLayout()
        lbl = QLabel(t("⚠ Loop incidents"))
        _fuente_ui(lbl)
        lbl.setStyleSheet("font-weight: 600; font-size: 13px;")
        h.addWidget(lbl)
        self.lbl_estado = _LabelMuted("")
        h.addWidget(self.lbl_estado)
        h.addStretch()
        self.lbl_apunte = _LabelMuted(
            t("Failures, aborts and blocked tasks with their real reason."))
        h.addWidget(self.lbl_apunte)
        v.addLayout(h)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(
            [t("Time"), t("Iteration"), t("Task"), t("Type"), t("Reason")])
        self.tree.setColumnWidth(0, 130)
        self.tree.setColumnWidth(1, 70)
        self.tree.setColumnWidth(2, 220)
        self.tree.setColumnWidth(3, 150)
        self.tree.setColumnWidth(4, 420)
        _fuente_monospace(self.tree)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionBehavior(QTreeWidget.SelectRows)
        v.addWidget(self.tree, 1)

        h = QHBoxLayout()
        h.setSpacing(8)
        b_recargar = _BtnGhost(t("Reload"))
        b_recargar.clicked.connect(lambda: self.cargar())
        h.addStretch()
        h.addWidget(b_recargar)
        v.addLayout(h)

    def cargar(self, ruta=None):
        if ruta is not None:
            self._ruta = ruta or None
        self.tree.clear()
        if not self._ruta or not os.path.isfile(self._ruta):
            self.lbl_estado.setText(t("incidencias.jsonl does not exist yet"))
            self._huella_guardada = None
            return
        try:
            with open(self._ruta, encoding="utf-8", errors="replace") as f:
                lineas = f.read().splitlines()
        except OSError:
            lineas = []
        n = 0
        for li in lineas:
            li = li.strip()
            if not li:
                continue
            try:
                d = json.loads(li)
            except ValueError:
                continue
            self.tree.addTopLevelItem(QTreeWidgetItem([
                str(d.get("ts", "")),
                str(d.get("iteracion", "")),
                str(d.get("tarea", "") or "—"),
                str(d.get("tipo", "")),
                str(d.get("motivo", "")),
            ]))
            n += 1
        self._huella_guardada = self._huella()
        self.lbl_estado.setText(
            t("{n} incident(s) · {ruta}", n=n, ruta=self._ruta))

    def _huella(self):
        if not self._ruta:
            return None
        try:
            return (os.path.getmtime(self._ruta), os.path.getsize(self._ruta))
        except OSError:
            return None

    def _recargar_si_cambio(self):
        """Reloads if incidencias.jsonl changed on disk (read-only)."""
        if not self._ruta:
            return
        huella = self._huella()
        if huella is None or huella == self._huella_guardada:
            return
        self.cargar()


class PanelMapa(QWidget):
    """Viewer for mapeo.txt (module -> test map)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ruta = None
        self._proyecto = None
        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        self.lbl_estado = _LabelMuted(t("No project"))
        v.addWidget(self.lbl_estado)

        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        _fuente_monospace(self.editor)
        v.addWidget(self.editor, 1)

        h = QHBoxLayout()
        h.setSpacing(8)
        b_recargar = _BtnGhost(t("Reload"))
        b_recargar.clicked.connect(lambda: self.cargar())
        b_regenerar = _BtnPrimary(t("🔄 Regenerate map"))
        b_regenerar.clicked.connect(self._regenerar)
        h.addStretch()
        h.addWidget(b_recargar)
        h.addWidget(b_regenerar)
        v.addLayout(h)

    def cargar(self, ruta=None, proyecto=None):
        if proyecto is not None:
            self._proyecto = proyecto
        elif ruta is None:
            self._proyecto = None
        if ruta is not None:
            self._ruta = ruta or None
        if not self._ruta or not os.path.isfile(self._ruta):
            self.editor.setPlainText(
                t("(mapeo.txt does not exist — press Regenerate)"))
            self.lbl_estado.setText(t("mapeo.txt not found"))
            return
        with open(self._ruta, encoding="utf-8", errors="replace") as f:
            self.editor.setPlainText(f.read())
        self.lbl_estado.setText(self._ruta)

    def _regenerar(self):
        if not self._ruta:
            return
        import subprocess
        dir_proy = self._proyecto or os.path.dirname(self._ruta)
        mapear_sh = rutas.mapear_sh(dir_proy)
        if not os.path.isfile(mapear_sh):
            self.lbl_estado.setText(t("mapear.sh not found in the project"))
            return
        try:
            salida = subprocess.run(["bash", mapear_sh], cwd=dir_proy,
                                    check=True, capture_output=True, text=True)
            # The bundled mapear.sh prints the map; a custom one may write the
            # file itself (as before), so only overwrite it with real output.
            if salida.stdout.strip():
                os.makedirs(os.path.dirname(self._ruta) or ".", exist_ok=True)
                with open(self._ruta, "w", encoding="utf-8") as f:
                    f.write(salida.stdout)
            self.cargar()
            self.lbl_estado.setText(
                t("mapeo.txt regenerated ({ruta})", ruta=self._ruta))
        except subprocess.CalledProcessError as e:
            self.lbl_estado.setText(
                t("Error: {msg}", msg=e.stderr.decode()[:120]))


class PanelRevision(QWidget):
    """Panel to review the diff before committing: shows diff, Approve/Reject buttons."""

    aprobado = Signal()
    rechazado = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ruta_proyecto = None
        self._archivo_diff = None
        self._archivo_senal = None

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        # Header
        h = QHBoxLayout()
        h.setSpacing(8)
        self.lbl_titulo = QLabel(t("⏸ Pending review"))
        _fuente_ui(self.lbl_titulo)
        self.lbl_titulo.setStyleSheet("font-weight: 600; font-size: 13px;")
        h.addWidget(self.lbl_titulo)
        h.addStretch()
        self.lbl_tarea = _LabelMuted("")
        h.addWidget(self.lbl_tarea)
        v.addLayout(h)

        # Diff viewer
        self.txt_diff = QPlainTextEdit()
        self.txt_diff.setReadOnly(True)
        _fuente_monospace(self.txt_diff)
        v.addWidget(self.txt_diff, 1)

        # Buttons
        h = QHBoxLayout()
        h.setSpacing(8)
        self.b_aprobar = _BtnPrimary(t("✓ Approve and commit"))
        self.b_aprobar.clicked.connect(self._emitir_aprobado)
        self.b_rechazar = _BtnDanger(t("✗ Reject and retry"))
        self.b_rechazar.clicked.connect(self._pedir_motivo_rechazo)
        h.addWidget(self.b_aprobar)
        h.addWidget(self.b_rechazar)
        v.addLayout(h)

        self.setVisible(False)

    def mostrar_revision(self, ruta_proyecto, tarea, archivo_diff, archivo_senal):
        self._ruta_proyecto = ruta_proyecto
        self._archivo_diff = archivo_diff
        self._archivo_senal = archivo_senal
        self.lbl_tarea.setText(t("Task: {tarea}", tarea=tarea))
        try:
            with open(archivo_diff, encoding="utf-8") as f:
                self.txt_diff.setPlainText(f.read())
        except OSError:
            self.txt_diff.setPlainText(t("(could not read the diff)"))
        self.setVisible(True)

    def ocultar(self):
        self.setVisible(False)
        self._archivo_diff = None
        self._archivo_senal = None

    def _emitir_aprobado(self):
        if self._archivo_senal:
            _escribir_privado(self._archivo_senal, "APPROVE\n# origen=gui\n")
        self.aprobado.emit()
        self.ocultar()

    def _pedir_motivo_rechazo(self):
        motivo, ok = QInputDialog.getMultiLineText(
            self, t("Rejection reason"),
            t("Explain what the agent must fix (it will be injected into "
              "the next attempt):"))
        if ok and motivo.strip():
            if self._archivo_senal:
                _escribir_privado(
                    self._archivo_senal,
                    f"REJECT\n{motivo.strip()}\n# origen=gui\n")
            self.rechazado.emit(motivo.strip())
            self.ocultar()


class PanelEjecucion(QWidget):
    """Launch options, loop control and live output."""

    iniciar = Signal()
    detener = Signal()
    gate = Signal()
    modelos_modificados = Signal()
    refrescar_modelos = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Internal scroll: the options readjust (and can scroll) if
        # the window is short; with enough height they span the full width.
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        contenido = QWidget()
        contenido.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        scroll.setWidget(contenido)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.addWidget(scroll)

        v = QVBoxLayout(contenido)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        # ===== HEADER: loop pipeline (lit phases) =====
        self.pipeline = PipelineLoop()
        v.addWidget(self.pipeline)

        # ===== ZONE 1: LAUNCH OPTIONS =====
        grupo = QGroupBox(t("Launch options"))
        g = QGridLayout(grupo)
        g.setSpacing(8)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        g.setContentsMargins(12, 12, 12, 12)

        def add_field(row, label_text, widget, placeholder=""):
            lbl = QLabel(label_text)
            _fuente_ui(lbl)
            g.addWidget(lbl, row, 0)
            if placeholder:
                widget.setPlaceholderText(placeholder)
            g.addWidget(widget, row, 1)

        def _llenar_combo_agente(cmb_cli):
            """Fills the combo with whatever is on the machine right now.

            An agent installed but WITHOUT A SESSION is shown marked and
            disabled: choosing it would abort the loop on the first iteration.
            """
            operativo = modelos.agentes_operativos()
            detectados = modelos.agentes_instalados()
            previo = cmb_cli.currentData()
            cmb_cli.blockSignals(True)
            cmb_cli.clear()
            if operativo:
                cmb_cli.addItem(
                    t("auto → {agente}", agente=operativo[0]), "auto")
                for a in detectados:
                    sin_sesion = modelos.sesion_agente(a) is False
                    etiqueta = (t("{agente} (no login)", agente=a)
                                if sin_sesion else a)
                    cmb_cli.addItem(etiqueta, a)
                    idx = cmb_cli.count() - 1
                    if sin_sesion:
                        # Disable only the item: the combo remains
                        # usable, but that agent cannot be chosen.
                        cmb_cli.model().item(idx).setEnabled(False)
                        cmb_cli.setItemData(
                            idx, t("{agente}: installed but no session started",
                                   agente=a),
                            Qt.ToolTipRole)
                cmb_cli.setCurrentIndex(0)
            else:
                cmb_cli.addItem(t("auto (no agents with session)"), "auto")
            cmb_cli.setToolTip(t(
                "Installed: {inst}\nWith session: {ses}\n"
                "Models: only for opencode",
                inst=((", ".join(detectados)) or t("none")),
                ses=((", ".join(operativo)) or t("none"))))
            cmb_cli.blockSignals(False)
            # Respect the selection if it still exists after filling.
            if previo and previo != "auto":
                idx = cmb_cli.findData(previo)
                if idx > 0 and cmb_cli.model().item(idx).isEnabled():
                    cmb_cli.setCurrentIndex(idx)
            return cmb_cli

        def contenedor_agente(selector):
            """Agent row = CLI combo + model selector in a single widget.

            The combo only offers INSTALLED agents (plus "auto"), so it never
            lets you pick one that doesn't exist. The model selector is enabled
            only with opencode: codex and claude don't accept --model here.
            """
            h = QHBoxLayout()
            h.setSpacing(8)
            cmb_cli = QComboBox()
            _llenar_combo_agente(cmb_cli)
            cmb_cli.setMinimumWidth(170)
            cmb_cli.currentIndexChanged.connect(
                lambda _i, s=selector, c=cmb_cli: _sincronizar_modelo(s, c))
            h.addWidget(cmb_cli, 0)
            h.addWidget(selector, 1)
            w = QWidget()
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            w.setLayout(h)
            _sincronizar_modelo(selector, cmb_cli)
            self._llenar_agente = _llenar_combo_agente
            return w, cmb_cli

        add_field(0, t("Until (HH:MM, empty = no limit):"),
                  self._crear_lineedit(cfg.LAUNCH_DEFECTO["hasta"], "22:00"))
        self.txt_hasta = g.itemAtPosition(0, 1).widget()

        add_field(1, t("Max iterations:"),
                  self._crear_lineedit(str(cfg.LAUNCH_DEFECTO["iteraciones"])))
        self.txt_iter = g.itemAtPosition(1, 1).widget()

        self.cmb_padre = QComboBox()
        self.cmb_padre.setEditable(True)
        self.cmb_padre.setInsertPolicy(QComboBox.NoInsert)
        self.cmb_padre.setPlaceholderText(
            cfg.LAUNCH_DEFECTO["padre"] or t("base branch"))
        add_field(2, t("Parent (base branch):"), self.cmb_padre)
        self.cmb_padre.setCurrentText(cfg.LAUNCH_DEFECTO["padre"])
        self.cmb_padre.currentTextChanged.connect(self.modelos_modificados)

        w_agente, self.cmb_agente_cli = contenedor_agente(
            SelectorModelo(proveedores=PROVEEDORES_CATALOGO))
        add_field(3, t("Agent + Model (task):"), w_agente)
        self.cmb_agente = g.itemAtPosition(3, 1).widget().layout().itemAt(1).widget()
        self.cmb_agente.currentTextChanged.connect(self.modelos_modificados)
        self.cmb_agente_cli.currentTextChanged.connect(self.modelos_modificados)

        w_revisor, self.cmb_revisor_cli = contenedor_agente(
            SelectorModelo(proveedores=PROVEEDORES_CATALOGO))
        add_field(4, t("Agent + Model (reviewer):"), w_revisor)
        self.cmb_revisor = g.itemAtPosition(4, 1).widget().layout().itemAt(1).widget()
        self.cmb_revisor.currentTextChanged.connect(self.modelos_modificados)
        self.cmb_revisor_cli.currentTextChanged.connect(self.modelos_modificados)

        # Project to work on (target branch of the work; editable: allows
        # typing a branch that doesn't exist yet, NoInsert).
        self.cmb_trabajo = QComboBox()
        self.cmb_trabajo.setEditable(True)
        self.cmb_trabajo.setInsertPolicy(QComboBox.NoInsert)
        self.cmb_trabajo.setPlaceholderText(
            cfg.LAUNCH_DEFECTO["padre"] or t("work branch"))
        add_field(5, t("Project to work on (branch):"), self.cmb_trabajo)
        self.cmb_trabajo.setCurrentText(cfg.LAUNCH_DEFECTO["trabajo"])
        self.cmb_trabajo.currentTextChanged.connect(self.modelos_modificados)

        # Navigator
        self.chk_nav = QCheckBox(
            t("🔍 Automatic Navigator (finds context before each task)"))
        self.chk_nav.setChecked(cfg.NAVEGADOR_DEFECTO)
        g.addWidget(self.chk_nav, 6, 0, 1, 2)

        add_field(7, t("Model (navigator):"),
                  SelectorModelo(proveedores=PROVEEDORES_CATALOGO))
        self.cmb_nav = g.itemAtPosition(7, 1).widget()
        self.cmb_nav.currentTextChanged.connect(self.modelos_modificados)

        b_modelos = _BtnGhost(t("↻ Refresh models"))
        b_modelos.clicked.connect(self.refrescar_modelos)
        g.addWidget(b_modelos, 8, 0, 1, 2)

        self.lbl_net = _LabelStatus("", "info")
        g.addWidget(self.lbl_net, 9, 0, 1, 2)

        self.lbl_modelos = _LabelMuted("")
        g.addWidget(self.lbl_modelos, 10, 0, 1, 2)

        self.chk_dual = QCheckBox(t(
            "Dual gate: the reviewer requires VERDICT: PASS before commit"))
        self.chk_dual.setChecked(cfg.LAUNCH_DEFECTO["dual"])
        g.addWidget(self.chk_dual, 11, 0, 1, 2)

        self.chk_voz = QCheckBox(t(
            "Voice alerts on block/finish (notify-send/spd-say)"))
        self.chk_voz.setChecked(cfg.LAUNCH_DEFECTO["voz"])
        g.addWidget(self.chk_voz, 12, 0, 1, 2)

        add_field(13, t("Max budget (USD, 0 = no limit):"),
                  self._crear_lineedit(str(cfg.LAUNCH_DEFECTO["costo_max"])))
        self.txt_costo_max = g.itemAtPosition(13, 1).widget()

        add_field(14, t("Estimated cost per task (USD):"),
                  self._crear_lineedit(str(cfg.LAUNCH_DEFECTO["costo_iter"])))
        self.txt_costo_iter = g.itemAtPosition(14, 1).widget()

        self.chk_push = QCheckBox(t("--push at the end"))
        self.chk_push.setChecked(cfg.LAUNCH_DEFECTO["push"])
        g.addWidget(self.chk_push, 15, 0, 1, 2)

        self.chk_revision_manual = QCheckBox(t(
            "Review diff manually before each commit (pauses the loop)"))
        self.chk_revision_manual.setChecked(False)
        g.addWidget(self.chk_revision_manual, 16, 0, 1, 2)

        self.chk_fichas = QCheckBox(t(
            "📄 Generate JSON ficha on each accepted task (uses extra tokens)"))
        self.chk_fichas.setChecked(bool(cfg.LAUNCH_DEFECTO["fichas"]))
        self.chk_fichas.setToolTip(t(
            "Runs a separate agent call after the task is accepted. The ficha "
            "is saved in .dedalo/fichas/ and never blocks the commit."))
        g.addWidget(self.chk_fichas, 17, 0, 1, 2)

        v.addWidget(grupo)

        # ===== CONTROL BUTTONS =====
        h_ctrl = QHBoxLayout()
        h_ctrl.setSpacing(8)
        self.b_iniciar = _BtnPrimary(t("▶ Start loop"))
        self.b_iniciar.clicked.connect(self.iniciar)
        self.b_detener = _BtnDanger(t("■ Stop"))
        self.b_detener.clicked.connect(self.detener)
        self.b_detener.setEnabled(False)
        self.b_gate = _BtnGhost(t("Run gate"))
        self.b_gate.clicked.connect(self.gate)
        h_ctrl.addWidget(self.b_iniciar)
        h_ctrl.addWidget(self.b_detener)
        h_ctrl.addWidget(self.b_gate)
        h_ctrl.addStretch()
        v.addLayout(h_ctrl)

        # Diff review panel (hidden by default)
        self.panel_revision = PanelRevision()
        self.panel_revision.setVisible(False)
        v.addWidget(self.panel_revision)

    def _crear_lineedit(self, texto, placeholder=""):
        le = QLineEdit(texto)
        le.setPlaceholderText(placeholder)
        _fuente_ui(le)
        return le

    def actualizar_ramas(self, ruta):
        """Fills the 'Padre' and 'Proyecto a trabajar' combos with the repo's
        real branches (git).

        Keeps the current selection; also allows typing a branch that doesn't
        exist yet (NoInsert). On any git failure it leaves the combos as they
        were.
        """
        if not ruta:
            return
        for cmb in (self.cmb_padre, self.cmb_trabajo):
            actual = cmb.currentText()
            ramas = []
            try:
                out = subprocess.run(
                    ["git", "-C", ruta, "for-each-ref",
                     "--format=%(refname:short)", "refs/heads"],
                    capture_output=True, text=True, timeout=6)
                if out.returncode == 0:
                    ramas = [r for r in out.stdout.splitlines() if r.strip()]
            except (OSError, subprocess.SubprocessError):
                ramas = []
            cmb.blockSignals(True)
            cmb.clear()
            cmb.addItems(ramas)
            if actual:
                cmb.setCurrentText(actual)
            cmb.blockSignals(False)

    # ---------- API for the window ----------

    def config(self):
        return {
            "hasta": self.txt_hasta.text().strip(),
            "padre": self.cmb_padre.currentText().strip(),
            "trabajo": self.cmb_trabajo.currentText().strip(),
            "push": self.chk_push.isChecked(),
            "iteraciones": int(_numero(self.txt_iter.text(),
                                        cfg.LAUNCH_DEFECTO["iteraciones"],
                                        int, minimo=1)),
            "agente_cli": self.cmb_agente_cli.currentData() or "auto",
            "agente": self.cmb_agente.currentText(),
            "revisor_cli": self.cmb_revisor_cli.currentData() or "auto",
            "revisor": self.cmb_revisor.currentText(),
            "dual": self.chk_dual.isChecked(),
            "voz": self.chk_voz.isChecked(),
            "revision_manual": self.chk_revision_manual.isChecked(),
            "fichas": self.chk_fichas.isChecked(),
            "costo_max": _numero(self.txt_costo_max.text(),
                                 cfg.LAUNCH_DEFECTO["costo_max"], float),
            "costo_iter": _numero(self.txt_costo_iter.text(),
                                  cfg.LAUNCH_DEFECTO["costo_iter"], float),
            "nav": self.chk_nav.isChecked(),
            "nav_modelo": self.cmb_nav.currentText() if "/" in self.cmb_nav.currentText() else "",
        }

    def aplicar_config(self, conf):
        """Fills the widgets with the project's saved configuration.

        Blocks signals so it doesn't trigger saves during loading.
        """
        c = dict(cfg.LAUNCH_DEFECTO)
        c.update(conf or {})
        previo = self.signalsBlocked()
        self.blockSignals(True)
        self.txt_hasta.setText(c.get("hasta") or "")
        self.txt_iter.setText(str(c["iteraciones"]))
        self.cmb_padre.setCurrentText(c.get("padre") or "")
        self.cmb_trabajo.setCurrentText(c.get("trabajo") or "")
        self.cmb_agente_cli.setCurrentText(
            c.get("agente_cli") or cfg.AGENTE_DEFECTO)
        self.cmb_agente.setCurrentText(c.get("agente") or "")
        self.cmb_revisor_cli.setCurrentText(
            c.get("revisor_cli") or cfg.AGENTE_DEFECTO)
        self.cmb_revisor.setCurrentText(c.get("revisor") or "")
        self.cmb_nav.setCurrentText(c.get("nav_modelo") or "")
        self.chk_nav.setChecked(bool(c.get("nav")))
        self.chk_dual.setChecked(bool(c.get("dual")))
        self.chk_voz.setChecked(bool(c.get("voz")))
        self.chk_push.setChecked(bool(c.get("push")))
        self.chk_revision_manual.setChecked(bool(c.get("revision_manual")))
        self.chk_fichas.setChecked(bool(c.get("fichas")))
        self.txt_costo_max.setText(
            str(c.get("costo_max", cfg.LAUNCH_DEFECTO["costo_max"])))
        self.txt_costo_iter.setText(
            str(c.get("costo_iter", cfg.LAUNCH_DEFECTO["costo_iter"])))
        self.blockSignals(previo)

    def nota_net(self, ok):
        if ok is None:
            self.lbl_net.setText(t("Internet: ?"))
            self.lbl_net.setProperty("status", "info")
        elif ok:
            self.lbl_net.setText(t("🟢 Internet: OK"))
            self.lbl_net.setProperty("status", "success")
        else:
            self.lbl_net.setText(t(
                "🔴 Internet: NO CONNECTION — AI models won't respond"))
            self.lbl_net.setProperty("status", "error")
        self.lbl_net.style().unpolish(self.lbl_net)
        self.lbl_net.style().polish(self.lbl_net)

    def info_modelos(self, nmodelos, nprov):
        self.lbl_modelos.setText(
            f"{nmodelos} modelos · {nprov} proveedores de opencode cargados")
        # Auto-hide after 3 seconds
        QTimer.singleShot(3000, lambda: self.lbl_modelos.clear())

    def aplicar_modelos(self, seleccion):
        self.cmb_agente.setCurrentText(seleccion.get("tarea") or "")
        self.cmb_revisor.setCurrentText(seleccion.get("revisor") or "")
        if seleccion.get("agente_cli"):
            self.cmb_agente_cli.setCurrentText(seleccion["agente_cli"])
        if seleccion.get("revisor_cli"):
            self.cmb_revisor_cli.setCurrentText(seleccion["revisor_cli"])

    def refrescar_agentes(self):
        """Re-lists the agents (after the background session probe).

        Keeps the current selection if the agent is still usable and, if it
        isn't, leaves the combo on "auto".
        """
        for combo, modelo in ((self.cmb_agente_cli, self.cmb_agente),
                              (self.cmb_revisor_cli, self.cmb_revisor)):
            self._llenar_agente(combo)
            _sincronizar_modelo(modelo, combo)

    def modelos_seleccion(self):
        return {
            "tarea": self.cmb_agente.currentText(),
            "revisor": self.cmb_revisor.currentText(),
            "agente_cli": self.cmb_agente_cli.currentData() or "auto",
            "revisor_cli": self.cmb_revisor_cli.currentData() or "auto",
        }

    def navegador_config(self):
        return {
            "activo": self.chk_nav.isChecked(),
            "modelo": self.cmb_nav.currentText() if "/" in self.cmb_nav.currentText() else "",
        }

    def aplicar_navegador(self, modelo: str):
        self.cmb_nav.setCurrentText(modelo)

    def agregar_catalogo(self, etiquetas):
        self.cmb_agente.addItems(etiquetas)
        self.cmb_revisor.addItems(etiquetas)
        self.cmb_nav.addItems(etiquetas)

    def establecer_running(self, corriendo):
        self.b_iniciar.setEnabled(not corriendo)
        self.b_detener.setEnabled(corriendo)

    def revision_manual_activa(self):
        return self.chk_revision_manual.isChecked()


class PanelGit(QWidget):
    """Branch, git status, recent commits and visual rollback.

    The git commands run on a background thread (Trabajo).
    """

    revertir_commit = Signal(str)  # sha
    limpiar_git = Signal()  # request: ensure .gitignore + stop tracking framework

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ruta = None
        self._worker = None

        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        h = QHBoxLayout()
        h.setSpacing(8)
        self.lbl_rama = QLabel("")
        _fuente_ui(self.lbl_rama)
        self.lbl_rama.setStyleSheet("font-weight: 500;")
        b_limpiar = _BtnGhost(t("🧹 Framework out of git"))
        b_limpiar.clicked.connect(self.limpiar_git.emit)
        b_limpiar.setToolTip(t(
            "Adds Dédalo's block to the project's .gitignore and stops "
            "tracking the framework files (they stay on disk)"))
        b_ref = _BtnGhost(t("Refresh"))
        b_ref.clicked.connect(lambda: self.cargar())
        h.addWidget(self.lbl_rama)
        h.addStretch()
        h.addWidget(b_limpiar)
        h.addWidget(b_ref)
        v.addLayout(h)

        # TreeWidget for commits with a Revert button
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(
            [t("SHA"), t("Message"), t("Author"), t("Date"), t("Action")])
        self.tree.setColumnWidth(0, 80)
        self.tree.setColumnWidth(1, 350)
        self.tree.setColumnWidth(2, 120)
        self.tree.setColumnWidth(3, 130)
        self.tree.setColumnWidth(4, 80)
        _fuente_monospace(self.tree)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionBehavior(QTreeWidget.SelectRows)
        v.addWidget(self.tree, 1)

    def _consulta_git(self):
        ruta = self._ruta
        if not ruta:
            return None

        def run(cmd):
            try:
                out = subprocess.run(cmd, cwd=ruta, capture_output=True,
                                     text=True, timeout=cfg.TIMEOUT_GIT)
                return out.stdout.strip()
            except Exception:
                return ""

        rama = run(["git", "branch", "--show-current"])
        status = run(["git", "status", "--short"])
        # All commits in the repo (last 30), from any branch, so that
        # the "revert: ..." ones created by the ↩ Revert button show up too.
        log = run([
            "git", "log", "--oneline", "--all", "-30",
            "--format=%H|%s|%an|%ad", "--date=short",
        ])

        return (rama, status, log)

    def _git_listo(self, datos):
        if not datos:
            self.tree.clear()
            self.lbl_rama.setText("")
            return
        rama, status, log = datos
        self.lbl_rama.setText(
            t("Branch: {rama}", rama=rama) if rama else t("Branch: —"))

        # Clear the tree
        self.tree.clear()

        # Parse the log and create items with a revert button
        if log:
            for linea in log.splitlines():
                if not linea.strip():
                    continue
                parts = linea.split("|", 3)
                if len(parts) < 4:
                    continue
                sha, msg, autor, fecha = parts
                item = QTreeWidgetItem([sha[:8], msg, autor, fecha, ""])
                item.setData(0, Qt.UserRole, sha)  # full SHA in role
                self.tree.addTopLevelItem(item)

                # Revert button (compact, follows the active theme)
                btn = _BtnSmallGhost(t("↩ Revert"))
                btn.setProperty("sha", sha)
                btn.clicked.connect(lambda _, s=sha: self.revertir_commit.emit(s))
                btn.setToolTip(t("Undoes the change (creates a new commit)"))
                self.tree.setItemWidget(item, 4, btn)

        # Status in the tooltip of the first item or the label
        if status:
            self.tree.setToolTip(f"Status:\n{status}")

    def cargar(self, ruta=None):
        if ruta is not None:
            self._ruta = ruta
        if not self._ruta:
            self.tree.clear()
            self.lbl_rama.setText("")
            return
        if self._worker and self._worker.isRunning():
            return
        w = Trabajo(self._consulta_git)
        w.conectar(self._git_listo)
        w.liberar(self, "_worker")
        self._worker = w
        w.start()


class PanelSeguridad(QWidget):
    """Thermal protection and push notifications."""

    guardar_ajustes = Signal(dict)

    def __init__(self, seguridad, webhooks_config, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        # Tabs: Temperature / Notifications
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)

        # --- Temperature tab ---
        tab_temp = QWidget()
        vt = QVBoxLayout(tab_temp)
        vt.setSpacing(12)
        vt.setContentsMargins(0, 0, 0, 0)

        grupo = QGroupBox(t("Temperature and protection"))
        g = QGridLayout(grupo)
        g.setSpacing(8)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        g.setContentsMargins(12, 12, 12, 12)

        self.chk_activo = QCheckBox(t(
            "Check the temperature and shut down the app if it overheats"))
        self.chk_activo.setChecked(bool(seguridad.get("activo")))
        g.addWidget(self.chk_activo, 0, 0, 1, 2)

        self.chk_ver = QCheckBox(t(
            "Show the temperature in this panel (updates every second)"))
        self.chk_ver.setChecked(bool(seguridad.get("ver")))
        g.addWidget(self.chk_ver, 1, 0, 1, 2)

        def add_num_field(row, label_text, valor, minimo=1):
            lbl = QLabel(label_text)
            _fuente_ui(lbl)
            g.addWidget(lbl, row, 0)
            le = QLineEdit(str(valor))
            _fuente_ui(le)
            g.addWidget(le, row, 1)
            return le

        self.txt_umbral = add_num_field(2, t("Danger threshold (°C):"),
                                        seguridad.get("umbral", 85))
        self.txt_segundos = add_num_field(
            3, t("Warning seconds before shutdown:"),
            seguridad.get("segundos", 5))

        b_guardar = _BtnPrimary(t("Save settings"))
        b_guardar.clicked.connect(self._emitir_ajustes)
        g.addWidget(b_guardar, 4, 0, 1, 2)

        vt.addWidget(grupo)

        self.lbl_titulo_temp = _LabelMuted(t("Current temperature:"))
        self.lbl_temp = QLabel("—")
        self.lbl_estado_temp = _LabelMuted("")

        vt.addWidget(self.lbl_titulo_temp)
        vt.addWidget(self.lbl_temp)
        vt.addWidget(self.lbl_estado_temp)
        vt.addStretch()

        self.tabs.addTab(tab_temp, t("🌡 Temperature"))

        # --- Notifications tab (Webhooks) ---
        self.panel_webhooks = PanelWebhooks(webhooks_config)
        self.panel_webhooks.guardado.connect(self._webhooks_guardado)
        self.tabs.addTab(self.panel_webhooks, t("🔔 Notifications"))

    def _webhooks_guardado(self, config: dict):
        """Re-emits the full signal with security + webhooks"""
        self.guardar_ajustes.emit({
            "seguridad": self.ajustes(),
            "webhooks": config,
        })

    def ajustes(self):
        return {
            "activo": self.chk_activo.isChecked(),
            "ver": self.chk_ver.isChecked(),
            "umbral": int(_numero(self.txt_umbral.text(), 85, int, 1)),
            "segundos": int(_numero(self.txt_segundos.text(), 5, int, 1)),
        }

    def aplicar_config(self, seguridad, webhooks=None):
        """Fills the controls with the active project's configuration."""
        seguridad = seguridad or {}
        self.chk_activo.setChecked(bool(seguridad.get("activo")))
        self.chk_ver.setChecked(bool(seguridad.get("ver")))
        self.txt_umbral.setText(str(seguridad.get("umbral", 85)))
        self.txt_segundos.setText(str(seguridad.get("segundos", 5)))
        self.set_visibilidad_temp(bool(seguridad.get("ver")))
        if webhooks is not None:
            self.panel_webhooks.aplicar_config(webhooks)

    def _emitir_ajustes(self):
        # Only security; webhooks are emitted separately
        self.guardar_ajustes.emit({
            "seguridad": self.ajustes(),
            "webhooks": self.panel_webhooks.obtener_config(),
        })

    def set_visibilidad_temp(self, ver):
        self.lbl_titulo_temp.setVisible(ver)
        self.lbl_temp.setVisible(ver)
        self.lbl_estado_temp.setVisible(ver)

    def actualizar_temp(self, temp, umbral):
        if temp is None:
            self.lbl_temp.setText(t("unknown"))
            self.lbl_temp.setStyleSheet("font-size: 28px; font-weight: 600; color: palette(text);")
            self.lbl_estado_temp.setText(
                t("No temperature sensor is available."))
            return
        if temp >= umbral:
            color = "#ef4444"
            estado = t("⚠ OVERHEATING: the shutdown warning will open.")
        elif temp >= umbral - 10:
            color = "#f59e0b"
            estado = t("High temperature: keep an eye on it.")
        else:
            color = "#22c55e"
            estado = t("Normal temperature.")
        self.lbl_temp.setStyleSheet(f"font-size: 28px; font-weight: 600; color: {color};")
        self.lbl_temp.setText(f"{temp:.1f} °C")
        self.lbl_estado_temp.setText(estado)


class PanelLogs(QWidget):
    """Dedicated logs tab: Loop + Gate in a vertical splitter with headers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        # Main vertical splitter
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStyleSheet("""
            QSplitter::handle { background: transparent; }
            QSplitter::handle:hover { background: palette(highlight); }
        """)

        # ---- LOOP (top) ----
        self.loop_container = self._crear_panel_log(
            t("Loop output (live progress)"),
            "loop"
        )
        self.panel_loop = self.loop_container.log_widget
        self.splitter.addWidget(self.loop_container)

        # ---- GATE (bottom) ----
        self.gate_container = self._crear_panel_log(
            t("Gate output"),
            "gate"
        )
        self.panel_gate = self.gate_container.log_widget
        self.gate_container.setMaximumHeight(300)
        self.splitter.addWidget(self.gate_container)

        # Initial 70/30 proportion
        self.splitter.setSizes([500, 200])
        v.addWidget(self.splitter, 1)

    def _crear_panel_log(self, titulo, tipo):
        """Creates a container with header + log widget."""
        container = QWidget()
        container.log_widget = PanelTarea()
        _fuente_monospace(container.log_widget)
        container.log_widget.setLineWrapMode(QPlainTextEdit.NoWrap)

        layout = QVBoxLayout(container)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header (always visible, only the log_widget collapses)
        header = QHBoxLayout()
        header.setSpacing(8)
        header.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(titulo)
        _fuente_ui(lbl)
        lbl.setStyleSheet("font-weight: 600; font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase; color: palette(mid);")
        header.addWidget(lbl)
        header.addStretch()

        b_limpiar = _BtnGhost(t("🗑 Clear"))
        b_limpiar.setToolTip(t("Clear output"))
        b_limpiar.clicked.connect(lambda: container.log_widget.clear())
        header.addWidget(b_limpiar)

        b_copiar = _BtnGhost(t("📋 Copy"))
        b_copiar.setToolTip(t("Copy everything to clipboard"))
        b_copiar.clicked.connect(lambda: (container.log_widget.selectAll(), container.log_widget.copy()))
        header.addWidget(b_copiar)

        b_maximizar = _BtnGhost("⛶")
        b_maximizar.setToolTip(t("Collapse/expand panel"))
        b_maximizar.setFixedWidth(28)
        b_maximizar.clicked.connect(
            lambda checked=False, _tipo=tipo: self._toggle_maximizar(_tipo))
        header.addWidget(b_maximizar)

        layout.addLayout(header)
        layout.addWidget(container.log_widget, 1)

        container.log_widget = container.log_widget
        container.tipo = tipo
        return container

    def _toggle_maximizar(self, tipo):
        """Collapses/expands only the log_widget, the header stays visible."""
        idx = 0 if tipo == "loop" else 1
        w = self.splitter.widget(idx)
        log = w.log_widget
        if log.isVisible():
            self._tam_prev = list(self.splitter.sizes())
            log.hide()
            return
        log.show()
        prev = getattr(self, "_tam_prev", None)
        if prev and sum(prev) > 0:
            self.splitter.setSizes(prev)
        else:
            total = sum(self.splitter.sizes())
            if idx == 0:
                self.splitter.setSizes([int(total * 0.7), int(total * 0.3)])
            else:
                self.splitter.setSizes([int(total * 0.3), int(total * 0.7)])
