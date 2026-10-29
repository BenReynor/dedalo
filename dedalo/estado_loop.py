"""Live loop state for observers (GUI, MCP): `estado_loop.json`.

`progreso.log` is prose for humans; guessing the phase from it with regexes
missed whole phases and only worked for loops the GUI itself launched. The
engine now publishes a small JSON at every transition (task picked, agent,
gate, reviewer, commit, end) that any observer can read, whoever launched
the loop. Writes are atomic (tmp + os.replace) so a reader never sees half a
file. Failing to write never breaks the loop: the state is a convenience.
"""

import json
import os
import time

from . import rutas

ARCHIVO = "estado_loop.json"
FASES = ("Plan", "Agente", "Gate", "Revisor", "Commit")


def ruta(proyecto):
    return rutas.estado(proyecto, ARCHIVO)


def leer(proyecto):
    """The published state, or None if there is none (or it is unreadable)."""
    try:
        with open(ruta(proyecto), encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def _escribir(destino, datos):
    tmp = f"{destino}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
        for espera in (0, 0.05, 0.2):
            try:
                os.replace(tmp, destino)
                return
            except PermissionError:
                # Windows: a reader holding the file open blocks the rename.
                time.sleep(espera)
        os.replace(tmp, destino)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


class EstadoLoop:
    """Writer used by the engine; one instance per run."""

    def __init__(self, proyecto, max_iter, max_reintentos, agente="",
                 revisor=""):
        self._ruta = ruta(proyecto)
        self.datos = {
            "version": 1,
            "pid": os.getpid(),
            "estado": "arrancando",   # arrancando|corriendo|finalizado|abortado
            "motivo": "",
            "run_inicio": time.time(),
            "actualizado": time.time(),
            "agente": agente,
            "revisor": revisor,
            "max_iter": int(max_iter),
            "max_reintentos": int(max_reintentos),
            "iteracion": 0,
            "tarea": "",
            "criterio": "",
            "tarea_inicio": None,
            "intento": 0,
            "fase": "",
            "fase_inicio": None,
            "esperando_humano": False,
            # Outcome of each phase of the CURRENT attempt: ok|fail.
            "fases": {},
            # Attempts of the current task: [{intento, fase, resultado, dur}].
            "intentos": [],
            # Excerpt of what each phase produced (agent summary, gate
            # lines, reviewer verdict): what a pill click shows.
            "detalles": {},
            # Tasks this run closed: [{iteracion, tarea, resultado, intentos, dur}].
            "historial": [],
        }
        self._guardar()

    def _guardar(self):
        self.datos["actualizado"] = time.time()
        _escribir(self._ruta, self.datos)

    # ---- transitions ---------------------------------------------------

    def corriendo(self, agente="", revisor=""):
        self.datos["estado"] = "corriendo"
        if agente:
            self.datos["agente"] = agente
        if revisor:
            self.datos["revisor"] = revisor
        self._guardar()

    def nueva_tarea(self, iteracion, tarea, criterio=""):
        ahora = time.time()
        self.datos.update({
            "iteracion": int(iteracion), "tarea": tarea, "criterio": criterio,
            "tarea_inicio": ahora, "intento": 0, "intentos": [], "fases": {},
            "detalles": {}, "esperando_humano": False,
            "fase": "Plan", "fase_inicio": ahora,
        })
        self._guardar()

    def nuevo_intento(self, intento):
        self.datos["intento"] = int(intento)
        self.datos["fases"] = {}
        self._guardar()

    def fase(self, nombre, esperando_humano=False):
        if nombre not in FASES:
            return
        self.datos["fase"] = nombre
        self.datos["fase_inicio"] = time.time()
        self.datos["esperando_humano"] = bool(esperando_humano)
        self._guardar()

    def resultado(self, fase, ok, detalle=""):
        """Closes a phase of the current attempt (ok=False marks it red)."""
        if fase not in FASES:
            return
        inicio = self.datos.get("fase_inicio") or time.time()
        self.datos["fases"][fase] = "ok" if ok else "fail"
        self.datos["esperando_humano"] = False
        if detalle:
            self.datos["detalles"][fase] = detalle[-4000:]
        if not ok:
            self.datos["intentos"].append({
                "intento": self.datos["intento"], "fase": fase,
                "resultado": "fail", "detalle": detalle[:300],
                "dur": round(time.time() - inicio, 1)})
        self._guardar()

    def cerrar_tarea(self, resultado):
        """resultado: hecha|bloqueada."""
        inicio = self.datos.get("tarea_inicio") or time.time()
        self.datos["historial"].append({
            "iteracion": self.datos["iteracion"],
            "tarea": self.datos["tarea"],
            "resultado": resultado,
            "intentos": max(1, self.datos["intento"]),
            "fallos": [i["fase"] for i in self.datos["intentos"]],
            "dur": round(time.time() - inicio, 1),
        })
        self.datos.update({"fase": "", "fase_inicio": None,
                           "esperando_humano": False})
        self._guardar()

    def terminar(self, rc, motivo=""):
        self.datos["estado"] = "finalizado" if rc == 0 else "abortado"
        self.datos["motivo"] = motivo
        self.datos["rc"] = rc
        self.datos.update({"fase": "", "fase_inicio": None,
                           "esperando_humano": False})
        self._guardar()


class _Nulo:
    """Stand-in when no state is being published (every call is a no-op)."""

    def __getattr__(self, _nombre):
        return lambda *a, **k: None


NULO = _Nulo()
