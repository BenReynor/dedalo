"""Shared fixtures for the headless suite.

Defines a session QApplication (offscreen) for tests that instantiate
widgets/QThread. Modules that need the app simply request it as the
`app` fixture; shutdown (breaking signal cycles and draining deferred
deletions) is centralized here.
"""

import gc
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dedalo import configuracion as cfg  # noqa: E402
from dedalo import consentimiento, loops_estado  # noqa: E402


@pytest.fixture(autouse=True)
def config_aislada(tmp_path, monkeypatch):
    """Never let the suite touch the user's real `~/.config/dedalo`.

    A GUI test (`test_quitar_proyecto_sin_ruta`) drives the real
    `_quitar_proyecto()`, which saves the project list through
    `proyectos.guardar()`. Without this redirection, running the suite deleted
    the developer's `proyectos.json` (projects, models and webhook settings
    included) — and the same for `loops.json` and `confianza.json`, which are
    written just as silently.

    Each test gets its own directory; the model catalog is symlinked so that
    listing models keeps working offline.
    """
    real = cfg.CONFIG_DIR
    aislado = str(tmp_path)
    # Child processes (the gate, `main` re-execs) do not see the module globals
    # patched below; the env var carries the isolation across `subprocess`.
    monkeypatch.setenv("DEDALO_CONFIG_DIR", aislado)
    catalogo = os.path.join(real, "models_dev.json")
    if os.path.exists(catalogo):
        try:
            os.symlink(catalogo, os.path.join(aislado, "models_dev.json"))
        except OSError:
            pass
    cfg.CONFIG_DIR = aislado
    cfg.REGISTRO = os.path.join(aislado, "proyectos.json")
    cfg.CATALOGO_MODELOS = os.path.join(aislado, "models_dev.json")
    consentimiento.CONFIG_DIR = aislado
    loops_estado.RUTA = os.path.join(aislado, "loops.json")
    loops_estado._RUTA_LEGACY = os.path.join(aislado, "mcp_loops.json")
    yield
    cfg.CONFIG_DIR = real
    cfg.REGISTRO = os.path.join(real, "proyectos.json")
    cfg.CATALOGO_MODELOS = os.path.join(real, "models_dev.json")
    consentimiento.CONFIG_DIR = real
    loops_estado.RUTA = os.path.join(real, "loops.json")
    loops_estado._RUTA_LEGACY = os.path.join(real, "mcp_loops.json")


def _drenar(app):
    """Collects cycles and drains Qt's deferred-delete queue."""
    for _ in range(3):
        gc.collect()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _apagar_qt(app):
    """Shuts down the suite without Qt's teardown SIGSEGV.

    The panels connect signals to their own slots and QTimer(self)/parents, so
    reference CYCLES form (widget -> signal -> bound method -> widget). The
    cycle collector frees them late: sometimes AFTER PySide destroys the
    QApplication in Py_FinalizeEx. Then Shiboken walks a QObject whose C++ side
    no longer exists and crashes inside ~QObject (SIGSEGV, exit 139; sometimes
    SIGABRT 134 "shared QObject was deleted directly"). Solution: break those
    cycles and drain the deferred deletions NOW, while the QApplication is
    still alive, so that no widget remains alive when the interpreter exits.
    """
    # Close first: closeAllWindows() leaves the widgets marked and lets
    # deleteLater() destroy them on the next drain.
    app.closeAllWindows()
    _drenar(app)
    for widget in list(app.topLevelWidgets()):
        widget.deleteLater()
    _drenar(app)
    app.quit()
    _drenar(app)


@pytest.fixture(scope="session")
def app():
    a = QApplication.instance() or QApplication(sys.argv)
    yield a
    _apagar_qt(a)
