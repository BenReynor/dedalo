"""Codex integration: real subprocess contract, isolated projects and JSONL."""

import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from dedalo import modelos
from dedalo.codex_cli import flags_codex, modelo_codex, resultado_codex
from dedalo.loop import Config
from dedalo.loop_agentes import revisar_diff, run_agente, run_navegador
from dedalo.loop_args import parse_args
from dedalo.loop_launch import entorno_juez, preparar


@pytest.fixture
def codex(tmp_path):
    binary = tmp_path / "codex"
    binary.write_text(f"#!{sys.executable}\n" + '''
import json, pathlib, sys
args = sys.argv[1:]
if args[:2] == ['mcp', 'list']:
    print(json.dumps([{'name': 'dedalo'}, {'name': 'argus'}, {'name': 'github'}]))
    sys.exit(0)
if args == ['login', 'status']:
    print('Logged in using ChatGPT')
    sys.exit(0)
prompt = sys.stdin.read() if args[-1] == '-' else args[-1]
pathlib.Path(__file__).with_name('invocation.json').write_text(json.dumps({'args':args, 'prompt':prompt}))
if prompt.startswith('Eres el JUEZ'):
    message = json.dumps({'met':True, 'reason':'Existe src/nuevo.py'})
elif prompt.startswith('Eres el OBSERVADOR'):
    message = json.dumps({'resumen':'Archivo creado y verificado.', 'confianza':'alta'})
elif prompt.startswith('Eres el REVISOR'):
    message = 'Todo correcto.\\nVERDICT: PASS'
elif prompt.startswith('Tarea:') and 'ARCHIVOS:' in prompt:
    message = 'ARCHIVOS: src/nuevo.py'
else:
    pathlib.Path('src').mkdir(exist_ok=True)
    pathlib.Path('src/nuevo.py').write_text('VALUE = 42\\n')
    message = 'Archivo creado.'
if '--json' not in args:
    print(message)
    sys.exit(0)
print(json.dumps({'type':'item.completed', 'item':{'type':'command_execution', 'aggregated_output':'VERDICT: FAIL'}}))
print(json.dumps({'type':'item.completed', 'item':{'type':'agent_message','text':message}}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':123,'cached_input_tokens':100,'output_tokens':7}}))
''', encoding="utf-8")
    binary.chmod(0o755)
    return binary


def config(tmp_path, codex):
    env = {"PATH": os.environ.get("PATH", ""), "CLI_CODEX": str(codex),
           "AGENTE_TAREA": "codex", "AGENTE_JUEZ": "codex",
           "VOZ": "0", "TIMEOUT_POR_TAREA": "10"}
    return Config(parse_args(["plan.md"]), environ=env, proyecto=str(tmp_path))


@pytest.mark.parametrize(('selection', 'expected'), [
    ('openai/gpt-5', 'gpt-5'), ('gpt-5-codex', 'gpt-5-codex'),
    ('o3', 'o3'), ('anthropic/haiku', ''), ('opencode/big-pickle', ''), ('', ''),
])
def test_model_selection(selection, expected):
    assert modelo_codex(selection) == expected


def test_login_status_never_uses_inference(codex, monkeypatch):
    monkeypatch.setattr(modelos, 'ruta_binario', lambda name: str(codex))
    monkeypatch.setattr(modelos, '_sesiones', {})
    assert modelos.sesion_agente('codex') is True
    assert modelos.SONDA_SESION['codex'][0] == ['login', 'status']


@pytest.mark.parametrize(('rc', 'text', 'expected'), [
    (1, 'Not logged in', False), (1, 'Network unavailable', None),
])
def test_login_failure_is_not_mistaken_for_a_session(monkeypatch, rc, text, expected):
    monkeypatch.setattr(modelos, 'ruta_binario', lambda name: '/fake/codex')
    monkeypatch.setattr(modelos, '_sesiones', {})
    monkeypatch.setattr(modelos.subprocess, 'run', lambda *a, **k:
                        subprocess.CompletedProcess(a, rc, '', text))
    assert modelos.sesion_agente('codex') is expected


def test_task_creates_file_and_records_real_json_usage(tmp_path, codex):
    cfg = config(tmp_path, codex)
    output = str(tmp_path / 'task-output')
    rc, _ = run_agente(cfg, 'codex', output, 'openai/gpt-5', 'crear archivo', 't1', 1)
    assert rc == 0
    assert (tmp_path / 'src/nuevo.py').read_text() == 'VALUE = 42\n'
    assert (tmp_path / 'task-output').read_text() == 'Archivo creado.'
    invocation = json.loads((tmp_path / 'invocation.json').read_text())
    args = invocation['args']
    assert args[args.index('--sandbox') + 1] == 'workspace-write'
    assert args[args.index('--model') + 1] == 'gpt-5'
    assert args[args.index('-C') + 1] == str(tmp_path)
    assert invocation['prompt'] == 'crear archivo'
    assert args[-1] == '-'
    for name in ('dedalo', 'argus', 'github'):
        assert f'mcp_servers.{name}.enabled=false' in args
    with open(cfg.metrics) as f:
        metric = json.loads(f.readline())
    assert (metric['tokens_in'], metric['tokens_out']) == (123, 7)


def test_reviewer_reads_final_message_not_command_output(tmp_path, codex):
    cfg = config(tmp_path, codex)
    cfg.modelo_revisor = 'openai/gpt-5'
    cfg.environ['CODEX_FLAGS'] = '--dangerously-bypass-approvals-and-sandbox'
    result, _ = revisar_diff(cfg, 'codex', 'tarea', 'diff')
    assert result == 'pass'
    args = json.loads((tmp_path / 'invocation.json').read_text())['args']
    assert args[args.index('--sandbox') + 1] == 'read-only'
    assert '--dangerously-bypass-approvals-and-sandbox' not in args
    assert not (tmp_path / 'src/nuevo.py').exists()


def test_reviewer_cannot_pass_when_codex_exits_with_error(tmp_path, codex):
    codex.write_text(codex.read_text() + '\nsys.exit(2)\n')
    cfg = config(tmp_path, codex)
    result, feedback = revisar_diff(cfg, 'codex', 'tarea', 'diff')
    assert result == 'fail'
    assert 'rc=2' in feedback


def test_failed_turn_does_not_hide_error_behind_an_earlier_message():
    events = [
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'VERDICT: PASS'}},
        {'type': 'turn.failed', 'error': {'message': 'rate_limit_exceeded'}},
    ]
    text, _ = resultado_codex('\n'.join(json.dumps(e) for e in events))
    assert 'rate_limit_exceeded' in text
    assert 'VERDICT: PASS' not in text


def test_reviewer_uses_last_verdict(tmp_path, codex):
    codex.write_text(codex.read_text().replace(
        "message = 'Todo correcto.\\nVERDICT: PASS'",
        "message = 'VERDICT: PASS\\nVERDICT: FAIL'"))
    cfg = config(tmp_path, codex)
    assert revisar_diff(cfg, 'codex', 'tarea', 'diff')[0] == 'fail'


def test_navigator_uses_read_only_and_selected_model(tmp_path, codex):
    cfg = config(tmp_path, codex)
    rc, _ = run_navegador(cfg, str(tmp_path / 'nav'), 'openai/gpt-5', 'tarea', 'codex')
    assert rc == 0
    assert (tmp_path / 'nav').read_text() == 'ARCHIVOS: src/nuevo.py'
    args = json.loads((tmp_path / 'invocation.json').read_text())['args']
    assert args[args.index('--sandbox') + 1] == 'read-only'
    assert args[args.index('--model') + 1] == 'gpt-5'


def test_judge_flags_protect_installed_gate_checks(tmp_path, codex):
    cfg = config(tmp_path, codex)
    cfg.environ['CODEX_FLAGS'] = '--sandbox danger-full-access'
    env = entorno_juez(cfg.environ, 'openai/gpt-5', str(tmp_path))
    args = env['CODEX_FLAGS'].split()
    assert args[args.index('--sandbox') + 1] == 'read-only'
    assert 'danger-full-access' not in args
    assert '--json' not in args  # Existing judges consume a final JSON answer.
    assert args[args.index('--model') + 1] == 'gpt-5'


def test_mcp_config_failure_stops_before_inference(tmp_path):
    with pytest.raises(ValueError, match='configuración MCP'):
        flags_codex('/no/such/codex', {}, str(tmp_path))


def test_corrupt_mcp_catalog_never_launches_worker(tmp_path, codex):
    codex.write_text(codex.read_text().replace(
        "print(json.dumps([{'name': 'dedalo'}, {'name': 'argus'}, {'name': 'github'}]))",
        "print('invalid catalog')"))
    cfg = config(tmp_path, codex)
    rc, _ = run_agente(cfg, 'codex', str(tmp_path / 'out'), '', 'crear archivo', 't1', 1)
    assert rc == 2
    assert not (tmp_path / 'src/nuevo.py').exists()
    assert not (tmp_path / 'invocation.json').exists()


def test_codex_extra_flags_keep_quoted_values_together(tmp_path, codex):
    cfg = config(tmp_path, codex)
    flags = flags_codex(str(codex), cfg.environ, str(tmp_path),
                        extra="-c 'model_reasoning_effort=high'")
    assert 'model_reasoning_effort=high' in flags
    assert flags[flags.index('--sandbox') + 1] == 'workspace-write'


@pytest.mark.skipif(os.name == 'nt', reason='POSIX SIGTERM integration')
def test_stopping_codex_during_manual_review_clears_waiting_state(tmp_path):
    from pathlib import Path

    from dedalo import estado_loop, rutas

    (tmp_path / 'plan.md').write_text('- [ ] pendiente\n')
    code = '''
import os
from dedalo import estado_loop
from dedalo.loop import Config, _instalar_senales, _esperar_revision_manual
from dedalo.loop_args import parse_args
env = dict(os.environ, AGENTE_TAREA='codex', REVISION_MANUAL='1')
cfg = Config(parse_args(['plan.md']), environ=env, proyecto=os.environ['TEST_PROJECT'])
cfg.vivo = estado_loop.EstadoLoop(cfg.proyecto, 1, 2, agente='codex')
_instalar_senales(cfg)
_esperar_revision_manual(cfg, 'pendiente')
'''
    proc = subprocess.Popen([sys.executable, '-c', code],
                            env=dict(os.environ, TEST_PROJECT=str(tmp_path)),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    review = Path(rutas.dir_review(str(tmp_path)))
    try:
        deadline = time.monotonic() + 5
        while not (review / 'waiting').exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (review / 'waiting').exists()
        proc.terminate()
        proc.communicate(timeout=5)
        assert proc.returncode == 143
        assert not (review / 'waiting').exists()
        assert not (review / 'decision').exists()
        state = estado_loop.leer(str(tmp_path))
        assert state['estado'] == 'abortado'
        assert state['esperando_humano'] is False
        assert (tmp_path / 'plan.md').read_text() == '- [ ] pendiente\n'
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


def test_json_errors_are_visible():
    message, usage = resultado_codex(json.dumps(
        {'type': 'turn.failed', 'error': {'message': 'rate_limit_exceeded'}}))
    assert message == 'rate_limit_exceeded' and usage is None


def test_gui_and_mcp_launch_keep_codex_models(monkeypatch):
    monkeypatch.setattr(modelos, 'agentes_operativos', lambda: ['codex'])
    monkeypatch.setattr(modelos, 'ruta_binario', lambda name: '/bin/codex' if name == 'codex' else '')
    plan = preparar({'agente_cli': 'codex', 'revisor_cli': 'codex',
                     'agente': 'openai/gpt-5', 'revisor': 'openai/gpt-5-codex'},
                    {'activo': True, 'modelo': 'openai/gpt-5'}, environ={})
    assert plan['modelo_tarea'] == plan['env']['MODELO_TAREA'] == 'gpt-5'
    assert plan['modelo_revisor'] == 'gpt-5-codex'


def test_gui_enables_codex_model_selection(app):
    from PySide6.QtWidgets import QComboBox

    from dedalo.paneles import _sincronizar_modelo

    selector, cli = QComboBox(), QComboBox()
    selector.addItems(['openai/gpt-5', 'anthropic/haiku'])
    cli.addItem('codex', 'codex')
    selector.setEnabled(False)
    _sincronizar_modelo(selector, cli)
    assert selector.isEnabled()
    assert selector.currentText() == 'openai/gpt-5'


def test_mcp_gate_uses_project_codex_and_read_only_permissions(tmp_path, codex, monkeypatch):
    from dedalo import mcp_server as m

    monkeypatch.setattr(m, '_ruta_de', lambda name: str(tmp_path))
    monkeypatch.setattr(m.consentimiento, 'concedido', lambda *a: True)
    monkeypatch.setattr(m.loop_launch, 'config_de_proyecto', lambda name:
                        ({'agente_cli': 'codex', 'agente': 'openai/gpt-5'}, {}))
    monkeypatch.setattr(modelos, 'ruta_binario', lambda name: str(codex))
    checks = tmp_path / 'gate_checks'
    checks.mkdir()
    (checks / '01_codex.py').write_text('''
import os
def run(env):
    assert os.environ['AGENTE_JUEZ'] == 'codex'
    flags = os.environ['CODEX_FLAGS'].split()
    assert flags[flags.index('--sandbox') + 1] == 'read-only'
    assert flags[flags.index('--model') + 1] == 'gpt-5'
    return 0
''')
    result = json.loads(m.correr_gate('test-codex', timeout_s=10))
    assert result['rc'] == 0, result


@pytest.mark.parametrize('judge_extension', ['sh', 'py'])
def test_complete_codex_loop_with_navigator_reviewer_gate_and_commit(tmp_path, codex, judge_extension):
    from pathlib import Path

    from test_e2e_loop_python import _correr, _entorno, _escenario

    proyecto = _escenario(tmp_path, '#!/usr/bin/env bash\nexit 0\n')
    source = Path(__file__).parents[1] / 'dedalo/plantillas_data/gate_checks'
    judge = f'98_criterio.{judge_extension}'
    shutil.copy2(source / judge, proyecto / 'gate_checks' / judge)
    env = _entorno(codex)
    env.update({'AGENTE_TAREA': 'codex', 'CLI_CODEX': str(codex),
                'AGENTE_REVISOR': 'codex', 'AGENTES_PREFERIDOS': 'codex',
                'AGENTE_JUEZ': 'codex', 'FICHA_ACTIVA': '1',
                'MODELO_TAREA': 'openai/gpt-5', 'MODELO_REVISOR': 'openai/gpt-5',
                'MODELO_NAVEGADOR': '',
                'NAVEGADOR': '1', 'REVISION_DUAL': '1'})
    rc, cfg = _correr(proyecto, env)
    assert rc == 0
    assert '- [x] t1' in (proyecto / 'plan.md').read_text()
    assert (proyecto / 'src/nuevo.py').read_text() == 'VALUE = 42\n'
    commits = subprocess.run(['git', 'log', '--format=%s'], cwd=proyecto,
                             capture_output=True, text=True, check=True).stdout
    assert 'dedalo:' in commits
    with open(cfg.metrics) as f:
        metrics = [json.loads(line) for line in f]
    assert len(metrics) >= 4
    assert all(m['agente'] == 'codex' for m in metrics)
    assert all(m['tokens_in'] == 123 for m in metrics)
    fichas = list((proyecto / '.dedalo/fichas').glob('*.json'))
    assert fichas
    result = json.loads(fichas[0].read_text())
    assert result['incompleta'] is False
    assert result['generado_por']['agente'] == 'codex'
    assert result['resumen'] == 'Archivo creado y verificado.'
