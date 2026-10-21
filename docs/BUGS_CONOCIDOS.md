# Known bugs and resolved decisions

A deliberate record of defects **found and decided not to fix now**, plus
the ones already fixed, with the reason and a pointer to the code. It lives
here so they don't get lost in chat or in the agent's memory.

Suite status: see [README](../README.md#-development). Each entry states whether it carries
an active risk or is just technical debt.

---

## Resolved in v2.1.0

- **The gate no longer kills any process on the port.** `03_backend.sh` and
  `03_backend.py` now reuse a backend that already answers at `SERVE_URL`, and
  fail with a diagnostic (PID included when `lsof` is available) when the port
  is occupied by something that does not answer HTTP. The backend launched by
  the check is isolated in its own process group/session and stopped with
  `TERM` → `KILL`; the check never looks up a PID by port to kill it.
- Remaining limitation: a server that deliberately daemonizes outside its
  process group can survive the cleanup. The next run then reuses it if it
  answers, or fails safely if it does not; it is never killed by port.

---

## 1. A 3xx on endpoints is now a failure

**Active risk: cosmetic, with diagnostics.**

When the HTTP check was hardened, an endpoint responding 307/308 (typical for a
missing trailing slash) went from green to red. The message includes the code, so
the cause is obvious: fix it by adding the trailing slash to the endpoint in
`endpoints.txt` or in `ENDPOINTS`.

`curl -L` is deliberately not used: following redirects automatically could yield a
false 2xx on a mistyped route.

---

## 2. `proyectos.json` has no schema versioning

**Active risk: low.** Technical debt.

`dedalo/proyectos.py` already protects the registry against syntactic corruption
(atomic write via `os.replace`, `.corrupto` copy and a blocked startup instead of
losing projects — see `descartar_registro_corrupto` and `guardar`), but the format
carries no version. A future migration
that changes keys has no way to tell "old configuration" from "corrupt file".

When the first real migration lands: write `version: N` when creating the
registry and validate the number when reading.

---

## 3. Orphan branches from blocked tasks pile up

**Active risk: cosmetic.** Consequence of a deliberate decision.

Marking a task as `[B]` because a merge failed (user decision) keeps the branch
`dedalo/tareas/<fecha>/t<n>` around so the work can be inspected. The reaper in
`dedalo.sh:1149-1152` (and the cleanup at `:1364`/`:1381`) only deletes the branch
for the same `<fecha>/t<iter>` of the run in progress, so branches from earlier days
stay behind.

To list and delete them:

```bash
git -C <proyecto> branch --list 'dedalo/tareas/*'
git -C <proyecto> branch --delete --force <rama>
```

---

## 4. Platform compatibility

**Active risk: known and documented.** See
[README](../README.md#-compatibility).

- Linux is the reference platform and the only one with full verification.
- macOS no longer requires GNU coreutils: `timeout` → `_timeout` (GNU/gtimeout/bash
  fallback) and `sed -i "0,/…/"` → `marcar_plan` (awk+cat), with tests that prevent
  regressions. Still to verify on a real Mac and to package the `.dmg`; the thermal
  sensor (`/sys/class/thermal`) does not exist there and degrades to "no data".
- Windows is partial: the GUI and the engines (loop `loop.py`, gate `gate.py`)
  run natively on Python (PATH joined with `os.pathsep`, `.exe`/`.cmd`
  CLIs resolved, tests in CI with the POSIX ones skipped). The gate runs the checks
  `*.py` in `gate_checks/` and only uses bash, if present, to prefer the equivalent
  `*.sh` ones. Bash remains only for the project map (`mapear.sh`,
  the "Refresh map" button) and the optional bash engine (`dedalo.sh`); verification
  on a real Windows machine is still missing.
