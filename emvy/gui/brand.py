"""Marca de EMVy (GUI): logotipo/wordmark/lockup desde SVG, recoloreados al
tema. Los SVG de `assets/` son monocromos (sin `fill` → negro), así que se
**tintan** por alfa: se rasteriza el trazo a un pixmap transparente y se pinta
el color destino a través de su máscara (`CompositionMode_SourceIn`). Así el
mismo asset sirve en blanco (sobre fondo oscuro), acento verde o el color que
pida cada contexto, sin duplicar ficheros.

Assets (ver `assets/`):
  * ``logo``      — solo la marca (chip EMV estilizado), ~2.8:1.
  * ``wordmark``  — solo el texto "EMVy", ~5:1.
  * ``lockup``    — marca + texto apilados, ~1.7:1.

`brand_pixmap(name, height, color)` devuelve un `QPixmap` a la altura pedida
(ancho proporcional al viewBox); `brand_icon(name, color, size)` un `QIcon`
cuadrado (para el icono de ventana / app). Ambos cachean por (name,dims,color).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import ACCENT, BG, TEXT

_NAMES = {"logo", "wordmark", "lockup"}


def _assets_dir() -> Path:
    here = Path(__file__).resolve().parent / "assets"
    if here.is_dir():
        return here
    from .. import config  # frozen (PyInstaller): datas → <_MEIPASS>/emvy/gui/assets
    return config.repo_root() / "emvy" / "gui" / "assets"


@lru_cache(maxsize=None)
def _renderer_size(name: str) -> tuple[bytes, float, float]:
    """Bytes del SVG + (ancho, alto) de su viewBox. Cacheado por nombre."""
    data = (_assets_dir() / f"{name}.svg").read_bytes()
    r = QSvgRenderer(QByteArray(data))
    box = r.viewBoxF()
    w = box.width() or float(r.defaultSize().width()) or 1.0
    h = box.height() or float(r.defaultSize().height()) or 1.0
    return data, w, h


@lru_cache(maxsize=None)
def brand_pixmap(name: str, height: int = 40, color: str = TEXT) -> QPixmap:
    """`QPixmap` de la marca a `height` px de alto (ancho proporcional), tintado
    a `color`. Nombre desconocido → pixmap vacío."""
    if name not in _NAMES:
        return QPixmap()
    data, vw, vh = _renderer_size(name)
    height = max(1, int(height))
    width = max(1, round(height * vw / vh))

    # 1) rasterizar el trazo (negro) sobre transparente → máscara alfa nítida.
    shape = QPixmap(width, height)
    shape.fill(Qt.transparent)
    p = QPainter(shape)
    p.setRenderHint(QPainter.Antialiasing, True)
    QSvgRenderer(QByteArray(data)).render(p, QRectF(0, 0, width, height))
    p.end()

    # 2) tintar: pintar el color destino a través de esa máscara.
    out = QPixmap(width, height)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawPixmap(0, 0, shape)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()
    return out


@lru_cache(maxsize=None)
def app_pixmap(size: int = 256, bg: str = BG, fg: str = ACCENT) -> QPixmap:
    """Icono de aplicación: cuadrado redondeado con fondo `bg` y la marca (`logo`)
    centrada en `fg`. Legible sobre cualquier barra de tareas (a diferencia de una
    silueta plana sobre transparente). Mismo diseño que `packaging/emvy.svg`."""
    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    r = size * 0.1875  # 48/256
    path.addRoundedRect(0, 0, size, size, r, r)
    p.fillPath(path, QColor(bg))
    mark = brand_pixmap("logo", height=round(size * 0.30), color=fg)
    p.drawPixmap((size - mark.width()) // 2, (size - mark.height()) // 2, mark)
    p.end()
    return canvas


@lru_cache(maxsize=None)
def brand_icon(name: str = "logo", color: str = TEXT, size: int = 256) -> QIcon:
    """`QIcon` de la app (fondo + marca) para icono de ventana/taskbar. `name`/
    `color` se conservan por compatibilidad; el icono usa el diseño compuesto."""
    return QIcon(app_pixmap(size, fg=color if color != TEXT else ACCENT))
