"""Gate (rust): `cargo check` (compila sin generar binario)."""
import os
import shutil
import subprocess

HERRAMIENTA = "[rust]"


def run(env):
    if not os.path.isfile(os.path.join(env.proyecto, "Cargo.toml")):
        env.aviso(f"{HERRAMIENTA} sin Cargo.toml, se omite cargo check")
        return 0
    cargo = shutil.which("cargo")
    if not cargo:
        env.aviso(f"{HERRAMIENTA} cargo no disponible, se omite")
        return 0
    p = subprocess.run([cargo, "check"], cwd=env.proyecto,
                       capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} cargo check falló")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} cargo check OK")
    return 0
