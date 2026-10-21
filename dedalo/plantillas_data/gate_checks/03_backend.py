# 03_backend.py — Starts the backend and checks that it responds and serves endpoints.
# Port of 03_backend.sh for the portable orchestrator (Windows without bash).
#
#   SERVE_CMD    command to start the backend ("" = check is skipped)
#   SERVE_URL    base URL to call (e.g.: http://localhost:8000)
#   TOKEN_URL    login endpoint to obtain a token ("" = no auth)
#   USUARIO/CLAVE login credentials
#   ENDPOINTS    list "ep1 ep2 ..." (joined as $SERVE_URL/api/$ep)
#
# If endpoints.txt exists at the root, it takes priority (gate_env resolves it).
import json
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


def _http(url, headers=None, body=None):
    """Returns (code, body). code 0 = no HTTP response (000)."""
    datos = body.encode("utf-8") if isinstance(body, str) else body
    req = urllib.request.Request(url, data=datos, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.getcode(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            cuerpo = e.read().decode("utf-8", "replace")
        except Exception:
            cuerpo = ""
        return e.code, cuerpo
    except Exception:
        return 0, ""


def _responde(url):
    return _http(url)[0] != 0


def _resumen(texto):
    return texto.replace("\n", " ")[:200]


def _puerto(serve_url):
    m = re.search(r":(\d+)", serve_url or "")
    return int(m.group(1)) if m else None


def _es_local(serve_url):
    host = (urlparse(serve_url or "").hostname or "").lower()
    if not host:
        host = (serve_url or "").split(":")[0].strip("[]").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def _puerto_ocupado(serve_url):
    """True only for a LOCAL port with something listening.

    A remote SERVE_URL is not probed: `lsof` cannot see it and the check must
    never make decisions about ports on another machine.
    """
    puerto = _puerto(serve_url)
    if not puerto or not _es_local(serve_url):
        return False
    host = (urlparse(serve_url or "").hostname or "").lower() or "127.0.0.1"
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    try:
        with socket.create_connection((host, puerto), timeout=0.5):
            return True
    except OSError:
        return False


def _pids_puerto(serve_url):
    """PIDs listening on the local port, for diagnostics only (never killed)."""
    puerto = _puerto(serve_url)
    if not puerto or not shutil.which("lsof"):
        return []
    try:
        salida = subprocess.run(
            ["lsof", "-ti", f":{puerto}"], capture_output=True, text=True)
    except OSError:
        return []
    return [p for p in salida.stdout.split() if p.strip()]


def _token(env):
    if not env.token_url:
        return ""
    body = "{}"
    if env.usuario:
        body = json.dumps({"username": env.usuario, "password": env.clave})
    code, cuerpo = _http(env.token_url, {"Content-Type": "application/json"}, body)
    try:
        d = json.loads(cuerpo)
        return d.get("access") or d.get("token") or d.get("token_type", "")
    except Exception:
        print(f"[GATE] \u2717 no se obtuvo token en {env.token_url} (HTTP {code})")
        if cuerpo:
            print(f"[GATE]   respuesta: {_resumen(cuerpo)}")
        return ""


def run(env):
    if env.serve_cmd is None:
        env.aviso("SERVE_CMD no configurado, se omite el check de backend")
        return 0

    base = env.serve_url or "http://localhost:8000"
    proc = None
    if _puerto_ocupado(env.serve_url):
        if _responde(base + "/"):
            env.aviso(
                f"ya hay un backend respondiendo en {base}; "
                "se reutiliza sin liberar el puerto")
        else:
            pids = _pids_puerto(env.serve_url)
            detalle = f" (PID(s): {', '.join(pids)})" if pids else ""
            env.fail(
                f"puerto {_puerto(env.serve_url)} ocupado{detalle} "
                f"y no responde HTTP en {base}")
            env.aviso(
                "libéralo o cambia SERVE_URL; el gate no mata procesos por puerto")
            return 1
    else:
        proc = env.lanzar(env.serve_cmd)
    try:
        for _ in range(15):
            if _responde(base + "/"):
                break
            time.sleep(1)
        if not _responde(base + "/"):
            env.fail(f"backend no responde en {base}")
            return 1
        env.ok(f"backend responde en {base}")

        token = ""
        if env.token_url:
            token = _token(env)
            if not token:
                return 1
            env.ok(f"token JWT en {env.token_url}")

        if not env.endpoints:
            env.aviso("sin endpoints configurados; solo comprobación de arranque")
            return 0

        err = 0
        for ep in env.endpoints:
            url = ep if ep.startswith("http") else f"{base}/api/{ep}"
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            code, cuerpo = _http(url, headers)
            if 200 <= code < 300:
                env.ok(url)
            else:
                env.fail(f"{url} (HTTP {code})")
                if cuerpo:
                    print(f"[GATE]   respuesta: {_resumen(cuerpo)}")
                err = 1
        return 1 if err else 0
    finally:
        if proc is not None:
            env.detener(proc)
