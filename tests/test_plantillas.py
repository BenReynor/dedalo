#!/usr/bin/env python3
"""Tests for plantillas.py - creation of lecciones.md (project memory)."""

import glob
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dedalo import plantillas, rutas

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(RAIZ, "pyproject.toml")


def _globs_de_package_data():
    """Extracts the globs from [tool.setuptools.package-data] without depending on tomli.

    The text is read on purpose: this way the test works on Python 3.10, where
    tomllib does not exist (the project's requires-python is >=3.10).
    """
    with open(PYPROJECT, encoding="utf-8") as f:
        texto = f.read()
    m = re.search(
        r"^\[tool\.setuptools\.package-data\][^\[]*?dedalo\s*=\s*\[(.*?)\]",
        texto,
        re.S | re.M,
    )
    assert m, "no se encontró [tool.setuptools.package-data] en pyproject.toml"
    return re.findall(r'"([^"]+)"', m.group(1))


def _lo_que_instala_en_runtime():
    """The names that instalar() copies unconditionally from PLANTILLA_DIR.

    Mirrors plantillas.instalar(): list(ARCHIVOS) + list(GATE_CHECKS) +
    [".gitignore"]. If this grows without touching package-data, the package stops
    being installable in a non-editable way.
    """
    return list(plantillas.ARCHIVOS) + list(plantillas.GATE_CHECKS) + [
        ".gitignore"
    ]


def test_package_data_cubre_lo_que_instala():
    """pyproject.toml must package EVERYTHING instalar() copies.

    Without this, `pip install .` produces a package missing
    plantillas_data/.gitignore; instalar() does shutil.copy2 without try and blows up
    with FileNotFoundError when adding the first project. The tests did not
    catch it because CI always installs with `-e`.
    """
    patrones = _globs_de_package_data()
    base = os.path.join(RAIZ, "dedalo")
    cubiertos = set()
    for patron in patrones:
        cubiertos.update(os.path.relpath(p, base) for p in glob.glob(
            os.path.join(base, patron)
        ))

    sin_cubrir = [
        nombre
for nombre in _lo_que_instala_en_runtime()
    # ALWAYS compare with "/": on Windows os.path.join would mix in many
    # backslashes and glob.relpath uses the OS ones, so both sides are normalized.
    if os.path.join("plantillas_data", nombre).replace("\\", "/") not in {
        p.replace("\\", "/") for p in cubiertos
    }
    ]
    assert not sin_cubrir, (
        "pyproject.toml no empaqueta estos ficheros que instalar() copia "
        f"incondicionalmente: {sin_cubrir}. Añade su glob a "
        "[tool.setuptools.package-data] (recuerda: `*` no hace match con "
        "ficheros que empiezan por punto)."
    )


def test_package_data_no_declara_ficheros_inexistentes():
    """Globs must not point at nothing: phantom globs promote bugs."""
    base = os.path.join(RAIZ, "dedalo")
    for patron in _globs_de_package_data():
        assert glob.glob(os.path.join(base, patron)), (
            f"[tool.setuptools.package-data] declara {patron!r} pero no "
            "coincide con ningún fichero del paquete"
        )


def _proyecto_tmp():
    tmp = tempfile.mkdtemp()
    try:
        for nombre in plantillas.SCRIPTS:
            with open(os.path.join(tmp, nombre), "w", encoding="utf-8"):
                pass
        os.mkdir(os.path.join(tmp, "gate_checks"))
        with open(os.path.join(tmp, "progreso.log"), "w", encoding="utf-8"):
            pass
    except OSError:
        pass
    return tmp


def test_faltan_incluye_lecciones():
    tmp = _proyecto_tmp()
    try:
        assert "lecciones.md" in plantillas.faltan(tmp)
        assert "CONTEXTO.md" in plantillas.faltan(tmp)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_instalar_crea_contexto():
    """CONTEXTO.md is installed with a skeleton and never overwritten."""
    import shutil
    tmp = _proyecto_tmp()
    try:
        creados = plantillas.instalar(tmp)
        assert "CONTEXTO.md" in creados
        ruta = os.path.join(tmp, "CONTEXTO.md")
        with open(ruta, encoding="utf-8") as f:
            assert "CONTEXTO DEL PROYECTO" in f.read()
        # The user's own content: it is not overwritten on the second install
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("# Mi contexto propio")
        creados2 = plantillas.instalar(tmp)
        assert "CONTEXTO.md" not in creados2
        with open(ruta, encoding="utf-8") as f:
            assert f.read() == "# Mi contexto propio"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_instalar_crea_lecciones():
    tmp = _proyecto_tmp()
    try:
        creados = plantillas.instalar(tmp)
        assert "lecciones.md" in creados
        ruta = os.path.join(tmp, "lecciones.md")
        assert os.path.exists(ruta)
        with open(ruta, encoding="utf-8") as f:
            contenido = f.read()
        assert "Lecciones aprendidas" in contenido
        # It is not overwritten if the user's content already exists
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("# Mi memoria propia")
        creados2 = plantillas.instalar(tmp)
        assert "lecciones.md" not in creados2
        with open(ruta, encoding="utf-8") as f:
            assert f.read() == "# Mi memoria propia"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_quitar_borra_lecciones():
    tmp = _proyecto_tmp()
    try:
        plantillas.instalar(tmp)
        eliminados = plantillas.quitar(tmp)
        assert "lecciones.md" in eliminados
        assert "CONTEXTO.md" in eliminados
        assert not os.path.exists(os.path.join(tmp, "lecciones.md"))
        assert not os.path.exists(os.path.join(tmp, "CONTEXTO.md"))
        assert not os.path.exists(os.path.join(tmp, "plan.md"))
        assert not os.path.exists(os.path.join(tmp, "progreso.log"))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_instalar_propaga_checks_nuevos_sin_pisar_custom():
    """A NEW template check is installed; a CUSTOM check is not touched."""
    import shutil
    tmp = _proyecto_tmp()
    try:
        plantillas.instalar(tmp)
        # The user creates their own check with content different from the template
        custom = os.path.join(rutas.gate_checks(tmp), "99_custom.sh")
        with open(custom, "w", encoding="utf-8") as f:
            f.write("echo 'check custom'\n")
        # "Old" project: without the new template check
        os.remove(os.path.join(rutas.gate_checks(tmp), "98_criterio.sh"))

        creados = plantillas.instalar(tmp)

        assert ".dedalo/scripts/gate_checks/98_criterio.sh" in creados, (
            "check nuevo se propaga")
        with open(custom, encoding="utf-8") as f:
            assert f.read() == "echo 'check custom'\n", "custom no se sobreescribe"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_actualizar_no_toca_gate_checks_custom():
    """actualizar() only renews the SCRIPTS; custom gate_checks stay intact."""
    import shutil
    tmp = _proyecto_tmp()
    try:
        plantillas.instalar(tmp)

        # Customize a check and force a difference in dedalo.sh
        custom = os.path.join(rutas.gate_checks(tmp), "99_custom.sh")
        with open(custom, "w", encoding="utf-8") as f:
            f.write("echo 'check custom'\n")
        script = rutas.dedalo_sh(tmp)
        with open(script, encoding="utf-8") as f:
            original = f.read()
        with open(script, "w", encoding="utf-8") as f:
            f.write(original + "\necho 'mod'\n")

        desact = plantillas._desactualizados(tmp)
        assert "gate_checks/99_custom.sh" not in desact
        assert "gate_checks/98_criterio.sh" not in desact
        assert "dedalo.sh" in desact

        plantillas.actualizar(tmp)
        with open(custom, encoding="utf-8") as f:
            assert f.read() == "echo 'check custom'\n", "custom intacto tras actualizar"
        with open(script, encoding="utf-8") as f:
            assert f.read() != original + "\necho 'mod'\n", "script restaurado"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_instalar_crea_gitignore_del_framework():
    """A new project receives a .gitignore that excludes the framework files."""
    tmp = _proyecto_tmp()
    try:
        creados = plantillas.instalar(tmp)
        assert ".gitignore" in creados
        ruta = os.path.join(tmp, ".gitignore")
        assert os.path.exists(ruta)
        with open(ruta, encoding="utf-8") as f:
            contenido = f.read()
        # The project's repo must never commit/push Dédalo files
        assert ".dedalo/" in contenido, "falta la entrada .dedalo/"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_instalar_no_pisa_gitignore_existente():
    """If the project has its own .gitignore, its entries are kept and the
    framework block is appended (install must exclude .dedalo/ right away)."""
    import shutil
    tmp = _proyecto_tmp()
    try:
        ruta = os.path.join(tmp, ".gitignore")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("# node\nnode_modules/\n")
        creados = plantillas.instalar(tmp)
        assert ".gitignore" not in creados
        with open(ruta, encoding="utf-8") as f:
            contenido = f.read()
        assert contenido.startswith("# node\nnode_modules/\n")
        assert ".dedalo/" in contenido
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_asegurar_gitignore_anade_bloque_existente():
    """asegurar_gitignore adds the Dédalo block to an existing .gitignore."""
    import shutil
    tmp = tempfile.mkdtemp()
    try:
        ruta = os.path.join(tmp, ".gitignore")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("# node\nnode_modules/\n")
        assert plantillas.asegurar_gitignore(tmp) is True
        with open(ruta, encoding="utf-8") as f:
            contenido = f.read()
        assert "node_modules/" in contenido, "lo del usuario no se toca"
        assert ".dedalo/" in contenido, "falta la entrada .dedalo/"
        # Idempotent: the second call does not duplicate
        assert plantillas.asegurar_gitignore(tmp) is False
        with open(ruta, encoding="utf-8") as f:
            assert f.read().count(".dedalo/") == 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_asegurar_gitignore_crea_si_falta():
    """If there is no .gitignore, asegurar_gitignore copies the whole template."""
    import shutil
    tmp = tempfile.mkdtemp()
    try:
        assert plantillas.asegurar_gitignore(tmp) is True
        ruta = os.path.join(tmp, ".gitignore")
        assert os.path.exists(ruta)
        with open(ruta, encoding="utf-8") as f:
            contenido = f.read()
        assert "Dédalo:" in contenido
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_quitar_framework_del_git():
    """quitar_framework_del_git stops tracking but keeps them on disk."""
    import shutil
    import subprocess
    tmp = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        for nombre in ["dedalo.sh", "gate.sh", "plan.md", "lecciones.md",
                       "CONTEXTO.md", "progreso.log", "metrics.jsonl",
                       "incidencias.jsonl", "mapeo.txt", "endpoints.txt",
                       "gate_checks/01_db.sh", "readme.md"]:
            p = os.path.join(tmp, nombre)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8"):
                pass
        subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                        "commit", "-q", "-m", "init"], cwd=tmp, check=True)

        salidos = plantillas.quitar_framework_del_git(tmp)

        assert "dedalo.sh" in salidos
        assert "gate_checks/01_db.sh" in salidos
        assert "CONTEXTO.md" not in salidos, "la memoria es del proyecto"
        assert "plan.md" not in salidos, "la memoria es del proyecto"
        assert "readme.md" not in salidos, "lo del usuario no se toca"
        # They are still on disk
        assert os.path.exists(os.path.join(tmp, "dedalo.sh"))
        assert os.path.exists(os.path.join(tmp, "plan.md"))
        # They are no longer in the index
        out = subprocess.run(["git", "ls-files"], cwd=tmp, capture_output=True,
                             text=True, check=True)
        trackeados = out.stdout.splitlines()
        assert "dedalo.sh" not in trackeados
        assert "CONTEXTO.md" in trackeados
        assert "plan.md" in trackeados
        assert "readme.md" in trackeados
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_inicializar_git_crea_repo_si_falta():
    import shutil
    tmp = tempfile.mkdtemp()
    try:
        with open(os.path.join(tmp, "plan.md"), "w", encoding="utf-8") as f:
            f.write("# PLAN\n\n- [ ] tarea\n      criterio: ok\n")
        assert not plantillas._es_repo_git(tmp)
        res = plantillas.inicializar_git(tmp)
        assert res["repo"] == "creado"
        assert res["archivos"] >= 1
        assert plantillas._es_repo_git(tmp)
        # The second call does not re-initialize
        res2 = plantillas.inicializar_git(tmp)
        assert res2["repo"] == "ya-existia"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_inicializar_git_no_rompe_repo_existente():
    import shutil
    import subprocess
    tmp = tempfile.mkdtemp()
    try:
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        with open(os.path.join(tmp, "readme.md"), "w", encoding="utf-8") as f:
            f.write("# repo\n")
        subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                        "commit", "-q", "-m", "init"], cwd=tmp, check=True)
        res = plantillas.inicializar_git(tmp)
        assert res["repo"] == "ya-existia"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_faltan_incluye_lecciones()
    test_instalar_crea_lecciones()
    test_instalar_crea_contexto()
    test_quitar_borra_lecciones()
    test_instalar_propaga_checks_nuevos_sin_pisar_custom()
    test_actualizar_no_toca_gate_checks_custom()
    test_inicializar_git_crea_repo_si_falta()
    test_inicializar_git_no_rompe_repo_existente()
    test_instalar_crea_gitignore_del_framework()
    test_instalar_no_pisa_gitignore_existente()
    test_asegurar_gitignore_anade_bloque_existente()
    test_asegurar_gitignore_crea_si_falta()
    test_quitar_framework_del_git()
    print("\n🎉 Todos los tests de plantillas.py PASARON")


def test_asegurar_gitignore_migra_el_bloque_antiguo():
    """An old per-file block is replaced by `.dedalo/` (and plan.md is tracked)."""
    import shutil
    tmp = tempfile.mkdtemp()
    try:
        ruta = os.path.join(tmp, ".gitignore")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("# node\nnode_modules/\n\n"
                    "# Dédalo: archivos del framework (NO deben ir al repo del proyecto)\n"
                    "dedalo.sh\ngate.sh\ngate_checks/\nplan.md\nlecciones.md\n"
                    "CONTEXTO.md\nprogreso.log\n\n"
                    "# Entorno / secretos (nunca subir)\n.env\n")
        assert plantillas.asegurar_gitignore(tmp) is True
        with open(ruta, encoding="utf-8") as f:
            contenido = f.read()
        assert "node_modules/" in contenido, "lo del usuario no se toca"
        assert ".env" in contenido, "el bloque de entorno se conserva"
        assert ".dedalo/" in contenido
        assert "\nplan.md\n" not in contenido, "plan.md ya no se ignora"
        assert "gate_checks/" not in contenido, (
            "la ruta del framework cambió a .dedalo/")
        assert contenido.count("# Dédalo:") == 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_plantillas_son_acumulables():
    """Several stacks can be enabled at once without their checks colliding."""
    import shutil
    tmp = _proyecto_tmp()
    try:
        plantillas.instalar(tmp, "rust, go")
        checks = os.path.join(tmp, ".dedalo", "scripts", "gate_checks")
        assert os.path.exists(os.path.join(checks, "03_test_rust.py"))
        assert os.path.exists(os.path.join(checks, "03_test_go.py"))
        assert plantillas.plantillas_de(tmp) == ["rust", "go"]
        # Installing again does not duplicate nor overwrite user checks
        assert plantillas.instalar(tmp) == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_plantilla_desconocida_se_ignora():
    """Unknown names are dropped instead of breaking the install."""
    import shutil
    tmp = _proyecto_tmp()
    try:
        plantillas.instalar(tmp, ["web", "no-existe"])
        assert plantillas.plantillas_de(tmp) == ["web"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_marcador_guarda_varias_plantillas():
    """The marker persists the whole selection, one name per line."""
    import shutil
    tmp = _proyecto_tmp()
    try:
        plantillas.instalar(tmp, "python,node")
        with open(os.path.join(tmp, ".dedalo", "plantilla"),
                  encoding="utf-8") as f:
            assert f.read().split() == ["python", "node"]
        # Reopening with no explicit selection keeps both
        assert plantillas.instalar(tmp) == []
        assert plantillas.plantilla_de(tmp) == "python,node"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -------- Auto-detección de stacks --------

def _dir_vacio():
    return tempfile.mkdtemp()


def _tocar(tmp, *nombres):
    for nombre in nombres:
        with open(os.path.join(tmp, nombre), "w", encoding="utf-8"):
            pass


def test_detectar_stacks_por_marcadores():
    import shutil
    tmp = _dir_vacio()
    try:
        _tocar(tmp, "package.json", "pyproject.toml",
               "index.html", "styles.css", "app.js")
        assert plantillas.detectar_stacks(tmp) == ["node", "python", "web"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_detectar_stacks_csharp_y_cpp():
    import shutil
    tmp = _dir_vacio()
    try:
        _tocar(tmp, "App.csproj", "main.cpp")
        assert plantillas.detectar_stacks(tmp) == ["csharp", "cpp"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_detectar_stacks_java_vs_kotlin():
    import shutil
    tmp = _dir_vacio()
    try:
        _tocar(tmp, "build.gradle")
        assert plantillas.detectar_stacks(tmp) == ["java"]
        os.remove(os.path.join(tmp, "build.gradle"))
        _tocar(tmp, "build.gradle.kts")
        assert plantillas.detectar_stacks(tmp) == ["kotlin"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_detectar_stacks_proyecto_vacio():
    import shutil
    tmp = _dir_vacio()
    try:
        assert plantillas.detectar_stacks(tmp) == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_detectar_no_confunde_makefile_con_cpp():
    """A lone Makefile is not proof of C++ (many non-C++ repos ship one)."""
    import shutil
    tmp = _dir_vacio()
    try:
        _tocar(tmp, "Makefile")
        assert "cpp" not in plantillas.detectar_stacks(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_instalar_auto_aplica_lo_detectado():
    import shutil
    tmp = _dir_vacio()
    try:
        _tocar(tmp, "Cargo.toml")
        creados = plantillas.instalar(tmp, "auto")
        assert plantillas.plantillas_de(tmp) == ["rust"]
        assert any("03_test_rust.py" in c for c in creados)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_instalar_auto_sin_marcadores_cae_en_python():
    import shutil
    tmp = _dir_vacio()
    try:
        plantillas.instalar(tmp, "auto")
        assert plantillas.plantillas_de(tmp) == ["python"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cambiar_seleccion_elimina_checks_obsoletos():
    """Switching stacks removes the untouched checks of the old one."""
    import shutil
    tmp = _proyecto_tmp()
    try:
        plantillas.instalar(tmp, "rust, python")
        checks = os.path.join(tmp, ".dedalo", "scripts", "gate_checks")
        assert os.path.exists(os.path.join(checks, "03_test_rust.py"))
        plantillas.instalar(tmp, "python")
        assert not os.path.exists(os.path.join(checks, "03_test_rust.py"))
        assert os.path.exists(os.path.join(checks, "02_pytest_python.py"))
        assert plantillas.plantillas_de(tmp) == ["python"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cambiar_seleccion_respeta_check_modificado():
    """A template check the user edited is NOT deleted on deselect."""
    import shutil
    tmp = _proyecto_tmp()
    try:
        plantillas.instalar(tmp, "rust, python")
        checks = os.path.join(tmp, ".dedalo", "scripts", "gate_checks")
        rust = os.path.join(checks, "03_test_rust.py")
        with open(rust, "w", encoding="utf-8") as f:
            f.write("# personalizado\n")
        plantillas.instalar(tmp, "python")
        assert os.path.exists(rust), "no se borra lo que el usuario tocó"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_plantillas_instaladas_sin_marcador():
    """Without marker the GUI reads the installed checks, not a guess."""
    import shutil
    tmp = _proyecto_tmp()
    try:
        plantillas.instalar(tmp)  # legacy default: unsuffixed checks
        assert plantillas.plantillas_instaladas(tmp) == []
        plantillas.instalar(tmp, "rust")
        os.remove(os.path.join(tmp, ".dedalo", "plantilla"))
        assert plantillas.plantillas_instaladas(tmp) == ["rust"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
