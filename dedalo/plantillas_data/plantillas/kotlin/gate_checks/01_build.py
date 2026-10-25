"""Gate (kotlin): compila con Gradle (compileKotlin)."""
import os
import shutil
import subprocess

HERRAMIENTA = "[kotlin]"


def _gradle(proyecto):
    for nombre in ("gradlew", "gradle"):
        ruta = os.path.join(proyecto, nombre)
        if os.path.isfile(ruta):
            return ruta if nombre == "gradlew" else shutil.which("gradle")
    return shutil.which("gradle")


def run(env):
    proyecto = env.proyecto
    if not any(os.path.isfile(os.path.join(proyecto, n))
               for n in ("build.gradle.kts", "build.gradle")):
        env.aviso(f"{HERRAMIENTA} sin build.gradle(.kts), se omite")
        return 0
    gradle = _gradle(proyecto)
    if not gradle:
        env.aviso(f"{HERRAMIENTA} gradle no disponible, se omite")
        return 0
    p = subprocess.run([gradle, "-q", "compileKotlin", "--console=plain"],
                       cwd=proyecto, capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} compileKotlin falló")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} compileKotlin OK")
    return 0
