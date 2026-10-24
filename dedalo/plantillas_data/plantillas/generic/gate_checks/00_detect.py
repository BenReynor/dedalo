"""Gate genérico: detecta la pila del proyecto y ejecuta sus comandos estándar.

Orden de detección: Rust, Go, Node, Python, web estática, Makefile. Si no
reconoce nada, avisa y deja pasar (añade tus checks en 99_custom.py).
"""
import json
import os
import shutil
import subprocess


def _cmd(env, argv, etiqueta, necesario=True):
    """Runs argv in the project. Returns 0/1. Missing tool -> warn/omit."""
    if not shutil.which(argv[0]):
        env.aviso(f"{etiqueta}: {argv[0]} no disponible, se omite")
        return 0
    p = subprocess.run(argv, cwd=env.proyecto, capture_output=True, text=True)
    if p.returncode != 0:
        env.fail(f"{etiqueta} falló")
        print(p.stdout or p.stderr)
        return 1
    env.ok(f"{etiqueta} OK")
    return 0


def _scripts_node(proyecto):
    try:
        with open(os.path.join(proyecto, "package.json"), encoding="utf-8") as f:
            return (json.load(f).get("scripts") or {})
    except (OSError, json.JSONDecodeError):
        return {}


def _web(env):
    proyecto = env.proyecto
    for nombre in ("index.html", "styles.css", "app.js"):
        if not os.path.isfile(os.path.join(proyecto, nombre)):
            env.fail(f"{nombre} no existe")
            return 1
    for nombre in ("index.html", "styles.css", "app.js"):
        with open(os.path.join(proyecto, nombre), encoding="utf-8",
                  errors="replace") as f:
            if not f.read().strip():
                env.fail(f"{nombre} está vacío")
                return 1
    env.ok("web estática: index.html, styles.css y app.js presentes")
    return 0


def run(env):
    proyecto = env.proyecto
    if os.path.isfile(os.path.join(proyecto, "Cargo.toml")):
        for argv, etiqueta in (
            (["cargo", "fmt", "--check"], "cargo fmt"),
            (["cargo", "check"], "cargo check"),
            (["cargo", "test"], "cargo test"),
        ):
            rc = _cmd(env, argv, etiqueta)
            if rc:
                return rc
        return 0
    if os.path.isfile(os.path.join(proyecto, "go.mod")):
        for argv, etiqueta in (
            (["gofmt", "-l", "."], "gofmt"),
            (["go", "vet", "./..."], "go vet"),
            (["go", "test", "./..."], "go test"),
        ):
            rc = _cmd(env, argv, etiqueta)
            if rc:
                return rc
        return 0
    if os.path.isfile(os.path.join(proyecto, "package.json")):
        scripts = _scripts_node(proyecto)
        for nombre, argv in (
            ("lint", ["npm", "run", "lint"]),
            ("test", ["npm", "test"]),
            ("build", ["npm", "run", "build"]),
        ):
            if nombre in scripts:
                rc = _cmd(env, argv, f"npm {nombre}")
                if rc:
                    return rc
        if not any(n in scripts for n in ("lint", "test", "build")):
            env.aviso("package.json sin scripts lint/test/build")
        return 0
    if any(os.path.isfile(os.path.join(proyecto, n))
           for n in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt")):
        for argv, etiqueta in (
            (["ruff", "check", "."], "ruff"),
            (["pytest", "-q"], "pytest"),
        ):
            rc = _cmd(env, argv, etiqueta)
            if rc:
                return rc
        return 0
    if os.path.isfile(os.path.join(proyecto, "index.html")):
        return _web(env)
    if os.path.isfile(os.path.join(proyecto, "Makefile")):
        for objetivo in ("check", "test"):
            rc = _cmd(env, ["make", objetivo], f"make {objetivo}")
            if rc:
                return rc
        return 0
    env.aviso("pila no reconocida: sin checks automáticos")
    return 0
