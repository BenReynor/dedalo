"""Installation of the scripts/templates needed in a project."""

import filecmp
import os
import re
import shutil
import subprocess
from datetime import datetime

from . import rutas

PLANTILLA_DIR = os.path.join(os.path.dirname(__file__), "plantillas_data")
PLANTILLAS_DIR = os.path.join(PLANTILLA_DIR, "plantillas")
SCRIPTS = ("dedalo.sh", "gate.sh", "mapear.sh")
MEMORIA = ("plan.md", "lecciones.md", "CONTEXTO.md")
ARCHIVOS = SCRIPTS + MEMORIA
GATE_CHECKS_DIR = "gate_checks"
# Checks shared by every selectable template: they are copied from the default
# gate_checks/ (the criterion judge is generic, not stack-specific).
COMMON_CHECKS = ("98_criterio.py",)
MARCADOR = "plantilla"
GATE_CHECKS = tuple(
    # Relative names ALWAYS with "/": the listing from `instalar()` (which the GUI
    # shows and the test compares) must not depend on the OS slash.
    os.path.relpath(os.path.join(ruta, f), PLANTILLA_DIR).replace("\\", "/")
    for ruta, _dirs, archivos in os.walk(os.path.join(PLANTILLA_DIR, GATE_CHECKS_DIR))
    for f in archivos
    # The .py files are the portable port (used on Windows, without bash); the .sh
    # ones are preferred on Unix. Both are always copied into the project.
    if f.endswith((".sh", ".py"))
)


def quitar(ruta):
    """Deletes the files the app installed. Returns the deleted ones.

    Only touches the framework scripts, gate_checks/, plan.md, lecciones.md,
    CONTEXTO.md and the run state under `.dedalo/`: never the rest of the
    project. Legacy (root) layouts are cleaned too, so removing an old project
    from the list keeps working.
    """
    eliminados = []
    for nombre in SCRIPTS:
        for destino in (os.path.join(ruta, nombre),
                        os.path.join(rutas.dir_scripts(ruta), nombre)):
            if os.path.isfile(destino):
                os.remove(destino)
                if nombre not in eliminados:
                    eliminados.append(nombre)
    for nombre in MEMORIA:
        destino = os.path.join(ruta, nombre)
        if os.path.exists(destino):
            os.remove(destino)
            eliminados.append(nombre)
    for dir_checks in (rutas.gate_checks(ruta),
                       os.path.join(ruta, GATE_CHECKS_DIR)):
        if os.path.isdir(dir_checks):
            shutil.rmtree(dir_checks)
            if GATE_CHECKS_DIR + "/" not in eliminados:
                eliminados.append(GATE_CHECKS_DIR + "/")
    # Run state (new layout) and anything left at the root of an old project
    for directorio in (rutas.dir_estado(ruta), rutas.dir_review(ruta),
                       rutas.dir_fichas(ruta)):
        if os.path.isdir(directorio):
            shutil.rmtree(directorio, ignore_errors=True)
    for nombre in ("progreso.log", "metrics.jsonl", "incidencias.jsonl",
                   "mapeo.txt", "endpoints.txt", ".dedalo_review"):
        destino = os.path.join(ruta, nombre)
        if os.path.isdir(destino):
            shutil.rmtree(destino, ignore_errors=True)
        elif os.path.exists(destino):
            os.remove(destino)
    # Remove the framework directories (then .dedalo/) only if they are empty:
    # never delete anything the user put there.
    for directorio in (rutas.dir_scripts(ruta), rutas.dir_estado(ruta),
                       os.path.join(ruta, rutas.DIR, rutas.REVIEW),
                       rutas.dir_fichas(ruta)):
        try:
            os.rmdir(directorio)
        except OSError:
            pass
    dedalo_dir = rutas.dir_dedalo(ruta)
    if os.path.isdir(dedalo_dir):
        try:
            os.rmdir(dedalo_dir)
        except OSError:
            pass
    return eliminados


def _es_repo_git(ruta):
    return os.path.isdir(os.path.join(ruta, ".git"))


def inicializar_git(ruta):
    """Initializes a git repo if the project does not have one.

    Dedalo works 100% with branches/commits; without a repo it aborts on the first
    `git checkout` (as happened with Proyecto_nuevo). This:
      1. `git init -b master` (base branch of the dedalo.sh script).
      2. Initial commit of the files so that the branch exists.

    Returns a dict {repo: "creado"|"ya-existia"|"no-disponible", archivos: n}.
    Not available = git not installed or identity not configured (touches nothing).
    """
    if _es_repo_git(ruta):
        return {"repo": "ya-existia", "archivos": 0}
    try:
        git = subprocess.run(["git", "init", "-b", "master"], cwd=ruta,
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return {"repo": "no-disponible", "archivos": 0}
    if git.returncode != 0:
        return {"repo": "no-disponible", "archivos": 0}
    try:
        subprocess.run(["git", "add", "-A"], cwd=ruta, capture_output=True,
                       text=True, timeout=30)
        # --allow-empty: if the project has no files of its own (only the
        # framework ones, which the .gitignore excludes), master is left with an empty
        # commit so that dedalo can branch on top of it.
        cm = subprocess.run(["git", "commit", "-q", "--allow-empty", "-m",
                             "init: dedalo (plantillas instaladas)"],
                            cwd=ruta, capture_output=True, text=True,
                            timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return {"repo": "creado", "archivos": 0}
    # The commit fails if there is no git identity configured or nothing to commit
    return {"repo": "creado", "archivos": 0 if cm.returncode != 0 else _git_archivos(ruta)}


def _git_archivos(ruta):
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ruta, capture_output=True,
                             text=True, timeout=30)
        return len([linea for linea in out.stdout.splitlines() if linea.strip()])
    except (OSError, subprocess.TimeoutExpired):
        return 0


def _desactualizados(ruta):
    """Framework scripts that differ between template and project.

    Only the SCRIPTS (dedalo.sh, gate.sh, mapear.sh) are compared/renewed:
    they are support code that must follow the template version.

    plan.md, lecciones.md, CONTEXTO.md and gate_checks/*.sh are NOT compared: they
    are user content (their tasks, their memory, their context and their
    verifications). They are created if missing, but never overwritten with the
    template.
    """
    diff = []
    for nombre in SCRIPTS:
        src = os.path.join(PLANTILLA_DIR, nombre)
        dst = rutas.script(ruta, nombre)
        if os.path.exists(dst) and os.path.exists(src):
            if not filecmp.cmp(src, dst, shallow=False):
                diff.append(nombre)
    return diff


def _destino(ruta, nombre):
    """Where a template goes: scripts and checks under `.dedalo/`, rest at root."""
    if nombre in SCRIPTS:
        return os.path.join(rutas.dir_scripts(ruta), nombre)
    if nombre.startswith(GATE_CHECKS_DIR + "/"):
        return os.path.join(rutas.dir_scripts(ruta), nombre)
    return os.path.join(ruta, nombre)


def disponibles():
    """Names of the selectable gate templates (e.g. web, python, node...)."""
    if not os.path.isdir(PLANTILLAS_DIR):
        return []
    return sorted(
        d for d in os.listdir(PLANTILLAS_DIR)
        if os.path.isdir(os.path.join(PLANTILLAS_DIR, d, GATE_CHECKS_DIR))
    )


def _normalizar_plantillas(valor):
    """Normalizes a template selection (str/list, comma or space separated).

    Unknown names are ignored; duplicates are removed keeping order. This is
    what makes templates accumulative: `"rust, go"` enables both.
    """
    if not valor:
        return []
    if isinstance(valor, str):
        partes = re.split(r"[,\s]+", valor)
    else:
        partes = list(valor)
    disponibles_ = set(disponibles())
    elegidas = []
    for parte in partes:
        nombre = str(parte).strip()
        if nombre in disponibles_ and nombre not in elegidas:
            elegidas.append(nombre)
    return elegidas


def plantillas_de(ruta):
    """Templates chosen for a project (persisted marker), in order."""
    marca = os.path.join(rutas.dir_dedalo(ruta), MARCADOR)
    try:
        with open(marca, encoding="utf-8") as f:
            return _normalizar_plantillas(f.read())
    except OSError:
        return []


def plantilla_de(ruta):
    """Comma-joined selection for a project, or None (kept for compatibility)."""
    return ",".join(plantillas_de(ruta)) or None


def _escribir_marcador(ruta, nombres):
    """Persists the selection so reopening does not add the defaults."""
    marca = os.path.join(rutas.dir_dedalo(ruta), MARCADOR)
    os.makedirs(os.path.dirname(marca), exist_ok=True)
    with open(marca, "w", encoding="utf-8") as f:
        f.write("\n".join(nombres) + "\n")


def _checks_de_plantillas(nombres):
    """(destination, source) pairs for the selected templates.

    Check names are suffixed with the template (`03_test_go.py`,
    `03_test_rust.py`) so several stacks can coexist without overwriting each
    other. Common checks (98_criterio) are copied once, unprefixed.
    """
    pares = []
    for nombre in nombres:
        directorio = os.path.join(PLANTILLAS_DIR, nombre, GATE_CHECKS_DIR)
        if not os.path.isdir(directorio):
            continue
        for f in sorted(os.listdir(directorio)):
            if not f.endswith((".sh", ".py")) or f.startswith("_"):
                continue
            base, ext = os.path.splitext(f)
            destino = f"{GATE_CHECKS_DIR}/{base}_{nombre}{ext}"
            pares.append((destino, os.path.join(directorio, f)))
    comunes = [c for c in COMMON_CHECKS
               if os.path.isfile(os.path.join(PLANTILLA_DIR, GATE_CHECKS_DIR, c))]
    pares += [(f"{GATE_CHECKS_DIR}/{c}",
               os.path.join(PLANTILLA_DIR, GATE_CHECKS_DIR, c))
              for c in comunes]
    return pares


def instalar(ruta, plantilla=None):
    """Copies the templates (scripts + gate_checks) that are missing.

    `plantilla` selects one or more gate templates by name (see
    `disponibles()`), either as a list or as a comma/space separated string:
    `"rust,go"`. Selections accumulate, so a project that uses several stacks
    enables several templates. If it is omitted, the project's persisted choice
    is used and, failing that, the default (Python/backend) checks.

    Projects installed with an older version are migrated first: their
    framework files move from the project root into `.dedalo/`. Returns the
    project-relative paths of the created files.
    """
    if plantilla is None:
        seleccion = plantillas_de(ruta)
    else:
        seleccion = _normalizar_plantillas(plantilla)
    if seleccion:
        pares = _checks_de_plantillas(seleccion)
        nombres = list(ARCHIVOS) + [d for d, _ in pares] + [".gitignore"]
        origenes = dict(pares)
    else:
        nombres = list(ARCHIVOS) + list(GATE_CHECKS) + [".gitignore"]
        origenes = {}
    habia_log = (os.path.exists(os.path.join(ruta, "progreso.log"))
                 or os.path.exists(os.path.join(rutas.dir_estado(ruta),
                                                "progreso.log")))
    habia_gitignore = os.path.exists(os.path.join(ruta, ".gitignore"))
    rutas.asegurar(ruta)
    # Also here (not only when the GUI closes): MCP installs and any other
    # caller need the framework excluded from git before inicializar_git()
    # commits the project, or `ruff check .` would lint the .py checks.
    asegurar_gitignore(ruta)
    log = rutas.log(ruta)
    creados = []
    if not habia_gitignore and os.path.exists(os.path.join(ruta, ".gitignore")):
        creados.append(".gitignore")
    if not habia_log and os.path.exists(log):
        creados.append(os.path.relpath(log, ruta).replace("\\", "/"))
    for nombre in nombres:
        destino = _destino(ruta, nombre)
        if not os.path.exists(destino):
            origen = origenes.get(nombre, os.path.join(PLANTILLA_DIR, nombre))
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            shutil.copy2(origen, destino)
            if nombre.endswith(".sh"):
                os.chmod(destino, 0o755)
            creados.append(os.path.relpath(destino, ruta).replace("\\", "/"))
    if seleccion:
        _escribir_marcador(ruta, seleccion)
    return creados


def _bloque_framework_gitignore():
    """Lines of the template .gitignore that exclude the framework."""
    ruta = os.path.join(PLANTILLA_DIR, ".gitignore")
    with open(ruta, encoding="utf-8") as f:
        lineas = f.read().splitlines()
    bloque = []
    for linea in lineas:
        if linea.startswith("# Entorno"):
            break
        bloque.append(linea)
    return "\n".join(bloque).strip() + "\n"


def asegurar_gitignore(ruta):
    """Ensures the project's .gitignore excludes the framework.

    If it does not exist, the full template is copied. If it already exists (the
    user's own entries), ONLY the framework block is ADDED, without touching the rest
    and without duplicating it if it is already there. Returns True if it was modified.
    """
    destino = os.path.join(ruta, ".gitignore")
    if not os.path.exists(destino):
        shutil.copy2(os.path.join(PLANTILLA_DIR, ".gitignore"), destino)
        return True
    with open(destino, encoding="utf-8") as f:
        contenido = f.read()
    lineas = contenido.splitlines()
    # Projects installed before the `.dedalo/` layout already have the old
    # per-file block (with its "Dédalo:" header). Only the new directory entry
    # matters now, so check the actual pattern instead of the header.
    if any(linea.strip() in (".dedalo/", ".dedalo") for linea in lineas):
        return False
    inicio = next((i for i, linea in enumerate(lineas)
                   if linea.startswith("# Dédalo:")), None)
    if inicio is not None:
        # Replace the old framework block (plan.md/lecciones.md/CONTEXTO.md
        # were ignored back then; they are project content now) and keep the
        # user's own entries and the environment block untouched.
        fin = next((j for j in range(inicio + 1, len(lineas))
                    if lineas[j].startswith("# Entorno")), len(lineas))
        bloque = _bloque_framework_gitignore().rstrip("\n").splitlines()
        lineas[inicio:fin] = bloque + [""]
        with open(destino, "w", encoding="utf-8") as f:
            f.write("\n".join(lineas).rstrip("\n") + "\n")
        return True
    with open(destino, "a", encoding="utf-8") as f:
        if not contenido.endswith("\n"):
            f.write("\n")
        f.write("\n" + _bloque_framework_gitignore())
    return True


def quitar_framework_del_git(ruta):
    """Removes the framework files from git tracking (without deleting them).

    The project keeps the scripts, gate_checks/ and the run state on disk
    (dedalo needs them), but they are no longer in the repo. plan.md,
    lecciones.md and CONTEXTO.md are project content and stay tracked.
    Returns the list of files that git stopped tracking.
    """
    if not _es_repo_git(ruta):
        return []
    patrones = ([rutas.DIR, GATE_CHECKS_DIR] + list(SCRIPTS)
                + ["progreso.log", "metrics.jsonl", "incidencias.jsonl",
                   "mapeo.txt", "endpoints.txt", ".dedalo_review"])
    try:
        out = subprocess.run(
            ["git", "ls-files"] + patrones, cwd=ruta, capture_output=True,
            text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    trackeados = [linea for linea in out.stdout.splitlines() if linea.strip()]
    if not trackeados:
        return []
    try:
        subprocess.run(["git", "rm", "--cached", "-q", "-r", "--ignore-unmatch",
                        "--"] + trackeados, cwd=ruta, capture_output=True,
                       text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return trackeados


def actualizar(ruta):
    """Overwrites templates that differ. Returns the list of updated ones.

    Before overwriting each script, it creates a timestamped backup
    (e.g. dedalo.sh.bak.20261005_123456) so it can be reverted manually
    if the update breaks something.
    """
    actualizados = []
    for nombre in _desactualizados(ruta):
        dst = rutas.script(ruta, nombre)
        # Timestamped backup before overwriting
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = f"{dst}.bak.{ts}"
        shutil.copy2(dst, backup)
        # Copy the new template
        shutil.copy2(os.path.join(PLANTILLA_DIR, nombre), dst)
        if nombre.endswith(".sh"):
            os.chmod(dst, 0o755)
        actualizados.append(nombre)
    return actualizados


def faltan(ruta):
    """Scripts and memory that are missing (lecciones.md/CONTEXTO.md are created if they do not exist)."""
    faltantes = [s for s in MEMORIA if not os.path.exists(os.path.join(ruta, s))]
    faltantes += [s for s in SCRIPTS if not os.path.exists(rutas.script(ruta, s))]
    return faltantes
