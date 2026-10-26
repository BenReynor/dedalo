"""Visual design system: semantic colors, typography and components.

Based on desktop design references (Linear, Vercel, VS Code).
A single accent, coherent neutral scale, visible focus, WCAG AA contrast.
"""

import re

# ─── FONTS ────────────────────────────────────────────────────────

# Preferred fonts for desktop apps (avoid Inter, Roboto, Arial)
# If they are not installed, Qt falls back to the system font
FONT_UI_FAMILIES = [
    "JetBrains Mono",   # mono for code/logs
    "Geist Mono",       # alternative mono
    "Fira Code",        # mono fallback with ligatures
    "Monospace",        # generic fallback
]

FONT_UI_PRIMARY = [
    "Outfit",           # clean, modern UI
    "DM Sans",          # neutral, versatile
    "Plus Jakarta Sans",# polished
    "Source Sans 3",    # legible when dense
    "System",           # native fallback (Segoe UI / San Francisco / Ubuntu)
]

FONT_MONO = "JetBrains Mono"  # preferred monospace

# Lazy font initialization (requires QApplication to be created)
_FUENTES: dict[str, str | None] = {"mono": None, "ui": None}


def _inicializar_fuentes():
    """Registers the fonts installed on the system for use in QSS.
    Must be called after creating QApplication."""
    global _FUENTES
    if _FUENTES["mono"] is not None:
        return
    from PySide6.QtGui import QFontDatabase
    familias = QFontDatabase.families()
    _FUENTES["mono"] = next((f for f in FONT_UI_FAMILIES if f in familias), "Monospace")
    _FUENTES["ui"] = next((f for f in FONT_UI_PRIMARY if f in familias), "System")


def _get_fuente_mono():
    if _FUENTES["mono"] is None:
        _inicializar_fuentes()
    return _FUENTES["mono"]


def _get_fuente_ui():
    if _FUENTES["ui"] is None:
        _inicializar_fuentes()
    return _FUENTES["ui"]


# ─── TYPOGRAPHIC SCALE (Major Third 1.25x) ────────────────────────

# 14px base for dense desktop
TEXT_XS = "10px"      # captions, badges
TEXT_SM = "11px"      # secondary labels, sidebar
TEXT_BASE = "13px"    # body, inputs, buttons
TEXT_MD = "16px"      # subheadings
TEXT_LG = "20px"      # section headings
TEXT_XL = "25px"      # page titles

# Line heights
LH_TIGHT = "1.2"      # buttons, labels
LH_NORMAL = "1.4"     # inputs, table cells
LH_RELAXED = "1.6"    # paragraphs

# Letter spacing
LS_UPPER = "0.06em"   # labels uppercase
LS_HEADING = "-0.01em"
LS_BODY = "0"

# ─── SPACING (4px base) ────────────────────────────────────────

SPACE_1 = "2px"
SPACE_2 = "4px"
SPACE_3 = "6px"
SPACE_4 = "8px"
SPACE_5 = "10px"
SPACE_6 = "12px"
SPACE_8 = "16px"
SPACE_10 = "20px"
SPACE_12 = "24px"
SPACE_16 = "32px"

# Border radius
RADIUS_SM = "4px"
RADIUS_MD = "6px"
RADIUS_LG = "8px"
RADIUS_XL = "12px"

# Shadows (directional, no glow)
SHADOW_SM = "0 1px 2px rgba(0,0,0,0.05)"
SHADOW_MD = "0 4px 6px -1px rgba(0,0,0,0.07), 0 2px 4px -2px rgba(0,0,0,0.05)"
SHADOW_LG = "0 10px 15px -3px rgba(0,0,0,0.08), 0 4px 6px -4px rgba(0,0,0,0.04)"
SHADOW_XL = "0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.05)"

# Transitions (no bounce)
TRANSITION_FAST = "100ms ease"
TRANSITION_NORMAL = "150ms ease"
TRANSITION_SLOW = "200ms ease"

# ─── SEMANTIC COLORS ───────────────────────────────────────────

# Neutrals: Slate (cool blue, clean, Linear/Vercel style)
NEUTRAL_SLATE = {
    50:  "#f8fafc",
    100: "#f1f5f9",
    200: "#e2e8f0",
    300: "#cbd5e1",
    400: "#94a3b8",
    500: "#64748b",
    600: "#475569",
    700: "#334155",
    800: "#1e293b",
    900: "#0f172a",
    950: "#020617",
}

# Neutrals: Zinc (cool neutral, Vercel/Linear style)
NEUTRAL_ZINC = {
    50:  "#fafafa",
    100: "#f4f4f5",
    200: "#e4e4e7",
    300: "#d4d4d8",
    400: "#a1a1aa",
    500: "#71717a",
    600: "#52525b",
    700: "#3f3f46",
    800: "#27272a",
    900: "#18181b",
    950: "#09090b",
}

# Neutrals: Gray (pure gray, classic)
NEUTRAL_GRAY = {
    50:  "#f9fafb",
    100: "#f3f4f6",
    200: "#e5e7eb",
    300: "#d1d5db",
    400: "#9ca3af",
    500: "#6b7280",
    600: "#4b5563",
    700: "#374151",
    800: "#1f2937",
    900: "#111827",
    950: "#030712",
}

# Neutrals: Stone (warm, Notion/writing style)
NEUTRAL_STONE = {
    50:  "#fafaf9",
    100: "#f5f5f4",
    200: "#e7e5e4",
    300: "#d6d3d1",
    400: "#a8a29e",
    500: "#78716c",
    600: "#57534e",
    700: "#44403c",
    800: "#292524",
    900: "#1c1917",
    950: "#0c0a09",
}

# Neutrals by name for easy access
NEUTRALS = {
    "slate": NEUTRAL_SLATE,
    "zinc": NEUTRAL_ZINC,
    "gray": NEUTRAL_GRAY,
    "stone": NEUTRAL_STONE,
}

# Available accents (sat < 75% for readability)
ACCENTS = {
    "blue": {      # Electric Blue - technical
        50:  "#eff6ff", 100: "#dbeafe", 400: "#60a5fa",
        500: "#3b82f6", 600: "#2563eb", 700: "#1d4ed8", 900: "#1e3a8a",
    },
    "teal": {      # Teal - data, productivity
        50:  "#f0fdfa", 100: "#ccfbf1", 400: "#2dd4bf",
        500: "#14b8a6", 600: "#0d9488", 700: "#0f766e", 900: "#134e4a",
    },
    "emerald": {   # Emerald - success, clean
        50:  "#ecfdf5", 100: "#d1fae5", 400: "#34d399",
        500: "#10b981", 600: "#059669", 700: "#047857", 900: "#065f46",
    },
    "green": {     # Green - nature
        50:  "#f0fdf4", 100: "#dcfce7", 400: "#4ade80",
        500: "#22c55e", 600: "#16a34a", 700: "#15803d", 900: "#14532d",
    },
    "amber": {     # Amber - warm, creative
        50:  "#fffbeb", 100: "#fef3c7", 400: "#fbbf24",
        500: "#f59e0b", 600: "#d97706", 700: "#b45309", 900: "#92400e",
    },
    "orange": {    # Orange - energy
        50:  "#fff7ed", 100: "#ffedd5", 400: "#fb923c",
        500: "#f97316", 600: "#ea580c", 700: "#c2410c", 900: "#9a3412",
    },
    "red": {       # Red - danger, error
        50:  "#fef2f2", 100: "#fee2e2", 400: "#f87171",
        500: "#ef4444", 600: "#dc2626", 700: "#b91c1c", 900: "#991b1b",
    },
    "rose": {      # Rose - modern, brand
        50:  "#fff1f2", 100: "#ffe4e6", 400: "#fb7185",
        500: "#f43f5e", 600: "#e11d48", 700: "#be123c", 900: "#9f1239",
    },
    "violet": {    # Violet - premium (OK for data viz)
        50:  "#f5f3ff", 100: "#ede9fe", 400: "#a78bfa",
        500: "#8b5cf6", 600: "#7c3aed", 700: "#6d28d9", 900: "#5b21b6",
    },
    "purple": {    # Purple - creative
        50:  "#faf5ff", 100: "#f3e8ff", 400: "#c084fc",
        500: "#a855f7", 600: "#9333ea", 700: "#7e22ce", 900: "#6b21a8",
    },
    "indigo": {    # Indigo - enterprise
        50:  "#eef2ff", 100: "#e0e7ff", 400: "#818cf8",
        500: "#6366f1", 600: "#4f46e5", 700: "#4338ca", 900: "#312e81",
    },
    "sky": {       # Sky - light, airy
        50:  "#f0f9ff", 100: "#e0f2fe", 400: "#38bdf8",
        500: "#0ea5e9", 600: "#0284c7", 700: "#0369a1", 900: "#075985",
    },
    "cyan": {      # Cyan - technical
        50:  "#ecfeff", 100: "#cffafe", 400: "#22d3ee",
        500: "#06b6d4", 600: "#0891b2", 700: "#0e7490", 900: "#164e63",
    },
}

# Aliases for compatibility
NEUTRAL = NEUTRAL_SLATE
ACCENT = ACCENTS["blue"]

# Status (semantic, not just color)
STATUS_SUCCESS = "#16a34a"
STATUS_WARNING = "#d97706"
STATUS_ERROR = "#dc2626"
STATUS_INFO = "#2563eb"

# ─── SHARED COLORS (cockpit) ──────────────────────────────────────
# Global tokens for panels/plots (avoids loose hex values in the widgets).
ACCENTO_CABINA = "#d97706"  # instrument amber
ACCENTO_CABINA_CLARO = "#f59e0b"
DATOS_EXITO = "#22c55e"
DATOS_ERROR = "#ef4444"
DATOS_INFO = "#3b82f6"

# ─── QSS GENERATOR ────────────────────────────────────────────────

def _qss_variables(tema: str) -> dict:
    """Returns the token dictionary for the theme."""

    # Hardcoded special themes
    if tema == "Hacker":
        return _build_hacker_theme()
    if tema == "Cyberpunk":
        return _build_cyberpunk_theme()

    # Parse theme: "Neutral/Accent [Light|Dark]"
    # Examples: "Slate/Blue Oscuro", "Zinc/Teal Claro", "Stone/Amber Oscuro"
    parts = tema.split()
    if len(parts) >= 2:
        neutral_accent = parts[0].split("/")
        if len(neutral_accent) == 2:
            neutral_name = neutral_accent[0].lower()
            accent_name = neutral_accent[1].lower()
            is_dark = "Oscuro" in tema
            if neutral_name in NEUTRALS and accent_name in ACCENTS:
                return _build_theme(neutral_name, accent_name, is_dark)

    # Fallback: legacy themes
    is_dark = tema in ("Oscuro", "Hacker")
    if tema == "Hacker":
        return _build_hacker_theme()

    return _build_theme("slate", "blue", is_dark)


def _build_theme(neutral_name: str, accent_name: str, is_dark: bool) -> dict:
    """Builds a theme from neutral + accent + light/dark mode."""
    neutral = NEUTRALS[neutral_name]
    accent = ACCENTS[accent_name]

    if is_dark:
        return {
            "bg_app":       neutral[950],
            "bg_panel":     neutral[900],
            "bg_elevated":  neutral[800],
            "bg_sunken":    "rgba(0,0,0,0.3)",
            "bg_overlay":   "rgba(0,0,0,0.6)",

            "text_primary":   neutral[50],
            "text_secondary": neutral[400],
            "text_tertiary":  neutral[500],
            "text_disabled":  neutral[700],
            "text_inverse":   neutral[950],

            "border_subtle":  "rgba(255,255,255,0.04)",
            "border_default": "rgba(255,255,255,0.08)",
            "border_strong":  "rgba(255,255,255,0.14)",
            "border_focus":   accent[600],

            "action_primary":       accent[600],
            "action_primary_hover": accent[700],
            "action_primary_active": accent[900],
            "action_primary_text":  "#ffffff",
            "action_secondary":     neutral[800],
            "action_secondary_hover": neutral[700],

            "surface_hover":    "rgba(255,255,255,0.05)",
            "surface_selected": f"rgba({_hex_to_rgb(accent[600])}, 0.15)",
            "surface_active":   f"rgba({_hex_to_rgb(accent[600])}, 0.20)",

            "danger_border":    "rgba(220,38,38,0.35)",
            "danger_hover":     "rgba(220,38,38,0.16)",
            "danger_hover_text": "#f87171",

            "status_success": STATUS_SUCCESS,
            "status_warning": STATUS_WARNING,
            "status_error":   STATUS_ERROR,
            "status_info":    STATUS_INFO,

            "accent_rgb":         _hex_to_rgb(accent[600]),
            "accent_rgb_claro":   _hex_to_rgb(accent[400]),
            "status_success_rgb": _hex_to_rgb(STATUS_SUCCESS),
            "status_error_rgb":   _hex_to_rgb(STATUS_ERROR),
            "status_warning_rgb": _hex_to_rgb(STATUS_WARNING),

            "shadow_sm": SHADOW_SM,
            "shadow_md": SHADOW_MD,
            "shadow_lg": SHADOW_LG,
            "shadow_xl": SHADOW_XL,

            "btn_text_primary": "#ffffff",
            "btn_text_hover": "#ffffff",
            "btn_text_disabled": neutral[600],
            "btn_bg_hover": accent[700],
            "btn_bg_active": accent[900],
            "btn_bg_disabled": neutral[800],
            "btn_border_disabled": neutral[800],
        }

    # Light
    return {
        "bg_app":       neutral[50],
        "bg_panel":     "#ffffff",
        "bg_elevated":  "#ffffff",
        "bg_sunken":    neutral[100],
        "bg_overlay":   "rgba(0,0,0,0.4)",

        "text_primary":   neutral[900],
        "text_secondary": neutral[500],
        "text_tertiary":  neutral[400],
        "text_disabled":  neutral[300],
        "text_inverse":   "#ffffff",

        "border_subtle":  neutral[100],
        "border_default": neutral[200],
        "border_strong":  neutral[300],
        "border_focus":   accent[600],

        "action_primary":       accent[600],
        "action_primary_hover": accent[700],
        "action_primary_active": accent[900],
        "action_primary_text":  "#ffffff",
        "action_secondary":     neutral[100],
        "action_secondary_hover": neutral[200],

"surface_hover":    neutral[100],
            "surface_selected": f"rgba({_hex_to_rgb(accent[600])}, 0.08)",
            "surface_active":   f"rgba({_hex_to_rgb(accent[600])}, 0.12)",

            "danger_border":    ACCENTS["red"][100],
            "danger_hover":     ACCENTS["red"][50],
            "danger_hover_text": ACCENTS["red"][700],

        "status_success": STATUS_SUCCESS,
        "status_warning": STATUS_WARNING,
        "status_error":   STATUS_ERROR,
        "status_info":    STATUS_INFO,

        "accent_rgb":         _hex_to_rgb(accent[600]),
        "accent_rgb_claro":   _hex_to_rgb(accent[400]),
        "status_success_rgb": _hex_to_rgb(STATUS_SUCCESS),
        "status_error_rgb":   _hex_to_rgb(STATUS_ERROR),
        "status_warning_rgb": _hex_to_rgb(STATUS_WARNING),

        "shadow_sm": SHADOW_SM,
        "shadow_md": SHADOW_MD,
        "shadow_lg": SHADOW_LG,
        "shadow_xl": SHADOW_XL,

        "btn_text_primary": "#ffffff",
        "btn_text_hover": "#ffffff",
        "btn_text_disabled": neutral[400],
        "btn_bg_hover": accent[700],
        "btn_bg_active": accent[900],
        "btn_bg_disabled": neutral[200],
        "btn_border_disabled": neutral[200],
    }


def _hex_to_rgb(hex_color: str) -> str:
    """Converts #RRGGBB to 'R, G, B' for rgba()."""
    h = hex_color.lstrip("#")
    return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"


def _build_hacker_theme():
    """Special Hacker theme (terminal green)."""
    return {
        "bg_app":       "#04080a", "bg_panel":     "#071009", "bg_elevated":  "#0a1a0e",
        "bg_sunken":    "#04180d", "bg_overlay":   "rgba(0,0,0,0.6)",
        "text_primary":   "#00ff99", "text_secondary": "#00cc77", "text_tertiary":  "#00aa66",
        "text_disabled":  "#006644", "text_inverse":   "#04080a",
        "border_subtle":  "#0f3d24", "border_default": "#1a5c3a", "border_strong":  "#2a7a4e",
        "border_focus":   "#00ff77",
        "action_primary":       "#00ff77", "action_primary_hover": "#33ff99", "action_primary_active": "#00cc5f",
        "action_primary_text":  "#04080a", "action_secondary":     "#0a1a0e", "action_secondary_hover": "#1a3a2a",
        "surface_hover":     "rgba(0,255,153,0.08)", "surface_selected":  "rgba(0,255,153,0.15)",
        "surface_active":    "rgba(0,255,153,0.20)",
        "danger_border":     "#2a7a4e", "danger_hover": "rgba(255,68,68,0.15)", "danger_hover_text": "#ff6666",
        "status_success": "#00cc55", "status_warning": "#ffaa00", "status_error": "#ff4444", "status_info": "#00aaff",
        "accent_rgb": "0, 255, 153", "accent_rgb_claro": "51, 255, 153",
        "status_success_rgb": "0, 204, 85", "status_error_rgb": "255, 68, 68",
        "status_warning_rgb": "255, 170, 0",
        "shadow_sm": SHADOW_SM, "shadow_md": SHADOW_MD, "shadow_lg": SHADOW_LG, "shadow_xl": SHADOW_XL,
        "btn_text_primary": "#04080a", "btn_text_hover": "#04080a", "btn_text_disabled": "#2e7a52",
        "btn_bg_hover": "#33ff99", "btn_bg_active": "#00cc5f", "btn_bg_disabled": "#0a1a0e", "btn_border_disabled": "#0a1a0e",
    }


def _build_cyberpunk_theme():
    """Cyberpunk theme (purple/fuchsia neon on graphite)."""
    return {
        "bg_app":       "#0b0612", "bg_panel":     "#150a24", "bg_elevated":  "#1f0f35",
        "bg_sunken":    "rgba(0,0,0,0.35)", "bg_overlay": "rgba(0,0,0,0.65)",
        "text_primary":   "#f3ecff", "text_secondary": "#c4b0e8", "text_tertiary":  "#8a6fb0",
        "text_disabled":  "#4c3a66", "text_inverse":   "#0b0612",
        "border_subtle":  "rgba(224,164,255,0.07)", "border_default": "rgba(205,130,255,0.18)",
        "border_strong":  "rgba(224,170,255,0.32)", "border_focus":   "#d946ef",
        "action_primary":       "#d946ef", "action_primary_hover": "#e879f9", "action_primary_active": "#a21caf",
        "action_primary_text":  "#0b0612", "action_secondary":     "#1f0f35", "action_secondary_hover": "#311a55",
        "surface_hover":     "rgba(217,70,239,0.10)", "surface_selected":  "rgba(217,70,239,0.20)",
        "surface_active":    "rgba(217,70,239,0.28)",
        "danger_border":     "rgba(251,113,133,0.35)", "danger_hover": "rgba(251,113,133,0.16)", "danger_hover_text": "#fda4af",
        "status_success": "#22c55e", "status_warning": "#f59e0b", "status_error": "#fb7185", "status_info": "#818cf8",
        "accent_rgb": "217, 70, 239", "accent_rgb_claro": "232, 121, 249",
        "status_success_rgb": "34, 197, 94", "status_error_rgb": "251, 113, 133",
        "status_warning_rgb": "245, 158, 11",
        "shadow_sm": SHADOW_SM, "shadow_md": SHADOW_MD, "shadow_lg": SHADOW_LG, "shadow_xl": SHADOW_XL,
        "btn_text_primary": "#0b0612", "btn_text_hover": "#0b0612", "btn_text_disabled": "#6d4f9f",
        "btn_bg_hover": "#e879f9", "btn_bg_active": "#a21caf", "btn_bg_disabled": "#2a1740", "btn_border_disabled": "#2a1740",
    }


# QSS template with placeholders for .format()
_QSS_TEMPLATE = """
/* ─── RESET BASE ─── */
* {{
    font-family: "{fuente_ui}";
    font-size: {TEXT_BASE};
    line-height: {LH_NORMAL};
}}

QWidget {{
    background-color: {bg_app};
    color: {text_primary};
}}

QMainWindow, QDialog {{ background-color: {bg_app}; }}
QLabel {{ background: transparent; color: {text_primary}; }}

/* ─── TÍTULOS ─── */
QLabel[heading="true"] {{
    font-size: {TEXT_LG};
    font-weight: 600;
    color: {text_primary};
    letter-spacing: {LS_HEADING};
    qproperty-textWrap: balance;
}}

/* ─── GRUPOS ─── */
QGroupBox {{
    border: 1px solid {border_default};
    border-radius: {RADIUS_LG};
    margin-top: {SPACE_6};
    padding-top: {SPACE_3};
    background: {bg_panel};
    font-weight: 500;
    color: {text_primary};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: {SPACE_4};
    padding: 0 {SPACE_3};
    color: {action_primary};
    font-weight: 600;
    font-size: {TEXT_MD};
}}

/* ─── BOTONES ─── */
QPushButton {{
    background-color: {action_primary};
    color: {btn_text_primary};
    border: 1px solid {action_primary};
    border-radius: {RADIUS_MD};
    padding: {SPACE_3} {SPACE_6};
    font-size: {TEXT_BASE};
    font-weight: 500;
    font-family: "{fuente_ui}";
    min-height: 28px;
}}
QPushButton:hover {{
    background-color: {btn_bg_hover};
    border-color: {btn_bg_hover};
}}
QPushButton:pressed {{
    background-color: {action_primary_active};
    border-color: {action_primary_active};
}}
QPushButton:disabled {{
    background-color: {btn_bg_disabled};
    color: {btn_text_disabled};
    border-color: {btn_border_disabled};
}}
QPushButton:focus {{
    outline: none;
    border: 2px solid {border_focus};
    outline-offset: 2px;
}}

/* Botón secundario (ghost) */
QPushButton[ghost="true"] {{
    background-color: transparent;
    color: {text_secondary};
    border: 1px solid {border_default};
    padding: {SPACE_2} {SPACE_4};
}}
QPushButton[ghost="true"]:hover {{
    background-color: {surface_hover};
    color: {text_primary};
    border-color: {border_strong};
}}
QPushButton[ghost="true"]:focus {{
    outline: none;
    border: 2px solid {border_focus};
}}

/* Botón peligro (destructivo) */
QPushButton[danger="true"] {{
    background-color: {STATUS_ERROR};
    border-color: {STATUS_ERROR};
    color: #ffffff;
}}
QPushButton[danger="true"]:hover {{ background-color: #b91c1c; border-color: #b91c1c; }}

/* Botón peligro sutil (destructive ghost: acciones de riesgo en tablas) */
QPushButton[danger_ghost="true"] {{
    background-color: transparent;
    color: {STATUS_ERROR};
    border: 1px solid {danger_border};
    padding: {SPACE_1} {SPACE_4};
}}
QPushButton[danger_ghost="true"]:hover {{
    background-color: {danger_hover};
    color: {danger_hover_text};
    border-color: {STATUS_ERROR};
}}
QPushButton[danger_ghost="true"]:focus {{
    outline: none;
    border: 2px solid {border_focus};
}}

/* Botón compacto (tablas, listas) */
QPushButton[small="true"] {{
    padding: {SPACE_1} {SPACE_4};
    font-size: {TEXT_SM};
    min-height: 22px;
    border-radius: {RADIUS_SM};
}}

/* ─── INPUTS Y COMBOBOX ─── */
QLineEdit, QComboBox {{
    background-color: {bg_sunken};
    color: {text_primary};
    border: 1px solid {border_default};
    border-radius: {RADIUS_MD};
    padding: {SPACE_3} {SPACE_4};
    font-size: {TEXT_BASE};
    font-family: "{fuente_ui}";
    min-height: 28px;
    selection-background-color: {action_primary};
    selection-color: #ffffff;
}}
QLineEdit:hover, QComboBox:hover {{
    border-color: {border_strong};
}}
QLineEdit:focus, QComboBox:focus {{
    border-color: {border_focus};
    outline: none;
}}
QLineEdit:disabled, QComboBox:disabled {{
    background-color: {bg_sunken};
    color: {text_disabled};
    border-color: {border_subtle};
}}

/* ComboBox dropdown */
QComboBox::drop-down {{
    border: none;
    width: 24px;
    background: transparent;
}}
QComboBox QAbstractItemView {{
    background-color: {bg_elevated};
    color: {text_primary};
    selection-background-color: {surface_selected};
    selection-color: {text_primary};
    border: 1px solid {border_default};
    border-radius: {RADIUS_MD};
    padding: {SPACE_2};
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: {SPACE_2} {SPACE_3};
    border-radius: {RADIUS_SM};
}}
QComboBox QAbstractItemView::item:hover {{
    background: {surface_hover};
}}
QComboBox QAbstractItemView::item:selected {{
    background: {surface_selected};
    color: {text_primary};
}}

/* ─── PLAINTEXTEDIT (logs, código) ─── */
QPlainTextEdit, QTextEdit {{
    background-color: {bg_sunken};
    color: {text_primary};
    border: 1px solid {border_default};
    border-radius: {RADIUS_MD};
    padding: {SPACE_3};
    font-family: "{fuente_mono}";
    font-size: {TEXT_SM};
    line-height: 1.6;
    selection-background-color: {action_primary};
    selection-color: #ffffff;
}}
QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {border_focus};
    outline: none;
}}

/* Tables/trees: without this the alternate rows took the system palette's
   light colour, leaving every other row unreadable in dark themes. */
QTableView, QTreeView {{
    background-color: {bg_sunken};
    alternate-background-color: {bg_panel};
    color: {text_primary};
    selection-background-color: {surface_selected};
    selection-color: {text_primary};
}}

/* ─── TABS ─── */
QTabWidget::pane {{
    border: 1px solid {border_default};
    border-radius: {RADIUS_LG};
    top: -1px;
    background: transparent;
}}
QTabBar::tab {{
    background-color: {bg_panel};
    color: {text_secondary};
    border: 1px solid {border_default};
    padding: {SPACE_3} {SPACE_6};
    margin-right: {SPACE_2};
    border-top-left-radius: {RADIUS_MD};
    border-top-right-radius: {RADIUS_MD};
    font-size: {TEXT_SM};
    font-weight: 500;
    min-height: 28px;
}}
QTabBar::tab:selected {{
    background-color: {action_primary};
    color: {action_primary_text};
    font-weight: 600;
    border-color: {action_primary};
}}
QTabBar::tab:hover:!selected {{
    background-color: {action_secondary_hover};
    color: {text_primary};
}}
QTabBar::tab:focus {{
    outline: none;
    border: 2px solid {border_focus};
}}

/* ─── CHECKBOX ─── */
QCheckBox {{
    background: transparent;
    spacing: {SPACE_3};
    color: {text_primary};
    font-size: {TEXT_BASE};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {border_default};
    border-radius: {RADIUS_SM};
    background: {bg_sunken};
}}
QCheckBox::indicator:hover {{
    border-color: {border_strong};
}}
QCheckBox::indicator:checked {{
    background-color: {action_primary};
    border-color: {action_primary};
    image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iOSIgdmlld0JveD0iMCAwIDEyIDkiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxwYXRoIGQ9Ik0xIDQuNUw0LjUgOEwxMSAxIiBzdHJva2U9IiNmZmZmZmYiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
}}
QCheckBox::indicator:focus {{
    outline: none;
    border: 2px solid {border_focus};
}}

/* ─── SCROLLBARS ─── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background-color: {border_default};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {border_strong};
}}
QScrollBar::handle:vertical:pressed {{
    background-color: {border_strong};
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* Horizontal */
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background-color: {border_default};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {border_strong};
}}

/* ─── TOOLTIPS ─── */
QToolTip {{
    background-color: {bg_elevated};
    color: {text_primary};
    border: 1px solid {border_default};
    border-radius: {RADIUS_MD};
    padding: {SPACE_3} {SPACE_4};
    font-size: {TEXT_SM};
}}

/* ─── PROGRESS BAR ─── */
QProgressBar {{
    background-color: {bg_sunken};
    border: 1px solid {border_default};
    border-radius: {RADIUS_MD};
    text-align: center;
    color: {text_primary};
    font-size: {TEXT_SM};
}}
QProgressBar::chunk {{
    background-color: {action_primary};
    border-radius: {RADIUS_MD};
}}

/* ─── SPLITTER (redimensionable) ─── */
QSplitter::handle {{
    background: transparent;
    width: 4px;
    height: 4px;
}}
QSplitter::handle:hover {{
    background: {border_focus};
}}
QSplitter::handle:horizontal {{
    width: 4px;
}}
QSplitter::handle:vertical {{
    height: 4px;
}}
QSplitter::handle:focus {{
    outline: none;
    background: {border_focus};
}}

/* ─── MENSAJES DE ESTADO (labels con clase) ─── */
QLabel[status="success"] {{ color: {status_success}; font-weight: 500; }}
QLabel[status="warning"] {{ color: {status_warning}; font-weight: 500; }}
QLabel[status="error"]   {{ color: {status_error}; font-weight: 500; }}
QLabel[status="info"]    {{ color: {status_info}; font-weight: 500; }}
QLabel[status="muted"]   {{ color: {text_tertiary}; }}

/* ─── SIDEBAR DE NAVEGACIÓN (cabina) ─── */
QListWidget#sidebar {{
    background-color: {bg_panel};
    border: none;
    border-right: 1px solid {border_default};
    padding: {SPACE_3} {SPACE_2};
    outline: none;
}}
QListWidget#sidebar::item {{
    color: {text_secondary};
    padding: {SPACE_3} {SPACE_4};
    border-radius: {RADIUS_MD};
    margin: 1px {SPACE_1};
    font-size: {TEXT_BASE};
    font-weight: 500;
}}
QListWidget#sidebar::item:hover {{
    background-color: {surface_hover};
    color: {text_primary};
    border-radius: {RADIUS_MD};
}}
QListWidget#sidebar::item:selected {{
    background-color: {surface_selected};
    color: {action_primary};
    font-weight: 600;
    border-radius: {RADIUS_MD};
    border: none;
}}
QListWidget#sidebar::item:selected:focus {{
    background-color: {surface_selected};
    color: {action_primary};
    font-weight: 600;
    border: none;
}}

/* ─── STATUS BAR (cabina) ─── */
QStatusBar {{
    background-color: {bg_panel};
    border-top: 1px solid {border_default};
    color: {text_secondary};
    font-size: {TEXT_SM};
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ background: transparent; }}

/* ─── PÍLDORA DE ESTADO DEL LOOP ─── */
QLabel#pill_loop {{
    background-color: {bg_sunken};
    color: {text_secondary};
    border: 1px solid {border_default};
    border-radius: {RADIUS_XL};
    padding: {SPACE_2} {SPACE_4};
    font-size: {TEXT_SM};
    font-weight: 600;
    min-height: 16px;
}}
QLabel#pill_loop[running="true"] {{
    background-color: rgba({accent_rgb_claro}, 0.15);
    border-color: {accent_rgb_claro};
    color: {status_warning};
}}
"""


def _qss(c: dict) -> str:
    """Generates the full QSS with semantic tokens using .format() to avoid problems with braces."""
    # Resolve fonts (initializes them if not done yet)
    fuente_mono = _get_fuente_mono()
    fuente_ui = _get_fuente_ui()
    return _QSS_TEMPLATE.format(
        fuente_ui=fuente_ui,
        fuente_mono=fuente_mono,
        TEXT_BASE=TEXT_BASE,
        LH_NORMAL=LH_NORMAL,
        TEXT_LG=TEXT_LG,
        LS_HEADING=LS_HEADING,
        TEXT_MD=TEXT_MD,
        TEXT_SM=TEXT_SM,
        SPACE_1=SPACE_1,
        SPACE_2=SPACE_2,
        SPACE_3=SPACE_3,
        SPACE_4=SPACE_4,
        SPACE_6=SPACE_6,
        RADIUS_SM=RADIUS_SM,
        RADIUS_MD=RADIUS_MD,
        RADIUS_LG=RADIUS_LG,
        RADIUS_XL=RADIUS_XL,
        STATUS_ERROR=STATUS_ERROR,
        **c
    )


# Available themes - curated list (visually very distinct from each other)
NOMBRES = [
    "Oscuro",                    # slate/blue dark (legacy)
    "Claro",                     # slate/blue light (legacy)
    "Hacker",                    # terminal green
    "Cyberpunk",                 # purple/fuchsia neon on graphite
    "Zinc/Amber Oscuro",         # amber cockpit (default)
    "Gray/Red Oscuro",           # red
    "Stone/Emerald Claro",       # warm light green
    "Zinc/Sky Claro",            # light blue
    "Slate/Teal Oscuro",         # deep teal
]
_TEMAS_CACHE: dict[str, str] = {}


def colores_tema(tema: str) -> dict:
    """Theme colors as QColor for manual painting (e.g. the stepper).

    Reuses the same tokens as the QSS so nothing goes out of sync.
    """
    from PySide6.QtGui import QColor
    c = _qss_variables(tema)

    def _qcolor(v):
        v = v.strip()
        if v.startswith("rgba"):
            nums = re.findall(r"[\d.]+", v)
            if len(nums) == 4:
                return QColor(int(float(nums[0])), int(float(nums[1])),
                              int(float(nums[2])), int(float(nums[3]) * 255))
        return QColor(v)

    accent = QColor(c["action_primary"])
    return {
        "bg_panel":     _qcolor(c["bg_panel"]),
        "bg_sunken":    _qcolor(c["bg_sunken"]),
        "text_primary": QColor(c["text_primary"]),
        "text_secondary": QColor(c["text_secondary"]),
        "text_tertiary":  QColor(c["text_tertiary"]),
        "text_inverse":   QColor(c["action_primary_text"]),
        "border":       _qcolor(c["border_default"]),
        "accent":       accent,
        "accent_claro": accent.lighter(130),
        "success":      QColor(c["status_success"]),
        "error":        QColor(c["status_error"]),
        "warning":      QColor(c["status_warning"]),
    }


def inicializar_temas():
    """Generates the QSS themes. Must be called after creating QApplication."""
    global _TEMAS_CACHE
    if not _TEMAS_CACHE:
        for nombre in NOMBRES:
            _TEMAS_CACHE[nombre] = _qss(_qss_variables(nombre))


def obtener_temas():
    """Returns the theme dictionary, initializing it if necessary."""
    if not _TEMAS_CACHE:
        inicializar_temas()
    return _TEMAS_CACHE
