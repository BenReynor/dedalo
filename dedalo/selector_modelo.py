"""Two-level AI model selector: provider -> model.

When a provider is chosen (opencode, google, openai, anthropic...) the model
combo is filled with that company's real model list. Everything by selection,
no typing: the catalogs come from `opencode models` (when the provider has
credentials) or from models.dev.

Design: it keeps a local catalog {provider: [models]}. Live lookups only
happen the first time a provider is requested (and the rest of the package
caches them per session), so the GUI refresh stays lightweight.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from . import modelos
from .proceso import Trabajo


class SelectorModelo(QWidget):
    """Chained provider/model combos, both selection-only.

    Exposes a QComboBox-like API (addItems, currentText, setCurrentText,
    clear, blockSignals) but always returning 'provider/model'.
    """

    currentTextChanged = Signal(str)

    def __init__(self, proveedores=None, parent=None):
        super().__init__(parent)
        self._catalogo = {}
        self._proveedores_inicial = proveedores
        self._pendientes = {}  # provider -> running Trabajo

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.cmb_proveedor = QComboBox()
        self.cmb_modelo = QComboBox()
        h.addWidget(self.cmb_proveedor, 2)
        h.addWidget(QLabel("/"))
        h.addWidget(self.cmb_modelo, 3)

        self.cmb_proveedor.currentTextChanged.connect(self._proveedor_elegido)
        self.cmb_modelo.currentTextChanged.connect(self._emitir)
        self._refrescar_proveedores()

    def activar_catalogo_global(self):
        """Uses the globally detected catalog instead of the initial list."""
        self._proveedores_inicial = None
        self._refrescar_proveedores()

    # ---------- QComboBox-like API ----------

    def addItems(self, etiquetas=None):
        """Adds a 'provider/model' list to the local catalog."""
        for m in etiquetas or []:
            if "/" in m:
                prov, modelo = m.split("/", 1)
                self._catalogo.setdefault(prov, [])
                if modelo not in self._catalogo[prov]:
                    self._catalogo[prov].append(modelo)
        self._refrescar_proveedores()

    def clear(self):
        self._catalogo = {}
        self.cmb_proveedor.blockSignals(True)
        self.cmb_modelo.blockSignals(True)
        self.cmb_proveedor.clear()
        self.cmb_modelo.clear()
        self.cmb_proveedor.blockSignals(False)
        self.cmb_modelo.blockSignals(False)

    def blockSignals(self, bloqueado):
        super().blockSignals(bloqueado)
        self.cmb_proveedor.blockSignals(bloqueado)
        self.cmb_modelo.blockSignals(bloqueado)

    def currentText(self):
        prov = (self.cmb_proveedor.currentText() or "").strip()
        idm = (self.cmb_modelo.currentText() or "").strip()
        if not prov:
            return ""
        if not idm:
            return prov
        if "/" in idm and not idm.startswith(prov + "/"):
            return idm
        return f"{prov}/{idm}"

    def setCurrentText(self, valor):
        valor = (valor or "").strip()
        self.blockSignals(True)
        if valor:
            if "/" in valor:
                prov, idm = valor.split("/", 1)
            else:
                prov, idm = valor, ""
            self.cmb_proveedor.setCurrentText(prov)
            # We always have to repopulate: with signals blocked,
            # cmb_proveedor doesn't fire _cargar_modelos(), and the model combo
            # kept the previous provider's models. Without this,
            # setCurrentText("google") returned "google/gpt-4o-mini".
            self._cargar_modelos(prov)
            if idm:
                self.cmb_modelo.setCurrentText(idm)
        self.blockSignals(False)
        self._emitir()

    # ---------- Internals ----------

    def _emitir(self, _=None):
        self.currentTextChanged.emit(self.currentText())

    def _refrescar_proveedores(self):
        fuentes = set(self._catalogo)
        if self._proveedores_inicial is not None:
            fuentes |= set(self._proveedores_inicial)
        else:
            fuentes |= set(modelos.nombres_proveedores())
        proveedores = sorted(fuentes)
        actual = self.cmb_proveedor.currentText()
        self.cmb_proveedor.blockSignals(True)
        self.cmb_proveedor.clear()
        self.cmb_proveedor.addItems(proveedores)
        if actual and self.cmb_proveedor.findText(actual) >= 0:
            self.cmb_proveedor.setCurrentText(actual)
        self.cmb_proveedor.blockSignals(False)
        self._cargar_modelos(self.cmb_proveedor.currentText())

    def _proveedor_elegido(self, prov):
        """User picked a provider: fetch its models off the UI thread if needed.

        `opencode models <prov>` can take up to TIMEOUT_OPENCODE seconds.
        Programmatic changes (setCurrentText, refresh) block signals and keep
        loading synchronously, from caches warmed by the app's worker.
        """
        prov = (prov or "").strip()
        if not prov or prov in self._catalogo:
            self.cmb_modelo.setEnabled(True)
            self._cargar_modelos(prov)
            return
        if prov in self._pendientes:
            return
        self.cmb_modelo.blockSignals(True)
        # Empty combo + placeholder: currentText() stays "prov" while loading,
        # never a fake "prov/…" model id.
        self.cmb_modelo.clear()
        self.cmb_modelo.setPlaceholderText("…")
        self.cmb_modelo.setEnabled(False)
        self.cmb_modelo.blockSignals(False)
        w = Trabajo(lambda: modelos.lista_modelos_proveedor(prov))
        w.conectar(lambda lista: self._modelos_recibidos(prov, lista))
        w.finished.connect(lambda: self._pendientes.pop(prov, None))
        self._pendientes[prov] = w
        w.start()

    def _modelos_recibidos(self, prov, lista):
        self._catalogo.setdefault(prov, list(lista or []))
        # Stale answer: the user already moved to another provider.
        if (self.cmb_proveedor.currentText() or "").strip() != prov:
            return
        self.cmb_modelo.setEnabled(True)
        self._cargar_modelos(prov)

    def _cargar_modelos(self, prov):
        prov = (prov or "").strip()
        lista = self._catalogo.get(prov)
        if lista is None:
            lista = modelos.lista_modelos_proveedor(prov)
            self._catalogo[prov] = lista
        actual = self.cmb_modelo.currentText()
        self.cmb_modelo.blockSignals(True)
        self.cmb_modelo.clear()
        self.cmb_modelo.addItems(lista)
        if actual and self.cmb_modelo.findText(actual) >= 0:
            self.cmb_modelo.setCurrentText(actual)
        elif self.cmb_modelo.currentIndex() < 0 and lista:
            # Qt6 leaves the index at -1 after a placeholder was shown.
            self.cmb_modelo.setCurrentIndex(0)
        self.cmb_modelo.blockSignals(False)
        if not self.signalsBlocked():
            self._emitir()
