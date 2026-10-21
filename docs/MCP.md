# Dédalo MCP Server

`dedalo.mcp_server` exposes Dédalo over the **Model Context Protocol** (stdio,
JSON-RPC). It is the same panel, without the GUI: an MCP client can list
projects, read their memory and logs, run the gate, start and stop the loop,
and answer a pending manual review.

Use it when you want another agent — a "pilot" — to supervise Dédalo, or when
you want to drive a project from an editor that speaks MCP.

- **Transport:** stdio only. No ports are opened.
- **Process:** headless; it does not import PySide6.
- **Source only:** the packaged binary is built `--windowed` (no console), so
  it cannot serve stdio. Run it from a checkout.

---

## Requirements

- Python 3.10+ and a Dédalo checkout.
- The `mcp` extra. `install.sh` already installs it; for a manual install:

```bash
pip install -e ".[mcp]"
```

- At least one agent CLI with a session (`opencode`, `codex` or `claude`) if
  you plan to start loops.

Verify the install:

```bash
.venv/bin/python -c "import mcp; print(mcp.__version__)"
.venv/bin/python -m dedalo.mcp_server   # starts serving; Ctrl+C to exit
```

The server speaks JSON-RPC on stdin/stdout, so running it by hand will look like
it is waiting for input. That is expected.

---

## Client configuration

Always use the **absolute path** to the virtual environment's Python. A bare
`python` may resolve to another interpreter that cannot import `dedalo`.

### opencode

Add this to your `opencode.json` (global or project-level):

```json
{
  "mcp": {
    "dedalo": {
      "type": "local",
      "command": [
        "/absolute/path/to/dedalo/.venv/bin/python",
        "-m",
        "dedalo.mcp_server"
      ],
      "enabled": true
    }
  }
}
```

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, or
`%APPDATA%\Claude\claude_desktop_config.json` on Windows:

```json
{
  "mcpServers": {
    "dedalo": {
      "command": "/absolute/path/to/dedalo/.venv/bin/python",
      "args": ["-m", "dedalo.mcp_server"]
    }
  }
}
```

### After an upgrade

**Restart the MCP client.** A long-running server keeps the modules it imported
at startup, so code changes (and packages added to `.venv`) are not picked up
until the client starts a new process. The loop engine is spawned fresh for each
run, so engine fixes apply without restarting the client.

---

## Tools

All tools return a JSON string (some return plain text, as noted). Project names
are the names registered in Dédalo, not paths.

### Read

| Tool | Parameters | Returns |
|---|---|---|
| `listar_proyectos` | — | Array of `{nombre, ruta, existe}` for every registered project. |
| `estado_proyecto` | `nombre` | Project path and existence, plan counts (`pendientes`, `hechas`, `bloqueadas`), size of `lecciones.md`/`CONTEXTO.md`, and the current loop state. |
| `leer_fichero` | `nombre`, `fichero` | Raw content of an allowed file; empty string if it does not exist. Unknown names raise `ValueError`. |
| `leer_plan` | `nombre` | Content of `plan.md`. |
| `leer_lecciones` | `nombre` | Content of `lecciones.md`. |
| `leer_contexto` | `nombre` | Content of `CONTEXTO.md`. |
| `leer_incidencias` | `nombre`, `limite=50` | Last `limite` structured incidents from `incidencias.jsonl` as a JSON array. |
| `resumen_metricas` | `nombre` | `{resumen, iteraciones}` parsed from `progreso.log`; the last 25 iterations. |
| `cola_log` | `nombre`, `lineas=60` | Last `lineas` lines of `progreso.log`; empty string if missing. |
| `estado_agentes` | — | Per-CLI state: installed, path, and whether it has a session. |
| `listar_modelos` | — | `{sugerido, modelos}` from the opencode catalog. |

Allowed `fichero` names: `plan.md`, `lecciones.md`, `CONTEXTO.md`,
`progreso.log`, `metrics.jsonl`, `incidencias.jsonl`, `mapeo.txt`.

The first three live at the project root. The four run artifacts live under
`<project>/.dedalo/estado/` (legacy root layouts are still resolved).

### Act

| Tool | Parameters | Effect |
|---|---|---|
| `instalar_proyecto` | `ruta`, `nombre=""` | Creates the folder if needed, installs the Dédalo templates, initializes git (if absent), and registers the project. Returns `{nombre, ruta, creados, git}`. |
| `confiar_gate` | `nombre` | Records consent for the project's current `gate_checks` (same as the GUI prompt). Required before a headless loop can run its gate. Returns `{proyecto, gate_confiado}`. |
| `correr_gate` | `nombre`, `timeout_s=1800` | Runs the gate **blocking** and returns `{rc, stdout, stderr}`; on timeout returns `{rc: -1, timeout: true, ...}`. Without gate consent it returns `rc: 3` and does not execute the checks. |
| `iniciar_loop` | `nombre` | Starts the engine in the background. Returns `{nombre, pid, agente_tarea, agente_revisor, revision_manual}`. Refuses if the loop is already running, there is no internet, the gate is not trusted, or no agent has a session. |
| `estado_loop` | `nombre` | `{nombre, corriendo, pid, origen, revision_pendiente, tarea_en_revision}`. Reflects loops started by the GUI too. |
| `detener_loop` | `nombre`, `espera_s=5` | Stops the loop's whole process group (TERM, then KILL). Returns `{nombre, pid, detenido}`; `detenido: false` if it was not running or the process could not be stopped. |
| `resolver_revision` | `nombre`, `decision`, `motivo=""` | Writes `APPROVE` or `REJECT <motivo>` plus `# origen=mcp` to `.dedalo/review/decision` (mode `0600`). |

`decision` is case-insensitive and must be `APPROVE` or `REJECT`.

---

## Resources

| URI | Content |
|---|---|
| `dedalo://{nombre}/plan.md` | Task list. |
| `dedalo://{nombre}/lecciones.md` | Project memory. |
| `dedalo://{nombre}/CONTEXTO.md` | Permanent context. |
| `dedalo://{nombre}/progreso.log` | Loop log. |
| `dedalo://{nombre}/metrics.jsonl` | One JSON object per iteration. |
| `dedalo://{nombre}/incidencias.jsonl` | Structured incidents. |
| `dedalo://{nombre}/mapeo.txt` | Project map. |
| `dedalo://manual` | Full curated manual. |

The same manual is sent in the `instructions` field of `initialize`, so the
model starts with Dédalo's vocabulary and file layout already loaded.

---

## Recommended pilot workflow

1. `listar_proyectos` → choose a project.
2. `estado_proyecto` → confirm the plan, memory and loop state.
3. `leer_contexto`, `leer_lecciones`, `leer_plan` → understand the work.
4. `cola_log` and `leer_incidencias` → see what happened last.
5. `confiar_gate` once (or after the checks change).
6. `correr_gate` → catch a broken baseline before spending tokens.
7. `iniciar_loop` → start it; keep the returned `pid`.
8. Poll `estado_loop` every 30–60 s and read `cola_log` for progress.
9. If `revision_pendiente` is true, inspect the diff in the project (the MCP
   surface does not expose a diff tool), then `resolver_revision` with
   `APPROVE` or `REJECT` plus a reason. `APPROVE` only takes effect with
   `REVISION_APRUEBA_AGENTE=1`; `REJECT` always works.
10. `detener_loop` only if you need to interrupt; otherwise wait for
    `estado_loop.corriendo` to become false and read `estado_proyecto` again.

---

## Consent, review and safety

- **Gate consent** is per project and tied to the contents of `gate_checks/`.
  `confiar_gate` is the headless equivalent of the GUI's first-run prompt.
  `correr_gate` returns `rc: 3` without it, and the engine aborts with exit
  code `3` if it runs out of options to ask.
- **Manual review:** with `REVISION_MANUAL=1` the loop pauses before each
  commit. An agent's `APPROVE` (`origen=mcp`) is **ignored by default**; the
  loop keeps waiting for a human. Set `REVISION_APRUEBA_AGENTE=1` to allow a
  pilot to approve. `REJECT` is always honored, and every decision is audited
  in `progreso.log` with its origin.
- **Push:** the loop pushes the work branch (default `dedalo/*`), never
  `main`/`master`/the configured base. Branch protection on GitHub is the final
  backstop.
- **Environment:** the engine receives only Dédalo's allowlist, not the full
  environment of the MCP client. Opt in extra variables with
  `DEDALO_ENTORNO_EXTRA`.
- **State:** the GUI, the MCP server and the engine share
  `~/.config/dedalo/loops.json`; the engine holds an exclusive `flock` for its
  lifetime, so a project cannot run two loops.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The client does not list Dédalo | Wrong config key (`mcp` for opencode, `mcpServers` for Claude Desktop), or a relative/incorrect interpreter path. Use the absolute `.venv/bin/python`. Restart the client. |
| `ModuleNotFoundError: dedalo` or `mcp` | The client launched a different Python. Point `command` at the checkout's `.venv/bin/python` and install with `pip install -e ".[mcp]"`. |
| Tools behave like an old version | The MCP process cached the old modules. Restart the client. |
| `iniciar_loop` returns `iniciado: false` | The loop is already running, there is no internet, or no agent has a session (`estado_agentes`). |
| The gate aborts with code `3` | The project's checks are not trusted. Call `confiar_gate`, approve in the GUI, or set `DEDALO_GATE_CONSENT=1` for CI. |
| `APPROVE` seems to do nothing | Default policy ignores agent approvals. Use a human decision or set `REVISION_APRUEBA_AGENTE=1`. |
| No notifications from MCP-started loops | Configure a channel and its event switches in **Security → Notifications**; the engine uses the project's config. Failures are logged in `progreso.log`. |
| stdio transport unavailable in the binary | Expected: the packaged app is `--windowed`. Use the source checkout. |

---

## See also

- [README — MCP Server](../README.md#-mcp-server-pilot-agent)
- [Technical spec](FICHA_TECNICA.md)
- [Known bugs](BUGS_CONOCIDOS.md)
