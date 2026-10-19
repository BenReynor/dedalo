"""Portability lint for the shell templates.

The templates are copied into other users' projects, which may be on
macOS or Windows (WSL/Git Bash). GNU-only constructs fail there silently or
with confusing errors, so they are forbidden here.

This file does not replace testing on the real machine: it only prevents
reintroducing constructs we already know are incompatible.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# This module analyzes .sh with `bash -n`, `locale`, +x permissions and symlinks:
# on Windows it makes no sense (there it is skipped entirely). Template
# portability is verified on Linux and in the CI macOS job.
pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="lint de plantillas shell: sólo POSIX")

RAIZ = Path(__file__).resolve().parent.parent
SH_DIRS = [RAIZ / "dedalo", RAIZ]
_IGNORAR = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache",
            "venv", ".venv", "__pycache__", "node_modules",
            # `pip install .` / `pip wheel` leave build/lib/ with a copy of
            # the templates: without this, a local build duplicated the 12 .sh
            # and the portability suite reported 48 extra tests.
            "build", "dist", "dedalo.egg-info",
            # build_linux.sh unpacks copies of the previous build's .sh into
            # packaging/out/: they analyze the old file and fail (no
            # .sh in the repo lives under a directory named `out`).
            "out"}

# (regex, reason, functions where the use is legitimate)
PROHIBIDOS: list[tuple[str, str, tuple[str, ...]]] = [
    # GNU %N does not exist in BSD's date: it returns the literal "%3N" and breaks
    # the duration arithmetic. It is only allowed inside ahora_ms(), which
    # detects the non-numeric output and degrades to perl/seconds.
    (r"date \+%s%3N", "date %3N es GNU; usa ahora_ms()", ("ahora_ms",)),
    (r"head\s+-n\s+-\d", "head -n negativo no existe en BSD", ()),
    (r"\bseq\s+\d", "seq no existe en BSD/macOS; usa while", ()),
    (r"find .*?-printf", "find -printf es sólo GNU", ()),
    (r"sed .*\\s", r"sed POSIX no reconoce \s; usa [[:space:]]", ()),
    (r"\$\{[A-Za-z_][A-Za-z_0-9]*\^\^?\}", "expansión ^ es bash 4+; usa tr", ()),
    (r"\$\{[A-Za-z_][A-Za-z_0-9]*,[^}]*\}", "expansión {a,b} es bash 4+", ()),
    (r"readarray|mapfile", "readarray/mapfile son bash 4+", ()),
    # Resolved for macOS: they move to PROHIBIDOS so they do not come back.
    (r"\btimeout\s+[0-9]",
     "`timeout` no existe en macOS (BSD); usa _timeout()", ()),
    (r"sed -i \"0,/",
     "`sed 0,/re/` es extensión GNU; usa marcar_plan()", ()),
    (r"readlink -f",
     "`readlink -f` es GNU; resuelve symlinks con el bucle while -L", ()),
]


def _bloques_permitidos(lineas: list[str]) -> set[int]:
    """Line numbers that are inside a function with an exception."""
    permitidos: set[int] = set()
    abierta = ""
    for n, linea in enumerate(lineas, 1):
        if not abierta:
            m = re.match(r"^([a-z_][a-z_0-9]*)\s*\(\)\s*\{", linea)
            if m and m.group(1) in {
                f for _, _, fs in PROHIBIDOS for f in fs
            }:
                abierta = m.group(1)
            continue
        permitidos.add(n)
        if linea.strip() == "}":
            abierta = ""
    return permitidos


def _scripts() -> list[Path]:
    """All the .sh in the repo: templates, gate_checks and launchers."""
    out: set[Path] = set()
    for base in SH_DIRS:
        for p in base.rglob("*.sh"):
            if not any(parte in _IGNORAR for parte in p.parts):
                out.add(p.resolve())
    return sorted(out)


def test_hay_plantillas_que_analizar():
    assert len(_scripts()) >= 8


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_sin_crlf(path: Path):
    """With CRLF the shebang `#!/usr/bin/env bash` breaks (`bash\\r`)."""
    crudo = path.read_bytes()
    assert b"\r\n" not in crudo, f"{path.name} tiene finales de línea CRLF"


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_sin_construcciones_gnu(path: Path):
    """Fails if a GNU-only/BSD-broken construct appears."""
    lineas = path.read_text(encoding="utf-8").splitlines()
    permitidos = _bloques_permitidos(lineas)
    offenders = []
    for n, linea in enumerate(lineas, 1):
        if linea.lstrip().startswith("#") or n in permitidos:
            continue
        for patron, motivo, _ in PROHIBIDOS:
            if re.search(patron, linea):
                offenders.append(f"{path.name}:{n}  {motivo}\n    {linea.strip()}")
    assert not offenders, "Construcciones no portables:\n" + "\n".join(offenders)


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_sintaxis_bash(path: Path):
    r = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, f"{path.name}: {r.stderr.strip()}"


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_ejecutable(path: Path):
    """The templates launched with `bash x.sh` do not need it, but the ones
    that go in the destination project's PATH do."""
    if path.name in {"_env.sh", "98_criterio.sh"}:
        pytest.skip("se sourcean/ejecutan con bash explícito")
    assert path.stat().st_mode & 0o111, f"{path.name} no tiene permiso +x"


# ---------------------------------------------------------------------------
# Known pending items: they block Windows and are NOT yet resolved.
# If they disappear, remove them from here (the lint above prevents them from coming back).
# macOS is already resolved: `timeout` and `sed 0,/` have portable alternatives
# (_timeout and marcar_plan) and are now in PROHIBIDOS, not here.
# ---------------------------------------------------------------------------
PENDIENTES_MACOS: set[str] = set()
PENDIENTES_WINDOWS = {
    # The loop and the gate are already Python (they do not need bash). Bash remains only
    # for the project map (mapear.sh, "Refrescar mapa" button) and for the
    # optional bash engine (dedalo.sh): without Git Bash those paths fail.
    "bash": "mapear.sh/dedalo.sh siguen siendo bash: requieren WSL2 o Git Bash",
    # "QProcess(\"bash\")" is no longer there: the GUI launches the gate as
    # `python -m dedalo.gate` (or the --dedalo-gate binary).
    # "os.pathsep" is no longer there: app.py joins the PATH with os.pathsep (it was fixed
    # along with the CLI search with .exe/.cmd suffix in modelos.py).
}


def test_pendientes_documentados_no_ocultan_nada_nuevo():
    """Guardrail: the pending allowlist must exist and be explicit,
    so that what still blocks macOS/Windows stays visible."""
    assert PENDIENTES_MACOS == set(), (
        "macOS quedó resuelto: timeout/sed ya no deben estar en pendientes")
    assert set(PENDIENTES_WINDOWS) == {"bash"}, (
        "actualiza PENDIENTES_WINDOWS (y su comentario) al arreglar o "
        "añadir un bloqueo de Windows")
    # Resolved: they are now PROHIBIDOS so they are not reintroduced.
    prohibidos = " | ".join(p for p, _, _ in PROHIBIDOS)
    assert "timeout" in prohibidos
    assert r"sed -i \"0,/" in prohibidos
    assert "readlink -f" in prohibidos


def test_gitattributes_fuerza_lf_para_sh():
    """Without this, a `git clone` on Windows with autocrlf breaks all the .sh."""
    ga = RAIZ / ".gitattributes"
    assert ga.is_file(), "falta .gitattributes"
    texto = ga.read_text(encoding="utf-8")
    assert re.search(r"^\*\.sh\s+text\s+eol=lf$", texto, re.M), (
        ".gitattributes debe fijar `*.sh text eol=lf`")


# ---------------------------------------------------------------------------
# Formats that must not depend on the user's locale
# ---------------------------------------------------------------------------

_DEDALO = RAIZ / "dedalo" / "plantillas_data" / "dedalo.sh"


def test_awk_de_formatos_usa_locale_c():
    """With a Spanish locale, `awk 'BEGIN{printf "%.6f", x}'` gives "0,500000".

    That decimal comma wrote metrics.jsonl as INVALID JSON and broke the
    cost cap comparison. NOTE: `export LC_NUMERIC=C` does NOT fix it,
    because LC_ALL takes priority over LC_NUMERIC in child processes.
    """
    texto = _DEDALO.read_text(encoding="utf-8")
    assert re.search(r"^num\(\)\s*\{\s*LC_ALL=C awk", texto, re.M), (
        "dedalo.sh debe definir num() con LC_ALL=C awk")
    # No awk that formats a decimal may stay outside the helper.
    sueltos = [n for n, linea in enumerate(texto.splitlines(), 1)
               if re.search(r"(?<![\w-])awk .*printf \"%", linea)
               and not linea.lstrip().startswith("#")]
    assert not sueltos, f"awk sin locale C en las líneas {sueltos}"


def test_exporta_lc_all_c_para_el_printf_de_bash():
    """The other side of the bug: bash's own `printf "%.6f"` uses the shell
    locale and rejected "0.500000" as an invalid number."""
    texto = _DEDALO.read_text(encoding="utf-8")
    m = re.search(r"^export LC_ALL=C$", texto, re.M)
    assert m, "dedalo.sh debe hacer `export LC_ALL=C`"
    assert m.start() < texto.index("costo=$(num"), (
        "el export debe ir antes de calcular el coste")


def test_registrar_metrica_escribe_json_valido(tmp_path):
    """Runs the template's real function under LC_ALL=es_ES."""
    if "es_es" not in subprocess.run(["locale", "-a"], capture_output=True,
                                     text=True).stdout.lower():
        pytest.skip("el runner no tiene locale es_ES; el test A ya lo cubre")

    texto = _DEDALO.read_text(encoding="utf-8")
    ini = texto.index("_registrar_metrica() {")
    funcion = texto[ini:texto.index("\n}", ini) + 2]

    salida = tmp_path / "salida.txt"
    salida.write_text("")
    prog = "\n".join([
        "set -uo pipefail",
        "export LC_ALL=C",              # the export, exactly as in the template
        'num() { LC_ALL=C awk "$@"; }',  # and the helper, in case it is sourced
        f'PROYECTO="{tmp_path}"',
        "iter=1",
        'TAREA="#1 prueba"',
        funcion,
        f'_registrar_metrica opencode opencode/big-pickle 1234 0 "{salida}"',
    ])
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True,
                       env={"LC_ALL": "es_ES.UTF-8", "PATH": os.environ["PATH"]})
    assert r.returncode == 0, r.stderr

    lineas = [x for x in (tmp_path / "metrics.jsonl").read_text().splitlines() if x.strip()]
    assert len(lineas) == 1, lineas
    # If the locale breaks the decimal, this raises JSONDecodeError.
    dato = json.loads(lineas[0])
    assert dato["costo_usd"] == 0.0
    assert dato["dur_ms"] == 1234
    # "0,500000" inside the number (not a field-separating comma).
    assert not re.search(r'":\d+,\d+', lineas[0]), (
        f"coma decimal dentro de un número del JSON: {lineas[0]}")


def test_registrar_metrica_falla_sin_lc_all_c(tmp_path):
    """Counter-check: without the export, the SAME function crashes under es_ES.

    If this test stopped failing, the original bug would have returned (or the
    runner's locale has changed and the tests above would pass by chance).
    """
    if "es_es" not in subprocess.run(["locale", "-a"], capture_output=True,
                                     text=True).stdout.lower():
        pytest.skip("el runner no tiene locale es_ES")

    texto = _DEDALO.read_text(encoding="utf-8")
    ini = texto.index("_registrar_metrica() {")
    funcion = texto[ini:texto.index("\n}", ini) + 2]

    salida = tmp_path / "salida.txt"
    salida.write_text("")
    prog = "\n".join([
        "set -uo pipefail",
        'num() { LC_ALL=C awk "$@"; }',
        f'PROYECTO="{tmp_path}"',
        "iter=1",
        'TAREA="#1 prueba"',
        funcion,
        f'_registrar_metrica opencode opencode/big-pickle 1234 0 "{salida}"',
    ])
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True,
                       env={"LC_ALL": "es_ES.UTF-8", "PATH": os.environ["PATH"]})
    # Without `export LC_ALL=C`, bash's printf does not recognize the decimal point.
    assert r.returncode != 0, (
        "el printf de bash aceptó el punto: revisa que el locale de es_ES "
        "siga.teniendo coma decimal")


# ---------------------------------------------------------------------------
# Portable helpers: _timeout and marcar_plan (base macOS does not ship GNU)
# ---------------------------------------------------------------------------

def _extraer_bloque(nombre: str) -> str:
    texto = _DEDALO.read_text(encoding="utf-8")
    ini = texto.index(f"{nombre}() {{")
    fin = texto.index("\n}", ini) + 2
    return texto[ini:fin]


@pytest.mark.parametrize("marca,esperado", [
    ("x", "- [x] #1 primera"),
    ("B", "- [B] #1 primera"),
])
def test_marcar_plan_portable(tmp_path, marca, esperado):
    """Replaces `sed -i "0,/^- \\[ \\]/s//- [x]/"` (GNU) with awk+cat (POSIX):
    it marks ONLY the first pending task and preserves the plan's permissions."""
    plan = tmp_path / "plan.md"
    plan.write_text(
        "# PLAN\n\n- [x] #0 ya hecha\n- [ ] #1 primera\ncriterio: ok\n"
        "- [ ] #2 segunda\n", encoding="utf-8")
    os.chmod(plan, 0o644)
    prog = "\n".join([
        f'PLAN="{plan}"',
        _extraer_bloque("marcar_plan"),
        f"marcar_plan {marca}",
    ])
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lineas = plan.read_text(encoding="utf-8").splitlines()
    assert esperado in lineas, lineas
    assert "- [ ] #2 segunda" in lineas, "no debe tocar la tarea siguiente"
    # the fixture already has #0 done: `x` adds one, `B` adds no `[x]` at all
    esperadas = 2 if marca == "x" else 1
    assert sum(1 for ln in lineas if ln.startswith("- [x]")) == esperadas
    assert plan.stat().st_mode & 0o777 == 0o644, (
        "`cat > fichero` debe conservar los permisos del plan")


def test_marcar_plan_con_plan_vacio_no_revienta(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("# PLAN\n\n- [x] #0 ya todo hecho\n", encoding="utf-8")
    prog = "\n".join([
        f'PLAN="{plan}"',
        _extraer_bloque("marcar_plan"),
        "marcar_plan x",
        "echo rc=$?",
    ])
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True)
    assert "rc=0" in r.stdout, r.stderr
    assert plan.read_text(encoding="utf-8").count("- [x]") == 1


def test_timeout_con_gnu_devuelve_124_y_completa(tmp_path):
    """GNU branch (Linux/CI): identical to the old `timeout`, 124 when it hangs."""
    prog = "\n".join([
        _extraer_bloque("_timeout"),
        "_timeout 1 sleep 30",
        'echo "rc=$?"',
        "_timeout 10 true",
        'echo "ok=$?"',
    ])
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True,
                       timeout=30)
    assert "rc=124" in r.stdout, r.stdout + r.stderr
    assert "ok=0" in r.stdout, r.stdout + r.stderr


def test_timeout_fallback_de_124_y_mata_al_hijo(tmp_path):
    """Without `timeout` or `gtimeout` in PATH (base macOS): a pure bash
    fallback that must return 124 and leave the child dead, like GNU."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sleep_real = shutil.which("sleep")
    assert sleep_real, "el runner no tiene sleep"
    (bin_dir / "sleep").symlink_to(sleep_real)
    dormir = bin_dir / "dormir"
    dormir.write_text(
        '#!/bin/bash\n'
        'echo $$ > "$PIDF"\n'
        'exec sleep 30\n', encoding="utf-8")
    os.chmod(dormir, 0o755)
    pidf = tmp_path / "pid.txt"
    prog = "\n".join([
        f'PATH="{bin_dir}"',  # neither timeout nor gtimeout is found
        f'PIDF="{pidf}"',
        "export PIDF",
        _extraer_bloque("_timeout"),
        "_timeout 1 dormir",
        'echo "rc=$?"',
    ])
    r = subprocess.run(["bash", "-c", prog], capture_output=True, text=True,
                       timeout=30)
    assert "rc=124" in r.stdout, r.stdout + r.stderr
    assert pidf.is_file(), "el hijo ni siquiera arrancó"
    pid = int(pidf.read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_auto_localizacion_sin_readlink_f(tmp_path):
    """The self-location block of lanzar.sh/acceso.sh must yield the project's
    real path also with absolute, relative and chained symlinks
    (readlink -f does not exist on macOS)."""
    texto = (RAIZ / "lanzar.sh").read_text(encoding="utf-8")
    ini = texto.index('ORIGEN="${BASH_SOURCE')
    fin = texto.index('PROYECTO="$(dirname "$ORIGEN")"', ini)
    fin += len('PROYECTO="$(dirname "$ORIGEN")"')
    bloque = texto[ini:fin]
    assert "readlink -f" not in bloque

    proy = tmp_path / "proy"
    proy.mkdir()
    script = proy / "lanzar.sh"
    script.write_text("set -euo pipefail\n" + bloque
                      + '\necho "P=$PROYECTO"\n', encoding="utf-8")
    enlace = tmp_path / "directo.sh"
    enlace.symlink_to(script)
    relativo = tmp_path / "rel.sh"
    relativo.symlink_to(Path("proy") / "lanzar.sh")

    for entrada in (script, enlace, relativo):
        r = subprocess.run(["bash", str(entrada)], capture_output=True,
                           text=True, cwd=tmp_path)
        assert r.returncode == 0, (entrada, r.stderr)
        assert f"P={proy}" in r.stdout, (entrada, r.stdout)


def test_gui_une_el_path_con_pathsep():
    """Regression: app.py joined the PATH with a hardcoded ":", which corrupts
    the loop's PATH on Windows (separator ';'). It is no longer in
    PENDIENTES_WINDOWS, so this test prevents it from coming back."""
    app = (RAIZ / "dedalo" / "app.py").read_text(encoding="utf-8")
    assert 'env["PATH"] = ":"' not in app, "usa os.pathsep para unir el PATH"
    # The join moved to loop_launch.construir_entorno, shared by the GUI and
    # the MCP server; it is still the place where the PATH is assembled.
    launch = (RAIZ / "dedalo" / "loop_launch.py").read_text(encoding="utf-8")
    assert "os.pathsep" in launch, "usa os.pathsep para unir el PATH"
