"""Paletas de color con nombre (temas) compartidas por GUI y TUI.

Cada paleta es un `dict` con los **tokens de color** que consume el tema visual
(`gui.theme` construye el QSS; `tui.app` construye un `textual.theme.Theme`), de
modo que un único conjunto de colores viste ambas interfaces. Añadir un tema es
solo añadir una entrada aquí.

**Tokens base** (`_TOKENS`, obligatorios en cada entrada — los valida `is_valid`):
bg / bg_deep / panel / surface2 / border / border_hi / text / muted /
accent / accent_hi / accent_fg / warning / error / info  (+ label, dark).

**Tokens derivados** (`_DERIVED`): se calculan a partir de los base cuando la
paleta no los trae — así las paletas heredadas siguen siendo válidas sin editar
las 8 a mano, y solo la de por defecto ("emvy"/Nova) los afina. `get()` los
rellena, así que quien consuma una paleta vía `get()` los tiene garantizados:
surface3 (superficie elevada) · accent_muted (fondo tenue del acento, para
selección/insignias) · success/success_fg · warning_fg · error_fg · info_fg.
"""
from __future__ import annotations

_TOKENS = ("bg", "bg_deep", "panel", "surface2", "border", "border_hi", "text",
           "muted", "accent", "accent_hi", "accent_fg", "warning", "error", "info")

_DERIVED = ("surface3", "accent_muted", "success", "success_fg",
            "warning_fg", "error_fg", "info_fg")


def _p(label, dark, bg, bg_deep, panel, surface2, border, border_hi, text, muted,
       accent, accent_hi, accent_fg, warning, error, info, **extra) -> dict:
    d = dict(label=label, dark=dark, bg=bg, bg_deep=bg_deep, panel=panel,
             surface2=surface2, border=border, border_hi=border_hi, text=text,
             muted=muted, accent=accent, accent_hi=accent_hi, accent_fg=accent_fg,
             warning=warning, error=error, info=info)
    d.update(extra)     # permite afinar tokens derivados a mano (p.ej. la default)
    return d


PALETTES: dict[str, dict] = {
    # "emvy" (Nova) — identidad moderna: neutros fríos + acento índigo, verde
    # semántico para acciones de "correr/capturar". Los tokens derivados van
    # afinados a mano aquí (surface3/accent_muted/success/*_fg); el resto de
    # paletas los derivan de sus base.
    "emvy": _p("EMVy (Nova)", True,
               "#0B0E14", "#07090D", "#12151D", "#1A1E28", "#262B37", "#363C4A",
               "#E7EAF0", "#8B93A5", "#6E7BFF", "#9AA3FF", "#0A0B10",
               "#FBBF24", "#F87171", "#60A5FA",
               surface3="#22262F", accent_muted="#1B2036",
               success="#34D399", success_fg="#04140C",
               warning_fg="#1A1204", error_fg="#FFFFFF", info_fg="#04121A"),
    #                       etiqueta            oscuro  bg        bg_deep   panel     surface2  border    border_hi text      muted     accent    accent_hi accent_fg warning   error     info
    "tokyo-night": _p("Tokyo Night",       True,  "#1A1B26", "#16161E", "#24283B", "#2F3549", "#3B4261", "#545C7E", "#C0CAF5", "#565F89", "#7AA2F7", "#9EB5F9", "#1A1B26", "#E0AF68", "#F7768E", "#7DCFFF"),
    "gruvbox":     _p("Gruvbox Dark",      True,  "#282828", "#1D2021", "#3C3836", "#504945", "#504945", "#665C54", "#EBDBB2", "#A89984", "#B8BB26", "#D3D830", "#282828", "#FABD2F", "#FB4934", "#83A598"),
    "nord":        _p("Nord",              True,  "#2E3440", "#272C36", "#3B4252", "#434C5E", "#434C5E", "#4C566A", "#ECEFF4", "#7B88A1", "#88C0D0", "#8FBCBB", "#2E3440", "#EBCB8B", "#BF616A", "#81A1C1"),
    "catppuccin":  _p("Catppuccin Mocha",  True,  "#1E1E2E", "#181825", "#313244", "#45475A", "#45475A", "#585B70", "#CDD6F4", "#9399B2", "#CBA6F7", "#DDBDFB", "#1E1E2E", "#F9E2AF", "#F38BA8", "#89DCEB"),
    "dracula":     _p("Dracula",           True,  "#282A36", "#21222C", "#343746", "#44475A", "#44475A", "#6272A4", "#F8F8F2", "#6272A4", "#50FA7B", "#69FF94", "#282A36", "#F1FA8C", "#FF5555", "#8BE9FD"),
    "solarized":   _p("Solarized Dark",    True,  "#002B36", "#00212B", "#073642", "#0A4B5A", "#0A4B5A", "#586E75", "#EEE8D5", "#93A1A1", "#859900", "#A5B900", "#002B36", "#B58900", "#DC322F", "#268BD2"),
    "gruvbox-light": _p("Gruvbox Light",   False, "#FBF1C7", "#F2E5BC", "#EBDBB2", "#D5C4A1", "#D5C4A1", "#BDAE93", "#3C3836", "#7C6F64", "#79740E", "#98971A", "#FBF1C7", "#B57614", "#9D0006", "#076678"),
}

DEFAULT = "emvy"


# -- helpers de color (mezcla en sRGB, suficiente para derivar tokens) -------
def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, r)):02X}{max(0, min(255, g)):02X}{max(0, min(255, b)):02X}"


def _mix(a: str, b: str, t: float) -> str:
    """Mezcla `a`→`b` en proporción `t` (0..1) en sRGB."""
    ar, ag, ab = _hex_to_rgb(a)
    br, bg_, bb = _hex_to_rgb(b)
    return _rgb_to_hex(round(ar + (br - ar) * t), round(ag + (bg_ - ag) * t),
                       round(ab + (bb - ab) * t))


def _looks_green(hexcol: str) -> bool:
    r, g, b = _hex_to_rgb(hexcol)
    return g > r + 20 and g > b + 20


def _derive(pal: dict) -> dict:
    """Devuelve una copia de `pal` con los tokens derivados que falten, calculados
    desde los base. No pisa los que la paleta ya define a mano."""
    p = dict(pal)
    white, black = "#FFFFFF", "#000000"
    success = p.get("success") or (p["accent"] if _looks_green(p["accent"]) else "#22C55E")
    defaults = {
        # superficie un paso más clara/oscura que surface2 (hacia el texto)
        "surface3": _mix(p["surface2"], p["text"], 0.12),
        # fondo tenue del acento (selección/insignias): acento mezclado con panel
        "accent_muted": _mix(p["panel"], p["accent"], 0.28),
        # verde de éxito: si el acento ya es verdoso se reusa; si no, un verde fijo
        "success": success,
        # foregrounds legibles sobre colores semánticos (claro u oscuro)
        "success_fg": _mix(success, black, 0.72),
        "warning_fg": _mix(p["warning"], black, 0.78),
        "error_fg": white if p.get("dark", True) else _mix(p["error"], black, 0.5),
        "info_fg": _mix(p["info"], black, 0.78),
    }
    for k in _DERIVED:
        p.setdefault(k, defaults[k])
    return p


def get(name: str) -> dict:
    """Paleta por nombre (con tokens derivados rellenados); cae a la de por
    defecto si no existe."""
    return _derive(PALETTES.get(name, PALETTES[DEFAULT]))


def names() -> list[tuple[str, str]]:
    """`[(nombre, etiqueta)]` para poblar selectores (orden de inserción)."""
    return [(k, v["label"]) for k, v in PALETTES.items()]


def is_valid(pal: dict) -> bool:
    """True si la paleta trae todos los tokens **base** (para tests). Los tokens
    derivados no son obligatorios en la definición: `get()` los rellena."""
    return all(t in pal for t in _TOKENS)
