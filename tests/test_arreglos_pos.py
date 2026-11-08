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


# --- point 12: the task comes from the run branch's plan ----------------------

@e2e
def test_con_rama_de_trabajo_la_tarea_sale_del_plan_del_run(tmp_path):
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    plan = proyecto / "plan.md"
    plan.write_text("# PLAN\n\n- [ ] t1: crear modulo nuevo\n- [ ] t2: otra\n",
                    encoding="utf-8")
    _git("commit", "-qam", "plan", cwd=proyecto)
    bin_ = _agente_falso(tmp_path / "bin")
    assert _correr(proyecto, _entorno(bin_))[0] == 0  # MAX_ITER=1: only t1
    _git("checkout", "-q", "master", cwd=proyecto)
    time.sleep(1.1)  # run branches are named by the second
    rc, _ = _correr(proyecto, _entorno(bin_), ["--trabajo", "master"])
    log = (proyecto / "progreso.log").read_text(encoding="utf-8")
    assert rc == 0, log[-2000:]
    assert log.count(": t1: crear modulo nuevo (rama") == 1, "t1 was redone"
    assert "== Iteración 1: t2" in log


# --- point 16: blocked work is kept; a quota in the judge repeats only that ----

def _agente_que_cuenta(tmp_path):
    bin_ = _agente_falso(tmp_path / "bin")
    cuenta = tmp_path / "llamadas_agente"
    bin_.write_text(bin_.read_text(encoding="utf-8").replace(
        "mkdir -p src\n", f"case \"$*\" in *--help*) ;; *) echo x >> '{cuenta}' ;; esac\nmkdir -p src\n"), encoding="utf-8")
    return bin_, cuenta


@e2e
def test_tarea_bloqueada_conserva_su_trabajo(tmp_path):
    gate = "#!/usr/bin/env bash\n[ -e src/nuevo.py ] && exit 1\nexit 0\n"
    proyecto = _escenario(tmp_path, gate)
    rc, _ = _correr(proyecto, _entorno(_agente_falso(tmp_path / "bin")))
    assert rc == 0
    assert "- [B] t1" in (proyecto / "plan.md").read_text(encoding="utf-8")
    assert not (proyecto / "src" / "nuevo.py").exists()
    bloqueadas = [r for r in _ramas(proyecto) if r.startswith("dedalo/bloqueadas/")]
    assert len(bloqueadas) == 1
    contenido = subprocess.check_output(
        ["git", "-C", str(proyecto), "show", f"{bloqueadas[0]}:src/nuevo.py"], text=True)
    assert "nuevo" in contenido


@e2e
def test_cuota_en_el_juez_al_reanudar_no_llama_al_agente(tmp_path):
    from test_e2e_loop_python import _gate_con_juez
    aviso = ("[GATE] ⚠ juez salió con rc=1 (¿cuota o red?): Credit balance is too "
             "low; se omite (no bloqueante)")
    gate, _c = _gate_con_juez(tmp_path, [aviso] * 3 + ["[GATE] ✓ juez: criterio cumplido"])
    proyecto = _escenario(tmp_path, gate)
    bin_, cuenta = _agente_que_cuenta(tmp_path)
    env = {**_entorno(bin_), "ESPERA_JUEZ": "0"}
    assert _correr(proyecto, env)[0] == 5
    assert not (proyecto / "src" / "nuevo.py").exists()
    assert cuenta.read_text().count("x") == 1
    time.sleep(1.1)
    rc, _ = _correr(proyecto, env)
    log = (proyecto / "progreso.log").read_text(encoding="utf-8")
    assert rc == 0, log[-2000:]
    assert "REANUDANDO verificación" in log
    assert cuenta.read_text().count("x") == 1, "the agent was called again"
    assert "- [x] t1" in (proyecto / "plan.md").read_text(encoding="utf-8")
    assert subprocess.check_output(
        ["git", "-C", str(proyecto), "stash", "list"], text=True) == ""


@e2e
def test_si_la_tarea_cambio_tras_la_cuota_se_empieza_de_cero(tmp_path):
    from test_e2e_loop_python import _gate_con_juez
    aviso = ("[GATE] ⚠ juez salió con rc=1 (¿cuota o red?): Credit balance is too "
             "low; se omite (no bloqueante)")
    gate, _c = _gate_con_juez(tmp_path, [aviso] * 3 + ["[GATE] ✓ juez: ok"])
    proyecto = _escenario(tmp_path, gate)
    bin_, cuenta = _agente_que_cuenta(tmp_path)
    env = {**_entorno(bin_), "ESPERA_JUEZ": "0"}
    assert _correr(proyecto, env)[0] == 5
    plan = proyecto / "plan.md"
    plan.write_text(plan.read_text(encoding="utf-8").replace(
        "existe src/nuevo.py", "existe src/nuevo.py y funciona"), encoding="utf-8")
    time.sleep(1.1)
    assert _correr(proyecto, env)[0] == 0
    assert cuenta.read_text().count("x") == 2


# --- point 13: the loop outlives its launcher and recovers if it dies ----------

@pytest.mark.parametrize("hay_systemd", [True, False])
def test_scope_propio_solo_si_hay_systemd(monkeypatch, hay_systemd):
    from types import SimpleNamespace

    from dedalo import loop_launch
    monkeypatch.setattr(loop_launch.sys, "platform", "linux")
    monkeypatch.setattr(loop_launch.shutil, "which",
                        lambda _n: "/usr/bin/systemd-run" if hay_systemd else None)
    monkeypatch.setattr(loop_launch.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0))
    programa, argv = loop_launch.en_scope_propio("py", ["-m", "x"], "mi proyecto")
    if hay_systemd:
        assert programa == "/usr/bin/systemd-run"
        assert argv[:2] == ["--user", "--scope"] and argv[-3:] == ["py", "-m", "x"]
        assert any(a.startswith("--unit=dedalo-mi-proyecto-") for a in argv)
    else:
        assert (programa, argv) == ("py", ["-m", "x"])


def test_sin_gestor_de_usuario_no_se_envuelve(monkeypatch):
    from types import SimpleNamespace

    from dedalo import loop_launch
    monkeypatch.setattr(loop_launch.sys, "platform", "linux")
    monkeypatch.setattr(loop_launch.shutil, "which", lambda _n: "/usr/bin/systemd-run")
    monkeypatch.setattr(loop_launch.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1))
    assert loop_launch.en_scope_propio("py", ["-m"], "n") == ("py", ["-m"])


def _rama_tarea_abandonada(proyecto):
    """Repo as a killed engine leaves it: on a task branch with loose work."""
    _git("branch", "dedalo/2026-01-01_00-00-00", cwd=proyecto)
    _git("checkout", "-qb", "dedalo/tareas/2026-01-01_00-00-00/t5", cwd=proyecto)
    (proyecto / "a_medias.txt").write_text("trabajo\n", encoding="utf-8")


@e2e
def test_al_arrancar_recupera_el_trabajo_de_un_loop_muerto(tmp_path):
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    _rama_tarea_abandonada(proyecto)
    rc, _ = _correr(proyecto, _entorno(_agente_falso(tmp_path / "bin")))
    log = (proyecto / "progreso.log").read_text(encoding="utf-8")
    assert rc == 0, log[-2000:]
    assert "RECUPERADO tras muerte del loop" in log
    assert not (proyecto / "a_medias.txt").exists()
    stash = subprocess.check_output(["git", "-C", str(proyecto), "stash", "list"],
                                    text=True)
    assert "recuperado tras muerte del loop" in stash
    assert "dedalo/tareas/2026-01-01_00-00-00/t5" not in _ramas(proyecto)


@e2e
def test_si_no_puede_guardar_lo_de_un_loop_muerto_no_toca_nada(tmp_path, monkeypatch):
    from dedalo import loop_git
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    _rama_tarea_abandonada(proyecto)
    monkeypatch.setattr(loop_git, "guardar_parcial", lambda *a, **k: None)
    rc, _ = _correr(proyecto, _entorno(_agente_falso(tmp_path / "bin")))
    assert rc == 1
    assert (proyecto / "a_medias.txt").exists()
    assert _rama_actual(proyecto) == "dedalo/tareas/2026-01-01_00-00-00/t5"


# --- point 14: a network blip does not lose a notification ---------------------

@pytest.fixture
def plataforma_falsa(monkeypatch):
    from dedalo import notificaciones
    envios = {"fallos": 0, "llegados": []}

    def enviar(_config, texto):
        if envios["fallos"] > 0:
            envios["fallos"] -= 1
            raise ConnectionResetError(104, "Connection reset by peer")
        envios["llegados"].append(texto)
        return "OK"

    monkeypatch.setattr(notificaciones, "_PLATAFORMAS",
                        (("falsa", enviar, lambda _c: True),))
    monkeypatch.setattr(notificaciones, "_ESPERAS_REINTENTO", (1, 3, 10))
    esperas = []
    monkeypatch.setattr(notificaciones.time, "sleep", esperas.append)
    envios["esperas"] = esperas
    return envios


def test_notificacion_se_reintenta_tras_un_corte(plataforma_falsa):
    from dedalo import notificaciones
    plataforma_falsa["fallos"] = 2
    assert notificaciones.enviar_texto({}, "aviso") == [("falsa", "OK")]
    assert plataforma_falsa["esperas"] == [1, 3]
    assert plataforma_falsa["llegados"] == ["aviso"]


def test_notificacion_perdida_sale_con_la_siguiente(plataforma_falsa):
    from dedalo import notificaciones
    plataforma_falsa["fallos"] = 4
    estado = notificaciones.enviar_texto({}, "cuota agotada")[0][1]
    assert "encolada" in estado and plataforma_falsa["llegados"] == []
    assert notificaciones.enviar_texto({}, "fin") == [("falsa", "OK")]
    assert plataforma_falsa["llegados"] == ["fin", "cuota agotada"]


def test_boton_de_probar_no_reintenta(plataforma_falsa):
    from dedalo import notificaciones
    plataforma_falsa["fallos"] = 1
    estado = notificaciones.enviar_texto({}, "prueba", solo="falsa")[0][1]
    assert "reset" in estado and plataforma_falsa["esperas"] == []


# --- point 18: tasks only a person can do --------------------------------------

@e2e
def test_tareas_manuales_se_saltan_y_se_listan(tmp_path, capsys):
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    plan = proyecto / "plan.md"
    plan.write_text("- [M] comprar la impresora\n- [ ] t1: crear modulo nuevo\n",
                    encoding="utf-8")
    _git("commit", "-qam", "plan", cwd=proyecto)
    rc, _ = _correr(proyecto, _entorno(_agente_falso(tmp_path / "bin")))
    texto = plan.read_text(encoding="utf-8")
    assert rc == 0
    assert "- [M] comprar la impresora" in texto and "- [x] t1" in texto
    assert "- [M] comprar la impresora" in capsys.readouterr().out
    p = Plan(str(plan))
    p.cargar()
    assert p.manuales == ["comprar la impresora"]
    assert p.conteo() == (0, 1, 0)


# --- point 19: the plan grows during a run --------------------------------------

def _agente_que_amplia(tmp_path):
    bin_ = _agente_falso(tmp_path / "bin")
    bin_.write_text(bin_.read_text(encoding="utf-8").replace(
        "mkdir -p src\n",
        "case \"$*\" in *--help*) ;; *) printf -- '- [ ] t9: nueva\\n' >> plan.md ;; esac\n"
        "mkdir -p src\n"),
        encoding="utf-8")
    return bin_


@e2e
@pytest.mark.parametrize("pausar", [False, True])
def test_avisa_si_el_plan_crece_y_puede_pausar(tmp_path, monkeypatch, pausar):
    avisos = []
    monkeypatch.setattr(loop, "_notificar",
                        lambda _c, evento, **d: avisos.append((evento, d)))
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    env = {**_entorno(_agente_que_amplia(tmp_path)), "MAX_ITER": "1"}
    if pausar:
        env.update({"MAX_ITER": "5", "PAUSAR_SI_CRECE": "1"})
    rc, _ = _correr(proyecto, env)
    log = (proyecto / "progreso.log").read_text(encoding="utf-8")
    assert rc == 0, log[-1500:]
    assert "PLAN AMPLIADO: 1 tarea(s)" in log
    crecio = [d for e, d in avisos if e == "plan_crecio"]
    assert crecio and crecio[0]["n"] == 1 and "t9: nueva" in crecio[0]["titulos"]
    if pausar:
        assert log.count("== Iteración") == 1


# --- point 22: the gate names the failed test -----------------------------------

_SALIDA_CARGO = """running 2 tests
test ventas::suma ... ok
test ventas::resta ... FAILED

failures:

---- ventas::resta stdout ----

thread 'ventas::resta' panicked at src/ventas.rs:9:5:
assertion failed

failures:
    ventas::resta

test result: FAILED. 1 passed; 1 failed
error: test failed, to rerun pass `--lib`
"""


def _check_rust():
    import importlib.util
    ruta = os.path.join(os.path.dirname(gate.__file__), "plantillas_data", "plantillas",
                        "rust", "gate_checks", "03_test.py")
    spec = importlib.util.spec_from_file_location("check_rust_test", ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(modulo)
    return modulo


def test_check_rust_nombra_el_test_que_fallo():
    check = _check_rust()
    assert check._tests_fallidos(_SALIDA_CARGO) == ["ventas::resta"]
    salida = check._errores(_SALIDA_CARGO)
    assert "ventas::resta ... FAILED" in salida and "panicked at" in salida


@pytest.mark.parametrize(("segundo", "esperado"), [(0, 0), (101, 1)])
def test_check_rust_repite_y_marca_inestable(monkeypatch, tmp_path, capsys, segundo, esperado):
    from types import SimpleNamespace
    check = _check_rust()
    (tmp_path / "Cargo.toml").write_text("")
    rcs = [101, segundo]
    monkeypatch.setattr(check.shutil, "which", lambda _n: "/bin/cargo")
    monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=rcs.pop(0), stdout=_SALIDA_CARGO, stderr=""))
    avisos, fallos = [], []
    env = SimpleNamespace(proyecto=str(tmp_path), aviso=avisos.append,
                          fail=fallos.append, ok=lambda _m: None)
    assert check.run(env) == esperado
    if esperado == 0:
        assert "inestables" in avisos[0] and "ventas::resta" in avisos[0]
    else:
        assert "ventas::resta" in fallos[0]


# --- point 15: criteria the agent is allowed to fulfil ---------------------------

def test_comandos_extra_solo_nombres_simples():
    from dedalo.loop_agentes import comandos_validos
    assert comandos_validos("gitleaks, make  ./x.sh") == ["gitleaks", "make", "./x.sh"]
    assert comandos_validos(["ok", "*", "rm(-rf)"]) == ["ok"]


def test_comandos_extra_entran_en_la_lista_de_claude(tmp_path):
    from dedalo.loop_agentes import flags_claude
    flags = flags_claude("tarea", str(tmp_path), comandos=["gitleaks"])
    assert "Bash(gitleaks:*)" in flags


def test_avisa_de_comandos_del_criterio_sin_permiso(tmp_path, monkeypatch):
    monkeypatch.setattr(loop.shutil, "which", lambda c: f"/bin/{c}" if c != "noinstalado" else None)
    plan = tmp_path / "plan.md"
    plan.write_text(
        "- [ ] a\n  criterio: pasa `gitleaks detect` y `cargo test` y `noinstalado x`\n"
        "- [ ] b\n  criterio: pasa `cargo test`\n"
        "- [x] c\n  criterio: `rm -rf x`\n", encoding="utf-8")
    assert loop._comandos_no_permitidos(str(plan), ["cargo"]) == [("a", "gitleaks")]


def test_el_juez_sabe_que_podia_ejecutar_el_agente(tmp_path):
    from types import SimpleNamespace
    cfg = SimpleNamespace(agente_tarea="claude", proyecto=str(tmp_path),
                          comandos_extra=["gitleaks"])
    assert "gitleaks" in loop._criterio_para_juez(cfg, "pasa el escaneo")
    cfg.agente_tarea = "codex"
    assert loop._criterio_para_juez(cfg, "pasa el escaneo") == "pasa el escaneo"


@e2e
def test_bloqueo_por_permiso_pausa_sin_gastar_reintentos(tmp_path):
    proyecto = _escenario(tmp_path, "#!/usr/bin/env bash\nexit 0\n")
    bin_, cuenta = _agente_que_cuenta(tmp_path)
    bin_.write_text(bin_.read_text(encoding="utf-8").replace(
        "echo '{\"usage\"",
        "echo 'DEDALO_BLOQUEO_PERMISO: gitleaks detect'\necho '{\"usage\""), encoding="utf-8")
    rc, _ = _correr(proyecto, _entorno(bin_))
    log = (proyecto / "progreso.log").read_text(encoding="utf-8")
    assert rc == 11, log[-1500:]
    assert "- [ ] t1" in (proyecto / "plan.md").read_text(encoding="utf-8")
    assert cuenta.read_text().count("x") == 1
    assert "comando sin permiso: gitleaks detect" in log


# --- point 20: resume on its own after the quota ---------------------------------

def test_lee_la_hora_de_reseteo_del_mensaje():
    import datetime as dt
    ahora = dt.datetime(2026, 11, 8, 8, 0, tzinfo=dt.timezone.utc)  # 03:00 in Lima
    texto = "You've hit your 5-hour limit · resets 3:40am (America/Lima)"
    assert loop.segundos_hasta_reseteo(texto, ahora) == 40 * 60
    # Already past today: tomorrow.
    assert loop.segundos_hasta_reseteo("resets 2am (America/Lima)", ahora) == 23 * 3600
    assert loop.segundos_hasta_reseteo("resets 12pm (America/Lima)", ahora) == 9 * 3600
    for sin_hora in ("usage limit", "resets Nov 12", "resets 3 days from now", ""):
        assert loop.segundos_hasta_reseteo(sin_hora, ahora) is None


def _cfg_cuota(tmp_path, reanudar):
    from types import SimpleNamespace
    return SimpleNamespace(reanudar_tras_cuota=reanudar, hasta="", nombre="p",
                           proyecto=str(tmp_path), origen="cli",
                           log=str(tmp_path / "progreso.log"))


@pytest.mark.parametrize(("mensaje", "esperado"), [
    ("resets 1pm (America/Lima)", None), ("sin hora", 300)])
def test_con_la_opcion_duerme_y_relanza(tmp_path, monkeypatch, mensaje, esperado):
    from dedalo import loop_agentes
    resultados = [5, 0]

    def _run(_cfg):
        loop_agentes.ULTIMA_CUOTA["texto"] = mensaje
        return resultados.pop(0)

    esperas = []
    monkeypatch.setattr(loop, "run", _run)
    monkeypatch.setattr(loop, "_notificar", lambda *a, **k: None)
    monkeypatch.setattr(loop.time, "sleep", esperas.append)
    monkeypatch.setattr(loop, "segundos_hasta_reseteo",
                        lambda t: 1000 if "resets" in t else None)
    cfg = _cfg_cuota(tmp_path, True)
    assert loop._correr_reanudando(cfg, lambda: cfg) == 0
    assert esperas == [1000 + loop.MARGEN_CUOTA if esperado is None else esperado]
    assert "ESPERANDO CUOTA" in (tmp_path / "progreso.log").read_text(encoding="utf-8")


def test_sin_la_opcion_una_parada_por_cuota_termina(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "run", lambda _c: 5)
    monkeypatch.setattr(loop.time, "sleep", lambda _s: pytest.fail("no debe esperar"))
    assert loop._correr_reanudando(_cfg_cuota(tmp_path, False), lambda: None) == 5


# --- point 17: committed commands can really be reached --------------------------

def _check_alcanzable():
    import importlib.util
    ruta = os.path.join(os.path.dirname(gate.__file__), "plantillas_data", "plantillas",
                        "tauri", "gate_checks", "05_alcanzable.py")
    spec = importlib.util.spec_from_file_location("check_alcanzable", ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(modulo)
    return modulo


_RUST = """
#[tauri::command]
pub async fn crear_venta(state: State<'_, Db>, producto_id: i64, nota: Option<String>) -> R<()> {}
#[tauri::command]
fn huerfano(app: tauri::AppHandle) {}
#[tauri::command(rename_all = "snake_case")]
fn listar(total_filas: i64) {}
fn main() { tauri::Builder::default().invoke_handler(tauri::generate_handler![
    ventas::crear_venta, huerfano, listar,
]); }
"""


def test_alcanzable_detecta_comandos_sin_uso_y_argumentos():
    check = _check_alcanzable()
    front = ["""
      await invoke<Foo<Bar>>("crear_venta", { productoId: 1 });
      invoke('listar', { totalFilas: 2 });
      invoke("no_existe");
      // invoke("huerfano");
    """]
    encontrados = check.problemas([_RUST], [check._sin_comentarios(front[0])])
    assert encontrados == [
        "comando sin ninguna llamada desde src/: huerfano",
        "llamada a un comando no registrado: no_existe",
        "invoke('listar') sin el argumento 'total_filas'",
    ]


def test_alcanzable_acepta_excepciones_y_argumentos_opcionales():
    check = _check_alcanzable()
    front = ['invoke("crear_venta", { productoId: 1 }); invoke("listar", { total_filas: 1 });'
             'invoke("huerfano");']
    assert check.problemas([_RUST], front) == []
    assert check.problemas([_RUST], ['invoke("listar", args); invoke("crear_venta", {...x});'],
                           ignorar=["huerfano"]) == []


def test_alcanzable_en_un_proyecto(tmp_path):
    from types import SimpleNamespace
    check = _check_alcanzable()
    for sub in ("src-tauri/src", "src"):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / "src-tauri/src/main.rs").write_text(_RUST, encoding="utf-8")
    (tmp_path / "src/a.test.ts").write_text('invoke("huerfano")', encoding="utf-8")
    (tmp_path / "src/a.ts").write_text(
        'invoke("crear_venta", { productoId: 1 }); invoke("listar", { total_filas: 1 });',
        encoding="utf-8")
    fallos = []
    env = SimpleNamespace(proyecto=str(tmp_path), aviso=print, ok=print, fail=fallos.append)
    assert check.run(env) == 1, "a call only from a test file does not count"
    (tmp_path / ".dedalo").mkdir()
    (tmp_path / ".dedalo/alcanzable_ignorar.txt").write_text("huerfano\n", encoding="utf-8")
    assert check.run(env) == 0


def test_alcanzable_entiende_ayudantes_y_lifetimes():
    check = _check_alcanzable()
    rust = """
#[tauri::command]
fn abrir(estado: State<'_, EstadoApp>, monto_inicial: i64) {}
fn m() { generate_handler![abrir]; }
"""
    front = ["""export async function llamar<T>(comando: string, args?: X): Promise<T> {
        try { return await invoke<T>(comando, args); } catch (e) { throw e; }
      }""", 'llamar<Caja>("abrir", { montoInicial });']
    assert check.problemas([rust], front) == []
    assert check.problemas([rust], [front[0], 'llamar("abrir", {});']) == [
        "invoke('abrir') sin el argumento 'montoInicial'"]


def test_alcanzable_ve_los_nombres_en_un_ternario():
    check = _check_alcanzable()
    rust = "fn m() { generate_handler![a_pdf, a_csv]; }"
    assert check.problemas([rust], ["invoke<void>(f === 'PDF' ? 'a_pdf' : 'a_csv', { x });"]) == []


def test_el_plan_no_puede_dar_permisos_al_agente(tmp_path):
    from types import SimpleNamespace

    from dedalo.loop_agentes import _comandos_extra
    cfg = SimpleNamespace(comandos_extra=["gitleaks"])
    assert _comandos_extra(cfg) == ["gitleaks"]
    assert not hasattr(loop, "_clave_tarea")


def test_cola_de_avisos_sobrevive_al_proceso(plataforma_falsa, monkeypatch):
    from dedalo import notificaciones
    plataforma_falsa["fallos"] = 4
    notificaciones.enviar_texto({}, "cuota agotada")
    # A new process starts with no memory of the failure: only the disk remains.
    assert "falsa" in notificaciones._leer_cola()
    assert notificaciones.enviar_texto({}, "inicio") == [("falsa", "OK")]
    assert plataforma_falsa["llegados"] == ["inicio", "cuota agotada"]
    assert notificaciones._leer_cola() == {}


def test_con_reanudacion_solo_un_aviso_de_cuota(tmp_path, monkeypatch):
    from types import SimpleNamespace
    enviados = []
    monkeypatch.setattr(loop.notificaciones, "enviar",
                        lambda e, d, **k: enviados.append((e, d)) or [])
    cfg = SimpleNamespace(reanudar_tras_cuota=True, origen="cli", nombre="p",
                          proyecto=str(tmp_path), log=str(tmp_path / "l"))
    loop._notificar(cfg, "tokens")
    assert enviados == []
    loop._notificar(cfg, "tokens", reanuda="a las 3")
    assert len(enviados) == 1


def test_tareas_manuales_visibles_en_estado_y_kanban(tmp_path, app):
    from dedalo.paneles import PanelPlan
    plan = tmp_path / "plan.md"
    plan.write_text("- [ ] a\n- [M] llamar al proveedor\n", encoding="utf-8")
    panel = PanelPlan()
    p = Plan(str(plan))
    p.cargar()
    panel.kanban.cargar(p)
    textos = [panel.kanban.col_pend.lista.item(i).text()
              for i in range(panel.kanban.col_pend.lista.count())]
    assert any("llamar al proveedor" in x for x in textos)
    assert panel.kanban.col_pend.badge.text() == "1"
