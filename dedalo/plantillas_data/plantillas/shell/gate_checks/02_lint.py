"""Gate (shell): shellcheck (opcional)."""
import glob
import shutil
import subprocess

HERRAMIENTA = "[shell]"


def run(env):
    shellcheck = shutil.which("shellcheck")
    if not shellcheck:
        env.aviso(f"{HERRAMIENTA} shellcheck no disponible, se omite")
        return 0
    ficheros = sorted(glob.glob("**/*.sh", root_dir=env.proyecto, recursive=True))
    if not ficheros:
        env.aviso(f"{HERRAMIENTA} sin ficheros .sh, se omite")
        return 0
    p = subprocess.run([shellcheck, "-x", *ficheros], cwd=env.proyecto,
                       capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} shellcheck encontró problemas")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} shellcheck OK")
    return 0
