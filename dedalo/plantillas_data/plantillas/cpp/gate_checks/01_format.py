"""Gate (c/c++): clang-format en modo comprobación (opcional)."""
import glob
import shutil
import subprocess

HERRAMIENTA = "[cpp]"
EXTENSIONES = ("*.c", "*.cc", "*.cpp", "*.cxx", "*.h", "*.hh", "*.hpp", "*.hxx")


def run(env):
    clang_format = shutil.which("clang-format")
    if not clang_format:
        env.aviso(f"{HERRAMIENTA} clang-format no disponible, se omite")
        return 0
    ficheros = []
    for patron in EXTENSIONES:
        ficheros += glob.glob(patron, root_dir=env.proyecto, recursive=True)
    ficheros = sorted(set(ficheros))
    if not ficheros:
        env.aviso(f"{HERRAMIENTA} sin fuentes C/C++, se omite")
        return 0
    p = subprocess.run([clang_format, "--dry-run", "--Werror", *ficheros],
                       cwd=env.proyecto, capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{HERRAMIENTA} clang-format: hay ficheros sin formatear")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{HERRAMIENTA} clang-format OK")
    return 0
