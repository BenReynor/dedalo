"""Gate (php): lint con `php -l` en cada .php."""
import glob
import shutil
import subprocess

HERRAMIENTA = "[php]"


def run(env):
    php = shutil.which("php")
    if not php:
        env.aviso(f"{HERRAMIENTA} php no disponible, se omite")
        return 0
    ficheros = sorted(glob.glob("**/*.php", root_dir=env.proyecto, recursive=True))
    if not ficheros:
        env.aviso(f"{HERRAMIENTA} sin ficheros .php, se omite")
        return 0
    for fichero in ficheros:
        p = subprocess.run([php, "-l", fichero], cwd=env.proyecto,
                           capture_output=True, text=True)
        if p.returncode != 0:
            env.fail(f"{HERRAMIENTA} sintaxis inválida en {fichero}")
            print(p.stderr)
            return 1
    env.ok(f"{HERRAMIENTA} lint OK ({len(ficheros)} ficheros)")
    return 0