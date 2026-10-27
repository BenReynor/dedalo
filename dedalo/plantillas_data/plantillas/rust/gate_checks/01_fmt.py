"""Gate (rust): `cargo fmt --check`."""
import os
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


def run(env):
    carpeta = _dir_cargo(env.proyecto)
    if carpeta is None:
        env.aviso(f"{HERRAMIENTA} sin Cargo.toml, se omite cargo fmt")
        return 0
    cargo = shutil.which("cargo")
    if not cargo:
        env.aviso(f"{HERRAMIENTA} cargo no disponible, se omite")
        return 0
    p = subprocess.run([cargo, "fmt", "--check", "--", "-l"], cwd=carpeta,
                       capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} cargo fmt: hay archivos sin formatear "
                 f"(ejecuta `cargo fmt` en {os.path.relpath(carpeta, env.proyecto)})")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} cargo fmt OK")
    return 0
