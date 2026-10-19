"""Layout of the files Dédalo owns inside a project.

Dédalo keeps its own files under `.dedalo/` so the project root stays clean:

    proyecto/
    ├── plan.md  lecciones.md  CONTEXTO.md   # project content (tracked)
    ├── .gitignore
    └── .dedalo/
        ├── scripts/   dedalo.sh  gate.sh  mapear.sh  gate_checks/
        ├── estado/    progreso.log  metrics.jsonl  incidencias.jsonl
        │              mapeo.txt  endpoints.txt
        └── review/    diff.txt ...

Projects installed with Dédalo < 2.1 keep their files at the root. The
resolvers use the legacy location while the project has no `.dedalo/` directory
and the new one after `asegurar()` migrates it, so both layouts work and a
migration never breaks an in-flight run.
"""

import os
import shutil

DIR = ".dedalo"
SCRIPTS = "scripts"
ESTADO = "estado"
REVIEW = "review"

# Framework files that used to live at the project root.
SCRIPTS_LEGACY = ("dedalo.sh", "gate.sh", "mapear.sh", "gate_checks")
ESTADO_LEGACY = ("progreso.log", "metrics.jsonl", "incidencias.jsonl",
                 "mapeo.txt", "endpoints.txt")
REVIEW_LEGACY = ".dedalo_review"

# Project content: always at the root, tracked in git.
PROYECTO = ("plan.md", "lecciones.md", "CONTEXTO.md")


def dir_dedalo(proyecto):
    return os.path.join(proyecto, DIR)


def dir_scripts(proyecto):
    return os.path.join(proyecto, DIR, SCRIPTS)


def dir_estado(proyecto):
    return os.path.join(proyecto, DIR, ESTADO)


def dir_review(proyecto):
    if es_nuevo(proyecto):
        return os.path.join(proyecto, DIR, REVIEW)
    return os.path.join(proyecto, REVIEW_LEGACY)


def es_nuevo(proyecto):
    """True if the project already uses the `.dedalo/` layout."""
    return os.path.isdir(dir_dedalo(proyecto))


def script(proyecto, nombre):
    """Path of a framework script (dedalo.sh, gate.sh, mapear.sh)."""
    if es_nuevo(proyecto):
        return os.path.join(dir_scripts(proyecto), nombre)
    return os.path.join(proyecto, nombre)


def gate_sh(proyecto):
    return script(proyecto, "gate.sh")


def mapear_sh(proyecto):
    return script(proyecto, "mapear.sh")


def dedalo_sh(proyecto):
    return script(proyecto, "dedalo.sh")


def gate_checks(proyecto):
    if es_nuevo(proyecto):
        return os.path.join(dir_scripts(proyecto), "gate_checks")
    return os.path.join(proyecto, "gate_checks")


def estado(proyecto, nombre):
    """Path of a run artifact (progreso.log, metrics.jsonl, mapeo.txt...)."""
    if es_nuevo(proyecto):
        return os.path.join(dir_estado(proyecto), nombre)
    return os.path.join(proyecto, nombre)


def log(proyecto):
    return estado(proyecto, "progreso.log")


def metrics(proyecto):
    return estado(proyecto, "metrics.jsonl")


def incidencias(proyecto):
    return estado(proyecto, "incidencias.jsonl")


def mapeo(proyecto):
    return estado(proyecto, "mapeo.txt")


def endpoints(proyecto):
    return estado(proyecto, "endpoints.txt")


def proyecto_archivo(proyecto, nombre):
    """Project-owned file (plan.md, lecciones.md, CONTEXTO.md, .gitignore)."""
    return os.path.join(proyecto, nombre)


def _mover(viejo, nuevo):
    """Moves `viejo` to `nuevo` if needed. Never overwrites. Returns True if moved."""
    if not os.path.exists(viejo) or os.path.exists(nuevo):
        return False
    try:
        os.makedirs(os.path.dirname(nuevo), exist_ok=True)
        shutil.move(viejo, nuevo)
    except (OSError, shutil.Error):
        return False
    return True


def _fusionar(viejo, nuevo):
    """Moves the contents of `viejo` into `nuevo` (never overwrites)."""
    try:
        nombres = os.listdir(viejo)
    except OSError:
        return False
    for nombre in nombres:
        _mover(os.path.join(viejo, nombre), os.path.join(nuevo, nombre))
    try:
        os.rmdir(viejo)
    except OSError:
        pass
    return True


def asegurar(proyecto):
    """Creates the `.dedalo/` tree and migrates legacy files.

    Idempotent: safe to call every time a project is opened. Returns a dict
    with `migrados` (names moved from the root) and `creados` (names of the
    files created empty when they did not exist).
    """
    migrados = []
    for nombre in SCRIPTS_LEGACY:
        viejo = os.path.join(proyecto, nombre)
        nuevo = os.path.join(dir_scripts(proyecto), nombre)
        if _mover(viejo, nuevo):
            migrados.append(nombre)
    for nombre in ESTADO_LEGACY:
        viejo = os.path.join(proyecto, nombre)
        nuevo = os.path.join(dir_estado(proyecto), nombre)
        if _mover(viejo, nuevo):
            migrados.append(nombre)
    viejo_review = os.path.join(proyecto, REVIEW_LEGACY)
    nuevo_review = os.path.join(proyecto, DIR, REVIEW)
    if os.path.isdir(viejo_review):
        if os.path.isdir(nuevo_review):
            _fusionar(viejo_review, nuevo_review)
        elif _mover(viejo_review, nuevo_review):
            pass
        migrados.append(REVIEW_LEGACY)
    for ruta in (dir_scripts(proyecto), dir_estado(proyecto), nuevo_review):
        os.makedirs(ruta, exist_ok=True)
    creados = []
    if not os.path.exists(log(proyecto)):
        try:
            with open(log(proyecto), "w", encoding="utf-8") as f:
                f.write("# progreso.log — Dédalo\n")
        except OSError:
            pass
        else:
            creados.append("progreso.log")
    return {"migrados": migrados, "creados": creados}
