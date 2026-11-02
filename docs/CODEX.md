# Compatibilidad de Dédalo con Codex

El motor Python usa `codex exec`. Codex también puede actuar como piloto mediante
el MCP de Dédalo; son dos formas distintas de integrarlo.

## Configuración

1. Instala Codex CLI e inicia sesión con `codex login`.
2. Comprueba `codex login status`. Dédalo usa este comando sin enviar prompts.
3. En Dédalo elige `codex` en agente y/o revisor. El selector de modelos permanece
   habilitado: `openai/<modelo>` se convierte en `<modelo>`. Usa un modelo que tu
   cuenta permita ejecutar; el catálogo de la interfaz no verifica ese permiso.
4. Sin un modelo OpenAI seleccionado se conserva el modelo configurado en Codex.
5. Para usar Codex como piloto registra el servidor según [MCP.md](MCP.md).

La implementación se contrastó con la ayuda de Codex CLI 0.166.0 y la
[documentación oficial de ejecución no interactiva](https://learn.chatgpt.com/docs/non-interactive-mode).
Requiere las opciones `exec --json --ephemeral`, `-C`, `--sandbox` y `mcp list --json`.
No modifica la configuración global de Codex ni lee sus archivos de credenciales.

## Red, razonamiento, juez y sandbox

- **Red del agente de tareas**: `workspace-write` corta la red por defecto, así
  que el agente no podía añadir crates ni paquetes npm y programaba a ciegas.
  Dédalo pasa `-c sandbox_workspace_write.network_access=true` a la tarea
  (desactívalo con `"red_agente": false` en el lanzamiento del proyecto o
  `CODEX_RED_TAREA=0`). Revisor, juez y navegador siguen en `read-only`.
- **Razonamiento por rol**: `"razonamiento_tarea"`, `"razonamiento_revisor"` y
  `"razonamiento_juez"` en `lanzamiento` de `~/.config/dedalo/proyectos.json`
  (o `CODEX_RAZONAMIENTO_TAREA|REVISOR|JUEZ`), valores `minimal`, `low`,
  `medium`, `high`, `xhigh`; se pasan como `-c model_reasoning_effort=…`.
- **Modelo del juez aparte**: `"modelo_juez": "openai/<modelo>"` en `lanzamiento`
  (o `MODELO_JUEZ`); sin él, el juez usa el modelo de la tarea.
- **Sandbox bloqueado (bubblewrap/AppArmor)**: al arrancar, Dédalo ejecuta
  `codex sandbox -- true` (gratis, sin modelo). Si falla con el error de bwrap
  (Ubuntu 24.04 con `kernel.apparmor_restrict_unprivileged_userns=1` sin perfil
  para `/usr/bin/bwrap`) o el agente lo muestra durante una tarea, el loop se
  detiene con código 10 y un mensaje con las dos salidas: un perfil AppArmor
  para bwrap con `userns,` (recomendado) o `"sin_sandbox_codex": true` en
  `lanzamiento` (`CODEX_SIN_SANDBOX=1`), que quita el sandbox a **todos** los
  roles de Codex (tarea, revisor y juez).

La interfaz conserva estas claves al guardar el lanzamiento.

## Roles y opciones

| Función | Comportamiento |
|---|---|
| Tarea | `workspace-write`, modelo elegido, proyecto explícito y prompt por stdin. |
| Revisor dual | `read-only`, modelo propio y veredicto extraído del mensaje final. |
| Navegador | `read-only`, modelo y timeout del navegador. |
| Juez de criterio | `read-only`; se prepara el entorno de los checks Bash/Python existentes. |
| Ficha | Observador `read-only` en directorio temporal; respeta el modelo Codex elegido. |
| Sesión | `login status`; un error desconocido se muestra como estado desconocido. |
| Métricas | Tokens de entrada/salida de `turn.completed.usage`; se guarda el JSONL como evidencia. |
| MCP piloto | Herramientas de proyectos, plan, gate, ejecución, parada, revisión y métricas. |

Cada ejecución consulta los MCP efectivos en el directorio de trabajo y los
desactiva mediante overrides. Si no puede consultar esa configuración, aborta
antes de lanzar al agente. Los nombres MCP deben usar letras, números, guion o
guion bajo para poder construir esos overrides. La autenticación, proveedores y
demás configuración de Codex se conservan. Los workers usan sesiones efímeras.

`CODEX_FLAGS` solo se aplica a tareas; puede cambiar sus permisos si se configura
explícitamente. Los demás roles no heredan esos flags. `read-only` impide escribir;
no significa que el agente carezca de una herramienta para ejecutar comandos.

La revisión manual, los timeouts, los reintentos, los presupuestos estimados y
el control de ramas siguen a cargo del motor. El coste de las métricas no es una
factura de OpenAI ni una lectura de la cuota de la suscripción.

Estas mejoras son del motor Python usado por GUI/MCP. El `dedalo.sh` obsoleto no
se ha convertido en un segundo motor nuevo.

## Verificación

Las pruebas `tests/test_codex.py` usan un CLI simulado en un proceso real y
repositorios Git temporales, sin llamadas a modelos ni credenciales reales.
Cubren sesión, modelos, permisos, aislamiento de MCP, respuesta final, tokens,
selector GUI y gate iniciado por MCP. Dos recorridos completos usan navegador,
tarea, juez (Bash o Python), revisor, commit, marcado del plan y ficha.

```bash
.venv/bin/python -m pytest tests/test_codex.py -o addopts='' -q
.venv/bin/ruff check dedalo tests/test_codex.py
```

Resultado local (2026-11-02): **26 pruebas específicas de Codex aprobadas**.
La regresión terminó con **614 aprobadas, 4 omitidas y 1 deseleccionada** usando:

```bash
.venv/bin/python -m pytest -o addopts='' -q \
  --ignore=tests/test_gate_backend.py -k 'not recurso_manual_y_instructions'
```

El módulo de backend excluido contiene 17 pruebas que requieren sockets locales.
Ruff y `git diff --check` también pasaron. Una consulta real al CLI comprobó
que los overrides dejan desactivados los MCP `dedalo` y `github` heredados,
sin ejecutar inferencia ni cambiar el archivo de configuración.

La terminal aislada de la sesión no puede iniciar el app-server de Codex porque
monta `~/.codex` en solo lectura. **La prueba real se ejecutó mediante el MCP de
Dédalo**, cuyo proceso sí dispone del entorno normal del usuario: registró un
proyecto desechable, confió sus checks y lanzó el motor nativo con Codex.
Cuatro ciclos completaron tareas con respuestas reales, incluyendo juez,
revisor, commits, fichas, navegador con modelo predeterminado y selección
explícita de `gpt-6.1-sol`. Un gate fallido provocó feedback y recuperación en
el segundo intento. El navegador con modelo vacío se corrigió y quedó cubierto
por regresión y prueba real.

Se probaron también aprobación MCP ignorada, rechazo manual, parada y modelo
inexistente. La parada reveló un estado de revisión obsoleto: ahora el handler
cierra el estado y limpia los marcadores antes de salir. La corrección se
verificó en otra ejecución real. El modelo inválido detuvo el ciclo tras dos
errores y dejó la tarea pendiente. Pruebas adicionales detectaron y corrigieron
la aceptación de PASS con rc distinto de cero/veredictos contradictorios y la
ocultación de `turn.failed` detrás de un mensaje anterior.

Proyecto de evidencia: `prueba-codex-mcp-bn4ucntq`, guardado localmente en
`~/outputs/prueba-dedalo-codex-mcp-bn4ucntq`. No tiene remoto y sus notificaciones
están desactivadas. Los registros están en `.dedalo/estado/` y las fichas en
`.dedalo/fichas/`.
Las pruebas de control y modelo inválido están en
`~/outputs/prueba-dedalo-codex-control` y
`~/outputs/prueba-dedalo-codex-modelo-invalido`. El informe local completo está
en `~/outputs/informe-pruebas-dedalo-codex.md`. Los siete ciclos reales han terminado.

La terminal aislada tampoco permite sockets HTTP locales; las pruebas de
backend HTTP fallan con `PermissionError`. La prueba del recurso manual mediante
el SDK y la prueba de transporte stdio lanzadas desde esa terminal quedaron
bloqueadas. El MCP ya conectado sí funcionó para registrar, confiar, iniciar y
consultar el ciclo real. Reinicia Dédalo y el cliente MCP para cargar el código nuevo.
