"""Tests for the MCP server (headless tools and resources).

They call the functions directly (MCPServer decorators return the
unwrapped function) with the project registry and the pidfile isolated in
a tmp_path, without starting the stdio transport.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from dedalo import mcp_server as m
from dedalo import rutas  # noqa: E402


@pytest.fixture
def proyecto(tmp_path, monkeypatch):
    """Test project with plan/lessons/context and an isolated registry."""
    (tmp_path / "plan.md").write_text(
        "# Plan\n\n- [x] hecha\n- [ ] pendiente\n- [B] bloqueada\n",
        encoding="utf-8")
    (tmp_path / "lecciones.md").write_text("# Lecciones\n\n- ojo\n", encoding="utf-8")
    (tmp_path / "CONTEXTO.md").write_text("# CONTEXTO\n\nun juego\n", encoding="utf-8")
    (tmp_path / "incidencias.jsonl").write_text(
        '{"tipo": "gate", "motivo": "falla", "tarea": "t1"}\n'
        'no-es-json\n'
        '{"tipo": "revisor", "motivo": "no", "tarea": "t2"}\n',
        encoding="utf-8")
    (tmp_path / "progreso.log").write_text(
        "\n".join(f"linea {i}" for i in range(100)), encoding="utf-8")
    monkeypatch.setattr(m.proyectos, "cargar",
                        lambda: {"p1": {"ruta": str(tmp_path)}})
    # Isolate the shared loop registry (read by the MCP and the GUI).
    monkeypatch.setattr(m.loops_estado, "RUTA", str(tmp_path / "loops.json"))
    monkeypatch.setattr(m.loops_estado, "_RUTA_LEGACY",
                        str(tmp_path / "loops_legacy.json"))
    return tmp_path


def test_listar_proyectos(proyecto):
    datos = json.loads(m.listar_proyectos())
    assert datos == [{"nombre": "p1", "ruta": str(proyecto), "existe": True}]


def test_estado_proyecto_cuenta_plan(proyecto):
    datos = json.loads(m.estado_proyecto("p1"))
    assert datos["plan"] == {"pendientes": 1, "hechas": 1, "bloqueadas": 1}
    assert datos["lecciones"]["existe"] is True
    assert datos["contexto"]["existe"] is True
    assert datos["loop"]["corriendo"] is False


def test_leer_fichero_permitido_y_bloqueado(proyecto):
    assert "un juego" in m.leer_fichero("p1", "CONTEXTO.md")
    assert m.leer_fichero("p1", "plan.md").startswith("# Plan")
    with pytest.raises(ValueError):
        m.leer_fichero("p1", "../../etc/passwd")


def test_leer_incidencias_salta_lineas_rotas(proyecto):
    datos = json.loads(m.leer_incidencias("p1"))
    assert [d["tipo"] for d in datos] == ["gate", "revisor"]
    assert all("_crudo" not in d for d in datos)


def test_cola_log_devuelve_ultimas(proyecto):
    assert m.cola_log("p1", 3) == "linea 97\nlinea 98\nlinea 99"


def test_resolver_revision_escribe_decision(proyecto):
    m.resolver_revision("p1", "approve")
    decision = (Path(rutas.dir_review(str(proyecto))) / "decision").read_text(encoding="utf-8")
    assert decision == "APPROVE\n# origen=mcp\n"
    m.resolver_revision("p1", "REJECT", "no me convence")
    decision = (Path(rutas.dir_review(str(proyecto))) / "decision").read_text(encoding="utf-8")
    assert decision == "REJECT no me convence\n# origen=mcp\n"
    with pytest.raises(ValueError):
        m.resolver_revision("p1", "quizas")


def test_estado_loop_detecta_revision_pendiente(proyecto):
    fondo = Path(rutas.dir_review(str(proyecto)))
    fondo.mkdir(parents=True)
    (fondo / "waiting").write_text("", encoding="utf-8")
    (fondo / "tarea.txt").write_text("Tarea 3\n", encoding="utf-8")
    datos = json.loads(m.estado_loop("p1"))
    assert datos["revision_pendiente"] is True
    assert datos["tarea_en_revision"] == "Tarea 3"
    assert datos["corriendo"] is False


def test_proyecto_desconocido_falla(proyecto):
    with pytest.raises(ValueError):
        m.estado_proyecto("no-existe")


def test_detener_loop_si_no_corre(proyecto):
    datos = json.loads(m.detener_loop("p1"))
    assert datos["detenido"] is False
    assert "motivo" in datos


def test_registro_tools_y_recurso():
    async def _listar(server):
        tools = [t.name for t in await server.list_tools()]
        plantillas = [x.uri_template for x in await server.list_resource_templates()]
        return tools, plantillas

    tools, plantillas = asyncio.run(_listar(m.servidor()))
    for esperada in ("listar_proyectos", "iniciar_loop", "detener_loop",
                     "resolver_revision", "estado_loop", "correr_gate",
                     "instalar_proyecto", "leer_fichero", "leer_contexto",
                     "leer_plan", "leer_lecciones"):
        assert esperada in tools
    assert "dedalo://{nombre}/{fichero}" in plantillas


def test_recurso_manual_y_instructions():
    async def _leer(server):
        recursos = [str(r.uri) for r in await server.list_resources()]
        contenido = await server.read_resource("dedalo://manual")
        return recursos, contenido

    recursos, contenido = asyncio.run(_leer(m.servidor()))
    assert "dedalo://manual" in recursos
    assert contenido[0].content == m.MANUAL
    assert m.servidor().instructions == m.MANUAL


def test_iniciar_loop_sin_agentes(proyecto, monkeypatch):
    monkeypatch.setattr(m.modelos, "agentes_operativos",
                        lambda preferidos=None: [])
    monkeypatch.setattr(m.net, "hay_internet", lambda: True)
    monkeypatch.setattr(m.proyectos, "leer_config_proyecto", lambda n: {})
    datos = json.loads(m.iniciar_loop("p1"))
    assert datos["iniciado"] is False
    assert "agente" in datos["motivo"]


def test_iniciar_loop_sin_internet(proyecto, monkeypatch):
    monkeypatch.setattr(m.net, "hay_internet", lambda: False)
    datos = json.loads(m.iniciar_loop("p1"))
    assert datos["iniciado"] is False
    assert "internet" in datos["motivo"]


def test_estado_loop_ve_bucle_externo(proyecto):
    """A loop started elsewhere (GUI/CLI) is visible via the shared registry."""
    m.loops_estado.registrar("p1", os.getpid(), origen="gui")
    datos = json.loads(m.estado_loop("p1"))
    assert datos["corriendo"] is True
    assert datos["pid"] == os.getpid()
    assert datos["origen"] == "gui"


def test_iniciar_loop_no_duplica_si_ya_corre(proyecto, monkeypatch):
    monkeypatch.setattr(m.net, "hay_internet", lambda: True)
    m.loops_estado.registrar("p1", os.getpid(), origen="mcp")
    datos = json.loads(m.iniciar_loop("p1"))
    assert datos["iniciado"] is False
    assert "corriendo" in datos["motivo"]


def test_correr_gate_pasa_el_argv_completo(monkeypatch, tmp_path):
    """argv_gate returns a list; correr_gate must not try to unpack 2 values."""
    monkeypatch.setattr(m, "_ruta_de", lambda nombre: str(tmp_path))
    vistos = {}

    class Resultado:
        returncode = 0
        stdout = "TODO OK"
        stderr = ""

    def run_falso(cmd, **kwargs):
        vistos["cmd"] = cmd
        vistos["kwargs"] = kwargs
        return Resultado()

    monkeypatch.setattr(m.subprocess, "run", run_falso)
    datos = json.loads(m.correr_gate("p1", timeout_s=5))
    assert datos["rc"] == 0
    assert vistos["cmd"] == m.argv_gate(False)
    assert vistos["kwargs"]["cwd"] == str(tmp_path)


def test_confiar_gate_habilita_el_gate(monkeypatch, tmp_path):
    from dedalo import consentimiento

    checks = tmp_path / ".dedalo" / "scripts" / "gate_checks"
    checks.mkdir(parents=True)
    (checks / "01_x.sh").write_text("exit 0\n", encoding="utf-8")
    monkeypatch.setattr(consentimiento, "CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(m, "_ruta_de", lambda nombre: str(tmp_path))
    assert consentimiento.concedido(str(tmp_path), {}) is False
    datos = json.loads(m.confiar_gate("p1"))
    assert datos["gate_confiado"] is True
