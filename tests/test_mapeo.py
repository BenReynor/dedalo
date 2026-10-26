"""Tests for the pure-Python project map (mapeo.txt)."""

import os
import shutil

import pytest

from dedalo import mapeo, plantillas, rutas


def _escribir(base, rel, texto=""):
    ruta = base / rel
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8")


def test_mapa_de_paquete_python_con_cli(tmp_path):
    """A plain package (no Django) lists modules, tests and argparse commands."""
    _escribir(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    _escribir(tmp_path, "app/cli.py",
              "sub.add_parser('agregar')\nsub.add_parser(\"bajo-stock\")\n")
    _escribir(tmp_path, "app/modelo.py", "class A: pass\n")
    _escribir(tmp_path, "tests/test_modelo.py",
              "def test_uno():\n    pass\n\nasync def test_dos():\n    pass\n")
    texto = mapeo.construir(str(tmp_path))
    assert "app/cli.py" in texto and "app/modelo.py" in texto
    assert "tests/test_modelo.py: 2 tests" in texto
    assert "- test_uno" in texto and "- test_dos" in texto
    assert "agregar  (app/cli.py)" in texto
    assert "bajo-stock  (app/cli.py)" in texto
    assert "Stacks: python" in texto


def test_mapa_detecta_rutas_http(tmp_path):
    _escribir(tmp_path, "api.py",
              "@app.get('/productos')\ndef f(): ...\n"
              "@router.post(\"/ventas\")\ndef g(): ...\n")
    _escribir(tmp_path, "urls.py", "urlpatterns = [path('admin/', v)]\n")
    _escribir(tmp_path, "server.js", "app.delete('/items/:id', h)\n")
    texto = mapeo.construir(str(tmp_path))
    assert "GET /productos  (api.py)" in texto
    assert "POST /ventas  (api.py)" in texto
    assert "admin/  (urls.py)" in texto
    assert "DELETE /items/:id  (server.js)" in texto


def test_mapa_ignora_dependencias_y_caches(tmp_path):
    _escribir(tmp_path, "main.py")
    for d in (".venv/lib/x.py", "node_modules/a/index.js",
              "__pycache__/m.py", ".dedalo/scripts/gate.py"):
        _escribir(tmp_path, d)
    texto = mapeo.construir(str(tmp_path))
    assert "main.py" in texto
    for basura in (".venv", "node_modules", "__pycache__", ".dedalo"):
        assert basura not in texto.split("## Modules")[1]


def test_mapa_sin_rutas_lo_explica(tmp_path):
    _escribir(tmp_path, "main.py", "print('hola')\n")
    texto = mapeo.construir(str(tmp_path))
    assert "(none detected: no Django/Flask" in texto


def test_generar_escribe_en_estado(tmp_path):
    _escribir(tmp_path, "main.py")
    destino = mapeo.generar(str(tmp_path))
    assert destino == rutas.mapeo(str(tmp_path))
    assert "main.py" in open(destino, encoding="utf-8").read()


@pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt",
                    reason="a customized mapear.sh is a bash script")
def test_generar_respeta_mapear_sh_personalizado(tmp_path):
    plantillas.instalar(str(tmp_path))
    with open(rutas.mapear_sh(str(tmp_path)), "w", encoding="utf-8") as f:
        f.write("#!/usr/bin/env bash\necho 'MAPA PROPIO'\n")
    destino = mapeo.generar(str(tmp_path))
    assert open(destino, encoding="utf-8").read().strip() == "MAPA PROPIO"


def test_generar_ignora_mapear_sh_de_fabrica(tmp_path):
    """The bundled mapear.sh is replaced by the Python map (works on Windows)."""
    plantillas.instalar(str(tmp_path))
    _escribir(tmp_path, "main.py")
    destino = mapeo.generar(str(tmp_path))
    assert "## CLI commands" in open(destino, encoding="utf-8").read()


def test_mapa_incluye_binarios_de_rust_en_src_bin(tmp_path):
    _escribir(tmp_path, "Cargo.toml", "[package]\nname='x'\n")
    _escribir(tmp_path, "src/bin/herramienta.rs", "fn main() {}\n")
    _escribir(tmp_path, "bin/compilado.rs", "")  # root build output: ignored
    texto = mapeo.construir(str(tmp_path))
    assert "src/bin/herramienta.rs" in texto
    assert "\n  bin/compilado.rs" not in texto
