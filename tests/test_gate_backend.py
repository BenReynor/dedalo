#!/usr/bin/env python3
"""Tests for 03_backend.sh: the gate cannot go green with a broken backend.

Regression of the bug: the four `curl` calls were `curl -s`, which returns 0
even if the response is 404 or 500. The endpoints loop marked `ok` for a 404
and the check ended with exit 0, so a backend with broken routes passed the
gate.

Adding `-f` blindly does not work either: it aborts with "HTTP 404" and discards
the body, which is where FastAPI/Django explain the reason ("detail": "not
found"). The solution is to read the code with `-w '%{http_code}'` and keep the
body for diagnosis.

A real HTTP server is started (http.server in a thread) to test the codes for
real, instead of simulating curl.

Port safety: the check must never kill by port. When a healthy backend already
answers on SERVE_URL it is reused; when the port is occupied by something that
does not answer HTTP, the check fails with a diagnostic and leaves it alive.
"""

import http.server
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RAIZ = Path(__file__).resolve().parent.parent
CHECK = RAIZ / "dedalo" / "plantillas_data" / "gate_checks" / "03_backend.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt",
    reason="harness POSIX (gate.sh en bash): se valida en Linux")

PENDIENTE = 100  # port with no service, to test "no responde"


class _Handler(http.server.BaseHTTPRequestHandler):
    """Responds with the code set for the route in `self.server.respuestas`."""

    def do_GET(self):
        self._responder()

    def do_POST(self):
        self._responder()

    def _responder(self):
        status, cuerpo = self.server.respuestas.get(
            self.path.split("?")[0], (404, "no encontrado"))
        datos = cuerpo.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def servidor():
    """Local HTTP server in a thread; `respuestas` is filled in per test."""
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.respuestas = {}
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _preparar(tmp_path, endpoints=None):
    """Copies the check to a temp dir. Returns the project and an empty PATH dir."""
    proyecto = tmp_path / "proyecto"
    proyecto.mkdir(exist_ok=True)
    shutil.copy2(CHECK, proyecto / "check.sh")
    if endpoints is not None:
        (proyecto / "endpoints.txt").write_text(
            "".join(f"{e}\n" for e in endpoints), encoding="utf-8")
    binstub = tmp_path / "bin"
    binstub.mkdir(exist_ok=True)
    return proyecto, binstub


def _correr(proyecto, binstub, url, endpoints=None, **extra):
    """Runs the real check. `url` is the server base (or a dead port)."""
    env = {
        "PATH": f"{binstub}{os.pathsep}{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/tmp"),
        "PROYECTO": str(proyecto),
        "SERVE_CMD": "true",
        "SERVE_URL": url,
        "TOKEN_URL": "",
        "USUARIO": "",
        "CLAVE": "",
        "ENDPOINTS": "",
        "PY_BACKEND": sys.executable,
    }
    env.update(extra)
    res = subprocess.run(
        ["bash", str(proyecto / "check.sh")],
        capture_output=True, text=True, timeout=90,
        cwd=str(proyecto), env=env,
    )
    return res.returncode, res.stdout + res.stderr


def _url(servidor):
    return f"http://127.0.0.1:{servidor.server_address[1]}"


def _con_respuestas(servidor, respuestas):
    servidor.respuestas = respuestas


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _lanzar_ocupante(tmp_path, puerto):
    """Separate process that listens but never answers HTTP.

    It is deliberately NOT pytest itself: if a regression reintroduces the
    port kill, this process dies and the assertion fails, instead of killing
    the test runner.
    """
    guion = tmp_path / "ocupante.py"
    guion.write_text(
        "import socket, sys, time\n"
        "s = socket.socket()\n"
        "s.bind(('127.0.0.1', int(sys.argv[1])))\n"
        "s.listen(1)\n"
        "time.sleep(60)\n",
        encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(guion), str(puerto)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", puerto), timeout=0.1):
                return proc
        except OSError:
            time.sleep(0.1)
    proc.terminate()
    pytest.fail("el proceso ocupante no llegó a escuchar")


def _cargar_backend_py():
    ruta = RAIZ / "dedalo" / "plantillas_data" / "gate_checks" / "03_backend.py"
    spec = importlib.util.spec_from_file_location("gate_backend_py", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class _EnvPy:
    """Minimal Entorno for 03_backend.py, recording what the check does."""

    def __init__(self, url):
        self.serve_cmd = object()
        self.serve_url = url
        self.token_url = ""
        self.endpoints = []
        self.avisos = []
        self.fallos = []
        self.oks = []
        self.lanzado = False

    def aviso(self, mensaje):
        self.avisos.append(mensaje)

    def ok(self, mensaje):
        self.oks.append(mensaje)

    def fail(self, mensaje):
        self.fallos.append(mensaje)

    def lanzar(self, cmd):
        self.lanzado = True
        raise AssertionError("no debía lanzar un backend con el puerto ocupado")

    def detener(self, proc):
        return True


# ─── Port safety: reuse or fail, never kill by port ───────────────────────

def test_reutiliza_backend_sano_sin_matarlo(tmp_path, servidor):
    """A healthy server already on SERVE_URL is reused, not killed."""
    _con_respuestas(servidor, {"/": (200, "{}")})
    proyecto, binstub = _preparar(tmp_path, [])
    rc, out = _correr(proyecto, binstub, _url(servidor))
    assert rc == 0, out
    assert "se reutiliza" in out
    assert "liberando" not in out


@pytest.mark.skipif(shutil.which("lsof") is None, reason="diagnóstico con lsof")
def test_puerto_ocupado_sin_http_falla_sin_matarlo(tmp_path):
    """Occupied by a non-HTTP process: fail and leave that process alive."""
    puerto = _puerto_libre()
    proc = _lanzar_ocupante(tmp_path, puerto)
    try:
        proyecto, binstub = _preparar(tmp_path, [])
        rc, out = _correr(proyecto, binstub,
                          f"http://127.0.0.1:{puerto}")
        assert rc == 1, out
        assert "ocupado" in out
        assert "no mata procesos por puerto" in out
        assert proc.poll() is None, "el gate mató un proceso ajeno"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def test_py_reutiliza_backend_sano_sin_lanzar(servidor):
    """The portable .py check follows the same safe rule."""
    _con_respuestas(servidor, {"/": (200, "{}")})
    modulo = _cargar_backend_py()
    env = _EnvPy(_url(servidor))
    assert modulo.run(env) == 0
    assert env.lanzado is False
    assert any("se reutiliza" in a for a in env.avisos)


def test_py_puerto_ocupado_sin_http_falla_sin_lanzar(monkeypatch):
    """The .py check must not launch or kill when the port is not HTTP."""
    modulo = _cargar_backend_py()
    monkeypatch.setattr(modulo, "_http", lambda *a, **k: (0, ""))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        puerto = s.getsockname()[1]
        env = _EnvPy(f"http://127.0.0.1:{puerto}")
        assert modulo.run(env) == 1
    assert env.lanzado is False
    assert any("ocupado" in f for f in env.fallos)


# ─── Endpoints: 404/500 are no longer green ────────────────────────────────

def test_endpoint_404_falla_el_gate(tmp_path, servidor):
    """An endpoint that returns 404 must make the check fail."""
    _con_respuestas(servidor, {"/api/roto": (404, '{"detail":"no encontrado"}')})
    proyecto, binstub = _preparar(tmp_path, ["roto"])
    rc, out = _correr(proyecto, binstub, _url(servidor))
    assert rc == 1, f"se esperaba rc=1 con un 404:\n{out}"
    assert "✗" in out
    assert "404" in out


def test_endpoint_500_falla_con_el_cuerpo_en_el_log(tmp_path, servidor):
    """A 500 fails and also shows the body, which is the useful diagnosis."""
    _con_respuestas(servidor,
                    {"/api/error": (500, '{"detail":"boom en la base de datos"}')})
    proyecto, binstub = _preparar(tmp_path, ["error"])
    rc, out = _correr(proyecto, binstub, _url(servidor))
    assert rc == 1, f"se esperaba rc=1 con un 500:\n{out}"
    assert "500" in out
    assert "boom en la base de datos" in out, (
        f"el cuerpo del error no llegó al log, no hay diagnóstico:\n{out}")


def test_endpoint_404_no_pisa_al_siguiente(tmp_path, servidor):
    """A broken endpoint marks an error, but the healthy ones are still evaluated."""
    _con_respuestas(servidor, {
        "/api/roto": (404, "nope"),
        "/api/bueno": (200, '{"ok":true}'),
    })
    proyecto, binstub = _preparar(tmp_path, ["roto", "bueno"])
    rc, out = _correr(proyecto, binstub, _url(servidor))
    assert rc == 1
    assert "✓" in out and "api/bueno" in out


def test_endpoints_sanos_pasan(tmp_path, servidor):
    """With all endpoints in 2xx, the check passes."""
    _con_respuestas(servidor, {
        "/": (200, "{}"),
        "/api/uno": (200, '{"ok":true}'),
        "/api/dos": (201, '{"ok":true}'),
    })
    proyecto, binstub = _preparar(tmp_path, ["uno", "dos"])
    rc, out = _correr(proyecto, binstub, _url(servidor))
    assert rc == 0, f"se esperaba rc=0:\n{out}"
    assert "✗" not in out


def test_endpoint_307_falla(tmp_path, servidor):
    """A 3xx is considered a misspelled route and fails, stating the code."""
    _con_respuestas(servidor, {"/api/sin-barra": (307, "")})
    proyecto, binstub = _preparar(tmp_path, ["sin-barra"])
    rc, out = _correr(proyecto, binstub, _url(servidor))
    assert rc == 1
    assert "307" in out


def test_cuerpo_multilinea_se_resume_en_una_linea(tmp_path, servidor):
    """A body with line breaks does not break the log format."""
    _con_respuestas(servidor, {"/api/largo": (500, json_dumps_multilinea())})
    proyecto, binstub = _preparar(tmp_path, ["largo"])
    rc, out = _correr(proyecto, binstub, _url(servidor))
    assert rc == 1
    lineas = [ln for ln in out.splitlines() if "respuesta:" in ln]
    assert lineas, f"no se imprimió el resumen del cuerpo:\n{out}"
    assert len(lineas[0]) < 260, "el resumen no se recortó"


def json_dumps_multilinea():
    return '{"detail": "linea 1",\n "otro": "linea 2",\n "cola": "linea 3"}'


# ─── Startup: a 404 at the root is NOT a down backend ─────────────────

def test_raiz_404_no_se_toma_por_backend_caido(tmp_path, servidor):
    """What proves the server started is that it responds with HTTP, not 2xx.

    An API without a "/" route returns 404 at the root and is perfectly healthy (it is
    normal in FastAPI and Express). If the check demanded 2xx here, it would take down almost
    all real projects.
    """
    _con_respuestas(servidor, {
        "/": (404, "Not Found"),
        "/api/ok": (200, "{}"),
    })
    proyecto, binstub = _preparar(tmp_path, ["ok"])
    rc, out = _correr(proyecto, binstub, _url(servidor))
    assert rc == 0, f"un 404 en la raíz no debe tumbar el gate:\n{out}"
    assert "backend responde" in out


def test_sin_respuesta_http_falla(tmp_path):
    """If there is no response (000), the backend is indeed down and a warning is given."""
    proyecto, binstub = _preparar(tmp_path, [])
    rc, out = _correr(proyecto, binstub, f"http://127.0.0.1:{PENDIENTE}")
    assert rc == 1
    assert "no responde" in out


# ─── Token: a 401 must explain why ────────────────────────────────

def test_token_401_falla_con_el_mensaje_del_servidor(tmp_path, servidor):
    """Bad credentials: the response body says so and it must be shown."""
    _con_respuestas(servidor, {"/api/token": (401, '{"detail":"credenciales incorrectas"}')})
    proyecto, binstub = _preparar(tmp_path, [])
    rc, out = _correr(proyecto, binstub, _url(servidor),
                      TOKEN_URL=f"{_url(servidor)}/api/token")
    assert rc == 1, f"se esperaba rc=1 con un 401 en el login:\n{out}"
    assert "401" in out
    assert "credenciales incorrectas" in out


def test_token_valido_llega_a_los_endpoints(tmp_path, servidor):
    """With a valid token, the endpoints are requested authenticated."""
    pedidos = []
    original = _Handler._responder

    def _spy(self):
        pedidos.append((self.path, self.headers.get("Authorization")))
        return original(self)

    _Handler._responder = _spy
    try:
        _con_respuestas(servidor, {
            "/api/token": (200, '{"access":"jwt-falso-123"}'),
            "/api/privado": (200, "{}"),
        })
        proyecto, binstub = _preparar(tmp_path, ["privado"])
        rc, out = _correr(proyecto, binstub, _url(servidor),
                          TOKEN_URL=f"{_url(servidor)}/api/token",
                          USUARIO="admin", CLAVE="secreto")
    finally:
        _Handler._responder = original

    assert rc == 0, f"se esperaba rc=0:\n{out}"
    auths = [a for ruta, a in pedidos if ruta == "/api/privado"]
    assert auths == ["Bearer jwt-falso-123"], (
        f"el endpoint no se pidió autenticado: {pedidos}")


# ─── Without endpoints and without SERVE_CMD: behavior intact ───────────────

def test_sin_endpoints_solo_comprueba_arranque(tmp_path, servidor):
    """Explicit user decision: empty list = warning, not failure."""
    _con_respuestas(servidor, {"/": (404, "")})
    proyecto, binstub = _preparar(tmp_path, [])
    rc, out = _correr(proyecto, binstub, _url(servidor))
    assert rc == 0, f"sin endpoints no debe fallar:\n{out}"
    assert "sin endpoints configurados" in out


def test_serve_cmd_vacio_omite_el_check(tmp_path):
    """An empty SERVE_CMD still omits the check entirely."""
    proyecto, binstub = _preparar(tmp_path, [])
    rc, out = _correr(proyecto, binstub, "", SERVE_CMD="")
    assert rc == 0
    assert "se omite el check de backend" in out


# ─── Isolated execution ───────────────────────────────────────────────────

def test_check_funciona_sin_env_sh(tmp_path, servidor):
    """The check must be able to run on its own, without the `ok` that gate.sh defines.

    Run as a standalone process it does not inherit gate.sh's functions. If
    `ok` were not defined, bash would give rc=127, the check would continue (there is no
    `set -e`) and it would exit 0: green without checking anything.
    """
    _con_respuestas(servidor, {"/": (200, ""), "/api/ok": (200, "{}")})
    proyecto, binstub = _preparar(tmp_path, ["ok"])
    rc, out = _correr(proyecto, binstub, _url(servidor))
    assert rc == 0, out
    assert "[GATE] ✓" in out, f"el check no pudo imprimir su ok: {out}"
    assert "orden no encontrada" not in out
