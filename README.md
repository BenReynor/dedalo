# Dédalo

[![CI](https://github.com/BenReynor/dedalo/actions/workflows/ci.yml/badge.svg)](https://github.com/BenReynor/dedalo/actions/workflows/ci.yml)
[![Release](https://github.com/BenReynor/dedalo/actions/workflows/release.yml/badge.svg)](https://github.com/BenReynor/dedalo/actions/workflows/release.yml)
[![Latest release](https://img.shields.io/github/v/release/BenReynor/dedalo?sort=semver&color=blue)](https://github.com/BenReynor/dedalo/releases)
[![License: MIT](https://img.shields.io/github/license/BenReynor/dedalo?color=green)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20macOS%20%7C%20Windows-informational)](#-compatibility)

Orchestrates AI agents (opencode, codex, claude) to iterate over tasks in `plan.md`, run tests, request code review, and commit automatically.

> **Working with an AI on this project?** See
> [`docs/FICHA_TECNICA.md`](docs/FICHA_TECNICA.md) —requirements, dependencies,
> platforms, MCP surface, and security in a single file designed so that a model
> (and a technical person) can grasp at a glance what Dédalo is and what it
> includes— or the [`llms.txt`](llms.txt) index, designed so an LLM knows
> what's here without walking the entire repository.

---

## 📑 Table of Contents

- [Quick Start](#-quick-start)
- [What It Does](#-what-it-does)
- [Usage Tips](#-usage-tips)
- [Keyboard Shortcuts](#-keyboard-shortcuts)
- [Themes (9 curated)](#-themes-9-curated)
- [Persistent Settings](#-persistent-settings)
- [Adding a Project That Already Has Content](#-adding-a-project-that-already-has-content)
- [Model Catalog](#-model-catalog)
- [Managed Project Requirements](#-managed-project-requirements)
- [Compatibility and Downloads](#-compatibility)
- [Loop Environment Variables](#-loop-environment-variables)
- [MCP Server (Pilot Agent)](#-mcp-server-pilot-agent)
- [Security](#-security)
- [Development](#-development)
- [Key Structure](#-key-structure)
- [Known Open Bugs](#-known-open-bugs)

---

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/BenReynor/dedalo.git
cd dedalo

# Automatic install: creates .venv, installs with MCP support and
# creates the desktop shortcut.
bash install.sh

# Run: double-click the "Dédalo" desktop icon, or from the terminal:
./lanzar.sh
```

> On Debian/Ubuntu, if the venv module is missing: `sudo apt install python3-venv`.

<details>
<summary>Manual installation (step by step)</summary>

```bash
# Virtual environment (recommended; avoids the distros' PEP 668 error)
python3 -m venv venv
source venv/bin/activate

# Dependencies (with MCP support)
pip install -e ".[mcp]"
# or minimal, without MCP: pip install PySide6 pyqtgraph

# Development dependencies (tests/lint)
pip install -e ".[dev]"

# Run
python -m dedalo
```
</details>

> **Python**: Requires 3.10+.

---

## 🎯 What It Does

| Function | Description |
|---------|-------------|
| **Plan** | Kanban + Markdown editor for `plan.md` (tasks `- [ ]`, done `- [x]`, blocked `- [B]`). |
| **Lessons** | Editor for `lecciones.md` (project memory): injected into the agent before each task, and an entry is added when a task gets blocked. |
| **Incidents** | Table for `incidencias.jsonl` (time, iteration, task, type, reason): failures, aborts, and blocks with their actual cause. |
| **Run** | Launches the loop: agent → gate → reviewer → commit. Parameters: deadline, iterations, base branch, max cost, dual/manual review. |
| **Logs** | Live output of `progreso.log` (loop) and `gate.sh`. Collapsible (⛶) with a permanently visible header. Auto-scroll. |
| **Map** | Viewer for `mapeo.txt` (modules → tests). The **Regenerate** button runs `bash mapear.sh`. |
| **Metrics** | Real-time dashboard: tasks/hour, cumulative cost (amber), gate OK/FAIL, reviewer PASS/FAIL. Exports CSV. |
| **Git** | Project commit history, quick revert. |
| **Security** | CPU temperature limit (safe shutdown), webhooks (Telegram, Discord, WhatsApp). |

> **Project context (`CONTEXTO.md`)**: a permanent file that describes *what
> the project is about* (what it does, requirements, philosophy, structure). The
> loop **injects it into the agent and reviewer prompts** on every iteration, so
> they work with the project's framing rather than blindly. Unlike
> `lecciones.md` (lessons learned, grows on its own) and `plan.md` (tasks), the
> context is stable and you write it. It's installed as a skeleton in every
> project and is **never overwritten**. It has no GUI panel: edit it with your
> own editor.

---

## 💡 Usage Tips

- **Start with the context.** A clear `CONTEXTO.md` and a `plan.md` with small,
  verifiable tasks give better results than long prompts: the loop injects
  `CONTEXTO.md` into the agent and reviewer on *every* iteration.
- **`auto` already picks well.** It takes the first CLI that is installed *and
  has a session*; if an agent shows up as `claude (sin login)`, log in or pick
  another.
- **First contact with someone else's repo: enable manual review.** With
  `REVISION_MANUAL=1` the loop pauses before every commit and waits for your
  `APPROVE`.
- **Set a spending cap.** `MAX_COSTO` is a hard limit in USD; set it before
  leaving the loop unattended.
- **Don't hand-edit the 3 framework scripts** (`dedalo.sh`, `gate.sh`,
  `mapear.sh`): they renew themselves when you open the project. If you touch
  them, commit first.
- **Keep the gate fast.** It runs on every iteration; a slow gate slows the
  whole cycle.
- **Your configuration lives in `~/.config/dedalo/`.** Copy it before
  experimenting; if you want to start from scratch, delete it.
- **The packaged binary does not ship the stdio MCP** (it's built without a
  console): for the MCP "pilot agent", use the source code.
- **Verify downloads.** Check each Release's `SHA256SUMS*` before running a
  binary.

---

## ⌨️ Keyboard Shortcuts

| Key | Action |
|-------|--------|
| `Ctrl+1` … `Ctrl+9` | Switch tab (Plan, Lessons, Incidents, Run, Logs, Map, Git, Metrics, Security) |
| `Ctrl+Q` | Quit |

---

## 🎨 Themes (9 curated)

| Theme | Style |
|------|--------|
| **Dark / Light** | Classic Slate/Blue |
| **Hacker** | Terminal green |
| **Cyberpunk** | Fuchsia/purple neon on graphite |
| **Zinc/Amber Dark** | Amber cockpit (default) |
| **Gray/Red Dark** | Red |
| **Stone/Emerald Light** | Warm green |
| **Zinc/Sky Light** | Blue |
| **Slate/Teal Dark** | Deep teal |

Live switching from the "Theme" selector in the top bar.

---

## ⚙️ Persistent Settings

Stored in `~/.config/dedalo/proyectos.json`:

- Registered projects (path + per-project config)
- Active theme
- Thermal safety
- Webhooks
- Selected models
- **Sidebar width** (`sidebar_ancho`)

Two pieces of window state don't live here, but in Qt's `QSettings`
(`~/.config/dedalo/panel.conf`): the window geometry and the project that was
active.

The registry is written atomically (temp file + `os.replace()`), so a power
cut mid-write won't leave it half-done. Even so, if the JSON ever ends up
corrupt, the app **won't start**: it tells you where the problem is, leaves a
`proyectos.json.corrupto` copy (never overwriting a previous one), and offers
two ways out:

- **Exit and fix it by hand** (default): the original is left untouched and, if
  you reopen, it warns you again instead of silently losing the registry.
- **Start from scratch**: only then is the original discarded, and the copy is
  kept in case something needs recovering by hand.

---

## 📂 Adding a Project That Already Has Content

The folder picker accepts any existing directory, not just an empty one.
It's worth knowing what the app touches in each case:

| | What it does |
|---|---|
| Missing files (`plan.md`, `lecciones.md`, `CONTEXTO.md`, `.gitignore`, scripts) | Copies them from the template. **Never overwrites an existing file.** |
| `plan.md`, `lecciones.md`, `CONTEXTO.md`, `gate_checks/*.sh` | Your own content. Never compared, never overwritten. |
| `dedalo.sh`, `gate.sh`, `mapear.sh` | **They are overwritten** when you open the project if they differ from the template. If you hand-edited them, commit first. |
| Directory without a git repo | Runs `git init -b master` and makes an initial commit with whatever is there (`git add -A`). |

In other words: your code and documents are safe; the three framework
scripts are treated as support code and renew themselves.

---

## 🌐 Model Catalog

Models come from `https://models.dev/api.json`, and the catalog is cached for
**7 days** (`modelos.CATALOGO_HORAS`). Switching provider triggers a new
lookup; the rest of the session runs off the cache, so refreshing the GUI
doesn't touch the network. If there's no network, the cached data is served
and the log says so.

---

## 🔧 Managed Project Requirements

Every project must have the following at its root:

```
my-project/
├── dedalo.sh    # loop bash (DEPRECATED; the GUI uses the python engine)
├── gate.sh          # checks (tests, lint, etc.) — bash, the only non-native piece
├── mapear.sh        # generates mapeo.txt
├── plan.md          # task list
├── lecciones.md     # project memory
├── CONTEXTO.md      # permanent context (what the project is about; injected to the agent and the reviewer)
├── incidencias.jsonl # failures/aborts/blocks (written by the engine)
└── progreso.log     # written by the engine (parsed by the GUI)
```

The loop engine is `dedalo/loop.py` (a port of the script, born in `W2`,
same log/observability). The GUI launches it with its own interpreter
(`python -m dedalo.loop`, or `--dedalo-loop` inside the packaged binary)
and no longer needs bash to start. The `dedalo.sh`, `gate.sh`, and `mapear.sh`
files are copied automatically when a project is created/opened from the
repo template (`dedalo/plantillas_data/`); `dedalo.sh`
is kept as a reference and for manual runs in a POSIX terminal.

---

## 🖥️ Compatibility

| OS | Status |
|----|--------|
| **Linux** | ✅ Works. It's the reference environment and where CI runs. |
| **macOS** | ⚠️ Partial. No longer requires GNU coreutils: `timeout` → `_timeout` (GNU/gtimeout/bash fallback returning 124) and `sed -i "0,/…/"` → `marcar_plan` (awk+cat, preserves permissions), with tests that prevent regressions. Remaining: the thermal sensor (`/sys/class/thermal`, Linux-only; degrades to "no data") and validation on a real Mac plus the `.dmg`. |
| **Windows** | ✅ Native GUI + loop + gate. Both the loop (`dedalo/loop.py`) and the gate (`dedalo/gate.py`) are Python engines that the GUI launches with its own interpreter: **Git Bash is no longer required** (PATH via `os.pathsep`, CLIs with `.exe`/`.cmd` suffix, suite in CI on `windows-latest`). The gate runs the `*.py` checks in `gate_checks/` and, if bash is available, prefers the equivalent `*.sh`. Bash remains only for the project map (`mapear.sh`) and the optional bash engine (`dedalo.sh`). |

What's already OS-independent: the line endings of `.sh` files
(`.gitattributes` forces `eol=lf`, so a `clone` on Windows with `autocrlf`
no longer breaks the shebang) and the numeric format (`LC_ALL=C`: with a
Spanish locale, `awk`/`printf` wrote `0,500000` and `metrics.jsonl` ended up
as invalid JSON).

`tests/test_portabilidad.py` is the guardrail: it fails if someone
reintroduces a non-portable construct, and a CI job on `macos-latest` runs that
lint against real BSD binutils. The allowlist of pending blocks
(Windows only; macOS's became empty after porting `timeout` and the plan
marking) is at the end of that file, with the reason for each.

### 📦 Downloads (Release)

Per-platform binaries are published to [Releases](https://github.com/BenReynor/dedalo/releases)
when a `v*` tag is pushed (Linux: `.tar.gz`/`.deb`/`.AppImage`; Windows: `.zip`
with `dedalo.exe`; macOS: `.dmg`). The builds are **not code-signed**:
when installing them, the OS will ask for explicit confirmation:

| OS | First launch |
|----|-----------------|
| **macOS** | `control + clic` on the app → *Open* (or `xattr -dr com.apple.quarantine /Applications/Dedalo.app`). |
| **Windows** | SmartScreen will warn you: *More info → Run anyway*. |
| **Linux** | No signature or sandbox; provenance = this repository (checksums are in the Release itself). |

Each Release ships its `SHA256SUMS*`; verify them with
`shasum -a 256 -c SHA256SUMS[-windows|-macos]`.

End-to-end validation (GUI plus a real loop run with an agent like
opencode) is documented step by step, per OS, in
[packaging/PRUEBA-MANUAL.md](packaging/PRUEBA-MANUAL.md).

#### 🏷️ Tags and Release Status

The current tags are `v2.0.0`, `v2.0.1` (pre-rename) and `v2.0.2` (already as
Dédalo). Every `v*` tag triggers `.github/workflows/release.yml`, which builds
and publishes a Release with the binaries for all three OSes. Worth knowing:

- Releases **v2.0.0 / v2.0.1 predate the rename**: their title is
  *"Autopiloto v2.0.x"* and their assets are named `autopiloto-gui-*`. **They
  still download** (they're working code from the pre-Dédalo era), but they
  **do not reflect the repo's current code**.
- From **v2.0.2** on, assets are generated as `dedalo-<version>-…` and the
  Release title is *"Dédalo"*.
- The *Full Changelog* links of the old Releases point to the old name
  `autopiloto-gui`; GitHub **redirects** renamed repos, so they don't 404.
- **Repository topics**: managed with
  `gh repo edit --add-topic <tema>` (independent of git tags).

---

## 🔧 Loop Environment Variables

The loop engine (`dedalo/loop.py`; `dedalo.sh` is its bash port,
deprecated by the GUI) is configured through environment variables (the GUI
fills them in from the Run form). The most useful ones:

| Variable | Description |
|----------|-------------|
| `AGENTE_TAREA` | Agent that implements: `opencode`\|`codex`\|`claude`\|`auto` (default). |
| `AGENTES_PREFERIDOS` | Preference order for `auto` and the reviewer. |
| `MODELO_TAREA` | Task model `provider/model` (opencode only). |
| `AGENTE_REVISOR` / `MODELO_REVISOR` | Agent and model for the dual gate (diff reviewer). |
| `AGENTE_JUEZ` | Judge agent for `criterio:` (default: the task's agent). |
| `REVISION_DUAL` | `1` enables the reviewer (default), `0` disables it. |
| `REVISION_MANUAL` | `1` pauses before each commit and waits for your approval in the GUI. |
| `TIMEOUT_REVISION_MANUAL` | Max seconds to wait for manual approval; on expiry the task is marked `[B]` and the loop continues (`0` = infinite). Default: `1800`. |
| `MAX_COSTO` | Budget in USD (`0` = no limit). |
| `COSTO_POR_ITER` | Estimated USD cost per task+review (default `0.50`). |
| `VOZ` | `1` enables alerts via `notify-send`/`spd-say`. |
| `NAVEGADOR` / `MODELO_NAVEGADOR` | Automatic context browser before each task. |
| `CRITERIO` | Extracted from the `criterio:` line under the task in `plan.md`. |
| `REVISION_APRUEBA_AGENTE` | `1` lets a pilot agent approve its own manual review (default `0`: an agent's `APPROVE` is ignored and the loop keeps waiting for a human). |
| `DEDALO_GATE_CONSENT` | `1` trusts the project's gate without prompting (for CI/scripts). Unset = ask once per project (interactive) or abort. |

> While waiting on `REVISION_MANUAL`, if the network goes down the loop aborts
> (rather than hanging); and if `TIMEOUT_REVISION_MANUAL` expires, the task is
> marked `[B]`.
>
> These variables (plus everything prefixed `DEDALO_`, `CLI_`, `LC_`,
> `OPENCODE_`, `CODEX_` and `CLAUDE_`) are always passed through. Any **other**
> variable you need in the engine/gate must be opted in with
> `DEDALO_ENTORNO_EXTRA` — see [Security](#-security).

### CLI Agents

`auto` (default) picks the first installed CLI according to `AGENTES_PREFERIDOS`
(`opencode codex claude`). The GUI only shows the agents it finds on the machine
and labels the detected one in the `auto` option, so it never offers one that
doesn't exist.

- `codex` is invoked with `codex exec --skip-git-repo-check`.
- `claude` is invoked with `claude -p --output-format text`.
- Only `opencode` accepts `MODELO_*` (`provider/model`); the GUI disables the
  selector for the other two, which take their model from their own account.
- If a CLI is installed but has no session (`Not logged in`, 401, invalid API
  key), the loop stops with a clear warning instead of marking tasks as failed
  over an authentication error.
- On startup, the GUI probes in the background whether each CLI has a session:
  those that don't show up as `claude (sin login)` and can't be selected.
  The probe is cached and doesn't block the UI; the refresh-models button
  triggers it again.
- For `opencode`, the session can't be determined unambiguously (it always
  responds 0 and its catalog models don't need credentials), so it's
  considered usable and labeled "session not verified".

---

## 🤖 MCP Server (Pilot Agent)

`dedalo.mcp_server` exposes project state and loop actions over **MCP on
stdio**, so a "pilot" agent (e.g. opencode or Claude Desktop) can read the
plan, incidents, and metrics, run the gate, start/stop the loop, and **resolve
the manual review** that would otherwise wait on a human.

Requires the optional `mcp` extra (not installed by default):

```bash
pip install -e ".[mcp]"

# Start the server (speaks JSON-RPC over stdin/stdout)
python -m dedalo.mcp_server
```

MCP client configuration (example for `opencode`/Claude Desktop):

```json
{
  "mcpServers": {
    "dedalo": {
      "command": "python",
      "args": ["-m", "dedalo.mcp_server"]
    }
  }
}
```

**Read tools:** `listar_proyectos`, `estado_proyecto`,
`leer_fichero`, `leer_incidencias`, `resumen_metricas`, `cola_log`,
`estado_agentes`, `listar_modelos`.

**Action tools:** `instalar_proyecto`, `correr_gate`, `iniciar_loop`
(background), `estado_loop`, `detener_loop`, `resolver_revision`.

**Shared state:** the MCP server, the GUI and the loop engine share a single
running-state registry (`dedalo/loops_estado.py`, `~/.config/dedalo/loops.json`)
and the engine holds an exclusive `flock` for its whole lifetime. So a loop
started by the MCP **shows up as running in the GUI** (and vice versa), the GUI
can stop it, and neither side can launch a duplicate for a project that already
has one running.

**Program context:** the server sends a curated manual in the
`instructions` field of `initialize` (what Dédalo is, how the loop works, the
files, and the usage flow), which the client shows the model as context without
having to read the code. The full manual is also available as the
`dedalo://manual` resource for on-demand reading.

**Resources:** `dedalo://{nombre}/{fichero}` with an allowlist (`plan.md`,
`lecciones.md`, `CONTEXTO.md`, `progreso.log`, `metrics.jsonl`,
`incidencias.jsonl`, `mapeo.txt`) and `dedalo://manual` (full manual).

The loop's manual review is resolved by writing to
`<project>/.dedalo_review/decision`: `resolver_revision(nombre, "APPROVE")`
or `REJECT <motivo>`. The pilot can approve the trivial and escalate the
questionable.

> Note: the PyInstaller binary is packaged `--windowed` (no console), so the
> stdio transport isn't available in the `.exe`; use the source code
> for the MCP server.

---

## 🔒 Security

Dédalo runs an autonomous agent inside **your** project: it can edit files, run
the project's gate and push branches. These are the guardrails it ships with.

### First-run gate consent

A project's gate runs the project's own checks (`gate_checks/*`), so pointing
Dédalo at an **untrusted repository** means executing that repository's code.
The first time you run a project, Dédalo asks for explicit consent:

- **Interactive** (terminal or GUI): you get a one-time prompt per project.
- **Non-interactive** (CI, scripts): it **aborts by default** (exit code `3`).
  Set `DEDALO_GATE_CONSENT=1` to trust without prompting.

The decision is persisted per project (hashed contents) in
`~/.config/dedalo/confianza.json` (`0o600`), **outside** the repo, so the repo
itself can never grant itself trust. Re-run with a changed gate to be asked
again.

### Manual review cannot be self-approved

When `REVISION_MANUAL=1`, the loop waits for a human `APPROVE`/`REJECT`. An
agent's approval is **ignored by default**, even if a pilot agent (MCP) writes
it. Set `REVISION_APRUEBA_AGENTE=1` to allow it, and the decision is still
audited in `progreso.log` with its origin (`gui`, `mcp` or `humano`).

The decision file `.dedalo_review/decision` is written with `0o600`. Its first
line stays `APPROVE` / `REJECT <reason>`; the second line carries the origin
marker (`# origen=gui|mcp`).

### Push safety

`--push` (or the GUI's push option) only ever pushes the work branch
(`dedalo/*`), **never** the base branch: if the resolved branch were `main`,
`master` or the configured base, the push is aborted. The target remote URL is
printed before pushing, and the GUI/CLI tells you which PR to open. Protect the
base branch on GitHub (branch protection rules) as the final backstop.

### Credentials

The gate can smoke-test a backend's endpoints. The bundled dev credentials
(`admin`/`admin123`) are applied **only when the target is `localhost`**; a
remote `SERVE_URL` with no `USUARIO`/`CLAVE` never receives them and prints a
warning instead.

### Engine environment (allowlist)

The engine does **not** inherit the full environment of the GUI/MCP process:
only an allowlist of variables crosses over, and from there into the gate and
the agent CLIs (`dedalo/loop_launch.py` → `filtrar_entorno`). This prevents a
prompt-injected agent from reading unrelated secrets you exported in your shell
(`AWS_*`, `DATABASE_URL`, tokens of other services…) with a plain `env`.

Allowed are the process/session basics (`PATH`, `HOME`, `LANG`, `TZ`…), the
XDG/display vars (keyring, `notify-send`), proxies and TLS, the git/SSH ones
(`SSH_AUTH_SOCK`, `GITHUB_TOKEN`, `GH_TOKEN`…), the engine overrides
(`MODELO_JUEZ`, `TIMEOUT_JUEZ`, `CRITERIO`, `SKIP_RUFF`) and, if present, the
agent CLIs' own API keys.

If a project's gate legitimately needs **other** variables (cloud creds, a real
`DATABASE_URL`…), opt in per launch with a space/comma-separated list:

```bash
DEDALO_ENTORNO_EXTRA="DATABASE_URL KUBECONFIG" dedalo
```

### Supply chain

- GitHub Actions are **pinned by commit SHA** (not by tag) to prevent a moved
  tag from running different code.
- Each Release carries **keyless build provenance** (Sigstore via GitHub OIDC):
  verify any asset with
  `gh attestation verify <file> --repo BenReynor/dedalo`.
- Releases also ship `SHA256SUMS*`; the binaries themselves are **not
  code-signed** (see [Downloads](#-downloads-release)).

---

## 🐛 Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Tests
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q

# Lint
python -m ruff check dedalo/ tests/

# Smoke test of the NON-editable install (the one that actually matters: with
# `pip install -e .` missing package-data files go unnoticed)
python -m pip wheel --no-deps -w /tmp/wheel . && python -m zipfile -l /tmp/wheel/*.whl

# Boot test (headless)
QT_QPA_PLATFORM=offscreen python -c "from dedalo.app import main; main()" &
```

`[project.optional-dependencies] dev` ships `pytest` and `ruff`, nothing else:
there's no type checker in the project, so don't configure mypy expecting it to
do anything.

---

## 📂 Key Structure

```
dedalo/
├── app.py              # Main window, orchestration, QProcess
├── paneles.py          # 8 panels + shared widgets (PipelineLoop, LoopPill, etc.)
├── temas.py            # Design system: 9 themes, QSS, colores_tema()
├── paneles_metricas.py # pyqtgraph dashboard
├── metricas.py         # progreso.log parsing → series
├── plan.py             # plan.md model
├── proyectos.py        # JSON persistence (~/.config/dedalo/)
├── loops_estado.py     # shared loop registry + flock, read by GUI/MCP/engine
├── loop_launch.py      # launch preparation (env + argv), shared GUI/MCP
├── mcp_server.py       # MCP server over stdio (tools + resources); extra `mcp`
├── plantillas.py       # project scaffolding
├── plantillas_data/    # .sh template scripts + initial memory
│   ├── dedalo.sh   # BASH loop (deprecated; reference/manual use)
│   ├── gate.sh         # bash gate (legacy/Unix; the loop uses gate.py)
│   ├── mapear.sh       # repo map
│   ├── plan.md         # initial memory (NOT overwritten)
│   ├── lecciones.md
│   ├── CONTEXTO.md     # project context (skeleton; NOT overwritten)
│   ├── .gitignore      # excludes the framework from the user's repo
│   └── gate_checks/    # 8 checks (.sh bash + .py portable port without bash)
├── loop.py             # Loop ENGINE in Python (native, W2):
│   │                   #   Config, signals, portable gate, agents, review,
│   │                   #   commit/merge/[B], integration, push
│   ├── gate.py         # portable gate orchestrator (.py checks; .sh via bash)
│   ├── gate_env.py     # gate environment (port of gate_checks/_env.sh)
│   ├── loop_agentes.py # launch/agents/reviewer + metrics
│   ├── loop_git.py     # git in Python
│   ├── loop_proceso.py # run_con_timeout/killpg (agent or gate)
│   ├── loop_args.py    # CLI parsing (--hasta/--push/--padre/--trabajo)
│   └── plan.py         # plan.md model
└── tests/              # plan, metrics, templates, webhooks, GUI, log/review, agents, net, sensor, process, config, portability, themes/selector, python loop/e2e
```

---

## 🐛 Known Open Bugs

Defects that were found and deliberately decided not to fix now, with the
reason and a code reference: [`docs/BUGS_CONOCIDOS.md`](docs/BUGS_CONOCIDOS.md).

---

## 📝 License

MIT — full text in [LICENSE](LICENSE).
