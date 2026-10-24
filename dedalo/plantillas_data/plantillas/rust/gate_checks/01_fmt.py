"""Gate: `cargo fmt --check` (si hay Cargo.toml)."""
import os
import shutil
import subprocess


def run(env):
    if not os.path.isfile(os.path.join(env.proyecto, "Cargo.toml")):
        env.aviso("sin Cargo.toml, se omite cargo fmt")
        return 0
    cargo = shutil.which("cargo")
    if not cargo:
        env.aviso("cargo no disponible, se omite")
        return 0
    p = subprocess.run([cargo, "fmt", "--check"], cwd=env.proyecto,
                       capture_output=True, text=True)
    if p.returncode != 0:
        env.fail("cargo fmt: hay archivos sin formatear")
        print(p.stdout or p.stderr)
        return 1
    env.ok("cargo fmt OK")
    return 0
