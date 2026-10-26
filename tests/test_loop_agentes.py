#!/usr/bin/env python3
"""Tests for dedalo.loop_agentes (port of the loop's agent layer).

They are taken from the sections of dedalo.sh (cli_agente, agente_ok,
detectar_agente, elegir_revisor, sin_autenticacion, tokens_agotados,
_registrar_metrica, revisar_diff) keeping the SAME semantics, including the
auth corroboration (it only aborts if there was also no work).
"""

import json
import os
import sys

import pytest  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="motores de agente falsos en bash (POSIX): se valida en Linux")

from dedalo import loop_agentes as la  # noqa: E402
from dedalo.loop_agentes import (  # noqa: E402
    agente_ok,
    costo_por_modelo,
    detectar_agente,
    elegir_revisor,
    extraer_tokens,
    registrar_metrica,
    revisar_diff,
    run_agente,
    sin_autenticacion,
    soporta_dir,
    tokens_agotados,
)
from dedalo.loop_args import parse_args  # noqa: E402


def _config(tmp_path, env_extra=None):
    from dedalo.loop import Config
    env = {
        "PATH": os.environ.get("PATH", ""),
        "AGENTE_TAREA": "opencode",
        "VOZ": "0",
        "MAX_ITER": "1",
        "TIMEOUT_POR_TAREA": "60",
        "TIMEOUT_NAVEGADOR": "60",
        "TIMEOUT_REVISION_MANUAL": "0",
    }
    env.update(env_extra or {})
    return Config(parse_args(["plan.md"]), environ=env, proyecto=str(tmp_path))


def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _binario_falso(tmp_path, nombre="opencode", cuerpo="true\n"):
    bin_ = tmp_path / "bin" / nombre
    bin_.parent.mkdir(parents=True, exist_ok=True)
    bin_.write_text("#!/usr/bin/env bash\n" + cuerpo, encoding="utf-8")
    bin_.chmod(0o755)
    return bin_


# ---------------------------------------------------------------- cli/agente_ok


def test_cli_agente_lee_cli_sobrescrito(tmp_path):
    bin_ = _binario_falso(tmp_path, "opencode")
    cfg = _config(tmp_path, {"CLI_OPENCODE": str(bin_)})
    assert agente_ok("opencode", cfg)


def test_agente_ok_falso_si_no_existe(tmp_path):
    cfg = _config(tmp_path, {"CLI_OPENCODE": "/no/existe/opencode"})
    assert not agente_ok("opencode", cfg)


# Non-existent binaries in CLI_*: they block the system's `which <global>`.
_INE = "/no/existe/"

def test_detectar_agente_usa_primer_disponible(tmp_path):
    _binario_falso(tmp_path, "codex")
    cfg = _config(tmp_path, {"CLI_OPENCODE": _INE + "opencode",
                             "CLI_CODEX": str(tmp_path / "bin" / "codex")})
    cfg.agentes_preferidos = "opencode codex claude"
    assert detectar_agente(cfg) == "codex"


def test_detectar_agente_vacio_sin_ninguno(tmp_path):
    cfg = _config(tmp_path, {"CLI_OPENCODE": _INE + "opencode",
                             "CLI_CODEX": _INE + "codex",
                             "CLI_CLAUDE": _INE + "claude"})
    cfg.agentes_preferidos = "opencode codex claude"
    assert detectar_agente(cfg) == ""


def test_elegir_revisor_preferido_concreto(tmp_path):
    _binario_falso(tmp_path, "claude")
    cfg = _config(tmp_path, {
        "CLI_OPENCODE": _INE + "opencode",
        "CLI_CLAUDE": str(tmp_path / "bin" / "claude"),
        "AGENTE_REVISOR": "claude",
    })
    cfg.agente_tarea = "opencode"
    assert elegir_revisor(cfg) == "claude"


def test_elegir_revisor_otro_distinto_de_tarea(tmp_path):
    _binario_falso(tmp_path, "codex")
    _binario_falso(tmp_path, "claude")
    env = {
        "CLI_OPENCODE": _INE + "opencode",
        "CLI_CODEX": str(tmp_path / "bin" / "codex"),
        "CLI_CLAUDE": str(tmp_path / "bin" / "claude"),
    }
    cfg = _config(tmp_path, env)
    cfg.agentes_preferidos = "opencode codex claude"
    cfg.agente_tarea = "codex"
    # codex is the task agent; the reviewer prefers another agent.
    assert elegir_revisor(cfg) == "claude"


# --------------------------------------------------------------- auth / tokens


def test_sin_autenticacion_detecta_401_en_stderr(tmp_path):
    err = tmp_path / "out.err"
    out = tmp_path / "out"
    err.write_text("Authentication Error: HTTP 401 Unauthorized\n",
                   encoding="utf-8")
    out.write_text("intentando...", encoding="utf-8")
    assert sin_autenticacion(str(err), str(out), 1)
    assert not sin_autenticacion(str(err), str(out), 0)


def test_sin_autenticacion_falso_positivo_por_narrativa(tmp_path):
    """A mention of *auth* in stdout is not enough if the iteration produced
    work (corroborar=0): the loop must not abort."""
    err = tmp_path / "out.err"
    err.write_text("", encoding="utf-8")
    out = tmp_path / "out"
    # A stray '401' in narrative is NOT a high-confidence pattern.
    out.write_text("el cliente dice '401' en narrativa\n" * 5, encoding="utf-8")
    assert not sin_autenticacion(str(err), str(out), 0)
    assert not sin_autenticacion(str(err), str(out), 1)
    # REAL pattern (HTTP 401) in stdout: with work it does NOT abort, without work it DOES.
    out2 = tmp_path / "out2"
    out2.write_text("trabajo real\n" * 40 + "HTTP 401 Unauthorized\n",
                    encoding="utf-8")
    assert not sin_autenticacion(str(err), str(out2), 0)
    assert sin_autenticacion(str(err), str(out2), 1)
    # stderr with a clear pattern aborts whenever it corroborates.
    err2 = tmp_path / "out2.err"
    err2.write_text("Please run opencode auth login\n", encoding="utf-8")
    assert sin_autenticacion(str(err2), str(out2), 1)


def test_tokens_agotados_detecta_cuota(tmp_path):
    out = tmp_path / "out"
    out.write_text("Error: insufficient_quota for the request",
                   encoding="utf-8")
    assert tokens_agotados(str(out))
    out.write_text("todo ok", encoding="utf-8")
    assert not tokens_agotados(str(out))


# ------------------------------------------------------------------- costs


def test_costo_por_modelo_distingue_tarifas():
    assert costo_por_modelo("anthropic/claude-3.5-sonnet", 1_000_000, 0) == 15
    assert costo_por_modelo("gpt-4o", 1_000_000, 0) == 30
    assert costo_por_modelo("gpt-3.5-turbo", 1_000_000, 0) == 0.5
    assert costo_por_modelo("opencode/big-pickle", 1_000_000, 1_000_000) == 4


def test_extraer_tokens_ultimo_usage():
    texto = ('{"usage":{"input_tokens":1,"output_tokens":2}}\n'
             '{"usage":{"input_tokens":100,"output_tokens":50}}')
    assert extraer_tokens(texto, "opencode") == (100, 50)


def test_extraer_tokens_codex_usa_tokens_used():
    texto = "tokens_used: 5\ntokens_used: 7"
    assert extraer_tokens(texto, "codex") == (0, 7)


def test_registrar_metrica_escribe_json_valido(tmp_path):
    cfg = _config(tmp_path)
    salida = tmp_path / "out"
    salida.write_text('{"usage":{"input_tokens":100,"output_tokens":100}}',
                      encoding="utf-8")
    registrar_metrica(cfg, "opencode", "", 1000, 0, str(salida), "t1", 1)
    lineas = _leer(cfg.metrics).splitlines()
    assert lineas, "metrics.jsonl vacío"
    d = json.loads(lineas[0])
    assert d["iter"] == 1 and d["agente"] == "opencode"
    assert d["tokens_in"] == 100 and d["tokens_out"] == 100
    assert d["costo_usd"] > 0 and isinstance(d["costo_usd"], float)
    assert d["tarea"] == "t1"


# ------------------------------------------------------------- run_agente


def test_run_agente_ejecuta_y_registra_metrica(tmp_path):
    salida = tmp_path / "out"
    bin_ = tmp_path / "bin" / "opencode"
    bin_.parent.mkdir(parents=True, exist_ok=True)
    bin_.write_text(
        "#!/usr/bin/env bash\necho '{\"usage\":{\"input_tokens\":5,"
        "\"output_tokens\":5}}'\nexit 0\n", encoding="utf-8")
    bin_.chmod(0o755)
    cfg = _config(tmp_path, {"CLI_OPENCODE": str(bin_)})
    cfg.timeout_por_tarea = 30

    rc, _vivo = run_agente(cfg, "opencode", str(salida), "", "prompt", "t1", 1)
    assert rc == 0
    assert json.loads(_leer(cfg.metrics).splitlines()[0])["rc"] == 0
    assert '{"usage":{"input_tokens":5' in salida.read_text(encoding="utf-8")


def test_run_agente_resuelve_auto(tmp_path):
    salida = tmp_path / "out"
    bin_ = tmp_path / "bin" / "opencode"
    bin_.parent.mkdir(parents=True, exist_ok=True)
    bin_.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    bin_.chmod(0o755)
    env = {"CLI_OPENCODE": str(bin_),
           "AGENTES_PREFERIDOS": "opencode",
           "AGENTE_TAREA": "auto"}
    cfg = _config(tmp_path, env)
    cfg.timeout_por_tarea = 30
    rc, _ = run_agente(cfg, "auto", str(salida), "", "prompt", "t1", 1)
    assert rc == 0


# ---------------------------------------------------------------- revisar_diff


def _revisor_falso(tmp_path, salida_texto):
    bin_ = tmp_path / "bin" / "claude"
    bin_.parent.mkdir(parents=True, exist_ok=True)
    bin_.write_text("#!/usr/bin/env bash\ncat <<'EOF'\n" + salida_texto +
                    "\nEOF\n", encoding="utf-8")
    bin_.chmod(0o755)
    return bin_


def test_revisar_diff_pass(tmp_path):
    bin_ = _revisor_falso(tmp_path, '{"usage":{"input_tokens":1,'
                                      '"output_tokens":1}}\nrazon\nVERDICT: PASS')
    cfg = _config(tmp_path, {"CLI_CLAUDE": str(bin_)})
    cfg.revisor = "claude"
    cfg.modelo_revisor = ""
    cfg.timeout_por_tarea = 30
    resultado, _fb = revisar_diff(cfg, "claude", "t1", "diff")
    assert resultado == "pass"


def test_revisar_diff_fail_devuelve_feedback(tmp_path):
    bin_ = _revisor_falso(tmp_path, 'falta arreglar el modulo\nVERDICT: FAIL')
    cfg = _config(tmp_path, {"CLI_CLAUDE": str(bin_)})
    cfg.timeout_por_tarea = 30
    resultado, fb = revisar_diff(cfg, "claude", "t1", "diff")
    assert resultado == "fail"
    assert "falta arreglar" in fb


def test_revisar_diff_sin_veredicto_como_fail(tmp_path):
    """Output without VERDICT: the reviewer could not evaluate → FAIL (not
    sin_auth because there is no auth pattern either)."""
    bin_ = _revisor_falso(tmp_path, "no se que paso")
    cfg = _config(tmp_path, {"CLI_CLAUDE": str(bin_)})
    cfg.timeout_por_tarea = 30
    resultado, fb = revisar_diff(cfg, "claude", "t1", "diff")
    assert resultado == "fail"
    assert fb


def test_revisar_diff_auth_sin_veredicto(tmp_path):
    """No verdict + auth pattern → sin_auth (the loop aborts with 7)."""
    bin_ = _revisor_falso(
        tmp_path, "Please run claude /login\nveremos")
    cfg = _config(tmp_path, {"CLI_CLAUDE": str(bin_)})
    cfg.timeout_por_tarea = 30
    resultado, _fb = revisar_diff(cfg, "claude", "t1", "diff")
    assert resultado == "sin_auth"


def test_revisar_diff_auth_con_veredicto_es_falso_positivo(tmp_path):
    """With VERDICT present the auth mention is narrative: it counts as
    pass (the reviewer DID work)."""
    bin_ = _revisor_falso(
        tmp_path, 'texto dice "401" pero reviso\nVERDICT: PASS')
    cfg = _config(tmp_path, {"CLI_CLAUDE": str(bin_)})
    cfg.timeout_por_tarea = 30
    resultado, _fb = revisar_diff(cfg, "claude", "t1", "diff")
    assert resultado == "pass"


def test_revisar_diff_incluye_contexto_del_proyecto(tmp_path):
    """The reviewer receives CONTEXTO.md to judge with the project's frame."""
    bin_ = tmp_path / "bin" / "claude"
    bin_.parent.mkdir(parents=True, exist_ok=True)
    bin_.write_text(
        "#!/usr/bin/env bash\n"
        "{ printf '%s\\n' \"$@\"; cat; } > prompt_revisor.txt\n"
        "echo 'VERDICT: PASS'\n", encoding="utf-8")
    bin_.chmod(0o755)
    (tmp_path / "CONTEXTO.md").write_text(
        "MARCADOR_REVISOR_XYZ: app de finanzas personales\n", encoding="utf-8")

    cfg = _config(tmp_path, {"CLI_CLAUDE": str(bin_)})
    cfg.revisor = "claude"
    cfg.timeout_por_tarea = 30
    resultado, _fb = revisar_diff(cfg, "claude", "t1", "diff")
    assert resultado == "pass"

    prompt = _leer(str(tmp_path / "prompt_revisor.txt"))
    assert "MARCADOR_REVISOR_XYZ" in prompt, prompt[-2000:]


# ------------------------------------------------------------------- --dir
#
# `opencode run` attaches to an already-running opencode server and executes in
# THAT server's project, ignoring the cwd we pass: the agent would read and
# edit the wrong repository. `--dir <proyecto>` pins it back to our project.


def _opencode_falso(tmp_path, soporta=True, veredicto=""):
    """Fake opencode: answers `run --help` advertising `--dir` (or not) and
    writes its argv to $CAPTURA on a real run."""
    ayuda = ("Usage: opencode run [options] [message..]\n"
             "  --agent    agent to use\n"
             + ("  --dir      directory to run in\n" if soporta else ""))
    cuerpo = ("#!/usr/bin/env bash\n"
              "if [ \"${1:-}\" = \"run\" ] && [ \"${2:-}\" = \"--help\" ]; then\n"
              "  cat <<'AYUDA'\n" + ayuda + "AYUDA\n"
              "  exit 0\n"
              "fi\n"
              "printf '%s\\n' \"$@\" > \"${CAPTURA:-/dev/null}\"\n"
              + (f"echo '{veredicto}'\n" if veredicto else "")
              + "exit 0\n")
    bin_ = tmp_path / "bin" / "opencode"
    bin_.parent.mkdir(parents=True, exist_ok=True)
    bin_.write_text(cuerpo, encoding="utf-8")
    bin_.chmod(0o755)
    return bin_


@pytest.fixture(autouse=True)
def _limpiar_cache_dir():
    la._DIR_SOPORTADO.clear()
    yield
    la._DIR_SOPORTADO.clear()


def test_soporta_dir_detecta_la_capacidad(tmp_path):
    assert soporta_dir(str(_opencode_falso(tmp_path, soporta=True)))
    assert not soporta_dir(str(_opencode_falso(tmp_path / "viejo", soporta=False)))


def test_soporta_dir_falso_si_el_binario_no_existe():
    assert not soporta_dir("/no/existe/opencode")


def test_run_agente_pasa_dir_al_opencode(tmp_path):
    """argv must carry `--dir <proyecto>` so the agent works in OUR project."""
    captura = tmp_path / "argv.txt"
    bin_ = _opencode_falso(tmp_path, soporta=True)
    cfg = _config(tmp_path, {"CLI_OPENCODE": str(bin_),
                             "CAPTURA": str(captura)})
    cfg.timeout_por_tarea = 30

    rc, _vivo = run_agente(cfg, "opencode", str(tmp_path / "out"), "",
                           "prompt", "t1", 1)
    assert rc == 0
    argv = captura.read_text(encoding="utf-8").splitlines()
    assert "run" in argv and "--agent" in argv
    assert "--dir" in argv, argv
    assert argv[argv.index("--dir") + 1] == str(tmp_path)
    assert argv[-1] == "prompt"


def test_run_agente_sin_dir_en_opencode_antiguo(tmp_path):
    """An older opencode without `--dir` must keep working (no flag added)."""
    captura = tmp_path / "argv.txt"
    bin_ = _opencode_falso(tmp_path, soporta=False)
    cfg = _config(tmp_path, {"CLI_OPENCODE": str(bin_),
                             "CAPTURA": str(captura)})
    cfg.timeout_por_tarea = 30

    rc, _vivo = run_agente(cfg, "opencode", str(tmp_path / "out"), "",
                           "prompt", "t1", 1)
    assert rc == 0
    argv = captura.read_text(encoding="utf-8").splitlines()
    assert "--dir" not in argv, argv
    assert argv[-1] == "prompt"


def test_revisor_tambien_recibe_dir(tmp_path):
    """The reviewer runs through run_agente, so it inherits `--dir` too."""
    captura = tmp_path / "argv.txt"
    bin_ = _opencode_falso(tmp_path, soporta=True, veredicto="VERDICT: PASS")
    cfg = _config(tmp_path, {"CLI_OPENCODE": str(bin_),
                             "CAPTURA": str(captura)})
    cfg.revisor = "opencode"
    cfg.modelo_revisor = ""
    cfg.timeout_por_tarea = 30

    resultado, _fb = revisar_diff(cfg, "opencode", "t1", "diff")
    assert resultado == "pass"
    argv = captura.read_text(encoding="utf-8").splitlines()
    assert argv[argv.index("--dir") + 1] == str(tmp_path)


# ------------------------------------------------------------- claude roles

def test_modelo_claude_solo_acepta_modelos_de_claude():
    from dedalo.loop_agentes import modelo_claude
    assert modelo_claude("haiku") == "haiku"
    assert modelo_claude("anthropic/haiku") == "haiku"
    assert modelo_claude("anthropic/claude-sonnet-4-5") == "claude-sonnet-4-5"
    assert modelo_claude("opencode/big-pickle") == ""
    assert modelo_claude("") == ""


def test_claude_tarea_edita_y_corre_herramientas_del_stack(tmp_path):
    from dedalo import plantillas
    from dedalo.loop_agentes import flags_claude
    plantillas.instalar(str(tmp_path), "python")
    flags = flags_claude("tarea", str(tmp_path), "anthropic/haiku",
                         extra="--verbose")
    assert "--strict-mcp-config" in flags
    assert flags[flags.index("--permission-mode") + 1] == "acceptEdits"
    assert "Bash(pytest:*)" in flags and "Bash(ruff:*)" in flags
    assert not any("git" in f for f in flags), "git es del loop, no del agente"
    assert "--verbose" in flags
    assert flags[-2:] == ["--model", "haiku"]


def test_claude_roles_de_lectura_no_pueden_escribir(tmp_path):
    from dedalo.loop_agentes import flags_claude
    for rol in ("revisor", "juez", "lectura"):
        flags = flags_claude(rol, str(tmp_path), extra="--permission-mode acceptEdits")
        assert "acceptEdits" not in flags, f"{rol}: CLAUDE_FLAGS es solo para la tarea"
        vetadas = flags[flags.index("--disallowedTools") + 1:]
        for herramienta in ("Edit", "Write", "Bash"):
            assert herramienta in vetadas
        # Ends in a non-variadic option: a positional prompt stays a prompt.
        assert flags[-2:] == ["--permission-mode", "default"]


def test_agente_recibe_el_prompt_por_stdin(tmp_path):
    """The prompt never travels in argv (variadic flags, Windows 32K limit)."""
    bin_ = tmp_path / "bin" / "claude"
    bin_.parent.mkdir(parents=True, exist_ok=True)
    bin_.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > args.txt\n"
                    "cat > stdin.txt\necho 'VERDICT: PASS'\n", encoding="utf-8")
    bin_.chmod(0o755)
    cfg = _config(tmp_path, {"CLI_CLAUDE": str(bin_)})
    cfg.revisor = "claude"
    cfg.timeout_por_tarea = 30
    revisar_diff(cfg, "claude", "t1", "DIFF_UNICO_123")
    assert "DIFF_UNICO_123" in _leer(str(tmp_path / "stdin.txt"))
    assert "DIFF_UNICO_123" not in _leer(str(tmp_path / "args.txt"))
