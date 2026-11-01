# plan.md — Dédalo 3

Dédalo deja de ser una fila de tareas y pasa a ser un **orquestador por grafo**:
cada tarea dice de qué depende, Dédalo calcula los **pisos** y avanza varias tareas
a la vez (2 agentes por defecto, ajustable), cada una con el agente, modelo y gate
que pida, con respaldo de otros proveedores si uno se queda sin cuota y con un
revisor que vigila que ninguna tarea pise el trabajo de otra.

**Este plan no lo ejecuta el loop de Dédalo** (se estaría modificando a sí mismo):
lo implementa Claude directamente, tarea por tarea, delegando en subagentes cuando
convenga. Reglas: código y comentarios en inglés, textos de la interfaz con
`dedalo/i18n.py`, commits convencionales, cada tarea con tests; verificación:
`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/` (mirar el código de
salida) y `.venv/bin/ruff check dedalo tests`. **Manual**: toda tarea que cambie
cómo se usa Dédalo actualiza también su sección de `docs/MANUAL.md` y
`docs/MANUAL.es.md` en el mismo commit (a partir de que exista el manual).
**Compatibilidad**: un plan.md
actual (sin las claves nuevas) funciona exactamente como hoy, en fila.

## FASE 0 — Manual de usuario

- [ ] Manual completo de Dédalo
  criterio: `docs/MANUAL.md` (inglés) y `docs/MANUAL.es.md` (español), escritos para alguien que usa Dédalo a mano sin leer el código, con índice y estas partes: (1) qué es Dédalo y conceptos (proyecto, plan, tarea, criterio, gate, revisor, juez, iteración, run, rama de tarea, lecciones, mapeo, incidencias, métricas); (2) instalación y requisitos (agentes CLI soportados, cómo iniciar sesión en cada uno, Linux/macOS/Windows); (3) recorrido por la interfaz, panel por panel y botón por botón, con capturas; (4) **cómo escribir un buen plan.md**: estructura de fases y tareas, `criterio:` bien escrito (qué hace un criterio verificable, ejemplos buenos y malos), tamaño ideal de una tarea, «Verificación manual», y todas las claves admitidas con ejemplos (las nuevas de Dédalo 3 se añaden aquí según se implementan); (5) gates y plantillas: qué comprueba cada check, cómo correr el gate a mano, cómo añadir un check propio; (6) lanzar, seguir, detener y retomar un run; revisión manual APPROVE/REJECT; costes y presupuesto; (7) agentes y modelos: elegir, pesos, respaldo, cuotas; (8) MCP: qué ofrece y cómo conectarlo a Claude Code u otros clientes; (9) notificaciones y webhooks; (10) **problemas frecuentes** con causa y solución (baseline fallido y cómo ver qué check falló, tareas repetidas tras un corte, cuota agotada, gate que pasa a mano y falla en el loop, conflictos de git, agente no instalado o sin sesión, Wayland/atajos, Windows parcial); (11) glosario; README.md y README.es.md enlazan al manual en «Table of Contents» y al principio; la GUI tiene un botón «Manual» (menú de ayuda o F1) que abre el manual en el idioma de la interfaz; test de que el botón abre la ruta correcta y de que los dos manuales tienen las mismas secciones

## FASE 1 — Arreglos encontrados usando Dédalo en ARGUS y MultiVoice

- [ ] El motivo del baseline fallido se ve
  criterio: cuando el baseline (o cualquier gate) falla, progreso.log, incidencias.jsonl, la GUI y `estado_loop`/`cola_log` del MCP muestran qué check falló y las últimas líneas de su salida (no solo «ABORTADO: baseline falló»); la salida completa se guarda en `.dedalo/estado/gate_ultimo.log` en vez de un temporal en /tmp; tests con un gate falso que falla en un check concreto

- [ ] Un solo gate para el usuario y para el loop
  criterio: `gate.sh` ejecutado a mano corre exactamente los mismos checks que el loop (incluidos los `gate_checks/*.py`), o delega en `python -m dedalo.gate`; README explica cómo correr el gate a mano; test que compara la lista de checks de las dos vías

- [ ] Retomar sin repetir tareas tras un corte
  criterio: si un run se aborta (cuota, red, Ctrl+C, apagado) las tareas ya terminadas no se pierden: al relanzar, Dédalo detecta la rama base del run abortado, integra en main lo terminado (fast-forward; si no es posible, lo informa sin tocar nada) y sigue por la primera tarea pendiente; se registra en progreso.log; tests con un repo temporal: abortar tras 2 tareas, relanzar, no se repite ninguna

- [ ] Vueltas según las tareas pendientes y lanzamiento configurable por MCP
  criterio: el máximo de iteraciones por defecto es «tareas pendientes + 30 %» (mínimo +3) en vez de un número fijo; sigue pudiendo fijarse a mano; el MCP gana `configurar_lanzamiento(nombre, …)` (iteraciones, agentes, modelos, revisor, presupuesto, máximo de agentes en paralelo) que valida y guarda en proyectos.json, para no editarlo a mano; tests del cálculo y de la validación

- [ ] Esperar a que vuelva la cuota
  criterio: si todos los agentes disponibles (incluidos los de respaldo, FASE 2) están sin cuota, el loop no se aborta: queda «esperando cuota» (visible en GUI, MCP y notificaciones), reintenta con espera creciente (5, 10, 20… hasta 60 min) y sigue solo cuando responde; opción para abortar como hoy; tests con un agente falso que falla por cuota N veces y luego responde

- [ ] Fallos conocidos pendientes
  criterio: resueltos los puntos 2 y 3 de docs/BUGS_CONOCIDOS.md: proyectos.json lleva `"version"` de esquema con migración automática de los archivos antiguos (copia de seguridad antes de migrar), y las ramas de tareas bloqueadas o integradas se limpian solas al terminar un run (las bloqueadas se conservan en una lista consultable hasta que el usuario las descarta); BUGS_CONOCIDOS.md actualizado; tests de migración y de limpieza

## FASE 2 — Agente y modelo por tarea, pesos y respaldo

- [ ] Claves por tarea en el plan
  criterio: el parser del plan acepta, bajo cada tarea (como `criterio:`), `agente:`, `modelo:`, `peso: ligero|normal|pesado`, `revisor:` y `modelo_revisor:`; si faltan se usan los valores del proyecto; un valor desconocido se rechaza al validar el plan con un mensaje que dice la línea; el MCP `leer_plan` devuelve estas claves por tarea; tests del parser (con y sin claves, valores inválidos, plan antiguo)

- [ ] Pesos configurables por proyecto
  criterio: en los ajustes del proyecto (GUI y `configurar_lanzamiento`) cada peso apunta a un agente+modelo (por defecto ligero = el modelo barato del agente, normal = el actual, pesado = el más capaz disponible); cambiar el mapeo no obliga a tocar el plan; la GUI muestra junto a cada tarea el agente/modelo que usará; tests de resolución (tarea con modelo explícito > peso > proyecto)

- [ ] Revisor de otra empresa
  criterio: opción «revisión cruzada»: el revisor se elige automáticamente de un proveedor distinto al del agente que hizo la tarea, si hay otro instalado (p. ej. código de claude revisado por codex y al revés); si no hay, se usa el revisor configurado y se anota; tests de elección del revisor

- [ ] Cadena de respaldo por cuota
  criterio: el proyecto (y opcionalmente la tarea con `respaldo:`) define una cadena ordenada de agente/modelo; si el agente de una tarea falla por cuota, límite de tokens o de velocidad (los patrones de error ya detectados, por agente), la tarea continúa con el siguiente de la cadena **en la misma rama/copia**, con un prompt que le dice qué hizo el anterior (diff y resumen); cada cambio de agente queda en progreso.log y metrics.jsonl (qué agente/modelo hizo cada parte y su coste); si se agota la cadena, se aplica la espera de cuota (FASE 1); tests con agentes falsos

## FASE 3 — Dependencias, pisos y gates por tarea (todavía un agente a la vez)

- [ ] Ids y dependencias en el plan
  criterio: cada tarea tiene `id:` explícito o uno automático (slug del título, único); `depende: id1, id2` en una tarea y `| depende: FASE 1, FASE 3` en la cabecera de una fase (la fase entera espera; las tareas heredan la dependencia); sin ninguna clave `depende` en todo el plan, cada tarea depende de la anterior (comportamiento actual); tests del parser y de la herencia de fase

- [ ] Validar el grafo
  criterio: `python -m dedalo.plan check <ruta>` y el MCP `validar_plan(nombre)` detectan ids duplicados, dependencias a ids o fases inexistentes y ciclos (indicando el ciclo completo), y calculan los pisos; el loop valida antes de empezar y no arranca con un plan inválido (motivo visible); tests con ciclos, ids inexistentes y un grafo correcto de 3 pisos

- [ ] Planificador por grafo
  criterio: el loop elige la siguiente tarea entre las «listas» (todas sus dependencias hechas `[x]`), por piso y luego por orden del plan; si una tarea queda bloqueada `[B]`, todas las que dependen de ella (directa o indirectamente) se marcan «esperando a <id>» y el resto sigue; el run termina cuando no quedan tareas listas, informando de las que esperan y por qué; tests de orden, de propagación de bloqueos y de fin de run

- [ ] Gate por tarea o por fase
  criterio: `gate:` en una tarea o en la cabecera de una fase elige qué checks correr (nombres de `gate_checks`, p. ej. `gate: rust, i18n`) o añade un comando extra (`gate+: npm run e2e`); sin `gate:` se corre el gate completo; el baseline y el gate final del run siempre corren completos; el resultado dice qué checks se corrieron; tests de selección de checks y de que un check inexistente se rechaza al validar

## FASE 4 — Varios agentes a la vez

- [ ] Copias aisladas por tarea
  criterio: cada tarea en curso trabaja en su propio `git worktree` (rama de tarea actual) en `.dedalo/trabajo/<run>/<id>`; variables de entorno por copia para que el gate no se pise: `DEDALO_SLOT`, un rango de puertos propio (`DEDALO_PORT_BASE`) y, configurable, carpeta de compilación propia (p. ej. `CARGO_TARGET_DIR`) o compartida; las copias se borran al integrar; tests con dos tareas simultáneas en un repo temporal

- [ ] Ejecución en paralelo con límite
  criterio: hasta `max_agentes` tareas listas a la vez (por defecto 2, ajustable en GUI y MCP, 1 = comportamiento en fila); presupuesto y cuota globales del run, no por tarea; solo el coordinador escribe plan.md, lecciones.md, mapeo.txt, progreso.log y metrics.jsonl (los agentes reciben lo que necesitan en el prompt y devuelven su informe); Detener para todas las tareas en curso dejando su trabajo en sus ramas; tests: dos tareas independientes avanzan a la vez y una dependiente espera a ambas

- [ ] Informe de cambios de cada tarea
  criterio: al terminar, cada tarea produce un informe (archivos tocados con el diff resumido, qué hizo y por qué, y si tocó algo fuera de su `zona:` opcional) que el coordinador guarda en un registro de cambios del run; si el agente no lo da, se genera del diff y se le pide la explicación de los archivos fuera de zona; tests del informe generado y de la detección fuera de zona

- [ ] Revisor que vigila a las demás tareas
  criterio: antes de integrar una tarea, el revisor recibe su informe, la lista de archivos que están cambiando las tareas en curso y los de los pilares de pisos superiores pendientes que declaran esas zonas; si la tarea tocó archivos que otra está trabajando o que pertenecen a otra zona, no se integra: el revisor pide al agente que lo justifique o lo deshaga, lo reporta en progreso.log/GUI/MCP y, si persiste, la tarea se rehace después de la otra; tests con dos tareas que tocan el mismo archivo

- [ ] Integración en cola y conflictos
  criterio: las tareas terminadas se integran de una en una en la rama del run (cola); si una integración da conflicto, la tarea se rehace automáticamente sobre la rama actualizada (con su informe anterior como contexto) hasta 2 veces y luego se marca `[B]` con el motivo; `zona:` se usa también para no lanzar a la vez dos tareas de la misma zona; tests de integración limpia, conflicto resuelto rehaciendo y conflicto que bloquea

## FASE 5 — El plan manda: dirección automática y vistas

- [ ] Analizar un plan y proponer el grafo
  criterio: botón «Analizar plan» en la GUI y MCP `proponer_grafo(nombre)`: un agente lee un plan sin claves (o con pocas) y propone `id`, `depende`, `peso`, `gate` y `zona` por tarea; se muestra como diff del plan y solo se guarda si el usuario lo aprueba; la propuesta se valida (FASE 3) antes de mostrarse; tests con un agente falso

- [ ] Vista del grafo por pisos
  criterio: la GUI muestra el plan como pisos (columnas o filas) con una caja por tarea coloreada por estado (hecha, en curso con su agente/modelo, lista, esperando a <id>, bloqueada) y las flechas de dependencia; clic en una tarea muestra criterio, agente, gate, informe de cambios y log; se actualiza en vivo; tests de la construcción del modelo de la vista (sin GUI) y smoke de la vista con QT offscreen

- [ ] MCP del grafo
  criterio: el MCP expone `grafo(nombre)` (pisos, estado y agente de cada tarea), `tareas_en_curso(nombre)` y `registro_cambios(nombre)`; `estado_loop` incluye las tareas en paralelo y la espera de cuota; docs/MCP.md actualizado; tests de las herramientas

## FASE 6 — Documentación y versión 3

- [ ] Documentación del formato nuevo
  criterio: el manual (docs/MANUAL.md y .es.md) queda completo y revisado de punta a punta con todo Dédalo 3 (sección del plan con un ejemplo grande de 3 pisos y una tabla de todas las claves con su significado, valor por defecto y ejemplo; nuevas entradas en problemas frecuentes: conflictos entre tareas paralelas, tarea esperando a otra bloqueada, respaldo activado, ciclo en el plan); README.md y README.es.md explican el plan por grafo con un ejemplo de 3 pisos (`id`, `depende`, fases con `depende`, `peso`, `agente`/`modelo`, `revisor`, `respaldo`, `gate`, `zona`), el paralelismo y sus límites (recursos, cuota), la cadena de respaldo, la espera de cuota y la revisión cruzada; `llms.txt` y la plantilla de plan generada por `instalar_proyecto` incluyen las claves nuevas; capturas nuevas de la vista de grafo

- [ ] Release v3.0.0
  criterio: versión 3.0.0 en pyproject; notas con lo nuevo y la garantía de compatibilidad con los planes actuales; CI verde en Linux, macOS y Windows; **push y release solo con el «sí» del usuario**
