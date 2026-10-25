"""Gate (python): ruff sobre el código Python."""
import glob
import os
import shutil
import subprocess

HERRAMIENTA = "[python]"


def run(env):
    if not glob.glob(os.path.join(env.proyecto, "**", "*.py"), recursive=True):
        env.aviso(f"{HERRAMIENTA} sin archivos .py, se omite ruff")
        return 0
    ruff = shutil.which("ruff")
    if not ruff:
        env.aviso(f"{HERRAMIENTA} ruff no instalado, se omite (pip install ruff)")
        return 0
    p = subprocess.run([ruff, "check", "."], cwd=env.proyecto,
                       capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} ruff encontró problemas")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} ruff OK")
    return 0
