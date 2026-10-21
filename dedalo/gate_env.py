"""Environment detection for the portable gate (equivalent to _env.sh).

This module is used by `gate.py` (the portable orchestrator) to prepare the
variables and utilities shared by the `.py` checks, especially on Windows,
where there is no bash for the `gate_checks/*.sh`.

It is a faithful port of `plantillas_data/gate_checks/_env.sh`: same variables,
same detection (Backend/, frontend/, venv, Django, DB/migration/test/backend
commands) and same priorities. The difference is in how the commands are run:
the defaults go as lists (argv, no shell) and only what the user overrides via
the environment is run with a shell.
"""

import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse

from . import rutas


def _es_local(url):
    """True if `url` points at the local machine (where the dev server runs)."""
    host = (urlparse(url or "").hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "[::1]")


@dataclass
class Comando:
    """A command to run: argv (list) or shell (string), and its cwd."""

    argv: list | None = None
    shell: "str | None" = None
    cwd: "str | None" = None


@dataclass
class Entorno:
    """Variables and utilities shared by the `.py` checks."""

    proyecto: str
    backend_dir: str
    frontend_dir: str
    py_backend: str
    py_frontend: str
    db_check: "Comando | None"
    migrate_check: "Comando | None"
    test_cmd: "Comando | None"
    serve_cmd: "Comando | None"
    serve_url: str
    token_url: str
    usuario: str
    clave: str
    endpoints: list

    def ok(self, mensaje):
        print(f"[GATE] \u2713 {mensaje}")

    def fail(self, mensaje):
        print(f"[GATE] \u2717 {mensaje}")

    def aviso(self, mensaje):
        print(f"[GATE] \u26a0 {mensaje}")

    def ejecutar(self, cmd, timeout=None):
        """Runs the command and returns the return code (0 if it is None)."""
        return self.ejecutar_salida(cmd, timeout=timeout)[0]

    def ejecutar_salida(self, cmd, timeout=None):
        """Runs the command and returns (rc, combined stdout+stderr output)."""
        if cmd is None:
            return 0, ""
        if cmd.shell is not None:
            args, usar_shell = cmd.shell, True
        else:
            args, usar_shell = cmd.argv, False
        try:
            p = subprocess.run(
                args, shell=usar_shell, cwd=cmd.cwd or self.proyecto,
                capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, ""
        except OSError as e:
            return 127, str(e)
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    def lanzar(self, cmd):
        """Starts the command in its own session/group. Returns the Popen or None.

        The backend check must be able to stop the server AND the children it
        spawns (reloaders, workers...). A new session on POSIX (a new process
        group on Windows) makes `detener` safe: it only kills what this check
        started, never another process that happens to hold the port.
        """
        if cmd is None:
            return None
        kwargs = dict(
            cwd=cmd.cwd or self.proyecto,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.name == "posix":
            kwargs["start_new_session"] = True
        else:
            kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if cmd.shell is not None:
            return subprocess.Popen(cmd.shell, shell=True, **kwargs)
        return subprocess.Popen(cmd.argv, **kwargs)

    def detener(self, proc, espera=5):
        """Stops the process group started by `lanzar` (TERM, then KILL).

        Returns True when the process is gone. It never looks up a PID by port:
        the target is only the group/session created for this check.
        """
        if proc is None or proc.poll() is not None:
            return True
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                return True
            except OSError:
                try:
                    proc.terminate()
                except OSError:
                    pass
            try:
                proc.wait(timeout=espera)
                return True
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                return False
            return True
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10)
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return False
        return True


def _comando(valor, cwd):
    """User command (str -> shell) or default (list -> argv)."""
    if not valor:
        return None
    if isinstance(valor, str):
        return Comando(shell=valor, cwd=cwd)
    return Comando(argv=list(valor), cwd=cwd)


def _db_por_defecto():
    """Default DB_CHECK for Django (port of the _env.sh default).

    Same one-liner as the script: it only checks pg_isready, and it is run with
    a shell (like the rest of the defaults the user overrides)."""
    return "command -v pg_isready >/dev/null 2>&1 && pg_isready -q"


def detectar(proyecto, environ=None):
    """Port of _env.sh: returns an Entorno with the detection resolved."""
    env = environ if environ is not None else os.environ
    proyecto = os.path.abspath(proyecto)

    backend = env.get("BACKEND_DIR", "")
    if not backend and os.path.isdir(os.path.join(proyecto, "Backend")):
        backend = os.path.join(proyecto, "Backend")
    if not backend:
        backend = proyecto

    frontend = env.get("FRONTEND_DIR", "")
    if not frontend and os.path.isdir(os.path.join(proyecto, "frontend")):
        frontend = os.path.join(proyecto, "frontend")

    py_backend = env.get("PY_BACKEND", "")
    if not py_backend:
        py_backend = _python_de(proyecto) or _python_de(backend) or _python3()

    py_frontend = env.get("PY_FRONTEND", "") or _python_de(frontend) or py_backend

    db_check = env.get("DB_CHECK_CMD", "")
    migrate = env.get("MIGRATE_CHECK", "")
    test = env.get("TEST_CMD", "")
    serve = env.get("SERVE_CMD", "")
    serve_url = env.get("SERVE_URL", "")
    token_url = env.get("TOKEN_URL", "")
    usuario = env.get("USUARIO", "")
    clave = env.get("CLAVE", "")
    endpoints = env.get("ENDPOINTS", "")

    if py_backend and os.path.isfile(os.path.join(backend, "manage.py")):
        migrate = migrate or [py_backend, "manage.py", "migrate", "--check"]
        test = test or [py_backend, "-m", "pytest", "-q"]
        db_check = db_check or _db_por_defecto()
        if not serve and not endpoints:
            serve = [py_backend, "manage.py", "runserver", "8000", "--noreload"]
            serve_url = serve_url or "http://localhost:8000"
            token_url = token_url or "http://localhost:8000/api/token/"
            # Dev-only scaffold credentials. They are NEVER sent outside the
            # local machine: only applied when the target is localhost. For a
            # remote URL, USUARIO/CLAVE must be set explicitly.
            if not usuario and _es_local(serve_url or token_url):
                usuario = "admin"
                clave = "admin123"
            if not usuario:
                print("[GATE] ⚠ USUARIO/CLAVE no configurados para un backend "
                      "remoto; define credenciales o el login fallará.")
            endpoints = endpoints or (
                "productos/productos/ ventas/clientes/ usuarios/usuarios/ "
                "caja/caja/ kardex/movimientos/ compras/compras/ "
                "config/config/")
    elif py_backend:
        test = test or [py_backend, "-m", "pytest", "-q"]

    return Entorno(
        proyecto=proyecto,
        backend_dir=backend,
        frontend_dir=frontend,
        py_backend=py_backend,
        py_frontend=py_frontend,
        db_check=_comando(db_check, backend),
        migrate_check=_comando(migrate, backend),
        test_cmd=_comando(test, backend),
        serve_cmd=_comando(serve, backend),
        serve_url=serve_url,
        token_url=token_url,
        usuario=usuario,
        clave=clave,
        endpoints=_endpoints(proyecto, endpoints),
    )


def _python3():
    return "python3" if shutil.which("python3") else "python"


def _python_de(base):
    """Python interpreter of a venv inside `base` (or "")."""
    if not base:
        return ""
    for nombre in ("venv", ".venv"):
        for sub in ("bin/python", "Scripts/python.exe"):
            ruta = os.path.join(base, nombre, *sub.split("/"))
            if os.path.isfile(ruta):
                return ruta
    return ""


def _endpoints(proyecto, endpoints):
    """endpoints.txt in the root wins; otherwise, the ENDPOINTS list."""
    ruta = rutas.endpoints(proyecto)
    if os.path.isfile(ruta):
        with open(ruta, encoding="utf-8", errors="replace") as f:
            lineas = f.read().splitlines()
        return [linea.strip() for linea in lineas if linea.strip()]
    return endpoints.split() if endpoints else []

