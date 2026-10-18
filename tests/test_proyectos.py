#!/usr/bin/env python3
"""Regression tests: a removed project must NOT reappear in the registry.

Protects against the bug where closeEvent/_cambiar_proyecto called
guardar_config_proyecto() and this re-added (`setdefault`) the name of the
project the user had just removed, making it reappear when
reopening the GUI as an orphan entry (config without path).
"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dedalo import configuracion as cfg
from dedalo import proyectos


def _config_aislada(contenido=None):
    """Redirects CONFIG_DIR/REGISTRO to a temp and returns the registry's path.

    By default it writes a valid, empty registry; passing `contenido` lets you
    seed any text (including invalid JSON).
    """
    tmp = tempfile.mkdtemp()
    reg = os.path.join(tmp, "proyectos.json")
    cfg.CONFIG_DIR = tmp
    cfg.REGISTRO = reg
    proyectos.cfg.CONFIG_DIR = tmp
    proyectos.cfg.REGISTRO = reg
    if contenido is None:
        contenido = json.dumps({"proyectos": {}}, ensure_ascii=False)
    with open(reg, "w", encoding="utf-8") as f:
        f.write(contenido)
    return reg


def _limpiar(reg):
    import shutil

    shutil.rmtree(os.path.dirname(reg), ignore_errors=True)


def test_guardar_config_no_reañade_proyecto_quitado():
    reg = _config_aislada()
    try:
        # Registry with two projects, then the user removes "A"
        proyectos_dic = {
            "A": {"ruta": "/tmp/a", "config": {"tema": "X"}},
            "B": {"ruta": "/tmp/b", "config": {}},
        }
        proyectos.guardar(proyectos_dic, "Oscuro")
        proyectos_dic.pop("A", None)
        # Removing a project is the only case that must shrink the list.
        proyectos.guardar(proyectos_dic, "Oscuro", exacto=True)

        # closeEvent keeps calling with the active name already removed
        proyectos.guardar_config_proyecto(proyectos_dic, "A", {"tema": "Y"})

        with open(reg, encoding="utf-8") as f:
            datos = json.load(f)
        assert "A" not in datos["proyectos"], "el proyecto quitado no debe reaparecer"
        assert set(datos["proyectos"]) == {"B"}
    finally:
        import shutil

        shutil.rmtree(os.path.dirname(reg), ignore_errors=True)


def test_guardar_config_sigue_guardando_proyectos_existentes():
    reg = _config_aislada()
    try:
        proyectos_dic = {"B": {"ruta": "/tmp/b", "config": {}}}
        proyectos.guardar(proyectos_dic, "Oscuro")
        proyectos.guardar_config_proyecto(
            proyectos_dic, "B", {"modelos": {"tarea": "x"}}
        )

        with open(reg, encoding="utf-8") as f:
            datos = json.load(f)
        assert "B" in datos["proyectos"]
        assert datos["proyectos"]["B"]["config"]["modelos"]["tarea"] == "x"
    finally:
        import shutil

        shutil.rmtree(os.path.dirname(reg), ignore_errors=True)


# ---------- registry integrity ----------
#
# Serious regression: _leer_archivo() swallowed the JSONDecodeError and returned {},
# so Ventana.__init__ (app.py:78) saw "no projects" and called
# guardar(), which wrote an EMPTY registry over the corrupt one. A
# damaged registry = all the user's projects deleted on the next startup,
# with no warning.


def test_registro_corrupto_no_se_sobreescribe():
    """verificar_registro() must raise AND leave the original intact."""
    reg = _config_aislada(contenido='{"proyectos": {"A": {"ruta": "/tmp/a"')
    try:
        with pytest.raises(proyectos.RegistroCorrupto) as exc:
            proyectos.verificar_registro()

        assert os.path.exists(reg), "el original no debe tocarse al detectar"
        with open(reg, encoding="utf-8") as f:
            assert f.read() == '{"proyectos": {"A": {"ruta": "/tmp/a"'
        assert exc.value.copia and os.path.exists(exc.value.copia)
    finally:
        _limpiar(reg)


def test_registro_corrupto_hace_copia_de_seguridad():
    """The .corrupto copy keeps the data so the user can recover it."""
    reg = _config_aislada(contenido='{"proyectos": {"A": {"ruta": "/tmp/a"')
    try:
        with pytest.raises(proyectos.RegistroCorrupto) as exc:
            proyectos.verificar_registro()
        with open(exc.value.copia, encoding="utf-8") as f:
            assert '"A"' in f.read()
    finally:
        _limpiar(reg)


def test_registro_corrupto_bloquea_en_cada_arranque():
    """Until the user decides, the warning repeats: the registry is not
    lost silently for having closed and reopened the app."""
    reg = _config_aislada(contenido="no soy json")
    try:
        for _ in range(2):
            with pytest.raises(proyectos.RegistroCorrupto):
                proyectos.verificar_registro()
        with open(reg, encoding="utf-8") as f:
            assert f.read() == "no soy json"
    finally:
        _limpiar(reg)


def test_copia_corrupta_no_pisa_la_anterior():
    """Two corrupt runs in a row = two different copies."""
    reg = _config_aislada(contenido="basura1")
    try:
        with pytest.raises(proyectos.RegistroCorrupto) as c1:
            proyectos.verificar_registro()
        with open(reg, "w", encoding="utf-8") as f:
            f.write("basura2")
        with pytest.raises(proyectos.RegistroCorrupto) as c2:
            proyectos.verificar_registro()

        assert c1.value.copia != c2.value.copia
        with open(c1.value.copia, encoding="utf-8") as f:
            assert f.read() == "basura1"
        with open(c2.value.copia, encoding="utf-8") as f:
            assert f.read() == "basura2"
    finally:
        _limpiar(reg)


def test_descartar_registro_permite_arrancar_vacio():
    """With the user's consent, the corrupt one is deleted and guardar()
    rebuilds a valid registry; the copy is kept."""
    reg = _config_aislada(contenido="basura")
    try:
        with pytest.raises(proyectos.RegistroCorrupto) as exc:
            proyectos.verificar_registro()

        proyectos.descartar_registro_corrupto()
        assert not os.path.exists(reg)

        proyectos.verificar_registro()  # no longer raises

        proyectos.guardar({"B": {"ruta": "/tmp/b"}}, "Oscuro")
        with open(reg, encoding="utf-8") as f:
            datos = json.load(f)
        assert datos["proyectos"]["B"]["ruta"] == "/tmp/b"
        assert datos["tema"] == "Oscuro"
        assert os.path.exists(exc.value.copia), "la copia debe sobrevivir"
    finally:
        _limpiar(reg)


def test_escribir_es_atomico_y_no_deja_temporales():
    """No orphan .tmp files: replace() swaps in one go."""
    reg = _config_aislada()
    try:
        proyectos.guardar({"A": {"ruta": "/tmp/a"}}, "Oscuro")
        proyectos.guardar_sidebar_ancho(320)

        assert not [f for f in os.listdir(os.path.dirname(reg)) if ".tmp" in f]
        with open(reg, encoding="utf-8") as f:
            assert json.load(f)["sidebar_ancho"] == 320
    finally:
        _limpiar(reg)


def test_escribir_no_deja_el_registro_roto_si_falla_la_serializacion():
    """If json.dump blows up mid-write, the previous good registry
    must still be readable (that is why it is written to a temp and not in place)."""
    reg = _config_aislada()
    try:
        proyectos.guardar({"A": {"ruta": "/tmp/a"}}, "Oscuro")

        class Inserializable:
            pass

        with pytest.raises(TypeError):
            proyectos._escribir({"proyectos": {"A": Inserializable()}})

        with open(reg, encoding="utf-8") as f:
            datos = json.load(f)
        assert datos["proyectos"]["A"]["ruta"] == "/tmp/a"
        assert not [f for f in os.listdir(os.path.dirname(reg)) if ".tmp" in f]
    finally:
        _limpiar(reg)


# ---------- no clobbering the registry from a stale window ----------
#
# A window keeps its project list in memory and re-saves it on every config
# change. If another process (the MCP server, a second window) registered a
# project meanwhile, that save used to overwrite the whole registry with the
# stale list: the project installed in the background vanished.


def test_guardar_no_machaca_los_proyectos_ajenos():
    """Saving global settings with a stale (empty) list keeps what is on disk."""
    reg = _config_aislada()
    try:
        proyectos.guardar({"instalado": {"ruta": "/tmp/instalado"}}, "Oscuro")

        # A window opened before that project existed saves its theme.
        proyectos.guardar({}, "Claro")

        with open(reg, encoding="utf-8") as f:
            datos = json.load(f)
        assert "instalado" in datos["proyectos"], "el proyecto ajeno desapareció"
        assert datos["tema"] == "Claro"
    finally:
        _limpiar(reg)


def test_guardar_exacto_si_permite_vaciar_la_lista():
    reg = _config_aislada()
    try:
        proyectos.guardar({"A": {"ruta": "/tmp/a"}}, "Oscuro")
        proyectos.guardar({}, "Oscuro", exacto=True)
        with open(reg, encoding="utf-8") as f:
            assert json.load(f)["proyectos"] == {}
    finally:
        _limpiar(reg)


def test_guardar_config_no_pisa_los_proyectos_ajenos():
    """The config save for the active project must touch only that project."""
    reg = _config_aislada()
    try:
        proyectos.guardar({"A": {"ruta": "/tmp/a"},
                           "B": {"ruta": "/tmp/b"}}, "Oscuro")

        # The window only knows about "A" (its list predates "B").
        proyectos.guardar_config_proyecto({"A": {"ruta": "/tmp/a"}},
                                          "A", {"tema": "X"})

        with open(reg, encoding="utf-8") as f:
            datos = json.load(f)
        assert set(datos["proyectos"]) == {"A", "B"}
        assert datos["proyectos"]["A"]["config"] == {"tema": "X"}
        # B's entry survives untouched (without config, as it was).
        assert datos["proyectos"]["B"] == {"ruta": "/tmp/b"}
    finally:
        _limpiar(reg)


def test_registrar_no_pierde_los_demas_proyectos():
    """registering a project is a read-modify-write, not a replace."""
    reg = _config_aislada()
    try:
        proyectos.guardar({"A": {"ruta": "/tmp/a"}}, "Oscuro")

        reg_de_vuelta = proyectos.registrar("Nuevo", "/tmp/nuevo")

        with open(reg, encoding="utf-8") as f:
            datos = json.load(f)
        assert set(datos["proyectos"]) == {"A", "Nuevo"}
        assert datos["proyectos"]["Nuevo"]["ruta"] == "/tmp/nuevo"
        assert set(reg_de_vuelta) == {"A", "Nuevo"}
    finally:
        _limpiar(reg)


# ---------- registry permissions (webhook tokens) ----------
#
# The registry stores telegram_token/whatsapp_token/discord in cleartext. With the
# default umask permissions it came out as 0664, readable by the group. The
# fix: create the temp with 0600 BEFORE writing (replace moves the inode,
# so the destination inherits the mode) and harden old registries in
# verificar_registro.


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows no aplica bits de permiso POSIX (no hay 0600)")
def test_escribir_deja_el_registro_en_0600():
    """Neither the lax umask nor the temp must leave group/other permissions."""
    reg = _config_aislada()
    try:
        umask_previo = os.umask(0o022)  # default, permissive umask
        try:
            proyectos.guardar({"A": {"ruta": "/tmp/a", "config": {
                "webhooks": {"telegram_token": "123:abc"}}}}, "Oscuro")
        finally:
            os.umask(umask_previo)

        modo = os.stat(reg).st_mode & 0o777
        assert modo == 0o600, f"permisos del registro: {modo:04o}, esperado 0600"
    finally:
        _limpiar(reg)


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows no aplica bits de permiso POSIX (no hay 0600)")
def test_verificar_registro_endurece_un_registro_antiguo():
    """A legacy proyectos.json (0664) is hardened on startup."""
    reg = _config_aislada()
    try:
        os.chmod(reg, 0o664)
        proyectos.verificar_registro()  # does not raise: the JSON is valid

        modo = os.stat(reg).st_mode & 0o777
        assert modo == 0o600, f"tras verificar: {modo:04o}, esperado 0600"
    finally:
        _limpiar(reg)


if __name__ == "__main__":
    test_guardar_config_no_reañade_proyecto_quitado()
    test_guardar_config_sigue_guardando_proyectos_existentes()
    print("\nTests de regresión de proyectos.py PASARON")
