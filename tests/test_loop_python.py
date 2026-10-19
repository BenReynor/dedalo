#!/usr/bin/env python3
"""Tests for dedalo.loop: pure engine helpers (proxima_tarea,
criterio_tarea, rama_run_nombre, Config, backup/gate_intacto/restaurar_gate,
_run_gate and _esperar_revision_manual).

Without Qt: the python engine does not depend on PySide.
"""

import io
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dedalo.loop import (  # noqa: E402
    _RECHAZO_MOTIVO,
    Config,
    _esperar_revision_manual,
    _run_gate,
    backup_gate,
    criterio_tarea,
    gate_intacto,
    proxima_tarea,
    rama_run_nombre,
    restaurar_gate,
)
from dedalo.loop_args import parse_args  # noqa: E402


def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _cfg(proyecto, env_extra=None, plan="plan.md"):
    env = {"PATH": os.environ.get("PATH", "")}
    env.update(env_extra or {})
    return Config(parse_args([str(proyecto / plan)]), environ=env,
                  proyecto=str(proyecto))


# ------------------------------------------------------------------- plan


def test_proxima_tarea_primera_pendiente(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("# PLAN\n\n- [x] hecha\n\n- [ ] pendiente uno\n"
                    "- [ ] pendiente dos\n", encoding="utf-8")
    assert proxima_tarea(str(plan)) == "pendiente uno"


def test_proxima_tarea_none_sin_pendientes(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("- [x] a\n", encoding="utf-8")
    assert proxima_tarea(str(plan)) is None


def test_criterio_inline_en_misma_linea(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("- [ ] tarea. criterio: existe a.py\n", encoding="utf-8")
    assert criterio_tarea(str(plan)) == "existe a.py"


def test_criterio_indentado_bajo_la_tarea(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("- [ ] tarea\n    criterio: corre test_x\n",
                    encoding="utf-8")
    assert criterio_tarea(str(plan)) == "corre test_x"


def test_criterio_sin_el_prefijo_se_corta_en_otra_tarea(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("- [ ] t1\n- [x] t2\n", encoding="utf-8")
    assert criterio_tarea(str(plan)) is None


def test_criterio_se_corta_en_linea_sin_indentar(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("- [ ] t1\nparrafo suelto\n", encoding="utf-8")
    assert criterio_tarea(str(plan)) is None


def test_criterio_vacio_ignora_otras_tareas_previas(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("# a\n- [x] previa\n- [ ] t1\n  criterio: ok\n",
                    encoding="utf-8")
    assert criterio_tarea(str(plan)) == "ok"


# ------------------------------------------------------------------ branches


def test_rama_run_nombre_formato():
    nombre = rama_run_nombre()
    assert re.fullmatch(r"dedalo/\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}",
                        nombre)


# ------------------------------------------------------------------ Config


def test_config_defaults_y_plan_absoluto(tmp_path):
    cfg = _cfg(tmp_path)
    assert cfg.plan_md == str(tmp_path / "plan.md")
    assert cfg.max_iter == 40 and cfg.max_reintentos == 2
    assert cfg.rama_base == "master"
    assert cfg.timeout_por_tarea == 900
    assert cfg.navegador == "0"
    assert cfg.push is False


def test_config_respeta_entorno_y_args(tmp_path):
    from dedalo.loop_args import parse_args as pa
    env = {"MAX_ITER": "12", "REVISION_DUAL": "0", "TIMEOUT_POR_TAREA": "30",
           "AGENTE_TAREA": "codex", "RAMA_BASE": "dev"}
    cfg = Config(pa(["--hasta", "23:00", "--padre", "feat", "--push",
                     "--trabajo", "aux"]), environ=env, proyecto=str(tmp_path))
    assert cfg.max_iter == 12 and cfg.revision_dual == "0"
    assert cfg.timeout_por_tarea == 30
    assert cfg.agente_tarea == "codex"
    assert cfg.hasta == "23:00"
    assert cfg.rama_base == "feat"
    assert cfg.push is True
    assert cfg.rama_trabajo == "aux"


# ----------------------------------------------------------- gate (backup)


def test_backup_gate_intacto_y_restaurar(tmp_path):
    proyecto = tmp_path / "p"
    proyecto.mkdir()
    (proyecto / "gate.sh").write_text("#!/usr/bin/env bash\nexit 0\n",
                                      encoding="utf-8")
    checks = proyecto / "gate_checks"
    checks.mkdir()
    (checks / "01_x.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    cfg = _cfg(proyecto)
    dir_b = backup_gate(cfg)
    assert gate_intacto(dir_b, cfg)

    (proyecto / "gate.sh").write_text("#!/usr/bin/env bash\nextra\n",
                                      encoding="utf-8")
    assert not gate_intacto(dir_b, cfg)
    restaurar_gate(dir_b, cfg)
    assert gate_intacto(dir_b, cfg)

    os.unlink(proyecto / "gate.sh")
    assert not gate_intacto(dir_b, cfg)


def test_run_gate_pasa_env_y_devuelve_0(tmp_path):
    """_run_gate runs gate.py; the CRITERIO reaches the check through the environment."""
    proyecto = tmp_path / "p"
    checks = proyecto / "gate_checks"
    checks.mkdir(parents=True)
    (checks / "01_x.py").write_text(
        "import os\n"
        "def run(env):\n"
        "    with open('criterio_env.txt', 'w') as f:\n"
        "        f.write(os.environ['CRITERIO'])\n"
        "    return 0\n", encoding="utf-8")
    cfg = _cfg(proyecto, {"MODELO_JUEZ": "juez-x"})
    rc, ruta = _run_gate(cfg, "criterio de prueba")
    try:
        assert rc == 0
        assert _leer(proyecto / "criterio_env.txt").strip() == \
            "criterio de prueba"
    finally:
        os.unlink(ruta)


def test_run_gate_rc_distinto_de_cero(tmp_path):
    proyecto = tmp_path / "p"
    checks = proyecto / "gate_checks"
    checks.mkdir(parents=True)
    (checks / "01_x.py").write_text("def run(env):\n    return 1\n",
                                    encoding="utf-8")
    cfg = _cfg(proyecto)
    rc, ruta = _run_gate(cfg, "")
    try:
        assert rc == 1
    finally:
        os.unlink(ruta)


# ----------------------------------------------------- manual review


def _dir_rev(tmp_path):
    from dedalo import rutas

    return Path(rutas.dir_review(str(tmp_path)))


def test_manual_desactivada_devuelve_0(tmp_path):
    cfg = _cfg(tmp_path, {"REVISION_MANUAL": "0"})
    assert _esperar_revision_manual(cfg, "t1") == 0


def test_manual_aprobada(tmp_path):
    dir_rev = _dir_rev(tmp_path)
    dir_rev.mkdir(parents=True, exist_ok=True)
    (dir_rev / "decision").write_text("APPROVE\n", encoding="utf-8")
    cfg = _cfg(tmp_path, {"REVISION_MANUAL": "1"})

    rc = _esperar_revision_manual(cfg, "tarea x")

    assert rc == 0
    assert not (dir_rev / "decision").exists()
    assert not (dir_rev / "waiting").exists()
    assert (dir_rev / "diff.txt").exists()
    assert _leer(dir_rev / "tarea.txt") == "tarea x"
    assert "ESPERANDO REVISIÓN MANUAL: tarea x" in _leer(cfg.log)


def test_manual_rechazada_rellena_motivo(tmp_path):
    dir_rev = _dir_rev(tmp_path)
    dir_rev.mkdir(parents=True, exist_ok=True)
    (dir_rev / "decision").write_text("REJECT\nmalisimo\n", encoding="utf-8")
    cfg = _cfg(tmp_path, {"REVISION_MANUAL": "1"})
    _RECHAZO_MOTIVO["txt"] = ""

    rc = _esperar_revision_manual(cfg, "t1")

    assert rc == 1
    assert _RECHAZO_MOTIVO["txt"] == "malisimo"
    assert "REVISIÓN MANUAL: RECHAZADO - malisimo" in _leer(cfg.log)


def test_manual_aprobacion_de_agente_ignorada_por_defecto(tmp_path, monkeypatch):
    """An APPROVE with origen=mcp does not settle the review if there is no opt-in."""
    dir_rev = _dir_rev(tmp_path)
    dir_rev.mkdir(parents=True, exist_ok=True)
    (dir_rev / "decision").write_text("APPROVE\n# origen=mcp\n", encoding="utf-8")
    cfg = _cfg(tmp_path, {"REVISION_MANUAL": "1",
                          "TIMEOUT_REVISION_MANUAL": "2"})
    import dedalo.loop as loop_m
    monkeypatch.setattr(loop_m.time, "sleep", lambda s: None)

    rc = _esperar_revision_manual(cfg, "t1")

    assert rc == 2
    log = _leer(cfg.log)
    assert "APROBACIÓN POR AGENTE IGNORADA" in log
    assert "APROBADO" not in log


def test_manual_aprobacion_de_agente_permitida_con_opt_in(tmp_path, monkeypatch):
    """With REVISION_APRUEBA_AGENTE=1 the APPROVE from origen=mcp is accepted."""
    dir_rev = _dir_rev(tmp_path)
    dir_rev.mkdir(parents=True, exist_ok=True)
    (dir_rev / "decision").write_text("APPROVE\n# origen=mcp\n", encoding="utf-8")
    cfg = _cfg(tmp_path, {"REVISION_MANUAL": "1",
                          "REVISION_APRUEBA_AGENTE": "1"})

    rc = _esperar_revision_manual(cfg, "t1")

    assert rc == 0
    assert "APROBADO (origen=mcp)" in _leer(cfg.log)


def test_manual_aprobacion_gui_siempre_valida(tmp_path):
    """The GUI (origen=gui) approves like a person, without opt-in."""
    dir_rev = _dir_rev(tmp_path)
    dir_rev.mkdir(parents=True, exist_ok=True)
    (dir_rev / "decision").write_text("APPROVE\n# origen=gui\n", encoding="utf-8")
    cfg = _cfg(tmp_path, {"REVISION_MANUAL": "1"})

    rc = _esperar_revision_manual(cfg, "t1")

    assert rc == 0
    assert "APROBADO (origen=gui)" in _leer(cfg.log)


def test_manual_rechazo_de_agente_no_se_bloquea(tmp_path):
    """An agent REJECT is respected (it is not self-approval)."""
    dir_rev = _dir_rev(tmp_path)
    dir_rev.mkdir(parents=True, exist_ok=True)
    (dir_rev / "decision").write_text("REJECT\nmejora tests\n# origen=mcp\n",
                                      encoding="utf-8")
    cfg = _cfg(tmp_path, {"REVISION_MANUAL": "1"})
    _RECHAZO_MOTIVO["txt"] = ""

    rc = _esperar_revision_manual(cfg, "t1")

    assert rc == 1
    assert _RECHAZO_MOTIVO["txt"] == "mejora tests"
    assert "origen=mcp" in _leer(cfg.log)


def test_manual_timeout_marca_2(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, {"REVISION_MANUAL": "1",
                          "TIMEOUT_REVISION_MANUAL": "2"})
    import dedalo.loop as loop_m
    monkeypatch.setattr(loop_m.time, "sleep", lambda s: None)
    rc = _esperar_revision_manual(cfg, "t1")
    assert rc == 2
    assert "timeout sin respuesta" in _leer(cfg.log)


def test_manual_sin_internet_aborta_con_4(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, {"REVISION_MANUAL": "1",
                          "TIMEOUT_REVISION_MANUAL": "0"})
    import dedalo.loop as loop_m
    monkeypatch.setattr(loop_m.time, "sleep", lambda s: None)
    monkeypatch.setattr(loop_m.net, "hay_internet", lambda: False)
    rc = _esperar_revision_manual(cfg, "t1")
    assert rc == 4
    assert "ABORTADO: sin internet durante revisión manual" in _leer(cfg.log)


def test_proteger_salidas_reconfigura_consola_no_utf8(monkeypatch):
    """Windows with a legacy console: the encoding is cp1252 and the first ✗
    from the engine blew up with UnicodeEncodeError (regression seen in the
    Windows binary smoke test). It must set the stream to utf-8/replace."""
    import dedalo.loop as loop_m
    buf = io.BytesIO()
    flujo = io.TextIOWrapper(buf, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", flujo)
    loop_m._proteger_salidas()
    print("[dedalo] ✗✗ agente no disponible")  # must not blow up
    flujo.flush()
    assert "✗✗" in buf.getvalue().decode("utf-8")
    flujo.close()


def test_proteger_salidas_sustituye_stream_none_por_devnull(monkeypatch):
    """--windowed binary: stdout/stderr are None and the first print would blow up."""
    import dedalo.loop as loop_m
    monkeypatch.setattr(sys, "stdout", None)
    loop_m._proteger_salidas()
    print("ok")
    assert sys.stdout is not None
    sys.stdout.close()
