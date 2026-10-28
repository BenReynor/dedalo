#!/usr/bin/env python3
"""Tests for loop_git.py - git operations of the native loop.

They are exercised against real git repos in /tmp; they require git (present in CI).
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dedalo.loop_git import (
    borrar_rama,
    cambios_entre,
    checkout,
    commit_tarea,
    diff_para_revisor,
    merge_ff,
    preparar_ramas,
    rama_existe,
    registrar_leccion,
    revertir,
    run_git,
    snapshot,
)


def _repo(tmp_path):
    """Creates a master repo with base.txt committed and author config."""
    proyecto = tmp_path / "proy"
    proyecto.mkdir()
    for cmd in (["git", "init", "-q", "-b", "master"],
                ["git", "config", "user.email", "dedalo@test"],
                ["git", "config", "user.name", "Dédalo Test"]):
        subprocess.run(cmd, cwd=proyecto, check=True)
    (proyecto / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=proyecto, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=proyecto,
                   check=True)
    return proyecto


def test_snapshot_excluye_caches_e_incluye_cambios(tmp_path):
    proy = _repo(tmp_path)
    (proy / "modo.txt").write_text("cambio\n", encoding="utf-8")
    (proy / "nuevo.py").write_text("x\n", encoding="utf-8")
    (proy / "plan.md").write_text("plan\n", encoding="utf-8")
    (proy / "mod.pyc").write_text("by\n", encoding="utf-8")
    subprocess.run(["git", "add", "mod.pyc"], cwd=proy, check=True)
    capa = proy / "__pycache__"
    capa.mkdir()
    (capa / "cach.pyc").write_text("z\n", encoding="utf-8")
    destino = tmp_path / "before"
    snapshot(proy, destino)
    lineas = destino.read_text(encoding="utf-8").splitlines()
    assert sorted(lineas) == sorted(["plan.md", "modo.txt", "nuevo.py"])
    assert not any(".pyc" in linea or "__pycache__" in linea
                   for linea in lineas)


def test_cambios_entre_simetrico(tmp_path):
    proy = _repo(tmp_path)
    # A file that appears and disappears from the status (EXACT semantics
    # of bash: compare the LISTS of files). A tracked modified file that is
    # then deleted stays in the status as " D", so it is NOT "deleted".
    (proy / "base.txt").write_text("modificado antes del before\n",
                                   encoding="utf-8")
    (proy / "tmp_borrable.txt").write_text("untracked\n", encoding="utf-8")
    before = tmp_path / "before"
    after = tmp_path / "after"
    snapshot(proy, before)
    (proy / "nuevo.txt").write_text("x\n", encoding="utf-8")
    (proy / "plan.md").write_text("cambiado\n", encoding="utf-8")
    os.unlink(proy / "tmp_borrable.txt")
    snapshot(proy, after)
    nuevos, borrados = cambios_entre(before, after)
    assert nuevos == ["nuevo.txt"]
    assert borrados == ["tmp_borrable.txt"]
    # Without filtering CONTROL, plan.md IS a "change"
    nuevos_c, borrados_c = cambios_entre(before, after, control="NOEXISTE_COM0")
    assert "plan.md" in nuevos_c


def test_cambios_entre_control_excluye_marco(tmp_path):
    antes = tmp_path / "antes"
    despues = tmp_path / "despues"
    antes.write_text("plan.md\nbase.txt\n", encoding="utf-8")
    despues.write_text("plan.md\nbase.txt\nprogreso.log\n", encoding="utf-8")
    nuevos, borrados = cambios_entre(antes, despues)
    assert nuevos == [] and borrados == []
    nuevos, borrados = cambios_entre(antes, despues, control="NOEXISTE_COM0")
    assert nuevos == ["progreso.log"]


def test_commit_tarea_con_espacios(tmp_path):
    proy = _repo(tmp_path)
    (proy / "mi modulo.py").write_text("print(1)\n", encoding="utf-8")
    archivos = ["mi modulo.py"]
    rc = commit_tarea(proy, archivos, "dedalo: tarea", "cuerpo de la tarea")
    assert rc == 0
    _, log, _ = run_git(proy, "log", "-1", "--format=%s%n%b")
    assert log.startswith("dedalo: tarea\ncuerpo de la tarea")



def test_commit_tarea_incluye_borrados_y_no_se_rompe_por_una_ruta_perdida(tmp_path):
    """On ARGUS one unmatched path made `git add` stage nothing (rc 128): the
    task was marked done with its work uncommitted. Deletions, quoted paths
    and a vanished path must not stop the commit."""
    proy = _repo(tmp_path)
    (proy / "base.txt").unlink()                       # tracked, deleted
    (proy / "con espacio.css").write_text("a\n", encoding="utf-8")
    (proy / "nuevo.tsx").write_text("b\n", encoding="utf-8")
    archivos = ["base.txt", '"con espacio.css"', "nuevo.tsx", "ya-no-existe.css"]
    assert commit_tarea(proy, archivos, "dedalo: t", "cuerpo") == 0
    _, out, _ = run_git(proy, "status", "--porcelain")
    assert out.strip() == ""
    _, ls, _ = run_git(proy, "ls-files")
    assert "base.txt" not in ls and "con espacio.css" in ls and "nuevo.tsx" in ls


def test_commit_tarea_fallido_guarda_el_error_de_git(tmp_path):
    from dedalo import loop_git
    proy = _repo(tmp_path)
    (proy / "x.txt").write_text("x\n", encoding="utf-8")
    run_git(proy, "config", "core.hooksPath", str(tmp_path / "hooks"))
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/bin/sh\necho 'rechazado por hook' >&2\nexit 1\n",
                                      encoding="utf-8")
    (hooks / "pre-commit").chmod(0o755)
    assert commit_tarea(proy, ["x.txt"], "s", "c") != 0
    assert "rechazado por hook" in loop_git.ULTIMO_ERROR["git"]

def test_commit_tarea_sin_archivos_no_hace_nada(tmp_path):
    proy = _repo(tmp_path)
    assert commit_tarea(proy, [], "subj", "b") == 0
    _, log, _ = run_git(proy, "log", "-1", "--format=%s")
    assert log.strip() == "base"


def test_merge_ff_y_borrar_rama(tmp_path):
    proy = _repo(tmp_path)
    checkout(proy, "rama-tarea", crear=True, desde="master")
    (proy / "feat.txt").write_text("f\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=proy, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "feat"], cwd=proy, check=True)
    assert rama_existe(proy, "rama-tarea")
    assert rama_existe(proy, "master")
    checkout(proy, "master")
    assert merge_ff(proy, "rama-tarea") == 0
    assert borrar_rama(proy, "rama-tarea") == 0
    assert not rama_existe(proy, "rama-tarea")


def test_merge_ff_aborta_con_divergencia(tmp_path):
    proy = _repo(tmp_path)
    checkout(proy, "rama-tarea", crear=True, desde="master")
    (proy / "feat.txt").write_text("f\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=proy, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "feat"], cwd=proy, check=True)
    checkout(proy, "master")
    (proy / "base.txt").write_text("otro\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=proy, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "master-avanza"], cwd=proy,
                   check=True)
    assert merge_ff(proy, "rama-tarea") != 0
    # Does not delete a branch that has not been merged
    assert borrar_rama(proy, "rama-tarea", fuerza=False) != 0
    assert rama_existe(proy, "rama-tarea")


def test_revertir_restaura_y_quita_untracked(tmp_path):
    proy = _repo(tmp_path)
    (proy / "base.txt").write_text("editado\n", encoding="utf-8")
    (proy / "plan.md").write_text("control del framework\n", encoding="utf-8")
    (proy / "nuevo_del_agente.py").write_text("x\n", encoding="utf-8")
    revertir(proy)
    assert (proy / "base.txt").read_text(encoding="utf-8") == "base\n"
    assert not (proy / "nuevo_del_agente.py").exists()
    assert (proy / "plan.md").exists()  # CONTROL intact


def test_revertir_archivo_borrado_se_restaura(tmp_path):
    proy = _repo(tmp_path)
    os.unlink(proy / "base.txt")
    (proy / "plan.md").write_text("cambiado\n", encoding="utf-8")
    revertir(proy)
    assert (proy / "base.txt").read_text(encoding="utf-8") == "base\n"


def test_diff_para_revisor_excluye_control_e_incluye_nuevos(tmp_path):
    proy = _repo(tmp_path)
    (proy / "base.txt").write_text("cambio en codigo\n", encoding="utf-8")
    (proy / "nuevo.py").write_text("print(1)\n", encoding="utf-8")
    (proy / "plan.md").write_text("nuevo plan\n", encoding="utf-8")
    stat, diff = diff_para_revisor(proy)
    assert "base.txt" in stat
    assert "nuevo.py" in stat
    assert "plan.md |" not in stat
    assert "diff --git a/base.txt" in diff
    assert "+cambio en codigo" in diff
    assert "+print(1)" in diff
    assert diff_para_revisor.__doc__ is not None


def test_diff_para_revisor_sin_cambios(tmp_path):
    proy = _repo(tmp_path)
    stat, diff = diff_para_revisor(proy)
    assert stat == "(sin cambios fuera de archivos CONTROL)"
    assert diff == ""


def test_registrar_leccion_append(tmp_path):
    lecciones = tmp_path / "lecciones.md"
    registrar_leccion(str(lecciones), "Titulo", "Sintoma",
                      "Causa", "Prevencion")
    registrar_leccion(str(lecciones), "Otro", "S2", "C2", "P2")
    contenido = lecciones.read_text(encoding="utf-8")
    assert contenido.count("## ") == 2
    assert "- Síntoma: Sintoma" in contenido
    assert "- Causa: Causa" in contenido
    assert "- Prevención: Prevencion" in contenido


def test_preparar_ramas_crea_run_y_trabajo(tmp_path):
    proy = _repo(tmp_path)
    rama_trabajo, mensajes = preparar_ramas(proy, "master", "auto/run1", "")
    assert rama_trabajo == "auto/run1"
    assert any("Rama base: auto/run1" in m for m in mensajes)
    assert any("Rama de trabajo (default): auto/run1" in m for m in mensajes)
    assert rama_existe(proy, "auto/run1")


def test_preparar_ramas_trabajo_master(tmp_path):
    proy = _repo(tmp_path)
    rama_trabajo, mensajes = preparar_ramas(proy, "master", "auto/run2", "master")
    assert rama_trabajo == "master"
    assert any("rama principal master" in m for m in mensajes)


def test_preparar_ramas_trabajo_nueva_desde_run(tmp_path):
    proy = _repo(tmp_path)
    rama_trabajo, mensajes = preparar_ramas(proy, "master", "auto/run3", "feat/x")
    assert rama_trabajo == "feat/x"
    assert any("Creada la rama de trabajo feat/x" in m for m in mensajes)


def test_preparar_ramas_trabajo_existente(tmp_path):
    proy = _repo(tmp_path)
    subprocess.run(["git", "-C", str(proy), "checkout", "-q", "-b", "feat/ya"],
                   check=True)
    subprocess.run(["git", "-C", str(proy), "checkout", "-q", "master"],
                   check=True)
    rama_trabajo, mensajes = preparar_ramas(proy, "master", "auto/run4", "feat/ya")
    assert rama_trabajo == "feat/ya"
    assert any("rama existente feat/ya" in m for m in mensajes)
    _, out, _ = run_git(proy, "branch", "--show-current")
    assert out.strip() == "feat/ya"


def test_preparar_ramas_reusa_rama_run(tmp_path):
    proy = _repo(tmp_path)
    subprocess.run(["git", "-C", str(proy), "checkout", "-q", "-b", "auto/run5"],
                   check=True)
    subprocess.run(["git", "-C", str(proy), "checkout", "-q", "master"],
                   check=True)
    rama_trabajo, mensajes = preparar_ramas(proy, "master", "auto/run5", "")
    assert rama_trabajo == "auto/run5"
    assert any("Reusando rama auto/run5" in m for m in mensajes)


def test_preparar_ramas_origin_tracking(tmp_path):
    proy = _repo(tmp_path)
    subprocess.run(["git", "-C", str(proy), "checkout", "-q", "-b", "feat/o"],
                   check=True)
    subprocess.run(["git", "-C", str(proy), "checkout", "-q", "master"],
                   check=True)
    # create a local remote so that origin/feat/o exists
    base = tmp_path / "remoto"
    subprocess.run(["git", "-C", str(proy), "clone", "-q", "--bare",
                    str(proy), str(base)], check=True)
    subprocess.run(["git", "-C", str(proy), "remote", "add", "origin",
                    str(base)], check=True)
    subprocess.run(["git", "-C", str(proy), "checkout", "-q", "feat/o"],
                   check=True)
    subprocess.run(["git", "-C", str(proy), "push", "-q", "origin", "feat/o"],
                   check=True)
    subprocess.run(["git", "-C", str(proy), "checkout", "-q", "master"],
                   check=True)
    subprocess.run(["git", "-C", str(proy), "branch", "-q", "-D", "feat/o"],
                   check=True)
    rama_trabajo, mensajes = preparar_ramas(
        proy, "master", "auto/run6", "feat/o")
    assert rama_trabajo == "feat/o"
    assert any("seguimiento de origin/feat/o" in m for m in mensajes)


if __name__ == "__main__":
    import tempfile

    class _T:
        def __init__(self):
            self._t = tempfile.mkdtemp()

        def __truediv__(self, nombre):
            return type("P", (), {"__str__": lambda s: self._t + "/" + nombre})()

    tmp = _T()
    for fn in (test_snapshot_excluye_caches_e_incluye_cambios,
               test_cambios_entre_simetrico,
               test_cambios_entre_control_excluye_marco,
               test_commit_tarea_con_espacios,
               test_commit_tarea_sin_archivos_no_hace_nada,
               test_commit_tarea_incluye_borrados_y_no_se_rompe_por_una_ruta_perdida,
               test_merge_ff_y_borrar_rama,
               test_merge_ff_aborta_con_divergencia,
               test_revertir_restaura_y_quita_untracked,
               test_revertir_archivo_borrado_se_restaura,
               test_diff_para_revisor_excluye_control_e_incluye_nuevos,
               test_diff_para_revisor_sin_cambios,
               test_registrar_leccion_append,
               test_preparar_ramas_crea_run_y_trabajo,
               test_preparar_ramas_trabajo_master,
               test_preparar_ramas_trabajo_nueva_desde_run,
               test_preparar_ramas_trabajo_existente,
               test_preparar_ramas_reusa_rama_run,
               test_preparar_ramas_origin_tracking):
        fn(_T())
    print("\n🎉 Todos los tests de loop_git.py PASARON")
