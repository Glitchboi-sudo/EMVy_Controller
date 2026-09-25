"""Tokens de diseño **independientes del tema** (geometría y tipografía),
compartidos por la GUI (Qt/QSS) y la TUI (Textual).

El color vive en `palettes.py` (varía por tema); aquí vive todo lo que **no**
cambia con el tema: la escala de espaciado, los radios de borde, la escala
tipográfica y las sombras/elevación. Un único origen para ambas interfaces, de
modo que "16 px" o "radio md" signifiquen lo mismo en la ventana nativa y en la
terminal (dentro de lo que cada medio permite).

Es **dato puro** (sin IO, sin estado) — coherente con el núcleo funcional del
proyecto. La GUI lee píxeles; la TUI, celdas (aprox. 1 celda ≈ 8 px de ancho).
"""
from __future__ import annotations

# -- escala de espaciado (px) — múltiplos de 4, nombres semánticos -----------
# xs=4 sm=8 md=12 lg=16 xl=24 xxl=32. Se usa en paddings/márgenes/gaps.
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}

# -- radios de borde (px) ----------------------------------------------------
# sm=6 (chips) md=10 (inputs/botones) lg=14 (tarjetas) pill=999 (cápsulas).
RADIUS = {"sm": 6, "md": 10, "lg": 14, "pill": 999}

# -- escala tipográfica (px, peso) -------------------------------------------
# Nombres de rol; la GUI aplica px+peso, la TUI usa negrita/tenue equivalente.
TYPE = {
    "display": (26, 800),   # marca / hero
    "h1": (20, 700),        # título de página
    "h2": (15, 700),        # título de sección/tarjeta
    "h3": (13, 600),        # subtítulo/etiqueta fuerte
    "body": (13, 400),      # texto normal
    "caption": (12, 400),   # texto tenue/ayudas
    "overline": (10, 700),  # etiquetas de grupo (mayúsculas, tracking)
    "mono": (12, 400),      # datos hex/APDU
}

# -- elevación (sombra CSS por nivel) ----------------------------------------
# Qt QSS no soporta box-shadow real; se usa como guía y para bordes elevados.
ELEVATION = {
    0: "none",
    1: "0 1px 2px rgba(0,0,0,0.30)",
    2: "0 4px 12px rgba(0,0,0,0.35)",
    3: "0 12px 32px rgba(0,0,0,0.45)",
}

# -- familias tipográficas (fallbacks del sistema) ---------------------------
FONT_SANS = ["Inter", "IBM Plex Sans", "Segoe UI", "Cantarell",
             "Noto Sans", "Ubuntu", "DejaVu Sans", "sans-serif"]
FONT_MONO = ["JetBrains Mono", "Cascadia Code", "Fira Code", "IBM Plex Mono",
             "DejaVu Sans Mono", "Consolas", "monospace"]


def px(name: str) -> int:
    """Espaciado en px por nombre (`SPACE`); 0 si no existe."""
    return SPACE.get(name, 0)


def radius(name: str) -> int:
    """Radio de borde en px por nombre (`RADIUS`)."""
    return RADIUS.get(name, RADIUS["md"])


def font_size(role: str) -> int:
    """Tamaño en px del rol tipográfico (`TYPE`); body si no existe."""
    return TYPE.get(role, TYPE["body"])[0]


def font_weight(role: str) -> int:
    """Peso del rol tipográfico (`TYPE`); 400 si no existe."""
    return TYPE.get(role, TYPE["body"])[1]
