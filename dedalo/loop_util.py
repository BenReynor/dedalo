#!/usr/bin/env python3
"""Utilities of the native loop (port of dedalo.sh's utilities section).
The loop lives today in plantillas_data/dedalo.sh; these helpers are the
base of the Python engine (dedalo.loop) that will replace it. Same log
format contract so the GUI consumes it the same way.

No PySide dependencies: the engine runs as a subprocess of the GUI (and
also by hand with `python -m dedalo.loop`).
"""

import json
import os
import subprocess
import time
from decimal import ROUND_HALF_UP, Decimal


def hora_texto():
    """Local time as "HH:MM" (`date +%H:%M`)."""
    return time.strftime("%H:%M")


def hora_limite(hasta):
    """True if the deadline has already passed (bash script string semantics).

    dedalo.sh does `[[ "$(date +%H:%M)" > "$HASTA" ]]`, which is a
    LEXICOGRAPHIC comparison: it works as a clock because "HH:MM" is
    padded to two digits. We keep the same comparison so the Python
    engine and bash behave identically (even an odd value like "9:00" is
    compared the same in both).
    """
    if not hasta:
        return False
    return hora_texto() > str(hasta)


def ahora_ms():
    """Epoch in milliseconds (portable version of `date +%s%3N`)."""
    return int(time.time() * 1000)


def logx(log, mensaje):
    """Append to `log` with a local timestamp, script format:
    `[YYYY-MM-DD HH:MM:SS] <mensaje>`."""
    directorio = os.path.dirname(log)
    if directorio:
        os.makedirs(directorio, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {mensaje}\n")


def alerta(voz, mensaje):
    """Desktop notice if VOZ=1 (notify-send + spd-say), without breaking
    anything if they are missing (same as the script's alerta())."""
    if str(voz) != "1":
        return
    for cmd in (("notify-send", "Dédalo", mensaje),
                ("spd-say", f"Dédalo: {mensaje}")):
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass


def _dec(valor):
    """Decimal from str/float/int with decimal exactness (for costs)."""
    if isinstance(valor, Decimal):
        return valor
    if valor in (None, ""):
        return Decimal(0)
    return Decimal(str(valor))


def d2(valor):
    """Formats a value as `%.2f` currency (half-up rounding).

    Equivalent to the `num awk 'printf "%.2f"'` contract of the script (awk
    rounds 12.345 -> 12.35, 0.005 -> 0.01)."""
    return format(_dec(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                  ".2f")


def suma_coste(actual, por_iter):
    """`actual + por_iter` with two decimals; equivalent to the
    `COSTO_TOTAL=num ... printf "%.2f"` line of dedalo.sh."""
    return d2(_dec(actual) + _dec(por_iter))


def incidencia(ruta, tipo, motivo, tarea="", iteracion=0, rama=""):
    """Append of an incident (JSONL) to the project's structured record.

    One line per failure/abort, independent of `progreso.log` (which is
    chronological prose): `{ts, iteracion, tarea, tipo, motivo, rama}`. Never
    crashes the loop on a write failure."""
    linea = json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "iteracion": int(iteracion),
        "tarea": tarea or "",
        "tipo": tipo,
        "motivo": motivo or "",
        "rama": rama or "",
    }, ensure_ascii=False)
    try:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass
