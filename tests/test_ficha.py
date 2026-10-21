#!/usr/bin/env python3
"""Tests for the opt-in JSON fichas of accepted tasks."""

import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dedalo import ficha  # noqa: E402


def _cfg(tmp_path, activa="1"):
    proyecto = tmp_path / "proyecto"
    proyecto.mkdir()
    log = proyecto / "progreso.log"
    log.write_text("[2026-01-01 10:00:00] tarea aceptada\n", encoding="utf-8")
    metrics = proyecto / "metrics.jsonl"
    metrics.write_text("", encoding="utf-8")
    fichas_dir = proyecto / ".dedalo" / "fichas"
    return SimpleNamespace(
        proyecto=str(proyecto),
        nombre="demo",
        log=str(log),
        metrics=str(metrics),
        incidencias=str(proyecto / "incidencias.jsonl"),
        fichas_dir=str(fichas_dir),
        fichas_index=str(fichas_dir / "index.jsonl"),
        ficha_activa=activa,
        agente_ficha="auto",
        agente_tarea="opencode",
        modelo_ficha="",
        modelo_tarea="opencode/x",
        timeout_ficha=10,
        ficha_max_diff=12000,
        ficha_max_salida=20000,
        ficha_diff_completo=False,
    )


def _generar(cfg, **extra):
    datos = {
        "tarea": "Añadir fichas",
        "criterio": "pytest -q",
        "iteracion": 3,
        "rama": "master",
        "commit": "",
        "commit_msg": "dedalo: fichas",
        "gate_rc": 0,
        "gate_salida": "pytest: 4 passed",
        "salida_agente": "implementado",
        "resultado_revision": "pass",
        "feedback_revision": "",
        "merge_ok": True,
        "revisor_modo": "dual",
    }
    datos.update(extra)
    return ficha.generar(cfg, **datos)


def test_desactivada_no_escribe_ni_llama_al_observador(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, activa="0")

    def _no_llamar(*args, **kwargs):
        raise AssertionError("el observador no debe ejecutarse")

    monkeypatch.setattr(ficha, "run_agente", _no_llamar)
    assert _generar(cfg) is None
    assert not os.path.exists(cfg.fichas_dir)


def test_sin_agente_guarda_ficha_base_incompleta(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(ficha, "_resolver_agente", lambda _cfg: ("", ""))

    def _no_llamar(*args, **kwargs):
        raise AssertionError("sin agente no hay observador")

    monkeypatch.setattr(ficha, "run_agente", _no_llamar)
    resultado = _generar(cfg)

    assert resultado["incompleta"] is True
    with open(resultado["ruta"], encoding="utf-8") as f:
        datos = json.load(f)
    assert datos["incompleta"] is True
    assert datos["motivo_incompleta"] == "sin_agente"
    assert datos["verificacion"]["gate"]["rc"] == 0
    assert datos["verificacion"]["revisor"]["resultado"] == "pass"
    assert datos["tarea"] == "Añadir fichas"
    assert datos["merge"]["mensaje"] == "dedalo: fichas"

    with open(cfg.fichas_index, encoding="utf-8") as f:
        indice = [json.loads(linea) for linea in f if linea.strip()]
    assert indice[-1]["id"] == datos["id"]
    assert indice[-1]["incompleta"] is True


def test_observador_completa_solo_la_narrativa(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(ficha, "_resolver_agente",
                        lambda _cfg: ("opencode", "opencode/x"))
    capturado = {}

    def _run(cfg_, agente, salida, modelo, prompt, tarea, iteracion, **kw):
        capturado.update({
            "agente": agente, "modelo": modelo, "tarea": tarea,
            "iteracion": iteracion, "prompt": prompt, **kw,
        })
        with open(salida, "w", encoding="utf-8") as f:
            f.write("```json\n")
            json.dump({
                "resumen": "Se añadieron fichas.",
                "decisiones": [{"decision": "opt-in", "motivo": "coste"}],
                "progreso": [{"paso": "implementar", "resultado": "ok",
                              "evidencia": "ficha.py"}],
                "riesgos": [{"riesgo": "tokens", "impacto": "bajo",
                             "mitigacion": "desactivado por defecto"}],
                "pendientes": ["HTML"],
                "lecciones": ["no bloquear el loop"],
                "confianza": "alta",
            }, f)
            f.write("\n```\n")
        return 0, None

    monkeypatch.setattr(ficha, "run_agente", _run)
    resultado = _generar(cfg)

    assert resultado["incompleta"] is False
    with open(resultado["ruta"], encoding="utf-8") as f:
        datos = json.load(f)

    assert datos["resumen"] == "Se añadieron fichas."
    assert datos["decisiones"][0]["decision"] == "opt-in"
    assert datos["confianza"] == "alta"
    # Facts are kept even if the model returns other values.
    assert datos["verificacion"]["gate"]["rc"] == 0
    assert datos["merge"]["ok"] is True
    assert datos["generado_por"]["agente"] == "opencode"
    assert datos["metricas"]["observador"] is None
    assert capturado["fase"] == "ficha"
    assert capturado["cwd"] == capturado["dir_trabajo"]
    assert capturado["cwd"] != cfg.proyecto
    assert "<SKILL>" in capturado["prompt"]
    assert "ficha base" in capturado["prompt"].lower()


def test_json_invalido_deja_ficha_incompleta(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(ficha, "_resolver_agente",
                        lambda _cfg: ("opencode", ""))

    def _run(cfg_, agente, salida, modelo, prompt, tarea, iteracion, **kw):
        with open(salida, "w", encoding="utf-8") as f:
            f.write("no es json")
        return 0, None

    monkeypatch.setattr(ficha, "run_agente", _run)
    resultado = _generar(cfg)
    with open(resultado["ruta"], encoding="utf-8") as f:
        datos = json.load(f)
    assert datos["incompleta"] is True
    assert datos["motivo_incompleta"] == "json_invalido"
    assert datos["confianza"] == "baja"


def test_redacta_secretos_y_trunca():
    texto = "token=abc123456789\nBearer abcdefghijklmnop\nfin"
    limpio = ficha.redactar(texto)
    assert "abc123456789" not in limpio
    assert "abcdefghijklmnop" not in limpio
    assert "***" in limpio
    assert ficha._truncar("x" * 20, 10).endswith("(truncado)")
