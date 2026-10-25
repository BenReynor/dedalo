"""Gate (node): package.json válido."""
import json
import os

HERRAMIENTA = "[node]"


def run(env):
    ruta = os.path.join(env.proyecto, "package.json")
    if not os.path.isfile(ruta):
        env.fail(f"{HERRAMIENTA} package.json no existe")
        return 1
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        env.fail(f"{HERRAMIENTA} package.json inválido: {e}")
        return 1
    if not isinstance(datos, dict) or not datos.get("name"):
        env.fail(f"{HERRAMIENTA} package.json sin campo 'name'")
        return 1
    env.ok(f"{HERRAMIENTA} package.json válido")
    return 0
