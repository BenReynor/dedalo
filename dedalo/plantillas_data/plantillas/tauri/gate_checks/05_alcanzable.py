"""Gate (tauri): every backend command can really be reached from the frontend.

Gate, judge and reviewer approved commands with backend and tests that no file
in `src/` ever invoked. This compares `generate_handler![...]` with the
`invoke("name", {...})` calls: commands nobody calls, calls to commands that do
not exist, and required arguments missing from the call.

Exceptions, one command per line: `.dedalo/alcanzable_ignorar.txt`.
"""
import os
import re

HERRAMIENTA = "[tauri]"
EXT_FRONT = (".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte")
_TIPOS_INYECTADOS = re.compile(
    r"^(?:&\s*)?(?:tauri::)?(?:State|AppHandle|App|Window|WebviewWindow|Webview|"
    r"Manager|ipc::)\b|^tauri::")
# A function that forwards its first parameter to invoke(): many projects call
# their commands only through a helper like `llamar("x", {...})`.
_ENVOLTORIO = re.compile(
    r"(?:function\s+|const\s+)(\w+)\b[^\n;{]*?\(\s*(\w+)\b[^)]*\)[^{;]*?(?:=>|\{)"
    r"[\s\S]{0,400}?\binvoke\b[^(\n]*\(\s*\2\b")
_COMANDO_RS = re.compile(
    r"#\[(?:tauri::)?command(\([^\]]*\))?\]\s*(?:#\[[^\]]*\]\s*)*"
    r"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)\s*(?:<[^>]*>)?\s*\(")


def _archivos(raiz, extensiones):
    for carpeta, dirs, nombres in os.walk(raiz):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "target", "dist", "__tests__")]
        for nombre in nombres:
            if nombre.endswith(extensiones) and not re.search(r"\.(test|spec)\.", nombre):
                yield os.path.join(carpeta, nombre)


def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _sin_comentarios(texto):
    texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.S)
    return re.sub(r"(^|[^:\"'])//[^\n]*", r"\1", texto)


def _cierre(texto, inicio, abre, cierra, comillas="\"'`"):
    """Index just past the delimiter closing the one at `inicio`, or -1.

    Rust callers pass only `"`: a `'` there is usually a lifetime (`State<'_, T>`).
    """
    nivel = 0
    comilla = ""
    i = inicio
    while i < len(texto):
        c = texto[i]
        if comilla:
            if c == "\\":
                i += 1
            elif c == comilla:
                comilla = ""
        elif c in comillas:
            comilla = c
        elif c == abre:
            nivel += 1
        elif c == cierra:
            nivel -= 1
            if nivel == 0:
                return i + 1
        i += 1
    return -1


def _partes_nivel_cero(texto):
    """Splits on top-level commas, ignoring (), [], {} and <>."""
    partes, actual, nivel = [], "", 0
    for c in texto:
        if c in "([{<":
            nivel += 1
        elif c in ")]}>":
            nivel -= 1
        if c == "," and nivel == 0:
            partes.append(actual)
            actual = ""
        else:
            actual += c
    return [p.strip() for p in [*partes, actual] if p.strip()]


def registrados(fuentes_rs):
    """Names inside every `generate_handler![...]`, without their module path."""
    nombres = set()
    for texto in fuentes_rs:
        for m in re.finditer(r"generate_handler!\s*\[", texto):
            fin = _cierre(texto, m.end() - 1, "[", "]", comillas='"')
            if fin > 0:
                nombres.update(p.split("::")[-1].strip()
                               for p in texto[m.end():fin - 1].split(",") if p.strip())
    return nombres


def _camel(nombre):
    cabeza, *resto = nombre.split("_")
    return cabeza + "".join(p.capitalize() for p in resto)


def parametros(fuentes_rs):
    """{command: names the frontend must send} (no Option<>, no injected types)."""
    salida = {}
    for texto in fuentes_rs:
        for m in _COMANDO_RS.finditer(texto):
            fin = _cierre(texto, m.end() - 1, "(", ")", comillas='"')
            if fin < 0:
                continue
            snake = "snake_case" in (m.group(1) or "")
            requeridos = []
            for parte in _partes_nivel_cero(texto[m.end():fin - 1]):
                if ":" not in parte:
                    continue
                nombre, tipo = (x.strip() for x in parte.split(":", 1))
                nombre = nombre.removeprefix("mut ").strip().lstrip("_")
                if _TIPOS_INYECTADOS.search(tipo) or re.match(r"(?:std::option::)?Option\s*<", tipo):
                    continue
                requeridos.append(nombre if snake else _camel(nombre))
            salida[m.group(2)] = requeridos
    return salida


def _claves(objeto):
    """Top-level keys of a JS object literal (`{ a, b: 1, ...c }`); None if spread."""
    claves = []
    for parte in _partes_nivel_cero(objeto[1:-1]):
        if parte.startswith("..."):
            return None
        m = re.match(r"[\"']?([A-Za-z_$][\w$]*)[\"']?", parte)
        if m:
            claves.append(m.group(1))
    return claves


def envoltorios(fuentes_front):
    """Names through which the frontend calls commands (invoke + its helpers)."""
    nombres = {"invoke"}
    for texto in fuentes_front:
        nombres.update(m.group(1) for m in _ENVOLTORIO.finditer(texto))
    return nombres


def llamadas(fuentes_front):
    """[(command, keys or None when they cannot be read from the call)]."""
    salida = []
    patron = re.compile(r"\b(?:" + "|".join(sorted(envoltorios(fuentes_front))) + r")\b"
                        r"[^(\n]*\(\s*[\"'`]([A-Za-z0-9_]+)[\"'`]")
    ternario = re.compile(r"\b(?:" + "|".join(sorted(envoltorios(fuentes_front))) + r")\b"
                          r"[^(\n]*\(\s*([^,\n]+\?[^,\n]+)")
    for texto in fuentes_front:
        for m in patron.finditer(texto):
            resto = texto[m.end():].lstrip()
            # The closing quote of the name was consumed by the pattern.
            claves = None
            if resto.startswith(")"):
                claves = []
            elif resto.startswith(","):
                cuerpo = resto[1:].lstrip()
                if cuerpo.startswith("{"):
                    fin = _cierre(cuerpo, 0, "{", "}")
                    if fin > 0:
                        claves = _claves(cuerpo[:fin])
                elif cuerpo.startswith(")"):
                    claves = []
            salida.append((m.group(1), claves))
        # `llamar(pdf ? "a_pdf" : "a_csv", args)`: both names are in use.
        for m in ternario.finditer(texto):
            # Only after the `?`: the condition can hold strings of its own.
            opciones = m.group(1).split("?", 1)[1]
            salida.extend((n, None) for n in re.findall(r"[\"'`](\w+)[\"'`]", opciones))
    return salida


def problemas(fuentes_rs, fuentes_front, ignorar=()):
    registro = registrados(fuentes_rs)
    params = parametros(fuentes_rs)
    usos = llamadas(fuentes_front)
    invocados = {n for n, _c in usos}
    salida = [f"comando sin ninguna llamada desde src/: {n}"
              for n in sorted(registro - invocados - set(ignorar))]
    salida += [f"llamada a un comando no registrado: {n}"
               for n in sorted(invocados - registro - set(ignorar))]
    for nombre, claves in usos:
        if claves is None or nombre in ignorar or nombre not in params:
            continue
        for falta in params[nombre]:
            if falta not in claves:
                salida.append(f"invoke('{nombre}') sin el argumento '{falta}'")
    return list(dict.fromkeys(salida))


def run(env):
    raiz_rs = os.path.join(env.proyecto, "src-tauri", "src")
    raiz_front = os.path.join(env.proyecto, "src")
    if not os.path.isdir(raiz_rs) or not os.path.isdir(raiz_front):
        env.aviso(f"{HERRAMIENTA} sin src-tauri/src o src, se omite")
        return 0
    rs = [_sin_comentarios(_leer(r)) for r in _archivos(raiz_rs, (".rs",))]
    front = [_sin_comentarios(_leer(r)) for r in _archivos(raiz_front, EXT_FRONT)]
    if not registrados(rs):
        env.aviso(f"{HERRAMIENTA} sin generate_handler!, se omite")
        return 0
    ignorar = _leer(os.path.join(env.proyecto, ".dedalo", "alcanzable_ignorar.txt")).split()
    encontrados = problemas(rs, front, ignorar)
    if encontrados:
        env.fail(f"{HERRAMIENTA} {len(encontrados)} problema(s) de comandos no alcanzables")
        print("\n".join(encontrados[:60]))
        return 1
    env.ok(f"{HERRAMIENTA} todos los comandos se invocan desde el frontend")
    return 0
