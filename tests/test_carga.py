"""Startup splash: progress only moves forward and the agent session probes
run in parallel (they used to add ~10 s one after another)."""
import time

from dedalo import carga, modelos


def test_paso_muestra_texto_y_no_retrocede(app):
    pantalla = carga.PantallaCarga()
    pantalla.paso("uno", 40)
    pantalla.paso("dos", 20)
    assert pantalla.lbl_paso.text() == "dos"
    assert pantalla.barra.value() == 40
    pantalla.paso("tres", 250)
    assert pantalla.barra.value() == 100
    pantalla.close()


def test_precalentar_sondea_en_paralelo_y_avisa_cada_agente(app, monkeypatch):
    monkeypatch.setattr(modelos, "agentes_instalados",
                        lambda preferidos=None: ["claude", "codex", "opencode"])
    sesiones = {"claude": True, "codex": False, "opencode": None}

    def lenta(nombre):
        time.sleep(0.3)
        return sesiones[nombre]

    monkeypatch.setattr(modelos, "sesion_agente", lenta)
    avances = []
    inicio = time.monotonic()
    carga.precalentar_agentes(lambda texto, valor: avances.append((texto, valor)),
                              desde=10, hasta=70)
    assert time.monotonic() - inicio < 0.8      # 3 × 0.3 s en serie serían 0.9 s
    assert avances[0][1] == 10
    assert avances[-1][1] == 70
    textos = " ".join(texto for texto, _ in avances[1:])
    assert "claude ✓" in textos and "codex ✗" in textos and "opencode ?" in textos


def test_precalentar_sin_agentes_no_hace_nada(app, monkeypatch):
    monkeypatch.setattr(modelos, "agentes_instalados", lambda preferidos=None: [])
    avances = []
    carga.precalentar_agentes(lambda *a: avances.append(a))
    assert avances == []
