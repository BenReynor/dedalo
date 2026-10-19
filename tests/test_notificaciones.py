"""Tests for the Qt-free notification module and the engine's notifications."""


from dedalo import loop, notificaciones

CONFIG = {
    "telegram_token": "tok",
    "telegram_chat_id": "123",
    "eventos": {"externo": True, "tarea": True, "fin": True},
}


class _Respuesta:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_las_plantillas_nuevas_muestran_el_origen_y_el_commit():
    msg = notificaciones.formatear("externo", {
        "proyecto": "p", "origen": "mcp",
        "modelo_tarea": "m1", "modelo_revisor": "m2"})
    assert "MCP" in msg and "mcp" in msg and "m1" in msg

    msg = notificaciones.formatear("tarea", {
        "proyecto": "p", "tarea": "login", "iteracion": 2,
        "rama": "dedalo/x", "commit": "\nCommit: `abc`"})
    assert "login" in msg and "abc" in msg

    # Without a commit the placeholder is simply omitted.
    msg = notificaciones.formatear("tarea", {
        "proyecto": "p", "tarea": "login", "iteracion": 2,
        "rama": "dedalo/x"})
    assert "Commit" not in msg


def test_un_evento_desactivado_no_envia_nada(monkeypatch):
    def _explotar(*a, **k):
        raise AssertionError("urlopen should not be called")

    monkeypatch.setattr("urllib.request.urlopen", _explotar)
    config = {**CONFIG, "eventos": {"externo": False}}
    assert notificaciones.enviar("externo", {"origen": "mcp"}, config=config) == []


def test_envia_por_telegram(monkeypatch):
    llamadas = []

    def _urlopen(req, timeout=None):
        llamadas.append(req.full_url)
        return _Respuesta()

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    res = notificaciones.enviar("tarea", {
        "proyecto": "p", "tarea": "t", "iteracion": 1, "rama": "r"},
        config=CONFIG)
    assert res == [("telegram", "OK")]
    assert llamadas and llamadas[0].startswith(
        "https://api.telegram.org/bottok/sendMessage")


def test_un_error_de_red_no_propaga(monkeypatch):
    def _falla(req, timeout=None):
        raise OSError("sin red con tok")

    monkeypatch.setattr("urllib.request.urlopen", _falla)
    res = notificaciones.enviar("tarea", {"proyecto": "p", "tarea": "t"},
                                config=CONFIG)
    assert res and res[0][0] == "telegram"
    assert "***" in res[0][1] and "tok" not in res[0][1]


def test_el_loop_no_se_rompe_si_notificar_falla(monkeypatch):
    class Cfg:
        nombre = ""
        proyecto = "/tmp/proyecto-x"

    def _explotar(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(notificaciones, "enviar", _explotar)
    loop._notificar(Cfg(), "tarea", tarea="t")  # must not raise


def test_el_loop_incluye_el_nombre_del_proyecto(monkeypatch):
    enviados = []
    monkeypatch.setattr(notificaciones, "enviar",
                        lambda ev, datos, **k: enviados.append((ev, datos)))

    class Cfg:
        nombre = "prueba-web"
        proyecto = "/tmp/otro"

    loop._notificar(Cfg(), "externo", origen="mcp")
    assert enviados == [("externo", {"proyecto": "prueba-web",
                                     "origen": "mcp"})]


def test_normalizar_activa_los_eventos_nuevos_por_defecto():
    """An old config without `externo`/`tarea` must not silence them: the GUI
    renders an absent switch as checked."""
    viejo = {"telegram_token": "tok", "telegram_chat_id": "123",
             "eventos": {"inicio": True}}
    config = notificaciones.normalizar(viejo)
    assert config["eventos"]["externo"] is True
    assert config["eventos"]["tarea"] is True
    assert notificaciones.esta_activo(config, "externo")

    apagado = notificaciones.normalizar(
        {**viejo, "eventos": {"externo": False}})
    assert not notificaciones.esta_activo(apagado, "externo")
