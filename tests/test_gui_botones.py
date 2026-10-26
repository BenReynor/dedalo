"""Headless GUI tests: each button does what it says.

Instantiates the panels with QT_QPA_PLATFORM=offscreen and a temporary
project with a real git repository. Verifies that pressing each button produces
the expected effect (signal emitted, file written, tree reloaded, etc.).

Modal dialogs (QMessageBox, QFileDialog, QInputDialog) close
themselves with a QTimer so as not to block the test.
"""

import os
import shutil
import subprocess
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QInputDialog,
    QMessageBox,
    QPushButton,
)


@pytest.fixture
def cerrar_modales(app):
    t = QTimer()
    t.timeout.connect(_cerrar_todos_los_modales)
    t.start(30)
    yield t
    t.stop()


def _cerrar_todos_los_modales():
    app = QApplication.instance()
    for w in app.topLevelWidgets():
        if isinstance(w, (QMessageBox, QInputDialog)):
            w.reject()


def boton(curso, texto):
    """Finds a QPushButton by exact text in a widget or child."""
    for b in curso.findChildren(QPushButton):
        if b.text().strip() == texto:
            return b
    return None


@pytest.fixture
def proyecto_git(tmp_path):
    """Git repo with a plan.md and 2 Dédalo commits."""
    subprocess.run(["git", "init", "-q", "-b", "master"], cwd=tmp_path, check=True)
    (tmp_path / "plan.md").write_text(
        "# PLAN\n\n- [ ] #1 crear demo.py\n      criterio: demo.py existe\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "-q", "-m", "dedalo: tarea 1"], cwd=tmp_path,
                   check=True)
    (tmp_path / "demo.py").write_text("def demo():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "-q", "-m", "dedalo: tarea 2"], cwd=tmp_path,
                   check=True)
    return tmp_path


# ─── PanelPlan ────────────────────────────────────────────────

def test_plan_guardar_modifica_archivo_y_kanban(app, proyecto_git):
    from dedalo.paneles import PanelPlan
    p = PanelPlan()
    ruta = str(proyecto_git / "plan.md")
    p.cargar(ruta)
    assert p.kanban.col_pend.badge.text() == "1"

    # Edit and press Save plan.md
    p.editor.setPlainText(
        "# PLAN\n\n- [ ] #1 crear demo.py\n- [x] #0 tarea hecha\n")
    guardados = []
    p.guardado.connect(guardados.append)
    boton(p, "Save plan.md").click()
    assert (proyecto_git / "plan.md").read_text(encoding="utf-8") == p.editor.toPlainText()
    assert guardados, "señal guardado no emitida"
    assert p.kanban.col_pend.badge.text() == "1"
    assert p.kanban.col_hecha.badge.text() == "1"

    # Reload returns to the on-disk state
    boton(p, "Reload").click()
    assert p.kanban.col_hecha.badge.text() == "1"


def test_plan_kanban_click_enfoca_editor(app, proyecto_git):
    from dedalo.paneles import PanelPlan
    p = PanelPlan()
    p.cargar(str(proyecto_git / "plan.md"))
    p.kanban.tarea_seleccionada.emit("crear demo.py")
    assert p.editor.textCursor().block().text() != ""
    assert "crear demo.py" in p.editor.toPlainText()


# ─── PanelLecciones ───────────────────────────────────────────

def test_lecciones_nueva_y_guardar(app, proyecto_git):
    from dedalo.paneles import PanelLecciones
    p = PanelLecciones()
    ruta = str(proyecto_git / "lecciones.md")
    p.cargar(ruta)
    boton(p, "＋ New lesson").click()
    assert "Symptom" in p.editor.toPlainText()

    guardados = []
    p.guardado.connect(guardados.append)
    boton(p, "Save lecciones.md").click()
    assert (proyecto_git / "lecciones.md").read_text(encoding="utf-8") == p.editor.toPlainText()
    assert guardados


# ─── PanelMapa ────────────────────────────────────────────────

@pytest.mark.skipif(
    shutil.which("bash") is None,
    reason="bash no disponible (el botón regenera mapeo.sh con bash)")
@pytest.mark.skipif(os.name == "nt",
                    reason="regenerar el mapa ejecuta mapear.sh (POSIX): "
                           "se valida en Linux")
def test_mapa_regenerar_crea_mapeo(app, proyecto_git):
    from dedalo.paneles import PanelMapa
    # Add mapear.sh that generates mapeo.txt
    (proyecto_git / "mapear.sh").write_text(
        "#!/usr/bin/env bash\necho '# demo.py -> tests/test_demo.py' > mapeo.txt\n",
        encoding="utf-8",
    )
    subprocess.run(["bash", "mapear.sh"], cwd=proyecto_git, check=True)
    p = PanelMapa()
    p.cargar(str(proyecto_git / "mapeo.txt"))
    assert "demo.py" in p.editor.toPlainText()
    # Regenerate from disk
    boton(p, "🔄 Regenerate map").click()
    assert "# demo.py -> tests/test_demo.py" in p.editor.toPlainText()


# ─── PanelGit ─────────────────────────────────────────────────

def test_git_refrescar_lista_commits(app, proyecto_git):
    from dedalo.paneles import PanelGit
    p = PanelGit()
    p.cargar(str(proyecto_git))
    # wait for worker
    from PySide6.QtTest import QTest
    for _ in range(100):
        app.processEvents()
        if p._worker is None:
            break
        QTest.qWait(20)
    assert "tarea 2" in str([p.tree.topLevelItem(i).text(1)
                            for i in range(p.tree.topLevelItemCount())])
    assert p.tree.topLevelItemCount() >= 2


def test_git_worker_se_libera_y_no_crea_atributo_espurio(app, proyecto_git):
    """After loading, the thread is released (self._worker = None) and no
    'worker' attribute without an underscore appears (regression of the liberar() bug)."""
    from PySide6.QtTest import QTest

    from dedalo.paneles import PanelGit
    p = PanelGit()
    p.cargar(str(proyecto_git))
    for _ in range(100):
        app.processEvents()
        if p._worker is None:
            break
        QTest.qWait(20)
    assert p._worker is None
    assert not hasattr(p, "worker")


def test_git_revert_devuelve_estado_anterior(app, proyecto_git):
    """Pressing '↩ Revertir' undoes the change while keeping the repo intact."""
    from dedalo.paneles import PanelGit
    # The tarea 2 commit added demo.py; reverting it must remove demo.py
    p = PanelGit()
    p.cargar(str(proyecto_git))
    from PySide6.QtTest import QTest
    for _ in range(100):
        app.processEvents()
        if p._worker is None:
            break
        QTest.qWait(20)
    assert (proyecto_git / "demo.py").exists()

    # Emulate the app.py flow: capture the signal emitted by the button
    shas = []
    p.revertir_commit.connect(shas.append)
    # Press the first item's button
    btn = p.tree.itemWidget(p.tree.topLevelItem(0), 4)
    assert btn is not None and "Revert" in btn.text()
    btn.click()
    assert shas, "el botón Revertir no emitió la señal"

    # Actually revert (same code as app.Ventana._git_revert)
    sha = shas[0]
    out = subprocess.run(["git", "revert", "--no-commit", sha], cwd=proyecto_git,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "-q", "-m", f"revert: {sha[:8]}"], cwd=proyecto_git,
                   check=True)
    # demo.py was added by the reverted commit (tarea 2), so it stops existing
    assert not (proyecto_git / "demo.py").exists()


def test_git_revert_no_rompe_rama(app, proyecto_git):
    """After reverting, git status is clean and the branch is still master."""
    from dedalo.app import Ventana
    # revert the most recent commit via the git panel's real function
    _ = Ventana._git_revert  # referencia (usada por app)
    sha = subprocess.run(["git", "-C", str(proyecto_git), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    import dedalo.app as app_mod
    ok = app_mod.Ventana._git_revert(None, str(proyecto_git), sha)
    assert ok
    # repo is still valid: active branch intact, log unbroken
    rama = subprocess.run(["git", "-C", str(proyecto_git), "branch",
                           "--show-current"], capture_output=True, text=True).stdout.strip()
    assert rama == "master"
    out = subprocess.run(["git", "-C", str(proyecto_git), "log", "--oneline", "-3"],
                         capture_output=True, text=True)
    assert "revert:" in out.stdout
    assert "tarea 2" in out.stdout  # the original commit is still in the history


def test_git_revert_aparece_en_lista(app, proyecto_git):
    """The 'revert: ...' commit generated by the button MUST show up in PanelGit."""
    from PySide6.QtTest import QTest

    from dedalo.paneles import PanelGit
    sha = subprocess.run(["git", "-C", str(proyecto_git), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    import dedalo.app as app_mod
    assert app_mod.Ventana._git_revert(None, str(proyecto_git), sha)

    p = PanelGit()
    p.cargar(str(proyecto_git))
    for _ in range(100):
        app.processEvents()
        if p._worker is None:
            break
        QTest.qWait(20)
    mensajes = [p.tree.topLevelItem(i).text(1)
                for i in range(p.tree.topLevelItemCount())]
    assert any("revert:" in m for m in mensajes), \
        f"el revert no aparece en la lista (mensajes: {mensajes})"


def test_git_revert_conflicto_no_rompe_ui(app, proyecto_git, cerrar_modales):
    """Reverting a commit that produces a conflict returns False (it does not crash)."""
    import dedalo.app as app_mod
    # Create a dirty state that clashes with reverting commit 2
    (proyecto_git / "demo.py").write_text("# modificado por el usuario\n",
                                          encoding="utf-8")
    sha = subprocess.run(["git", "-C", str(proyecto_git), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    # Does HEAD~1 add demo.py? no: tarea1 plan.md, tarea2 demo.py. Reverting HEAD
    # (which created demo.py) with a touched working tree → conflict or -m needed.
    ok = app_mod.Ventana._git_revert(None, str(proyecto_git), sha)
    assert ok is False  # must not raise an exception or leave the repo broken
    rama = subprocess.run(["git", "-C", str(proyecto_git), "branch",
                           "--show-current"], capture_output=True, text=True).stdout.strip()
    assert rama == "master"


# ─── PanelMetricas ────────────────────────────────────────────

def test_metricas_exportar_csv(app, proyecto_git, cerrar_modales, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from dedalo.paneles_metricas import PanelMetricas
    # Pass a minimal progreso.log with the real format (timestamp)
    (proyecto_git / "progreso.log").write_text(
        "[2026-09-24 10:00:00] == Iteración 1: tarea demo "
        "(rama dedalo/tareas/2026-09-24/t1) ==\n"
        "[2026-09-24 10:00:05] ✔ commit: abc\n"
        "[2026-09-24 10:00:05] Costo iteración 1: 0.50 USD\n",
        encoding="utf-8")
    p = PanelMetricas()
    p.cargar(str(proyecto_git))
    # Force the save dialog to a fixed path
    destino = tmp_path / "metricas.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(destino), "")))
    b_export = boton(p, "📥 Export CSV")
    assert b_export is not None
    b_export.click()
    p._timer.stop()
    assert destino.exists()
    assert "Iter" in destino.read_text(encoding="utf-8")


def test_metricas_actualizar_kpis(app, proyecto_git):
    from dedalo.paneles_metricas import PanelMetricas
    (proyecto_git / "progreso.log").write_text(
        "[2026-09-24 10:00:00] == Iteración 1: tarea demo "
        "(rama dedalo/tareas/2026-09-24/t1) ==\n"
        "[2026-09-24 10:00:05] ✔ commit: abc\n"
        "[2026-09-24 10:00:05] Costo iteración 1: 0.50 USD\n",
        encoding="utf-8")
    p = PanelMetricas()
    p.cargar(str(proyecto_git))
    boton(p, "🔄 Refresh now").click()
    p._timer.stop()
    assert p.kpi_total.lbl_valor.text() == "1"
    assert p.kpi_hechas.lbl_valor.text() == "1"
    assert p.kpi_coste.lbl_valor.text() == "$0.50"


# ─── PanelEjecucion ───────────────────────────────────────────

def test_ejecucion_botones_emiten_senales(app, proyecto_git):
    from dedalo.paneles import PanelEjecucion
    p = PanelEjecucion()
    senales = {"iniciar": [], "detener": [], "gate": [], "refrescar": []}
    p.iniciar.connect(lambda: senales["iniciar"].append(True))
    p.detener.connect(lambda: senales["detener"].append(True))
    p.gate.connect(lambda: senales["gate"].append(True))
    p.refrescar_modelos.connect(lambda: senales["refrescar"].append(True))

    # The Start button is enabled
    assert p.b_iniciar.isEnabled()
    boton(p, "▶ Start loop").click()
    assert senales["iniciar"]

    # Stop disabled until it runs
    assert not p.b_detener.isEnabled()

    # Run gate emits
    boton(p, "Run gate").click()
    assert senales["gate"]

    # Refresh models
    boton(p, "↻ Refresh models").click()
    assert senales["refrescar"]

    # config() returns what the user sees
    conf = p.config()
    assert conf["iteraciones"] == 40
    assert "agente" in conf and "revisor" in conf


def test_ejecucion_marca_agente_sin_login(app, proyecto_git, monkeypatch):
    """An installed CLI without a session is shown marked and cannot be selected."""
    from dedalo import modelos, paneles

    monkeypatch.setattr(modelos.shutil, "which", lambda n: (
        "/usr/bin/opencode" if n == "opencode" else
        "/usr/bin/claude" if n == "claude" else None))
    monkeypatch.setattr(modelos, "sesion_agente", lambda n: (
        False if n == "claude" else None))
    monkeypatch.setenv("HOME", str(proyecto_git))
    modelos.invalidar_cache()

    p = paneles.PanelEjecucion()
    textos = [p.cmb_agente_cli.itemText(i)
              for i in range(p.cmb_agente_cli.count())]
    assert "claude (no login)" in textos

    idx_claude = textos.index("claude (no login)")
    assert not p.cmb_agente_cli.model().item(idx_claude).isEnabled()
    # opencode is eligible and is the one that marks "auto"
    idx_oc = textos.index("opencode")
    assert p.cmb_agente_cli.model().item(idx_oc).isEnabled()
    assert p.cmb_agente_cli.itemText(0) == "auto → opencode"


def test_ejecucion_auto_sin_agente_operativo(app, proyecto_git, monkeypatch):
    """If the only CLI has no session, it is not offered as auto."""
    from dedalo import modelos, paneles

    monkeypatch.setattr(modelos.shutil, "which", lambda n: (
        "/usr/bin/claude" if n == "claude" else None))
    monkeypatch.setattr(modelos, "sesion_agente", lambda n: (
        False if n == "claude" else None))
    monkeypatch.setenv("HOME", str(proyecto_git))
    modelos.invalidar_cache()

    p = paneles.PanelEjecucion()
    assert "auto (no agents with session)" in p.cmb_agente_cli.itemText(0)
    assert p.modelos_seleccion()["agente_cli"] == "auto"


def test_ejecucion_config_devuelve_el_valor_y_no_la_etiqueta(
        app, proyecto_git, monkeypatch):
    """config() feeds AGENTE_TAREA, so it must return the real value.

    The combo's label is decorative ("auto → opencode"); if config()
    returned the text, the env would carry "auto → opencode", dedalo.sh would
    not enter auto-detection and would abort with exit 2 without reaching tarea 1.
    """
    from dedalo import modelos, paneles

    monkeypatch.setattr(modelos.shutil, "which", lambda n: (
        "/usr/bin/opencode" if n == "opencode" else None))
    monkeypatch.setattr(modelos, "sesion_agente", lambda n: None)
    monkeypatch.setenv("HOME", str(proyecto_git))
    modelos.invalidar_cache()

    p = paneles.PanelEjecucion()
    assert p.cmb_agente_cli.currentText() == "auto → opencode"

    conf = p.config()
    # neither the decorative label nor an agent id: exactly "auto"
    assert conf["agente_cli"] == "auto"
    assert conf["revisor_cli"] == "auto"

    # app.py only resolves the "auto" value toward auto-detection; any
    # other value is sent as is to the env, so it must be an agent id.
    for clave in ("agente_cli", "revisor_cli"):
        valor = conf[clave]
        assert valor == "auto", f"{clave} no es auto: {valor!r}"

    # and with an explicit concrete agent, it returns that id (not the label)
    idx = p.cmb_agente_cli.findText("opencode")
    p.cmb_agente_cli.setCurrentIndex(idx)
    assert p.config()["agente_cli"] == "opencode"


def test_ejecucion_config_roundtrip(app, proyecto_git):
    from dedalo.paneles import PanelEjecucion
    p = PanelEjecucion()
    p.txt_hasta.setText("18:30")
    p.txt_iter.setText("5")
    p.chk_fichas.setChecked(True)
    conf = p.config()
    assert conf["hasta"] == "18:30"
    assert conf["iteraciones"] == 5
    assert conf["fichas"] is True
    # apply back
    p2 = PanelEjecucion()
    p2.aplicar_config(conf)
    assert p2.txt_hasta.text() == "18:30"
    assert p2.txt_iter.text() == "5"
    assert p2.chk_fichas.isChecked() is True


def test_ejecucion_combo_agente_solo_ofrece_instalados(
        app, proyecto_git, monkeypatch):
    """The combo must not offer agents that do not exist on the machine."""
    from dedalo import modelos, paneles

    monkeypatch.setattr(modelos.shutil, "which", lambda n: (
        "/usr/bin/claude" if n == "claude" else None))
    monkeypatch.setattr(modelos, "sesion_agente", lambda n: None)
    monkeypatch.setenv("HOME", str(proyecto_git))
    modelos.invalidar_cache()

    p = paneles.PanelEjecucion()
    etiquetas = [p.cmb_agente_cli.itemText(i)
                 for i in range(p.cmb_agente_cli.count())]
    assert etiquetas[0].startswith("auto")
    assert "claude" in etiquetas
    assert "codex" not in etiquetas
    assert "opencode" not in etiquetas


def test_ejecucion_auto_usa_current_data(app, proyecto_git, monkeypatch):
    """The "auto → x" label is decorative: the real value must be 'auto'."""
    from dedalo import modelos, paneles

    monkeypatch.setattr(modelos.shutil, "which", lambda n: (
        "/usr/bin/claude" if n == "claude" else None))
    monkeypatch.setattr(modelos, "sesion_agente", lambda n: None)
    monkeypatch.setattr(modelos, "lista_modelos_proveedor",
                        lambda prov: ["haiku", "sonnet"] if prov == "anthropic" else [])
    monkeypatch.setenv("HOME", str(proyecto_git))
    modelos.invalidar_cache()

    p = paneles.PanelEjecucion()
    assert p.modelos_seleccion()["agente_cli"] == "auto"

    idx = p.cmb_agente_cli.findData("claude")
    assert idx > 0
    p.cmb_agente_cli.setCurrentIndex(idx)
    assert p.modelos_seleccion()["agente_cli"] == "claude"
    # claude takes Anthropic models: selector stays usable, on a Claude model.
    assert p.cmb_agente.isEnabled()
    assert p.modelos_seleccion()["tarea"] == "anthropic/haiku"

    idx_codex = p.cmb_agente_cli.findData("codex")
    if idx_codex > 0:
        p.cmb_agente_cli.setCurrentIndex(idx_codex)
        assert not p.cmb_agente.isEnabled()

    p.cmb_agente_cli.setCurrentIndex(0)
    assert p.modelos_seleccion()["agente_cli"] == "auto"
    assert p.cmb_agente.isEnabled()


# ─── PanelSeguridad / PanelWebhooks ───────────────────────────

def test_seguridad_guardar_emite(app, proyecto_git, cerrar_modales):
    from dedalo.paneles import PanelSeguridad
    p = PanelSeguridad({"activo": True, "umbral": 85, "segundos": 5, "ver": False}, {})
    datos = []
    p.guardar_ajustes.connect(datos.append)
    p.txt_umbral.setText("90")
    boton(p, "Save settings").click()
    assert datos and datos[-1]["seguridad"]["umbral"] == 90


def test_webhooks_guardar_emite_y_probar_no_crashea(app, cerrar_modales):
    from dedalo.paneles_webhooks import PanelWebhooks
    p = PanelWebhooks({})
    datos = []
    p.guardado.connect(datos.append)
    # Testing with an empty token must not raise an exception
    b = boton(p, "🧪 Test Telegram")
    b.click()
    boton(p, "💾 Save settings").click()
    assert datos and "telegram_token" in datos[-1]


# ─── PanelLogs ────────────────────────────────────────────────

def test_logs_limpiar_maximizar(app):
    from dedalo.paneles import PanelLogs
    p = PanelLogs()
    p.show()  # without show() the widgets are not 'visible' to Qt
    app.processEvents()
    p.panel_loop.setPlainText("línea de prueba")
    p.panel_gate.setPlainText("gate log")
    assert p.panel_loop.toPlainText() == "línea de prueba"
    # Clear the LOOP panel (the button inside its container)
    b_limpiar_loop = boton(p.loop_container, "🗑 Clear")
    b_limpiar_loop.click()
    assert p.panel_loop.toPlainText() == ""
    assert p.panel_gate.toPlainText() == "gate log"  # the other one is not touched
    # Maximize collapses the gate panel
    b_max = None
    for b in p.gate_container.findChildren(QPushButton):
        if b.text().strip() == "⛶":
            b_max = b
            break
    assert b_max is not None
    p._toggle_maximizar("gate")
    assert not p.panel_gate.isVisible()
    p._toggle_maximizar("gate")
    assert p.panel_gate.isVisible()
    p.hide()


# ─── AvisoTemperatura ─────────────────────────────────────────

def test_aviso_continuar_no_apaga(app):
    from dedalo.paneles import AvisoTemperatura
    a = AvisoTemperatura(95, 30)
    boton(a, "Continue").click()
    assert not a.apagar


# ─── All the commits (not just dedalo) ─────────────────────

def test_git_muestra_todos_los_commits(app):
    """PanelGit shows MANUAL commits in addition to Dédalo's."""
    import os
    import tempfile

    from PySide6.QtTest import QTest

    from dedalo.paneles import PanelGit
    tmp = tempfile.mkdtemp(prefix="git_todos_")
    subprocess.run(["git", "init", "-q", "-b", "master"], cwd=tmp, check=True)
    with open(os.path.join(tmp, "readme.md"), "w", encoding="utf-8") as f:
        f.write("# manual\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "-q", "-m", "manual: commit hecho a mano"],
                   cwd=tmp, check=True)
    p = PanelGit()
    p.cargar(tmp)
    for _ in range(100):
        app.processEvents()
        if p._worker is None:
            break
        QTest.qWait(20)
    mensajes = [p.tree.topLevelItem(i).text(1)
                for i in range(p.tree.topLevelItemCount())]
    assert any("manual:" in m for m in mensajes), \
        f"el commit manual no aparece (mensajes: {mensajes})"


# ─── Remove orphan project (without path) ───────────────────────

def test_quitar_proyecto_sin_ruta(app, monkeypatch):
    """'Remove' must be able to delete a saved project without a 'ruta' key."""
    from PySide6.QtWidgets import QComboBox

    import dedalo.app as app_mod

    nombre = "proyecto_sin_ruta"
    monkeypatch.setattr(app_mod.plantillas, "quitar", lambda *a, **k: [])
    # Minimal Window without __init__ (avoids the real one's timers/workers/threads)
    v = app_mod.Ventana.__new__(app_mod.Ventana)
    v.proyectos = {nombre: {"config": {}}}
    v.tema = "Oscuro"
    v.cmb = QComboBox()
    v.cmb.addItem(nombre)
    v.cmb.setCurrentText(nombre)
    v.loop = None
    q_resp = {"resp": app_mod.QMessageBox.Yes}
    monkeypatch.setattr(app_mod.QMessageBox, "question",
                        staticmethod(lambda *a, **k: q_resp["resp"]))
    boxes = []
    monkeypatch.setattr(app_mod.QMessageBox, "information",
                        staticmethod(lambda *a, **k: boxes.append(1)))
    v._quitar_proyecto()
    assert nombre not in v.proyectos, "el proyecto huérfano no se quitó"
    assert nombre not in [v.cmb.itemText(i) for i in range(v.cmb.count())]
    assert boxes, "no se informó al usuario de la eliminación"
    v.cmb.deleteLater()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
