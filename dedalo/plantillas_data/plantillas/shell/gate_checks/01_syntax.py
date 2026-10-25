"""Gate (shell): sintaxis de todos los .sh con `bash -n`."""
import glob
import shutil
import subprocess

HERRAMIENTA = "[shell]"


def run(env):
    bash = shutil.which("bash")
    if not bash:
        env.aviso(f"{HERRAMIENTA} bash no disponible, se omite")
        return 0
    ficheros = sorted(glob.glob("**/*.sh", root_dir=env.proyecto, recursive=True))
    if not ficheros:
        env.aviso(f"{HERRAMIENTA} sin ficheros .sh, se omite")
        return 0
    for fichero in ficheros:
        p = subprocess.run([bash, "-n", fichero], cwd=env.proyecto,
                           capture_output=True, text=True)
        if p.returncode != 0:
            env.fail(f"{HERRAMIENTA} sintaxis inválida en {fichero}")
            print(p.stderr)
            return 1
    env.ok(f"{HERRAMIENTA} sintaxis OK ({len(ficheros)} ficheros)")
    return 0
