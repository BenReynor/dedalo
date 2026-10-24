"""Gate: app.js con toggle de tema persistido y sintaxis válida."""
import os
import shutil
import subprocess

ARCHIVO = "app.js"


def run(env):
    ruta = os.path.join(env.proyecto, ARCHIVO)
    if not os.path.isfile(ruta):
        env.fail(f"{ARCHIVO} no existe")
        return 1
    with open(ruta, encoding="utf-8", errors="replace") as f:
        js = f.read()

    if "localStorage" not in js:
        env.fail(f"{ARCHIVO} sin localStorage (el tema no se persiste)")
        return 1
    if not any(p in js.lower() for p in ("dark", "light", "theme")):
        env.fail(f"{ARCHIVO} sin lógica de tema dark/light")
        return 1
    if not any(p in js for p in ("addEventListener", "onclick")):
        env.fail(f"{ARCHIVO} sin event listener para la interacción")
        return 1

    node = shutil.which("node")
    if node:
        p = subprocess.run([node, "--check", ruta], capture_output=True, text=True)
        if p.returncode != 0:
            env.fail(f"{ARCHIVO} error de sintaxis: {p.stderr.strip()}")
            return 1
        env.ok(f"{ARCHIVO} sintaxis válida y toggle de tema")
    else:
        env.ok(f"{ARCHIVO} toggle de tema (node no disponible: sin --check)")
    return 0
