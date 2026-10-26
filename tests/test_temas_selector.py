#!/usr/bin/env python3
"""Tests for temas.py and selector_modelo.py, the two modules without coverage.

temas.py is 959 lines and holds up the look of the whole app (9 themes, full QSS,
color tokens); if a token is renamed, the QSS degrades to
default values or raises an exception, the whole UI breaks without any
test noticing. selector_modelo.py is the widget for the provider/model combos
and its API (currentText/setCurrentText) is subtle: it always returns
'provider/model' and that value travels to the agent's CLI.
"""

import os
import re
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402

from dedalo import selector_modelo, temas  # noqa: E402

# ---------- themes ----------


def test_hay_nueve_temas_y_no_se_repiten():
    assert len(temas.NOMBRES) == 9, f"esperados 9 temas, hay {len(temas.NOMBRES)}"
    assert len(set(temas.NOMBRES)) == len(temas.NOMBRES), "hay nombres repetidos"


def _color_valido(valor):
    """Accepts the four token forms that _qss_variables() really uses:

      * '#rrggbb'                → QColor parses it
      * 'rgba(r,g,b,a)'          → QSS accepts it; QColor() does not, and that is why
                                   production has the _qcolor() helper
      * '37, 99, 235'            → triplet to interpolate inside rgb(...)
      * '0 1px 2px rgba(...)'    → box-shadow
    """
    valor = valor.strip()
    if valor.startswith("rgba"):
        return len(re.findall(r"[\d.]+", valor)) == 4
    if valor.startswith("#"):
        return QColor(valor).isValid()
    if re.fullmatch(r"[\d,\s]+", valor):
        return len(valor.split(",")) == 3
    return "px" in valor and "rgba" in valor


@pytest.mark.parametrize("nombre", temas.NOMBRES)
def test_variables_de_cada_tema_estan_completas(nombre):
    """Every token the QSS consumes must exist and have a usable value."""
    variables = temas._qss_variables(nombre)
    assert variables, f"{nombre} no devuelve variables"
    for clave, valor in variables.items():
        assert isinstance(clave, str) and clave
        assert isinstance(valor, str) and valor.strip(), (
            f"{nombre}: token {clave!r} vacío"
        )
        assert _color_valido(valor), (
            f"{nombre}: token {clave!r} = {valor!r} no tiene una forma conocida"
        )


def test_los_nueve_temas_declaran_los_mismos_tokens():
    """A token that exists in one theme but not another = half-built QSS."""
    referencia = set(temas._qss_variables(temas.NOMBRES[0]))
    assert referencia, "el primer tema no declara ningún token"
    for nombre in temas.NOMBRES[1:]:
        claves = set(temas._qss_variables(nombre))
        assert claves == referencia, (
            f"{nombre}: le faltan {referencia - claves} "
            f"y tiene de más {claves - referencia}"
        )


@pytest.mark.parametrize("nombre", temas.NOMBRES)
def test_qss_de_cada_tema_se_genera_sin_excepcion(app, nombre):
    """_qss() queries QFontDatabase, so it requires a live QApplication."""
    qss = temas._qss(temas._qss_variables(nombre))
    assert qss.strip(), f"{nombre} genera QSS vacío"
    assert "{" in qss and "}" in qss, f"{nombre} genera QSS mal formado"
    assert "None" not in qss, f"{nombre} ha interpolado None en el QSS"


def test_inicializar_temas_cubre_todos_los_nombres(app):
    temas.inicializar_temas()
    cache = temas.obtener_temas()
    faltan = [n for n in temas.NOMBRES if not cache.get(n)]
    assert not faltan, f"temas sin QSS generado: {faltan}"


def test_colores_tema_devuelve_los_tokens_que_pinta_la_gui(app):
    """colores_tema() is the source for manual painting; if it is missing a key,
    the consumer blows up with KeyError."""
    esperadas = {
        "bg_panel", "bg_sunken", "text_primary", "text_secondary",
        "text_tertiary", "text_inverse", "border", "accent", "accent_claro",
        "success", "error", "warning",
    }
    for nombre in temas.NOMBRES:
        colores = temas.colores_tema(nombre)
        assert esperadas <= set(colores), (
            f"{nombre}: faltan {esperadas - set(colores)}"
        )
        for clave in esperadas:
            assert isinstance(colores[clave], QColor), f"{nombre}:{clave} no es QColor"
            assert colores[clave].isValid(), f"{nombre}:{clave} es un QColor inválido"


def test_temas_oscuros_y_claros_no_son_el_mismo_color(app):
    """Detects a 'Claro' theme that got stuck with the dark theme's tokens."""
    oscuro = temas.colores_tema("Oscuro")
    claro = temas.colores_tema("Claro")
    assert oscuro["bg_panel"] != claro["bg_panel"], (
        "Oscuro y Claro tienen el mismo fondo: probablemente un token mal copiado"
    )


# ---------- selector_modelo ----------


def _selector(monkeypatch, catalogo=None, proveedores=None):
    """Selector with the global catalog controlled (without touching the network)."""
    monkeypatch.setattr(
        selector_modelo.modelos,
        "nombres_proveedores",
        lambda: proveedores or ["openai", "google"],
    )
    monkeypatch.setattr(
        selector_modelo.modelos,
        "lista_modelos_proveedor",
        lambda prov: (catalogo or {}).get(prov, [f"{prov}-default"]),
    )
    return selector_modelo.SelectorModelo()


def test_selector_devuelve_proveedor_modelo(app, monkeypatch):
    s = _selector(monkeypatch)
    s.addItems(["openai/gpt-4o", "openai/gpt-4o-mini", "google/gemini-2.0"])
    s.setCurrentText("openai/gpt-4o-mini")
    assert s.currentText() == "openai/gpt-4o-mini"


def test_selector_proveedor_sin_modelos_devuelve_solo_proveedor(app, monkeypatch):
    """Without models there is no 'prov/model' to return: it stays on the provider."""
    s = _selector(monkeypatch, catalogo={"openai": []})
    s.setCurrentText("openai")
    assert s.currentText() == "openai"


def test_selector_cambiar_de_proveedor_elige_su_primer_modelo(app, monkeypatch):
    """Changing provider repopulates the combo and leaves one selected, so as not to
    return a model that no longer belongs to the chosen provider."""
    s = _selector(
        monkeypatch,
        catalogo={
            "openai": ["gpt-4o", "gpt-4o-mini"],
            "google": ["gemini-2.0"],
        },
    )
    s.setCurrentText("openai/gpt-4o-mini")
    assert s.currentText() == "openai/gpt-4o-mini"
    s.setCurrentText("google")
    assert s.currentText() == "google/gemini-2.0", (
        "al cambiar de proveedor se mantiene un modelo del anterior"
    )


def test_selector_vacio_devuelve_cadena_vacia(app, monkeypatch):
    s = _selector(monkeypatch)
    s.clear()
    assert s.currentText() == ""


def test_selector_emite_al_cambiar(app, monkeypatch):
    s = _selector(monkeypatch)
    s.addItems(["openai/gpt-4o"])
    emitidos = []
    s.currentTextChanged.connect(emitidos.append)
    s.setCurrentText("openai/gpt-4o")
    assert emitidos == ["openai/gpt-4o"]


def test_selector_ignora_etiquetas_sin_proveedor(app, monkeypatch):
    """A 'model' without '/' has no provider: it cannot generate a valid id."""
    s = _selector(monkeypatch)
    s.addItems(["sin-proveedor"])
    assert "sin-proveedor" not in [
        s.cmb_proveedor.itemText(i) for i in range(s.cmb_proveedor.count())
    ]


def test_selector_no_duplica_modelos(app, monkeypatch):
    s = _selector(monkeypatch)
    s.addItems(["openai/gpt-4o", "openai/gpt-4o"])
    s.setCurrentText("openai")
    assert s.cmb_modelo.count() == 1, "el mismo modelo se ha duplicado"


def _esperar(selector):
    from PySide6.QtWidgets import QApplication
    for w in list(selector._pendientes.values()):
        w.wait(5000)
    QApplication.processEvents()
    QApplication.processEvents()


def test_selector_elegir_proveedor_carga_en_segundo_plano(app, monkeypatch):
    """A user-picked provider without cached models is fetched off the UI thread."""
    s = _selector(monkeypatch, catalogo={"openai": ["gpt-4o"],
                                         "google": ["gemini-2.0"]})
    s.cmb_proveedor.setCurrentText("google")
    assert "google" in s._pendientes or s.cmb_modelo.count() == 1
    _esperar(s)
    assert s.currentText() == "google/gemini-2.0"
    assert s.cmb_modelo.isEnabled()


def test_selector_descarta_respuesta_de_proveedor_anterior(app, monkeypatch):
    """A slow answer for a provider the user already left must not win."""
    import threading
    soltar = threading.Event()

    def lista(prov):
        if prov == "google":
            soltar.wait(5)
        return {"google": ["gemini-2.0"], "openai": ["gpt-4o"]}[prov]

    s = _selector(monkeypatch)
    monkeypatch.setattr(selector_modelo.modelos, "lista_modelos_proveedor", lista)
    s._catalogo.clear()
    s.cmb_proveedor.setCurrentText("google")
    s.cmb_proveedor.setCurrentText("openai")
    soltar.set()
    _esperar(s)
    assert s.currentText() == "openai/gpt-4o"
