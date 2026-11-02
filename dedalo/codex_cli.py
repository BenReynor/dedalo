"""Codex CLI integration shared by the native engine and gate preparation."""

import json
import re
import shlex
import subprocess

NIVELES_RAZONAMIENTO = ("minimal", "low", "medium", "high", "xhigh")

# Linux sandbox (bubblewrap) blocked by the OS, e.g. Ubuntu 24.04 with
# kernel.apparmor_restrict_unprivileged_userns=1 and no AppArmor profile for bwrap.
_PATRON_SANDBOX_ROTO = re.compile(
    r"bwrap:.*(Operation not permitted|Permission denied)|"
    r"Failed RTM_NEWADDR|setting up uid map|"
    r"No permissions to create (a )?new namespace", re.IGNORECASE)

MENSAJE_SANDBOX_ROTO = (
    "el sandbox de Codex (bubblewrap) no puede arrancar en este sistema "
    "(AppArmor bloquea los user namespaces). Opciones: (1) crear un perfil "
    "AppArmor para /usr/bin/bwrap con 'userns,' (recomendado), o (2) poner "
    "\"sin_sandbox_codex\": true en el lanzamiento del proyecto o "
    "CODEX_SIN_SANDBOX=1 (Codex corre SIN sandbox en todos sus roles: tarea, "
    "revisor y juez; el loop sigue trabajando en ramas aisladas)")


def sandbox_roto(texto):
    """True if Codex output shows the Linux sandbox could not start."""
    return bool(_PATRON_SANDBOX_ROTO.search(texto or ""))


def sandbox_funciona(binario, env=None, cwd=None):
    """Free preflight (no model call): can Codex start its Linux sandbox?

    Returns (ok, detail). Only meaningful on Linux; elsewhere it returns ok.
    """
    import sys
    if not sys.platform.startswith("linux"):
        return True, ""
    try:
        p = subprocess.run([binario, "sandbox", "--", "true"], env=env,
                           cwd=cwd or None, capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return True, f"no se pudo comprobar el sandbox: {e}"
    salida = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0 and sandbox_roto(salida):
        return False, salida.strip()[-400:]
    return True, ""


def razonamiento(env, rol):
    """Reasoning effort for a role from CODEX_RAZONAMIENTO_<ROL> ("" = Codex default)."""
    clave = {"lectura": "NAVEGADOR"}.get(rol, rol.upper())
    nivel = (env or {}).get("CODEX_RAZONAMIENTO_" + clave, "").strip().lower()
    return nivel if nivel in NIVELES_RAZONAMIENTO else ""


def modelo_codex(seleccion):
    """Translate OpenAI provider/model selections to Codex model identifiers."""
    modelo = (seleccion or "").strip()
    if modelo.startswith("openai/"):
        modelo = modelo[len("openai/"):]
    if re.fullmatch(r"(?:gpt-|codex-|o[134](?:-|$))[A-Za-z0-9._-]*", modelo):
        return modelo
    return ""


def flags_codex(binario, env, proyecto, rol="tarea", modelo="", extra=""):
    """Set role permissions and disable nested MCPs without altering user config.

    The effective MCP catalog is queried in the target project so project and
    CODEX_HOME configuration are included. If it cannot be read, stop before
    inference rather than accidentally granting the worker the pilot's tools.
    """
    try:
        consulta = subprocess.run(
            [binario, "mcp", "list", "--json"], env=env, cwd=proyecto or None,
            capture_output=True, text=True, timeout=20)
        servidores = json.loads(consulta.stdout)
        if consulta.returncode or not isinstance(servidores, list):
            raise ValueError
        nombres = [s["name"] for s in servidores]
        if not all(isinstance(n, str) and re.fullmatch(r"[A-Za-z0-9_-]+", n)
                   for n in nombres):
            raise ValueError
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as e:
        raise ValueError("No se pudo consultar la configuración MCP de Codex") from e
    # Extra flags belong to the task agent, never to read-only roles.
    flags = shlex.split(extra) if rol == "tarea" else []
    if str((env or {}).get("CODEX_SIN_SANDBOX", "")) == "1":
        # Explicit user choice when bubblewrap cannot start: every role, or the
        # read-only judge/reviewer would keep failing inside the sandbox.
        flags = [f for f in flags if f != "--dangerously-bypass-approvals-and-sandbox"]
        flags.append("--dangerously-bypass-approvals-and-sandbox")
    if not any(x in ("-s", "--sandbox", "--approve-for-me",
                     "--dangerously-bypass-approvals-and-sandbox")
               or x.startswith("--sandbox=") for x in flags):
        flags += ["--sandbox", "workspace-write" if rol == "tarea" else "read-only"]
    # workspace-write cuts the network by default: the task agent could not
    # add crates/npm packages and coded blind. CODEX_RED_TAREA=0 restores it.
    if rol == "tarea" and str((env or {}).get("CODEX_RED_TAREA", "1")) != "0":
        flags += ["-c", "sandbox_workspace_write.network_access=true"]
    nivel = razonamiento(env, rol)
    if nivel:
        flags += ["-c", f'model_reasoning_effort="{nivel}"']
    flags += ["--ephemeral", "-c", 'approval_policy="never"']
    for nombre in nombres:
        flags += ["-c", "mcp_servers." + nombre + ".enabled=false"]
    elegido = modelo_codex(modelo)
    if elegido:
        flags += ["--model", elegido]
    return flags


def resultado_codex(texto):
    """Final agent message and usage from exec JSONL; keep legacy text readable."""
    mensajes, errores = [], []
    usage = None
    reconocido = False
    fallido = False
    for linea in texto.splitlines():
        try:
            evento = json.loads(linea)
        except ValueError:
            continue
        if not isinstance(evento, dict) or "type" not in evento:
            continue
        reconocido = True
        if evento["type"] == "item.completed":
            item = evento.get("item", {})
            if item.get("type") == "agent_message":
                mensajes.append(item.get("text", ""))
        elif evento["type"] == "turn.completed":
            usage = evento.get("usage")
            fallido = False
        elif evento["type"] in ("error", "turn.failed"):
            error = evento.get("error", evento)
            errores.append(str(error.get("message", "Codex failed"))
                           if isinstance(error, dict) else str(error))
            if evento["type"] == "turn.failed":
                fallido = True
    final = mensajes[-1] if mensajes and not fallido else "\n".join(errores)
    return (final if reconocido else texto), usage
