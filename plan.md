# plan.md — Dédalo 3

Dédalo deja de ser una fila de tareas y pasa a ser un **orquestador por grafo**:
cada tarea dice de qué depende, Dédalo calcula los **pisos** y avanza varias tareas
a la vez (1 agente por defecto, ajustable), cada una con el agente, modelo y gate
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
**Ramas**: la carpeta `dedalo` en `main` es la copia estable con la que corren los loops de otros proyectos. Se trabaja en el `git worktree` `~/Escritorio/Programas_Propios/dedalo-3` (con su propio `.venv`). Los **arreglos** se integran en `main` cuando están probados; cada **mejora** va en su propia rama (`mejora/<nombre>`) y no toca `main` hasta que el usuario lo pida. `ERROR_DEDALO_BASELINE.txt` es el backlog vivo de la sesión del POS: un punto se pasa a «Ya ARREGLADOS» al integrarse en `main`, no antes. **Un solo motor**: el loop vive en Python (`dedalo/loop.py` y compañía); `plantillas_data/dedalo.sh` se retira (tarea «Retirar funciones sin uso», FASE 1). **Simple por defecto**: todo lo nuevo es opcional y se activa solo al escribirlo en el plan, para que un proyecto pequeño siga usando la estructura sencilla de siempre. **Compatibilidad**: un plan.md
actual (sin las claves nuevas) funciona exactamente como hoy, en fila.

## FASE 0A — Arreglos urgentes (informe del POS, 2026-11-08)

Fuente: `ERROR_DEDALO_BASELINE.txt`; el número entre paréntesis es el punto de esa lista. Van antes que el manual porque cambian comportamientos que el manual tiene que describir.

- [x] Nunca se borra trabajo que no se pudo guardar
  criterio: `guardar_parcial` deshace antes las entradas intent-to-add (las deja `git add -N` el revisor, y con ellas `git stash` falla); si el stash falla por cualquier motivo, `_parar_limpio` **no** revierte ni borra la rama de la tarea: deja el trabajo donde está y lo registra en progreso.log e incidencias.jsonl; tests con repo temporal: parada tras `diff_para_revisor` → stash con archivos nuevos y modificados, y stash que falla → archivos intactos y rama conservada (16, caso B)

- [x] Un bloqueo o una cuota no tiran trabajo terminado
  criterio: al bloquear una tarea su trabajo se conserva en `dedalo/bloqueadas/<run>/<n>` (con commit) y el log dice cómo recuperarlo, en vez de descartar la rama; si la cuota se agota en el revisor o en el juez, el trabajo que ya pasó por el agente se guarda y la iteración queda registrada en `estado`, de modo que al reanudar se restaura y se repite solo la verificación, sin volver a llamar al agente; si la tarea cambió en plan.md se empieza de cero y se avisa; tests con agentes falsos: bloqueo → rama conservada; cuota en revisor → al relanzar, el agente no se invoca y la tarea termina (16)

- [x] La tarea sale del plan de la rama del run
  criterio: con `trabajo: master`, `preparar_ramas` no deja el árbol en la rama de trabajo hasta la integración final, así que plan.md, código y baseline son los de la rama del run; test: con master atrasado, RETOMAR y `--trabajo master`, la primera tarea es la pendiente de la rama del run (12)

- [x] El loop sobrevive a quien lo lanzó y se recupera si muere
  criterio: en Linux, `iniciar_loop` del MCP lanza el motor con `systemd-run --user --scope` cuando esté disponible (si no, como hoy), para que cerrar la sesión cliente no lo mate (la GUI queda igual: su salida va por una tubería al panel); al arrancar, si el árbol está sucio en una rama `dedalo/tareas/*` y no hay motor vivo, el trabajo se guarda en un stash con nombre «recuperado tras muerte del loop», se vuelve a la rama del run y se continúa, en vez de negarse; tests del argv con y sin systemd y de la recuperación con repo temporal (13)

- [x] Criterios que el agente sí puede cumplir
  criterio: al arrancar, los comandos citados entre comillas invertidas en cada criterio se comparan con los que el agente puede ejecutar (`bash_permitidos` en claude) y se avisa de los que no; agente y juez reciben la lista de comandos permitidos; `comandos_extra` por proyecto (fuera del repo) amplía la lista; no hay clave por tarea porque el agente puede editar plan.md y se daría permisos a sí mismo; si el agente informa de un bloqueo por permiso (línea `DEDALO_BLOQUEO_PERMISO:`), la tarea se pausa con el motivo sin gastar reintentos; tests de la validación, del prompt y de la pausa (15)

- [x] Las funciones que se commitean se pueden usar
  criterio: check opcional «alcanzable» por stack, empezando por Tauri: compara `generate_handler![...]` con las invocaciones en `src/` y los nombres de sus argumentos, e informa de los comandos que nadie llama; se instala con la plantilla `tauri` y admite lista de excepciones (`.dedalo/alcanzable_ignorar.txt`); tests con un proyecto de ejemplo (17)

- [x] Tareas que solo puede hacer una persona
  criterio: el marcador `- [M]` en plan.md se salta sin bloquear, se cuenta aparte en GUI y MCP y se lista al final del run; el prompt prohíbe al agente crear `- [ ]` que declaren no ser automatizables; tests del parser, del salto y del resumen final (18)

- [x] El gate dice qué test falló
  criterio: el filtro de las plantillas de test (el de Rust era el único que recortaba la salida) conserva `FAILED`, `panicked` y el bloque final `failures:`; un test que falla se repite una vez y, si entonces pasa, se informa como «inestable» en vez de ocultarlo; tests con salidas reales de cargo (22)

- [x] Las notificaciones no se pierden por un corte
  criterio: reintentos con espera (1, 3 y 10 s) ante errores de red o 5xx; si sigue fallando, el mensaje se encola y sale con la siguiente notificación; ningún token aparece en logs ni mensajes de error; tests con un servidor falso que falla N veces (14)

- [x] Avisar cuando el plan crece
  criterio: si un agente añade tareas a plan.md durante un run, se notifica «el agente añadió N tareas» con sus títulos y el total del aviso final ya las cuenta; opción del proyecto `pausar_si_crece` para parar y revisarlas; tests con un agente falso que añade una tarea (19)

- [x] Reanudar solo tras la cuota
  criterio: si todos los agentes disponibles (incluidos los de respaldo, FASE 2) están sin cuota, tras dejar el árbol limpio y con `reanudar_tras_cuota` activo, el loop avisa («se reanuda a las HH:MM» en el log, visible por GUI y MCP, y notificación), duerme hasta la hora del mensaje del proveedor («resets 3:40am (America/Lima)») más un margen; sin hora, reintenta con espera creciente (5, 10, 20… hasta 60 min); sin la opción, se detiene como hoy; tests con un agente falso sin cuota N veces y con un mensaje con hora de reseteo (7, 20)

## FASE 0 — Manual de usuario

- [ ] Manual completo de Dédalo
  criterio: `docs/MANUAL.md` (inglés) y `docs/MANUAL.es.md` (español), escritos para alguien que usa Dédalo a mano sin leer el código, con índice y estas partes: (1) qué es Dédalo y conceptos (proyecto, plan, tarea, criterio, gate, revisor, juez, iteración, run, rama de tarea, lecciones, mapeo, incidencias, métricas); (2) instalación y requisitos (agentes CLI soportados, cómo iniciar sesión en cada uno, Linux/macOS/Windows); (3) recorrido por la interfaz, panel por panel y botón por botón, con capturas; (4) **cómo escribir un buen plan.md**, con dos caminos claros: **plan simple** (fases y tareas en fila con `criterio:`, sin claves extra; lo recomendado para proyectos pequeños) y **plan avanzado** (dependencias, pisos, pesos, modelos, gates y zonas para proyectos grandes; se pueden mezclar y adoptar poco a poco): estructura de fases y tareas, `criterio:` bien escrito (qué hace un criterio verificable, ejemplos buenos y malos), tamaño ideal de una tarea, «Verificación manual», y todas las claves admitidas con ejemplos (las nuevas de Dédalo 3 se añaden aquí según se implementan); (5) gates y plantillas: qué comprueba cada check, cómo correr el gate a mano, cómo añadir un check propio; (6) lanzar, seguir, detener y retomar un run; revisión manual APPROVE/REJECT; costes y presupuesto; (7) agentes y modelos: elegir, pesos, respaldo, cuotas; (8) MCP: qué ofrece y cómo conectarlo a Claude Code u otros clientes; (9) notificaciones y webhooks; (10) **problemas frecuentes** con causa y solución (baseline fallido y cómo ver qué check falló, tareas repetidas tras un corte, cuota agotada, gate que pasa a mano y falla en el loop, conflictos de git, agente no instalado o sin sesión, Wayland/atajos, Windows parcial); (11) glosario; README.md y README.es.md enlazan al manual en «Table of Contents» y al principio; la GUI tiene un botón «Manual» (menú de ayuda o F1) que abre el manual en el idioma de la interfaz; test de que el botón abre la ruta correcta y de que los dos manuales tienen las mismas secciones

## FASE 1 — Arreglos encontrados usando Dédalo en ARGUS, MultiVoice y POS-Minimarket

Fuente: uso real y `ERROR_DEDALO_BASELINE.txt`. Lo marcado `[x]` ya está en `main` (commits 86beaeb, 821eaaf, d73e91d).

Orden: primero lo ya hecho, luego los arreglos (van a `main` al estar probados), después el control de calidad y por último las mejoras (cada una en su rama).

- [x] La tarea que se marca es la que se hizo
  criterio: al empezar una iteración se guarda la identidad de la tarea elegida (línea, título y criterio); al terminar se marca `[x]`/`[B]` exactamente esa tarea aunque plan.md haya cambiado entretanto (tareas insertadas encima, otra desbloqueada, criterio editado); si ya no existe o cambió de estado no se marca nada y se avisa en progreso.log e incidencias.jsonl; `Plan.marcar_primera` deja de usarse en el loop; tests: editar el plan durante la iteración (insertar arriba, desbloquear una `[B]` anterior) y comprobar que se marca la correcta (error 16) — **hecha en 821eaaf**

- [x] El consentimiento del gate no se pierde por la caché de Python
  criterio: el manifiesto de consentimiento ignora `__pycache__/` y `*.pyc`, y el gate solo ejecuta código fuente `.py` (nunca bytecode), así que excluirlos no abre una puerta; el gate, el agente y el juez corren con `PYTHONDONTWRITEBYTECODE=1`; se localiza y corrige quién escribía la caché en `gate_checks/` (solo 8 de 12 checks la tenían); tests: correr el gate y relanzar no pide `confiar_gate`; un `.pyc` plantado no se ejecuta ni cambia el consentimiento (error 15) — **hecha en 821eaaf**

- [x] Paradas limpias
  criterio: cualquier parada (cuota agotada, `detener_loop`/Detener, presupuesto, `hasta`, máximo de iteraciones, error) deja el repo limpio en la rama del run: el trabajo a medias de la tarea en curso se guarda en un stash con nombre (`dedalo <run>/<tarea>: parcial (<motivo>)`) y se anota en progreso.log con el comando para recuperarlo, se vuelve a la rama del run y se borra la rama de tarea a medias; Detener espera a un punto seguro como máximo N s antes de cortar; tests con repo temporal: parar por cuota y por Detener a mitad de tarea → árbol limpio, stash presente, rama de tarea borrada (errores 3 y 7) — **hecha en 821eaaf y d73e91d; el caso del stash que falla sigue en FASE 0A**

- [x] Retomar sin repetir tareas tras un corte
  criterio: si un run se aborta (cuota, red, Ctrl+C, apagado, Detener) las tareas ya terminadas no se pierden: al relanzar, Dédalo encuentra la última rama de run (guardada en `estado_loop.json`) y, si va por delante de la rama base y la base es su ancestro, sigue desde ella (o integra en la base por fast-forward si el proyecto lo pide; si no es posible, lo informa sin tocar nada) y continúa por la primera tarea pendiente; GUI y MCP avisan cuando hay trabajo de un run sin integrar en la rama principal y ofrecen «Continuar la última ejecución» e «Integrar en <rama>»; con el árbol sucio al arrancar no se cambia de rama: se aborta con el motivo; se registra en progreso.log; tests con un repo temporal: abortar tras 2 tareas, relanzar, no se repite ninguna (error 2) — **hecha en 821eaaf; la integración sigue en la tarea siguiente**

- [x] Codex: red, razonamiento y sandbox
  criterio: (las bases de Codex — modelo por rol, `--sandbox` por rol, MCP aislados — ya están en `dedalo/codex_cli.py`); opción del proyecto «red para el agente de tareas» (activada por defecto) que pasa a Codex el permiso de red del modo `workspace-write` (opción comprobada contra `codex exec --help`/docs de la versión instalada); nivel de razonamiento por rol (tarea, revisor, juez) en GUI y `configurar_lanzamiento`; modelo del juez elegible aparte (no solo por `MODELO_JUEZ`); prueba previa al lanzar (`codex exec` mínimo) que detecta el fallo de bubblewrap/AppArmor («bwrap … Operation not permitted», solo lectura) y aborta con un mensaje que propone las dos salidas (perfil AppArmor para bwrap o `CODEX_FLAGS` sin sandbox, decisión del usuario); los mensajes «could not resolve / failed to download / ENOTFOUND» del agente se detectan como «sin red» y bloquean la tarea con ese motivo en vez de gastar reintentos; el prompt dice al agente que pida la dependencia si no tiene red en vez de inventar versiones; tests con CLI simulado (errores 12–14 y 17) — **hecha en 821eaaf y d73e91d**

- [x] Lecciones útiles tras un fallo
  criterio: la lección automática tras un fallo del gate o del revisor incluye las líneas concretas del fallo (qué check, qué regla, archivo y mensaje; recortadas a un máximo) y una prevención concreta; si el agente arregla el fallo en el reintento, se le pide una lección de una línea escrita por él a partir del feedback, que sustituye a la genérica; no se repite una lección igual; tests con la salida de un check de reglas que falla (error 4) — **hecha en 821eaaf; queda la lección escrita por el agente como mejora opcional**

- [ ] Codex: sin red detectado y cachés reutilizadas
  criterio: los mensajes «could not resolve / failed to download / ENOTFOUND» del agente con la red desactivada se detectan y bloquean la tarea con ese motivo sin gastar reintentos; la tarea de Codex puede escribir en las cachés de cargo y npm (`sandbox_workspace_write.writable_roots`, comprobado contra el CLI instalado) o usa un `CARGO_HOME` persistente en `.dedalo/`, para no volver a descargar en cada iteración; tests con CLI simulado (10)

- [ ] El gate del agente no lanza al juez
  criterio: `.dedalo/estado/gate` (el que corre el agente) omite `98_criterio` con un aviso claro («el juez se ejecuta después, fuera del sandbox»); el gate real del loop no cambia; tests del lanzador (9)

- [ ] El gate corre sobre lo que se commitea
  criterio: el gate se ejecuta sobre exactamente lo que se va a commitear (copia limpia o equivalente) y el commit incluye todo lo nuevo de la rama frente a su base, para que un residuo no dé un gate verde con un commit roto; tests con un archivo residual ignorado por el commit (11)

- [ ] El motivo del baseline fallido se ve
  criterio: (ya hecho: el aborto nombra los checks y guarda `gate_ultimo.log`) la GUI y `estado_loop` muestran esos checks y las últimas líneas de su salida; `iniciar_loop` espera al resultado del baseline (con límite de tiempo) y lo devuelve junto al pid; la salida del gate se guarda **siempre** por iteración, también cuando pasa, en `.dedalo/estado/gate_iter_<n>.log`, y la línea del juez va a progreso.log; tests con un gate falso (5)

- [ ] Plantillas que validan el orden de las primeras tareas
  criterio: (ya hecho en 821eaaf: el baseline tolera los checks rojos en un proyecto nuevo) los checks de plantilla que dependen del esqueleto dan «aviso» mientras no existe; `instalar_proyecto` y las plantillas validan que las primeras tareas crean lo que los checks piden, en ese orden; tests de la validación

- [ ] Un solo gate para el usuario y para el loop
  criterio: (ya hecho en 821eaaf: `--solo` y el lanzador del agente) `gate.sh` ejecutado a mano corre exactamente los mismos checks que el loop (incluidos los `gate_checks/*.py`), o delega en `python -m dedalo.gate`; README explica cómo correr el gate a mano; test que compara la lista de checks de las dos vías

- [ ] Sin procesos huérfanos al acabar la iteración
  criterio: al cerrar cada iteración se listan y terminan los procesos que quedan en el cgroup o scope del motor (salvo el motor), incluidos los que abrieron su propia sesión; sin cgroup se hace lo posible por grupo; tests con un proceso que se desliga (21)

- [ ] Revisor medido y modo estricto
  criterio: metrics.jsonl guarda por iteración el veredicto del revisor y del juez, qué encontraron y si el gate falló después de un PASS del revisor; la GUI/`resumen_metricas` muestran la tasa de hallazgos del revisor; opción «revisor estricto» con lista de comprobación (criterio punto por punto, tests nuevos que fallan sin el cambio, textos de UI e i18n); tests del registro y del prompt estricto (mejora 8)

- [ ] Capturas de la interfaz para el revisor
  criterio: check opcional que, en las tareas cuyo título empieza por «UI:», hace capturas de las pantallas clave (Xvfb o Playwright) y se las pasa al revisor, para que vea fallos visibles que hoy pasan el gate y el revisor (textos duplicados, etiquetas cortadas, barras que se desplazan, textos sin traducir); configurable por proyecto y sin efecto si no se activa; tests con un proyecto de ejemplo (1)

- [ ] Integrar el run en la rama padre al terminar
  criterio: opción del proyecto «integrar en la rama padre» que al terminar o parar el run hace fast-forward (si no es posible, avisa sin tocar nada); comando en GUI y tool MCP `integrar_run(nombre)`; GUI y MCP avisan cuando hay trabajo de un run sin integrar; tests con repo temporal: integración limpia y base divergente (4)

- [ ] Log por ejecución y texto del agente aparte
  criterio: cada run empieza con una línea de cabecera fija (`== RUN <id> INICIADO ==`) y `cola_log`/estado solo muestran líneas del run actual; progreso.log solo tiene eventos de una línea con formato fijo (hora, run, tarea, tipo, mensaje) y el texto completo del agente, del revisor y la salida del gate van a `.dedalo/estado/iter_<run>_<n>.md`, enlazado desde el evento; la GUI de Logs puede abrir ese detalle; tests del formato y de que un texto del agente con «limit» o «fin» no aparece como evento (error 6, mejora 5)

- [ ] Vueltas según las tareas pendientes y lanzamiento configurable por MCP
  criterio: el máximo de iteraciones por defecto es «tareas pendientes + 30 %» (mínimo +3) en vez de un número fijo; sigue pudiendo fijarse a mano; el MCP gana `configurar_lanzamiento(nombre, …)` (iteraciones, agentes, modelos, revisor, presupuesto, máximo de agentes en paralelo) que valida y guarda en proyectos.json, para no editarlo a mano; tests del cálculo y de la validación

- [ ] Fallos conocidos pendientes y ramas acumuladas
  criterio: resueltos los puntos 2 y 3 de docs/BUGS_CONOCIDOS.md: proyectos.json lleva `"version"` de esquema con migración automática de los archivos antiguos (copia de seguridad antes de migrar), y las ramas de tareas bloqueadas, abortadas o integradas se limpian solas al terminar un run (las bloqueadas se conservan en una lista consultable hasta que el usuario las descarta); comando/botón «Integrar run en <rama principal>» y limpieza de ramas de run ya integradas; BUGS_CONOCIDOS.md actualizado; al reiniciar una tarea se le ofrece al agente su stash parcial, y el comando `limpiar` borra las ramas ya integradas y los stashes de tareas completadas; tests de migración, de limpieza y de la reutilización del stash (23)

- [ ] Pausa para probar al terminar cada fase
  criterio: opción del proyecto «Parar al terminar cada fase», `| pausa` en la cabecera de una fase y una línea `- [PARAR] <texto>` en cualquier punto del plan: el loop se detiene **antes de empezar** la tarea siguiente (nunca deja una a medias), limpio, integra lo hecho y avisa (GUI, notificación, MCP) con la lista «Verificación manual» de esa fase sacada de plan.md; «Continuar» sigue con la fase siguiente; si el usuario encuentra un fallo puede añadir una tarea de arreglo antes de continuar; la cabecera de una fase admite `agente:`/`modelo:`/`revisor:` que heredan sus tareas (cuando existan las claves por tarea de FASE 2); tests: el loop para tras la última tarea de la fase sin empezar la siguiente y continúa al reanudar (`- [PARAR]` ya está en 821eaaf; queda la opción por proyecto, `| pausa`, y el cambio de agente o modelo por fase) (7)

- [ ] El loop no pisa la carpeta del usuario
  criterio: opción del proyecto (activada por defecto en proyectos nuevos) para que el loop trabaje en un `git worktree` propio en `.dedalo/trabajo/run` (ignorado por git) en vez de cambiar de rama en la carpeta del proyecto; el usuario puede abrir, probar y editar su copia mientras el loop corre; las ramas y el resultado son los mismos; esta copia única es la base de las copias por tarea de FASE 4; tests con repo temporal: editar un archivo en la carpeta del usuario durante una iteración no entra en el commit de la tarea (mejora 3)

- [ ] Esperar eventos y avisos para pilotos externos
  criterio: MCP `esperar_evento(nombre, tipos=[commit, fallo, bloqueo, pausa, cuota, fin], timeout)` que devuelve el primer evento nuevo (sin tener que leer el log); los mismos eventos pueden ir a notificaciones de escritorio y a un webhook/ntfy configurable; tests del MCP con un loop falso que emite eventos (mejora 4)

- [ ] Coste acumulado por proyecto y por fase
  criterio: además del coste del run, Dédalo guarda el acumulado por proyecto y por fase (sumando metrics.jsonl de todos los runs) y lo muestra en GUI y MCP; con CLIs de suscripción se marca como estimado y, si el CLI la informa, se muestra la hora de reseteo de la cuota; con tokens reales disponibles se calcula con ellos y, si no los hay, se muestra «no disponible» en vez de un número fijo; tests de la suma entre runs y del caso sin tokens (8, 24)

- [ ] Retirar funciones sin uso
  criterio: se quitan de la interfaz, el motor, las plantillas y la documentación: apagado por temperatura de CPU, avisos por voz, navegador de contexto, fichas JSON por tarea y el motor antiguo `dedalo.sh` (ningún proyecto registrado las tiene activas, comprobado el 2026-11-08); las claves viejas en `proyectos.json` se ignoran sin error; los proyectos ya instalados siguen funcionando aunque conserven esos archivos; se trabaja en su propia rama; la suite pasa sin los tests de lo retirado

## FASE 2 — Agente y modelo por tarea, pesos y respaldo

- [ ] Adaptadores por agente
  criterio: cada agente CLI (claude, codex, opencode y los que ya soporta Dédalo) tiene un adaptador propio en un módulo (cómo se lanza, aislamiento/permisos, cómo se pasa el modelo, cómo se lee la salida y el coste, y los patrones de error de cuota, límite de tokens, límite de velocidad, sesión caducada y agente no instalado); el resto del motor solo habla con la interfaz del adaptador; tests de contrato por adaptador con salidas reales grabadas (fixtures) de cada CLI, que fallan si cambia el formato; el manual explica cómo actualizar un adaptador cuando un CLI cambia; `instalar_proyecto`/GUI muestran la versión detectada de cada CLI

- [ ] Claves por tarea en el plan
  criterio: el parser del plan acepta, bajo cada tarea (como `criterio:`), `agente:`, `modelo:`, `peso: ligero|normal|pesado`, `revisor:` y `modelo_revisor:`; si faltan se usan los valores del proyecto; un valor desconocido se rechaza al validar el plan con un mensaje que dice la línea; el MCP `leer_plan` devuelve estas claves por tarea; tests del parser (con y sin claves, valores inválidos, plan antiguo)

- [ ] Pesos configurables por proyecto
  criterio: en los ajustes del proyecto (GUI y `configurar_lanzamiento`) cada peso apunta a un agente+modelo (por defecto ligero = el modelo barato del agente, normal = el actual, pesado = el más capaz disponible); cambiar el mapeo no obliga a tocar el plan; la GUI muestra junto a cada tarea el agente/modelo que usará; tests de resolución (tarea con modelo explícito > peso > proyecto)

- [ ] Revisor de otra empresa
  criterio: opción «revisión cruzada»: el revisor se elige automáticamente de un proveedor distinto al del agente que hizo la tarea, si hay otro instalado (p. ej. código de claude revisado por codex y al revés); si no hay, se usa el revisor configurado y se anota; tests de elección del revisor

- [ ] Cadena de respaldo por cuota
  criterio: el proyecto (y opcionalmente la tarea con `respaldo:`) define una cadena ordenada de agente/modelo; si el agente de una tarea falla por cuota, límite de tokens o de velocidad (los patrones de error ya detectados, por agente), la tarea continúa con el siguiente de la cadena **en la misma rama/copia**, con un prompt que le dice qué hizo el anterior (diff y resumen); cada cambio de agente queda en progreso.log y metrics.jsonl (qué agente/modelo hizo cada parte y su coste); si se agota la cadena, se aplica la espera de cuota (FASE 1); tests con agentes falsos

- [ ] Pista humana al reintentar
  criterio: antes de reintentar una tarea fallida o bloqueada, el usuario puede escribirle una **pista** al agente (GUI, MCP `pista_tarea(nombre, id, texto)`) que se añade al prompt del siguiente intento; tests de la pista en el prompt
- [ ] Lista de tareas en Ejecutar y registros etiquetados
  criterio: Ejecutar muestra una **lista de tareas** (filtros por fase y estado) con columnas estado, tarea, agente/modelo (desplegable: «Auto (peso)» o uno concreto), peso y un menú ⋯ con «Revisor especial…» (el revisor por defecto no se muestra); se pueden seleccionar varias filas y asignarles el mismo agente/peso; cada cambio se escribe en plan.md bajo esa tarea (`agente:`, `modelo:`, `peso:`, `revisor:`), que sigue siendo la única fuente de verdad (editar plan.md a mano refresca la lista); durante un run solo se editan las tareas que no han empezado; las opciones de lanzamiento marcan agente/modelo de tarea y revisor como «por defecto» y añaden pesos, cadena de respaldo, revisor de otra empresa, iteraciones «auto» y esperar cuota; progreso.log, incidencias.jsonl y metrics.jsonl llevan en cada entrada la tarea y el agente/modelo (`[id · agente/modelo]`), lecciones.md anota en cada lección dónde se aprendió, CONTEXTO.md sigue siendo uno solo y Logs tiene filtro por tarea; tests del etiquetado, del filtro, de que editar la lista escribe las claves correctas en plan.md y de que una tarea en curso no se puede editar, y smoke de Ejecutar (QT offscreen)

- [ ] Avisar de versiones nuevas
  criterio: al abrir la app, y como mucho una vez al día, Dédalo consulta la última versión publicada y avisa si hay una nueva, con sus notas y el enlace o comando para actualizar; se puede desactivar y un fallo de red no molesta; no se envía ningún dato del usuario ni de sus proyectos; tests con respuestas falsas (más nueva, igual, error)

- [ ] Deshacer una ejecución
  criterio: un botón en la GUI (y tool MCP) devuelve el proyecto al estado anterior a un run sin necesidad de saber git: muestra qué se va a quitar, pide confirmación y deja una rama de respaldo con lo deshecho, de modo que se puede recuperar; con cambios sin commitear se niega y dice por qué; tests con repo temporal: deshacer y recuperar

- [ ] Versión intermedia 2.3.0
  criterio: manual al día con lo de las FASES 0–2; versión 2.3.0 en pyproject con notas; CI verde en Linux, macOS y Windows; **push y release solo con el «sí» del usuario** (así ARGUS y MultiVoice pueden usar ya el modelo por tarea, el respaldo y los arreglos)

## FASE 3 — Dependencias, pisos y gates por tarea (todavía un agente a la vez)

- [ ] Separar el motor en coordinador y ejecutor de tarea
  criterio: refactor sin cambios de comportamiento: `loop.py` se divide en un **coordinador** (elige tareas, escribe plan/lecciones/mapeo/logs/métricas, integra) y un **ejecutor de tarea** (prepara la rama, lanza agente, gate, revisor y devuelve un resultado estructurado: estado, coste, informe, motivo), con una interfaz que más adelante permita varios ejecutores a la vez; coordinador, ejecutor y adaptadores llevan anotaciones de tipos completas y `mypy` (modo estricto solo para esos módulos) corre en el CI; todos los tests actuales pasan sin cambiarlos y se añaden tests del ejecutor con agentes falsos

- [ ] Ids y dependencias en el plan
  criterio: cada tarea tiene `id:` explícito o uno automático (slug del título, único); `depende: id1, id2` en una tarea y `| depende: FASE 1, FASE 3` en la cabecera de una fase (la fase entera espera; las tareas heredan la dependencia); sin ninguna clave `depende` en todo el plan, cada tarea depende de la anterior (comportamiento actual); tests del parser y de la herencia de fase

- [ ] Validar el grafo
  criterio: `python -m dedalo.plan check <ruta>` y el MCP `validar_plan(nombre)` detectan ids duplicados, dependencias a ids o fases inexistentes y ciclos (indicando el ciclo completo), y calculan los pisos; además muestran un **ensayo** del run (orden por pisos, agente/modelo y gate de cada tarea y una estimación de coste y tiempo a partir del historial de metrics.jsonl de ese agente/modelo, o «sin datos») visible también en la GUI antes de pulsar Iniciar; el loop valida antes de empezar y no arranca con un plan inválido (motivo visible); tests con ciclos, ids inexistentes y un grafo correcto de 3 pisos

- [ ] Planificador por grafo
  criterio: el loop elige la siguiente tarea entre las «listas» (todas sus dependencias hechas `[x]`), por piso y luego por orden del plan; si una tarea queda bloqueada `[B]`, todas las que dependen de ella (directa o indirectamente) se marcan «esperando a <id>» y el resto sigue; el run termina cuando no quedan tareas listas, informando de las que esperan y por qué; tests de orden, de propagación de bloqueos y de fin de run

- [ ] Gate por tarea o por fase
  criterio: `gate:` en una tarea o en la cabecera de una fase elige qué checks correr (nombres de `gate_checks`, p. ej. `gate: rust, i18n`) o añade un comando extra (`gate+: npm run e2e`); sin `gate:` se corre el gate completo; el baseline y el gate final del run siempre corren completos; el resultado dice qué checks se corrieron; nueva plantilla de check opcional **e2e** (Playwright para proyectos web, comando configurable para otros) para que los gates se parezcan más al uso real; tests de selección de checks y de que un check inexistente se rechaza al validar

- [ ] Árbol de tareas
  criterio: nueva vista en el panel Plan que dibuja las tareas como un **árbol de habilidades de videojuego**, a partir de `depende:` (sin claves nuevas): cada tarea es un nodo unido a las que necesita y a las que desbloquea, y una tarea puede requerir varias a la vez, como materiales que se combinan para forjar otra; estados visibles de un vistazo: bloqueada por dependencias (apagada, con candado), disponible, en curso, hecha, fallida `[B]` y para una persona `[M]`; al completarse una tarea se iluminan las líneas y se desbloquean las siguientes; las fases se ven como ramas; zoom y desplazamiento; al pulsar un nodo se ve su criterio, responsable, de qué depende, qué desbloquea y por qué no está disponible; un plan sin dependencias se ve como una sola línea; respeta los temas e i18n; `validar_plan` del MCP devuelve el mismo árbol en texto; los «pisos» quedan como cálculo interno y no se muestran con ese nombre; tests de la disposición (varios padres, ciclos rechazados, plan en fila) y smoke de la vista (QT offscreen)

## FASE 3B — Una interfaz que se sienta como un juego

La temática es opcional: el tema sobrio de siempre sigue disponible y cada cual elige. Cambia cómo se ve, nunca lo que hace; legibilidad y contraste por encima del efecto.

- [ ] Temas en Ajustes y temas de verdad
  criterio: el selector de temas pasa a una sección Ajustes; un tema deja de ser solo colores y define también tipografía (fuentes incluidas con licencia libre), bordes, formas, iconos y animaciones; los temas actuales siguen funcionando; cambiar de tema no requiere reiniciar; tests de carga de temas y de contraste mínimo, y smoke (QT offscreen)

- [ ] Temas de videojuego
  criterio: al menos cuatro temas que se sientan como estar dentro de un juego: retro pixel, HUD cyberpunk, anime y fantasía/RPG; incluyen el árbol de tareas y todas las secciones, sin zonas que se queden con el aspecto normal; capturas de cada tema en el README; smoke de cada tema (QT offscreen)

- [ ] Interfaz reorganizada con barra de estado de juego
  criterio: el árbol de tareas pasa a ser la pantalla principal del proyecto; una barra superior muestra de un vistazo el progreso del plan (como experiencia), la cuota restante si se conoce (como energía) y el coste (como monedas), y quién trabaja ahora; las secciones se reordenan como el menú de un juego; cada agente se muestra como un personaje y elegir modelo y peso de una tarea se presenta como equiparlo; con un agente se ve uno y con varios, un grupo; las funciones y atajos actuales siguen accesibles; textos con i18n; smoke (QT offscreen)

- [ ] Modo juego opcional: vocabulario y logros
  criterio: opción en Ajustes, apagada por defecto en el tema sobrio, que cambia el vocabulario visible (tarea → misión, gate → prueba, bloqueada → derrotada…) sin tocar `plan.md` ni el MCP; logros sencillos por proyecto (primera tarea, sin fallos en una fase, fase completada) guardados en local y sin efecto en el motor; tests del vocabulario y de los logros

## FASE 5B — Control desde el móvil

- [ ] Control remoto por Telegram y Discord
  criterio: desactivado por defecto; con él activo, el usuario puede pedir estado, pausar, continuar, detener y aprobar o rechazar una revisión manual desde el chat; solo se aceptan órdenes de identificadores de usuario de una lista permitida y del chat configurado (cualquier otro se ignora y se registra), y un mensaje del chat nunca llega al agente como instrucción: es una lista cerrada de órdenes, sin comandos libres; detener y aprobar piden confirmación; funciona sin abrir puertos (Telegram por consulta periódica, Discord por gateway); los tokens no aparecen en logs; tests con clientes falsos: usuario no autorizado, orden desconocida, confirmación y aprobación

## FASE 6 — MCP al día

- [ ] Todas las funciones nuevas en el MCP
  criterio: el MCP expone todo lo de Dédalo 3: `grafo(nombre)` (pisos, estado, agente y carril de cada tarea), `ensayo(nombre)`, `validar_plan(nombre)`, `tareas_en_curso(nombre)`, `registro_cambios(nombre)`, `continuar_fase(nombre)`, `pista_tarea(nombre, id, texto)`, `tareas_propuestas(nombre)` con aprobar/descartar, `configurar_lanzamiento` con todas las opciones nuevas y `estado_loop` con carriles, espera de cuota y pausa de fase; las instrucciones del servidor (manual del MCP) explican el flujo nuevo; docs/MCP.md actualizado; tests de cada herramienta

- [ ] Prueba de punta a punta por MCP
  criterio: un test (con agentes falsos) maneja un run completo solo por MCP: configurar, validar, ensayo, lanzar con 2 carriles, ver el grafo, dar una pista, aprobar una tarea descubierta, continuar tras la pausa de fase y terminar; sirve de ejemplo en docs/MCP.md

- [ ] Skills incluidas para usar Dédalo con pocos tokens
  criterio: Dédalo trae cuatro skills cortas que se cargan solo cuando hacen falta: `dedalo-piloto` (vigilar un loop gastando poco: estado antes que log, pocas líneas, sin consultas continuas, `esperar_evento`), `dedalo-plan` (tareas pequeñas, criterios verificables, dependencias y peso de cada tarea), `dedalo-diagnostico` (qué mirar ante un fallo y en qué orden) y `dedalo-reglas` (lo comprobable va a un check del gate y `CONTEXTO.md` queda corto); la guía se escribe una vez y también llega a los clientes sin skills por el manual del MCP y `dedalo://manual`; instalarlas es opcional y nunca sobrescribe las del usuario; tests de instalación, de no sobrescritura y de tamaño máximo de cada skill

- [ ] Respuestas cortas del MCP por defecto
  criterio: las tools de lectura devuelven por defecto un resumen breve y piden más detalle con un parámetro; se añade una tool de resumen del proyecto en pocas líneas (estado, tarea actual, último fallo, qué necesita del usuario); tests del límite de tamaño de cada respuesta

## FASE 7 — Rendimiento (si hace falta, midiendo antes)

- [ ] Medir antes de optimizar
  criterio: el gate guarda la duración de cada check y del total por iteración en metrics.jsonl; Métricas y el MCP muestran los checks más lentos; se mide también el tamaño de los prompts (tokens aproximados de plan, lecciones, mapeo y contexto) y el uso de la GUI con logs grandes; nota `docs/rendimiento.md` con los números y qué merece optimizarse (si nada lo merece, se dice y se cierra la fase)

- [ ] Prompts que no crecen sin control
  criterio: lecciones.md y CONTEXTO.md se compactan cuando pasan de un tamaño configurable (un agente ligero resume lo antiguo conservando lo vigente; el original se archiva en `.dedalo/estado/archivo/`); el prompt de cada tarea incluye solo las partes del mapeo relevantes (archivos de su zona y los que nombra el criterio) además de un resumen global; archivos enormes nunca se pegan enteros (tope por archivo con aviso); tests de compactación, de selección del mapeo y del tope

- [ ] Optimizaciones medidas
  criterio: se aplican solo las optimizaciones que la medición justificó (p. ej. límite de tiempo por check, cachear dependencias entre copias, GUI que no se congela con logs de miles de líneas), cada una con su antes/después en docs/rendimiento.md; tests de regresión de lo optimizado

## FASE 8 — Seguridad

- [ ] Modo aislado opcional
  criterio: opción del proyecto «Aislar agentes y gate»: el agente y el gate corren en un contenedor (Podman o Docker si están instalados) o, en Linux, con bubblewrap, con solo la copia del repo montada, sin acceso al resto del home, y red **cerrada** salvo la necesaria para el proveedor del modelo y una lista configurable (registros de paquetes); si no hay ninguna herramienta disponible se avisa y se ofrece seguir sin aislar; la GUI muestra si un run está aislado; tests de la construcción del comando de aislamiento por plataforma y de la lista de red

- [ ] Secretos y archivos protegidos
  criterio: el entorno que reciben agentes y gate se limpia de variables con pinta de secreto (TOKEN, KEY, SECRET, PASSWORD… configurable, con lista blanca) salvo las que el CLI del agente necesita para su sesión; archivos protegidos por defecto (gate y gate_checks, `.github/workflows/`, plan.md, lecciones.md, `.dedalo/`) que un agente no puede cambiar: si su diff los toca, la tarea no se integra y se avisa; el proyecto puede añadir rutas protegidas; tests de limpieza del entorno y de diffs que tocan archivos protegidos; los tokens de notificaciones (Telegram y demás) pasan de `proyectos.json` en texto plano al keyring del sistema, migrando el valor existente, y esa configuración no se vuelca en logs ni diagnósticos (25)

- [ ] Defensa contra instrucciones escondidas en el repo
  criterio: el prompt del agente y del revisor marca el contenido del repo (código, docs, issues) como datos no fiables cuyas instrucciones no se siguen; el revisor recibe una lista de señales a vigilar en el diff (nuevas llamadas de red, lectura de archivos fuera del repo, cambios en CI, scripts de instalación, ofuscación, secretos escritos) y las reporta como riesgo; un riesgo alto bloquea la integración hasta que el usuario lo aprueba; docs/MANUAL explica el modelo de amenazas; tests con un repo trampa que pide al agente leer ~/.ssh y con diffs sospechosos

- [ ] Auditoría de seguridad del propio Dédalo
  criterio: revisión de mcp_server (qué puede hacer un cliente MCP, validación de rutas y nombres), consentimiento del gate, permisos de archivos en ~/.config/dedalo, webhooks y notificaciones (que no filtren secretos), y dependencias (`pip-audit` en el CI); hallazgos corregidos o documentados en docs/SEGURIDAD.md; SECURITY.md con cómo reportar un problema

## FASE 9 — Documentación y versión 3

- [ ] Documentación del formato nuevo
  criterio: el manual (docs/MANUAL.md y .es.md) queda completo y revisado de punta a punta con todo Dédalo 3 (sección del plan con un ejemplo grande de 3 pisos y una tabla de todas las claves con su significado, valor por defecto y ejemplo; nuevas entradas en problemas frecuentes: tarea esperando a otra bloqueada, respaldo activado, ciclo en el plan); README.md y README.es.md explican el plan por grafo con un ejemplo de 3 pisos (`id`, `depende`, fases con `depende`, `peso`, `agente`/`modelo`, `revisor`, `respaldo`, `gate`, `zona`), el paralelismo y sus límites (recursos, cuota), la cadena de respaldo, la espera de cuota y la revisión cruzada; `llms.txt` y la plantilla de plan generada por `instalar_proyecto` incluyen las claves nuevas; capturas nuevas de la vista de grafo

- [ ] Windows probado en un PC real
  criterio: instalador sin bash, acceso directo, bandeja y un run completo con un agente real, probados en un PC con Windows y anotados en una lista de comprobación; los fallos encontrados se corrigen; el README actualiza el estado de Windows según lo comprobado

- [ ] Preparar la publicación
  criterio: GIF o vídeo corto en el README de un plan convirtiéndose en commits; guía para colaboradores en español e inglés; plantillas de GitHub para reportar fallos y proponer mejoras; el README abre con el público al que va dirigido (quien programa solo o en grupos pequeños con agentes de IA)

- [ ] Release v3.0.0
  criterio: versión 3.0.0 en pyproject; notas con lo nuevo y la garantía de compatibilidad con los planes actuales; CI verde en Linux, macOS y Windows; **push y release solo con el «sí» del usuario**

## FASE 4 — Varios agentes a la vez (después de la versión 3, experimental)

- [ ] Copias aisladas por tarea
  criterio: cada tarea en curso trabaja en su propio `git worktree` (rama de tarea actual) en `.dedalo/trabajo/<run>/<id>`; variables de entorno por copia para que el gate no se pise: `DEDALO_SLOT`, un rango de puertos propio (`DEDALO_PORT_BASE`) y, configurable, carpeta de compilación propia (p. ej. `CARGO_TARGET_DIR`) o compartida; las copias se borran al integrar (también en Windows, con rutas largas y archivos bloqueados contemplados); tests con dos tareas simultáneas en un repo temporal, corridos en el CI de Linux, macOS y Windows

- [ ] Ejecución en paralelo con límite
  criterio: hasta `max_agentes` tareas listas a la vez (por defecto 1 = en fila, ajustable en GUI y MCP); antes de lanzar, Dédalo mira la memoria libre y avisa si no alcanza para los agentes elegidos, con una sugerencia de cuántos usar, sin impedir que el usuario siga; el modo paralelo se marca como experimental en el README hasta que tenga uso real; presupuesto y cuota globales del run, no por tarea; solo el coordinador escribe plan.md, lecciones.md, mapeo.txt, progreso.log y metrics.jsonl (los agentes reciben lo que necesitan en el prompt y devuelven su informe); Detener para todas las tareas en curso dejando su trabajo en sus ramas; tests: dos tareas independientes avanzan a la vez y una dependiente espera a ambas, y el aviso de memoria con valores simulados

- [ ] Informe de cambios de cada tarea
  criterio: al terminar, cada tarea produce un informe (archivos tocados con el diff resumido, qué hizo y por qué, y si tocó algo fuera de su `zona:` opcional) que el coordinador guarda en un registro de cambios del run; si el agente no lo da, se genera del diff y se le pide la explicación de los archivos fuera de zona; tests del informe generado y de la detección fuera de zona

- [ ] Revisor que vigila a las demás tareas
  criterio: antes de integrar una tarea, el revisor recibe su informe, la lista de archivos que están cambiando las tareas en curso y los de los pilares de pisos superiores pendientes que declaran esas zonas; si la tarea tocó archivos que otra está trabajando o que pertenecen a otra zona, no se integra: el revisor pide al agente que lo justifique o lo deshaga, lo reporta en progreso.log/GUI/MCP y, si persiste, la tarea se rehace después de la otra; tests con dos tareas que tocan el mismo archivo

- [ ] Ejecutar con varios carriles
  criterio: arriba de Ejecutar, el estado resumido pasa a una línea (en curso / esperando cuota / parado, progreso del plan y «N carriles activos») con Iniciar / Detener todo / Ejecutar gate; la lista de tareas añade las columnas piso y depende de, y marca el carril de las tareas en curso; las opciones de lanzamiento añaden agentes a la vez y carpeta de compilación compartida/por carril; Logs da un color por carril; smoke de Ejecutar con dos carriles (QT offscreen)

- [ ] Mapeo con varios agentes
  criterio: mapeo.txt lo escribe solo el coordinador, después de cada integración (en el orden de la cola) y a partir de la rama del run, nunca de las copias de las tareas; la actualización es incremental (solo los archivos que tocó la tarea integrada) y al final del run se hace un mapeo completo; cada agente recibe el mapa más reciente al empezar o al rehacer su tarea; el mapa que recibe marca como «en obras por [id]» los archivos que están cambiando otras tareas en curso y las zonas declaradas, y el prompt le pide no tocarlos (el revisor lo comprueba después); tests: mapeo incremental igual al completo, marcas «en obras» con dos tareas simultáneas

- [ ] Integración en cola y conflictos
  criterio: las tareas terminadas se integran de una en una en la rama del run (cola); si una integración da conflicto, la tarea se rehace automáticamente sobre la rama actualizada (con su informe anterior como contexto) hasta 2 veces y luego se marca `[B]` con el motivo; `zona:` se usa también para no lanzar a la vez dos tareas de la misma zona; tests de integración limpia, conflicto resuelto rehaciendo y conflicto que bloquea

## FASE 10 — Trabajar en grupo sobre GitHub (después de la versión 3)

Para grupos pequeños, no empresas, y opcional. Sin sistema propio de invitaciones, roles ni firmas: colaboradores, permisos, revisiones, historial y expulsiones ya los da GitHub. El CI y la protección del repo son responsabilidad del líder o de quien lo administre; Dédalo no los gestiona. Cada persona usa su propio Dédalo con sus cuentas y modelos. El líder decide a quién da acceso; quien sale del repo conserva su copia. Se decidió así tras descartar un diseño con el PC del líder como centro: era más trabajo y menos seguro, porque ejecutaba código ajeno en ese PC.

- [ ] Archivos compartidos por el repo
  criterio: en el repo solo van los archivos de Dédalo pensados para compartir (`plan.md`, `lecciones.md` y `CONTEXTO.md`); los gates, el estado, los logs y la configuración de cuentas y modelos siguen siendo locales de cada persona; cuando varias personas tocan esos archivos no hay conflictos evitables: `lecciones.md` se fusiona sumando las dos partes y las marcas de `plan.md` se resuelven sin perder tareas de nadie; tests con dos clones de un repo temporal

- [ ] Reparto de tareas entre personas
  criterio: `responsable:` en `plan.md` asigna una tarea a una persona (su usuario de GitHub), y Dédalo salta las de otros; antes de empezar una tarea sin responsable, Dédalo hace `git pull`, se la asigna, hace commit y push: si el push se rechaza es que otro llegó antes, y vuelve a mirar el plan; así todos ven quién hace cada cosa al actualizar, y el rechazo de git evita que dos hagan la misma; opcionalmente, si la tarea enlaza una issue, la asigna también en GitHub con `gh issue edit --add-assignee`; una tarea no se inicia hasta que sus dependencias estén integradas en `main`, las haya hecho quien las haya hecho; sin estas claves todo funciona como antes; tests con dos clones y una dependencia entre personas

- [ ] Modo PR
  criterio: opción para que, al terminar una tarea, Dédalo abra un pull request y, si el repo tiene CI, lo espere antes de marcarla hecha; si el CI falla, el motivo vuelve como feedback al siguiente intento; la primera gate sigue corriendo en el PC de quien hizo la tarea; tests con un `gh` falso (CI verde, rojo y agotado el tiempo)

## Más adelante (ideas, sin criterios todavía)
- Índice de símbolos del repo con tree-sitter (funciones, clases y quién las usa) para un mapeo más preciso y para calcular el impacto de una tarea.
- Lecciones globales entre proyectos (opt-in): las lecciones generales de un proyecto disponibles para los demás.
- Modo «test primero» para arreglos: el agente escribe un test que falla, el gate comprueba que falla y luego que pasa con el arreglo.
- Modelos locales (Ollama u otros vía opencode) documentados como agente/respaldo para quien quiera privacidad total.
- Primer uso guiado: comprobar agentes, explicar cómo iniciar sesión y ofrecer un proyecto de ejemplo (el MCP no lo cubre porque presupone un agente ya conectado).
- Firmar el instalador de Windows y macOS para evitar los avisos de «programa no seguro» (tiene coste anual: cuando ya haya usuarios).
- Pasar a inglés los nombres del código y las variables de entorno (solo si llegan colaboradores).
