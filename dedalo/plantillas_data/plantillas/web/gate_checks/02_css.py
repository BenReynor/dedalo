"""Gate (web): styles.css con custom properties y diseño responsive."""
import os
import re

HERRAMIENTA = "[web]"
ARCHIVO = "styles.css"


def run(env):
    ruta = os.path.join(env.proyecto, ARCHIVO)
    if not os.path.isfile(ruta):
        env.fail(f"{HERRAMIENTA} {ARCHIVO} no existe")
        return 1
    with open(ruta, encoding="utf-8", errors="replace") as f:
        css = f.read()

    if not re.search(r"--[A-Za-z0-9_-]+\s*:", css):
        env.fail(f"{HERRAMIENTA} {ARCHIVO} sin custom properties (--variable: valor)")
        return 1
    if not re.search(r"@media|clamp\(|min\(|max\(|calc\(|\d(vw|vh|rem|em|%)",
                     css):
        env.fail(f"{HERRAMIENTA} {ARCHIVO} sin indicadores de diseño responsive")
        return 1
    if not re.search(r"prefers-color-scheme|\[data-theme|--bg\b|--text\b|--primary\b",
                     css):
        env.aviso(f"{HERRAMIENTA} {ARCHIVO} sin variables de tema aparentes")
    env.ok(f"{HERRAMIENTA} {ARCHIVO} con custom properties y responsive")
    return 0
