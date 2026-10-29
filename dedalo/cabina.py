"""Run cockpit: what someone watching Dédalo sees at a glance.

The cockpit sits at the top of the Run section and never scrolls away:

- a status badge (running / waiting for your review / finished / aborted)
  with the run clock and the start/stop buttons,
- the plan progress (overall bar plus one segment per `## FASE` heading),
- the current task with its iteration and attempt,
- the phase pipeline (Plan → Agent → Gate → Reviewer → Commit): the active
  phase pulses and ticks its clock, a failed one turns red, and clicking a
  phase shows what it produced,
- this run's timeline (one chip per task) and an estimate of what is left.

Everything is fed by `vista_loop()`, which merges the engine's
`estado_loop.json` (detail) with `loops_estado` (is it really running?), so
loops launched by the GUI and by an MCP agent look the same.
"""

import os
import re
import time

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from . import configuracion as cfg
from . import estado_loop, loops_estado
from .i18n import t

FASES = estado_loop.FASES
# Display names (the keys stay as the engine writes them).
_NOMBRE_FASE = {"Plan": "Plan", "Agente": "Agent", "Gate": "Gate",
                "Revisor": "Reviewer", "Commit": "Commit"}
_AYUDA_FASE = {
    "Plan": "Picks the next pending task of plan.md and gathers context.",
    "Agente": "The AI agent works on the task in its own branch.",
    "Gate": "The project's checks (tests, lint, criterio) must pass.",
    "Revisor": "A second model reviews the diff before it is accepted.",
    "Commit": "The accepted work is committed and merged into the run branch.",
}


def nombre_fase(fase):
    return t(_NOMBRE_FASE.get(fase, fase))


def fmt_dur(segundos):
    """1:05 · 12:40 · 1 h 03 min."""
    if segundos is None:
        return ""
    s = max(0, int(segundos))
    if s >= 3600:
        return t("{h} h {m:02d} min", h=s // 3600, m=(s % 3600) // 60)
    return f"{s // 60}:{s % 60:02d}"


# ─── Data ─────────────────────────────────────────────────────────────

_TAREA = re.compile(r"^\s*-\s*\[( |x|X|B)\]\s+(.*)")


def secciones_plan(texto):
    """[(title, done, total, blocked)] per `## ` heading that has tasks.

    Tasks before the first heading go under "Plan". Headings without tasks
    (conventions, notes) are skipped."""
    secciones = []
    actual = ["Plan", 0, 0, 0]
    for linea in texto.splitlines():
        if linea.startswith("## "):
            if actual[2]:
                secciones.append(tuple(actual))
            actual = [linea[3:].strip(), 0, 0, 0]
            continue
        m = _TAREA.match(linea)
        if not m:
            continue
        actual[2] += 1
        if m.group(1) in "xX":
            actual[1] += 1
        elif m.group(1) == "B":
            actual[3] += 1
    if actual[2]:
        secciones.append(tuple(actual))
    return secciones


_CACHE_PLAN = {}


def _plan(proyecto):
    from . import rutas
    ruta = rutas.proyecto_archivo(proyecto, "plan.md")
    try:
        mtime = os.path.getmtime(ruta)
    except OSError:
        return []
    clave = (ruta, mtime)
    if clave not in _CACHE_PLAN:
        try:
            with open(ruta, encoding="utf-8", errors="replace") as f:
                _CACHE_PLAN.clear()
                _CACHE_PLAN[clave] = secciones_plan(f.read())
        except OSError:
            return []
    return _CACHE_PLAN[clave]


def _pid_vivo(pid):
    try:
        return bool(pid) and loops_estado.vivo(int(pid))
    except (TypeError, ValueError):
        return False


def vista_loop(nombre, proyecto, local_corriendo=False):
    """Everything the cockpit paints, as plain data.

    `local_corriendo`: the GUI's own QProcess is running. Otherwise the shared
    `loops_estado` registry decides; the JSON only adds detail. A JSON that
    still says "running" for a dead pid (crash, SIGKILL) is shown as stopped.
    """
    e = estado_loop.leer(proyecto) or {}
    externo = loops_estado.estado(nombre) if nombre else {"corriendo": False}
    corriendo = bool(local_corriendo or externo.get("corriendo"))
    estado = e.get("estado", "")
    if estado in ("arrancando", "corriendo"):
        if not corriendo and not _pid_vivo(e.get("pid")):
            estado = "caido"
    elif corriendo and estado not in ("arrancando", "corriendo"):
        # The registry says running but this run has not written yet.
        e = {}
        estado = "arrancando"
    if not corriendo and estado in ("arrancando", "corriendo"):
        corriendo = True
    secciones = _plan(proyecto)
    hechas = sum(s[1] for s in secciones)
    total = sum(s[2] for s in secciones)
    bloqueadas = sum(s[3] for s in secciones)
    pendientes = total - hechas - bloqueadas
    historial = e.get("historial") or []
    durs = [h["dur"] for h in historial if h.get("resultado") == "hecha"]
    restantes = 0
    eta = None
    if corriendo:
        quedan_iter = max(0, int(e.get("max_iter") or 0)
                          - int(e.get("iteracion") or 0))
        en_curso = 1 if e.get("fase") else 0
        restantes = min(max(0, pendientes - en_curso), quedan_iter) + en_curso
        if durs and restantes:
            media = sum(durs) / len(durs)
            transcurrido = (time.time() - e["tarea_inicio"]
                            if en_curso and e.get("tarea_inicio") else 0)
            eta = max(0.0, media * restantes - min(transcurrido, media))
    return {
        "corriendo": corriendo,
        "estado": estado or ("arrancando" if corriendo else ""),
        "motivo": e.get("motivo", ""),
        "e": e,
        "secciones": secciones,
        "hechas": hechas, "total": total, "bloqueadas": bloqueadas,
        "pendientes": pendientes,
        "restantes": restantes,
        "eta": eta,
        "media": (sum(durs) / len(durs)) if durs else None,
    }


# ─── Widgets ──────────────────────────────────────────────────────────

_TEMA = {"nombre": cfg.TEMA_DEFECTO}


def _colores():
    from .temas import colores_tema
    return colores_tema(_TEMA["nombre"])


class _Pintable(QWidget):
    """Base for painted widgets: theme colors + a pulse clock (MOTION)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._c = _colores()
        self._pulso = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    def set_tema(self, nombre=None):
        if nombre:
            _TEMA["nombre"] = nombre
        self._c = _colores()
        self.update()

    def _animar(self, activo):
        if activo and cfg.MOTION:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            self._pulso = 0.0

    def _tick(self):
        self._pulso = (self._pulso + 0.035) % 1.0
        self.update()


class PipelineLoop(_Pintable):
    """Phase pipeline. Click a node to see what that phase produced."""

    fase_pulsada = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pipeline_loop")
        self._estados = {f: "idle" for f in FASES}
        self._sub = {f: "" for f in FASES}
        self._tips = {f: "" for f in FASES}
        self._rects = {}
        self.setMinimumHeight(66)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

    # Compatibility API (phase name only, earlier ones green).
    def setFase(self, fase):
        estados, alcanzada = {}, False
        for f in FASES:
            if f == fase:
                estados[f], alcanzada = "active", True
            else:
                estados[f] = "idle" if alcanzada or not fase else "ok"
        self.set_estados(estados if fase in FASES else {})

    def setPendiente(self):
        self.set_estados({})

    def setOk(self):
        self.set_estados({f: "ok" for f in FASES})

    def setFail(self):
        self.set_estados({f: "fail" for f in FASES})

    def set_estados(self, estados, subtextos=None, tips=None):
        """estados: phase → idle|active|wait|ok|fail."""
        self._estados = {f: estados.get(f, "idle") for f in FASES}
        self._sub = {f: (subtextos or {}).get(f, "") for f in FASES}
        self._tips = {f: (tips or {}).get(f, "") for f in FASES}
        self._animar(any(v in ("active", "wait") for v in self._estados.values()))
        self.update()

    def estados(self):
        return dict(self._estados)

    def _fase_en(self, pos):
        for f, r in self._rects.items():
            if r.adjusted(-4, -4, 4, 18).contains(QPointF(pos)):
                return f
        return None

    def mouseMoveEvent(self, ev):
        f = self._fase_en(ev.position())
        self.setCursor(Qt.PointingHandCursor if f else Qt.ArrowCursor)
        if f:
            tip = f"<b>{nombre_fase(f)}</b><br>{t(_AYUDA_FASE[f])}"
            if self._tips.get(f):
                tip += f"<br><br>{self._tips[f]}"
            tip += "<br><i>" + t("Click to see its output") + "</i>"
            QToolTip.showText(ev.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, ev):
        f = self._fase_en(ev.position())
        if f:
            self.fase_pulsada.emit(f)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self._c
        w = self.width()
        n = len(FASES)
        margen, sep = 10.0, 26.0
        pill_w = max(64.0, min(132.0, (w - 2 * margen - (n - 1) * sep) / n))
        pill_h = 32.0
        cy = 22.0
        total_w = n * pill_w + (n - 1) * sep
        x0 = max(margen, (w - total_w) / 2.0)

        def centro(i):
            return x0 + i * (pill_w + sep) + pill_w / 2.0

        colores = {"ok": c["success"], "fail": c["error"],
                   "active": c["accent"], "wait": c["warning"]}
        for i in range(1, n):
            a = centro(i - 1) + pill_w / 2.0 + 3
            b = centro(i) - pill_w / 2.0 - 3
            previo = self._estados[FASES[i - 1]]
            color = colores.get(previo, c["border"]) if previo != "fail" \
                else c["border"]
            p.setPen(QPen(color, 2.0))
            p.drawLine(QPointF(a, cy), QPointF(b, cy))
            if previo == "active" and cfg.MOTION:
                # A dot travelling along the connector: work is flowing.
                x = a + (b - a) * self._pulso
                p.setPen(Qt.NoPen)
                p.setBrush(c["accent"])
                p.drawEllipse(QPointF(x, cy), 3.0, 3.0)

        fuente = QFont(self.font())
        sub_fuente = QFont(self.font())
        sub_fuente.setPointSizeF(max(7.0, self.font().pointSizeF() - 1.5))
        self._rects = {}
        for i, f in enumerate(FASES):
            estado = self._estados[f]
            cx = centro(i)
            rect = QRectF(cx - pill_w / 2.0, cy - pill_h / 2.0, pill_w, pill_h)
            self._rects[f] = rect
            if estado in ("active", "wait") and cfg.MOTION:
                g = 10.0 * self._pulso
                halo = QColor(colores[estado])
                halo.setAlphaF(max(0.0, 0.35 * (1.0 - self._pulso)))
                p.setPen(Qt.NoPen)
                p.setBrush(halo)
                p.drawRoundedRect(rect.adjusted(-g, -g, g, g),
                                  pill_h / 2 + g, pill_h / 2 + g)
            if estado in ("active", "wait"):
                p.setPen(QPen(QColor(colores[estado]).lighter(125), 1.5))
                p.setBrush(colores[estado])
                color_tx = c["text_inverse"]
            elif estado in ("ok", "fail"):
                relleno = QColor(colores[estado])
                relleno.setAlphaF(0.16)
                p.setPen(QPen(colores[estado], 1.4))
                p.setBrush(relleno)
                color_tx = colores[estado]
            else:
                p.setPen(QPen(c["border"], 1.0))
                p.setBrush(c["bg_sunken"])
                color_tx = c["text_tertiary"]
            p.drawRoundedRect(rect, pill_h / 2, pill_h / 2)
            icono = {"ok": "✓ ", "fail": "✗ ", "wait": "⏸ "}.get(estado, "")
            fuente.setBold(estado in ("active", "wait"))
            p.setFont(fuente)
            p.setPen(color_tx)
            p.drawText(rect, Qt.AlignCenter, icono + nombre_fase(f))
            if self._sub.get(f):
                p.setFont(sub_fuente)
                p.setPen(colores.get(estado, c["text_tertiary"])
                         if estado != "idle" else c["text_tertiary"])
                p.drawText(QRectF(rect.left() - sep / 2, rect.bottom() + 2,
                                  rect.width() + sep, 16),
                           Qt.AlignHCenter | Qt.AlignTop, self._sub[f])


class BarraPlan(_Pintable):
    """Plan progress: one segment per `## FASE`, filled by done tasks.

    The fill glides to its new value (MOTION) so a finished task is seen
    moving the bar; hovering a segment names its section."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._secciones = []
        self._activa = -1
        self._mostrado = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(900)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._avance)
        self._segs = []
        self.setMinimumHeight(22)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

    def _avance(self, v):
        self._mostrado = float(v)
        self.update()

    def set_datos(self, secciones, activa=-1, corriendo=False):
        total = sum(s[2] for s in secciones) or 1
        hechas = sum(s[1] for s in secciones)
        objetivo = hechas / total
        cambio = abs(objetivo - self._mostrado) > 1e-6
        self._secciones = secciones
        self._activa = activa
        if cambio:
            if cfg.MOTION and self.isVisible() and self._mostrado:
                self._anim.stop()
                self._anim.setStartValue(self._mostrado)
                self._anim.setEndValue(objetivo)
                self._anim.start()
            else:
                self._mostrado = objetivo
        self._animar(corriendo and activa >= 0)
        self.update()

    def mouseMoveEvent(self, ev):
        x = ev.position().x()
        for (a, b), s in zip(self._segs, self._secciones, strict=False):
            if a <= x <= b:
                titulo, hechas, total, bloq = s
                txt = t("{titulo}: {hechas}/{total} done", titulo=titulo,
                        hechas=hechas, total=total)
                if bloq:
                    txt += " · " + t("{n} blocked", n=bloq)
                QToolTip.showText(ev.globalPosition().toPoint(), txt, self)
                return
        QToolTip.hideText()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self._c
        w, h = float(self.width()), 12.0
        y = (self.height() - h) / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(c["bg_sunken"])
        p.drawRoundedRect(QRectF(0, y, w, h), h / 2, h / 2)
        total = sum(s[2] for s in self._secciones)
        if not total:
            return
        # Fill (animated), clipped to the rounded track.
        from PySide6.QtGui import QPainterPath
        pista = QPainterPath()
        pista.addRoundedRect(QRectF(0, y, w, h), h / 2, h / 2)
        p.setClipPath(pista)
        hecho = QColor(c["success"])
        p.setBrush(hecho)
        p.drawRect(QRectF(0, y, w * self._mostrado, h))
        # Blocked tasks: red at the end of each segment's done part.
        x = 0.0
        self._segs = []
        for i, (_tit, hechas, n, bloq) in enumerate(self._secciones):
            ancho = w * n / total
            if bloq:
                p.setBrush(c["error"])
                p.drawRect(QRectF(x + ancho * hechas / n, y,
                                  ancho * bloq / n, h))
            if i == self._activa and cfg.MOTION:
                # Shimmer on the section being worked on.
                brillo = QColor(c["accent"])
                brillo.setAlphaF(0.25 + 0.25 * abs(0.5 - self._pulso) * 2)
                p.setBrush(brillo)
                inicio = x + ancho * (hechas + bloq) / n
                p.drawRect(QRectF(inicio, y, max(0.0, x + ancho - inicio), h))
            self._segs.append((x, x + ancho))
            x += ancho
        p.setClipping(False)
        # Section separators.
        p.setPen(QPen(c["bg_panel"], 2.0))
        for a, _b in self._segs[1:]:
            p.drawLine(QPointF(a, y), QPointF(a, y + h))


class LineaTiempo(_Pintable):
    """This run, one chip per task: ✓ done, ✗ blocked, ● now, ○ ahead."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._chips = []
        self.setMinimumHeight(30)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

    def set_datos(self, historial, actual=None, restantes=0):
        items = [("hecha" if h.get("resultado") == "hecha" else "bloqueada",
                  h) for h in historial]
        if actual:
            items.append(("actual", actual))
        for _ in range(max(0, restantes - (1 if actual else 0))):
            items.append(("pendiente", None))
        self._items = items
        self._animar(actual is not None)
        self.update()

    def mouseMoveEvent(self, ev):
        for rect, (tipo, h) in zip(self._chips, self._items, strict=False):
            if rect.contains(ev.position()):
                if tipo == "pendiente":
                    txt = t("Pending task")
                elif tipo == "actual":
                    txt = t("Now: {tarea}", tarea=h.get("tarea", ""))
                else:
                    txt = (f"#{h.get('iteracion')} · {h.get('tarea', '')}<br>"
                           + (t("Done") if tipo == "hecha" else t("Blocked"))
                           + f" · {fmt_dur(h.get('dur'))} · "
                           + t("{n} attempt(s)", n=h.get("intentos", 1)))
                    if h.get("fallos"):
                        txt += "<br>" + t("Failed at: {f}", f=", ".join(
                            nombre_fase(f) for f in h["fallos"]))
                QToolTip.showText(ev.globalPosition().toPoint(), txt, self)
                return
        QToolTip.hideText()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self._c
        d, sep = 20.0, 6.0
        cy = self.height() / 2.0
        max_chips = max(1, int((self.width() + sep) // (d + sep)))
        items = self._items
        if len(items) > max_chips:
            items = items[-max_chips:]
        x = 0.0
        self._chips = []
        fuente = QFont(self.font())
        fuente.setBold(True)
        fuente.setPointSizeF(max(7.0, self.font().pointSizeF() - 1))
        p.setFont(fuente)
        for tipo, _h in items:
            rect = QRectF(x, cy - d / 2, d, d)
            self._chips.append(rect)
            if tipo == "hecha":
                p.setPen(Qt.NoPen)
                p.setBrush(c["success"])
                p.drawEllipse(rect)
                p.setPen(c["text_inverse"])
                p.drawText(rect, Qt.AlignCenter, "✓")
            elif tipo == "bloqueada":
                p.setPen(Qt.NoPen)
                p.setBrush(c["error"])
                p.drawEllipse(rect)
                p.setPen(c["text_inverse"])
                p.drawText(rect, Qt.AlignCenter, "✗")
            elif tipo == "actual":
                if cfg.MOTION:
                    g = 6.0 * self._pulso
                    halo = QColor(c["accent"])
                    halo.setAlphaF(max(0.0, 0.4 * (1.0 - self._pulso)))
                    p.setPen(Qt.NoPen)
                    p.setBrush(halo)
                    p.drawEllipse(rect.adjusted(-g, -g, g, g))
                p.setPen(Qt.NoPen)
                p.setBrush(c["accent"])
                p.drawEllipse(rect)
            else:
                p.setPen(QPen(c["border"], 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(rect.adjusted(2, 2, -2, -2))
            x += d + sep
        if len(self._items) > len(items):
            # Older chips were cut on the left: say so.
            self._chips = [QRectF()] * (len(self._items) - len(items)) \
                + self._chips


class _Etiqueta(QLabel):
    def __init__(self, texto="", rol="", parent=None):
        super().__init__(texto, parent)
        if rol:
            self.setObjectName(rol)
        self.setTextInteractionFlags(Qt.NoTextInteraction)


class CabinaLoop(QFrame):
    """The fixed header of the Run section (see module docstring)."""

    fase_pulsada = Signal(str)

    def __init__(self, botones=(), parent=None):
        super().__init__(parent)
        self.setObjectName("cabina_loop")
        self._vista = None
        self._fase_detalle = None
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(14, 12, 14, 12)
        raiz.setSpacing(8)

        # Row 1: status + clock + buttons
        fila = QHBoxLayout()
        fila.setSpacing(10)
        self.lbl_estado = _Etiqueta(rol="cabina_estado")
        self.lbl_reloj = _Etiqueta(rol="cabina_tenue")
        fila.addWidget(self.lbl_estado)
        fila.addWidget(self.lbl_reloj)
        fila.addStretch(1)
        for b in botones:
            fila.addWidget(b)
        raiz.addLayout(fila)

        # Row 2: plan progress
        fila_plan = QHBoxLayout()
        fila_plan.setSpacing(10)
        self.lbl_plan = _Etiqueta(rol="cabina_plan")
        self.barra = BarraPlan()
        fila_plan.addWidget(self.lbl_plan)
        fila_plan.addWidget(self.barra, 1)
        raiz.addLayout(fila_plan)
        self.lbl_seccion = _Etiqueta(rol="cabina_tenue")
        raiz.addWidget(self.lbl_seccion)

        # Row 3: current task
        self.lbl_tarea_meta = _Etiqueta(rol="cabina_tenue")
        self.lbl_tarea = _Etiqueta(rol="cabina_tarea")
        self.lbl_tarea.setWordWrap(False)
        self.lbl_tarea.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        raiz.addSpacing(2)
        raiz.addWidget(self.lbl_tarea_meta)
        raiz.addWidget(self.lbl_tarea)

        # Row 4: pipeline (+ output of the clicked phase)
        self.pipeline = PipelineLoop()
        self.pipeline.fase_pulsada.connect(self._mostrar_detalle)
        raiz.addWidget(self.pipeline)
        self.detalle = QPlainTextEdit()
        self.detalle.setObjectName("cabina_detalle")
        self.detalle.setReadOnly(True)
        self.detalle.setMaximumHeight(130)
        self.detalle.setVisible(False)
        raiz.addWidget(self.detalle)

        # Row 5: this run's timeline + estimate
        fila_tl = QHBoxLayout()
        fila_tl.setSpacing(10)
        self.lbl_run = _Etiqueta(t("This run"), rol="cabina_tenue")
        self.linea = LineaTiempo()
        self.lbl_eta = _Etiqueta(rol="cabina_tenue")
        fila_tl.addWidget(self.lbl_run)
        fila_tl.addWidget(self.linea, 1)
        fila_tl.addWidget(self.lbl_eta)
        raiz.addLayout(fila_tl)

        self._estilo()

        # Clocks tick every second even when the log is silent.
        self._reloj = QTimer(self)
        self._reloj.setInterval(1000)
        self._reloj.timeout.connect(self._pintar_relojes)

    def set_tema(self, nombre=None):
        for w in (self.pipeline, self.barra, self.linea):
            w.set_tema(nombre)
        self._estilo()

    def _estilo(self):
        """Theme-driven look: a raised card with a colored status badge."""
        c = _colores()

        def rgba(color, alfa):
            return (f"rgba({color.red()},{color.green()},{color.blue()},"
                    f"{alfa})")

        badge = {
            "marcha": (rgba(c["accent"], 0.18), c["accent"].name()),
            "espera": (rgba(c["warning"], 0.20), c["warning"].name()),
            "ok": (rgba(c["success"], 0.18), c["success"].name()),
            "error": (rgba(c["error"], 0.18), c["error"].name()),
            "parado": (rgba(c["border"], 0.35), c["text_secondary"].name()),
        }
        reglas = [
            f"QFrame#cabina_loop {{ background: {c['bg_panel'].name()};"
            f" border: 1px solid {rgba(c['border'], c['border'].alphaF())};"
            " border-radius: 10px; }",
            "QLabel#cabina_estado { font-weight: 700; padding: 4px 12px;"
            " border-radius: 12px; }",
            f"QLabel#cabina_tenue {{ color: {c['text_tertiary'].name()}; }}",
            f"QLabel#cabina_plan {{ color: {c['text_secondary'].name()};"
            " font-weight: 600; }",
            f"QLabel#cabina_tarea {{ color: {c['text_primary'].name()};"
            " font-size: 15px; font-weight: 600; }",
            f"QPlainTextEdit#cabina_detalle {{ background: {c['bg_sunken'].name(QColor.HexArgb)};"
            f" border: 1px solid {rgba(c['border'], c['border'].alphaF())};"
            " border-radius: 6px; }",
        ]
        for clave, (fondo, texto) in badge.items():
            reglas.append(f'QLabel#cabina_estado[estado="{clave}"] '
                          f"{{ background: {fondo}; color: {texto}; }}")
        self.setStyleSheet("\n".join(reglas))

    # ---- data → widgets ------------------------------------------------

    def actualizar(self, vista):
        self._vista = vista
        e = vista["e"]
        estado = vista["estado"]
        corriendo = vista["corriendo"]

        # Status badge
        if estado == "corriendo" and e.get("esperando_humano"):
            clave, txt = "espera", t("⏸ Waiting for your review")
        elif estado == "corriendo":
            clave, txt = "marcha", t("● Running")
        elif estado == "arrancando":
            clave, txt = "marcha", t("● Starting (baseline gate)…")
        elif estado == "finalizado":
            clave, txt = "ok", t("✓ Finished")
        elif estado == "abortado":
            clave, txt = "error", t("✗ Stopped: {motivo}",
                                    motivo=vista["motivo"] or t("see Logs"))
        elif estado == "caido":
            clave, txt = "error", t("✗ The loop stopped unexpectedly")
        else:
            clave, txt = "parado", t("○ Idle")
        self.lbl_estado.setText(txt)
        self.lbl_estado.setToolTip(txt)
        if self.lbl_estado.property("estado") != clave:
            self.lbl_estado.setProperty("estado", clave)
            self.lbl_estado.style().unpolish(self.lbl_estado)
            self.lbl_estado.style().polish(self.lbl_estado)

        # Plan
        total, hechas = vista["total"], vista["hechas"]
        pct = int(round(100 * hechas / total)) if total else 0
        self.lbl_plan.setText(
            t("Plan {hechas}/{total} · {pct}%", hechas=hechas, total=total,
              pct=pct) if total else t("No tasks in plan.md"))
        activa = -1
        if corriendo and e.get("tarea"):
            # The section of the task being worked on = first one with work left.
            for i, s in enumerate(vista["secciones"]):
                if s[1] + s[3] < s[2]:
                    activa = i
                    break
        self.barra.set_datos(vista["secciones"], activa, corriendo)
        if activa >= 0:
            tit, h, n, _b = vista["secciones"][activa]
            self.lbl_seccion.setText(t("Now in {titulo} · {h}/{n}",
                                       titulo=tit, h=h, n=n))
        else:
            partes = []
            if vista["pendientes"]:
                partes.append(t("{n} pending", n=vista["pendientes"]))
            if vista["bloqueadas"]:
                partes.append(t("{n} blocked", n=vista["bloqueadas"]))
            self.lbl_seccion.setText(" · ".join(partes))
        self.lbl_seccion.setVisible(bool(self.lbl_seccion.text()))

        # Current task
        if corriendo and e.get("tarea"):
            meta = t("Task {i} of {n}", i=e.get("iteracion", 0),
                     n=e.get("max_iter", 0))
            if e.get("intento"):
                meta += " · " + t("attempt {k}/{m}", k=e["intento"],
                                   m=e.get("max_reintentos", 0))
            if e.get("agente"):
                meta += f" · {e['agente']}"
            self.lbl_tarea_meta.setText(meta)
            self._set_tarea(e["tarea"])
        elif corriendo:
            self.lbl_tarea_meta.setText(t("Preparing the run"))
            self._set_tarea(t("Checking internet and the baseline gate…"))
        else:
            hist = e.get("historial") or []
            if hist:
                n_ok = sum(1 for h in hist if h["resultado"] == "hecha")
                self.lbl_tarea_meta.setText(t("Last run"))
                self._set_tarea(t("{ok} done, {bloq} blocked in {dur}",
                                  ok=n_ok, bloq=len(hist) - n_ok,
                                  dur=fmt_dur(sum(h["dur"] for h in hist))))
            else:
                self.lbl_tarea_meta.setText(t("Nothing running"))
                self._set_tarea(t("Press ▶ Start loop to work through the "
                                  "pending tasks of plan.md"))

        # Pipeline
        self._pintar_pipeline()

        # Timeline + ETA
        actual = ({"tarea": e.get("tarea", "")}
                  if corriendo and e.get("fase") else None)
        self.linea.set_datos(e.get("historial") or [], actual,
                             vista["restantes"] if corriendo else 0)
        self.lbl_run.setVisible(bool(e.get("historial") or actual))
        self.linea.setVisible(bool(e.get("historial") or actual))
        if corriendo and vista["eta"] is not None:
            self.lbl_eta.setText(t("≈ {eta} left · {media} per task",
                                   eta=fmt_dur(vista["eta"]),
                                   media=fmt_dur(vista["media"])))
        elif corriendo and actual:
            self.lbl_eta.setText(t("estimating time left…"))
        else:
            self.lbl_eta.setText("")
        if corriendo:
            self._reloj.start()
        else:
            self._reloj.stop()
        self._pintar_relojes()
        if self._fase_detalle:
            self._mostrar_detalle(self._fase_detalle, refrescar=True)

    def _set_tarea(self, texto):
        self.lbl_tarea.setToolTip(texto)
        fm = QFontMetrics(self.lbl_tarea.font())
        ancho = max(80, self.lbl_tarea.width() or self.width() - 40)
        self.lbl_tarea.setText(fm.elidedText(texto, Qt.ElideRight, ancho))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.lbl_tarea.toolTip():
            self._set_tarea(self.lbl_tarea.toolTip())

    def _pintar_pipeline(self):
        v = self._vista
        if not v:
            return
        e = v["e"]
        if not v["corriendo"] or not e.get("fase"):
            fases = {}
            if v["estado"] in ("finalizado", "abortado", "caido"):
                fases = dict(e.get("fases") or {})
                if fases:
                    fases["Plan"] = "ok"  # a task was picked to get there
            self.pipeline.set_estados(fases, {}, self._tips(e))
            return
        estados, sub = {}, {}
        actual = e["fase"]
        pasada = True
        for f in FASES:
            if f == actual:
                estados[f] = "wait" if e.get("esperando_humano") else "active"
                inicio = e.get("fase_inicio")
                sub[f] = (t("your turn") if e.get("esperando_humano")
                          else fmt_dur(time.time() - inicio) if inicio else "")
                pasada = False
            elif pasada:
                r = (e.get("fases") or {}).get(f)
                estados[f] = "fail" if r == "fail" else "ok"
            else:
                estados[f] = "idle"
        # A failure earlier in this task (previous attempt) is worth a hint.
        fallos = [i["fase"] for i in e.get("intentos") or []]
        for f in set(fallos):
            if estados.get(f) == "ok" and f != actual:
                sub[f] = t("failed {n}×", n=fallos.count(f))
        self.pipeline.set_estados(estados, sub, self._tips(e))

    def _tips(self, e):
        tips = {}
        for f, txt in (e.get("detalles") or {}).items():
            linea = txt.strip().splitlines()[-1] if txt.strip() else ""
            tips[f] = linea[:160]
        return tips

    def _pintar_relojes(self):
        v = self._vista
        if not v:
            return
        e = v["e"]
        if v["corriendo"] and e.get("run_inicio"):
            self.lbl_reloj.setText(t("running for {d}", d=fmt_dur(
                time.time() - e["run_inicio"])))
        else:
            self.lbl_reloj.setText("")
        if v["corriendo"] and e.get("fase"):
            self._pintar_pipeline()

    def _mostrar_detalle(self, fase, refrescar=False):
        if not refrescar and self._fase_detalle == fase \
                and self.detalle.isVisible():
            self.detalle.setVisible(False)
            self._fase_detalle = None
            return
        self._fase_detalle = fase
        e = (self._vista or {}).get("e") or {}
        txt = (e.get("detalles") or {}).get(fase, "")
        if not txt:
            if fase == e.get("fase"):
                txt = t("{fase} is running right now; its output appears "
                        "here when it finishes. Live output: Logs.",
                        fase=nombre_fase(fase))
            else:
                txt = t("{fase}: no output yet in this run.",
                        fase=nombre_fase(fase))
        cabecera = f"── {nombre_fase(fase)} ──\n"
        if self.detalle.toPlainText() != cabecera + txt:
            self.detalle.setPlainText(cabecera + txt)
        self.detalle.setVisible(True)
        self.fase_pulsada.emit(fase)
