"""Tests for `dedalo.loop_launch`, focused on the environment allowlist.

The engine (and, through it, the gate and the agent CLIs) must only receive the
allowlisted variables, so an agent cannot read unrelated secrets the user has
exported in their shell.
"""

from dedalo import loop_launch as ll


def _conf(**extra):
    conf = {
        "iteraciones": 1, "agente_cli": "auto", "revisor_cli": "auto",
        "agente": "", "revisor": "", "dual": True, "voz": False,
        "costo_max": 0, "revision_manual": False,
    }
    conf.update(extra)
    return conf


def test_filtrar_entorno_deja_pasar_lo_permitido():
    env = {
        "PATH": "/usr/bin", "HOME": "/home/x", "LANG": "es_ES.UTF-8",
        "LC_ALL": "C", "TERM": "xterm-256color", "SSH_AUTH_SOCK": "/tmp/s",
        "GITHUB_TOKEN": "t", "DEDALO_IDIOMA": "es", "CLI_OPENCODE": "/bin/oc",
        "OPENCODE_AGENT_TAREA": "build", "CODEX_HOME": "/c", "CLAUDE_FLAGS": "-x",
        "MODELO_JUEZ": "opencode/x",
    }
    out = ll.filtrar_entorno(env)
    assert out == env


def test_filtrar_entorno_tira_secretos_ajenos():
    env = {
        "PATH": "/usr/bin",
        "AWS_SECRET_ACCESS_KEY": "s3cr3t",
        "DATABASE_URL": "postgres://u:p@h/db",
        "STRIPE_SECRET_KEY": "sk_live_xxx",
        "MY_RANDOM_TOKEN": "t",
    }
    assert ll.filtrar_entorno(env) == {"PATH": "/usr/bin"}


def test_entorno_extra_permite_ampliar():
    env = {"PATH": "/usr/bin", "DATABASE_URL": "postgres://x",
           "KUBECONFIG": "/k", "DEDALO_ENTORNO_EXTRA": "DATABASE_URL,KUBECONFIG"}
    out = ll.filtrar_entorno(env)
    assert out["DATABASE_URL"] == "postgres://x"
    assert out["KUBECONFIG"] == "/k"


def test_construir_entorno_filtra_y_conserva_el_contrato(monkeypatch):
    monkeypatch.setattr(ll.modelos, "ruta_binario", lambda clave: "")
    base = {"PATH": "/usr/bin", "SECRET_XYZ": "leak", "DEDALO_X": "1"}
    env = ll.construir_entorno(_conf(iteraciones=3), {}, [], base)
    assert env["MAX_ITER"] == "3"
    assert env["AGENTES_PREFERIDOS"] == ""
    assert env["NAVEGADOR"] == "0"
    assert env["DEDALO_X"] == "1"
    assert env["PATH"] == "/usr/bin"
    assert "SECRET_XYZ" not in env


def test_preparar_exporta_identidad_y_filtra(monkeypatch):
    monkeypatch.setattr(ll.modelos, "agentes_operativos", lambda: [])
    monkeypatch.setattr(ll.modelos, "ruta_binario", lambda clave: "")
    plan = ll.preparar(_conf(), {}, {"PATH": "/usr/bin", "SECRET": "x"},
                       frozen=True, nombre="p1", origen="mcp")
    assert plan["env"]["DEDALO_PROYECTO_NOMBRE"] == "p1"
    assert plan["env"]["DEDALO_ORIGEN"] == "mcp"
    assert "SECRET" not in plan["env"]
    # Frozen (packaged) → no PYTHONPATH injected; argv uses the exe entrypoint.
    assert "PYTHONPATH" not in plan["env"]
    assert plan["argv"][0] == "--dedalo-loop"


def test_preparar_reemplaza_un_pythonpath_viejo(monkeypatch):
    """A stale checkout exported by the parent must not shadow this one.

    Without this, the engine started with cwd=<project> imports whatever
    `dedalo` the inherited PYTHONPATH exposes: an old copy runs the loop.
    """
    monkeypatch.setattr(ll.modelos, "agentes_operativos", lambda: [])
    monkeypatch.setattr(ll.modelos, "ruta_binario", lambda clave: "")
    plan = ll.preparar(_conf(), {},
                       {"PATH": "/usr/bin",
                        "PYTHONPATH": "/otro/checkout/viejo"},
                       frozen=False)
    assert plan["env"]["PYTHONPATH"] == ll.raiz_codigo()


def test_entorno_python_quita_la_variable_si_es_frozen():
    env = {"PYTHONPATH": "/viejo"}
    ll.entorno_python(env, frozen=True)
    assert "PYTHONPATH" not in env


def test_el_directorio_de_configuracion_llega_a_los_hijos():
    """Child processes (gate, engine) must see the isolated config dir too."""
    out = ll.filtrar_entorno({"PATH": "/usr/bin", "DEDALO_CONFIG_DIR": "/tmp/cfg"})
    assert out["DEDALO_CONFIG_DIR"] == "/tmp/cfg"
