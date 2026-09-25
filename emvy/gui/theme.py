"""Sistema visual de la GUI (PySide6) — un tema **profesional** tipo consola de
seguridad / SaaS de pentest bancario, aplicado globalmente vía QSS + tipografía.

Construido desde los tokens compartidos (`emvy.palettes` para color, `emvy.design`
para geometría). Principios: neutros oscuros sobrios, un único acento (índigo)
usado con moderación, jerarquía tipográfica clara, rejilla de 8 px, superficies
planas con bordes finos (sin degradados decorativos), tablas orientadas a datos,
chips de estado con contorno. Todo el estilo va por **objectName / propiedad
dinámica**, así que cambiar de tema recolorea la UI entera en vivo (`apply_theme`).
"""
from __future__ import annotations

from .. import design, palettes

# -- tokens de color (fuente de verdad; los reasigna `apply_theme`) -----------
_DEF = palettes.get(palettes.DEFAULT)
BG        = _DEF["bg"]
BG_DEEP   = _DEF["bg_deep"]
PANEL     = _DEF["panel"]
SURFACE2  = _DEF["surface2"]
SURFACE3  = _DEF["surface3"]
BORDER    = _DEF["border"]
BORDER_HI = _DEF["border_hi"]
TEXT      = _DEF["text"]
MUTED     = _DEF["muted"]
ACCENT    = _DEF["accent"]
ACCENT_HI = _DEF["accent_hi"]
ACCENT_FG = _DEF["accent_fg"]
ACCENT_MUTED = _DEF["accent_muted"]
SUCCESS   = _DEF["success"]
SUCCESS_FG = _DEF["success_fg"]
WARNING   = _DEF["warning"]
WARNING_FG = _DEF["warning_fg"]
ERROR     = _DEF["error"]
ERROR_FG  = _DEF["error_fg"]
INFO      = _DEF["info"]
INFO_FG   = _DEF["info_fg"]

FONT_FAMILIES = design.FONT_SANS
MONO_FAMILIES = design.FONT_MONO


def build_qss(pal: dict) -> str:
    """Construye la hoja de estilo QSS a partir de una paleta (`palettes.get`)."""
    p = palettes._derive(pal)
    BG, BG_DEEP, PANEL = p["bg"], p["bg_deep"], p["panel"]
    SURFACE2, SURFACE3 = p["surface2"], p["surface3"]
    BORDER, BORDER_HI, TEXT, MUTED = p["border"], p["border_hi"], p["text"], p["muted"]
    ACCENT, ACCENT_HI, ACCENT_FG, ACCENT_MUTED = p["accent"], p["accent_hi"], p["accent_fg"], p["accent_muted"]
    SUCCESS, SUCCESS_FG = p["success"], p["success_fg"]
    WARNING, WARNING_FG = p["warning"], p["warning_fg"]
    ERROR, ERROR_FG, INFO, INFO_FG = p["error"], p["error_fg"], p["info"], p["info_fg"]
    RSM, RMD, RLG = design.radius("sm"), design.radius("md"), design.radius("lg")
    return f"""
/* ==== base ============================================================ */
QWidget {{ background-color: {BG}; color: {TEXT}; font-size: 13px; }}
QMainWindow, QDialog {{ background-color: {BG}; }}
QLabel {{ background-color: transparent; }}
QToolTip {{
    background-color: {SURFACE2}; color: {TEXT};
    border: 1px solid {BORDER_HI}; border-radius: {RSM}px; padding: 5px 9px;
}}

/* ==== app shell: rieles / marca / barra superior ===================== */
QWidget#sidebar {{ background-color: {BG_DEEP}; border-right: 1px solid {BORDER}; }}
QWidget#brand-lockup {{ background-color: {BG_DEEP}; border-bottom: 1px solid {BORDER}; }}
QLabel#brand-name {{ color: {TEXT}; font-size: 15px; font-weight: 800; letter-spacing: 0.5px; }}
QLabel#brand-sub {{ color: {MUTED}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; }}

/* navegación (QListWidget#nav) */
QListWidget#nav {{
    background-color: {BG_DEEP}; border: none; outline: none;
    padding: 8px 8px; font-size: 13px;
}}
QListWidget#nav::item {{
    color: {MUTED}; padding: 8px 10px 8px 12px; border-radius: {RSM}px;
    margin: 1px 0; border-left: 2px solid transparent;
}}
QListWidget#nav::item:hover {{ background-color: {PANEL}; color: {TEXT}; }}
QListWidget#nav::item:selected {{
    background-color: {ACCENT_MUTED}; color: {TEXT};
    border-left: 2px solid {ACCENT};
}}
QListWidget#nav::item:disabled {{        /* cabeceras de grupo (overline) */
    color: {MUTED}; font-size: 10px; font-weight: 800; padding: 14px 8px 5px 12px;
    margin: 0; background: transparent; border-left: none;
}}

/* barra superior de contexto */
QFrame#topbar {{ background-color: {BG_DEEP}; border-bottom: 1px solid {BORDER}; }}
QLabel#topbar-title {{ color: {TEXT}; font-size: 15px; font-weight: 700; }}
QLabel#topbar-crumb {{ color: {MUTED}; font-size: 11px; }}

/* contenido */
QTabWidget#main-tabs::pane {{ border: none; background-color: {BG}; padding: 14px 18px; }}
QTabWidget::pane {{ border: none; background-color: {BG}; padding: 6px 2px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: {MUTED};
    padding: 8px 16px; margin-right: 4px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600;
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}

/* ==== tarjetas ======================================================= */
QFrame[card="true"] {{
    background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: {RLG}px;
}}
QFrame[card="stat"] {{
    background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: {RLG}px;
}}
QFrame[card="stat"]:hover {{ border-color: {BORDER_HI}; }}
/* franja de acción destacada: superficie plana con filete de acento a la izq. */
QFrame[card="hero"] {{
    background-color: {PANEL}; border: 1px solid {BORDER};
    border-left: 3px solid {ACCENT}; border-radius: {RLG}px;
}}

/* insignia de icono (cuadrado sobrio; el acento lo pone el propio icono) */
QLabel[badge="accent"] {{ background-color: {ACCENT_MUTED}; border: 1px solid {BORDER_HI}; border-radius: {RMD}px; }}
QLabel[badge="neutral"] {{ background-color: {SURFACE2}; border: 1px solid {BORDER}; border-radius: {RMD}px; }}
QLabel[badge="success"] {{ background-color: {SURFACE2}; border: 1px solid {BORDER}; border-radius: {RMD}px; }}
QLabel[badge="info"] {{ background-color: {SURFACE2}; border: 1px solid {BORDER}; border-radius: {RMD}px; }}

/* ==== tipografía semántica (propiedad `role`) ======================== */
QLabel[role="display"] {{ color: {TEXT}; font-size: 19px; font-weight: 800; }}
QLabel[role="h1"] {{ color: {TEXT}; font-size: 15px; font-weight: 700; }}
QLabel[role="h2"], QLabel[h2="true"] {{ color: {TEXT}; font-size: 13px; font-weight: 700; }}
QLabel[role="body"] {{ color: {TEXT}; font-size: 13px; }}
QLabel[role="caption"], QLabel[hint="true"] {{ color: {MUTED}; font-size: 12px; }}
QLabel[role="overline"] {{ color: {MUTED}; font-size: 10px; font-weight: 800; letter-spacing: 1px; }}
QLabel[role="statvalue"] {{ color: {TEXT}; font-size: 16px; font-weight: 700; }}
QLabel[role="statlabel"] {{ color: {MUTED}; font-size: 10px; font-weight: 800; letter-spacing: 1px; }}
QLabel[role="mono"] {{ color: {TEXT}; font-family: "{MONO_FAMILIES[0]}"; }}

/* ==== chips de estado (contorno = sobrio; sólido = fuerte) =========== */
QLabel[chip] {{
    border-radius: 9px; padding: 2px 10px; font-weight: 700; font-size: 11px;
    background-color: transparent;
}}
QLabel[chip="neutral"] {{ color: {MUTED}; border: 1px solid {BORDER_HI}; }}
QLabel[chip="accent"]  {{ color: {ACCENT_HI}; border: 1px solid {ACCENT}; }}
QLabel[chip="on"]      {{ color: {SUCCESS}; border: 1px solid {SUCCESS}; }}
QLabel[chip="off"]     {{ color: {MUTED}; border: 1px solid {BORDER}; }}
QLabel[chip="warn"]    {{ color: {WARNING}; border: 1px solid {WARNING}; }}
QLabel[chip="error"]   {{ color: {ERROR}; border: 1px solid {ERROR}; }}
QLabel[chip="info"]    {{ color: {INFO}; border: 1px solid {INFO}; }}
QLabel[chip="solid-accent"] {{ color: {ACCENT_FG}; background-color: {ACCENT}; }}
QLabel[chip="solid-on"] {{ color: {SUCCESS_FG}; background-color: {SUCCESS}; }}

/* Compat con el nombre antiguo `pill` (paneles aún no migrados). */
QLabel[pill="on"], QLabel[pill="off"], QLabel[pill="warn"],
QLabel[pill="info"], QLabel[pill="accent"], QLabel[pill="neutral"] {{
    border-radius: 9px; padding: 2px 10px; font-weight: 700; font-size: 11px;
    background-color: transparent;
}}
QLabel[pill="on"] {{ color: {SUCCESS}; border: 1px solid {SUCCESS}; }}
QLabel[pill="accent"] {{ color: {ACCENT_HI}; border: 1px solid {ACCENT}; }}
QLabel[pill="warn"] {{ color: {WARNING}; border: 1px solid {WARNING}; }}
QLabel[pill="info"] {{ color: {INFO}; border: 1px solid {INFO}; }}
QLabel[pill="off"] {{ color: {MUTED}; border: 1px solid {BORDER}; }}
QLabel[pill="neutral"] {{ color: {MUTED}; border: 1px solid {BORDER_HI}; }}

/* ==== botones ======================================================== */
QPushButton {{
    background-color: {SURFACE2}; color: {TEXT};
    border: 1px solid {BORDER_HI}; border-radius: {RSM}px;
    padding: 6px 12px; font-weight: 600; min-height: 14px;
}}
QPushButton:hover {{ background-color: {SURFACE3}; border-color: {BORDER_HI}; }}
QPushButton:pressed {{ background-color: {BG_DEEP}; }}
QPushButton:disabled {{ color: {MUTED}; background-color: {PANEL}; border-color: {BORDER}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
/* primaria (acento plano) */
QPushButton[accent="true"], QPushButton[variant="primary"] {{
    background-color: {ACCENT}; color: {ACCENT_FG}; border: 1px solid {ACCENT}; font-weight: 700;
}}
QPushButton[accent="true"]:hover, QPushButton[variant="primary"]:hover {{
    background-color: {ACCENT_HI}; border-color: {ACCENT_HI};
}}
QPushButton[accent="true"]:disabled, QPushButton[variant="primary"]:disabled {{
    background-color: {PANEL}; color: {MUTED}; border-color: {BORDER};
}}
/* éxito (verde) */
QPushButton[variant="success"] {{
    background-color: {SUCCESS}; color: {SUCCESS_FG}; border: 1px solid {SUCCESS}; font-weight: 700;
}}
/* destructiva (contorno rojo) */
QPushButton[variant="danger"] {{
    background-color: transparent; color: {ERROR}; border: 1px solid {ERROR};
}}
QPushButton[variant="danger"]:hover {{ background-color: {ERROR}; color: {ERROR_FG}; }}
/* fantasma */
QPushButton[variant="ghost"] {{
    background-color: transparent; border: 1px solid transparent; color: {MUTED};
}}
QPushButton[variant="ghost"]:hover {{ color: {TEXT}; background-color: {PANEL}; }}

/* ==== entradas ======================================================= */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {BG_DEEP}; color: {TEXT};
    border: 1px solid {BORDER_HI}; border-radius: {RSM}px;
    padding: 7px 9px; selection-background-color: {ACCENT}; selection-color: {ACCENT_FG};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit::placeholder {{ color: {MUTED}; }}
QPlainTextEdit, QTextEdit {{ font-family: "{MONO_FAMILIES[0]}"; }}

/* combos */
QComboBox {{
    background-color: {BG_DEEP}; color: {TEXT};
    border: 1px solid {BORDER_HI}; border-radius: {RSM}px; padding: 7px 9px; min-height: 15px;
}}
QComboBox:hover {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {MUTED}; margin-right: 8px; }}
QComboBox QAbstractItemView {{
    background-color: {PANEL}; color: {TEXT};
    border: 1px solid {BORDER_HI}; border-radius: {RSM}px;
    selection-background-color: {ACCENT_MUTED}; selection-color: {TEXT}; outline: none;
}}

/* checkboxes / radios */
QCheckBox, QRadioButton {{ spacing: 8px; color: {TEXT}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid {BORDER_HI}; background: {BG_DEEP};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
}}

/* ==== tablas / árboles / listas (orientadas a datos) ================= */
QTableView, QTableWidget, QTreeView, QTreeWidget, QListView, QListWidget {{
    background-color: {PANEL}; alternate-background-color: {BG};
    color: {TEXT}; border: 1px solid {BORDER}; border-radius: {RMD}px;
    gridline-color: {BORDER}; outline: none;
    selection-background-color: {ACCENT_MUTED}; selection-color: {TEXT};
}}
QTableView::item, QTreeView::item, QListView::item {{ padding: 4px 7px; }}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{
    background-color: {ACCENT_MUTED}; color: {TEXT};
}}
QHeaderView::section {{
    background-color: {BG_DEEP}; color: {MUTED};
    padding: 5px 9px; border: none; border-bottom: 1px solid {BORDER};
    font-weight: 800; font-size: 10px;
}}
QTableCornerButton::section {{ background-color: {BG_DEEP}; border: none; }}

/* ==== dock consola / barra estado / scrollbars ====================== */
QDockWidget {{ color: {TEXT}; titlebar-close-icon: none; titlebar-normal-icon: none; }}
QDockWidget::title {{
    background-color: {BG_DEEP}; color: {MUTED};
    padding: 8px 14px; border-top: 1px solid {BORDER}; font-weight: 800; font-size: 10px;
}}
QStatusBar {{ background-color: {BG_DEEP}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_HI}; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_HI}; border-radius: 5px; min-width: 28px; }}
QScrollBar::handle:horizontal:hover {{ background: {MUTED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ==== menús / splitter / progress ================================== */
QMenuBar {{ background-color: {BG}; color: {TEXT}; }}
QMenuBar::item:selected {{ background: {PANEL}; }}
QMenu {{ background-color: {PANEL}; color: {TEXT}; border: 1px solid {BORDER_HI}; border-radius: {RSM}px; }}
QMenu::item:selected {{ background-color: {ACCENT_MUTED}; color: {TEXT}; }}
QSplitter::handle {{ background-color: {BORDER}; }}
QProgressBar {{ background-color: {BG_DEEP}; border: 1px solid {BORDER}; border-radius: {RSM}px;
    text-align: center; color: {TEXT}; }}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: {RSM}px; }}

/* grupos (compat: paneles aún no migrados usan QGroupBox) */
QGroupBox {{
    background-color: {PANEL}; border: 1px solid {BORDER}; border-radius: {RMD}px;
    margin-top: 12px; padding: 12px 10px 10px 10px; font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 10px; padding: 1px 6px; color: {MUTED}; background-color: transparent;
    font-size: 10px; font-weight: 800;
}}
QFrame[frameShape="4"], QFrame[frameShape="5"] {{ color: {BORDER}; }}
"""


def _refresh_constants(pal: dict) -> None:
    """Reasigna las constantes de módulo (para tintar iconos/marca por atributo)."""
    global BG, BG_DEEP, PANEL, SURFACE2, SURFACE3, BORDER, BORDER_HI, TEXT, MUTED
    global ACCENT, ACCENT_HI, ACCENT_FG, ACCENT_MUTED
    global SUCCESS, SUCCESS_FG, WARNING, WARNING_FG, ERROR, ERROR_FG, INFO, INFO_FG
    p = palettes._derive(pal)
    BG, BG_DEEP, PANEL = p["bg"], p["bg_deep"], p["panel"]
    SURFACE2, SURFACE3 = p["surface2"], p["surface3"]
    BORDER, BORDER_HI, TEXT, MUTED = p["border"], p["border_hi"], p["text"], p["muted"]
    ACCENT, ACCENT_HI, ACCENT_FG, ACCENT_MUTED = p["accent"], p["accent_hi"], p["accent_fg"], p["accent_muted"]
    SUCCESS, SUCCESS_FG = p["success"], p["success_fg"]
    WARNING, WARNING_FG = p["warning"], p["warning_fg"]
    ERROR, ERROR_FG, INFO, INFO_FG = p["error"], p["error_fg"], p["info"], p["info_fg"]


def apply_theme(app, palette_name: str | None = None) -> None:
    """Aplica el tema (fuente + QSS) a la `QApplication`. Idempotente.

    `palette_name` elige la paleta; si es None usa el tema de los ajustes. El QSS
    es dirigido por propiedades, así que se re-aplica en vivo y recolorea toda la
    UI (incluido el kit de componentes) sin reiniciar.
    """
    from PySide6.QtGui import QFont
    if palette_name is None:
        from .. import settings
        palette_name = settings.load().theme
    pal = palettes.get(palette_name)
    _refresh_constants(pal)
    font = QFont()
    try:
        font.setFamilies(FONT_FAMILIES)
    except Exception:
        font.setFamily(FONT_FAMILIES[0])
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(build_qss(pal))
