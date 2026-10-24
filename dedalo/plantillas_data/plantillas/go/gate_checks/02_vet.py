"""Gate: `go vet ./...`."""
import os
import shutil
import subprocess


def run(env):
    if not os.path.isfile(os.path.join(env.proyecto, "go.mod")):
        env.aviso("sin go.mod, se omite go vet")
        return 0
    go = shutil.which("go")
    if not go:
        env.aviso("go no disponible, se omite")
        return 0
    p = subprocess.run([go, "vet", "./..."], cwd=env.proyecto,
                       capture_output=True, text=True)
    if p.returncode != 0:
        env.fail("go vet falló")
        print(p.stdout or p.stderr)
        return 1
    env.ok("go vet OK")
    return 0
