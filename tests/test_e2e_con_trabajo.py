#!/usr/bin/env python3
"""E2E of the full dedalo.sh run with a fake agent that DOES work.

Regression of the script's most serious bug (line ~1140): `local iter_sin_trabajo=0`
was at the file's top level (inside the retry while, outside
any function). In bash `local` outside a function leaves the variable NOT
CREATED, and the next line (`iteracion_sin_trabajo && iter_sin_trabajo=1`)
only assigns it if there is NO work… so any iteration in which the
agent produced changes reached the next check with `set -u` and
aborted with `iter_sin_trabajo: unbound variable` → exit 1: no commit, no
marking [x], no summary. No existing test caught it:

  · test_dedalo_senales.py only uses agents that hang or that do not
    change anything (there the variable's branch DOES assign it).
  · test_agentes.py extracts loose functions and its harness uses the
    fixed form (`iter_sin_trabajo=0` without `local`), reinforcing the error.

It also covers the second arguments bug: `shift 2` without checking `$#`
left `--hasta/--padre/--trabajo` as the LAST argument in an
infinite loop at 100% CPU.
"""

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLAS = RAIZ / "dedalo" / "plantillas_data"

from dedalo import plantillas, rutas  # noqa: E402

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt",
    reason="el e2e ejecuta dedalo.sh con bash (no disponible en Windows)")


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T", *args],
                   cwd=cwd, check=True, capture_output=True)


def _agente_falso(dir_bin, con_trabajo: bool):
    """Fast fake agent: it responds to `session` and exits 0 instantly.

    If `con_trabajo`, it creates a new file (the path that broke the bug);
    if not, it does not touch the tree (the path that DID work and that masked
    the regression).
    """
    dir_bin.mkdir(parents=True, exist_ok=True)
    cuerpo = ("mkdir -p src && echo \"print('nuevo')\" > src/nuevo.py\n"
              if con_trabajo else "true\n")
    bin_ = dir_bin / "opencode"
    bin_.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        if [ "$1" = "debug" ]; then echo "{{}}"; exit 0; fi
        if [ "$1" = "session" ]; then
            case "$2" in
                list) echo "[]"; exit 0 ;;
                delete) exit 0 ;;
            esac
        fi
        {cuerpo}
        echo '{{"usage":{{"input_tokens":10,"output_tokens":10}}}}'
        exit 0"""), encoding="utf-8")
    bin_.chmod(0o755)
    return bin_


def _stub_red(dir_bin, nombre):
    """Fake ping/curl so `hay_internet` does not depend on the real network."""
    stub = dir_bin / nombre
    stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)


def _escenario(tmp_path, con_trabajo: bool):
    """Git project with the framework copied, a 1-task plan and an agent."""
    proyecto = tmp_path / "proyecto"
    proyecto.mkdir()
    _git("init", "-q", "-b", "master", cwd=proyecto)
    # Repo-level identity: the LOOP's commits (not the fixture's)
    # go without `-c`, and without it `git commit` would fail and the test could not
    # distinguish the bug from an identity failure.
    _git("config", "user.email", "t@t", cwd=proyecto)
    _git("config", "user.name", "T", cwd=proyecto)
    (proyecto / "plan.md").write_text(
        "# PLAN\n\n- [ ] t1: crear modulo nuevo\n"
        "      criterio: existe src/nuevo.py\n", encoding="utf-8")
    # Real installation: scripts and checks under `.dedalo/`. The generated
    # .gitignore keeps them out of the repo, so the gate's `ruff check .` does
    # not lint the port's .py checks and the baseline does not abort.
    plantillas.instalar(str(proyecto))
    plantillas.asegurar_gitignore(str(proyecto))
    _git("add", "-A", cwd=proyecto)
    _git("commit", "-q", "-m", "base", cwd=proyecto)

    dir_bin = tmp_path / "bin"
    _agente_falso(dir_bin, con_trabajo=con_trabajo)
    _stub_red(dir_bin, "ping")
    _stub_red(dir_bin, "curl")
    return proyecto, dir_bin


def _entorno(dir_bin):
    env = dict(os.environ)
    env.update({
        "PATH": f"{dir_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "MAX_ITER": "1",
        "MAX_REINTENTOS": "1",
        "REVISION_DUAL": "0",
        "REVISION_MANUAL": "0",
        "TIMEOUT_POR_TAREA": "60",
        "MAX_COSTO": "0",
        "VOZ": "0",
        "CLI_OPENCODE": str(dir_bin / "opencode"),
        "AGENTE_TAREA": "opencode",
        "DEDALO_GATE_CONSENT": "1",
    })
    return env


def _correr(proyecto, env):
    return subprocess.run(
        ["bash", rutas.dedalo_sh(str(proyecto)), "plan.md"],
        cwd=str(proyecto), env=env,
        capture_output=True, text=True, timeout=120)


def test_iteracion_con_trabajo_completa_el_run(tmp_path):
    """REGRESSION 1134: with real work the run must finish and commit."""
    proyecto, dir_bin = _escenario(tmp_path, con_trabajo=True)

    proc = _correr(proyecto, _entorno(dir_bin))
    log_path = Path(rutas.log(str(proyecto)))
    log = log_path.read_text(errors="replace") if log_path.exists() else ""
    combinado = proc.stdout + proc.stderr + log

    # The exact symptom of the bug: `local` outside a function + `set -u`.
    assert "unbound variable" not in combinado, combinado[-3000:]
    assert "sólo se puede usar dentro de una función" not in combinado, \
        combinado[-3000:]

    # The run must finish normally (with the bug it exited 1 mid-task).
    assert proc.returncode == 0, f"rc={proc.returncode}\n{combinado[-3000:]}"
    assert "DEDALO FINALIZADO" in log

    # The task was really completed: commit + plan marked.
    assert "- [x] t1" in (proyecto / "plan.md").read_text(encoding="utf-8"), \
        f"t1 sin marcar:\n{combinado[-3000:]}"
    loggit = subprocess.run(
        ["git", "log", "--all", "--format=%s"], cwd=str(proyecto),
        capture_output=True, text=True, check=True)
    assert any(linea.startswith("dedalo:") for linea in loggit.stdout.splitlines()), \
        f"no hubo commit de iteración:\n{loggit.stdout}"


def test_iteracion_sin_trabajo_no_crashea(tmp_path):
    """The other path of 1134 (agent that changes nothing) must not
    abort either: there the variable WAS assigned, but the test pins it so that
    neither of the two branches breaks again."""
    proyecto, dir_bin = _escenario(tmp_path, con_trabajo=False)

    proc = _correr(proyecto, _entorno(dir_bin))
    log_path = Path(rutas.log(str(proyecto)))
    log = log_path.read_text(errors="replace") if log_path.exists() else ""
    combinado = proc.stdout + proc.stderr + log

    assert "unbound variable" not in combinado, combinado[-3000:]
    assert proc.returncode == 0, f"rc={proc.returncode}\n{combinado[-3000:]}"
    assert "DEDALO FINALIZADO" in log


@pytest.mark.parametrize("opcion", ["--hasta", "--padre", "--trabajo"])
def test_opcion_sin_valor_no_deja_cuelgar(opcion):
    """REGRESSION: `shift 2` without checking `$#` spun forever if the
    option came as the LAST argument (100% CPU, it was killed with
    timeout). Now it fails fast with EX_USAGE (64)."""
    proc = subprocess.run(
        ["bash", str(PLANTILLAS / "dedalo.sh"), opcion],
        capture_output=True, text=True, timeout=10)
    assert proc.returncode == 64, (
        f"{opcion} sin valor: rc={proc.returncode}\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr}")
    assert "falta valor" in proc.stderr
