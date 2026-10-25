"""Gate (php): phpunit (opcional)."""
import os
import shutil
import subprocess

HERRAMIENTA = "[php]"


def run(env):
    proyecto = env.proyecto
    if not os.path.isfile(os.path.join(proyecto, "composer.json")):
        env.aviso(f"{HERRAMIENTA} sin composer.json, se omite")
        return 0
    # vendor/bin/phpunit if installed
    vendor_phpunit = os.path.join(proyecto, "vendor", "bin", "phpunit")
    phpunit = vendor_phpunit if os.path.isfile(vendor_phpunit) else shutil.which("phpunit")
    if not phpunit:
        env.aviso(f"{HERRAMIENTA} phpunit no disponible, se omite")
        return 0
    p = subprocess.run([phpunit], cwd=proyecto, capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} phpunit falló")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} phpunit OK")
    return 0