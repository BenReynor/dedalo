"""Gate: gofmt (los archivos .go deben estar formateados)."""
import os
import shutil
import subprocess


def run(env):
    if not os.path.isfile(os.path.join(env.proyecto, "go.mod")):
        env.aviso("sin go.mod, se omite gofmt")
        return 0
    gofmt = shutil.which("gofmt")
    if not gofmt:
        env.aviso("gofmt no disponible, se omite")
        return 0
    p = subprocess.run([gofmt, "-l", "."], cwd=env.proyecto,
                       capture_output=True, text=True)
    sin_formato = [l for l in (p.stdout or "").splitlines() if l.strip()]
    if p.returncode != 0 or sin_formato:
        env.fail("gofmt: archivos sin formatear: " + ", ".join(sin_formato))
        return 1
    env.ok("gofmt OK")
    return 0
