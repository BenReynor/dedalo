"""Gate (rust): `cargo test`."""
import os
import re
import shutil
import subprocess

HERRAMIENTA = "[rust]"


def _dir_cargo(proyecto):
    """Carpeta con el Cargo.toml: la raíz o `src-tauri/` (apps Tauri)."""
    for sub in ("", "src-tauri"):
        carpeta = os.path.join(proyecto, sub) if sub else proyecto
        if os.path.isfile(os.path.join(carpeta, "Cargo.toml")):
            return carpeta
    return None


def _tests_fallidos(salida):
    """Names of the failed tests, from cargo's `test x ... FAILED` lines."""
    return sorted(set(re.findall(r"^test (\S+)(?: - .*)? \.\.\. FAILED\s*$",
                                 salida, re.M)))


def _bloque_fallos(lineas):
    """`test … FAILED`, panics and cargo's final `failures:` list."""
    utiles = [li for li in lineas if re.search(r"\.\.\. FAILED|panicked at", li)]
    finales = [i for i, li in enumerate(lineas) if li.strip() == "failures:"]
    if finales:
        for li in lineas[finales[-1]:]:
            if li.startswith("test result:"):
                break
            utiles.append(li)
    return list(dict.fromkeys(utiles))


def _errores(salida, maximo=60):
    """Compile errors and failed tests (not 100 KB of warnings), else the
    tail; capped either way. `error: test failed` alone names no test."""
    lineas = [li for li in salida.splitlines() if li.strip()]
    errores = [li for li in lineas if re.search(r"\berror(\[E\d+\])?:", li)]
    utiles = _bloque_fallos(lineas) + errores
    return "\n".join(utiles[:maximo] if utiles else lineas[-maximo:])


def _cargo_test(cargo, carpeta):
    return subprocess.run([cargo, "test", "--message-format", "short"], cwd=carpeta,
                          capture_output=True, text=True,
                          env={**os.environ, "CARGO_TERM_COLOR": "never"})


def run(env):
    carpeta = _dir_cargo(env.proyecto)
    if carpeta is None:
        env.aviso(f"{HERRAMIENTA} sin Cargo.toml, se omite cargo test")
        return 0
    cargo = shutil.which("cargo")
    if not cargo:
        env.aviso(f"{HERRAMIENTA} cargo no disponible, se omite")
        return 0
    p = _cargo_test(cargo, carpeta)
    if p.returncode != 0:
        salida = p.stderr + "\n" + p.stdout
        fallidos = _tests_fallidos(salida)
        if fallidos and _cargo_test(cargo, carpeta).returncode == 0:
            env.aviso(f"{HERRAMIENTA} tests inestables (fallaron y pasaron al "
                      f"repetir): {', '.join(fallidos)}")
            env.ok(f"{HERRAMIENTA} cargo test OK")
            return 0
        env.fail(f"{HERRAMIENTA} cargo test falló"
                 + (f": {', '.join(fallidos[:10])}" if fallidos else ""))
        print(_errores(salida))
        return 1
    env.ok(f"{HERRAMIENTA} cargo test OK")
    return 0
