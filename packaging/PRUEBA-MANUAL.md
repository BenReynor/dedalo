# Manual test of a published binary (v2.1.0)

A ~15-minute checklist per OS to validate a binary from the
[GitHub Release](https://github.com/BenReynor/dedalo/releases) end to end.
The recommended test agent is **opencode** (CLI-agnostic; on Windows it is
`.exe`/`.cmd`). The binaries are **not code-signed**: see the first-launch
section for each OS.

Engine exit codes (`--dedalo-loop`): `0` = loop completed,
`2` = agent unavailable, `3` = gate not trusted (no consent), `4` = no
internet, `7` = internal error.

---

## 0. Common setup

1. A test project with a minimal plan:

   ```markdown
   # Plan

   - [ ] t1: crear hola.txt
         criterio: existe hola.txt
   ```

2. Have **opencode installed and visible on the PATH** of the shell it will be
   launched from (in the GUI, the PATH the app inherits from the desktop).
   Check with `opencode --version`.

3. (Optional) Verify the build provenance of an asset, if `gh` is available:
   `gh attestation verify dedalo-*.AppImage --repo BenReynor/dedalo`.

4. **MCP** is source-only: the packaged binary is windowed and cannot serve
   stdio, so validate it from a checkout with
   `.venv/bin/python -m dedalo.mcp_server` (see `docs/MCP.md`).

5. **Gate port safety** (projects with a backend check): if something already
   answers at `SERVE_URL`, the gate reuses it. If the port is occupied by a
   process that does not answer HTTP, the gate fails with the PID and **must
   leave that process alive**; it never kills by port.

> **First run per project**: Dédalo asks once for consent to trust and run the
> project's gate (interactive prompt, or the GUI dialog). If you decline, or run
> non-interactively without `DEDALO_GATE_CONSENT=1`, the loop aborts with
> rc `3`. The trust decision is remembered in
> `~/.config/dedalo/confianza.json`.

---

## 1. Linux (`.AppImage` / `.deb` / `.tar.gz`)

1. Verify the checksum: `sha256sum -c SHA256SUMS` (next to the files in the
   Release).
2. AppImage: `chmod +x dedalo-*.AppImage && ./dedalo-*.AppImage`.
   .deb: `sudo apt install ./dedalo_*.deb`.
3. **GUI**: the panel launches; add a project with the `plan.md` from step 0;
   switch themes and confirm it persists after a restart.
4. **Engine**: launch the loop from the panel → `progreso.log` advances, the gate
   runs, and `t1` finishes as `[x]` (`hola.txt` exists).
5. **CLI**: `./dedalo-*.AppImage --dedalo-loop plan.md`
   (in the project's cwd): with opencode on PATH → rc `0`; take it off the
   PATH → rc `2` and `ABORTADO: agente no disponible (opencode)` in the
   `progreso.log` queue.
6. **Thermal sensor**: on machines with `/sys/class/thermal` the reading is shown;
   without it, "no data" (expected degradation).

## 2. Windows (`dedalo-2.1.0-win64.zip`)

1. Verify the checksum from PowerShell:
   `Get-FileHash dedalo-2.1.0-win64.zip -Algorithm SHA256`
   and compare it with `SHA256SUMS-windows`.
2. Unzip → `dedalo\dedalo.exe`.
3. **First launch**: SmartScreen → *More info* → *Run anyway*.
   The panel opens.
4. **GUI**: add a project with the `plan.md` from step 0; theme persists.
5. **Gate**: runs the native Python checks (`03_backend.py`, etc.); **Git Bash is
   not required**. `t1` must pass the criterion and `progreso.log` must reflect it.
   Git for Windows is only needed for the optional project map (`mapear.sh`) and
   the legacy bash engine.
6. **CLI** (PowerShell, in the project's cwd):
   `.\dedalo\dedalo.exe --dedalo-loop plan.md`
   → rc `0` with opencode on PATH; rc `2` without it.

## 3. macOS (`dedalo-2.1.0-macos-arm64.dmg`)

> **Apple Silicon (arm64)** only. Binary unsigned and unnotarized.

1. Verify the checksum: `shasum -a 256 -c SHA256SUMS-macos`.
2. Open the dmg → drag **Dedalo.app** to Applications.
3. **First launch**: `control + clic` on the app → *Open*. Alternative:
   `xattr -dr com.apple.quarantine /Applications/Dedalo.app`.
4. **GUI + engine**: same as Linux; the **thermal sensor degrades to "no data"**
   (there is no `/sys/class/thermal` on macOS; expected behavior).
5. **CLI**: `"/Applications/Dedalo.app/Contents/MacOS/dedalo" \
   --dedalo-loop plan.md` → rc `0` with opencode on PATH; rc `2` without it.

---

## What fails and what to do

| Symptom | Likely cause |
|---|---|
| SmartScreen / Gatekeeper blocks it | Unsigned binary: use the "first launch" steps. |
| Loop blocks the task (Windows) | A gate check failed; read the gate pane. Git Bash is only needed for the project map/legacy bash engine. |
| Unexpected rc `2` | The agent is not on the PATH the app inherits: use `CLI_OPENCODE` or fix the PATH. |
| rc `4` | No network at the time of the run. |
| rc `3` | The project's gate was not trusted: accept the prompt or set `DEDALO_GATE_CONSENT=1`. |
| Temperature "no data" | Expected on macOS; on Linux only if `/sys/class/thermal` does not exist. |

If something does not fit: open an issue with the text of the `progreso.log`.