"""
lenses.py - Lens overlay windows (Qt) and the LensManager that owns them.

A lens is a borderless, always-on-top, see-through window:

    +--------------------------+  <- header strip (drag to move, shows the name)
    |########## name ##########|
    |##                      ##|  <- coloured frame (drag its edges to resize)
    |##   see-through area   ##|  <- the capture region (excludes header + frame,
    |##                      ##|     so a lens never captures its own paint)
    |##########################|
    +--------------------------+

Lenses are global to the app: every Lenses panel shows the same LensManager,
and scripts see them as `Lenses["name"]`. Each window keeps its capture region
as plain ints in *physical* screen pixels (what mss grabs), updated on the GUI
thread whenever it moves, so worker threads can read it without touching Qt.
"""

import sys
import threading
import time
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from .bridge import gui_call, on_gui_thread
from .vision import Lens

PALETTE = ["#00ff66", "#ff2bd6", "#00d5ff", "#ffd400", "#ff7a00", "#ff3b3b"]
LABEL_COLOR = "#111111"


def _physical_window_rect(widget: QWidget) -> Optional[QRect]:
    """The window's rectangle in physical pixels (Windows), else None."""
    if not sys.platform.startswith("win"):
        return None
    import ctypes
    from ctypes import wintypes
    rect = wintypes.RECT()
    if ctypes.windll.user32.GetWindowRect(int(widget.winId()), ctypes.byref(rect)):
        return QRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    return None


class LensWindow(QWidget):
    BORDER = 4      # px (logical) thickness of the visible frame
    HEADER = 18     # px (logical) height of the name/drag strip
    GRAB = 8        # px (logical) edge zone that starts a resize
    MIN_W = 50
    MIN_H = HEADER + 30

    def __init__(self, name: str, color: str, rect: QRect, capture_guard):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setMinimumSize(self.MIN_W, self.MIN_H)
        self.lens_name = name
        self.color = color
        self._manual_hidden = False
        self._region = (0, 0, 1, 1)           # physical (left, top, width, height)
        self.setGeometry(rect)
        # Backend object handed to scripts. It only reads the plain-int region.
        self.lens = Lens(name, lambda: self._region, capture_guard=capture_guard)
        self.show()
        self._update_region()

    # ------------------------------------------------------------------ API
    @property
    def capture_region(self):
        return self._region

    def to_dict(self) -> dict:
        g = self.geometry()
        return {"name": self.lens_name, "color": self.color, "left": g.x(), "top": g.y(),
                "width": g.width(), "height": g.height()}

    def set_name(self, name: str) -> None:
        self.lens_name = name
        self.lens.name = name
        self.update()

    def set_manual_hidden(self, hidden: bool) -> None:
        self._manual_hidden = hidden
        self.setVisible(not hidden)
        if not hidden:
            self.raise_()

    def set_capture_hidden(self, hidden: bool) -> None:
        self.setWindowOpacity(0.0 if hidden else 1.0)

    # ------------------------------------------------------- capture region
    def _update_region(self) -> None:
        """Recompute the see-through area in physical pixels (GUI thread)."""
        dpr = self.devicePixelRatioF()
        phys = _physical_window_rect(self)
        if phys is None:                      # non-Windows: logical * scale
            g = self.geometry()
            phys = QRect(round(g.x() * dpr), round(g.y() * dpr),
                         round(g.width() * dpr), round(g.height() * dpr))
        b, hd = round(self.BORDER * dpr), round(self.HEADER * dpr)
        self._region = (phys.x() + b, phys.y() + hd + b,
                        max(1, phys.width() - 2 * b), max(1, phys.height() - hd - 2 * b))

    def moveEvent(self, e):
        super().moveEvent(e)
        self._update_region()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_region()

    # ------------------------------------------------------------ rendering
    def paintEvent(self, _e):
        p = QPainter(self)
        w, h, b, hd = self.width(), self.height(), self.BORDER, self.HEADER
        c = QColor(self.color)
        p.fillRect(0, 0, w, hd, c)                 # header strip
        p.fillRect(0, hd, b, h - hd, c)            # left
        p.fillRect(w - b, hd, b, h - hd, c)        # right
        p.fillRect(0, hd, w, b, c)                 # top of frame
        p.fillRect(0, h - b, w, b, c)              # bottom
        # The see-through area stays unpainted (alpha 0): it is invisible and
        # clicks pass through it to whatever is underneath.
        p.setPen(QColor(LABEL_COLOR))
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.drawText(QRect(6, 0, w - 8, hd), Qt.AlignVCenter | Qt.AlignLeft, self.lens_name)

    # ---------------------------------------------------------- interaction
    def _zone(self, pos: QPoint) -> str:
        """'' for the move area, else a combination of 'n', 's', 'w', 'e'."""
        x, y, g = pos.x(), pos.y(), self.GRAB
        if y < self.HEADER:
            return ""
        v = "n" if y < self.HEADER + g else ("s" if y >= self.height() - g else "")
        h = "w" if x < g else ("e" if x >= self.width() - g else "")
        return v + h

    _CURSORS = {"": Qt.SizeAllCursor, "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
                "w": Qt.SizeHorCursor, "e": Qt.SizeHorCursor, "nw": Qt.SizeFDiagCursor,
                "se": Qt.SizeFDiagCursor, "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor}
    _EDGES = {"n": Qt.TopEdge, "s": Qt.BottomEdge, "w": Qt.LeftEdge, "e": Qt.RightEdge}

    def mouseMoveEvent(self, e):
        self.setCursor(self._CURSORS[self._zone(e.position().toPoint())])

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        zone = self._zone(e.position().toPoint())
        handle = self.windowHandle()
        if not zone:
            handle.startSystemMove()          # native move: smooth, multi-monitor aware
            return
        edges = self._EDGES[zone[0]]
        for c in zone[1:]:
            edges = edges | self._EDGES[c]
        handle.startSystemResize(edges)


class LensManager(QObject):
    """Owns all lens windows; hides them on request so they never get captured.

    * Manual toggle (`set_manually_hidden`) - the eye button in Lenses panels.
    * Hide-while-measuring (`capture_guard`) - wrapped around every Lens capture.
      Scripts capture on worker threads, so the guard asks the GUI thread (via
      the bridge) to make the lenses transparent, waits for that, then waits
      `settle_ms` for the desktop compositor to repaint before pixels are read.
      Lenses stay hidden `linger_ms` after the last capture, so reading several
      lenses back to back does not flicker.
    """

    changed = Signal()                    # lens added / removed / renamed
    hidden_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.windows: Dict[str, LensWindow] = {}
        self._color_index = 0
        self.manually_hidden = False
        self.hide_while_measuring = True
        self.settle_ms = 50
        self.linger_ms = 80
        self._lock = threading.Lock()
        self._active = 0
        self._capture_hidden = False
        self._hidden: List[LensWindow] = []

    # ------------------------------------------------------------ registry
    def names(self) -> List[str]:
        return list(self.windows)

    def snapshot(self) -> Dict[str, Lens]:
        """name -> script-facing Lens objects (GUI thread)."""
        return {name: win.lens for name, win in self.windows.items()}

    def next_default_name(self) -> str:
        i = len(self.windows) + 1
        while f"lens{i}" in self.windows:
            i += 1
        return f"lens{i}"

    def add(self, name: Optional[str] = None, color: Optional[str] = None,
            rect: Optional[QRect] = None) -> LensWindow:
        name = (name or "").strip() or self.next_default_name()
        if name in self.windows:
            raise ValueError(f"A lens named {name!r} already exists.")
        if color is None:
            color = PALETTE[self._color_index % len(PALETTE)]
            self._color_index += 1
        if rect is None:
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            area = screen.availableGeometry()
            offset = 40 * (len(self.windows) % 8)
            rect = QRect(area.x() + area.width() // 3 + offset,
                         area.y() + area.height() // 3 + offset, 220, 90)
        self.set_manually_hidden(False)          # a new lens should never appear hidden
        win = LensWindow(name, color, rect, self.capture_guard)
        self.windows[name] = win
        self.changed.emit()
        return win

    def rename(self, old: str, new: str) -> bool:
        new = new.strip()
        if old not in self.windows or not new or (new != old and new in self.windows):
            return False
        self.windows = {(new if k == old else k): v for k, v in self.windows.items()}
        self.windows[new].set_name(new)
        self.changed.emit()
        return True

    def remove(self, name: str) -> None:
        win = self.windows.pop(name, None)
        if win is not None:
            win.close()
            win.deleteLater()
            self.changed.emit()

    def clear(self) -> None:
        for win in self.windows.values():
            win.close()
            win.deleteLater()
        self.windows = {}
        self._color_index = 0
        self.changed.emit()

    def specs(self) -> List[dict]:
        return [win.to_dict() for win in self.windows.values()]

    def load(self, specs: List[dict]) -> List[str]:
        """Replace all lenses. Returns names that were moved back onto a screen."""
        self.clear()
        moved = []
        desktop = QRect()
        for screen in QGuiApplication.screens():
            desktop = desktop.united(screen.geometry())
        for i, spec in enumerate(specs):
            rect = QRect(spec["left"], spec["top"], spec["width"], spec["height"])
            if not desktop.intersected(rect).width() >= 40 or not desktop.intersected(rect).height() >= 20:
                # Saved on a monitor that is not connected now: bring it into view.
                rect.moveTopLeft(desktop.topLeft() + QPoint(240 + 40 * (i % 8), 180 + 40 * (i % 8)))
                moved.append(spec["name"])
            self.add(spec["name"], spec.get("color"), rect)
        self._color_index = len(specs)
        return moved

    # ----------------------------------------------------- manual toggle
    def set_manually_hidden(self, hidden: bool) -> None:
        if hidden == self.manually_hidden:
            return
        self.manually_hidden = hidden
        for win in self.windows.values():
            win.set_manual_hidden(hidden)
        self.hidden_changed.emit(hidden)

    # -------------------------------------------------- per-capture hide
    @contextmanager
    def capture_guard(self) -> Iterator[None]:
        """Keeps lenses invisible while the body grabs pixels (any thread)."""
        if not self.hide_while_measuring or self.manually_hidden or not self.windows:
            yield
            return

        if on_gui_thread():
            windows = list(self.windows.values())
            for win in windows:
                win.set_capture_hidden(True)
            QGuiApplication.processEvents()
            time.sleep(self.settle_ms / 1000)
            try:
                yield
            finally:
                for win in windows:
                    win.set_capture_hidden(False)
            return

        with self._lock:
            self._active += 1
            need_hide = not self._capture_hidden
            if need_hide:
                self._capture_hidden = True
        try:
            if need_hide:
                try:
                    gui_call(self._hide_for_capture, timeout=1.0)
                except TimeoutError:
                    pass
                time.sleep(self.settle_ms / 1000)       # let the compositor repaint
            yield
        finally:
            with self._lock:
                self._active -= 1
                idle = self._active == 0
            if idle:
                gui_call(self._schedule_restore, wait=False)

    def _hide_for_capture(self) -> None:
        self._hidden = list(self.windows.values())
        for win in self._hidden:
            win.set_capture_hidden(True)

    def _schedule_restore(self) -> None:
        QTimer.singleShot(self.linger_ms, self._restore_if_idle)

    def _restore_if_idle(self) -> None:
        with self._lock:
            if self._active != 0 or not self._capture_hidden:
                return
            self._capture_hidden = False
        for win in self._hidden:
            try:
                win.set_capture_hidden(False)
            except RuntimeError:
                pass                            # deleted in the meantime
        self._hidden = []
