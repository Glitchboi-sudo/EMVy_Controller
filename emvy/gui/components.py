"""Kit de componentes reutilizables de la GUI (PySide6) — vocabulario común para
componer paneles con aspecto de producto profesional, sin estilos en línea.

Todo se estiliza por `objectName` / propiedad dinámica en el QSS global
(`gui.theme`), de modo que los componentes **recolorean en vivo** al cambiar de
tema. La geometría (espaciado/radios) sale de `emvy.design`. Solo iconos SVG
(`gui.icons`), nunca emojis.

Piezas: `PageHeader`, `Card`/`SectionCard`, `StatCard`, `icon_badge`, `Chip`
(estado con contorno), `Pill` (compat), `SectionLabel`, `Divider`, `button()`/
`primary_button()`, `EmptyState`.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import design
from .icons import icon as _icon

_SP = design.SPACE


def _repolish(w: QWidget) -> None:
    """Re-evalúa el QSS de `w` tras cambiar una propiedad dinámica."""
    st = w.style()
    st.unpolish(w)
    st.polish(w)
    w.update()


# -- botones -----------------------------------------------------------------
def button(text: str, *, variant: str = "default", icon_name: str | None = None,
           on_click: Callable | None = None) -> QPushButton:
    """Botón semántico. `variant`: default / primary / success / danger / ghost."""
    b = QPushButton(text)
    if variant != "default":
        b.setProperty("variant", variant)
    if icon_name:
        from . import theme
        color = {"primary": theme.ACCENT_FG, "success": theme.SUCCESS_FG,
                 "danger": theme.ERROR}.get(variant, theme.MUTED)
        b.setIcon(_icon(icon_name, color=color))
    if on_click is not None:
        b.clicked.connect(on_click)
    return b


def primary_button(text: str, *, icon_name: str | None = None,
                   on_click: Callable | None = None) -> QPushButton:
    """Botón de acción primaria (acento)."""
    return button(text, variant="primary", icon_name=icon_name, on_click=on_click)


# -- texto / separadores -----------------------------------------------------
class SectionLabel(QLabel):
    """Etiqueta de sección en mayúsculas tenues (overline)."""

    def __init__(self, text: str) -> None:
        super().__init__(text.upper())
        self.setProperty("role", "overline")


class Divider(QFrame):
    """Línea divisoria horizontal fina."""

    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.HLine)
        self.setFixedHeight(1)


# -- chips de estado ---------------------------------------------------------
class Chip(QLabel):
    """Chip de estado con contorno (sobrio). `kind`: neutral / accent / on / off /
    warn / error / info (+ solid-accent / solid-on). El color lo pone el QSS."""

    def __init__(self, text: str = "", kind: str = "neutral") -> None:
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        self.setProperty("chip", kind)
        _repolish(self)

    def set_chip(self, text: str, kind: str) -> None:
        self.setText(text)
        self.set_kind(kind)


class Pill(QLabel):
    """Compat: insignia de estado (usa la propiedad `pill`). Prefiere `Chip`."""

    def __init__(self, text: str = "", kind: str = "neutral") -> None:
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        self.setProperty("pill", kind)
        _repolish(self)

    def set_pill(self, text: str, kind: str) -> None:
        self.setText(text)
        self.set_kind(kind)


# -- insignia de icono -------------------------------------------------------
def icon_badge(icon_name: str, *, kind: str = "accent", size: int = 40) -> QLabel:
    """Insignia de icono: cuadrado sobrio (`badge` en QSS) con el icono centrado.
    En `accent` el icono va en color de acento; el resto en tenue."""
    from . import theme
    color = theme.ACCENT if kind == "accent" else theme.MUTED
    b = QLabel(); b.setProperty("badge", kind)
    b.setFixedSize(size, size); b.setAlignment(Qt.AlignCenter)
    g = size - 20
    b.setPixmap(_icon(icon_name, color=color, size=g).pixmap(g, g))
    return b


# -- contenedores ------------------------------------------------------------
class Card(QFrame):
    """Contenedor con borde redondeado. `variant`: true / hero / stat. Expone
    `body` (QVBoxLayout) y `add()`."""

    def __init__(self, *, variant: str = "true", margins: str = "md",
                 spacing: str = "xs") -> None:
        super().__init__()
        self.setProperty("card", variant)
        m = _SP[margins]
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(m, m, m, m)
        self.body.setSpacing(_SP[spacing])

    def add(self, w) -> None:
        if isinstance(w, QWidget):
            self.body.addWidget(w)
        else:
            self.body.addLayout(w)


class SectionCard(Card):
    """Tarjeta con una cabecera de sección (overline) y, opcionalmente, un chip a
    la derecha."""

    def __init__(self, title: str, *, chip: tuple[str, str] | None = None, **kw) -> None:
        super().__init__(**kw)
        head = QHBoxLayout(); head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(SectionLabel(title)); head.addStretch(1)
        if chip:
            head.addWidget(Chip(chip[0], chip[1]))
        self.body.addLayout(head)


class StatCard(QFrame):
    """Tarjeta de estado/KPI: insignia de icono + etiqueta pequeña + valor + chip
    de estado + detalle tenue. Aspecto de tarjeta de producto."""

    def __init__(self, label: str, value: str = "—", caption: str = "",
                 *, icon_name: str | None = None, badge: str = "neutral") -> None:
        super().__init__()
        self.setProperty("card", "stat")
        row = QHBoxLayout(self)
        row.setContentsMargins(_SP["md"], _SP["sm"], _SP["md"], _SP["sm"])
        row.setSpacing(_SP["sm"])
        if icon_name:
            row.addWidget(icon_badge(icon_name, kind=badge, size=34), 0, Qt.AlignVCenter)

        col = QVBoxLayout(); col.setSpacing(2)
        top = QHBoxLayout(); top.setSpacing(_SP["sm"])
        self._label = QLabel(label.upper()); self._label.setProperty("role", "statlabel")
        top.addWidget(self._label); top.addStretch(1)
        self._chip = Chip("", "off"); self._chip.setVisible(False)
        top.addWidget(self._chip)
        col.addLayout(top)
        self._value = QLabel(value); self._value.setProperty("role", "statvalue")
        self._value.setWordWrap(True)
        self._caption = QLabel(caption); self._caption.setProperty("role", "caption")
        self._caption.setWordWrap(True)
        col.addWidget(self._value)
        col.addWidget(self._caption)
        row.addLayout(col, 1)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_caption(self, caption: str) -> None:
        self._caption.setText(caption)

    def set_status(self, text: str, kind: str) -> None:
        """Muestra (u oculta si `text` vacío) el chip de estado de la tarjeta."""
        if text:
            self._chip.set_chip(text, kind); self._chip.setVisible(True)
        else:
            self._chip.setVisible(False)


class PageHeader(QWidget):
    """Cabecera de página: título grande + subtítulo tenue a la izquierda y una
    barra de acciones a la derecha."""

    def __init__(self, title: str, subtitle: str = "", *,
                 actions: Sequence[QWidget] = ()) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(_SP["md"])
        col = QVBoxLayout(); col.setSpacing(2)
        self._title = QLabel(title); self._title.setProperty("role", "h1")
        col.addWidget(self._title)
        self._sub = QLabel(subtitle); self._sub.setProperty("role", "caption")
        self._sub.setWordWrap(True); self._sub.setVisible(bool(subtitle))
        col.addWidget(self._sub)
        row.addLayout(col, 1)
        for a in actions:
            row.addWidget(a, 0, Qt.AlignVCenter)

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self._sub.setText(subtitle); self._sub.setVisible(bool(subtitle))


class EmptyState(QWidget):
    """Estado vacío centrado: insignia de icono + título + ayuda + CTA opcional."""

    def __init__(self, title: str, body: str = "", *, icon_name: str | None = None,
                 cta: str | None = None, on_cta: Callable | None = None) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(_SP["sm"])
        if icon_name:
            badge = icon_badge(icon_name, kind="neutral", size=48)
            wrap = QHBoxLayout(); wrap.addStretch(1); wrap.addWidget(badge); wrap.addStretch(1)
            v.addLayout(wrap)
        t = QLabel(title); t.setProperty("role", "h2"); t.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        if body:
            b = QLabel(body); b.setProperty("role", "caption")
            b.setAlignment(Qt.AlignCenter); b.setWordWrap(True)
            v.addWidget(b)
        if cta:
            row = QHBoxLayout(); row.addStretch(1)
            row.addWidget(primary_button(cta, on_click=on_cta))
            row.addStretch(1)
            v.addLayout(row)
