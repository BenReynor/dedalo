<img src="dedalo/icono.svg" width="88" align="right" alt="Dédalo icon">

# Dédalo

[![CI](https://github.com/BenReynor/dedalo/actions/workflows/ci.yml/badge.svg)](https://github.com/BenReynor/dedalo/actions/workflows/ci.yml)
[![Release](https://github.com/BenReynor/dedalo/actions/workflows/release.yml/badge.svg)](https://github.com/BenReynor/dedalo/actions/workflows/release.yml)
[![Latest release](https://img.shields.io/github/v/release/BenReynor/dedalo?sort=semver&color=blue)](https://github.com/BenReynor/dedalo/releases)
[![License: MIT](https://img.shields.io/github/license/BenReynor/dedalo?color=green)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20Windows%20experimental-informational)](#-compatibility)

**A desktop control panel that turns a Markdown task list into finished,
tested, reviewed commits — done by AI coding agents while you watch.**

You write `plan.md` (one task per line, each with the condition that proves it
is done). Dédalo hands the tasks one by one to an AI agent CLI (`claude` or
`opencode`), runs your project's tests and lint, has a second model review the
diff, judges the result against your condition, and only then commits. Failed
tasks are retried or marked blocked with a lesson, so the plan keeps moving.

| Plan board and editor | Run cockpit |
|---|---|
| ![Plan view](docs/capturas/plan.png) | ![Run view](docs/capturas/run.png) |

**Prefer a ready-made build?** Download it from
[Releases](https://github.com/BenReynor/dedalo/releases) (Linux `.deb`/`.AppImage`/`.tar.gz`,
Windows `.zip`), or follow the [Quick Start](#-quick-start) to run it from source.

> [!WARNING]
> **Windows is experimental and untested on a real PC.** Dédalo is developed and
> used on Linux. On Windows the test suite passes in CI and the packaged
> `dedalo.exe` boots, but nobody has yet run the installer, the tray or a real
> loop with an agent there. Use it at your own risk and
> [open an issue](https://github.com/BenReynor/dedalo/issues) with what breaks.
> See [Compatibility](#-compatibility).

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
- [How the Loop Works](#-how-the-loop-works)
- [Usage Tips](#-usage-tips)
- [Keyboard Shortcuts](#-keyboard-shortcuts)
- [Themes (9 curated)](#-themes-9-curated)
- [Persistent Settings](#-persistent-settings)
- [Notifications](#-notifications)
- [Adding a Project That Already Has Content](#-adding-a-project-that-already-has-content)
- [Model Catalog](#-model-catalog)
- [Managed Project Requirements](#-managed-project-requirements)
- [Uninstall / Remove a Project](#-uninstall--remove-a-project)
- [Compatibility and Downloads](#-compatibility)
- [Loop Environment Variables](#-loop-environment-variables)
- [MCP Server (Pilot Agent)](#-mcp-server-pilot-agent)
- [Security](#-security)
- [Development](#-development)
- [Key Structure](#-key-structure)
- [Troubleshooting](#-troubleshooting)
- [Known Open Bugs](#-known-open-bugs)

---

## 🚀 Quick Start

**Before you start:** Python 3.10+, `git`, and at least one agent CLI
(`opencode` or `claude`) installed and logged in. Nothing else is
required for the GUI or the loop; `bash` is only needed for a customized
`mapear.sh` and the optional legacy engine.

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
python3 -m venv .venv
source .venv/bin/activate

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

> **Repair or start fresh**: `rm -rf .venv && bash install.sh` rebuilds the
> environment from scratch in one command, keeping your projects, models and
> notification settings untouched.

---

## 🎯 What It Does

| Function | Description |
|---------|-------------|
| **Plan** | Kanban + Markdown editor for `plan.md` (tasks `- [ ]`, done `- [x]`, blocked `- [B]`). |
| **Lessons** | Editor for `lecciones.md` (project memory): injected into the agent before each task, and an entry is added when a task gets blocked. |
| **Progress** | Every completed task is committed together with its updated `plan.md` and `lecciones.md` — the branch tells the whole story, not just the code. |
| **Incidents** | Table for `incidencias.jsonl` (time, iteration, task, type, reason): failures, aborts, and blocks with their actual cause. |
| **Run** | Launches the loop: agent → gate → reviewer → commit. Parameters: deadline, iterations, base branch, max cost, dual/manual review. A **cockpit** at the top shows the run at a glance: status and clock, plan progress per `## FASE`, the current task and attempt, the phase pipeline (Plan → Agent → Gate → Reviewer → Commit; click a phase to see what it produced) and a timeline with an estimate of what is left. Loops started from MCP show up the same way. |
| **Logs** | Live output of `progreso.log` (loop) and `gate.sh`. Collapsible (⛶) with a permanently visible header. Auto-scroll. |
| **Map** | Viewer for `mapeo.txt`: modules, tests (with their test names), HTTP routes (Django, Flask, FastAPI, Express, actix/axum, Go) and CLI commands (argparse, click/typer). Generated in Python for any stack; **Regenerate** rebuilds it. A `mapear.sh` you customized still takes precedence. |
| **Metrics** | Real-time dashboard: tasks completed per iteration, cumulative estimated cost (amber), gate OK/FAIL, reviewer PASS/FAIL. Exports CSV. |
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

## 🔁 How the Loop Works

Dédalo turns a Markdown checklist into a delivery pipeline. Point it at a
project and it works through `plan.md` in order, one task at a time:

1. **Pick** the first pending task (`- [ ]`) and inject `CONTEXTO.md` plus
   `lecciones.md` into the agent's prompt.
2. **Implement** it with the selected agent (`opencode`, `claude` or
   `auto`), in its own task branch created from the run branch.
3. **Gate** the result: the project's own checks (`gate_checks/`) must pass.
4. **Review** the diff with a second agent and model (dual review, on by
   default), so a change that only "looks done" does not slip through.
5. **Commit** the task on its branch and fast-forward it into the run branch;
   `plan.md` and `lecciones.md` are committed with it, so the branch records
   what was done and what was learned.
6. **Continue** with the next task. At the end, if you set a work branch
   (`--trabajo`), the run branch is integrated into it; then, if push is
   enabled, it is published.

If the gate or the reviewer rejects the work, the loop retries the task. When
the attempts run out, it marks the task `[B]`, writes a lesson and an incident,
notifies you, and moves on instead of stalling the whole plan. With manual
review enabled, it pauses **before each commit** and waits for your
`APPROVE`/`REJECT`.

Two guardrails keep this predictable: the loop stops if there is no internet,
and it stops before starting a new iteration once the **estimated** budget
(`MAX_COSTO`) is exhausted.

### Plan format

```markdown
## Tasks (in dependency order)

- [ ] #1 Add the CSV export button to the metrics panel.
      criterio: tests/test_metrics.py::test_export_csv passes and fails without the change.
- [ ] #2 Document the export in README.
      criterio: README.md contains an "Export" paragraph; no code changes.
- [x] #3 Previous task, already done.
- [B] #4 Blocked task, waiting for a decision.
```

- One task per line, written as an outcome, not a vague area.
- The optional `criterio:` line is the **literal** pass/fail condition the
  judge checks (you can also put it inline after the task). Be concrete: files,
  tests, commands. The loop does not guess what "improve the UI" means.
- To make the agent use one of your skills (Claude Code or opencode), just name
  it in the task or its criterio, e.g. `Restyle the settings view using the
  estilo-retro skill`. The agent loads the skills the task names (and only
  those); the reviewer checks the diff against them.
- If the judge cannot give a verdict (agent error, no credits, timeout, no
  readable answer), the loop reruns **only the gate** twice (pause:
  `ESPERA_JUEZ`, default 10 s). If it still cannot judge, the loop **stops**
  (exit code 8, error notification) and leaves the task `[ ]`: an unverified
  criterio is never counted as done. A manual gate run (GUI button, MCP
  `correr_gate`) still only warns.
- If committing a task fails, the loop **stops** (exit code 9) without marking
  it done and leaves the task branch and its changes untouched, with git's error
  in progreso.log: work is never left loose for the next task to pick up.
- `[x]` is done, `[B]` is blocked. The loop writes both; you can edit the file
  by hand to retry or reorder work.
- Order is dependency order: the loop always takes the first pending task.

### Costs and budget

Dédalo does **not** read your provider's invoice. It estimates spend from the
values you configure: each implementation attempt adds `COSTO_POR_ITER`, and a
dual review adds half of it. `MAX_COSTO` is checked before starting a new
iteration; when the accumulated estimate reaches it, the loop stops cleanly.
Use it as a guardrail, and check your provider dashboard for the real numbers.

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
- **Set a spending cap.** `MAX_COSTO` caps the **estimated** spend (attempts ×
  `COSTO_POR_ITER`, in USD); it is a safety rail, not your provider's invoice.
  Set it before leaving the loop unattended.
- **JSON fichas are opt-in.** The Run tab has a checkbox to write one
  `.dedalo/fichas/*.json` per accepted task. It uses an extra agent call, so it
  is off by default; a failure never blocks the commit.
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

| Theme (UI label) | Style |
|------|--------|
| **Oscuro** | Classic slate/blue dark |
| **Claro** | Classic slate/blue light |
| **Hacker** | Terminal green |
| **Cyberpunk** | Fuchsia/purple neon on graphite |
| **Zinc/Amber Oscuro** | Amber cockpit (default) |
| **Gray/Red Oscuro** | Red |
| **Stone/Emerald Claro** | Warm light green |
| **Zinc/Sky Claro** | Light blue |
| **Slate/Teal Oscuro** | Deep teal |

Live switching from the "Theme" selector in the top bar. Theme names are fixed
labels; the rest of the interface follows the language selector.

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

## 🔔 Notifications

A loop is only useful if you can walk away from it. Dédalo pings you on
**Telegram, Discord or WhatsApp** at the moments that matter — whether the
loop was launched from the panel, from an MCP pilot agent or from the Python
engine in a terminal.

| Event | What you get |
|---|---|
| Loop started (panel) | Project and selected models. |
| Loop started (MCP / CLI) | Project, selected models **and** the origin. |
| Task completed | Task name, iteration, branch and commit. |
| Task blocked | The task that needs your attention. |
| Loop finished | Tasks done/total, estimated cost and duration. |
| Tokens/quota exhausted | The loop stopped because the model ran dry. |
| Critical error | The exact reason the run aborted. |

### Set it up

Open **Security → Notifications** and fill in only the channel you want:

- **Telegram:** `Bot Token` from [@BotFather](https://t.me/BotFather) and the
  numeric `Chat ID` (send the bot a message first, then read it from
  `https://api.telegram.org/bot<token>/getUpdates`).
- **Discord:** the channel's webhook URL (Server Settings → Integrations).
- **WhatsApp:** Meta Cloud API URL, access token, phone number ID and the
  destination number in international format.

Click **🧪 Test** for that channel, then enable it. The seven switches under
**Events to notify** decide what is sent; missing switches default to enabled.
The panel edits the active project: values are saved as global defaults and as
that project's own configuration, so one project can ping your phone while
another stays silent.

- **No duplicates.** The panel and the engine agree on who reports what, so a
  GUI run never sends every event twice.
- **No silent failures.** If a channel rejects a message (bad token, wrong chat
  id), the reason lands in `progreso.log` instead of being swallowed.
- **Stored safely.** Tokens live in `~/.config/dedalo/proyectos.json`, created
  with `0600` permissions (user only).

Notifications are **best effort**: a broken webhook never stops the loop.

---

## 📂 Adding a Project That Already Has Content

The folder picker accepts any existing directory, not just an empty one.
It's worth knowing what the app touches in each case:

| | What it does |
|---|---|
| Missing files (`plan.md`, `lecciones.md`, `CONTEXTO.md`, `.gitignore`, scripts) | Copies them from the template. **Never overwrites an existing file.** |
| `plan.md`, `lecciones.md`, `CONTEXTO.md`, `.dedalo/scripts/gate_checks/*` | Your own content. Never compared, never overwritten. |
| `dedalo.sh`, `gate.sh`, `mapear.sh` (in `.dedalo/scripts/`) | **They are overwritten** when you open the project if they differ from the template. If you hand-edited them, commit first. |
| A project installed by an older version | Its framework files at the root move into `.dedalo/` once, automatically. |
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
├── plan.md            # task list
├── lecciones.md       # project memory
├── CONTEXTO.md        # permanent context (injected to the agent and the reviewer)
└── .dedalo/           # framework code + run state (gitignored)
    ├── scripts/
    │   ├── dedalo.sh  # bash engine (DEPRECATED; the GUI uses the python engine)
    │   ├── gate.sh    # checks (tests, lint, etc.)
    │   ├── mapear.sh  # generates mapeo.txt
    │   └── gate_checks/ # YOUR checks: never overwritten
    ├── estado/
    │   ├── progreso.log     # written by the engine (parsed by the GUI)
    │   ├── metrics.jsonl
    │   ├── incidencias.jsonl
    │   └── mapeo.txt
    └── review/              # pending manual decision (APPROVE/REJECT)
```

Two different kinds of files live here:

- **Yours, tracked:** `plan.md`, `lecciones.md`, `CONTEXTO.md` and your source
  code. Dédalo creates the memory files if missing and never overwrites them;
  commit them with the rest of your work.
- **Yours, local:** `gate_checks/`. Dédalo never overwrites your checks, but
  they live under the gitignored `.dedalo/`, so they are not committed by
  default. Keep a copy outside `.dedalo/` (or force-add them) if you need them
  versioned.
- **Framework:** the framework scripts (`dedalo.sh`, `gate.sh`, `mapear.sh`),
  their portable Python ports and everything under `.dedalo/estado/` and
  `.dedalo/review/`. Missing framework files are recreated, and the scripts
  are refreshed from the template (with a timestamped backup) when they differ.
  `.gitignore` keeps all of this out of your repository.

In short: the app repairs its own scaffolding, but it does **not** regenerate
your gate checks or your project memory.

**Project virtualenv.** If the project has a `.venv/` (or `venv/`), the loop
puts its `bin/` (`Scripts\` on Windows) first in `PATH` and sets
`VIRTUAL_ENV` for the agent, the gate and the judge. Gate templates and the
agent's allowed commands call `pytest`, `ruff` or `python` by name, so they run
with the project's dependencies instead of the system ones. Create it however
you like (e.g. `uv venv` + `uv pip install -r requirements.txt`).

The loop engine is `dedalo/loop.py` (a port of the script, born in `W2`,
same log/observability). The GUI launches it with its own interpreter
(`python -m dedalo.loop`, or `--dedalo-loop` inside the packaged binary)
and no longer needs bash to start. The `dedalo.sh`, `gate.sh`, and `mapear.sh`
files are copied automatically when a project is created/opened from the
repo template (`dedalo/plantillas_data/`); `dedalo.sh`
is kept as a reference and for manual runs in a POSIX terminal.

---

## 🛠️ Gate Templates (plantillas de gate)

Each project uses **one or more gate templates**, chosen in the **Run** panel
(or via MCP `instalar_proyecto`) and changeable at any time mid-project — each is a set of portable Python checks for a
language/stack. The templates live in `dedalo/plantillas_data/plantillas/`
and are installed into your project's `.dedalo/scripts/gate_checks/` with a
language suffix so several stacks coexist without collisions
(`03_test_rust.py`, `03_test_go.py`, etc.).

| Template | Detects | Checks (run if tool present) |
|---|---|---|
| `web` | `index.html` | HTML5 structure, CSS custom properties + responsive, JS theme toggle + syntax |
| `python` | `pyproject.toml` / `requirements.txt` | `ruff check .`, `pytest -q` (if `tests/`) |
| `node` | `package.json` | `package.json` validity, `npm run lint`, `npm test`, `tsc --noEmit` (when `tsconfig.json` exists) |
| `rust` | `Cargo.toml` (or `src-tauri/Cargo.toml` for Tauri apps) | `cargo fmt --check`, `cargo check`, `cargo test` |
| `go` | `go.mod` | `gofmt -l .`, `go vet ./...`, `go test ./...` |
| `java` | `pom.xml` / `build.gradle` | `mvn -q -B -DskipTests compile` / `gradle compileJava`, `mvn test` / `gradle test` |
| `kotlin` | `build.gradle.kts` / `*.kt` | `gradle compileKotlin`, `gradle test` |
| `csharp` | `*.sln` / `*.csproj` | `dotnet build`, `dotnet test` |
| `cpp` | `CMakeLists.txt` / C/C++ sources | `clang-format --dry-run --Werror`, CMake/make build, `ctest` / `make test` |
| `shell` | `*.sh` | `bash -n` syntax, `shellcheck -x` |
| `ruby` | `Gemfile` | `rubocop` (via `bundle exec`), `rspec` / `rake test` |
| `php` | `composer.json` | `php -l` on each `.php`, `phpunit` (vendor/bin) |
| `swift` | `Package.swift` | `swift build`, `swift test` |
| `dart` | `pubspec.yaml` | `dart analyze`, `dart test` |
| `generic` | any known marker | auto-detects stack and runs standard commands (use **alone**, not combined) |

**How it works:**
- GUI (**Run** panel → *Gate templates*):
  - type a comma-separated list or pick one of the last 5 used for that project;
  - **Auto-detect** reads the project files (table above) and applies the matching templates (falls back to `python` if nothing matches);
  - **Edit templates…** opens a checklist.
  Switching stacks removes the old stack's checks **only if you never edited them**.
- New projects get no dialog: they start with the default Python/backend checks until you pick templates.
- MCP: `instalar_proyecto(ruta, plantilla="rust,go")` — comma/space separated, or `plantilla="auto"` to detect.
- The selection is persisted in `.dedalo/plantilla` (one per line). Re-opening the project keeps it.
- Checks missing their tool (`cargo`, `dotnet`, `swift`, etc.) are **skipped with a warning**, not failed — so a multi-stack gate passes on a machine that only has some toolchains.
- Failures are reported per language (`[GATE] ✗ rust: 03_test_rust.py falló`), and **all checks run even if one fails** — you get the full picture.
- Your own checks go in `gate_checks/99_custom.py` (or `NN_mi_check.py`); they are never overwritten.

---

## 🧹 Uninstall / Remove a Project

**Remove a project from the list.** Stop its loop first, then use *Remove
project*. This is **destructive and irreversible** for the Dédalo files: it
deletes `.dedalo/` (scripts, checks and run state), `plan.md`, `lecciones.md`
and `CONTEXTO.md`. Your application code is never touched. Commit or copy the
memory files first if you may want them later. Removing an *orphan* entry (a
registry entry whose folder no longer exists) only removes the entry.

**Uninstall the app.** The installer creates a launcher, a desktop shortcut and
an icon. Removing those and the virtual environment is enough; your projects
stay where they are:

```bash
# From the Dédalo checkout
rm -rf .venv
rm -f ~/.local/bin/dedalo
rm -f ~/Escritorio/dedalo.desktop ~/Desktop/dedalo.desktop
rm -f ~/.local/share/icons/dedalo.svg
```

Your settings live outside the checkout, in `~/.config/dedalo/`. Delete that
folder only if you also want to forget the project list, trusted gates, webhook
tokens and window settings.

---

## 🖥️ Compatibility

> **Dédalo works on Linux.** Windows support is **experimental**: the full
> suite runs in CI on Windows (headless) and the release workflow builds and
> boots the packaged app, but it has not been used day to day on a real Windows
> machine. Report whatever breaks.

| OS | Status |
|----|--------|
| **Linux** | ✅ **Supported.** Reference environment: daily use plus the CI suite. |
| **Windows** | 🧪 **Experimental.** CI runs the full suite on `windows-latest` with real Git Bash. The GUI, the loop (`dedalo/loop.py`) and the gate (`dedalo/gate.py`) are native Python engines launched with the app's own interpreter, so **Git Bash is not required** (`os.pathsep`, `.exe`/`.cmd` suffixes). **Not tested on a real PC:** installer and shortcut, tray, and a real loop with opencode or claude. Bash (Git Bash or WSL) is only needed for the optional bash engine (`dedalo.sh`) or a customized `mapear.sh`; the default project map is generated in Python. |

What's already OS-independent: the line endings of `.sh` files
(`.gitattributes` forces `eol=lf`, so a `clone` on Windows with `autocrlf`
no longer breaks the shebang) and the numeric format (`LC_ALL=C`: with a
Spanish locale, `awk`/`printf` wrote `0,500000` and `metrics.jsonl` ended up
as invalid JSON).

`tests/test_portabilidad.py` is the guardrail: it fails if someone
reintroduces a non-portable construct. The allowlist of pending Windows blocks
is at the end of that file, with the reason for each.

### 📦 Downloads (Release)

Per-platform binaries are published to [Releases](https://github.com/BenReynor/dedalo/releases)
when a `v*` tag is pushed (Linux: `.tar.gz`/`.deb`/`.AppImage`; Windows, experimental: `.zip`
with `dedalo.exe`). The builds are **not code-signed**:
when installing them, the OS will ask for explicit confirmation:

| OS | First launch |
|----|-----------------|
| **Windows** | SmartScreen will warn you: *More info → Run anyway*. |
| **Linux** | No signature or sandbox; provenance = this repository (checksums are in the Release itself). |

Each Release ships its `SHA256SUMS*`; verify them with
`sha256sum -c SHA256SUMS[-windows]`.

End-to-end validation (GUI plus a real loop run with an agent like
opencode) is documented step by step, per OS, in
[packaging/PRUEBA-MANUAL.md](packaging/PRUEBA-MANUAL.md).

#### 🏷️ Tags and Release Status

The latest release is `v2.1.0`; the previous tags are `v2.0.0`, `v2.0.1`
(pre-rename) and `v2.0.2` (already as Dédalo). Every `v*` tag triggers
`.github/workflows/release.yml`, which builds and publishes a Release with the
binaries for all three OSes. Worth knowing:

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

The loop engine (`dedalo/loop.py`, a Python port of the original `dedalo.sh`,
which the GUI no longer uses) is configured through environment variables (the
GUI fills them in from the Run form). The most useful ones:

| Variable | Description |
|----------|-------------|
| `AGENTE_TAREA` | Agent that implements: `opencode`\|`claude`\|`auto` (default). |
| `AGENTES_PREFERIDOS` | Preference order for `auto` and the reviewer. |
| `MODELO_TAREA` | Task model `provider/model` (opencode only). |
| `AGENTE_REVISOR` / `MODELO_REVISOR` | Agent and model for the dual gate (diff reviewer). |
| `AGENTE_JUEZ` | Judge agent for `criterio:` (default: the task's agent). |
| `REVISION_DUAL` | `1` enables the reviewer (default), `0` disables it. |
| `REVISION_MANUAL` | `1` pauses before each commit and waits for your approval in the GUI. |
| `TIMEOUT_REVISION_MANUAL` | Max seconds to wait for manual approval; on expiry the task is marked `[B]` and the loop continues (`0` = infinite). Default: `1800`. |
| `MAX_COSTO` | Estimated budget in USD, checked before each iteration (`0` = no limit). |
| `COSTO_POR_ITER` | Estimated USD added per attempt (default `0.50`); dual review adds half. |
| `VOZ` | `1` enables alerts via `notify-send`/`spd-say`. |
| `NAVEGADOR` / `MODELO_NAVEGADOR` | Automatic context browser before each task. |
| `CRITERIO` | Extracted from the `criterio:` line under the task in `plan.md`. |
| `REVISION_APRUEBA_AGENTE` | `1` lets a pilot agent approve its own manual review (default `0`: an agent's `APPROVE` is ignored and the loop keeps waiting for a human). |
| `FICHA_ACTIVA` | `1` writes a JSON ficha per accepted task in `.dedalo/fichas/` (default `0`: off, no extra tokens). |
| `AGENTE_FICHA` / `MODELO_FICHA` | Agent/model for the ficha observer (`auto` = same as the task agent). |
| `TIMEOUT_FICHA` | Seconds for the observer call (default `120`). |
| `FICHAS_DIR` | Overrides `.dedalo/fichas` (relative to the project or absolute). |
| `FICHA_MAX_DIFF` | Max diff characters stored in the ficha (default `12000`). |
| `FICHA_MAX_SALIDA` | Max characters of gate/agent output (default `20000`). |
| `FICHA_DIFF_COMPLETO` | `1` stores the full diff (default `0`). |
| `DEDALO_GATE_CONSENT` | `1` trusts the project's gate without prompting (for CI/scripts). Unset = ask once per project (interactive) or abort. |

> While waiting on `REVISION_MANUAL`, if the network goes down the loop aborts
> (rather than hanging); and if `TIMEOUT_REVISION_MANUAL` expires, the task is
> marked `[B]`.
>
> Fichas use the canonical format in
> `dedalo/plantillas_data/skills/ficha-dedalo/SKILL.md`; the engine injects it
> into the observer prompt, so it works with opencode and claude.
>
> These variables (plus everything prefixed `DEDALO_`, `CLI_`, `LC_`,
> `OPENCODE_` and `CLAUDE_`) are always passed through. Any **other**
> variable you need in the engine/gate must be opted in with
> `DEDALO_ENTORNO_EXTRA` — see [Security](#-security).

### CLI Agents

`auto` (default) picks the first installed CLI according to `AGENTES_PREFERIDOS`
(`opencode claude`). The GUI only shows the agents it finds on the machine
and labels the detected one in the `auto` option, so it never offers one that
doesn't exist.

- `opencode` is invoked with `opencode run --agent <agent> --dir <project>`.
  Dédalo defines its own agents through `OPENCODE_CONFIG_CONTENT` (merged over
  your config) and disables every MCP server of yours in those runs, the same
  isolation as claude's `--strict-mcp-config`:
  - **task agent** (`dedalo-tarea`): may edit and run commands, never `git`.
  - **reviewer, judge, navigator and ficha** (`dedalo-lectura`): read-only
    (no edit, write, bash, subagents or web).
  - `OPENCODE_AGENT_TAREA`, `OPENCODE_AGENT_LECTURA`, `OPENCODE_AGENT_NAV` and
    `OPENCODE_AGENT_JUEZ` override them.
- `claude` is invoked with `claude -p --output-format text --strict-mcp-config`
  (it never loads your MCP servers) and receives the prompt through stdin.
  Permissions depend on the role:
  - **task agent:** may edit files (`acceptEdits`) and run the commands of the
    project's gate templates without asking (python → `pytest`, `python`,
    `ruff`; node → `npm`, `node`; rust → `cargo`…). Never `git`: the loop owns
    branches and commits. `CLAUDE_FLAGS` adds extra flags to this role only.
  - **reviewer, judge (`98_criterio`), navigator and ficha:** read-only
    (`Edit`, `Write`, `Bash`… disallowed).
- `opencode` accepts any `provider/model`; `claude` accepts Anthropic models
  (`anthropic/haiku`, `anthropic/sonnet`, `anthropic/opus` or a full
  `claude-*` id). Picking `claude` in the GUI switches a non-Claude model to
  `anthropic/haiku`, the cheapest.
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
stdio**, so a "pilot" agent (opencode, Claude Desktop, or any MCP client) can
read the plan, incidents and metrics, run the gate, start and stop the loop,
and **answer the manual review** that would otherwise wait on a human (subject
to the approval policy). It is the same Dédalo you see in the panel, driven
from the outside.

The complete reference — every tool, its parameters, return shape and worked
examples — is in **[docs/MCP.md](docs/MCP.md)**.

### Install and launch

`install.sh` already installs the `mcp` extra. If you installed manually, add it:

```bash
pip install -e ".[mcp]"
# Start the server (JSON-RPC over stdin/stdout)
.venv/bin/python -m dedalo.mcp_server
```

### Client configuration

Use the **absolute path** to the virtual environment's Python, or the client may
pick a different interpreter that cannot import `dedalo`. For opencode, add this
to your `opencode.json` (global or project):

```json
{
  "mcp": {
    "dedalo": {
      "type": "local",
      "command": ["/absolute/path/to/dedalo/.venv/bin/python", "-m", "dedalo.mcp_server"],
      "enabled": true
    }
  }
}
```

<details>
<summary>Claude Desktop configuration</summary>

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

Config file: `~/.config/Claude/claude_desktop_config.json` on Linux,
`%APPDATA%\Claude\claude_desktop_config.json` on Windows.
</details>

**Restart the client after updating Dédalo** (code or `.venv`): a long-running
MCP process keeps the modules it imported at startup. The loop engine is spawned
fresh, so engine fixes apply without restarting the client.

### What it exposes

- **Read (12):** `listar_proyectos`, `estado_proyecto`, `leer_fichero`,
  `leer_plan`, `leer_lecciones`, `leer_contexto`, `leer_incidencias`,
  `resumen_metricas`, `cola_log`, `estado_agentes`, `listar_modelos`,
  `listar_plantillas`.
- **Act (7):** `instalar_proyecto`, `confiar_gate`, `correr_gate`,
  `iniciar_loop` (background), `estado_loop`, `detener_loop`,
  `resolver_revision`. `confiar_gate` approves a repo's `gate_checks` (the same
  consent the GUI asks for) before a headless loop can run its gate.
  `instalar_proyecto` refuses a name already registered at another path
  (unless `sobrescribir=True`) and never installs into `/`, `$HOME` itself,
  system trees (`/etc`, `/usr`, `/var/lib`...) or dotfile trees (`~/.ssh`,
  `~/.config`...), so a prompt-injected agent cannot hijack a project.

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
`incidencias.jsonl`, `mapeo.txt`) and `dedalo://manual` (full manual). The four
run artifacts resolve under `<project>/.dedalo/estado/`.

**Manual review:** `resolver_revision` writes
`<project>/.dedalo/review/decision` with an `# origen=mcp` marker. An agent's
`APPROVE` is **ignored by default**; set `REVISION_APRUEBA_AGENTE=1` to let a
pilot approve (see [Security](#manual-review-cannot-be-self-approved)).

> The PyInstaller binary is packaged `--windowed` (no console), so the stdio
> transport is not available in the `.exe`; use the source code for MCP.

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

The decision file `.dedalo/review/decision` is written with `0o600`. Its first
line stays `APPROVE` / `REJECT <reason>`; the second line carries the origin
marker (`# origen=gui|mcp`).

### Push safety

`--push` (or the GUI's push option) pushes the **work branch** — the run branch
`dedalo/*` by default, or the branch you set with `--trabajo` — and **never** the
base branch. If the resolved branch is `main`, `master` or the configured base,
the push is aborted. The target remote URL is printed before pushing, and the
GUI/CLI tells you which PR to open. Protect the base branch on GitHub (branch
protection rules) as the final backstop.

### Credentials

The gate can smoke-test a backend's endpoints. The bundled dev credentials
(`admin`/`admin123`) are applied **only when the target is `localhost`**; a
remote `SERVE_URL` with no `USUARIO`/`CLAVE` never receives them and prints a
warning instead.

### Backend port

The bundled backend check **never kills a process by port**. If something
already answers at `SERVE_URL`, it reuses that backend with a warning. If the
port is occupied but does not answer HTTP, the gate fails and shows the PID(s),
asking you to free the port or change `SERVE_URL`. A backend started by the
check is stopped with its own process group (`TERM`, then `KILL`), so it cannot
leave a child holding the port for the next iteration.

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

`[project.optional-dependencies] dev` ships `pytest`, `ruff` and `mcp` (so the
MCP tests run instead of being skipped). There is no type checker in the
project, so don't configure mypy expecting it to do anything.

---

## 📂 Key Structure

```
dedalo/
├── app.py              # Main window, orchestration, QProcess
├── carga.py            # startup splash; probes agent sessions in parallel
├── cabina.py           # Run cockpit (status, plan progress, phase pipeline, timeline)
├── estado_loop.py      # live run state the cockpit reads (estado_loop.json)
├── modelos.py          # agent CLIs: installed, session probe, model catalog
├── selector_modelo.py  # provider/model picker widget
├── paneles.py          # 9 sidebar panels + review panel and shared widgets
├── paneles_webhooks.py # Security → Notifications tab
├── temas.py            # Design system: 9 themes, QSS, colores_tema()
├── paneles_metricas.py # pyqtgraph dashboard
├── metricas.py         # progreso.log parsing → series
├── plan.py             # plan.md model
├── proyectos.py        # JSON persistence (~/.config/dedalo/)
├── notificaciones.py   # notification events, templates and per-project config
├── webhooks.py         # Telegram / Discord / WhatsApp delivery
├── consentimiento.py   # first-run gate consent (hashes + trust store)
├── rutas.py            # .dedalo/ layout resolution and legacy migration
├── i18n.py             # GUI translation catalog (en/es)
├── loops_estado.py     # shared loop registry + flock, read by GUI/MCP/engine
├── loop_launch.py      # launch preparation (env + argv), shared GUI/MCP
├── mcp_server.py       # MCP server over stdio (tools + resources); extra `mcp`
├── plantillas.py       # project scaffolding
├── plantillas_data/    # .sh template scripts + initial memory
│   ├── dedalo.sh       # BASH loop (deprecated; reference/manual use)
│   ├── gate.sh         # bash gate (legacy/Unix; the loop uses gate.py)
│   ├── mapear.sh       # repo map
│   ├── plan.md         # initial memory (NOT overwritten)
│   ├── lecciones.md
│   ├── CONTEXTO.md     # project context (skeleton; NOT overwritten)
│   ├── .gitignore      # excludes the framework from the user's repo
│   └── gate_checks/    # 7 checks (.sh bash + .py portable port) + _env.sh
├── loop.py             # Loop ENGINE in Python (native, W2):
│   │                   #   Config, signals, portable gate, agents, review,
│   │                   #   commit/merge/[B], integration, push
│   ├── gate.py         # portable gate orchestrator (.py checks; .sh via bash)
│   ├── gate_env.py     # gate environment (port of gate_checks/_env.sh)
│   ├── loop_agentes.py # launch/agents/reviewer + metrics
│   ├── loop_git.py     # git in Python
│   ├── loop_proceso.py # run_con_timeout/killpg (agent or gate)
│   ├── loop_util.py    # shared loop helpers (log/metrics utilities)
│   └── loop_args.py    # CLI parsing (--hasta/--push/--padre/--trabajo)
└── tests/              # plan, metrics, templates, webhooks, GUI, log/review, agents, net, sensor, process, config, portability, themes/selector, python loop/e2e
```

---

## 🩺 Troubleshooting

| Symptom | What to do |
|---|---|
| “no agent CLI with a session” | Log in to at least one CLI (`opencode` or `claude`) or pick another one in the Run panel. The probe is cached; refresh models to re-check. |
| The gate is red | Open **Logs** and read the gate pane for the failing check; run `bash .dedalo/scripts/gate.sh` (or the portable gate) by hand and fix the project. The loop will not commit red work. |
| “gate_checks sin consentimiento” / exit code `3` | Approve the gate once in the GUI, call `confiar_gate` from MCP, or set `DEDALO_GATE_CONSENT=1` for an unattended run. |
| Manual review never finishes | Send `APPROVE`/`REJECT` from the Revision panel. An agent's approval is ignored unless `REVISION_APRUEBA_AGENTE=1`; on timeout the task is marked `[B]`. |
| The loop will not start | It is already running for that project, there is no internet, or no agent has a session. Check the loop status in the status bar and `progreso.log`. |
| MCP server does not appear in the client | Use the absolute `.venv/bin/python` path, the `mcp` key (not `mcpServers`) for opencode, and restart the client. |
| MCP tools still behave like the old version | Restart the MCP client; it caches imported modules. The engine itself is spawned fresh. |
| The project map is empty | Click **Map → Regenerate** (the map is generated in Python for any stack; a customized `mapear.sh` takes precedence and needs `bash`). |
| Notifications are silent | Use each channel's **🧪 Test**, enable the channel, check the seven event switches, then read the reason in `progreso.log`. |
| The loop stopped with exit code `5` | The provider's tokens/quota ran out (also logged as an incident and notified), or another loop is already running for that project. Wait for the quota to reset or stop the other loop, then relaunch: the task stays `[ ]`. |
| Opening the panel takes a few seconds | The loading screen shows why: Dédalo checks in parallel which agent CLIs have a session (the slowest one, usually `claude`, sets the wait). |
| `proyectos.json` is corrupt | The app refuses to start and offers to exit (fix by hand) or start fresh, keeping a `.corrupto` copy. |
| I lost `plan.md` / lessons | Removing a project deletes its Dédalo files. Restore them from git if they were committed; otherwise use your backup. |

---

## 🐛 Known Open Bugs

Defects that were found and deliberately decided not to fix now, with the
reason and a code reference: [`docs/BUGS_CONOCIDOS.md`](docs/BUGS_CONOCIDOS.md).

---

## 📝 License

MIT — full text in [LICENSE](LICENSE).
