"""Paletas de color con nombre (temas) compartidas por GUI y TUI.

Cada paleta es un `dict` con los **mismos tokens** que consume el tema visual
(`gui.theme` construye el QSS; `tui.app` construye un `textual.theme.Theme`), de
modo que un único conjunto de colores viste ambas interfaces. Añadir un tema es
solo añadir una entrada aquí.

Tokens: bg / bg_deep / panel / surface2 / border / border_hi / text / muted /
accent / accent_hi / accent_fg / warning / error / info  (+ label, dark).
"""
from __future__ import annotations

_TOKENS = ("bg", "bg_deep", "panel", "surface2", "border", "border_hi", "text",
           "muted", "accent", "accent_hi", "accent_fg", "warning", "error", "info")


def _p(label, dark, bg, bg_deep, panel, surface2, border, border_hi, text, muted,
       accent, accent_hi, accent_fg, warning, error, info) -> dict:
    return dict(label=label, dark=dark, bg=bg, bg_deep=bg_deep, panel=panel,
                surface2=surface2, border=border, border_hi=border_hi, text=text,
                muted=muted, accent=accent, accent_hi=accent_hi, accent_fg=accent_fg,
                warning=warning, error=error, info=info)


PALETTES: dict[str, dict] = {
    # nombre               etiqueta            oscuro  bg        bg_deep   panel     surface2  border    border_hi text      muted     accent    accent_hi accent_fg warning   error     info
    "emvy":        _p("EMVy (por defecto)", True,  "#0F172A", "#0B1220", "#1B2336", "#272F42", "#334155", "#475569", "#F8FAFC", "#94A3B8", "#22C55E", "#4ADE80", "#0F172A", "#F59E0B", "#EF4444", "#38BDF8"),
    "tokyo-night": _p("Tokyo Night",       True,  "#1A1B26", "#16161E", "#24283B", "#2F3549", "#3B4261", "#545C7E", "#C0CAF5", "#565F89", "#7AA2F7", "#9EB5F9", "#1A1B26", "#E0AF68", "#F7768E", "#7DCFFF"),
    "gruvbox":     _p("Gruvbox Dark",      True,  "#282828", "#1D2021", "#3C3836", "#504945", "#504945", "#665C54", "#EBDBB2", "#A89984", "#B8BB26", "#D3D830", "#282828", "#FABD2F", "#FB4934", "#83A598"),
    "nord":        _p("Nord",              True,  "#2E3440", "#272C36", "#3B4252", "#434C5E", "#434C5E", "#4C566A", "#ECEFF4", "#7B88A1", "#88C0D0", "#8FBCBB", "#2E3440", "#EBCB8B", "#BF616A", "#81A1C1"),
    "catppuccin":  _p("Catppuccin Mocha",  True,  "#1E1E2E", "#181825", "#313244", "#45475A", "#45475A", "#585B70", "#CDD6F4", "#9399B2", "#CBA6F7", "#DDBDFB", "#1E1E2E", "#F9E2AF", "#F38BA8", "#89DCEB"),
    "dracula":     _p("Dracula",           True,  "#282A36", "#21222C", "#343746", "#44475A", "#44475A", "#6272A4", "#F8F8F2", "#6272A4", "#50FA7B", "#69FF94", "#282A36", "#F1FA8C", "#FF5555", "#8BE9FD"),
    "solarized":   _p("Solarized Dark",    True,  "#002B36", "#00212B", "#073642", "#0A4B5A", "#0A4B5A", "#586E75", "#EEE8D5", "#93A1A1", "#859900", "#A5B900", "#002B36", "#B58900", "#DC322F", "#268BD2"),
    "gruvbox-light": _p("Gruvbox Light",   False, "#FBF1C7", "#F2E5BC", "#EBDBB2", "#D5C4A1", "#D5C4A1", "#BDAE93", "#3C3836", "#7C6F64", "#79740E", "#98971A", "#FBF1C7", "#B57614", "#9D0006", "#076678"),
}

DEFAULT = "emvy"


def get(name: str) -> dict:
    """Paleta por nombre; cae a la de por defecto si no existe."""
    return PALETTES.get(name, PALETTES[DEFAULT])


def names() -> list[tuple[str, str]]:
    """`[(nombre, etiqueta)]` para poblar selectores (orden de inserción)."""
    return [(k, v["label"]) for k, v in PALETTES.items()]


def is_valid(pal: dict) -> bool:
    """True si la paleta trae todos los tokens de color (para tests)."""
    return all(t in pal for t in _TOKENS)
