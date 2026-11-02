"""Data model for plan.md: reading, counting and saving tasks.

Separates the plan format from the UI so that counting and saving are
consistent and testable (same criterion used by the dedalo.sh script:
task `- [ ]`, done `- [x]`, blocked `- [B]`).
"""

import os
import re

ESTADOS = {" ": "pendiente", "x": "hecha", "b": "bloqueada"}

_LINEA_TAREA = re.compile(r"^\s*-\s+\[(.)\]\s*(.*)$")


class Plan:
    def __init__(self, ruta):
        self.ruta = ruta
        self.texto = ""

    def existe(self):
        return os.path.isfile(self.ruta)

    def cargar(self):
        try:
            with open(self.ruta, encoding="utf-8") as f:
                self.texto = f.read()
        except OSError:
            self.texto = ""
        return self.texto

    def guardar(self, texto):
        with open(self.ruta, "w", encoding="utf-8") as f:
            f.write(texto)
        self.texto = texto

    @property
    def tareas(self):
        """List of dicts {linea, estado, texto}, in file order."""
        out = []
        for i, linea in enumerate(self.texto.splitlines(), start=1):
            m = _LINEA_TAREA.match(linea)
            if not m:
                continue
            estado = m.group(1).lower()
            out.append({
                "linea": i,
                "estado": ESTADOS.get(estado, "pendiente"),
                "texto": m.group(2).strip(),
            })
        return out

    def conteo(self):
        """Returns (pending, done, blocked)."""
        pend = hecho = bloq = 0
        for t in self.tareas:
            if t["estado"] == "pendiente":
                pend += 1
            elif t["estado"] == "hecha":
                hecho += 1
            elif t["estado"] == "bloqueada":
                bloq += 1
        return pend, hecho, bloq

    def marcar_tarea(self, texto, estado):
        """Marks the pending task whose line is exactly `- [ ] <texto>`.

        The loop remembers which task it started; marking "the first pending"
        marked the wrong one when plan.md changed during the iteration (a task
        unblocked or inserted above). Returns False, touching nothing, when
        that task is no longer pending.
        """
        objetivo = "- [ ] " + (texto or "")
        return self._marcar_linea(
            lambda linea: linea.rstrip("\r\n") == objetivo, estado)

    def marcar_primera(self, estado):
        """Marks the FIRST pending task with `estado` (`x`/`B`).

        Same semantics as `marcar_plan` in dedalo.sh: only the first
        line that starts (column 0) with `- [ ]`. Atomic write (temporary
        file in the same directory + os.replace) so the plan is not left
        half-written if the process dies mid-write. Returns True if it
        touched some task.
        """
        return self._marcar_linea(lambda linea: linea.startswith("- [ ]"),
                                  estado)

    def _marcar_linea(self, coincide, estado):
        """Marks the first line matching `coincide` (atomic write)."""
        marca = "B" if str(estado).upper() == "B" else "x"
        hecha = False
        lineas = []
        for linea in self.texto.splitlines(keepends=True):
            if not hecha and coincide(linea):
                lineas.append(linea.replace("- [ ]", f"- [{marca}]", 1))
                hecha = True
            else:
                lineas.append(linea)
        if not hecha:
            return False
        tmp = os.path.join(
            os.path.dirname(self.ruta),
            f".plan.md.tmp.{os.getpid()}")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("".join(lineas))
            os.replace(tmp, self.ruta)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self.texto = "".join(lineas)
        return True
