"""Gate (swift): build con `swift build`."""
import os
import shutil
import subprocess

HERRAMIENTA = "[swift]"


def run(env):
    if not os.path.isfile(os.path.join(env.proyecto, "Package.swift")):
        env.aviso(f"{HERRAMIENTA} sin Package.swift, se omite")
        return 0
    swift = shutil.which("swift")
    if not swift:
        env.aviso(f"{HERRAMIENTA} swift no disponible, se omite")
        return 0
    p = subprocess.run([swift, "build"], cwd=env.proyecto,
                       capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} swift build falló")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} swift build OK")
    return 0