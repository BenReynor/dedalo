#!/usr/bin/env python3
"""Tests for metricas.py - parsing of progreso.log"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dedalo.metricas import invalidar_cache_metricas, parsear_log

SAMPLE_LOG = """[2025-01-15 10:00:00] [1/40] Tarea 1: arreglar login -> dedalo/2025-01-15/t1
[2025-01-15 10:02:00] ✔ commit: Tarea 1: arreglar login
[2025-01-15 10:02:00] Costo estimado acumulado: 0.50 USD
[2025-01-15 10:05:00] [2/40] Tarea 2: validar email -> dedalo/2025-01-15/t2
[2025-01-15 10:08:00] ✗ tarea bloqueada tras 2 intentos. Marcada [B] en plan.md
[2025-01-15 10:08:00] Costo estimado acumulado: 1.00 USD
[2025-01-15 10:10:00] [3/40] Tarea 3: tests unitarios -> dedalo/2025-01-15/t3
[2025-01-15 10:15:00] ✔ commit: Tarea 3: tests unitarios
[2025-01-15 10:15:00] Costo estimado acumulado: 1.50 USD
[2025-01-15 10:20:00] == DEDALO FINALIZADO (iter=3, rama=dedalo/2025-01-15, costo≈1.50) ==
"""

def test_parsear_log_basico():
    """Test basic log parsing with done and blocked tasks"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write(SAMPLE_LOG)
        log_path = f.name

    try:
        result = parsear_log(log_path)

        # Check structure
        assert "iteraciones" in result
        assert "series" in result
        assert "resumen" in result

        # Check parsed iterations
        iteraciones = result["iteraciones"]
        assert len(iteraciones) == 3

        # Task 1 - done
        assert iteraciones[0]["tarea"] == "Tarea 1: arreglar login"
        assert iteraciones[0]["estado"] == "hecha"
        assert iteraciones[0]["gate"] == "ok"
        assert iteraciones[0]["revisor"] == "pass"

        # Task 2 - blocked
        assert iteraciones[1]["tarea"] == "Tarea 2: validar email"
        assert iteraciones[1]["estado"] == "bloqueada"

        # Task 3 - done
        assert iteraciones[2]["tarea"] == "Tarea 3: tests unitarios"
        assert iteraciones[2]["estado"] == "hecha"

        # Check summary
        resumen = result["resumen"]
        assert resumen["total"] == 3
        assert resumen["hechas"] == 2
        assert resumen["bloqueadas"] == 1
        assert resumen["coste_total"] == 1.50

        # Check series
        series = result["series"]
        assert len(series["tareas_hora"]) == 3
        assert len(series["coste_acum"]) == 3

        print("✅ test_parsear_log_basico PASSED")
    finally:
        os.unlink(log_path)


def test_parsear_log_vacio():
    """Test with an empty or nonexistent log"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write("")
        log_path = f.name

    try:
        result = parsear_log(log_path)
        assert result["resumen"]["total"] == 0
        assert len(result["iteraciones"]) == 0
        print("✅ test_parsear_log_vacio PASSED")
    finally:
        os.unlink(log_path)


def test_parsear_log_solo_inicio():
    """Test a log with only iteration starts (without end)"""
    log = """[2025-01-15 10:00:00] [1/40] Tarea 1 -> dedalo/2025-01-15/t1
[2025-01-15 10:05:00] [2/40] Tarea 2 -> dedalo/2025-01-15/t2
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write(log)
        log_path = f.name

    try:
        result = parsear_log(log_path)
        assert len(result["iteraciones"]) == 2
        assert result["iteraciones"][0]["estado"] == "en_progreso"
        assert result["iteraciones"][1]["estado"] == "en_progreso"
        print("✅ test_parsear_log_solo_inicio PASSED")
    finally:
        os.unlink(log_path)


def test_series_temporales():
    """Check that the time series are generated correctly"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write(SAMPLE_LOG)
        log_path = f.name

    try:
        result = parsear_log(log_path)
        series = result["series"]

        # tareas_hora cumulative: 1, 1, 2 (the first done, the second blocked, the third done)
        tareas = [v for _, v in series["tareas_hora"]]
        assert tareas == [1, 1, 2]

        # cumulative cost
        costes = [v for _, v in series["coste_acum"]]
        assert costes == [0.5, 1.0, 1.5]

        print("✅ test_series_temporales PASSED")
    finally:
        os.unlink(log_path)


def test_coste_con_coma_decimal():
    """The real log (locale es_CO) writes '0,50 USD' with a decimal comma."""
    log = """[2025-01-15 10:00:00] [1/40] Tarea 1 -> dedalo/tareas/2025-01-15/t1
[2025-01-15 10:02:00] ✔ commit: Tarea 1
[2025-01-15 10:02:00] Costo estimado acumulado: 0,50 USD
[2025-01-15 10:05:00] [2/40] Tarea 2 -> dedalo/tareas/2025-01-15/t2
[2025-01-15 10:07:00] ✔ commit: Tarea 2
[2025-01-15 10:07:00] Costo estimado acumulado: 1,00 USD
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write(log)
        log_path = f.name

    try:
        result = parsear_log(log_path)
        # New branch format tolerated: dedalo/tareas/FECHA/tN
        assert len(result["iteraciones"]) == 2
        assert result["iteraciones"][0]["tarea"] == "Tarea 1"
        assert result["iteraciones"][0]["duracion_s"] == 120
        assert result["resumen"]["coste_total"] == 1.00
        costes = [v for _, v in result["series"]["coste_acum"]]
        assert costes == [0.50, 1.00]
        print("✅ test_coste_con_coma_decimal PASSED")
    finally:
        os.unlink(log_path)


def test_coste_por_iteracion():
    """Exact cost per iteration: each task adds its own cost to the accumulated
    series (log format dedalo: 'Costo iteración N: X USD')."""
    log = """[2025-01-15 10:00:00] == Iteración 1: Tarea A (rama dedalo/tareas/2025-01-15/t1) ==
[2025-01-15 10:02:00] Costo iteración 1: 1.00 USD
[2025-01-15 10:02:00] ✔ commit: Tarea A
[2025-01-15 10:05:00] == Iteración 2: Tarea B (rama dedalo/tareas/2025-01-15/t2) ==
[2025-01-15 10:07:00] Costo iteración 2: 0.50 USD
[2025-01-15 10:07:00] ✔ commit: Tarea B
[2025-01-15 10:10:00] == Iteración 3: Tarea C (rama dedalo/tareas/2025-01-15/t3) ==
[2025-01-15 10:12:00] Costo iteración 3: 0.75 USD
[2025-01-15 10:12:00] ✗ tarea bloqueada tras 2 intentos. Marcada [B] en plan.md
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write(log)
        log_path = f.name

    try:
        result = parsear_log(log_path)
        iters = result["iteraciones"]
        assert [it["iter"] for it in iters] == [1, 2, 3]
        # Exact cost assigned to each iteration (the accumulated one no longer overrides)
        assert iters[0]["coste_usd"] == 1.00
        assert iters[1]["coste_usd"] == 0.50
        assert iters[2]["coste_usd"] == 0.75
        # Accumulated series per iteration
        costes = [v for _, v in result["series"]["coste_acum"]]
        assert costes == [1.00, 1.50, 2.25]
        assert result["resumen"]["coste_total"] == 2.25
        print("✅ test_coste_por_iteracion PASSED")
    finally:
        os.unlink(log_path)


def test_iteraciones_con_criterio_no_se_pierden():
    """The suffix " | criterio: ..." must not hide the iteration.

    This is the REAL format that dedalo.sh:781 emits whenever the task
    in plan.md carries a criterio, which the template requires. The regex demanded ") =="
    right after the branch, so it did not match any normal iteration: the
    iteration stayed open, the closing lines were ignored and the
    panel showed fewer iterations than there were (and cost 0).
    """
    log = """[2025-01-15 10:00:00] == Iteración 1: Tarea A (rama dedalo/tareas/2025-01-15/t1) | criterio: pytest test_a en verde ==
[2025-01-15 10:02:00] Costo iteración 1: 1.00 USD
[2025-01-15 10:02:00] ✔ commit: Tarea A
[2025-01-15 10:05:00] == Iteración 2: Tarea B (rama dedalo/tareas/2025-01-15/t2) | criterio: pytest test_b en verde y flake8 limpio ==
[2025-01-15 10:07:00] Costo iteración 2: 0.50 USD
[2025-01-15 10:07:00] ✗ tarea bloqueada tras 2 intentos. Marcada [B] en plan.md
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write(log)
        log_path = f.name

    try:
        result = parsear_log(log_path)
        iters = result["iteraciones"]
        assert [it["iter"] for it in iters] == [1, 2], (
            f"iteraciones perdidas: {[it['iter'] for it in iters]}")
        # The criterio must NOT slip into the task name
        assert iters[0]["tarea"] == "Tarea A", iters[0]["tarea"]
        assert iters[1]["tarea"] == "Tarea B", iters[1]["tarea"]
        # States and counters
        assert iters[0]["estado"] == "hecha", iters[0]["estado"]
        assert iters[1]["estado"] == "bloqueada", iters[1]["estado"]
        assert result["resumen"]["total"] == 2, result["resumen"]
        assert result["resumen"]["hechas"] == 1, result["resumen"]
        assert result["resumen"]["bloqueadas"] == 1, result["resumen"]
        # And the cost is accounted for
        assert iters[0]["coste_usd"] == 1.00
        assert result["resumen"]["coste_total"] == 1.50
        assert len(result["series"]["coste_acum"]) == 2
    finally:
        os.unlink(log_path)


def test_iteraciones_legadas_siguen_parseando():
    """Without criterio (old format) and with a legacy branch: nothing breaks."""
    log = """[2025-01-15 10:00:00] == Iteración 1: Sin criterio (rama dedalo/tareas/2025-01-15/t1) ==
[2025-01-15 10:01:00] ✔ commit: Sin criterio
[2025-01-15 10:05:00] == Iteración 2: Rama legacy (rama dedalo/2025-01-15/t2) ==
[2025-01-15 10:06:00] ✔ commit: Rama legacy
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write(log)
        log_path = f.name
    try:
        result = parsear_log(log_path)
        assert [it["iter"] for it in result["iteraciones"]] == [1, 2]
        assert result["resumen"]["hechas"] == 2, result["resumen"]
    finally:
        os.unlink(log_path)


def test_cache_no_reparsea_si_no_cambia():
    """Two consecutive calls without touching the file return the same object."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write(SAMPLE_LOG)
        log_path = f.name
    try:
        primero = parsear_log(log_path)
        segundo = parsear_log(log_path)
        assert primero is segundo
    finally:
        os.unlink(log_path)
        invalidar_cache_metricas(log_path)


def test_cache_se_invalida_al_cambiar_el_log():
    """If the log grows, the parsing is redone and it sees the new iterations."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write(SAMPLE_LOG)
        log_path = f.name
    try:
        primero = parsear_log(log_path)
        assert len(primero["iteraciones"]) == 3
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("[2025-01-15 10:25:00] == Iteración 4: nueva (rama "
                    "dedalo/tareas/2025-01-15/t4) ==\n")
            f.write("[2025-01-15 10:26:00] ✔ commit: nueva\n")
        segundo = parsear_log(log_path)
        assert segundo is not primero
        assert len(segundo["iteraciones"]) == 4
    finally:
        os.unlink(log_path)
        invalidar_cache_metricas(log_path)


def test_invalidar_cache_metricas_global():
    """invalidar_cache_metricas() with no argument empties the whole cache."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write(SAMPLE_LOG)
        log_path = f.name
    try:
        primero = parsear_log(log_path)
        invalidar_cache_metricas()
        segundo = parsear_log(log_path)
        assert segundo is not primero
        assert segundo == primero
    finally:
        os.unlink(log_path)
        invalidar_cache_metricas(log_path)


def test_cache_log_inexistente_no_se_guarda():
    """A log that does not exist returns the empty one and does not pollute the cache."""
    ruta = os.path.join(tempfile.gettempdir(), "no_existe_dedalo_metricas.log")
    if os.path.exists(ruta):
        os.unlink(ruta)
    assert parsear_log(ruta)["iteraciones"] == []


if __name__ == "__main__":
    test_parsear_log_basico()
    test_parsear_log_vacio()
    test_parsear_log_solo_inicio()
    test_series_temporales()
    test_coste_con_coma_decimal()
    test_coste_por_iteracion()
    print("\n🎉 Todos los tests de metricas.py PASARON")


def test_ramas_del_motor_python_con_hora():
    """The Python engine names the run branch with the start time.

    Real branch: dedalo/2026-10-20_00-57-47 (and dedalo/tareas/<same>/t1).
    The regex only accepted dedalo/<date>/tN, so a real Python run showed
    0 iterations, 0 done and 0 cost in the GUI and in resumen_metricas.
    """
    log = """[2026-10-20 00:57:47] == DEDALO INICIADO (agente=opencode, dual=1, max_iter=3) ==
[2026-10-20 00:57:47] == Iteración 1: #1 Crear index.html (rama dedalo/tareas/2026-10-20_00-57-47/t1) | criterio: existe index.html ==
[2026-10-20 00:58:35] ✔ commit: dedalo: #1 Crear index.html
[2026-10-20 00:59:05] == Iteración 2: #2 Crear styles.css (rama dedalo/tareas/2026-10-20_00-57-47/t2) | criterio: existe styles.css ==
[2026-10-20 01:02:09] ✔ commit: dedalo: #2 Crear styles.css
[2026-10-20 01:02:09] == Iteración 3: #3 Crear README.md (rama dedalo/tareas/2026-10-20_00-57-47/t3) | criterio: existe README.md ==
[2026-10-20 01:03:38] ✔ commit: dedalo: #3 Crear README.md
[2026-10-20 01:03:41] == DEDALO FINALIZADO (iter=3, rama=dedalo/2026-10-20_00-57-47, costo≈1.50) ==
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        f.write(log)
        log_path = f.name
    try:
        result = parsear_log(log_path)
        assert [it["iter"] for it in result["iteraciones"]] == [1, 2, 3]
        assert result["resumen"]["total"] == 3
        assert result["resumen"]["hechas"] == 3
        assert result["resumen"]["pendientes"] == 0
        assert result["resumen"]["duracion_min"] == 5.9
    finally:
        os.unlink(log_path)
        invalidar_cache_metricas(log_path)
