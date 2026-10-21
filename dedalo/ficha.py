#!/usr/bin/env python3
"""JSON fichas of accepted tasks (opt-in).

The loop builds a deterministic base with the facts it already owns (task,
commit, diff, gate, reviewer, metrics) and, only when `FICHA_ACTIVA=1`, asks an
agent for the narrative fields. The observer runs in an isolated temporary
directory and never blocks the commit, the merge or the loop: any failure is
recorded and the base ficha is kept with `incompleta=true`.

No PySide dependencies.
"""

import datetime
import json
import os
import re
import subprocess
import tempfile
import unicodedata
import uuid

from . import rutas
from .loop_agentes import agente_ok, detectar_agente, run_agente
from .loop_git import run_git
from .loop_util import incidencia, logx

NARRATIVAS = ("resumen", "decisiones", "progreso", "riesgos", "pendientes",
              "lecciones", "confianza")
CONFIANZAS = ("alta", "media", "baja")
SKILL = os.path.join(os.path.dirname(__file__), "plantillas_data", "skills",
                     "ficha-dedalo", "SKILL.md")

_PATRON_SECRETO = (
    re.compile(
        r"(?i)((?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|"
        r"password|passwd|authorization)\s*[:=]\s*)(['\"]?)([^\s'\"]{6,})"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{10,}|"
               r"AKIA[0-9A-Z]{16})\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{10,}=*"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?"
               r"-----END [A-Z ]*PRIVATE KEY-----", re.S),
)
_PATRON_TEST = re.compile(
    r"(?i)\b(pytest|unittest|passed|failed|failure|error|tests?|assert)\b"
    r"|[✓✗]")


def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _leer_cola(ruta, lineas=80):
    texto = _leer(ruta)
    if not texto:
        return ""
    return "\n".join(texto.splitlines()[-lineas:])


def redactar(texto):
    """Removes obvious secrets from evidence before it leaves the repo."""
    texto = texto or ""
    for patron in _PATRON_SECRETO:
        if patron is _PATRON_SECRETO[0]:
            texto = patron.sub(r"\1\2***", texto)
        else:
            texto = patron.sub("***", texto)
    return texto


def _truncar(texto, maximo):
    texto = texto or ""
    if maximo <= 0 or len(texto) <= maximo:
        return texto
    return texto[:maximo] + "\n… (truncado)"


def _limpiar(texto, maximo):
    return _truncar(redactar(texto), maximo)


def _slug(texto):
    normal = unicodedata.normalize("NFKD", texto or "")
    ascii_ = normal.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-") or "tarea"


def _ahora():
    return datetime.datetime.now(datetime.timezone.utc)


def _archivos_git(proyecto, commit):
    if not commit:
        return []
    rc, salida, _ = run_git(proyecto, "show", "--name-status", "--format=",
                            "--no-renames", commit)
    if rc != 0:
        return []
    archivos = []
    for linea in salida.splitlines():
        partes = linea.split("\t")
        if len(partes) < 2:
            continue
        estado = partes[0].strip()
        if estado[:1] in ("R", "C") and len(partes) >= 3:
            archivos.append({"estado": estado, "desde": partes[1],
                             "ruta": partes[2]})
        else:
            archivos.append({"estado": estado, "ruta": partes[-1]})
    return archivos


def _diff_git(cfg, commit):
    if not commit:
        return "", ""
    _, stat, _ = run_git(cfg.proyecto, "show", "--stat", "--format=",
                         "--no-renames", commit)
    _, diff, _ = run_git(cfg.proyecto, "show", "--format=", "--patch",
                         "--no-ext-diff", "--no-renames", "--unified=3", commit)
    stat = _truncar(redactar(stat), 4000)
    if cfg.ficha_diff_completo:
        return stat, _truncar(redactar(diff), 0)
    return stat, _truncar(redactar(diff), cfg.ficha_max_diff)


def _tests_gate(salida):
    tests = []
    for linea in (salida or "").splitlines():
        if _PATRON_TEST.search(linea):
            tests.append(linea.strip())
    return [_truncar(redactar(t), 500) for t in tests[-25:]]


def _juez_gate(salida, rc):
    lineas = [li.strip() for li in (salida or "").splitlines()
              if "JUEZ" in li.upper()]
    return {
        "resultado": "pass" if rc == 0 else "fail",
        "detalle": [_truncar(redactar(li), 500) for li in lineas[-10:]],
    }


def _metrica(cfg, tarea, iteracion, fase=None):
    """Last metrics.jsonl line for this task (optionally filtered by phase)."""
    try:
        with open(cfg.metrics, encoding="utf-8", errors="replace") as f:
            lineas = f.readlines()[-2000:]
    except OSError:
        return None
    for linea in reversed(lineas):
        try:
            dato = json.loads(linea)
        except ValueError:
            continue
        if dato.get("tarea") != tarea:
            continue
        if int(dato.get("iter", 0)) != int(iteracion):
            continue
        if fase is None and dato.get("fase"):
            continue
        if fase is not None and dato.get("fase") != fase:
            continue
        return dato
    return None


def construir_base(cfg, *, tarea, criterio, iteracion, rama, commit,
                   commit_msg, gate_rc, gate_salida, salida_agente,
                   resultado_revision="no_ejecutado", feedback_revision="",
                   merge_ok=True, revisor_modo=""):
    """Deterministic ficha: facts only, no model involved."""
    stat, diff = _diff_git(cfg, commit)
    diff_truncado = (not cfg.ficha_diff_completo and bool(diff)
                     and len(diff) > cfg.ficha_max_diff)
    proyecto = getattr(cfg, "nombre", "") or os.path.basename(
        cfg.proyecto.rstrip("/\\"))
    fecha = _ahora().strftime("%Y%m%dT%H%M%SZ")
    ficha_id = f"{fecha}-{_slug(tarea)[:40]}-{uuid.uuid4().hex[:6]}"
    return {
        "schema": "dedalo.ficha/1",
        "id": ficha_id,
        "created_at": _ahora().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "proyecto": proyecto,
        "tarea": tarea,
        "criterio": criterio or "",
        "iteracion": int(iteracion),
        "rama": rama or "",
        "estado": "aceptada" if merge_ok else "no_aceptada",
        "resumen": "",
        "decisiones": [],
        "progreso": [],
        "cambios": {
            "archivos": _archivos_git(cfg.proyecto, commit),
            "estadisticas": stat,
            "diff": diff,
            "diff_truncado": diff_truncado,
        },
        "verificacion": {
            "gate": {
                "rc": int(gate_rc),
                "resultado": "pass" if int(gate_rc) == 0 else "fail",
                "salida": _limpiar(gate_salida, cfg.ficha_max_salida),
            },
            "tests": _tests_gate(gate_salida),
            "revisor": {
                "modo": revisor_modo or "no_ejecutado",
                "resultado": resultado_revision or "no_ejecutado",
                "detalle": _limpiar(feedback_revision, 4000),
            },
            "juez": _juez_gate(gate_salida, gate_rc),
        },
        "metricas": {
            "tarea": _metrica(cfg, tarea, iteracion),
            "observador": None,
        },
        "evidencia": {
            "resumen_agente": _limpiar(salida_agente, cfg.ficha_max_salida),
            "progreso_log": _limpiar(_leer_cola(cfg.log, 80), 12000),
        },
        "merge": {
            "ok": bool(merge_ok),
            "commit": commit or "",
            "mensaje": commit_msg or "",
        },
        "riesgos": [],
        "pendientes": [],
        "lecciones": [],
        "confianza": "media",
        "incompleta": False,
        "motivo_incompleta": "",
        "generado_por": {
            "agente": "",
            "modelo": "",
            "skill": "ficha-dedalo/1",
        },
    }


def _resolver_agente(cfg):
    agente = (getattr(cfg, "agente_ficha", "") or "auto").strip()
    if agente == "auto":
        agente = (cfg.agente_tarea or "").strip()
    if not agente or agente == "auto":
        agente = detectar_agente(cfg) or ""
    if not agente or not agente_ok(agente, cfg):
        return "", ""
    modelo = (getattr(cfg, "modelo_ficha", "") or "").strip()
    if not modelo and agente == cfg.agente_tarea:
        modelo = (cfg.modelo_tarea or "").strip()
    if agente != "opencode":
        modelo = ""
    return agente, modelo


def _prompt(base, skill):
    return (
        "Eres el OBSERVADOR de Dédalo. Documentas una tarea ya aceptada.\n"
        "Sigue exactamente la skill y devuelve SOLO el JSON narrativo.\n"
        "No cambies ni repitas los hechos de la ficha base.\n\n"
        f"<SKILL>\n{skill}\n</SKILL>\n\n"
        "FICHA BASE (hechos inmutables):\n"
        f"{json.dumps(base, ensure_ascii=False, indent=2)}\n\n"
        "Completa únicamente: resumen, decisiones, progreso, riesgos, "
        "pendientes, lecciones y confianza. Si un dato no consta, escribe "
        "\"no consta\". Responde solo con el objeto JSON."
    )


def _extraer_json(texto):
    """First JSON object with narrative fields (ignores logs/usage objects)."""
    decodificador = json.JSONDecoder()
    candidatos = []
    for i, char in enumerate(texto or ""):
        if char != "{":
            continue
        try:
            dato, _ = decodificador.raw_decode(texto[i:])
        except ValueError:
            continue
        if isinstance(dato, dict):
            candidatos.append(dato)
    for dato in candidatos:
        if any(clave in dato for clave in NARRATIVAS):
            return dato
    return None


def _lista_texto(valor):
    if isinstance(valor, str):
        return [valor.strip()] if valor.strip() else []
    if not isinstance(valor, list):
        return []
    return [str(v).strip() for v in valor if isinstance(v, (str, int, float))
            and str(v).strip()]


def _items(valor):
    return valor if isinstance(valor, list) else []


def _normalizar(datos):
    """Keeps only the narrative contract, with stable types."""
    resumen = datos.get("resumen")
    resumen = resumen.strip() if isinstance(resumen, str) else ""
    decisiones = []
    for item in _items(datos.get("decisiones")):
        if isinstance(item, str) and item.strip():
            decisiones.append({"decision": item.strip(), "motivo": "no consta",
                               "alternativas": []})
        elif isinstance(item, dict):
            decision = str(item.get("decision") or "").strip()
            if decision:
                alternativas = item.get("alternativas") or []
                decisiones.append({
                    "decision": decision,
                    "motivo": str(item.get("motivo") or "no consta").strip(),
                    "alternativas": _lista_texto(alternativas),
                })
    progreso = []
    for item in _items(datos.get("progreso")):
        if isinstance(item, str) and item.strip():
            progreso.append({"paso": item.strip(), "resultado": "no consta",
                             "evidencia": "no consta"})
        elif isinstance(item, dict):
            paso = str(item.get("paso") or "").strip()
            if paso:
                progreso.append({
                    "paso": paso,
                    "resultado": str(item.get("resultado") or "no consta").strip(),
                    "evidencia": str(item.get("evidencia") or "no consta").strip(),
                })
    riesgos = []
    for item in _items(datos.get("riesgos")):
        if isinstance(item, str) and item.strip():
            riesgos.append({"riesgo": item.strip(), "impacto": "medio",
                            "mitigacion": "no consta"})
        elif isinstance(item, dict):
            riesgo = str(item.get("riesgo") or "").strip()
            if riesgo:
                impacto = str(item.get("impacto") or "medio").lower()
                riesgos.append({
                    "riesgo": riesgo,
                    "impacto": impacto if impacto in ("alto", "medio", "bajo")
                    else "medio",
                    "mitigacion": str(item.get("mitigacion") or "no consta").strip(),
                })
    confianza = str(datos.get("confianza") or "media").strip().lower()
    return {
        "resumen": resumen,
        "decisiones": decisiones[:8],
        "progreso": progreso[:8],
        "riesgos": riesgos[:6],
        "pendientes": _lista_texto(datos.get("pendientes"))[:6],
        "lecciones": _lista_texto(datos.get("lecciones"))[:6],
        "confianza": confianza if confianza in CONFIANZAS else "media",
    }


def _observar(cfg, base, agente, modelo):
    skill = _leer(SKILL)
    if not skill.strip():
        return None, "skill_no_disponible"
    with tempfile.TemporaryDirectory(prefix="dedalo-ficha-") as tmp:
        try:
            subprocess.run(["git", "init", "-q"], cwd=tmp,
                           capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass
        salida = os.path.join(tmp, "respuesta")
        entorno = dict(getattr(cfg, "environ", {}) or {})
        entorno["PWD"] = tmp
        for clave in ("OLDPWD", "GIT_DIR", "GIT_WORK_TREE"):
            entorno.pop(clave, None)
        rc, _ = run_agente(
            cfg, agente, salida, modelo, _prompt(base, skill), base["tarea"], 0,
            cwd=tmp, timeout=cfg.timeout_ficha, dir_trabajo=tmp, fase="ficha",
            env=entorno)
        texto = _leer(salida)
        if rc != 0:
            return None, f"agente_rc_{rc}"
        datos = _extraer_json(texto)
        if datos is None:
            return None, "json_invalido"
        return _normalizar(datos), ""


def _escribir(ruta, datos):
    directorio = os.path.dirname(ruta)
    os.makedirs(directorio, exist_ok=True)
    fd, temporal = tempfile.mkstemp(prefix=".ficha-", suffix=".tmp",
                                    dir=directorio)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temporal, ruta)
    except Exception:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise


def _indexar(cfg, ruta, base):
    indice = getattr(cfg, "fichas_index", rutas.fichas_index(cfg.proyecto))
    linea = json.dumps({
        "id": base["id"],
        "created_at": base["created_at"],
        "tarea": base["tarea"],
        "estado": base["estado"],
        "commit": base["merge"]["commit"],
        "incompleta": base["incompleta"],
        "ruta": os.path.relpath(ruta, cfg.proyecto),
    }, ensure_ascii=False)
    try:
        os.makedirs(os.path.dirname(indice), exist_ok=True)
        with open(indice, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass


def _generar(cfg, **datos):
    base = construir_base(cfg, **datos)
    ruta = os.path.join(cfg.fichas_dir, base["id"] + ".json")
    # The first write is a safety net: if the process dies during the observer,
    # the ficha exists but is explicitly marked as pending, never as complete.
    base["incompleta"] = True
    base["motivo_incompleta"] = "pendiente"
    _escribir(ruta, base)

    agente, modelo = _resolver_agente(cfg)
    base["generado_por"]["agente"] = agente
    base["generado_por"]["modelo"] = modelo
    if not agente:
        base["incompleta"] = True
        base["motivo_incompleta"] = "sin_agente"
        base["confianza"] = "baja"
    else:
        narrativa, motivo = _observar(cfg, base, agente, modelo)
        if narrativa is None:
            base["incompleta"] = True
            base["motivo_incompleta"] = motivo
            base["confianza"] = "baja"
        else:
            base["incompleta"] = False
            base["motivo_incompleta"] = ""
            base.update(narrativa)
        base["metricas"]["observador"] = _metrica(
            cfg, base["tarea"], 0, fase="ficha")

    _escribir(ruta, base)
    _indexar(cfg, ruta, base)
    logx(cfg.log, f"FICHA: {ruta}"
                  + (" (incompleta: " + base["motivo_incompleta"] + ")"
                     if base["incompleta"] else ""))
    return {"ruta": ruta, "id": base["id"], "incompleta": base["incompleta"]}


def generar(cfg, *, tarea, criterio, iteracion, rama, commit, commit_msg,
            gate_rc, gate_salida, salida_agente, resultado_revision="no_ejecutado",
            feedback_revision="", merge_ok=True, revisor_modo=""):
    """Writes one ficha per accepted task; never raises into the loop.

    Returns `{ruta, id, incompleta}` or None if the ficha is disabled or could
    not be written at all.
    """
    activa = getattr(cfg, "ficha_activa", "0")
    if activa not in (True, 1, "1", "true", "True"):
        return None
    try:
        return _generar(
            cfg, tarea=tarea, criterio=criterio, iteracion=iteracion,
            rama=rama, commit=commit, commit_msg=commit_msg,
            gate_rc=gate_rc, gate_salida=gate_salida,
            salida_agente=salida_agente,
            resultado_revision=resultado_revision,
            feedback_revision=feedback_revision, merge_ok=merge_ok,
            revisor_modo=revisor_modo)
    except Exception as exc:  # noqa: BLE001 - never break the loop
        logx(cfg.log, f"FICHA: error al generarla: {exc}")
        try:
            incidencia(cfg.incidencias, "ficha_error", str(exc),
                       tarea=tarea, iteracion=iteracion, rama=rama)
        except Exception:
            pass
        return None
