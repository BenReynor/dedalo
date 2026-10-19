"""Metrics: parsing of progreso.log + metrics.jsonl → time series for charts.

Extracts from each iteration: task, state, duration, cost, gate, reviewer.
Adds real metrics (tokens, latency, real cost) from metrics.jsonl.
"""

import json
import os
import re
from datetime import datetime
from typing import Any

from . import rutas

# Timestamp format in log: [YYYY-MM-DD HH:MM:SS]
TIMESTAMP_RE = r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]"

# Real script format: [TS] == Iteración N: TAREA (rama dedalo/.../tN) ==
# The branch may be dedalo/FECHA/tN (legacy) or dedalo/tareas/FECHA/tN.
# And the script appends " | criterio: <texto>" when the plan.md task brings it
# (required by the template). That suffix is optional here: without it, the
# regex required ") ==" right after the branch, did NOT match any normal
# iteration and the panel lost the total, the done count and the cost.
LINEA_ITER_NUEVO = re.compile(
    TIMESTAMP_RE
    + r" == Iteración (\d+): (.+?) \(rama dedalo/(?:tareas/)?\d{4}-\d{2}-\d{2}/t(\d+)\)"
    + r"(?: \| criterio:.*?)? =="
)
# Tolerated alternative format: [TS] [N/MAX] TAREA -> dedalo/.../tN
LINEA_ITER_LEGACY = re.compile(
    TIMESTAMP_RE + r" \[(\d+)/(\d+)\] (.+?) -> dedalo/(?:tareas/)?\d{4}-\d{2}-\d{2}/t(\d+)"
)
# Iteration closing lines after the timestamp (commit / completada / BLOQUEADA)
LINEA_ESTADO = re.compile(TIMESTAMP_RE + r"\s*(?:✔|✗)?\s*(.+)")
LINEA_COSTE = re.compile(
    TIMESTAMP_RE + r" (?:Costo estimado acumulado:|💰 Costo estimado acumulado:)\s*([\d.,]+)\s*USD"
)
# Exact cost per iteration (log identical to the script's COSTO_ITER_ACTUAL variable)
LINEA_COSTE_ITER = re.compile(
    TIMESTAMP_RE + r" Costo iteración (\d+):\s*([\d.,]+)\s*USD"
)
LINEA_FIN = re.compile(
    TIMESTAMP_RE + r" == DEDALO FINALIZADO"
)


def _diff_seg(fecha_ini: str, fecha_fin: str) -> int:
    """Seconds between two timestamps `YYYY-MM-DD HH:MM:SS` (0 if they do not parse)."""
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        a = datetime.strptime(fecha_ini, fmt)
        b = datetime.strptime(fecha_fin, fmt)
        return max(0, int((b - a).total_seconds()))
    except (ValueError, TypeError):
        return 0


def _inicio_iteracion(linea: str):
    """Returns (date, number, task) if the line opens an iteration, else None."""
    m = LINEA_ITER_NUEVO.search(linea)
    if m:
        return m.group(1), int(m.group(2)), m.group(3).strip()
    m = LINEA_ITER_LEGACY.search(linea)
    if m:
        return m.group(1), int(m.group(5)), m.group(4).strip()
    return None


# Parse cache by (size, mtime_ns): the panel refreshes every 5 s and used to
# reparse the whole log on every tick (linear cost with log size).
# The cached dict is shared: callers must treat it as read-only.
_CACHE_LOG: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


def invalidar_cache_metricas(ruta_log: str | None = None) -> None:
    """Invalidates the parse cache (everything, or only `ruta_log`)."""
    if ruta_log is None:
        _CACHE_LOG.clear()
    else:
        _CACHE_LOG.pop(ruta_log, None)


def parsear_log(ruta_log: str) -> dict[str, Any]:
    """Parses progreso.log and returns time series and table.

    Result cached by (size, mtime): if the file has not changed since the
    last call, returns the already-parsed dict without re-reading it. The returned
    dict is shared with the cache: treat it as read-only.
    """
    try:
        st = os.stat(ruta_log)
        clave = (st.st_size, st.st_mtime_ns)
    except OSError:
        return _vacío()
    guardado = _CACHE_LOG.get(ruta_log)
    if guardado is not None and guardado[0] == clave:
        return guardado[1]
    datos = _parsear_log(ruta_log)
    _CACHE_LOG[ruta_log] = (clave, datos)
    return datos


def _parsear_log(ruta_log: str) -> dict[str, Any]:
    """Parses progreso.log from scratch (no cache). See `parsear_log`.

    Returns:
        {
            "iteraciones": [...],           # list of dicts per iteration
            "series": {
                "tareas_hora": [(timestamp, accumulated)],
                "coste_acum": [(timestamp, cost)],
                "gate": [(timestamp, ok, fail)],
                "revisor": [(timestamp, pass_, fail)],
            },
            "resumen": {
                "total": int,
                "hechas": int,
                "bloqueadas": int,
                "pendientes": int,
                "coste_total": float,
                "duracion_min": float,
            }
        }
    """
    if not os.path.isfile(ruta_log):
        return _vacío()

    with open(ruta_log, encoding="utf-8", errors="replace") as f:
        lineas = f.readlines()

    iteraciones = []
    iter_actual = None
    ultima_completada = None  # To assign cost after completing
    coste_acum = 0.0
    coste_por_iter: dict[int, float] = {}  # Exact cost per iteration (new format)
    gate_ok = gate_fail = 0
    rev_pass = rev_fail = 0

    for linea in lineas:
        linea = linea.rstrip("\n")

        # Start of iteration
        m = _inicio_iteracion(linea)
        if m:
            if iter_actual:
                iteraciones.append(iter_actual)
            fecha, num, tarea = m
            iter_actual = {
                "timestamp": fecha,
                "iter": num,
                "tarea": tarea,
                "estado": "en_progreso",
                "duracion_s": 0,
                "coste_usd": 0.0,
                "gate": "pendiente",
                "revisor": "pendiente",
            }
            continue

        # Final task state (commit or blocked)
        m = LINEA_ESTADO.search(linea)
        if m and iter_actual:
            fecha, resto = m.groups()
            bajo = resto.lower()
            es_cierre = ("commit" in bajo or "completada" in bajo
                         or "bloqueada" in bajo)
            if es_cierre:
                if "commit" in bajo or "completada" in bajo:
                    iter_actual["estado"] = "hecha"
                    iter_actual["gate"] = "ok"
                    iter_actual["revisor"] = "pass"
                elif "bloqueada" in bajo:
                    iter_actual["estado"] = "bloqueada"
                iter_actual["duracion_s"] = _diff_seg(iter_actual["timestamp"], fecha)
                iteraciones.append(iter_actual)
                ultima_completada = iter_actual  # Save to assign cost later
                iter_actual = None
                continue

        # Exact cost per iteration (assign to its open iteration)
        m = LINEA_COSTE_ITER.search(linea)
        if m:
            num = int(m.group(2))
            costo = float(m.group(3).replace(",", "."))
            coste_por_iter[num] = costo
            if iter_actual and iter_actual["iter"] == num:
                iter_actual["coste_usd"] = costo
            continue

        # Accumulated cost - assign to the last completed one (legacy format only,
        # when there is no exact per-iteration cost to override it)
        m = LINEA_COSTE.search(linea)
        if m:
            coste_acum = float(m.group(2).replace(",", "."))
            if not coste_por_iter:
                if ultima_completada:
                    ultima_completada["coste_usd"] = coste_acum
                elif iter_actual:
                    iter_actual["coste_usd"] = coste_acum
            continue

        mayus = linea.upper()
        # Gate
        if "GATE OK" in mayus or "✅" in linea:
            gate_ok += 1
            if iter_actual:
                iter_actual["gate"] = "ok"
        elif "GATE" in mayus and ("FAIL" in mayus or "FALL" in mayus):
            gate_fail += 1
            if iter_actual:
                iter_actual["gate"] = "fail"

        # Revisor
        if "VERDICT: PASS" in linea or "REVISOR PASS" in linea:
            rev_pass += 1
            if iter_actual:
                iter_actual["revisor"] = "pass"
        elif "VERDICT: FAIL" in linea or "REVISOR FAIL" in linea:
            rev_fail += 1
            if iter_actual:
                iter_actual["revisor"] = "fail"

    # Last iteration if it was left open
    if iter_actual:
        iteraciones.append(iter_actual)

    # Build time series
    tareas_hora = []
    coste_series = []
    gate_series = []
    rev_series = []

    hechas_acum = 0
    coste_acumulado = 0.0
    coste_por_iter_total = 0.0
    for it in iteraciones:
        ts = it["timestamp"]
        if it["estado"] == "hecha":
            hechas_acum += 1
        tareas_hora.append((ts, hechas_acum))
        # If there is an exact per-iteration cost, accumulate it into the series; if not, use the
        # assigned value (legacy format already accumulated).
        if it["iter"] in coste_por_iter:
            coste_acumulado += coste_por_iter[it["iter"]]
            coste_por_iter_total = coste_acumulado
            serie_coste = round(coste_acumulado, 2)
        else:
            serie_coste = it.get("coste_usd", 0.0)
        coste_series.append((ts, serie_coste))
        gate_val = 1 if it.get("gate") == "ok" else (0 if it.get("gate") == "fail" else None)
        rev_val = 1 if it.get("revisor") == "pass" else (0 if it.get("revisor") == "fail" else None)
        gate_series.append((ts, gate_val))
        rev_series.append((ts, rev_val))

    hechas = sum(1 for it in iteraciones if it["estado"] == "hecha")
    bloqueadas = sum(1 for it in iteraciones if it["estado"] == "bloqueada")
    total = len(iteraciones)

    # Enrich with real metrics (tokens, latency, real cost, model) from metrics.jsonl
    iteraciones = _enriquecer_con_metricas_reales(iteraciones, os.path.dirname(ruta_log))

    # Recalculate coste_total using the real cost if available
    coste_total_real = sum(it.get("costo_real_usd", 0.0) for it in iteraciones)
    coste_total = coste_total_real if coste_total_real > 0 else (coste_por_iter_total if coste_por_iter else coste_acum)

    return {
        "iteraciones": iteraciones,
        "series": {
            "tareas_hora": tareas_hora,
            "coste_acum": coste_series,
            "gate": gate_series,
            "revisor": rev_series,
        },
        "resumen": {
            "total": total,
            "hechas": hechas,
            "bloqueadas": bloqueadas,
            "pendientes": max(0, total - hechas - bloqueadas),
            "coste_total": coste_total,
            "duracion_min": 0.0,  # Computed in the UI if there are timestamps
        },
    }


def _leer_metrics_jsonl(ruta_proyecto: str) -> list[dict]:
    """Reads metrics.jsonl and returns a list of dicts with real metrics per agent call."""
    ruta = rutas.metrics(ruta_proyecto)
    if not os.path.isfile(ruta):
        return []
    out = []
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    out.append(json.loads(linea))
                except json.JSONDecodeError:
                    pass
    except (OSError, json.JSONDecodeError):
        pass
    return out


def _enriquecer_con_metricas_reales(iteraciones: list[dict], ruta_proyecto: str) -> list[dict]:
    """Adds tokens, latency, real cost and model to each iteration from metrics.jsonl."""
    metricas = _leer_metrics_jsonl(ruta_proyecto)
    if not metricas:
        return iteraciones
    # Group metrics by iteration
    by_iter: dict[int, list[dict]] = {}
    for m in metricas:
        it = m.get("iter")
        if isinstance(it, int):
            by_iter.setdefault(it, []).append(m)
    for it in iteraciones:
        num = it.get("iter")
        if not isinstance(num, int):
            continue
        metricas_it = by_iter.get(num, [])
        if not metricas_it:
            continue
        # Sum tokens and real cost of all the calls in that iteration
        tokens_in = sum(m.get("tokens_in", 0) for m in metricas_it)
        tokens_out = sum(m.get("tokens_out", 0) for m in metricas_it)
        costo_real = sum(m.get("costo_usd", 0.0) for m in metricas_it)
        dur_ms = sum(m.get("dur_ms", 0) for m in metricas_it)
        modelos = sorted({m.get("modelo", "") for m in metricas_it if m.get("modelo")})
        agentes = sorted({m.get("agente", "") for m in metricas_it if m.get("agente")})
        it["tokens_in"] = tokens_in
        it["tokens_out"] = tokens_out
        it["tokens_total"] = tokens_in + tokens_out
        it["costo_real_usd"] = round(costo_real, 6)
        it["duracion_ms"] = dur_ms
        it["duracion_s"] = round(dur_ms / 1000, 1)
        it["modelos"] = ", ".join(modelos) if modelos else ""
        it["agentes"] = ", ".join(agentes) if agentes else ""
        # Prefer real cost if it exists
        if costo_real > 0:
            it["costo_usd_real"] = round(costo_real, 4)
    return iteraciones


def _vacío() -> dict[str, Any]:
    return {
        "iteraciones": [],
        "series": {
            "tareas_hora": [],
            "coste_acum": [],
            "gate": [],
            "revisor": [],
        },
        "resumen": {
            "total": 0,
            "hechas": 0,
            "bloqueadas": 0,
            "pendientes": 0,
            "coste_total": 0.0,
            "duracion_min": 0.0,
        },
    }
