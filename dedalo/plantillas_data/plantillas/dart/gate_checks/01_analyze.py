"""Gate (dart): `dart analyze`."""
import os
import shutil
import subprocess

HERRAMIENTA = "[dart]"


def run(env):
    if not os.path.isfile(os.path.join(env.proyecto, "pubspec.yaml")):
        env.aviso(f"{HERRAMIENTA} sin pubspec.yaml, se omite")
        return 0
    dart = shutil.which("dart")
    if not dart:
        env.aviso(f"{HERRAMIENTA} dart no disponible, se omite")
        return 0
    p = subprocess.run([dart, "analyze"], cwd=env.proyecto,
                       capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} dart analyze falló")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} dart analyze OK")
    return 0