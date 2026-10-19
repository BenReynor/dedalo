#!/usr/bin/env python3
"""Portable gate orchestrator (port of gate.sh).

Runs the checks in `gate_checks/` in numeric order by prefix and returns
0=OK, 1=FAIL, with the SAME output contract as gate.sh (`[GATE] ✓/✗`, and
the final `[GATE] ✅ TODO OK`).

Prefix selection rule:
  · If `NN_*.sh` exists and bash is available -> it is run with bash (the usual
    gate behavior; so a custom .sh check still wins).
  · If there is no bash (Windows without Git Bash) -> `NN_*.py`, the port, runs.

The loop (loop.py) invokes this with the same project directory as before:

    python -m dedalo.gate      # installed / editable
    <exe> --dedalo-gate            # frozen binary (PyInstaller)
"""

import os
import re
import shutil
import subprocess
import sys

from . import gate_env, rutas


def _proteger_salidas():
    """Protects stdout/stderr against encodings that do not support emojis."""
    for nombre in ("stdout", "stderr"):
        try:
            st = getattr(sys, nombre, None)
            if st is None:
                setattr(sys, nombre, open(os.devnull, "w", encoding="utf-8", errors="replace"))
            elif hasattr(st, "reconfigure"):
                try:
                    st.reconfigure(encoding="utf-8", errors="replace")
                except (OSError, ValueError):
                    pass
        except Exception:
            pass


_PREFIJO = re.compile(r"^(\d+)_")


def argv_gate(frozen=None):
    """Command (argv list) to run the gate as a subprocess.

    In the source code: `python -m dedalo.gate`. In the PyInstaller
    binary `-m` does not resolve the module (it is packaged in the exe), so
    the entrypoint interprets `--dedalo-gate`.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        return [sys.executable, "--dedalo-gate"]
    return [sys.executable, "-m", "dedalo.gate"]


def _grupos(proyecto):
    """Groups gate_checks by prefix. None if the directory does not exist."""
    dir_checks = rutas.gate_checks(proyecto)
    if not os.path.isdir(dir_checks):
        return None
    grupos = {}
    for nombre in sorted(os.listdir(dir_checks)):
        ruta = os.path.join(dir_checks, nombre)
        if nombre in ("_env.sh", "_env.py") or not os.path.isfile(ruta):
            continue
        base, ext = os.path.splitext(nombre)
        if ext not in (".sh", ".py") or not _PREFIJO.match(nombre):
            continue
        grupos.setdefault((int(_PREFIJO.match(nombre).group(1)), base), {})[ext] = ruta
    return grupos


def _cargar_py(ruta):
    """Loads a .py check without writing __pycache__ into the project."""
    try:
        with open(ruta, encoding="utf-8") as f:
            codigo = f.read()
    except OSError:
        return None
    espacios = {"__name__": "gate_check_" + os.path.basename(ruta), "__file__": ruta}
    exec(compile(codigo, ruta, "exec"), espacios)
    return espacios.get("run")


def _correr_py(check, entorno):
    funcion = _cargar_py(check)
    if funcion is None:
        print(f"[GATE] ⚠ {os.path.basename(check)}: sin función run(), se omite")
        return 0
    try:
        resultado = funcion(entorno)
    except SystemExit as e:
        return int(e.code or 0)
    except Exception as e:  # noqa: BLE001
        print(f"[GATE] ✗ {os.path.basename(check)}: {e}")
        return 1
    if resultado is None:
        return 0
    if isinstance(resultado, bool):
        return 0 if resultado else 1
    return int(resultado)


def _correr_sh(proyecto, check, bash):
    """Runs a .sh check with bash, sourcing _env.sh first (like gate.sh)."""
    env_sh = os.path.join(rutas.gate_checks(proyecto), "_env.sh")
    partes = []
    if os.path.isfile(env_sh):
        partes.append(f'source "{env_sh}"')
    else:
        partes.append(f'PROYECTO="{proyecto}"')
        partes.append('fail() { echo "[GATE] ✗ $1"; exit 1; }')
        partes.append('ok()   { echo "[GATE] ✓ $1"; }')
    partes.append(f'source "{check}"')
    guion = "\n".join(partes)
    try:
        p = subprocess.run(
            [bash, "-c", guion], cwd=proyecto, capture_output=True, text=True)
    except OSError:
        return 127
    # Re-emit through Python's stdout/stderr to preserve the log ORDER:
    # if the subprocess wrote directly to the fd, its output could jump ahead
    # of the Python buffer (and of the final "[GATE] ✅ TODO OK").
    sys.stdout.write(p.stdout or "")
    if p.stderr:
        sys.stderr.write(p.stderr)
    sys.stdout.flush()
    return p.returncode


def correr(proyecto, bash=None):
    """Runs the project gate. Returns 0=OK, 1=FAIL."""
    _proteger_salidas()
    if bash is None:
        bash = shutil.which("bash")
    grupos = _grupos(proyecto)
    if grupos is None:
        print(f"[GATE] ⚠ No existe {rutas.gate_checks(proyecto)} — "
              "se asume OK")
        return 0
    if not grupos:
        print("[GATE] ⚠ Sin checks — se asume OK")
        return 0
    entorno = None
    for clave in sorted(grupos):
        grupo = grupos[clave]
        usado = grupo.get(".sh") or grupo.get(".py")
        if ".sh" in grupo and bash:
            usado = grupo[".sh"]
            rc = _correr_sh(proyecto, usado, bash)
        elif ".py" in grupo:
            if entorno is None:
                entorno = gate_env.detectar(proyecto)
            usado = grupo[".py"]
            rc = _correr_py(usado, entorno)
        else:
            print(f"[GATE] ⚠ {os.path.basename(usado)}: no hay bash ni .py, "
                  "se omite")
            rc = 0
        if rc != 0:
            print(f"[GATE] ✗ Check falló: {os.path.basename(usado)}")
            return rc if rc > 0 else 1
    print()
    print("[GATE] ✅ TODO OK")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        sys.dont_write_bytecode = True
    except Exception:
        pass
    proyecto = os.getcwd()
    i = 0
    while i < len(argv):
        if argv[i] in ("--proyecto", "-p") and i + 1 < len(argv):
            proyecto = argv[i + 1]
            i += 2
        elif not argv[i].startswith("-"):
            proyecto = argv[i]
            i += 1
        else:
            i += 1
    return correr(proyecto)


if __name__ == "__main__":
    sys.exit(main())
