"""Gate (c/c++): tests con ctest o `make test`."""
import os
import shutil
import subprocess

HERRAMIENTA = "[cpp]"


def run(env):
    proyecto = env.proyecto
    if os.path.isdir(os.path.join(proyecto, "build")):
        ctest = shutil.which("ctest")
        if ctest:
            p = subprocess.run([ctest, "--test-dir", "build", "--output-on-failure"],
                               cwd=proyecto, capture_output=True, text=True)
            if p.returncode != 0:
                env.fail(f"{HERRAMIENTA} ctest falló")
                print(p.stdout or p.stderr)
                return 1
            env.ok(f"{HERRAMIENTA} ctest OK")
            return 0
    if os.path.isfile(os.path.join(proyecto, "Makefile")):
        make = shutil.which("make")
        if make:
            p = subprocess.run([make, "test"], cwd=proyecto,
                               capture_output=True, text=True)
            if p.returncode != 0:
                env.fail(f"{HERRAMIENTA} make test falló")
                print(p.stdout or p.stderr)
                return 1
            env.ok(f"{HERRAMIENTA} make test OK")
            return 0
    env.aviso(f"{HERRAMIENTA} sin build/ ni Makefile, se omite")
    return 0
