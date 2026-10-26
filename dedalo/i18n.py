"""Lightweight UI internationalization (English source + Spanish catalog).

The GUI strings are written in English. `t()` returns the active language's
version of a string: in English mode it returns the source unchanged, in
Spanish mode it looks the string up in the `_ES` catalog and falls back to
the English source when there is no entry. This keeps the code readable and
avoids any build step or external tooling.

Only the GUI is translated. Engine/CLI/MCP output is intentionally left in
Spanish: it is asserted by the test suite and is not shown to end users.

The active language is module state. `main()` sets it at startup from
`DEDALO_IDIOMA` (useful for tests) or the persisted setting, and the GUI
selector updates it at runtime.
"""

IDIOMA_BASE = "en"
IDIOMAS = ("en", "es")
NOMBRES_IDIOMA = {"en": "English", "es": "Español"}

_idioma = IDIOMA_BASE


def idioma() -> str:
    """Returns the active language code ("en" or "es")."""
    return _idioma


def set_idioma(codigo: str) -> str:
    """Sets the active language; invalid codes fall back to the base language."""
    global _idioma
    _idioma = codigo if codigo in IDIOMAS else IDIOMA_BASE
    return _idioma


def t(texto: str, **kwargs) -> str:
    """Translates `texto` (English source) to the active language.

    Extra keyword arguments are applied with `str.format` so callers can use
    placeholders: `t("Saved {ruta}", ruta=ruta)`. If formatting fails, the
    untranslated template is returned.
    """
    salida = _ES.get(texto, texto) if _idioma == "es" else texto
    if kwargs:
        try:
            return salida.format(**kwargs)
        except (KeyError, IndexError):
            return salida
    return salida


# Spanish catalog: English source -> Spanish translation.
_ES: dict[str, str] = {
    "\n## {fecha} — Brief lesson title\n- Symptom: what failed.\n- Cause: why it failed.\n- Prevention: what to do to avoid repeating it.\n":
        "\n## {fecha} — Título breve de la lección\n- Síntoma: qué falló.\n- Causa: por qué falló.\n- Prevención: qué hacer para no repetirlo.\n",
    "\n[GUI] ⏸ Manual review required for: {tarea}":
        "\n[GUI] ⏸ Revisión manual requerida para: {tarea}",
    "  (none)": "  (ninguno)",
    " · phase: {fase}": " · fase: {fase}",
    "# Lessons learned — project memory\n\n": "# Lecciones aprendidas — memoria del proyecto\n\n",
    "[auto] New project(s) detected: {lista}":
        "[auto] Proyecto(s) nuevo(s) detectado(s): {lista}",
    "[mcp] A loop started by an external agent is running (pid {pid}); following it.":
        "[mcp] Un bucle lanzado por un agente externo está en marcha "
        "(pid {pid}); siguiéndolo.",
    "A loop is already running for this project (started by {origen}). "
    "Stop it before launching another.":
        "Ya hay un bucle corriendo para este proyecto (lanzado por {origen}). "
        "Deténlo antes de lanzar otro.",
    "stopping the external loop (pid {pid})…":
        "deteniendo el bucle externo (pid {pid})…",
    "# PLAN\n\n- [ ] your first task — criterion: ...\n":
        "# PLAN\n\n- [ ] tu primera tarea — criterio: ...\n",
    "(could not read the diff)": "(no se pudo leer el diff)",
    "(mapeo.txt does not exist — press Regenerate)":
        "(mapeo.txt no existe — pulsa Regenerar)",
    "--push at the end": "--push al final",
    "> loop (python engine)  (no usable agents: install or log into opencode, codex or claude)":
        "> loop (motor python)  (sin agentes usables: instala o inicia sesión en opencode, codex o claude)",
    "API URL (e.g. https://graph.facebook.com/v18.0/123456789)":
        "API URL (ej. https://graph.facebook.com/v18.0/123456789)",
    "API URL:": "API URL:",
    "Access Token (permissions: whatsapp_business_messaging)":
        "Access Token (permisos: whatsapp_business_messaging)",
    "Access Token:": "Access Token:",
    "Accumulated cost (USD)": "Coste acumulado (USD)",
    "Action": "Acción",
    "Adds Dédalo's block to the project's .gitignore and stops tracking the framework files (they stay on disk)":
        "Añade el bloque de Dédalo al .gitignore del proyecto y deja de rastrear los ficheros del framework (siguen en disco)",
    "Add…": "Añadir…",
    "Agent + Model (reviewer):": "Agente + Modelo (revisor):",
    "Agent + Model (task):": "Agente + Modelo (tarea):",
    "Applying framework cleanup in git...": "Aplicando limpieza del framework en git...",
    "Author": "Autor",
    "Blocked": "Bloqueadas",
    "Blocked task: {tarea}": "Tarea bloqueada: {tarea}",
    "Bot Token (from @BotFather)": "Bot Token (de @BotFather)",
    "Bot Token:": "Bot Token:",
    "Branch: {rama}": "Rama: {rama}",
    "Branch: —": "Rama: —",
    "Chat ID (numeric, e.g. 123456789)": "Chat ID (numérico, ej. 123456789)",
    "Chat ID:": "Chat ID:",
    "Check the temperature and shut down the app if it overheats":
        "Verificar la temperatura y apagar la app si se sobrecalienta",
    "Clear output": "Limpiar salida",
    "Collapse/expand panel": "Colapsar/expandir panel",
    "Configuration saved ✓": "Configuración guardada ✓",
    "Continue": "Continuar",
    "Copy everything to clipboard": "Copiar todo al portapapeles",
    "Corrupted projects registry": "Registro de proyectos corrupto",
    "Cost USD": "Coste USD",
    "Could not read the projects registry:\n{ruta}":
        "No se pudo leer el registro de proyectos:\n{ruta}",
    "Could not revert commit {sha}": "No se pudo revertir el commit {sha}",
    "Could not send. Check the configuration.":
        "No se pudo enviar. Revisa la configuración.",
    "Current temperature:": "Temperatura actual:",
    "Danger threshold (°C):": "Umbral de peligro (°C):",
    "Date": "Fecha",
    "Destination (international format, e.g. 34600123456)":
        "Destino (formato internacional, ej. 34600123456)",
    "Destination (to):": "Destino (to):",
    "Discord Webhook": "Discord Webhook",
    "Done": "Hechas",
    "Dual gate: the reviewer requires VERDICT: PASS before commit":
        "Gate doble: el revisor exige VERDICT: PASS antes del commit",
    "Duration": "Duración",
    "Duration (s)": "Duración (s)",
    "Dédalo running": "Dédalo en marcha",
    "Dédalo — control panel": "Dédalo — panel de control",
    "Enable Discord notifications": "Activar notificaciones Discord",
    "Enable Telegram notifications": "Activar notificaciones Telegram",
    "Enable WhatsApp notifications": "Activar notificaciones WhatsApp",
    "Error": "Error",
    "Error: {msg}": "Error: {msg}",
    "Est. Cost": "Coste est.",
    "Est. Cost (USD)": "Coste est. (USD)",
    "Estimated cost per task (USD):": "Coste estimado por tarea (USD):",
    "Events to notify (per enabled platform)":
        "Eventos a notificar (por plataforma activada)",
    "Explain what the agent must fix (it will be injected into the next attempt):":
        "Explica qué debe corregir el agente (se inyectará en el siguiente intento):",
    "Export metrics CSV": "Exportar métricas CSV",
    "Failures, aborts and blocked tasks with their real reason.":
        "Fallos, abortos y tareas bloqueadas con su motivo real.",
    "Framework out of git": "Framework fuera de git",
    "Full history": "Historial completo",
    "📄 Generate JSON ficha on each accepted task (uses extra tokens)":
        "📄 Generar ficha JSON al aceptar cada tarea (usa tokens extra)",
    "Runs a separate agent call after the task is accepted. The ficha is saved in .dedalo/fichas/ and never blocks the commit.":
        "Hace una llamada aparte al agente cuando la tarea se acepta. La ficha "
        "se guarda en .dedalo/fichas/ y nunca bloquea el commit.",
    "Gate": "Gate",
    "Gate output": "Salida del gate",
    "Gate: OK / FAIL": "Gate: OK / FAIL",
    "Git": "Git",
    "High temperature: keep an eye on it.": "Temperatura alta: vigílala.",
    "Injected into the agent before every task; it adds an entry automatically when a task gets blocked.":
        "Se inyecta en el agente antes de cada tarea; añade una entrada automáticamente cuando una tarea se bloquea.",
    "Installed: {inst}\nWith session: {ses}\nModels: only for opencode":
        "Instalados: {inst}\nCon sesión: {ses}\nModelos: solo para opencode",
    "Internet: ?": "Internet: ?",
    "It already had all the Dédalo files.": "Ya tenía todos los ficheros de Dédalo.",
    "It may be truncated or hand-edited. A full copy has been saved to:\n{copia}\n\nIf you quit now, the file stays where it is and you can repair it or restore it by hand. If you prefer to continue, the project list will start empty (your data is still in the copy).":
        "Puede estar truncado o editado a mano. Se ha guardado una copia completa en:\n{copia}\n\nSi sales ahora, el fichero se queda donde está y puedes repararlo o restaurarlo a mano. Si prefieres continuar, la lista de proyectos empezará vacía (tus datos siguen en la copia).",
    "It will run:\n1) Add the Dédalo block to the project's .gitignore\n2) git rm --cached of dedalo.sh, gate.sh, gate_checks/, plan.md,\n   lecciones.md, mapeo.txt, progreso.log, metrics.jsonl, etc.\n\nThe files REMAIN on disk (dedalo needs them); they just stop being in the git repo.\nContinue?":
        "Ejecutará:\n1) Añadir el bloque de Dédalo al .gitignore del proyecto\n2) git rm --cached de .dedalo/, gate.sh, gate_checks/,\n   progreso.log, metrics.jsonl, mapeo.txt, etc.\n\nLos ficheros PERMANECEN en disco (dedalo los necesita); simplemente dejan de estar en el repo git.\n¿Continuar?",
    "Iter": "Iter",
    "Iteration": "Iteración",
    "Language": "Idioma",
    "Language saved; restart to apply it": "Idioma guardado; reinicia para aplicarlo",
    "Language:": "Idioma:",
    "Last 100 iters": "Últimas 100 iter",
    "Last 50 iters": "Últimas 50 iter",
    "Last update: {n} iterations": "Última actualización: {n} iteraciones",
    "Latency": "Latencia",
    "Latency (ms)": "Latencia (ms)",
    "Launch options": "Opciones de lanzamiento",
    "Line {linea}": "Línea {linea}",
    "Logs": "Logs",
    "Loop output (live progress)": "Salida del loop (progreso en vivo)",
    "Loop stopped": "Loop parado",
    "Max budget (USD, 0 = no limit):": "Presupuesto máx. (USD, 0 = sin límite):",
    "Max iterations:": "Máx. iteraciones:",
    "Message": "Mensaje",
    "Model": "Modelo",
    "Model (navigator):": "Modelo (navegador):",
    "Models refreshed": "Modelos actualizados",
    "No CLI agent with a session was detected (opencode, codex or claude)":
        "No se detectó ningún agente CLI con sesión (opencode, codex o claude)",
    "No internet": "Sin internet",
    "No project": "Sin proyecto",
    "No temperature sensor is available.": "No hay sensor de temperatura disponible.",
    "No tests yet": "Sin pruebas todavía",
    "Normal temperature.": "Temperatura normal.",
    "Nothing to clean (it was already clean)": "Nada que limpiar (ya estaba limpio)",
    "Parent (base branch):": "Padre (rama base):",
    "Pending": "Pendientes",
    "Pending: {pend}   ·   Done: {hecho}   ·   Blocked: {bloqueada}":
        "Pendientes: {pend}   ·   Hechas: {hecho}   ·   Bloqueadas: {bloqueada}",
    "Phone Number ID": "Phone Number ID",
    "Phone Number ID:": "Phone Number ID:",
    "Plan": "Plan",
    "Project": "Proyecto",
    "Project ready": "Proyecto listo",
    "Gate templates": "Plantillas de gate",
    "Gate templates:": "Plantillas de gate:",
    "Select the stacks this project uses:":
        "Selecciona los lenguajes que usa este proyecto:",
    "None checked = python/backend (default)":
        "Ninguno marcado = python/backend (por defecto)",
    "default (python/backend)": "por defecto (python/backend)",
    "Auto-detect": "Autodetectar",
    "Detect stacks from project files and apply templates":
        "Detecta los lenguajes por los archivos del proyecto y aplica las "
        "plantillas",
    "Edit templates…": "Editar plantillas…",
    "Open checklist to pick templates":
        "Abre la lista para elegir plantillas",
    "Comma-separated list of gate templates (web, python, rust, go, etc.). "
    "History saves last 5 per project.":
        "Lista de plantillas de gate separadas por comas (web, python, rust, "
        "go, etc.). El historial guarda las últimas 5 por proyecto.",
    "Project removed": "Proyecto eliminado",
    "Project to work on (branch):": "Proyecto a trabajar (rama):",
    "Project:": "Proyecto:",
    "Project: {nombre} — {ruta}": "Proyecto: {nombre} — {ruta}",
    "Quit and repair it by hand": "Salir y repararlo a mano",
    "Real Cost": "Coste real",
    "Real Cost (USD)": "Coste real (USD)",
    "Reason": "Motivo",
    "Refresh": "Refrescar",
    "Rejection reason": "Motivo del rechazo",
    "Reload": "Recargar",
    "Remove": "Quitar",
    "Remove project": "Quitar proyecto",
    "Remove the project from the list?\n\nIts dedalo files will also be deleted from disk:\n  · .dedalo/ (scripts, gate_checks and run state)\n  · plan.md, lecciones.md and CONTEXTO.md\n\nThe rest of the project's code is NOT touched.":
        "¿Quitar el proyecto de la lista?\n\nTambién se borrarán de disco sus ficheros de dedalo:\n  · .dedalo/ (scripts, gate_checks y estado)\n  · plan.md, lecciones.md y CONTEXTO.md\n\nEl resto del código del proyecto NO se toca.",
    "Removed from the list and deleted:\n  · {lista}":
        "Quitado de la lista y borrado:\n  · {lista}",
    "Removed from the list.": "Quitado de la lista.",
    "Revert commit": "Revertir commit",
    "Revert commit {sha}?\n\nIt will run: git revert --no-commit {sha_full} && git commit -m 'revert: ...'\nThis creates a new commit that undoes the changes.":
        "¿Revertir el commit {sha}?\n\nEjecutará: git revert --no-commit {sha_full} && git commit -m 'revert: ...'\nEsto crea un commit nuevo que deshace los cambios.",
    "Reverting commit {sha}...": "Revirtiendo commit {sha}...",
    "Review diff manually before each commit (pauses the loop)":
        "Revisar el diff a mano antes de cada commit (pausa el loop)",
    "Reviewer": "Revisor",
    "Reviewer: PASS / FAIL": "Revisor: PASS / FAIL",
    "Run": "Ejecutar",
    "Run gate": "Ejecutar gate",
    "Run the project's gate": "Ejecutar el gate del proyecto",
    "SHA": "SHA",
    "Save lecciones.md": "Guardar lecciones.md",
    "Save plan.md": "Guardar plan.md",
    "Save settings": "Guardar ajustes",
    "See progreso.log": "Ver progreso.log",
    "Select the project root": "Selecciona la raíz del proyecto",
    "Settings saved": "Ajustes guardados",
    "Show the temperature in this panel (updates every second)":
        "Mostrar la temperatura en este panel (se actualiza cada segundo)",
    "Shut down now": "Apagar ahora",
    "Start from scratch (copy preserved)": "Empezar de cero (copia conservada)",
    "Status": "Estado",
    "Stop the loop before removing a project.":
        "Detén el loop antes de quitar un proyecto.",
    "Stop the loop before switching projects.":
        "Detén el loop antes de cambiar de proyecto.",
    "Task": "Tarea",
    "Task: {tarea}": "Tarea: {tarea}",
    "Tasks completed / iteration": "Tareas completadas / iteración",
    "Temperature and protection": "Temperatura y protección",
    "Test {a}": "Test {a}",
    "The application will shut down in <b>{restante}</b> s.":
        "La aplicación se apagará en <b>{restante}</b> s.",
    "The gate will run code from this repository with your permissions, without a sandbox:\n\n{detalle}\n\nRun it only if you trust this project. Trust and run?":
        "El gate ejecutará código de este repositorio con tus permisos, sin sandbox:\n\n{detalle}\n\nEjecútalo solo si confías en este proyecto. ¿Confiar y ejecutar?",
    "The interface language will change on the next start. Restart Dédalo now?":
        "El idioma de la interfaz cambiará en el próximo arranque. ¿Reiniciar Dédalo ahora?",
    "The project was prepared:\n\n  · {detalles}\n\nPress '▶ Start loop' whenever you want to start.":
        "El proyecto quedó preparado:\n\n  · {detalles}\n\nPulsa '▶ Iniciar loop' cuando quieras empezar.",
    "Theme:": "Tema:",
    "There is no internet connection.\n\nThe opencode AI models cannot respond and the loop will stop on start. Connect to the network and try again.":
        "No hay conexión a internet.\n\nLos modelos IA de opencode no podrán responder y el loop se detendrá al arrancar. Conéctate a la red e inténtalo de nuevo.",
    "This project has no valid path associated (orphan config).\n\nRemove it from the list?":
        "Este proyecto no tiene una ruta válida asociada (config huérfana).\n\n¿Quitarlo de la lista?",
    "Time": "Hora",
    "Tokens In": "Tokens Entrada",
    "Tokens Out": "Tokens Salida",
    "Total": "Total",
    "Type": "Tipo",
    "Undoes the change (creates a new commit)":
        "Deshace el cambio (crea un commit nuevo)",
    "Until (HH:MM, empty = no limit):": "Hasta (HH:MM, vacío = sin límite):",
    "Voice alerts on block/finish (notify-send/spd-say)":
        "Avisos de voz al bloquear/terminar (notify-send/spd-say)",
    "Warning seconds before shutdown:": "Segundos de aviso antes de apagar:",
    "Webhook URL (from Server Settings → Integrations)":
        "Webhook URL (desde Ajustes del servidor → Integraciones)",
    "Webhook URL:": "Webhook URL:",
    "Webhook {plataforma}: {msg}": "Webhook {plataforma}: {msg}",
    "WhatsApp (Meta Cloud API)": "WhatsApp (Meta Cloud API)",
    "[GUI] Rejected: {motivo}": "[GUI] Rechazado: {motivo}",
    "[auto-provision] Templates installed: {lista}":
        "[auto-provision] Plantillas instaladas: {lista}",
    "[auto-update] Templates updated: {lista}":
        "[auto-update] Plantillas actualizadas: {lista}",
    "[fin] error: FailedToStart (could not start the process)":
        "[fin] error: FailedToStart (no se pudo iniciar el proceso)",
    "[fin] exit={code} ({status})": "[fin] exit={code} ({status})",
    "auto (no agents with session)": "auto (sin agentes con sesión)",
    "auto → {agente}": "auto → {agente}",
    "base branch": "rama base",
    "git initialized (branch master) with {n} files":
        "git inicializado (rama master) con {n} ficheros",
    "incidencias.jsonl does not exist yet": "incidencias.jsonl no existe aún",
    "lecciones.md does not exist yet": "lecciones.md no existe aún",
    "lecciones.md saved ({ruta})": "lecciones.md guardado ({ruta})",
    "mapear.sh not found in the project": "mapear.sh no encontrado en el proyecto",
    "mapeo.txt not found": "mapeo.txt no encontrado",
    "mapeo.txt regenerated ({ruta})": "mapeo.txt regenerado ({ruta})",
    "none": "ninguno",
    "plan.md does not exist yet": "plan.md no existe aún",
    "plan.md saved ({ruta})": "plan.md guardado ({ruta})",
    "stopping the loop…": "deteniendo el loop…",
    "the loop is not responding to SIGTERM; forcing with SIGKILL…":
        "el loop no responde a SIGTERM; forzando con SIGKILL…",
    "unknown": "desconocido",
    "work branch": "rama del trabajo",
    "{actual} does not accept --model here: the model configured in its own account is used":
        "{actual} no acepta --model aquí: se usa el modelo configurado en su propia cuenta",
    "{agente} (no login)": "{agente} (sin login)",
    "{agente}: installed but no session started":
        "{agente}: instalado pero sin sesión iniciada",
    "{n} incident(s) · {ruta}": "{n} incidencia(s) · {ruta}",
    "· .gitignore updated: {modificado}": "· .gitignore actualizado: {modificado}",
    "· files out of tracking: {salidos}": "· ficheros fuera de seguimiento: {salidos}",
    "↩ Revert": "↩ Revertir",
    "↻ Refresh models": "↻ Refrescar modelos",
    "⏳ {a}: sending test…": "⏳ {a}: enviando prueba…",
    "⏸ Pending review": "⏸ Revisión pendiente",
    "■ Stop": "■ Detener",
    "▶ Start loop": "▶ Iniciar loop",
    "⚠ Blocked task: {tarea}": "⚠ Tarea bloqueada: {tarea}",
    "⚠ Critical temperature: <b>{temp} °C</b>":
        "⚠ Temperatura crítica: <b>{temp} °C</b>",
    "⚠ Incidents": "⚠ Incidencias",
    "⚠ Loop incidents": "⚠ Incidencias del loop",
    "⚠ OVERHEATING: the shutdown warning will open.":
        "⚠ SOBRECALENTAMIENTO: se abrirá el aviso de apagado.",
    "⚠ PC too hot": "⚠ PC demasiado caliente",
    "⚠ Task blocked": "⚠ Tarea bloqueada",
    "⚠ git not available: check that it is installed and your identity is configured (git config user.name/user.email)":
        "⚠ git no disponible: comprueba que está instalado y tu identidad configurada (git config user.name/user.email)",
    "✅ Loop finished": "✅ Loop finalizado",
    "✅ Task completed (gate and reviewer passed)":
        "✅ Tarea completada (gate y revisor OK)",
    "✓ .gitignore updated and {salidos} files stopped being tracked (left uncommitted; commit in the project's repo if you want to persist it)":
        "✓ .gitignore actualizado y {salidos} ficheros dejaron de rastrearse (quedan sin commitear; haz commit en el repo del proyecto si quieres persistirlo)",
    "✓ Approve and commit": "✓ Aprobar y commitear",
    "✓ Commit {sha} reverted": "✓ Commit {sha} revertido",
    "✓ Diff approved, continuing loop…": "✓ Diff aprobado, continuando el loop…",
    "✗ Diff rejected: {motivo}…": "✗ Diff rechazado: {motivo}…",
    "✗ Error reverting {sha}": "✗ Error al revertir {sha}",
    "✗ Reject and retry": "✗ Rechazar y reintentar",
    "✗ {a}: incomplete configuration": "✗ {a}: configuración incompleta",
    "＋ New lesson": "＋ Nueva lección",
    "🌡 Temperature": "🌡 Temperatura",
    "💥 Critical error": "💥 Error crítico",
    "💸 Tokens exhausted": "💸 Tokens agotados",
    "💾 Save settings": "💾 Guardar configuración",
    "📊 Loop Metrics": "📊 Métricas del Loop",
    "📊 Metrics": "📊 Métricas",
    "📋 Copy": "📋 Copiar",
    "📥 Export CSV": "📥 Exportar CSV",
    "🔄 Refresh now": "🔄 Actualizar ahora",
    "🔄 Regenerate map": "🔄 Regenerar mapeo",
    "🔄 reloaded ({ruta})": "🔄 recargado ({ruta})",
    "🔍 Automatic Navigator (finds context before each task)":
        "🔍 Navegador automático (busca contexto antes de cada tarea)",
    "🔔 Notifications": "🔔 Notificaciones",
    "One message per task that ends green, with its commit.":
        "Un mensaje por cada tarea que termina en verde, con su commit.",
    "Only for loops launched outside the panel (MCP tools or command line).":
        "Solo para loops lanzados fuera del panel (herramientas MCP o línea de comandos).",
    "🔥 Shut down due to overheating": "🔥 Apagado por sobrecalentamiento",
    "🔥 Shut down due to overheating. See you later.":
        "🔥 Apagado por sobrecalentamiento. Hasta luego.",
    "🔴 Internet: NO CONNECTION — AI models won't respond":
        "🔴 Internet: SIN CONEXIÓN — los modelos IA no responderán",
    "🗑 Clear": "🗑 Limpiar",
    "🗺 Map": "🗺 Mapa",
    "🚀 Loop started": "🚀 Loop iniciado",
    "🚀 Started from MCP / CLI": "🚀 Iniciado por MCP / CLI",
    "🛡 Security": "🛡 Seguridad",
    "🟢 Internet: OK": "🟢 Internet: OK",
    "🧠 Lessons": "🧠 Lecciones",
    "🧠 Project memory": "🧠 Memoria del proyecto",
    "📋 Context": "📋 Contexto",
    "📋 Project context": "📋 Contexto del proyecto",
    "Permanent context injected into the agent and reviewer before every task. Write architecture notes, constraints, decision logs, etc.":
        "Contexto permanente inyectado en el agente y el revisor antes de cada tarea. Escribe notas de arquitectura, restricciones, registros de decisiones, etc.",
    "CONTEXTO.md saved ({ruta})": "CONTEXTO.md guardado ({ruta})",
    "CONTEXTO.md does not exist yet": "CONTEXTO.md aún no existe",
    "# Project context — permanent notes\n\n": "# Contexto del proyecto — notas permanentes\n\n",
    "🧪 Test Discord": "🧪 Probar Discord",
    "🧪 Test Telegram": "🧪 Probar Telegram",
    "🧪 Test WhatsApp": "🧪 Probar WhatsApp",
    "🧹 Framework out of git": "🧹 Framework fuera de git",
}
