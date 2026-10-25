"""Gate (web): index.html es HTML5 válido y semántico."""
import os
import re

HERRAMIENTA = "[web]"
ARCHIVO = "index.html"
SEMANTICAS = ("header", "main", "footer")


def run(env):
    ruta = os.path.join(env.proyecto, ARCHIVO)
    if not os.path.isfile(ruta):
        env.fail(f"{HERRAMIENTA} {ARCHIVO} no existe")
        return 1
    with open(ruta, encoding="utf-8", errors="replace") as f:
        html = f.read()
    bajo = html.lower()

    if not re.search(r"<!doctype\s+html", bajo):
        env.fail(f"{HERRAMIENTA} {ARCHIVO} sin <!DOCTYPE html>")
        return 1
    for etiqueta in ("<html", "<head", "</head>", "<body", "</body>"):
        if etiqueta not in bajo:
            env.fail(f"{HERRAMIENTA} {ARCHIVO} sin {etiqueta}>")
            return 1
    faltan = [t for t in SEMANTICAS if f"<{t}" not in bajo]
    if faltan:
        env.fail(f"{HERRAMIENTA} {ARCHIVO} sin elementos semánticos: {', '.join(faltan)}")
        return 1
    env.ok(f"{HERRAMIENTA} {ARCHIVO} estructura HTML5 válida")
    return 0
