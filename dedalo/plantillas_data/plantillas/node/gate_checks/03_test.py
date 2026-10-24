"""Gate: ejecuta `npm test` si el script existe."""
import json
import os
import shutil
import subprocess


def _script(nombre):
    ruta = os.path.join(os.getcwd(), "package.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            return (json.load(f).get("scripts") or {}).get(nombre)
    except (OSError, json.JSONDecodeError):
        return None


def run(env):
    if not _script("test"):
        env.aviso("package.json sin script 'test', se omite")
        return 0
    npm = shutil.which("npm")
    if not npm:
        env.aviso("npm no disponible, se omite test")
        return 0
    p = subprocess.run([npm, "test", "--", "--runInBand"], cwd=env.proyecto,
                       capture_output=True, text=True)
    if p.returncode != 0:
        # Reintento sin flags (el script puede no aceptar --runInBand)
        p = subprocess.run([npm, "test"], cwd=env.proyecto,
                           capture_output=True, text=True)
        if p.returncode != 0:
            env.fail("npm test falló")
            print(p.stdout or p.stderr)
            return 1
    env.ok("npm test OK")
    return 0
