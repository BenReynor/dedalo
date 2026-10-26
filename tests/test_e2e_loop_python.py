#!/usr/bin/env python3
"""E2E of the complete Python engine (run() from dedalo.loop).

Functional mirror of test_e2e_con_trabajo.py (the bash engine one): a git repo
with a 1-task plan, a fixture gate, a fake agent that creates src/nuevo.py and
a faked network (monkeypatch of hay_internet, without depending on the real
network).

The run executes in-process (run(cfg)) so the network can be faked; the
engine is the same one the GUI would launch as `python -m dedalo.loop`
(the main() entry point only parses argv and calls run; it is covered in the
loop_args tests).
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dedalo.loop import Config, run  # noqa: E402
from dedalo.loop_args import parse_args  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANTILLAS = os.path.join(RAIZ, "dedalo", "plantillas_data")

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt",
    reason="el e2e ejecuta el gate con bash (no disponible en Windows)")


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T", *args],
                   cwd=cwd, check=True, capture_output=True)


def _agente_falso(dir_bin):
    """Fake agent: responds to `session` and to `run` (creates src/nuevo.py)."""
    dir_bin.mkdir(parents=True, exist_ok=True)
    bin_ = dir_bin / "opencode"
    bin_.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "session" ]; then\n'
        '    case "$2" in\n'
        '        list) echo "[]"; exit 0 ;;\n'
        '        delete) exit 0 ;;\n'
        '    esac\n'
        'fi\n'
        'mkdir -p src\n'
        'printf \'print("nuevo")\\n\' > src/nuevo.py\n'
        'echo \'{"usage":{"input_tokens":10,"output_tokens":10}}\'\n'
        'exit 0\n', encoding="utf-8")
    bin_.chmod(0o755)
    return bin_


def _escenario(tmp_path, gate_txt):
    """Git master project with a 1-task plan and the given gate."""
    proyecto = tmp_path / "proyecto"
    proyecto.mkdir()
    _git("init", "-q", "-b", "master", cwd=proyecto)
    _git("config", "user.email", "t@t", cwd=proyecto)
    _git("config", "user.name", "T", cwd=proyecto)
    (proyecto / "plan.md").write_text(
        "# PLAN\n\n- [ ] t1: crear modulo nuevo\n"
        "      criterio: existe src/nuevo.py\n", encoding="utf-8")
    checks = proyecto / "gate_checks"
    checks.mkdir()
    chk = checks / "01_x.sh"
    chk.write_text(gate_txt, encoding="utf-8")
    chk.chmod(0o755)
    _git("add", "-A", cwd=proyecto)
    _git("commit", "-q", "-m", "base", cwd=proyecto)
    return proyecto


def _entorno(binario):
    env = dict(os.environ)
    env.update({
        "PATH": f"{binario.parent}{os.pathsep}{os.environ.get('PATH', '')}",
        "MAX_ITER": "1",
        "REVISION_DUAL": "0",
        "REVISION_MANUAL": "0",
        "TIMEOUT_POR_TAREA": "60",
        "TIMEOUT_NAVEGADOR": "60",
        "VOZ": "0",
        "NAVEGADOR": "0",
        "CLI_OPENCODE": str(binario),
        "AGENTE_TAREA": "opencode",
        "MODELO_TAREA": "",
        "DEDALO_GATE_CONSENT": "1",
    })
    return env


def _correr(proyecto, env, extra_args=None):
    from unittest import mock

    import dedalo.net
    args = parse_args([str(proyecto / "plan.md")] + (extra_args or []))
    cfg = Config(args, environ=env, proyecto=str(proyecto))
    with mock.patch.object(dedalo.net, "hay_internet",
                           lambda: True):
        return run(cfg), cfg


def test_iteracion_con_trabajo_completa_el_run(tmp_path):
    gate = ("#!/usr/bin/env bash\n"
            'echo "$CRITERIO" > criterio_env.txt\n'
            "exit 0\n")
    proyecto = _escenario(tmp_path, gate)
    bin_falso = _agente_falso(tmp_path / "bin")

    rc, _cfg = _correr(proyecto, _entorno(bin_falso))
    log = (proyecto / "progreso.log").read_text(
        encoding="utf-8", errors="replace")

    assert rc == 0, log[-3000:]
    assert "DEDALO INICIADO" in log
    assert "DEDALO FINALIZADO" in log

    # The task truly completed: commit + plan marked [x].
    plan = (proyecto / "plan.md").read_text(encoding="utf-8")
    assert "- [x] t1" in plan, plan
    gitlog = subprocess.run(
        ["git", "log", "--all", "--format=%s"], cwd=str(proyecto),
        capture_output=True, text=True, check=True)
    assert any(linea.startswith("dedalo:") for linea in gitlog.stdout.splitlines()), \
        gitlog.stdout

    # The task branch was merged into the run branch and deleted.
    ramas = subprocess.run(["git", "branch"], cwd=str(proyecto),
                           capture_output=True, text=True, check=True)
    assert "dedalo/tareas/" not in ramas.stdout, ramas.stdout
    assert any(linea.startswith("* dedalo/") for linea in ramas.stdout.splitlines()), \
        ramas.stdout

    # The CRITERIO reached the gate (env) and no empty --model was passed to the agent.
    assert (proyecto / "criterio_env.txt").read_text(
        encoding="utf-8").strip() == "existe src/nuevo.py"

    # metrics.jsonl with the agent metric (rc 0 and estimated cost).
    metricas = (proyecto / "metrics.jsonl").read_text(encoding="utf-8")
    d = json.loads(metricas.splitlines()[0])
    assert d["agente"] == "opencode" and d["rc"] == 0
    assert d["costo_usd"] > 0
    assert "Costo estimado acumulado:" in log


def test_tarea_que_no_pasa_el_gate_se_bloquea(tmp_path, capsys):
    """The gate fails AFTER working (baseline passes): after the attempts
    the task is left marked [B] without a commit, and the run ends with rc 0."""
    gate = ("#!/usr/bin/env bash\n"
            "if [ -e src/nuevo.py ]; then exit 1; fi\n"
            "exit 0\n")
    proyecto = _escenario(tmp_path, gate)
    bin_falso = _agente_falso(tmp_path / "bin")

    rc, _cfg = _correr(proyecto, _entorno(bin_falso))
    log = (proyecto / "progreso.log").read_text(
        encoding="utf-8", errors="replace")

    assert rc == 0, log[-3000:]
    assert "GATE FALLÓ tras el agente" in log
    assert "tarea BLOQUEADA: t1" in log
    assert "- [B] t1" in (proyecto / "plan.md").read_text(encoding="utf-8")
    gitlog = subprocess.run(
        ["git", "log", "--all", "--format=%s"], cwd=str(proyecto),
        capture_output=True, text=True, check=True)
    asuntos = [linea for linea in gitlog.stdout.splitlines()
               if linea.startswith("dedalo:")]
    assert asuntos == ["dedalo: plan y lecciones (iter 1)"], asuntos
    # The blocked task's work is not committed, but the [B] mark and the lesson are.
    en_commit = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"], cwd=str(proyecto),
        capture_output=True, text=True, check=True).stdout.split()
    assert "plan.md" in en_commit and "lecciones.md" in en_commit

    # incidencias.jsonl records each gate_fail and the final block, and the
    # block inherits the real reason (gate_fail), not a generic text.
    inc = (proyecto / "incidencias.jsonl").read_text(encoding="utf-8")
    eventos = [json.loads(li) for li in inc.splitlines()]
    tipos = [e["tipo"] for e in eventos]
    assert "gate_fail" in tipos, tipos
    assert eventos[-1]["tipo"] == "bloqueada"
    assert "gate_fail" in eventos[-1]["motivo"], eventos[-1]

    # The final summary (stdout) lists the [B] task with its reason.
    salida = capsys.readouterr().out
    assert "TAREAS SIN COMPLETAR" in salida
    assert "- [B] t1" in salida


def test_gate_sin_consentimiento_aborta_con_3(tmp_path, monkeypatch):
    """Without consent (non-interactive) the gate of an unknown repo is not
    run: the run aborts with rc 3 before the baseline."""
    import dedalo.consentimiento as consentimiento
    monkeypatch.setattr(consentimiento, "CONFIG_DIR",
                        str(tmp_path / "cfg_aislado"))
    gate = "#!/usr/bin/env bash\nexit 0\n"
    proyecto = _escenario(tmp_path, gate)
    bin_falso = _agente_falso(tmp_path / "bin")
    env = _entorno(bin_falso)
    env["DEDALO_GATE_CONSENT"] = "0"

    eventos = []

    def enviar_falso(evento, datos=None, config=None, proyecto=None):
        eventos.append(evento)

    monkeypatch.setattr("dedalo.loop.notificaciones.enviar", enviar_falso)
    rc, _cfg = _correr(proyecto, env)
    log = (proyecto / "progreso.log").read_text(
        encoding="utf-8", errors="replace")

    assert rc == 3, log[-3000:]
    assert "sin consentimiento" in log
    # The engine (not only the GUI) reports aborts.
    assert "error" in eventos, eventos


def test_sin_agente_aborta_con_2(tmp_path):
    """Explicit agent whose binary does not exist → exit 2 without touching the loop."""
    proyecto = tmp_path / "proyecto"
    proyecto.mkdir()
    env = _entorno(tmp_path / "bin")
    env["CLI_OPENCODE"] = "/no/existe/opencode"

    rc, _cfg = _correr(proyecto, env)
    log = (proyecto / "progreso.log").read_text(
        encoding="utf-8", errors="replace") \
        if (proyecto / "progreso.log").exists() else ""
    assert rc == 2
    assert "ABORTADO: agente no disponible (opencode)" in log
    inc = (proyecto / "incidencias.jsonl").read_text(encoding="utf-8")
    assert json.loads(inc.splitlines()[0])["tipo"] == "aborto_agente"


def test_integracion_en_rama_de_trabajo(tmp_path):
    """With a different --trabajo, the work is integrated at the end into that branch."""
    gate = "#!/usr/bin/env bash\nexit 0\n"
    proyecto = _escenario(tmp_path, gate)
    bin_falso = _agente_falso(tmp_path / "bin")

    rc, _cfg = _correr(proyecto, _entorno(bin_falso),
                       extra_args=["--trabajo", "integra"])
    log = (proyecto / "progreso.log").read_text(
        encoding="utf-8", errors="replace")

    assert rc == 0, log[-3000:]
    assert "integrado" in log
    integra = subprocess.run(
        ["git", "log", "--format=%s", "integra"], cwd=str(proyecto),
        capture_output=True, text=True, check=True)
    assert any(linea.startswith("dedalo:") for linea in integra.stdout.splitlines()), \
        integra.stdout


def test_contexto_del_proyecto_llega_al_prompt_del_agente(tmp_path):
    """CONTEXTO.md is injected into the agent's prompt (permanent context)."""
    gate = "#!/usr/bin/env bash\nexit 0\n"
    proyecto = _escenario(tmp_path, gate)
    (proyecto / "CONTEXTO.md").write_text(
        "MARCADOR_CONTEXTO_XYZ: es un juego de cartas\n", encoding="utf-8")

    bin_falso = tmp_path / "bin" / "opencode"
    bin_falso.parent.mkdir(parents=True, exist_ok=True)
    bin_falso.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "session" ]; then\n'
        '    case "$2" in\n'
        '        list) echo "[]"; exit 0 ;;\n'
        '        delete) exit 0 ;;\n'
        '    esac\n'
        'fi\n'
        "printf '%s\\n' \"$@\" > prompt_agente.txt\n"
        'mkdir -p src\n'
        'printf \'print("nuevo")\\n\' > src/nuevo.py\n'
        'echo \'{"usage":{"input_tokens":10,"output_tokens":10}}\'\n'
        'exit 0\n', encoding="utf-8")
    bin_falso.chmod(0o755)

    rc, _cfg = _correr(proyecto, _entorno(bin_falso))
    log = (proyecto / "progreso.log").read_text(
        encoding="utf-8", errors="replace")
    assert rc == 0, log[-3000:]

    prompt = (proyecto / "prompt_agente.txt").read_text(encoding="utf-8")
    assert "MARCADOR_CONTEXTO_XYZ" in prompt, prompt[-2000:]
    assert "CONTEXTO DEL PROYECTO" in prompt


def _agente_que_falla(dir_bin, mensaje="boom"):
    """Fake agent that exits 1 without touching the repo."""
    dir_bin.mkdir(parents=True, exist_ok=True)
    bin_ = dir_bin / "opencode"
    bin_.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "session" ]; then echo "[]"; exit 0; fi\n'
        f"echo '{mensaje}' >&2\n"
        "exit 1\n", encoding="utf-8")
    bin_.chmod(0o755)
    return bin_


def test_agente_que_falla_sin_cambios_no_marca_la_tarea_hecha(tmp_path):
    """A failing agent + a green gate used to mark the task [x] with no work."""
    marca = tmp_path / "gate_corrido.txt"  # outside the repo: survives reverts
    gate = f"#!/usr/bin/env bash\necho corrido >> '{marca}'\nexit 0\n"
    proyecto = _escenario(tmp_path, gate)
    bin_falso = _agente_que_falla(tmp_path / "bin")

    rc, _cfg = _correr(proyecto, _entorno(bin_falso))
    log = (proyecto / "progreso.log").read_text(encoding="utf-8", errors="replace")
    plan = (proyecto / "plan.md").read_text(encoding="utf-8")

    assert "- [x] t1" not in plan, log[-2000:]
    assert "- [B] t1" in plan
    assert "AGENTE FALLÓ sin cambios" in log
    # Only the baseline ran the gate; failed attempts never reach it.
    corridas = marca.read_text(encoding="utf-8").split()
    assert len(corridas) == 1, corridas
    assert rc == 0


def test_agente_sin_creditos_detiene_el_loop(tmp_path):
    """'requires usage credits' (claude) is quota exhaustion: stop, rc 5."""
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    bin_falso = _agente_que_falla(
        tmp_path / "bin", "Fable 5 requires usage credits. Switch to another model")

    rc, _cfg = _correr(proyecto, _entorno(bin_falso))
    assert rc == 5
    assert "- [x] t1" not in (proyecto / "plan.md").read_text(encoding="utf-8")


def test_texto_del_agente_sobre_limites_no_detiene_el_loop(tmp_path):
    """An agent that works and *mentions* 'usage limit' must not abort the run."""
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    bin_ = _agente_falso(tmp_path / "bin")
    bin_.write_text(bin_.read_text(encoding="utf-8").replace(
        "mkdir -p src\n", "mkdir -p src\necho 'Añadí el usage limit por cliente'\n"),
        encoding="utf-8")
    rc, _cfg = _correr(proyecto, _entorno(bin_))
    assert rc == 0
    assert "- [x] t1" in (proyecto / "plan.md").read_text(encoding="utf-8")
