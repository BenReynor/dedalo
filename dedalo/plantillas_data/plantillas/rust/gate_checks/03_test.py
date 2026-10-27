"""Gate (rust): `cargo test`."""
import os
import re
import shutil
import subprocess

HERRAMIENTA = "[rust]"


def _dir_cargo(proyecto):
    """Carpeta con el Cargo.toml: la raíz o `src-tauri/` (apps Tauri)."""
    for sub in ("", "src-tauri"):
        carpeta = os.path.join(proyecto, sub) if sub else proyecto
        if os.path.isfile(os.path.join(carpeta, "Cargo.toml")):
            return carpeta
    return None


def _errores(salida, maximo=60):
    """Compile errors if there are any (not 100 KB of warnings), else the
    tail, where `cargo test` prints its failures; capped either way."""
    lineas = [li for li in salida.splitlines() if li.strip()]
    errores = [li for li in lineas if re.search(r"\berror(\[E\d+\])?:", li)]
    return "\n".join(errores[:maximo] if errores else lineas[-maximo:])


def run(env):
    carpeta = _dir_cargo(env.proyecto)
    if carpeta is None:
        env.aviso(f"{HERRAMIENTA} sin Cargo.toml, se omite cargo test")
        return 0
    cargo = shutil.which("cargo")
    if not cargo:
        env.aviso(f"{HERRAMIENTA} cargo no disponible, se omite")
        return 0
    p = subprocess.run([cargo, "test", "--message-format", "short"], cwd=carpeta,
                       capture_output=True, text=True,
                       env={**os.environ, "CARGO_TERM_COLOR": "never"})
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} cargo test falló")
        print(_errores(p.stderr + "\n" + p.stdout))
        return 1
    env.ok(f"{HERRAMIENTA} cargo test OK")
    return 0
