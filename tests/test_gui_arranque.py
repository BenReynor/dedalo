"""Smoke test for the window's startup path.

`Ventana.__init__` loads the current project, and that refresh consults the
external-loop state. A missing attribute there crashed the GUI at startup for
every user with a project registered, so the whole construction is exercised
here instead of isolated helpers.
"""

from dedalo import app as app_mod
from dedalo import proyectos


def test_la_ventana_arranca_con_un_proyecto_registrado(app, tmp_path, monkeypatch):
    proy = tmp_path / "proy"
    proy.mkdir()
    (proy / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (proy / "lecciones.md").write_text("", encoding="utf-8")
    proyectos.guardar({"proy": {"ruta": str(proy)}})

    # Network/agent probes run in background threads: not part of the startup
    # path under test and they would make the test slow and flaky.
    monkeypatch.setattr(app_mod.Ventana, "_cargar_modelos_en_fondo",
                        lambda self: None)
    monkeypatch.setattr(app_mod.Ventana, "_sondear_sesiones_en_fondo",
                        lambda self: None)
    monkeypatch.setattr(app_mod.Ventana, "_comprobar_net", lambda self: None)

    ventana = app_mod.Ventana()
    try:
        assert ventana._loop_externo is False
        assert ventana._proyecto_actual() == ("proy", str(proy))
    finally:
        ventana.close()
        ventana.deleteLater()


def test_consultar_catalogo_calienta_proveedores_fuera_del_hilo_ui(monkeypatch):
    """The worker warms the first provider and saved ones not listed by opencode."""
    m = app_mod.modelos
    pedidos = []
    monkeypatch.setattr(m, "lista_modelos", lambda: ["openai/gpt-4o"])
    monkeypatch.setattr(m, "nombres_proveedores", lambda: ["google", "openai"])
    monkeypatch.setattr(m, "lista_modelos_proveedor",
                        lambda prov: pedidos.append(prov) or [])
    lista, n = app_mod._consultar_catalogo(["groq", "openai", ""])
    assert lista == ["openai/gpt-4o"] and n == 2
    assert sorted(pedidos) == ["google", "groq"]
