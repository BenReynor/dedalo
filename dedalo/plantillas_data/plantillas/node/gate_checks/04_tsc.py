"""Gate (node): `tsc --noEmit` si el proyecto es TypeScript (hay tsconfig.json)."""
import os
import shutil
import subprocess

HERRAMIENTA = "[node]"


def run(env):
    if not os.path.isfile(os.path.join(env.proyecto, "tsconfig.json")):
        env.aviso(f"{HERRAMIENTA} sin tsconfig.json, se omite tsc")
        return 0
    # Solo el tsc local: `npx tsc` sin instalar descargaría un paquete ajeno.
    binario = "tsc.cmd" if os.name == "nt" else "tsc"
    tsc = os.path.join(env.proyecto, "node_modules", ".bin", binario)
    if not os.path.isfile(tsc):
        tsc = shutil.which("tsc")
    if not tsc:
        env.aviso(f"{HERRAMIENTA} typescript no instalado (npm install), se omite tsc")
        return 0
    p = subprocess.run([tsc, "--noEmit", "-p", "tsconfig.json"], cwd=env.proyecto,
                       capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} tsc: errores de tipos")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} tsc OK")
    return 0
