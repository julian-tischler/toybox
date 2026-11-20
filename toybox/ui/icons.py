"""
icons.py - Themed icons rendered from the SVGs in assets/icons/.

The SVGs are single-colour stroke icons (stroke="#000000"); the colour is
swapped before rendering, so one SVG serves every state (muted / normal /
error). Qt renders them crisply at any DPI.
"""

import os
from typing import Dict, Tuple

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets", "icons")
COLORS = {"fg": theme.FG, "muted": theme.MUTED, "error": theme.ERROR_FG, "accent": theme.ACCENT}

_cache: Dict[Tuple[str, str], QIcon] = {}


def _render(name: str, color: str, size: int, dpr: float) -> QPixmap:
    with open(os.path.join(ICON_DIR, f"{name}.svg"), "r", encoding="utf-8") as f:
        svg = f.read().replace("#000000", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    px = round(size * dpr)
    pix = QPixmap(px, px)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    renderer.render(p, QRectF(0, 0, px, px))
    p.end()
    pix.setDevicePixelRatio(dpr)
    return pix


def icon(name: str, color: str = "muted", hover: str = "") -> QIcon:
    """QIcon for `name` in a theme colour key; `hover` adds an Active-mode colour
    (shown by tool buttons under the mouse)."""
    key = (name, f"{color}/{hover}")
    if key not in _cache:
        ic = QIcon()
        for dpr in (1.0, 1.25, 1.5, 2.0):
            ic.addPixmap(_render(name, COLORS.get(color, color), 16, dpr), QIcon.Normal)
            if hover:
                ic.addPixmap(_render(name, COLORS.get(hover, hover), 16, dpr), QIcon.Active)
        _cache[key] = ic
    return _cache[key]


ICON_SIZE = QSize(16, 16)
