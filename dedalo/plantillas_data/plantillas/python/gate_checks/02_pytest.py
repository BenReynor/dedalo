"""Gate (python): pytest."""
import os
import shutil
import subprocess

HERRAMIENTA = "[python]"


def run(env):
    pytest = shutil.which("pytest")
    if not pytest:
        env.aviso(f"{HERRAMIENTA} pytest no instalado, se omite (pip install pytest)")
        return 0
    if not os.path.isdir(os.path.join(env.proyecto, "tests")):
        env.aviso(f"{HERRAMIENTA} sin carpeta tests/, se omite pytest")
        return 0
    p = subprocess.run([pytest, "-q"], cwd=env.proyecto,
                       capture_output=True, text=True)
    if p.returncode == 5:  # no tests collected
        env.aviso(f"{HERRAMIENTA} pytest no recolectó tests")
        return 0
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} pytest falló")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} pytest OK")
    return 0
