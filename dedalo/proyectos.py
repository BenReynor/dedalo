"""Project registry, theme and thermal protection for the Dédalo panel.

Stored in ~/.config/dedalo/proyectos.json and shared by all
the projects managed from the panel.

Integrity: the registry is ALWAYS written atomically (writing to a
temporary file and os.replace), so that an abrupt shutdown mid-save
cannot truncate it. And if the JSON ever became corrupted, main()
FAILS BEFORE starting up instead of swallowing the error and overwriting it with an
empty registry (which is how all the user's projects were lost).
"""

import json
import os
import shutil

from . import configuracion as cfg


class RegistroCorrupto(Exception):
    """The project registry is not valid JSON.

    Carries the path of the original file and that of the .corrupto
    backup copy. The original is NOT deleted upon detection: only when the user
    agrees to start from scratch (descartar_registro_corrupto).
    """

    def __init__(self, ruta, copia):
        super().__init__(f"registro de proyectos corrupto: {ruta}")
        self.ruta = ruta
        self.copia = copia


def _copia_de_seguridad(corrupto):
    """Copies the registry to <registro>.corrupto without overwriting the previous one.

    Returns the path of the created copy. The suffixes are .corrupto,
    .corrupto.2, .corrupto.3... so that not even the first version is lost.
    """
    n = 1
    while True:
        sufijo = "" if n == 1 else f".{n}"
        cand = f"{corrupto}.corrupto{sufijo}"
        if not os.path.exists(cand):
            shutil.copy2(corrupto, cand)
            return cand
        n += 1


def verificar_registro():
    """Validates the registry BEFORE starting up. Raises RegistroCorrupto if it is not
    valid JSON, leaving a .corrupto copy of the data beforehand.

    Does not modify the original on purpose: if the user closes the app and
    opens it again, the warning repeats instead of silently losing the registry
    on the first save.
    """
    if not os.path.exists(cfg.REGISTRO):
        return
    # A registry created by an earlier version may end up as 0664 and that is where
    # the webhook tokens live: permissions are hardened upon detection.
    try:
        os.chmod(cfg.REGISTRO, 0o600)
    except OSError:
        pass
    try:
        with open(cfg.REGISTRO, encoding="utf-8") as f:
            json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RegistroCorrupto(cfg.REGISTRO, _copia_de_seguridad(cfg.REGISTRO)) from exc


def descartar_registro_corrupto():
    """Deletes the corrupted registry (its data stays in the .corrupto copy)."""
    try:
        os.remove(cfg.REGISTRO)
    except FileNotFoundError:
        pass


def _escribir(datos):
    """Writes the registry atomically and privately.

    json.dump goes first to the temporary file and only afterwards does os.replace()
    move it onto the destination: replace is atomic on the same filesystem, so a
    power cut or a kill mid-write leaves the previous registry
    intact instead of a truncated, unreadable JSON.

    The temporary file is created with 0o600 permissions (user only) BEFORE
    writing, and since replace moves the inode, the destination inherits those
    permissions: the webhook tokens the registry stores do not end up
    readable by the group or by other users (they used to come out as 0664).
    """
    os.makedirs(cfg.CONFIG_DIR, exist_ok=True, mode=0o700)
    tmp = f"{cfg.REGISTRO}.{os.getpid()}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        # In case a lax umask or an inherited temporary file has loosened the mode.
        os.chmod(tmp, 0o600)
        os.replace(tmp, cfg.REGISTRO)
    except BaseException:
        # Includes TypeError/ValueError from json.dump with non-serializable data:
        # the already-created temporary file must be removed anyway or garbage accumulates in ~/.config.
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _leer_archivo():
    try:
        with open(cfg.REGISTRO, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def cargar():
    return _leer_archivo().get("proyectos", {})


def leer_tema():
    return _leer_archivo().get("tema", cfg.TEMA_DEFECTO)


def leer_seguridad():
    datos = _leer_archivo().get("seguridad", {})
    seg = dict(cfg.SEGURIDAD_DEFECTO)
    seg.update(datos)
    return seg


def leer_modelos():
    """Selected models (task/reviewer) saved between sessions."""
    return _leer_archivo().get("modelos", {})


def leer_webhooks():
    """Global webhook configuration (Telegram, Discord, WhatsApp)."""
    return _leer_archivo().get("webhooks", {})


def leer_sidebar_ancho():
    """Persisted sidebar width (px)."""
    return _leer_archivo().get("sidebar_ancho", cfg.SIDEBAR_ANCHO)


def guardar_sidebar_ancho(ancho: int):
    """Saves the sidebar width."""
    datos = _leer_archivo()
    datos["sidebar_ancho"] = ancho
    _escribir(datos)


def leer_config_proyecto(nombre):
    """Configuration saved for a specific project (without merging).

    The global values (tema/seguridad/webhooks/modelos) act as the
    base; whatever is inside proyectos[nombre]["config"] wins over that base.
    """
    proy = cargar().get(nombre)
    return proy.get("config", {}) if proy else {}


def guardar_config_proyecto(proyectos, nombre, config):
    """Persists the project's specific configuration alongside its registry entry.

    Reads the registry from disk and touches ONLY this project: a window whose
    in-memory list is stale must not overwrite projects that another process
    (the MCP server, a second window) added or removed meanwhile. That is how a
    long-running window used to wipe the whole registry on a theme change.

    Does not re-add the project if it is neither on disk nor in the passed dict
    (e.g. after "Quitar"): a removed name must not reappear when saving config.
    """
    datos = _leer_archivo()
    reg = datos.get("proyectos", {})
    if nombre not in reg and nombre not in proyectos:
        return
    entrada = reg.get(nombre) or dict(proyectos.get(nombre) or {})
    entrada["config"] = config
    reg[nombre] = entrada
    datos["proyectos"] = reg
    _escribir(datos)


def registrar(nombre, ruta):
    """Registers a project (read-modify-write) without touching the others.

    A fresh read before the write keeps entries added by another process; the
    previous read-then-write from the caller's copy lost them.
    """
    datos = _leer_archivo()
    reg = datos.get("proyectos", {})
    entrada = dict(reg.get(nombre) or {})
    entrada["ruta"] = ruta
    reg[nombre] = entrada
    datos["proyectos"] = reg
    _escribir(datos)
    return reg


def guardar(proyectos, tema=None, seguridad=None, webhooks=None, modelos=None,
            exacto=False):
    """Saves the project list and, optionally, the global settings.

    By default the write is a UNION with what is already on disk: entries added
    by another process are kept instead of being clobbered by a stale in-memory
    copy. Pass `exacto=True` to replace the list as-is, which is what actually
    removes a project.
    """
    datos = _leer_archivo()
    if exacto:
        datos["proyectos"] = proyectos
    else:
        reg = dict(datos.get("proyectos", {}))
        reg.update(proyectos)
        datos["proyectos"] = reg
    if tema:
        datos["tema"] = tema
    if seguridad is not None:
        datos["seguridad"] = seguridad
    if webhooks is not None:
        datos["webhooks"] = webhooks
    if modelos is not None:
        datos["modelos"] = modelos
    _escribir(datos)
