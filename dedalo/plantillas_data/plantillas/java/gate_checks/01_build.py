"""Gate (java): compila con Maven o Gradle."""
import os
import shutil
import subprocess

HERRAMIENTA = "[java]"


def _gradle(proyecto):
    for nombre in ("gradlew", "gradle"):
        ruta = os.path.join(proyecto, nombre)
        if os.path.isfile(ruta):
            return ruta if nombre == "gradlew" else shutil.which("gradle")
    return shutil.which("gradle")


def run(env):
    proyecto = env.proyecto
    if os.path.isfile(os.path.join(proyecto, "pom.xml")):
        mvn = shutil.which("mvn")
        if not mvn:
            env.aviso(f"{HERRAMIENTA} mvn no disponible, se omite")
            return 0
        p = subprocess.run([mvn, "-q", "-B", "-DskipTests", "compile"],
                           cwd=proyecto, capture_output=True, text=True)
        if p.returncode != 0:
            env.fail(f"{HERRAMIENTA} mvn compile falló")
            print(p.stdout or p.stderr)
            return 1
        env.ok(f"{HERRAMIENTA} mvn compile OK")
        return 0
    gradle = _gradle(proyecto)
    if gradle:
        p = subprocess.run([gradle, "-q", "compileJava", "--console=plain"],
                           cwd=proyecto, capture_output=True, text=True)
        if p.returncode != 0:
            env.fail(f"{HERRAMIENTA} gradle compileJava falló")
            print(p.stdout or p.stderr)
            return 1
        env.ok(f"{HERRAMIENTA} gradle compileJava OK")
        return 0
    env.aviso(f"{HERRAMIENTA} sin pom.xml ni gradle, se omite")
    return 0
