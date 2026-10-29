"""Run cockpit: what an observer sees, fed by estado_loop.json.

The old stepper only moved for loops the GUI itself launched and guessed the
phase from the log; these tests pin the new contract: any running loop (GUI
or MCP) lights its real phase, a dead pid is not shown as running, and the
plan progress comes from the `## ` sections of plan.md.
"""

import os
import subprocess
import sys
import time

import pytest

from dedalo import cabina, estado_loop, loops_estado
from dedalo.paneles import fase_actual


@pytest.fixture
def proyecto(tmp_path):
    (tmp_path / ".dedalo" / "estado").mkdir(parents=True)
    (tmp_path / "plan.md").write_text(
        "# PLAN\n\n## Convenciones\n- nada que hacer aquí\n\n"
        "## FASE 1 — Base\n- [x] a\n- [x] b\n\n"
        "## FASE 2 — Interfaz\n- [x] c\n- [B] d\n- [ ] e\n- [ ] f\n",
        encoding="utf-8")
    return tmp_path


def _publicar(proyecto, pid=None, **cambios):
    ev = estado_loop.EstadoLoop(str(proyecto), max_iter=5, max_reintentos=2,
                                agente="claude")
    ev.corriendo()
    ev.nueva_tarea(3, "e", "criterio de e")
    ev.nuevo_intento(1)
    ev.fase("Agente")
    ev.resultado("Agente", True, "hice e")
    ev.fase("Gate")
    if pid is not None or cambios:
        datos = estado_loop.leer(str(proyecto))
        if pid is not None:
            datos["pid"] = pid
        datos.update(cambios)
        estado_loop._escribir(estado_loop.ruta(str(proyecto)), datos)
    return ev


def test_secciones_del_plan_ignoran_encabezados_sin_tareas():
    texto = ("## Notas\ntexto\n## FASE 1\n- [x] a\n- [ ] b\n"
             "## FASE 2\n- [B] c\n")
    assert cabina.secciones_plan(texto) == [
        ("FASE 1", 1, 2, 0), ("FASE 2", 0, 1, 1)]


def test_vista_de_un_loop_vivo_lanzado_por_otro(proyecto):
    """Running pid (this test's), not launched by the GUI: still shown live."""
    _publicar(proyecto)
    v = cabina.vista_loop("p", str(proyecto), local_corriendo=False)
    assert v["corriendo"] and v["estado"] == "corriendo"
    assert v["e"]["fase"] == "Gate" and v["e"]["iteracion"] == 3
    assert (v["hechas"], v["total"], v["bloqueadas"]) == (3, 6, 1)
    assert v["pendientes"] == 2


def test_un_pid_muerto_no_se_muestra_corriendo(proyecto):
    muerto = subprocess.Popen([sys.executable, "-c", "pass"])
    muerto.wait()
    _publicar(proyecto, pid=muerto.pid)
    v = cabina.vista_loop("p", str(proyecto))
    assert not v["corriendo"]
    assert v["estado"] == "caido"


def test_el_registro_compartido_manda_aunque_no_haya_json(proyecto):
    loops_estado.registrar("p", os.getpid(), origen="mcp")
    v = cabina.vista_loop("p", str(proyecto))
    assert v["corriendo"] and v["estado"] == "arrancando"


def test_estimacion_con_la_media_de_las_tareas_hechas(proyecto):
    ev = _publicar(proyecto)
    ev.datos["historial"] = [
        {"iteracion": 1, "tarea": "c", "resultado": "hecha", "intentos": 1,
         "fallos": [], "dur": 100.0},
        {"iteracion": 2, "tarea": "d", "resultado": "bloqueada", "intentos": 2,
         "fallos": ["Gate", "Gate"], "dur": 500.0}]
    ev.datos["tarea_inicio"] = time.time() - 30
    ev._guardar()
    v = cabina.vista_loop("p", str(proyecto))
    # 2 pending (e is in progress + f), media 100 s, 30 s already spent on e.
    assert v["restantes"] == 2
    assert v["media"] == 100.0
    assert 160 <= v["eta"] <= 175


def test_la_cabina_enciende_la_fase_real(app, proyecto):
    _publicar(proyecto)
    c = cabina.CabinaLoop()
    c.actualizar(cabina.vista_loop("p", str(proyecto)))
    estados = c.pipeline.estados()
    assert estados == {"Plan": "ok", "Agente": "ok", "Gate": "active",
                       "Revisor": "idle", "Commit": "idle"}
    assert c.lbl_estado.property("estado") == "marcha"
    assert "e" in c.lbl_tarea.toolTip()


def test_esperando_revision_humana_se_ve_distinto(app, proyecto):
    ev = _publicar(proyecto)
    ev.resultado("Gate", True, "[GATE] ✅")
    ev.fase("Revisor", esperando_humano=True)
    c = cabina.CabinaLoop()
    c.actualizar(cabina.vista_loop("p", str(proyecto)))
    assert c.pipeline.estados()["Revisor"] == "wait"
    assert c.lbl_estado.property("estado") == "espera"


def test_un_fallo_marca_solo_su_fase_y_se_puede_ver(app, proyecto):
    ev = _publicar(proyecto)
    ev.resultado("Gate", False, "[GATE] ✗ tests fallaron")
    ev.cerrar_tarea("bloqueada")
    ev.terminar(0)
    c = cabina.CabinaLoop()
    c.actualizar(cabina.vista_loop("p", str(proyecto)))
    estados = c.pipeline.estados()
    assert estados["Gate"] == "fail"
    assert estados["Agente"] == "ok" and estados["Revisor"] == "idle"
    c._mostrar_detalle("Gate")
    assert "tests fallaron" in c.detalle.toPlainText()
    assert c.lbl_estado.property("estado") == "ok"


def test_fase_desde_el_log_usa_la_marca_mas_reciente(tmp_path):
    log = tmp_path / "progreso.log"
    log.write_text(
        "[t] == Iteración 1: a ==\n[t] GATE: ejecutando gate.sh (intento 1)\n"
        "[t] REVISOR PASS (claude, intento 1)\n[t] commit en x: dedalo: a\n",
        encoding="utf-8")
    assert fase_actual(str(log)) == "Commit"
    log.write_text("[t] DEDALO INICIADO\n[t] Baseline GATE OK\n",
                   encoding="utf-8")
    assert fase_actual(str(log)) == "Plan"
