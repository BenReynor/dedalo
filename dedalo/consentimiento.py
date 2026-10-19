"""First-use consent for the project gate (gate_checks/).

Running the gate executes code that lives in the target repo (gate.sh,
gate_checks/*.sh|.py) with the user's privileges: a cloned repo can
bring arbitrary commands. Before a project's first gate it shows what
is going to be run and requires an explicit decision, which is remembered tied to a
hash of the checks' content: if the checks change, it asks again.

Opt-in without a dialog: `DEDALO_GATE_CONSENT=1` (recommended in CI). Trust is
stored in `~/.config/dedalo/confianza.json` (0o600, outside the repo, so that
the repo itself cannot grant itself the permission).
"""

import hashlib
import json
import os
import tempfile

from . import rutas
from .configuracion import CONFIG_DIR

CONSENT_ENV = "DEDALO_GATE_CONSENT"


def _dir_checks(proyecto):
    return rutas.gate_checks(proyecto)


def ficheros(proyecto):
    """Relative paths of the files under `gate_checks/` (sorted)."""
    base = _dir_checks(proyecto)
    if not os.path.isdir(base):
        return []
    salida = []
    for raiz, _dirs, nombres in os.walk(base):
        for nombre in nombres:
            salida.append(os.path.relpath(os.path.join(raiz, nombre), base))
    return sorted(salida)


def manifest(proyecto):
    """SHA-256 of the `gate_checks/` contents ("" if the directory is absent).

    Includes each file's relative path and the hash of its content, so any
    change (add/remove/edit/rename) yields a different manifest.
    """
    base = _dir_checks(proyecto)
    if not os.path.isdir(base):
        return ""
    h = hashlib.sha256()
    for rel in ficheros(proyecto):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        try:
            with open(os.path.join(base, rel), "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
        except OSError:
            h.update(b"?")
    return h.hexdigest()


def _ruta_confianza():
    return os.path.join(CONFIG_DIR, "confianza.json")


def _leer_confianza():
    try:
        with open(_ruta_confianza(), encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def esta_confiado(proyecto, manifiesto=None):
    """Has the user already approved THIS gate content for THIS project?"""
    manifiesto = manifest(proyecto) if manifiesto is None else manifiesto
    if not manifiesto:
        return True
    return _leer_confianza().get(os.path.abspath(proyecto)) == manifiesto


def confiar(proyecto, manifiesto=None):
    """Persists the approval of the current manifest (atomic write 0o600)."""
    manifiesto = manifest(proyecto) if manifiesto is None else manifiesto
    datos = _leer_confianza()
    datos[os.path.abspath(proyecto)] = manifiesto
    ruta = _ruta_confianza()
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ruta))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, ruta)
        try:
            os.chmod(ruta, 0o600)
        except OSError:
            pass
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def revocar(proyecto):
    """Forgets a project's approval (asks for consent again)."""
    datos = _leer_confianza()
    if datos.pop(os.path.abspath(proyecto), None) is not None:
        ruta = _ruta_confianza()
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2, sort_keys=True)


def concedido(proyecto, entorno=None):
    """Can the gate run?

    True if there are no checks, if `DEDALO_GATE_CONSENT=1` (which also persists
    trust) or if the current manifest has already been approved. False in any
    other case: without consent, the gate of an unknown repo does not run.
    """
    entorno = os.environ if entorno is None else entorno
    if not manifest(proyecto):
        return True
    if str(entorno.get(CONSENT_ENV, "")).strip() == "1":
        try:
            confiar(proyecto)
        except OSError:
            pass
        return True
    return esta_confiado(proyecto)
