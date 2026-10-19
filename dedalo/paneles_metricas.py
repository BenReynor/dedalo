"""Metrics panel with pyqtgraph: 4 charts + summary table."""

import pyqtgraph as pg
from pyqtgraph import PlotWidget, mkBrush, mkPen
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import configuracion as cfg
from . import rutas
from .i18n import t
from .metricas import parsear_log
from .paneles import _BtnGhost, _fuente_monospace, _fuente_ui, _LabelMuted
from .temas import ACCENTO_CABINA, DATOS_ERROR, DATOS_EXITO


class PanelMetricas(QWidget):
    """Real-time metrics dashboard (reads progreso.log every 5s)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ruta_proyecto = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._actualizar)
        self._timer.setInterval(cfg.TIMER_METRICAS_MS)

        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        # Header
        h = QHBoxLayout()
        lbl = QLabel(t("📊 Loop Metrics"))
        _fuente_ui(lbl)
        lbl.setStyleSheet("font-size: 16px; font-weight: 600;")
        h.addWidget(lbl)
        h.addStretch()
        self.lbl_estado = _LabelMuted(t("No project"))
        h.addWidget(self.lbl_estado)
        self.cmb_rango = QComboBox()
        self.cmb_rango.addItems([
            t("Last 50 iters"), t("Last 100 iters"), t("Full history")])
        self.cmb_rango.currentTextChanged.connect(self._actualizar)
        h.addWidget(self.cmb_rango)
        v.addLayout(h)

        # Quick summary (4 KPIs)
        kpi = QHBoxLayout()
        kpi.setSpacing(12)
        self.kpi_total = self._crear_kpi(t("Total"), "0")
        self.kpi_hechas = self._crear_kpi(t("Done"), "0", DATOS_EXITO)
        self.kpi_bloqueadas = self._crear_kpi(t("Blocked"), "0", DATOS_ERROR)
        self.kpi_coste = self._crear_kpi(t("Cost USD"), "$0.00", ACCENTO_CABINA)
        kpi.addWidget(self.kpi_total)
        kpi.addWidget(self.kpi_hechas)
        kpi.addWidget(self.kpi_bloqueadas)
        kpi.addWidget(self.kpi_coste)
        v.addLayout(kpi)

        # Splitter: charts on top, table below
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(6)
        splitter.setChildrenCollapsible(False)

        # ---- Charts area (2x2 grid) ----
        graficas_widget = QWidget()
        g = QGridLayout(graficas_widget)
        g.setSpacing(8)
        g.setContentsMargins(0, 0, 0, 0)

        # 1. Tasks/hour (timeline)
        self.plot_tareas = self._crear_plot(t("Tasks completed / iteration"))
        self.curve_tareas = self.plot_tareas.plot(pen=mkPen(DATOS_EXITO, width=2), symbol='o', symbolSize=6, symbolBrush=mkBrush(DATOS_EXITO))
        g.addWidget(self.plot_tareas, 0, 0)

        # 2. Accumulated cost (amber, cockpit accent)
        self.plot_coste = self._crear_plot(t("Accumulated cost (USD)"))
        self.curve_coste = self.plot_coste.plot(pen=mkPen(ACCENTO_CABINA, width=2), symbol='o', symbolSize=6, symbolBrush=mkBrush(ACCENTO_CABINA))
        g.addWidget(self.plot_coste, 0, 1)

        # 3. Gate: OK vs FAIL (stacked bars)
        self.plot_gate = self._crear_plot(t("Gate: OK / FAIL"))
        self.bar_gate_ok = pg.BarGraphItem(x=[], height=[], width=0.6, brush=mkBrush(DATOS_EXITO))
        self.bar_gate_fail = pg.BarGraphItem(x=[], height=[], width=0.6, brush=mkBrush(DATOS_ERROR))
        self.plot_gate.addItem(self.bar_gate_ok)
        self.plot_gate.addItem(self.bar_gate_fail)
        g.addWidget(self.plot_gate, 1, 0)

        # 4. Reviewer: PASS vs FAIL
        self.plot_rev = self._crear_plot(t("Reviewer: PASS / FAIL"))
        self.bar_rev_pass = pg.BarGraphItem(x=[], height=[], width=0.6, brush=mkBrush(DATOS_EXITO))
        self.bar_rev_fail = pg.BarGraphItem(x=[], height=[], width=0.6, brush=mkBrush(DATOS_ERROR))
        self.plot_rev.addItem(self.bar_rev_pass)
        self.plot_rev.addItem(self.bar_rev_fail)
        g.addWidget(self.plot_rev, 1, 1)

        splitter.addWidget(graficas_widget)

        # ---- Summary table ----
        self.tabla = QTableWidget()
        self.tabla.setColumnCount(12)
        self.tabla.setHorizontalHeaderLabels([
            t("Iter"), t("Task"), t("Duration"), t("Est. Cost"), t("Real Cost"),
            t("Tokens In"), t("Tokens Out"), t("Latency"), t("Model"),
            t("Gate"), t("Reviewer"), t("Status")])
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        _fuente_monospace(self.tabla)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        splitter.addWidget(self.tabla)

        splitter.setSizes([500, 300])
        v.addWidget(splitter, 1)

        # Buttons
        h = QHBoxLayout()
        b_refresh = _BtnGhost(t("🔄 Refresh now"))
        b_refresh.clicked.connect(self._actualizar)
        b_export = _BtnGhost(t("📥 Export CSV"))
        b_export.clicked.connect(self._exportar_csv)
        h.addStretch()
        h.addWidget(b_refresh)
        h.addWidget(b_export)
        v.addLayout(h)

    def _crear_kpi(self, titulo: str, valor: str, color: str | None = None) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: palette(alternate-base); border-radius: 8px;")
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 12, 16, 12)
        lbl_t = QLabel(titulo)
        _fuente_ui(lbl_t)
        lbl_t.setStyleSheet("font-size: 11px; color: palette(mid);")
        lbl_v = QLabel(valor)
        _fuente_ui(lbl_v)
        lbl_v.setStyleSheet(f"font-size: 24px; font-weight: 600; color: {color or 'palette(text)'};")
        lbl_v.setAlignment(Qt.AlignCenter)
        v.addWidget(lbl_t)
        v.addWidget(lbl_v)
        w.lbl_valor = lbl_v
        return w

    def _crear_plot(self, titulo: str) -> PlotWidget:
        pw = PlotWidget(title=titulo)
        pw.setLabel('left', '')
        pw.setLabel('bottom', t("Iteration"))
        pw.showGrid(x=True, y=True, alpha=0.3)
        text_pen = pg.mkPen('#64748b')  # slate-500
        pw.getPlotItem().getAxis('bottom').setTextPen(text_pen)
        pw.getPlotItem().getAxis('left').setTextPen(text_pen)
        pw.setBackground('transparent')
        return pw

    def cargar(self, ruta_proyecto: str):
        self._ruta_proyecto = ruta_proyecto
        self._timer.start()
        self._actualizar()

    def _actualizar(self):
        if not self._ruta_proyecto:
            return
        log = rutas.log(self._ruta_proyecto)
        datos = parsear_log(log)
        self._pintar(datos)

    def _pintar(self, datos: dict):
        iters = datos["iteraciones"]
        series = datos["series"]
        resumen = datos["resumen"]

        # KPIs
        self.kpi_total.lbl_valor.setText(str(resumen["total"]))
        self.kpi_hechas.lbl_valor.setText(str(resumen["hechas"]))
        self.kpi_bloqueadas.lbl_valor.setText(str(resumen["bloqueadas"]))
        self.kpi_coste.lbl_valor.setText(f"${resumen['coste_total']:.2f}")
        self.lbl_estado.setText(
            t("Last update: {n} iterations", n=len(iters)))

        # Range
        rango_txt = self.cmb_rango.currentText()
        if "50" in rango_txt:
            n = 50
        elif "100" in rango_txt:
            n = 100
        else:
            n = len(iters)
        iters = iters[-n:]
        series = {k: v[-n:] for k, v in series.items()}

        # 1. Tasks/hour
        x = list(range(1, len(series["tareas_hora"]) + 1))
        y = [v for _, v in series["tareas_hora"]]
        self.curve_tareas.setData(x, y)

        # 2. Cost
        yc = [v for _, v in series["coste_acum"]]
        self.curve_coste.setData(x, yc)

        # 3. Gate bars
        gate_ok = [1 if v == 1 else 0 for _, v in series["gate"]]
        gate_fail = [1 if v == 0 else 0 for _, v in series["gate"]]
        self.bar_gate_ok.setOpts(x=x, height=gate_ok)
        self.bar_gate_fail.setOpts(x=[xi + 0.3 for xi in x], height=gate_fail)

        # 4. Reviewer bars
        rev_pass = [1 if v == 1 else 0 for _, v in series["revisor"]]
        rev_fail = [1 if v == 0 else 0 for _, v in series["revisor"]]
        self.bar_rev_pass.setOpts(x=x, height=rev_pass)
        self.bar_rev_fail.setOpts(x=[xi + 0.3 for xi in x], height=rev_fail)

        # Table
        self.tabla.setRowCount(len(iters))
        for row, it in enumerate(iters):
            vals = [
                str(it["iter"]),
                it["tarea"][:60],
                f"{it.get('duracion_s', 0):.1f}s",
                f"{it.get('coste_usd', 0):.4f}",
                f"{it.get('costo_real_usd', it.get('costo_usd_real', 0)):.4f}",
                str(it.get("tokens_in", 0)),
                str(it.get("tokens_out", 0)),
                f"{it.get('duracion_ms', it.get('duracion_s', 0)*1000):.0f}ms",
                it.get("modelos", ""),
                it.get("gate", "—"),
                it.get("revisor", "—"),
                it.get("estado", "—"),
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignCenter)
                if col == 11:
                    if val == "hecha":
                        item.setBackground(pg.mkColor("#22c55e"))
                    elif val == "bloqueada":
                        item.setBackground(pg.mkColor("#ef4444"))
                self.tabla.setItem(row, col, item)

    def _exportar_csv(self):
        if not self._ruta_proyecto:
            return
        from PySide6.QtWidgets import QFileDialog
        ruta, _ = QFileDialog.getSaveFileName(
            self, t("Export metrics CSV"), "metricas.csv", "CSV (*.csv)")
        if not ruta:
            return
        import csv
        log = rutas.log(self._ruta_proyecto)
        datos = parsear_log(log)
        with open(ruta, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([t("Iter"), t("Task"), t("Duration (s)"),
                        t("Est. Cost (USD)"), t("Real Cost (USD)"),
                        t("Tokens In"), t("Tokens Out"), t("Latency (ms)"),
                        t("Model"), t("Gate"), t("Reviewer"), t("Status")])
            for it in datos["iteraciones"]:
                w.writerow([
                    it["iter"], it["tarea"],
                    f"{it.get('duracion_s', 0):.1f}",
                    f"{it.get('coste_usd', 0):.4f}",
                    f"{it.get('costo_real_usd', it.get('costo_usd_real', 0)):.4f}",
                    it.get("tokens_in", 0), it.get("tokens_out", 0),
                    f"{it.get('duracion_ms', it.get('duracion_s', 0)*1000):.0f}",
                    it.get("modelos", ""),
                    it.get("gate", ""), it.get("revisor", ""), it.get("estado", "")
                ])

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
