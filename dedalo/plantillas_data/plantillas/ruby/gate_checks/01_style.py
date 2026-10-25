"""Gate (ruby): rubocop (opcional)."""
import os
import shutil
import subprocess

HERRAMIENTA = "[ruby]"


def run(env):
    proyecto = env.proyecto
    if not (os.path.isfile(os.path.join(proyecto, "Gemfile"))
            or any(f.endswith(".rb") for f in os.listdir(proyecto))):
        env.aviso(f"{HERRAMIENTA} sin Gemfile ni .rb, se omite")
        return 0
    rubocop = shutil.which("rubocop")
    if not rubocop:
        env.aviso(f"{HERRAMIENTA} rubocop no disponible, se omite")
        return 0
    argv = [rubocop]
    if os.path.isfile(os.path.join(proyecto, "Gemfile")):
        bundle = shutil.which("bundle")
        if bundle:
            argv = [bundle, "exec", "rubocop"]
    p = subprocess.run(argv, cwd=proyecto, capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} rubocop encontró problemas")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} rubocop OK")
    return 0
