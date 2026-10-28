#!/usr/bin/env python3
"""Git operations of the native loop (port of the git sections of
dedalo.sh: snapshot, iteracion_sin_trabajo, commit/merge, revert,
diff_para_revisor, registrar_leccion and preparar_ramas).

No PySide dependencies. Git commands are run with run_con_timeout
(defensive cap; the local tree should not hang). All paths
are passed as separate arguments (never quoted), same as the bash fix
for diffs with spaces.
"""

import os
import re
import shutil
import subprocess
import time
from collections import Counter

from .loop_proceso import run_con_timeout

# Pattern of caches/derived files that NEVER enter the diff nor the commits
# (same list as the grep -vE of snapshot() in the script).
_CACHES = re.compile(
    r"(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|node_modules|\.venv|venv)/"
    r"|\.pyc$|\.pyo$")

# Control files of the framework itself: loop traceability, not the
# agent's. Comes from the script's CONTROL variable. When used it is anchored
# `^(?P<control>...)$` so that "plan.md" does not swallow "docs/plan.md".
CONTROL = (
    r"plan\.md|lecciones\.md|CONTEXTO\.md|progreso\.log|gate\.sh|dedalo\.sh"
    r"|mapear\.sh|mapeo\.txt|endpoints\.txt|metrics\.jsonl|incidencias\.jsonl"
    r"|gate_checks(/.*)?|\.dedalo(/.*)?|\.dedalo_review(/.*)?")


def run_git(proyecto, *args, timeout=60):
    """`git -C <proyecto> <args>`; returns (rc, stdout, stderr)."""
    rc, salida, _t = run_con_timeout(
        ["git", "-C", str(proyecto)] + list(args), timeout,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = salida[0].decode("utf-8", "replace") if salida and salida[0] else ""
    err = salida[1].decode("utf-8", "replace") if salida and salida[1] else ""
    return rc, out, err


def _ok(proyecto, *args):
    return run_git(proyecto, *args)[0] == 0


def snapshot(proyecto, destino):
    """Writes to `destino` the sorted list of changed files, like
    `git status --porcelain`.

    Port of snapshot(): strips the 3-character status prefix, keeps the
    quoted paths git puts (spaces), and filters caches. The CONTROL
    file stripping is done LATER (cambios_entre), just as the
    script separates snapshot() from iteracion_sin_trabajo().
    """
    _, out, _ = run_git(proyecto, "-c", "core.quotepath=false",
                        "status", "--porcelain")
    lineas = []
    for linea in out.splitlines():
        if len(linea) < 4:
            continue
        ruta = linea[3:]
        if _CACHES.search(ruta):
            continue
        lineas.append(ruta)
    with open(destino, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(lineas)) + ("\n" if lineas else ""))


def _leer(fichero):
    if not os.path.exists(fichero):
        return []
    with open(fichero, encoding="utf-8") as f:
        return [linea for linea in f.read().splitlines() if linea]


def cambios_entre(before_path, after_path, control=CONTROL):
    """Compares two snapshots excluding CONTROL, symmetrically.

    Port of iteracion_sin_trabajo(): returns (nuevos, borrados). A file
    that disappears from the agent's status is also work (it deleted it). The
    result is a multiset (comm -13 / -23), like the script's sort+comm. If both
    are empty there was no work.
    """
    rx = re.compile(r"^(?:" + control + r")$")
    antes = Counter(linea for linea in _leer(before_path) if not rx.match(linea))
    despues = Counter(linea for linea in _leer(after_path) if not rx.match(linea))
    nuevos = list((despues - antes).elements())
    borrados = list((antes - despues).elements())
    return nuevos, borrados


# stderr of the last failed commit_tarea(), for the loop to log it.
ULTIMO_ERROR = {"git": ""}


def commit_tarea(proyecto, archivos, subject, cuerpo):
    """`git add -A -- <archivos> && git commit -q -m <subject> -m <cuerpo>`.

    Returns 0 if the commit was created. Paths come from `git status
    --porcelain`: quotes are stripped and a path that neither exists nor is
    tracked is skipped, because a single unmatched pathspec makes `git add`
    stage NOTHING (rc 128) and the task's work was left uncommitted. `-A`
    records deletions too. On failure, git's stderr is in ULTIMO_ERROR["git"].
    With no files it does nothing (same as the bash `[ -n ]` guard).
    """
    ULTIMO_ERROR["git"] = ""
    rutas = []
    for a in archivos:
        ruta = a.strip().strip('"')
        if ruta and (os.path.lexists(os.path.join(proyecto, ruta))
                     or _ok(proyecto, "ls-files", "--error-unmatch", "--", ruta)):
            rutas.append(ruta)
    if not rutas:
        return 0
    rc, _, err = run_git(proyecto, "add", "-A", "--", *rutas)
    if rc != 0:
        ULTIMO_ERROR["git"] = err.strip()
        return rc
    rc, _, err = run_git(proyecto, "commit", "-q", "-m", subject, "-m", cuerpo)
    ULTIMO_ERROR["git"] = err.strip() if rc else ""
    return rc

def merge_ff(proyecto, rama):
    """`git merge -q --ff-only <rama>`; rc 0 if the fast-forward went well."""
    return run_git(proyecto, "merge", "-q", "--ff-only", rama)[0]


def borrar_rama(proyecto, rama, fuerza=False):
    flag = "-D" if fuerza else "-d"
    return run_git(proyecto, "branch", "-q", flag, rama)[0]


def checkout(proyecto, rama, crear=False, desde=None):
    args = ["checkout", "-q", "-b", rama] + ([desde] if desde else []) \
        if crear else ["checkout", "-q", rama]
    return run_git(proyecto, *args)[0]


def rama_existe(proyecto, rama):
    """rev-parse --verify with -q: True if the ref exists (local or origin)."""
    return _ok(proyecto, "rev-parse", "--verify", "-q", rama)


def preparar_ramas(proyecto, rama_base, rama_run, rama_trabajo):
    """Port of lines 964-1017 of dedalo.sh: creates/reuses RAMA_RUN
    from RAMA_BASE and resolves RAMA_TRABAJO (main / existing /
    tracking origin / new from RAMA_RUN).

    Returns (effective_rama_trabajo, messages) to log. If the base
    branch could not be created it returns (None, messages) and the caller aborts.
    """
    mensajes = []
    if rama_existe(proyecto, rama_run):
        checkout(proyecto, rama_run)
        mensajes.append(f"[dedalo] Reusando rama {rama_run}")
    elif checkout(proyecto, rama_run, crear=True, desde=rama_base) != 0:
        mensajes.append(f"[dedalo] ✗ no se pudo crear {rama_run} desde "
                        f"{rama_base} (¿árbol sucio?).")
        return None, mensajes
    else:
        mensajes.append(f"[dedalo] Rama base: {rama_run} (desde {rama_base})")

    if rama_trabajo and rama_trabajo != rama_run:
        if rama_trabajo in ("master", "main"):
            if checkout(proyecto, rama_trabajo) != 0:
                checkout(proyecto, rama_trabajo, crear=True, desde=rama_run)
            mensajes.append("[dedalo] Trabajando en la rama principal "
                            f"{rama_trabajo} (sin rama paralela)")
        elif rama_existe(proyecto, rama_trabajo):
            checkout(proyecto, rama_trabajo)
            mensajes.append("[dedalo] Trabajando en la rama existente "
                            f"{rama_trabajo}")
        elif rama_existe(proyecto, "origin/" + rama_trabajo):
            checkout(proyecto, rama_trabajo, crear=True,
                     desde="origin/" + rama_trabajo)
            mensajes.append("[dedalo] Trabajando en "
                            f"{rama_trabajo} (seguimiento de origin/{rama_trabajo})")
        else:
            checkout(proyecto, rama_trabajo, crear=True, desde=rama_run)
            mensajes.append("[dedalo] Creada la rama de trabajo "
                            f"{rama_trabajo} (desde {rama_run})")
    else:
        rama_trabajo = rama_run
        mensajes.append(f"[dedalo] Rama de trabajo (default): {rama_trabajo}")
    return rama_trabajo, mensajes


def revertir(proyecto, control=CONTROL):
    """Reverts the working tree to the HEAD state (task branch without advancing).

    Port of revertir(): removes new (untracked) files, restores the
    deleted and modified ones from HEAD. The framework CONTROL files
    are not touched. Paths quoted by git (spaces) are normalized.
    """
    rx = re.compile(r"^(?:" + control + r")$")
    _, out, _ = run_git(proyecto, "status", "--porcelain")
    for linea in out.splitlines():
        if len(linea) < 4:
            continue
        estado = linea[:2]
        ruta = linea[3:].strip('"')
        if not ruta or rx.match(ruta):
            continue
        if estado == "??":
            ruta_abs = os.path.join(proyecto, ruta)
            if os.path.isdir(ruta_abs) and not os.path.islink(ruta_abs):
                shutil.rmtree(ruta_abs, ignore_errors=True)
            else:
                try:
                    os.unlink(ruta_abs)
                except OSError:
                    pass
        else:
            run_git(proyecto, "checkout", "--", ruta)


def diff_para_revisor(proyecto, control=CONTROL):
    """Diff of the iteration for the reviewer, excluding CONTROL files.

    Port of diff_revision(): marks intent-to-add (git add -N) so new
    files enter the diff, and passes the paths as separate pathspecs
    (never a multiline list in a single argument). Returns
    (stat, diff). With no changes it returns the text "(sin cambios fuera de
    archivos CONTROL)".
    """
    rx = re.compile(r"^(?:" + control + r")$")
    run_git(proyecto, "add", "-N", "-A")
    _, out, _ = run_git(proyecto, "diff", "--name-only")
    archivos = [linea for linea in out.splitlines()
                if linea and not rx.match(linea.strip('"'))]
    if not archivos:
        return "(sin cambios fuera de archivos CONTROL)", ""
    _, stat, _ = run_git(proyecto, "diff", "--stat", "--", *archivos)
    _, diff, _ = run_git(proyecto, "diff", "--", *archivos)
    return stat, ("#----- diff (excluye archivos CONTROL del framework) -----#\n"
                  + diff)


def registrar_leccion(lecciones, titulo, sintoma, causa, prevencion):
    """Adds a lesson to lecciones.md (project memory)."""
    fecha = time.strftime("%Y-%m-%d %H:%M")
    with open(lecciones, "a", encoding="utf-8") as f:
        f.write(f"\n## {fecha} — {titulo}\n"
                f"- Síntoma: {sintoma}\n"
                f"- Causa: {causa}\n"
                f"- Prevención: {prevencion}\n")
