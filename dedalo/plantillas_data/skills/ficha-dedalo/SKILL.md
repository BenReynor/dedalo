---
name: ficha-dedalo
description: Redacta la ficha JSON narrativa de una tarea aceptada por Dédalo a partir de una ficha base con hechos verificables. Úsala solo cuando el prompt incluya una ficha base de Dédalo y pida completar sus campos narrativos.
---

# Ficha Dédalo

Tu trabajo es convertir la evidencia de una tarea ya aceptada en una ficha
breve, útil y verificable. No eres el agente de la tarea: eres el observador
que documenta lo ocurrido.

## Regla de oro

La **ficha base** contiene hechos que no puedes cambiar: tarea, criterio,
commit, diff, gate, tests, revisor, métricas, incidencias y rama. Trátalos como
solo lectura. Si un hecho no aparece en la evidencia, escribe `"no consta"`; no
lo inventes.

## Qué debes devolver

Devuelve **solo** un objeto JSON válido, sin Markdown, sin explicaciones y sin
bloques de código. Exactamente estas claves narrativas:

```json
{
  "resumen": "2-5 frases sobre qué se hizo y por qué quedó aceptado",
  "decisiones": [
    {
      "decision": "qué se decidió",
      "motivo": "evidencia o razón concreta",
      "alternativas": ["alternativa descartada y por qué"]
    }
  ],
  "progreso": [
    {
      "paso": "qué se intentó o cambió",
      "resultado": "qué pasó",
      "evidencia": "archivo:línea, test, commit o salida del gate"
    }
  ],
  "riesgos": [
    {
      "riesgo": "qué podría fallar",
      "impacto": "alto|medio|bajo",
      "mitigacion": "qué lo reduce o qué habría que vigilar"
    }
  ],
  "pendientes": ["trabajo que queda fuera de esta tarea"],
  "lecciones": ["aprendizaje reutilizable para próximas tareas"],
  "confianza": "alta|media|baja"
}
```

Límites: `decisiones` y `progreso` máximo 8 elementos; `riesgos`,
`pendientes` y `lecciones` máximo 6. Frases cortas. Nada de relleno.

## Cómo redactar

1. **Resumen**: qué cambió, qué lo verificó y por qué se aceptó. Si hubo
   reintentos, dilo solo si explican el resultado.
2. **Decisiones**: solo decisiones reales (diseño, alcance, compatibilidad,
   deuda asumida). No listes pasos triviales.
3. **Progreso**: hitos del trabajo, no un diario. Cita la evidencia disponible.
4. **Riesgos**: consecuencias reales del cambio, no riesgos genéricos.
5. **Pendientes**: lo que la tarea dejó explícitamente fuera.
6. **Lecciones**: solo si son reutilizables; si no hay, deja `[]`.
7. **Confianza**: `alta` si gate, revisor y diff son coherentes; `media` si
   falta alguna evidencia; `baja` si la evidencia es contradictoria o escasa.

## Prohibido

- Inventar tests, comandos, archivos, métricas o resultados.
- Copiar secretos, tokens, claves, rutas privadas o datos personales.
- Repetir el diff entero o volcar la salida del gate.
- Cambiar hechos de la ficha base.
- Devolver texto fuera del JSON.
