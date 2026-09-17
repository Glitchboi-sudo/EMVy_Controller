"""Sistema visual de la GUI (PySide6): un tema **oscuro profesional** aplicado
globalmente vía QSS (hoja de estilo Qt) + tipografía.

Paleta "slate/OLED + run green" (fondo pizarra profundo, superficies elevadas,
acento verde de acción) — coherente para una herramienta de seguridad/dev:

    fondo  #0F172A   ·  panel #1B2336  ·  superficie-2 #272F42
    texto  #F8FAFC   ·  tenue #94A3B8  ·  borde #334155 / #475569
    acento #22C55E (verde) · aviso #F59E0B · error #EF4444 · info #38BDF8

Se aplica una sola vez sobre la `QApplication` (`apply_theme`), así **todos** los
widgets y diálogos quedan estilizados sin tocar cada panel. La tipografía usa una
sans moderna con fallbacks del sistema (IBM Plex Sans / Inter / Segoe UI…).
"""
from __future__ import annotations

from .. import palettes

# -- tokens de color (fuente de verdad; se actualizan al cambiar de tema) -----
# Se inicializan con la paleta por defecto y `apply_theme()` los reasigna. Otros
# paneles importan estas constantes para estilos en línea; el QSS (mayoría de la
# UI) se re-aplica en vivo, y estos valores quedan coherentes tras reiniciar.
_DEF = palettes.get(palettes.DEFAULT)
BG        = _DEF["bg"]
BG_DEEP   = _DEF["bg_deep"]
PANEL     = _DEF["panel"]
SURFACE2  = _DEF["surface2"]
BORDER    = _DEF["border"]
BORDER_HI = _DEF["border_hi"]
TEXT      = _DEF["text"]
MUTED     = _DEF["muted"]
ACCENT    = _DEF["accent"]
ACCENT_HI = _DEF["accent_hi"]
ACCENT_FG = _DEF["accent_fg"]
WARNING   = _DEF["warning"]
ERROR     = _DEF["error"]
INFO      = _DEF["info"]

FONT_FAMILIES = ["IBM Plex Sans", "Inter", "Segoe UI", "Cantarell",
                 "Noto Sans", "Ubuntu", "DejaVu Sans", "sans-serif"]
MONO_FAMILIES = ["JetBrains Mono", "Cascadia Code", "Fira Code", "IBM Plex Mono",
                 "DejaVu Sans Mono", "Consolas", "monospace"]


def build_qss(pal: dict) -> str:
    """Construye la hoja de estilo QSS a partir de una paleta (`palettes`)."""
    BG, BG_DEEP, PANEL, SURFACE2 = pal["bg"], pal["bg_deep"], pal["panel"], pal["surface2"]
    BORDER, BORDER_HI, TEXT, MUTED = pal["border"], pal["border_hi"], pal["text"], pal["muted"]
    ACCENT, ACCENT_HI, ACCENT_FG = pal["accent"], pal["accent_hi"], pal["accent_fg"]
    return f"""
/* ---- base ------------------------------------------------------------ */
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-size: 13px;
}}
QMainWindow, QDialog {{ background-color: {BG}; }}
QToolTip {{
    background-color: {PANEL}; color: {TEXT};
    border: 1px solid {BORDER_HI}; border-radius: 6px; padding: 4px 8px;
}}

/* ---- barra lateral de navegación (QListWidget#nav) ------------------ */
QListWidget#nav {{
    background-color: {BG_DEEP}; border: none; border-right: 1px solid {BORDER};
    outline: none; padding: 8px 6px; font-size: 13px;
}}
QListWidget#nav::item {{
    color: {MUTED}; padding: 8px 10px; border-radius: 8px; margin: 1px 2px;
}}
QListWidget#nav::item:hover {{ background-color: {PANEL}; color: {TEXT}; }}
QListWidget#nav::item:selected {{
    background-color: {SURFACE2}; color: {TEXT};
    border-left: 3px solid {ACCENT};
}}
QListWidget#nav::item:disabled {{        /* cabeceras de grupo */
    color: {MUTED}; font-size: 10px; font-weight: 700; padding: 10px 8px 4px 8px;
    margin: 0; background: transparent;
}}

/* ---- área de contenido (la barra lateral navega; sin barra de pestañas) */
QTabWidget::pane {{ border: none; background-color: {BG}; padding: 8px 10px; }}
QTabBar {{ qproperty-drawBase: 0; }}
/* sub-pestañas internas (Herramientas, Fuzzing) sí muestran su barra */
QTabBar::tab {{
    background: transparent; color: {MUTED};
    padding: 8px 16px; margin-right: 2px;
    border: 1px solid transparent; border-top-left-radius: 8px; border-top-right-radius: 8px;
    font-weight: 600;
}}
QTabBar::tab:hover {{ color: {TEXT}; background: {PANEL}; }}
QTabBar::tab:selected {{
    color: {ACCENT}; background: {PANEL};
    border: 1px solid {BORDER}; border-bottom: 2px solid {ACCENT};
}}

/* ---- grupos / tarjetas ---------------------------------------------- */
QGroupBox {{
    background-color: {PANEL};
    border: 1px solid {BORDER}; border-radius: 12px;
    margin-top: 14px; padding: 12px 12px 12px 12px; font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 12px; padding: 2px 8px; color: {ACCENT};
    background-color: {PANEL}; border-radius: 6px;
}}
QFrame[frameShape="4"], QFrame[frameShape="5"] {{ color: {BORDER}; }}   /* HLine/VLine */

/* ---- botones -------------------------------------------------------- */
QPushButton {{
    background-color: {SURFACE2}; color: {TEXT};
    border: 1px solid {BORDER_HI}; border-radius: 8px;
    padding: 7px 14px; font-weight: 600; min-height: 16px;
}}
QPushButton:hover {{ background-color: {BORDER}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background-color: {BG_DEEP}; }}
QPushButton:disabled {{ color: {MUTED}; background-color: {PANEL}; border-color: {BORDER}; }}
QPushButton:default {{ border-color: {ACCENT}; }}
/* acción primaria: botones marcados con propiedad accent=true */
QPushButton[accent="true"] {{
    background-color: {ACCENT}; color: {ACCENT_FG}; border: 1px solid {ACCENT};
}}
QPushButton[accent="true"]:hover {{ background-color: {ACCENT_HI}; }}

/* ---- campos de entrada ---------------------------------------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {BG_DEEP}; color: {TEXT};
    border: 1px solid {BORDER_HI}; border-radius: 8px;
    padding: 6px 8px; selection-background-color: {ACCENT}; selection-color: {ACCENT_FG};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit::placeholder {{ color: {MUTED}; }}
QPlainTextEdit, QTextEdit {{ border-radius: 10px; }}

/* ---- combos --------------------------------------------------------- */
QComboBox {{
    background-color: {BG_DEEP}; color: {TEXT};
    border: 1px solid {BORDER_HI}; border-radius: 8px; padding: 6px 8px; min-height: 16px;
}}
QComboBox:hover {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {MUTED}; margin-right: 8px; }}
QComboBox QAbstractItemView {{
    background-color: {PANEL}; color: {TEXT};
    border: 1px solid {BORDER_HI}; border-radius: 8px;
    selection-background-color: {ACCENT}; selection-color: {ACCENT_FG}; outline: none;
}}

/* ---- checkboxes / radios ------------------------------------------- */
QCheckBox, QRadioButton {{ spacing: 8px; color: {TEXT}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid {BORDER_HI};
    background: {BG_DEEP};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
}}

/* ---- tablas / árboles / listas ------------------------------------- */
QTableView, QTableWidget, QTreeView, QTreeWidget, QListView, QListWidget {{
    background-color: {PANEL}; alternate-background-color: {BG};
    color: {TEXT}; border: 1px solid {BORDER}; border-radius: 10px;
    gridline-color: {BORDER}; selection-background-color: {ACCENT}; selection-color: {ACCENT_FG};
    outline: none;
}}
QTableView::item, QTreeView::item, QListView::item {{ padding: 4px 6px; }}
QHeaderView::section {{
    background-color: {SURFACE2}; color: {MUTED};
    padding: 6px 8px; border: none; border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER}; font-weight: 600;
}}
QTableCornerButton::section {{ background-color: {SURFACE2}; border: none; }}

/* ---- dock de la consola cruda -------------------------------------- */
QDockWidget {{ color: {TEXT}; titlebar-close-icon: none; titlebar-normal-icon: none; }}
QDockWidget::title {{
    background-color: {PANEL}; color: {ACCENT};
    padding: 7px 12px; border-bottom: 1px solid {BORDER}; font-weight: 700;
}}

/* ---- barra de estado ------------------------------------------------ */
QStatusBar {{ background-color: {BG_DEEP}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}

/* ---- scrollbars (finas y redondeadas) ------------------------------ */
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_HI}; border-radius: 6px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_HI}; border-radius: 6px; min-width: 28px; }}
QScrollBar::handle:horizontal:hover {{ background: {MUTED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- menús / splitter / progress ----------------------------------- */
QMenuBar {{ background-color: {BG}; color: {TEXT}; }}
QMenuBar::item:selected {{ background: {PANEL}; }}
QMenu {{ background-color: {PANEL}; color: {TEXT}; border: 1px solid {BORDER_HI}; border-radius: 8px; }}
QMenu::item:selected {{ background-color: {ACCENT}; color: {ACCENT_FG}; }}
QSplitter::handle {{ background-color: {BORDER}; }}
QProgressBar {{ background-color: {BG_DEEP}; border: 1px solid {BORDER}; border-radius: 8px;
    text-align: center; color: {TEXT}; }}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 8px; }}
"""


def _refresh_constants(pal: dict) -> None:
    """Reasigna las constantes de módulo (para lecturas por atributo `theme.ACCENT`)."""
    global BG, BG_DEEP, PANEL, SURFACE2, BORDER, BORDER_HI, TEXT, MUTED
    global ACCENT, ACCENT_HI, ACCENT_FG, WARNING, ERROR, INFO
    BG, BG_DEEP, PANEL, SURFACE2 = pal["bg"], pal["bg_deep"], pal["panel"], pal["surface2"]
    BORDER, BORDER_HI, TEXT, MUTED = pal["border"], pal["border_hi"], pal["text"], pal["muted"]
    ACCENT, ACCENT_HI, ACCENT_FG = pal["accent"], pal["accent_hi"], pal["accent_fg"]
    WARNING, ERROR, INFO = pal["warning"], pal["error"], pal["info"]


def apply_theme(app, palette_name: str | None = None) -> None:
    """Aplica el tema (fuente + QSS) a la `QApplication`. Idempotente.

    `palette_name` elige la paleta (`palettes.PALETTES`); si es None usa el tema
    de los ajustes guardados. El QSS se re-aplica en vivo (recolorea toda la UI);
    los colores en línea de algunos paneles se actualizan del todo al reiniciar.
    """
    from PySide6.QtGui import QFont
    if palette_name is None:
        from .. import settings
        palette_name = settings.load().theme
    pal = palettes.get(palette_name)
    _refresh_constants(pal)
    font = QFont()
    try:
        font.setFamilies(FONT_FAMILIES)   # Qt6: primera familia disponible
    except Exception:
        font.setFamily(FONT_FAMILIES[0])
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(build_qss(pal))
