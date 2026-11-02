"""Codex CLI integration shared by the native engine and gate preparation."""

import json
import re
import shlex
import subprocess


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
    if not any(x in ("-s", "--sandbox", "--approve-for-me",
                     "--dangerously-bypass-approvals-and-sandbox")
               or x.startswith("--sandbox=") for x in flags):
        flags += ["--sandbox", "workspace-write" if rol == "tarea" else "read-only"]
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
