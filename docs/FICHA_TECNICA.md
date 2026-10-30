# Technical spec — Dédalo

For anyone who is going to **use or integrate** Dédalo and wants the hard data
without reading the code. For step-by-step usage see the [README](../README.md); for live
technical debt, [BUGS_CONOCIDOS.md](BUGS_CONOCIDOS.md).

## What it is

A graphical control panel (PySide6) that orchestrates command-line AI agents
(`opencode`, `claude`) over a project: they iterate on tasks from a `plan.md`,
run the gate (`gate.sh`), request code review and commit. The engine does not
depend on the GUI: it can be driven from the CLI or over MCP.

- **Package / CLI / binary**: `dedalo`
- **Display name**: Dédalo
- **Repository**: <https://github.com/BenReynor/dedalo>
- **Version**: 2.1.0
- **License**: MIT (first-party code)

## Requirements

| Requirement | Value |
|-----------|-------|
| Python | ≥ 3.10 |
| Operating system | Linux (supported); native Windows is experimental (CI-tested only, not validated on real hardware) |
| Graphical interface | Qt (X11/Wayland on Linux, native on Windows) |
| Network | Outbound only (model API, remote `git`, webhooks); opens no ports |

## Dependencies

| Package | Version | Role | License |
|---------|---------|-------|----------|
| PySide6 | ≥ 6.11.0 | GUI (Qt) | LGPL-3.0 (via dynamic linking) |
| pyqtgraph | ≥ 0.13.7 | Charts | MIT |
| mcp | ≥ 2 (extra `[mcp]`) | MCP server over stdio | MIT |

Dev (`.[dev]`): `pytest`, `ruff`. Full lock with hashes in
[`requirements.lock`](../requirements.lock) (generated with `uv pip compile`).

## Installation

```bash
git clone https://github.com/BenReynor/dedalo.git
cd dedalo
python3 -m venv venv && source venv/bin/activate
pip install -e .            # de fuentes
pip install -e ".[dev]"     # + tests/lint
pip install -e ".[mcp]"     # + servidor MCP
python -m dedalo            # arranca la GUI
```

There is also `install.sh` (environment + desktop shortcut).

## Components

| Module | Function |
|--------|---------|
| `dedalo/app.py` | Main PySide6 window (launched with `python -m dedalo`), opened after a loading screen (`carga.py`). |
| `dedalo/cabina.py` | Run cockpit: status, plan progress, phase pipeline and timeline, fed by `estado_loop.py`. |
| `dedalo/loop.py` | Loop engine: agent → gate → reviewer → commit. |
| `dedalo/gate.py` | Runs the checks (`gate_checks/`) and decides green/red. |
| `dedalo/mcp_server.py` | MCP server over stdio (integration with agents/editors). |
| `dedalo/plantillas_data/dedalo.sh` | Bash port of the loop (superseded by the GUI). |
| `dedalo/plantillas_data/gate.sh`, `mapear.sh` | Gate and mapping for the user's project. |
| `dedalo/plantillas_data/` | Templates copied into every project: `plan.md`, `lecciones.md`, `CONTEXTO.md`, `gate_checks/`, icon. |

Installing the templates into a project creates `.dedalo/scripts/{dedalo.sh,gate.sh,mapear.sh,gate_checks/}`,
`plan.md`, `lecciones.md`, `CONTEXTO.md` and tweaks the `.gitignore` to keep the framework
out of the user's repo.

## CLI usage

```bash
python -m dedalo                      # GUI
python -m dedalo.gate --proyecto RUTA  # gate only (exit 0 green / ≠0 red)
python -m dedalo.mcp_server            # servidor MCP (stdio)
```

`dedalo.sh` (bash port, deprecated) and the packaged `entrypoint` accept
`--dedalo-loop`, `--dedalo-gate`, `--dedalo-mcp`. The engine is configured via
environment variables (see the table in the [README](../README.md#-loop-environment-variables)).

## MCP Server

A **stdio** server (JSON-RPC), designed so that an MCP client (opencode,
etc.) can control Dédalo without the GUI. Protocol `2024-11-05`.

Full tool reference, client configuration and worked examples:
[`docs/MCP.md`](MCP.md).

- **Launch**: `python -m dedalo.mcp_server`
- **18 tools**: `listar_proyectos`, `estado_proyecto`, `leer_fichero`,
  `leer_plan`, `leer_lecciones`, `leer_contexto`, `leer_incidencias`,
  `resumen_metricas`, `cola_log`, `estado_agentes`, `listar_modelos`,
  `instalar_proyecto`, `confiar_gate`, `correr_gate`, `iniciar_loop`,
  `estado_loop`, `detener_loop`, `resolver_revision`.
- **Instructions** (`instructions` of the `initialize`): a curated Dédalo manual
  (what it is, how the loop works, project files and the usage flow) that the
  client hands to the model as startup context.
- **Resources**:
  - `dedalo://{nombre}/{fichero}` — allowed names: `plan.md`,
    `lecciones.md`, `CONTEXTO.md`, `progreso.log`, `metrics.jsonl`,
    `incidencias.jsonl`, `mapeo.txt` (run-state names resolve under
    `.dedalo/estado/`).
  - `dedalo://manual` — the full manual on demand.

Example configuration in an MCP client (opencode):

```json
{
  "mcp": {
    "dedalo": {
      "type": "local",
      "command": ["/ruta/al/venv/bin/python", "-m", "dedalo.mcp_server"],
      "enabled": true
    }
  }
}
```

## Data and state

| Path | Content |
|------|-----------|
| `~/.config/dedalo/proyectos.json` | Project registry (+ webhook tokens). |
| `~/.config/dedalo/models_dev.json` | Model catalog. |
| `<proyecto>/plan.md`, `lecciones.md`, `CONTEXTO.md` | Project-owned files. |
| `<proyecto>/.dedalo/estado/` | Run state (`progreso.log`, `metrics.jsonl`, ...). |
| `<proyecto>/.dedalo/fichas/` | Opt-in JSON fichas per accepted task (`index.jsonl` + one file each). |

The config directory is created with `0700` permissions.

## Platforms and artifacts

Binaries are published in [Releases](https://github.com/BenReynor/dedalo/releases)
when `v*` is tagged; every Release includes `SHA256SUMS*`.

| OS | Artifacts | Status |
|----|------------|--------|
| Linux | `dedalo-<v>-linux-x86_64.tar.gz`, `dedalo_<v>_amd64.deb`, `dedalo-<v>-x86_64.AppImage` | Reference |
| Windows | `dedalo-<v>-win64.zip` (`dedalo.exe`, onedir) | Experimental, native (no Git Bash) |

Builds are **not signed**: on Windows, SmartScreen warns
(*More info → Run anyway*). Checksums live in the
Release itself (`sha256sum -c SHA256SUMS*`).

### Distribution decisions (closed)

- **No code signing** or notarization: the signing secrets are optional
  in CI; without them the `.exe` ships unsigned and the OS warns.
- **No `.rpm`/Snap/Flatpak**: "any distro" is covered by AppImage +
  `.deb` + portable tar.gz.
- **Native Windows**: WSL2 is not packaged; the bash engine is replaced by
  Python in the bundle (`dedalo.exe`), without requiring Git Bash.
- **No macOS**: never run on real hardware, so it is neither tested in CI
  nor published.
- Integrity verification via `SHA256SUMS` on every Release, plus keyless
  **build provenance** (Sigstore/OIDC); no GPG signature.

## Security (current posture)

Implemented:

- No HTTP server of its own, and no `eval`/`os.system`/`pickle.load` in our
  own code. Project gate checks are the exception by design: the portable gate
  loads a project's `.py` checks with `exec(compile(...))` and runs its `.sh`
  checks with `bash`, i.e. it executes the project's code (see *First-run gate
  consent* below).
- **First-run gate consent**: a project's gate is not run until the user
  consents. Interactive prompt per project, or `DEDALO_GATE_CONSENT=1` for
  CI; non-interactive without consent aborts with exit code `3`. The trust
  decision is stored per project (hashed contents) in
  `~/.config/dedalo/confianza.json` (`0o600`, outside the repo, so a repo can
  never grant itself trust).
- **Manual review is not self-approvable**: by default an agent's `APPROVE`
  is ignored (`REVISION_APRUEBA_AGENTE=1` opts in) and the loop keeps waiting
  for a human. Every decision is audited in `progreso.log` with its origin
  (`gui`/`mcp`/`humano`); `.dedalo/review/decision` is written `0o600`.
- **Push safety**: `--push` only pushes the work branch (`dedalo/*`), aborts if
  the branch resolves to the base/`main`/`master`, and prints the target origin
  URL before pushing.
- **Credentials**: the bundled dev credentials (`admin`/`admin123`) are only
  applied when the backend target is `localhost`; a remote URL never receives
  them.
- **Environment allowlist**: the engine (and the gate and the agent CLIs it
  spawns) does not inherit the caller's full environment; only an allowlist of
  names crosses over (`loop_launch.filtrar_entorno`), so unrelated secrets in
  the user's shell never reach a prompt-injected agent. Extra names can be
  opted in per launch with `DEDALO_ENTORNO_EXTRA`.
- **Shared loop state + single-run lock**: GUI, MCP and engine share one
  registry (`~/.config/dedalo/loops.json`) and the engine holds an exclusive
  `flock` for its whole run, so a loop started by one side is visible to the
  others and a duplicate for the same project cannot start.
- Atomic registry writes (temp file + `os.replace`).
- **CI `seguridad`**: `gitleaks` over the full history + `pip-audit
  --strict` on `requirements.lock` + a check that the lock is up to date.
- Dependency lock with hashes (`requirements.lock`).
- `_sanitizar()` masks tokens (telegram/whatsapp/discord) in errors.
- The gate restores `.dedalo/scripts/{gate.sh,gate_checks/}` if the agent modifies them.
- **Supply chain**: GitHub Actions pinned by commit SHA; every Release carries
  keyless **build provenance** (Sigstore via GitHub OIDC), verifiable with
  `gh attestation verify <file> --repo BenReynor/dedalo`.

Known risks (accepted, see [BUGS_CONOCIDOS.md](BUGS_CONOCIDOS.md)):

- Webhook tokens are stored **in plaintext** in
  `~/.config/dedalo/proyectos.json` (`0700` folder; unencrypted file).
- The AI agent runs as the full user, **with no sandbox** (the tool's
  model, documented as a risk). The environment allowlist above limits what it
  can read from the environment and the gate consent limits what it runs, but
  neither replaces OS-level isolation (containers, `bubblewrap`/`firejail`).

## Quality and CI

| Aspect | Status |
|---------|--------|
| Tests | 588 passed, 5 skipped (`pytest`) |
| Lint | `ruff` (rules E, F, W, I, UP, B) — clean |
| Portability | `test_portabilidad.py` as a guardrail (bash BSD/GNU) |
| CI | 3 jobs: Linux, Windows, security |

## Links

- [README](../README.md) — usage and variable reference.
- [docs/BUGS_CONOCIDOS.md](BUGS_CONOCIDOS.md) — live technical debt.
- [packaging/PRUEBA-MANUAL.md](../packaging/PRUEBA-MANUAL.md) — per-OS manual validation.
