#!/usr/bin/env python3
"""Regression tests for the errors found running POS-Minimarket (2026-11).

Wrong task marked, gate consent lost to __pycache__, dirty tree after a
stop, redoing an interrupted run, new-project baseline, plan pauses, single
gate checks and the Codex sandbox/network/reasoning options.
"""

import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_e2e_loop_python import _agente_falso, _correr, _entorno, _escenario, _git  # noqa: E402

from dedalo import codex_cli, consentimiento, gate, loop  # noqa: E402
from dedalo.plan import Plan  # noqa: E402

e2e = pytest.mark.skipif(
    os.name == "nt" or not __import__("shutil").which("bash"),
    reason="the e2e runs the gate with bash")


def _rama_actual(proyecto):
    return subprocess.check_output(
        ["git", "-C", str(proyecto), "branch", "--show-current"],
        text=True).strip()


def _ramas(proyecto):
    return subprocess.check_output(
        ["git", "-C", str(proyecto), "branch", "--format=%(refname:short)"],
        text=True).split()


# --- error 16: the task marked is the one worked on ------------------------

def test_marca_la_tarea_trabajada_aunque_el_plan_cambie(tmp_path):
    ruta = tmp_path / "plan.md"
    ruta.write_text("- [B] a\n- [ ] b\n- [ ] c\n", encoding="utf-8")
    # During the iteration on "b", someone unblocks "a".
    ruta.write_text("- [ ] a\n- [ ] b\n- [ ] c\n", encoding="utf-8")
    p = Plan(str(ruta))
    p.cargar()
    assert p.marcar_tarea("b", "x") is True
    assert ruta.read_text(encoding="utf-8") == "- [ ] a\n- [x] b\n- [ ] c\n"


def test_no_marca_nada_si_la_tarea_ya_no_esta_pendiente(tmp_path):
    ruta = tmp_path / "plan.md"
    ruta.write_text("- [ ] a\n- [x] b\n", encoding="utf-8")
    p = Plan(str(ruta))
    p.cargar()
    assert p.marcar_tarea("b", "x") is False
    assert ruta.read_text(encoding="utf-8") == "- [ ] a\n- [x] b\n"


# --- error 15: __pycache__ does not revoke consent -------------------------

def test_pycache_no_cambia_el_consentimiento(tmp_path):
    checks = tmp_path / ".dedalo" / "scripts" / "gate_checks"
    checks.mkdir(parents=True)
    (checks / "01_a.py").write_text("def run(env):\n    return 0\n")
    antes = consentimiento.manifest(str(tmp_path))
    cache = checks / "__pycache__"
    cache.mkdir()
    (cache / "01_a.cpython-312.pyc").write_bytes(b"\x00planted")
    (checks / "02_b.pyc").write_bytes(b"\x00planted")
    assert consentimiento.manifest(str(tmp_path)) == antes
    # A real change to a check still asks again.
    (checks / "01_a.py").write_text("def run(env):\n    return 1\n")
    assert consentimiento.manifest(str(tmp_path)) != antes


# --- error 5: one check can be run alone ------------------------------------

def test_gate_solo_corre_un_check(tmp_path, capsys):
    checks = tmp_path / "gate_checks"
    checks.mkdir()
    (checks / "01_uno.py").write_text("def run(env):\n    print('UNO')\n    return 0\n")
    (checks / "07_reglas.py").write_text(
        "def run(env):\n    print('SIETE')\n    return 1\n")
    assert gate.correr(str(tmp_path), bash="", solo="7") == 1
    salida = capsys.readouterr().out
    assert "SIETE" in salida and "UNO" not in salida
    assert gate.correr(str(tmp_path), bash="", solo="uno") == 0
    assert gate.correr(str(tmp_path), bash="", solo="nada") == 2


def test_checks_fallidos_del_resumen():
    salida = ("x\n[GATE] ✗ pos: 00_estructura_pos.py falló\n"
              "[GATE] ✗ custom: 06_clippy.sh falló\n[GATE] ❌ 2 check(s) fallaron\n")
    assert loop.checks_fallidos(salida) == ["00_estructura_pos.py", "06_clippy.sh"]


# --- errors 13, 14, 17: Codex ------------------------------------------------

posix = pytest.mark.skipif(os.name == "nt", reason="fake CLI is a shebang script")


@pytest.fixture
def codex_falso(tmp_path):
    binario = tmp_path / "codex"
    binario.write_text(f"#!{sys.executable}\nimport sys\n"
                       "if sys.argv[1:3] == ['mcp', 'list']:\n"
                       "    print('[]')\n", encoding="utf-8")
    binario.chmod(0o755)
    return str(binario)


@posix
def test_codex_tarea_con_red_y_razonamiento_por_rol(codex_falso, tmp_path):
    env = {"CODEX_RAZONAMIENTO_TAREA": "medium", "CODEX_RAZONAMIENTO_JUEZ": "low",
           "PATH": os.environ.get("PATH", "")}
    tarea = codex_cli.flags_codex(codex_falso, env, str(tmp_path), "tarea")
    juez = codex_cli.flags_codex(codex_falso, env, str(tmp_path), "juez")
    assert "sandbox_workspace_write.network_access=true" in tarea
    assert 'model_reasoning_effort="medium"' in tarea
    assert "sandbox_workspace_write.network_access=true" not in juez
    assert 'model_reasoning_effort="low"' in juez
    sin_red = codex_cli.flags_codex(codex_falso, {**env, "CODEX_RED_TAREA": "0"},
                                    str(tmp_path), "tarea")
    assert "sandbox_workspace_write.network_access=true" not in sin_red


def test_nivel_de_razonamiento_invalido_se_ignora():
    assert codex_cli.razonamiento({"CODEX_RAZONAMIENTO_TAREA": "turbo"}, "tarea") == ""


def test_detecta_sandbox_bwrap_bloqueado():
    assert codex_cli.sandbox_roto(
        "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted")
    assert not codex_cli.sandbox_roto("cargo test: 12 passed")


@posix
def test_codex_sin_sandbox_explicito_aplica_a_todos_los_roles(codex_falso, tmp_path):
    env = {"CODEX_SIN_SANDBOX": "1", "PATH": os.environ.get("PATH", "")}
    for rol in ("tarea", "revisor", "juez"):
        flags = codex_cli.flags_codex(codex_falso, env, str(tmp_path), rol)
        assert "--dangerously-bypass-approvals-and-sandbox" in flags
        assert "--sandbox" not in flags


@posix
def test_preflight_del_sandbox_avisa_si_bwrap_falla(tmp_path):
    binario = tmp_path / "codex"
    binario.write_text("#!/bin/sh\necho 'bwrap: setting up uid map: "
                       "Permission denied' >&2\nexit 1\n")
    binario.chmod(0o755)
    ok, detalle = codex_cli.sandbox_funciona(str(binario))
    if sys.platform.startswith("linux"):
        assert ok is False and "uid map" in detalle


def test_lanzamiento_pasa_modelo_juez_y_razonamiento():
    from dedalo import loop_launch
    conf = {"agente_cli": "codex", "revisor_cli": "codex", "agente": "openai/gpt-6",
            "modelo_juez": "openai/gpt-6-luna", "razonamiento_tarea": "high",
            "razonamiento_juez": "low", "red_agente": False}
    env = loop_launch.construir_entorno(conf, {}, ["codex"], {"PATH": "/usr/bin"})
    assert env["MODELO_JUEZ"] == "gpt-6-luna"
    assert env["CODEX_RAZONAMIENTO_TAREA"] == "high"
    assert env["CODEX_RAZONAMIENTO_JUEZ"] == "low"
    assert env["CODEX_RED_TAREA"] == "0"


# --- errors 3 and 7: clean stops ---------------------------------------------

@e2e
def test_parada_por_cuota_deja_el_repo_limpio(tmp_path):
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    bin_ = _agente_falso(tmp_path / "bin")
    bin_.write_text(bin_.read_text(encoding="utf-8").replace(
        "mkdir -p src\n",
        "mkdir -p src\necho a medias > src/parcial.py\n"
        "echo \"You've hit your 5-hour limit · resets 1pm\" >&2\nexit 1\n"),
        encoding="utf-8")
    rc, cfg = _correr(proyecto, _entorno(bin_))
    assert rc == 5
    assert not (proyecto / "src" / "parcial.py").exists()
    assert _rama_actual(proyecto).startswith("dedalo/2")
    assert not [r for r in _ramas(proyecto) if r.startswith("dedalo/tareas/")]
    stash = subprocess.check_output(["git", "-C", str(proyecto), "stash", "list"],
                                    text=True)
    assert "parcial" in stash
    assert "git stash" in (proyecto / "progreso.log").read_text(encoding="utf-8")


# --- error 2: an interrupted run is continued, not redone --------------------

@e2e
def test_relanzar_continua_la_ejecucion_anterior(tmp_path):
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    plan = proyecto / "plan.md"
    plan.write_text("# PLAN\n\n- [ ] t1: crear modulo nuevo\n- [ ] t2: otra\n",
                    encoding="utf-8")
    _git("commit", "-qam", "plan", cwd=proyecto)
    _git("checkout", "-q", "master", cwd=proyecto)
    bin_ = _agente_falso(tmp_path / "bin")
    rc, _ = _correr(proyecto, _entorno(bin_))  # MAX_ITER=1: only t1
    assert rc == 0
    primera = _rama_actual(proyecto)
    _git("checkout", "-q", "master", cwd=proyecto)  # the user goes back to master
    time.sleep(1.1)  # run branches are named by the second
    rc, _ = _correr(proyecto, _entorno(bin_))
    log = (proyecto / "progreso.log").read_text(encoding="utf-8")
    assert rc == 0, log[-2000:]
    assert f"RETOMANDO desde {primera}" in log
    texto = plan.read_text(encoding="utf-8")
    assert "- [x] t1" in texto and "- [x] t2" in texto
    assert log.count("== Iteración 1: t1") == 1  # t1 was not redone


@e2e
def test_arbol_sucio_al_arrancar_aborta_con_motivo(tmp_path):
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    (proyecto / "mio.txt").write_text("trabajo del usuario")
    rc, _ = _correr(proyecto, _entorno(_agente_falso(tmp_path / "bin")))
    assert rc == 1
    assert "árbol sucio (mio.txt)" in (proyecto / "progreso.log").read_text(
        encoding="utf-8")
    assert (proyecto / "mio.txt").exists()


# --- errors 1 and 11: a new project can start --------------------------------

_GATE_ESQUELETO = ("#!/usr/bin/env bash\n"
                   "[ -e src/nuevo.py ] || { echo '[GATE] ✗ falta src/nuevo.py'; "
                   "exit 1; }\nexit 0\n")


@e2e
def test_proyecto_nuevo_arranca_con_baseline_rojo(tmp_path):
    proyecto = _escenario(tmp_path, _GATE_ESQUELETO)
    rc, _ = _correr(proyecto, _entorno(_agente_falso(tmp_path / "bin")))
    log = (proyecto / "progreso.log").read_text(encoding="utf-8")
    assert rc == 0, log[-2000:]
    assert "se toleran (01_x.sh)" in log
    assert "- [x] t1" in (proyecto / "plan.md").read_text(encoding="utf-8")


@e2e
def test_baseline_estricto_o_proyecto_empezado_sigue_abortando(tmp_path):
    proyecto = _escenario(tmp_path, _GATE_ESQUELETO)
    env = {**_entorno(_agente_falso(tmp_path / "bin")), "BASELINE": "estricto"}
    rc, _ = _correr(proyecto, env)
    assert rc == 1
    assert "ABORTADO: baseline falló: 01_x.sh" in (
        proyecto / "progreso.log").read_text(encoding="utf-8")

    (tmp_path / "otro").mkdir()
    otro = _escenario(tmp_path / "otro", _GATE_ESQUELETO)
    (otro / "plan.md").write_text("- [x] hecha\n- [ ] t1: crear\n", encoding="utf-8")
    _git("commit", "-qam", "plan", cwd=otro)
    rc, _ = _correr(otro, _entorno(_agente_falso(tmp_path / "bin2")))
    assert rc == 1


# --- improvement 1: the plan can say "stop here" ------------------------------

@e2e
def test_parar_en_el_plan_detiene_antes_de_la_siguiente_tarea(tmp_path):
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    plan = proyecto / "plan.md"
    plan.write_text("- [ ] t1: crear modulo nuevo\n- [PARAR] fin de la fase 1\n"
                    "- [ ] t2: otra\n", encoding="utf-8")
    _git("commit", "-qam", "plan", cwd=proyecto)
    env = {**_entorno(_agente_falso(tmp_path / "bin")), "MAX_ITER": "5"}
    rc, _ = _correr(proyecto, env)
    texto = plan.read_text(encoding="utf-8")
    assert rc == 0
    assert "- [x] t1" in texto and "- [ ] t2" in texto
    assert "- [PARADO] fin de la fase 1" in texto
    assert "PAUSA DEL PLAN: fin de la fase 1" in (
        proyecto / "progreso.log").read_text(encoding="utf-8")


@e2e
def test_check_tolerado_no_salta_la_proteccion_del_juez(tmp_path):
    """A tolerated red check must not let a judge without verdict pass the task."""
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\necho '[GATE] ✗ rojo'\nexit 1\n")
    juez = proyecto / "gate_checks" / "98_criterio.sh"
    juez.write_text("#!/usr/bin/env bash\necho '[GATE] ⚠ juez sin veredicto legible'\n"
                    "exit 0\n", encoding="utf-8")
    juez.chmod(0o755)
    _git("add", "-A", cwd=proyecto)
    _git("commit", "-qm", "juez", cwd=proyecto)
    env = {**_entorno(_agente_falso(tmp_path / "bin")), "ESPERA_JUEZ": "0"}
    rc, _ = _correr(proyecto, env)
    log = (proyecto / "progreso.log").read_text(encoding="utf-8")
    assert "se toleran (01_x.sh)" in log
    assert rc == 8, log[-1500:]
    assert "- [ ] t1" in (proyecto / "plan.md").read_text(encoding="utf-8")


# --- point 16, case B: never revert what could not be saved -------------------

def _repo_con_trabajo(tmp_path):
    from dedalo import loop_git
    _git("init", "-q", "-b", "master", cwd=tmp_path)
    (tmp_path / "a.txt").write_text("viejo\n", encoding="utf-8")
    _git("add", "-A", cwd=tmp_path)
    _git("commit", "-qm", "base", cwd=tmp_path)
    _git("branch", "dedalo/run", cwd=tmp_path)
    _git("checkout", "-qb", "dedalo/tareas/t1", cwd=tmp_path)
    (tmp_path / "a.txt").write_text("nuevo\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("archivo nuevo\n", encoding="utf-8")
    loop_git.diff_para_revisor(str(tmp_path))  # leaves intent-to-add entries


def _cfg_parada(tmp_path):
    from types import SimpleNamespace
    return SimpleNamespace(
        proyecto=str(tmp_path), rama_tarea="dedalo/tareas/t1",
        rama_run="dedalo/run", tarea_actual="t1",
        log=str(tmp_path / "progreso.log"),
        incidencias=str(tmp_path / "incidencias.jsonl"))


def test_parada_tras_el_revisor_guarda_el_trabajo(tmp_path):
    _repo_con_trabajo(tmp_path)
    loop._parar_limpio(_cfg_parada(tmp_path), "cuota")
    assert _rama_actual(tmp_path) == "dedalo/run"
    assert not (tmp_path / "b.txt").exists()
    _git("stash", "apply", cwd=tmp_path)
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "archivo nuevo\n"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "nuevo\n"


def test_si_el_stash_falla_no_se_borra_nada(tmp_path, monkeypatch):
    from dedalo import loop_git
    _repo_con_trabajo(tmp_path)
    monkeypatch.setattr(loop_git, "guardar_parcial", lambda *a, **k: None)
    loop._parar_limpio(_cfg_parada(tmp_path), "cuota")
    assert _rama_actual(tmp_path) == "dedalo/tareas/t1"
    assert (tmp_path / "b.txt").exists()
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "nuevo\n"
    assert "no se pudo guardar" in (tmp_path / "progreso.log").read_text(encoding="utf-8")
