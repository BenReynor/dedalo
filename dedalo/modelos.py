"""Query of the models available in opencode.

The list changes with every opencode version, so it is queried live with
`opencode models`. The results are cached during the session: the UI must not
launch repeated subprocesses while building the selectors. The app's button
calls `invalidar_cache()` before refreshing.

For providers without credentials (openai, anthropic, ...) the models.dev
catalog is used (the same source opencode uses), cached on disk.
"""

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request

from . import configuracion as cfg

CATALOGO_URL = "https://models.dev/api.json"
CATALOGO_HORAS = 24 * 7

RUTAS_OPENCODE = [
    "~/.opencode/bin/opencode",
    "~/.local/bin/opencode",
    "/usr/local/bin/opencode",
    "/opt/opencode/bin/opencode",
]


def _binario_en(ruta_base):
    """`ruta_base` if it exists, trying the Windows executable suffixes.

    On Windows CLIs are usually opencode.exe/opencode.cmd (PATHEXT), the
    extensionless `~/.agente/bin/agente` does not exist and os.access(X_OK)
    means nothing. shutil.which already resolves PATHEXT for what is on the
    PATH; this covers the absolute-path fallbacks.
    """
    sufijos = ("", ".exe", ".cmd", ".bat") if os.name == "nt" else ("",)
    for sufijo in sufijos:
        cand = ruta_base + sufijo
        if os.path.isfile(cand) and (
            os.name == "nt" or os.access(cand, os.X_OK)
        ):
            return cand
    return ""


ALIAS_CLAUDE = ("haiku", "sonnet", "opus")

PROVEEDORES_CATALOGO = [
    "opencode", "google", "openai", "anthropic", "xai", "groq",
    "together", "deepseek", "azure", "bedrock", "ollama", "lmstudio",
    "mistral", "github",
]

_modelos: list[str] | None = None
_proveedores: list[str] | None = None
_modelos_por_proveedor: dict[str, list[str]] = {}


def _cli_opencode():
    encontrado = shutil.which("opencode")
    if encontrado:
        return encontrado
    for ruta in RUTAS_OPENCODE:
        expandida = _binario_en(os.path.expanduser(ruta))
        if expandida:
            return expandida
    return "opencode"


def _consultar_modelos():
    try:
        out = subprocess.run([_cli_opencode(), "models"], capture_output=True,
                             text=True, timeout=cfg.TIMEOUT_OPENCODE)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    return [linea.strip() for linea in out.stdout.splitlines()
            if "/" in linea
            and not linea.startswith(("#", "--", "Usage"))]


def lista_modelos(forzar=False):
    """Returns the list of provider/model models that opencode supports."""
    global _modelos
    if _modelos is None or forzar:
        _modelos = _consultar_modelos() or []
    return _modelos


def _ruta_catalogo():
    return cfg.CATALOGO_MODELOS


_catalogo_cache: dict[str, object] = {"clave": None, "datos": None}


def _leer_catalogo_disco(ruta):
    """Reads the catalog and memoizes it by (size, mtime).

    The catalog is several MB; provider/model selectors ask for it repeatedly
    while the user browses. Without this memo every call re-read and re-parsed
    the whole JSON on the UI thread.
    """
    try:
        st = os.stat(ruta)
        clave = (st.st_size, st.st_mtime_ns)
    except OSError:
        return None
    if _catalogo_cache["clave"] == clave:
        return _catalogo_cache["datos"]
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(datos, dict):
        return None
    _catalogo_cache["clave"] = clave
    _catalogo_cache["datos"] = datos
    return datos


def leer_catalogo():
    """models.dev catalog cached on disk (downloads it if missing or stale)."""
    ruta = _ruta_catalogo()
    if (os.path.exists(ruta)
            and time.time() - os.path.getmtime(ruta) < CATALOGO_HORAS * 3600):
        datos = _leer_catalogo_disco(ruta)
        if datos is not None:
            return datos
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        req = urllib.request.Request(
            CATALOGO_URL,
            headers={"User-Agent": "dedalo/2.0"}
        )
        with urllib.request.urlopen(req, timeout=cfg.TIMEOUT_CATALOGO) as r:
            datos = json.loads(r.read().decode("utf-8"))
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
        _catalogo_cache["clave"] = None  # force a fresh read on next call
        return datos
    except (OSError, ValueError):
        datos = _leer_catalogo_disco(ruta)
        return datos if datos is not None else {}


def _consultar_proveedores():
    detectados = sorted({m.split("/", 1)[0] for m in lista_modelos()
                         if "/" in m})
    catalogo = leer_catalogo()
    for prov in PROVEEDORES_CATALOGO:
        if prov in catalogo and prov not in detectados:
            detectados.append(prov)
    return detectados


def nombres_proveedores(forzar=False):
    """Available companies: those from opencode plus those from the models.dev catalog."""
    global _proveedores
    if _proveedores is None or forzar:
        _proveedores = _consultar_proveedores()
    return _proveedores


def _consultar_proveedor(proveedor):
    try:
        out = subprocess.run([_cli_opencode(), "models", proveedor],
                             capture_output=True, text=True,
                             timeout=cfg.TIMEOUT_OPENCODE)
        if out.returncode == 0:
            modelos = [linea.strip().split("/", 1)[1] for linea in
                       out.stdout.splitlines() if "/" in linea.strip()]
            if modelos:
                return modelos
    except (OSError, subprocess.TimeoutExpired):
        pass
    catalogo = leer_catalogo()
    prov = catalogo.get(proveedor)
    if isinstance(prov, dict) and isinstance(prov.get("models"), dict):
        return sorted(prov["models"])
    return []


def lista_modelos_proveedor(proveedor, forzar=False):
    """Models of a provider: `opencode models <prov>` and, if that fails, models.dev."""
    proveedor = (proveedor or "").strip()
    if not proveedor:
        return []
    if forzar:
        _modelos_por_proveedor.pop(proveedor, None)
    if proveedor not in _modelos_por_proveedor:
        lista = _consultar_proveedor(proveedor)
        if proveedor == "anthropic":
            # Aliases the claude CLI resolves to the current model of each
            # tier; catalog ids can lag behind the CLI.
            lista = [a for a in ALIAS_CLAUDE if a not in lista] + lista
        _modelos_por_proveedor[proveedor] = lista
    return _modelos_por_proveedor[proveedor]


def ruta_binario(nombre):
    """Absolute path of an agent's CLI, or "" if it is not installed.

    Looks in the PATH and, since agent CLIs are usually installed in
    ~/.<agente>/bin without touching the shell PATH, tries that fallback.
    """
    ruta = shutil.which(nombre)
    if ruta:
        return ruta
    if nombre in cfg.AGENTES_DISPONIBLES:
        candidata = _binario_en(os.path.expanduser(f"~/.{nombre}/bin/{nombre}"))
        if candidata:
            return candidata
    return ""


def agentes_instalados(preferidos=None):
    """CLI agents available on this machine, in order of preference.

    `preferidos` = order to respect (by default, AGENTES_PREFERIDOS). Returns
    only those that actually exist, so the GUI does not offer an agent that
    cannot be run.
    """
    orden = preferidos or cfg.AGENTES_PREFERIDOS
    return [a for a in orden if a in cfg.AGENTES_DISPONIBLES and ruta_binario(a)]


def agentes_operativos(preferidos=None):
    """Installed agents that can actually be worked with.

    Leaves out those that have the binary installed but no session: choosing
    one would abort the loop on the first iteration. Those with an unknown session
    are kept (an agent is not discarded just for not having been tested).
    """
    return [a for a in agentes_instalados(preferidos)
            if sesion_agente(a) is not False]


def agente_por_defecto():
    """Agent to use when the user leaves the selector on 'auto'."""
    operativos = agentes_operativos()
    return operativos[0] if operativos else ""


# ---------- CLI session ----------

# Same signs that dedalo.sh detects when reading the agent output: if the
# CLI complains about credentials, there is no session to work with.
PATRONES_SIN_SESION = (
    r"not logged in", r"please run /login", r"not authenticated",
    r"unauthorized", r"\b401\b", r"authentication_error",
    r"invalid.?api.?key", r"missing.?api.?key",
    r"OPENAI_API_KEY", r"ANTHROPIC_API_KEY", r"please set your api key",
    r"run .?codex login",
)

# Session probe per agent. opencode is queried without inference (listing
# credentials); codex and claude do not expose a reliable session state, so
# they are sent a minimal prompt: if there is no session they fail before inferring.
SONDA_SESION = {
    "opencode": (["auth", "list"], 8),
    "codex": (["exec", "--skip-git-repo-check", "ping"], 20),
    "claude": (["-p", "--output-format", "text", "ping"], 20),
}

_sesiones = {}


def _sesion_opencode(salida):
    """Session state from `opencode auth list`.

    That command always exits 0 and prints two sections: stored credentials and
    environment variables. It is NOT an error report, so PATRONES_SIN_SESION
    must not be applied here: the listing contains names such as
    `OPENAI_API_KEY`, which are credentials, not a missing session. Counting
    them is the only reliable signal.
    """
    if re.search(r"not logged in|please run /login", salida, re.I):
        return False
    # "<n> credentials" / "<n> environment variable(s)".
    ceros = {}
    for clave, patron in (("cred", r"(\d+)\s+credentials?"),
                          ("env", r"(\d+)\s+environment\s+variables?")):
        m = re.search(patron, salida, re.I)
        ceros[clave] = int(m.group(1)) if m else None
        if ceros[clave]:
            return True
    # Both sections explicitly say 0: there is nothing to authenticate with.
    if ceros["cred"] == 0 and ceros["env"] == 0:
        return False
    return None


def sesion_agente(nombre):
    """True/False if the agent has a session; None if it cannot be known.

    False = installed but not logged in (it should not be offered for work).
    None = unknown: it is offered anyway, because discarding it would be worse.
    The result is cached during the session (invalidar_cache() clears it).
    """
    if nombre in _sesiones:
        return _sesiones[nombre]
    _sesiones[nombre] = None
    if not ruta_binario(nombre) or nombre not in SONDA_SESION:
        return _sesiones[nombre]
    args, timeout = SONDA_SESION[nombre]
    try:
        r = subprocess.run([ruta_binario(nombre)] + args, capture_output=True,
                           text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return _sesiones[nombre]
    salida = f"{r.stdout}\n{r.stderr}"
    if nombre == "opencode":
        _sesiones[nombre] = _sesion_opencode(salida)
    elif re.search("|".join(PATRONES_SIN_SESION), salida, re.I):
        _sesiones[nombre] = False
    elif r.returncode == 0 or salida.strip():
        _sesiones[nombre] = True
    return _sesiones[nombre]


def estado_agentes(preferidos=None):
    """Record for each agent: installed, path and session state."""
    return [{
        "nombre": a,
        "ruta": ruta_binario(a),
        "instalado": bool(ruta_binario(a)),
        "sesion": sesion_agente(a),
    } for a in (preferidos or cfg.AGENTES_PREFERIDOS)
        if a in cfg.AGENTES_CONOCIDOS]


def invalidar_cache():
    """Forgets the cached results; the next query goes back to the network."""
    global _modelos, _proveedores
    _modelos = None
    _proveedores = None
    _modelos_por_proveedor.clear()
    _sesiones.clear()


def sugerido(modelos):
    """Picks a default model: the suggested one if present, otherwise the first."""
    if not modelos:
        return cfg.MODELO_SUGERIDO
    if cfg.MODELO_SUGERIDO in modelos:
        return cfg.MODELO_SUGERIDO
    return modelos[0]
