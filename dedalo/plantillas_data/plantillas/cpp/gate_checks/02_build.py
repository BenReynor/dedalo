"""Gate (c/c++): build con CMake o make."""
import os
import shutil
import subprocess

HERRAMIENTA = "[cpp]"


def run(env):
    proyecto = env.proyecto
    if os.path.isfile(os.path.join(proyecto, "CMakeLists.txt")):
        cmake = shutil.which("cmake")
        if not cmake:
            env.aviso(f"{HERRAMIENTA} cmake no disponible, se omite")
            return 0
        for argv, etiqueta in (
            ([cmake, "-S", ".", "-B", "build"], "cmake configure"),
            ([cmake, "--build", "build"], "cmake build"),
        ):
            p = subprocess.run(argv, cwd=proyecto, capture_output=True,
                               text=True)
            if p.returncode != 0:
                env.fail(f"{HERRAMIENTA} {etiqueta} falló")
                print(p.stdout or p.stderr)
                return 1
        env.ok(f"{HERRAMIENTA} cmake build OK")
        return 0
    if os.path.isfile(os.path.join(proyecto, "Makefile")):
        make = shutil.which("make")
        if not make:
            env.aviso(f"{HERRAMIENTA} make no disponible, se omite")
            return 0
        p = subprocess.run([make], cwd=proyecto, capture_output=True,
                           text=True)
        if p.returncode != 0:
            env.fail(f"{HERRAMIENTA} make falló")
            print(p.stdout or p.stderr)
            return 1
        env.ok(f"{HERRAMIENTA} make OK")
        return 0
    env.aviso(f"{HERRAMIENTA} sin CMakeLists.txt ni Makefile, se omite")
    return 0
