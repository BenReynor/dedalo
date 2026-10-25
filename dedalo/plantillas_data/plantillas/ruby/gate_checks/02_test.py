"""Gate (ruby): tests con rspec o rake."""
import os
import shutil
import subprocess

HERRAMIENTA = "[ruby]"


def run(env):
    proyecto = env.proyecto
    if not os.path.isfile(os.path.join(proyecto, "Gemfile")):
        env.aviso(f"{HERRAMIENTA} sin Gemfile, se omite")
        return 0
    if os.path.isdir(os.path.join(proyecto, "spec")):
        bundle = shutil.which("bundle")
        if not bundle:
            env.aviso(f"{HERRAMIENTA} bundle no disponible, se omite")
            return 0
        p = subprocess.run([bundle, "exec", "rspec"],
                           cwd=proyecto, capture_output=True, text=True)
        if p.returncode != 0:
            env.fail(f"{HERRAMIENTA} rspec falló")
            print(p.stdout or p.stderr)
            return 1
        env.ok(f"{HERRAMIENTA} rspec OK")
        return 0
    if os.path.isfile(os.path.join(proyecto, "Rakefile")):
        bundle = shutil.which("bundle")
        if not bundle:
            env.aviso(f"{HERRAMIENTA} bundle no disponible, se omite")
            return 0
        p = subprocess.run([bundle, "exec", "rake", "test"],
                           cwd=proyecto, capture_output=True, text=True)
        if p.returncode != 0:
            env.fail(f"{HERRAMIENTA} rake test falló")
            print(p.stdout or p.stderr)
            return 1
        env.ok(f"{HERRAMIENTA} rake test OK")
        return 0
    env.aviso(f"{HERRAMIENTA} sin spec/ ni Rakefile, se omite")
    return 0