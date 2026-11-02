#!/usr/bin/env python3
"""Run the native Dédalo/Codex pipeline in a disposable Git repository."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    codex = shutil.which("codex")
    if not codex:
        sys.exit("No se encontró Codex en PATH.")
    project = Path(tempfile.mkdtemp(prefix="dedalo-codex-real-"))
    print(f"Proyecto de prueba y evidencias: {project}", flush=True)
    print("Usa tu sesión y modelo configurados. Ejecuta varias consultas reales.", flush=True)
    for args in (("init", "-q", "-b", "master"),
                 ("config", "user.name", "Dédalo compatibility check"),
                 ("config", "user.email", "test@example.invalid")):
        subprocess.run(["git", *args], cwd=project, check=True)
    (project / "plan.md").write_text(
        "# Prueba de compatibilidad\n\n"
        "- [ ] Crear src/nuevo.py con una sola línea: VALUE = 42\n"
        "    criterio: src/nuevo.py existe y define VALUE igual a 42.\n",
        encoding="utf-8")
    (project / "CONTEXTO.md").write_text(
        "Repositorio desechable de prueba. Implementa solo src/nuevo.py.\n"
        "No edites el plan, gate_checks ni la configuración. El motor hace los commits.\n",
        encoding="utf-8")
    checks = project / "gate_checks"
    checks.mkdir()
    (checks / "01_valor.py").write_text(
        "from pathlib import Path\nimport runpy\n"
        "def run(env):\n"
        "    p = Path(env.proyecto) / 'src/nuevo.py'\n"
        "    if p.exists():\n"
        "        assert runpy.run_path(str(p)).get('VALUE') == 42\n"
        "    return 0\n", encoding="utf-8")
    shutil.copy2(root / "dedalo/plantillas_data/gate_checks/98_criterio.py",
                 checks / "98_criterio.py")
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "Base de prueba"], cwd=project, check=True)
    # Start a fresh process so every Dédalo registry is isolated before imports.
    sys.path.insert(0, str(root))
    from dedalo.loop_launch import filtrar_entorno
    env = filtrar_entorno(os.environ)
    env.update({
        "PYTHONPATH": str(root), "DEDALO_CONFIG_DIR": str(project / ".config-prueba"),
        "CLI_CODEX": codex, "AGENTE_TAREA": "codex", "AGENTE_REVISOR": "codex",
        "AGENTE_JUEZ": "codex", "AGENTE_FICHA": "codex", "AGENTES_PREFERIDOS": "codex",
        "MODELO_TAREA": "", "MODELO_REVISOR": "", "MODELO_NAVEGADOR": "",
        "MODELO_JUEZ": "", "MODELO_FICHA": "", "CODEX_FLAGS": "",
        "MAX_ITER": "1", "NAVEGADOR": "1", "REVISION_DUAL": "1",
        "REVISION_MANUAL": "0", "FICHA_ACTIVA": "1", "VOZ": "0",
        "DEDALO_GATE_CONSENT": "1", "MAX_COSTO": "0", "FICHAS_DIR": "",
        "TIMEOUT_POR_TAREA": "180", "TIMEOUT_NAVEGADOR": "90",
        "TIMEOUT_JUEZ": "120", "TIMEOUT_FICHA": "120",
    })
    result = subprocess.run([sys.executable, "-m", "dedalo.loop", "plan.md"],
                            cwd=project, env=env)
    complete = "- [x]" in (project / "plan.md").read_text(encoding="utf-8")
    fichas = list((project / ".dedalo/fichas").glob("*.json"))
    documented = any(not json.loads(p.read_text(encoding="utf-8")).get("incompleta", True)
                     for p in fichas)
    passed = result.returncode == 0 and complete and documented
    print("\nDEDALO_CODEX_REAL_OK" if passed else "\nDEDALO_CODEX_REAL_FAIL")
    print(f"Tarea completada: {complete}; ficha completa: {documented}; rc: {result.returncode}")
    print(f"Evidencias conservadas en: {project}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
