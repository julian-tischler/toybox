"""
widgets.py - Small shared widgets.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSplitter, QSplitterHandle, QToolButton

from . import theme
from .icons import ICON_SIZE, icon


class _LineHandle(QSplitterHandle):
    """Thin centred line in a wider grab area, lighter on hover."""

    LINE = 3

    def __init__(self, orientation, splitter):
        super().__init__(orientation, splitter)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        color = QColor(theme.DIVIDER_HOVER if self._hover else theme.DIVIDER)
        r = self.rect()
        if self.orientation() == Qt.Horizontal:
            p.fillRect((r.width() - self.LINE) // 2, 0, self.LINE, r.height(), color)
        else:
            p.fillRect(0, (r.height() - self.LINE) // 2, r.width(), self.LINE, color)


class LineSplitter(QSplitter):
    """Splitter inside a panel (not part of the workspace layout)."""

    def __init__(self, orientation=Qt.Vertical):
        super().__init__(orientation)
        self.setHandleWidth(9)

    def createHandle(self):
        return _LineHandle(self.orientation(), self)


def icon_button(name: str, tooltip: str, color: str = "muted", hover: str = "fg") -> QToolButton:
    btn = QToolButton()
    btn.setIcon(icon(name, color, hover=hover))
    btn.setIconSize(ICON_SIZE)
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    return btn
