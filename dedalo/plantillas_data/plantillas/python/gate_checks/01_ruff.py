"""Gate: ruff sobre el código Python (si ruff está instalado)."""
import glob
import os
import shutil
import subprocess


def run(env):
    if not glob.glob(os.path.join(env.proyecto, "**", "*.py"), recursive=True):
        env.aviso("sin archivos .py, se omite ruff")
        return 0
    ruff = shutil.which("ruff")
    if not ruff:
        env.aviso("ruff no instalado, se omite (pip install ruff)")
        return 0
    p = subprocess.run([ruff, "check", "."], cwd=env.proyecto,
                       capture_output=True, text=True)
    if p.returncode != 0:
        env.fail("ruff encontró problemas")
        print(p.stdout or p.stderr)
        return 1
    env.ok("ruff OK")
    return 0
