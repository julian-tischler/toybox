"""
workspace.py - The modular workspace: a tree of splitters holding panel frames.

    Workspace
      ├─ EdgeHandle x4 (left/right/top/bottom window edges)
      └─ root: PanelFrame | Splitter
                Splitter(orientation) -> children: PanelFrame | Splitter ...

Interactions
  * Double-click a divider (between two panels) -> a new empty space there.
  * Double-click a window-edge line             -> a new empty space at that edge.
  * An empty space shows a picker of all registered tools.
  * Drag a panel by its header onto another panel: drop near an edge to dock it
    on that side, in the middle to swap the two. Drop on a window-edge line to
    dock it along that whole edge.
  * Panel header: rename (double-click the name), ⋮ menu (split, change tool,
    tool-specific actions), close.

The tree is kept tidy: a splitter with one child is replaced by that child, and
a splitter nested in a splitter of the same orientation is flattened into it.
"""

from typing import Dict, Iterator, List, Optional

from PySide6.QtCore import QMimeData, QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QPainter
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QSplitter,
                               QSplitterHandle, QToolButton, QVBoxLayout, QWidget)

from ..panels.base import REGISTRY, Panel
from . import theme
from .icons import ICON_SIZE, icon

MIME = "application/x-toybox-panel"
HANDLE_PX = 9          # divider grab / hover area (logical px)
LINE_PX = 3            # visible divider line inside it
SIDES = ("left", "right", "top", "bottom")


def _orientation(side: str) -> Qt.Orientation:
    return Qt.Horizontal if side in ("left", "right") else Qt.Vertical


def _paint_divider(widget: QWidget, orientation: Qt.Orientation, color: str) -> None:
    p = QPainter(widget)
    r = widget.rect()
    if orientation == Qt.Horizontal:        # vertical line (splits left | right)
        x = (r.width() - LINE_PX) // 2
        p.fillRect(x, 0, LINE_PX, r.height(), QColor(color))
    else:
        y = (r.height() - LINE_PX) // 2
        p.fillRect(0, y, r.width(), LINE_PX, QColor(color))


# ------------------------------------------------------------------ dividers
class SplitHandle(QSplitterHandle):
    """Thin line in a wider grab area; lights up on hover; double-click inserts."""

    def __init__(self, orientation, splitter):
        super().__init__(orientation, splitter)
        self._hover = False
        self.setToolTip("Drag to resize · double-click to add a panel here")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        _paint_divider(self, self.orientation(),
                       theme.DIVIDER_HOVER if self._hover else theme.DIVIDER)

    def mouseDoubleClickEvent(self, e):
        sp = self.splitter()
        sp.workspace.insert_at_handle(sp, sp.indexOf(self))
        e.accept()


class Splitter(QSplitter):
    def __init__(self, orientation, workspace: "Workspace"):
        super().__init__(orientation)
        self.workspace = workspace
        self.setHandleWidth(HANDLE_PX)
        self.setChildrenCollapsible(False)

    def createHandle(self):
        return SplitHandle(self.orientation(), self)


class EdgeHandle(QWidget):
    """Line along one window edge: double-click adds a panel along that edge;
    dropping a dragged panel here docks it along the whole edge."""

    def __init__(self, workspace: "Workspace", side: str):
        super().__init__()
        self.workspace = workspace
        self.side = side
        self._hover = False
        self._drop = False
        self.setAcceptDrops(True)
        if side in ("left", "right"):
            self.setFixedWidth(HANDLE_PX)
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setFixedHeight(HANDLE_PX)
            self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"Double-click to add a panel on the {side}")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        color = theme.ACCENT if self._drop else (
            theme.DIVIDER_HOVER if self._hover else theme.DIVIDER)
        # A left/right edge is a vertical line, i.e. drawn like a horizontal splitter's handle.
        _paint_divider(self, _orientation(self.side), color)

    def mouseDoubleClickEvent(self, e):
        self.workspace.add_at_edge(self.side)
        e.accept()

    def dragEnterEvent(self, e):
        if self.workspace.drag_source is not None and e.mimeData().hasFormat(MIME):
            self._drop = True
            self.update()
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._drop = False
        self.update()

    def dropEvent(self, e):
        self._drop = False
        self.update()
        src = self.workspace.drag_source
        if src is not None:
            e.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.workspace.move_to_edge(src, self.side))


# ---------------------------------------------------------------- frames
class DropOverlay(QWidget):
    """Highlights where a dragged panel would land on the frame below it."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.zone = ""
        self.hide()

    def show_zone(self, zone: str) -> None:
        self.zone = zone
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect()
        w, h = r.width(), r.height()
        target = {"left": QRect(0, 0, w // 2, h), "right": QRect(w - w // 2, 0, w // 2, h),
                  "top": QRect(0, 0, w, h // 2), "bottom": QRect(0, h - h // 2, w, h // 2),
                  "center": r}.get(self.zone, r)
        fill = QColor(theme.ACCENT)
        fill.setAlpha(55)
        p.fillRect(target.adjusted(3, 3, -3, -3), fill)
        p.setPen(QColor(theme.ACCENT))
        p.drawRect(target.adjusted(3, 3, -4, -4))
        if self.zone == "center":
            p.drawText(r, Qt.AlignCenter, "Swap")


class Picker(QWidget):
    """Content of an empty space: one button per registered tool."""

    COLUMNS = 3

    def __init__(self, frame: "PanelFrame"):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        outer.addWidget(scroll)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.addStretch(1)
        title = QLabel("Choose a tool for this space")
        title.setAlignment(Qt.AlignCenter)
        title.setProperty("muted", True)
        lay.addWidget(title)
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (kind, cls) in enumerate(REGISTRY.items()):
            btn = QPushButton(cls.title)
            btn.setToolTip(cls.description)
            btn.setMinimumSize(110, 30)
            btn.clicked.connect(lambda _=False, k=kind: frame.workspace.fill(frame, k))
            grid.addWidget(btn, i // self.COLUMNS, i % self.COLUMNS)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addLayout(grid)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(2)
        scroll.setWidget(content)


class PanelFrame(QFrame):
    """A space in the workspace: header (drag handle, name, menu, close) + body."""

    def __init__(self, workspace: "Workspace"):
        super().__init__()
        self.workspace = workspace
        self.panel: Optional[Panel] = None
        self.setAcceptDrops(True)
        self.setMinimumSize(120, 80)
        self._press: Optional[QPoint] = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)

        self.header = QWidget()
        self.header.setObjectName("panelHeader")
        self.header.setCursor(Qt.OpenHandCursor)
        self.header.setToolTip("Drag to move this panel")
        h = QHBoxLayout(self.header)
        h.setContentsMargins(8, 3, 4, 3)
        h.setSpacing(6)
        self.kind_label = QLabel()
        self.kind_label.setObjectName("panelKind")
        self.name_label = QLabel()
        self.name_label.setObjectName("panelName")
        self.name_label.setToolTip("Double-click to rename")
        self.name_label.setCursor(Qt.IBeamCursor)
        self.name_edit: Optional[QLineEdit] = None
        h.addWidget(self.kind_label)
        h.addWidget(self.name_label)
        h.addStretch(1)
        self.extra = QHBoxLayout()
        self.extra.setSpacing(2)
        h.addLayout(self.extra)
        self.menu_btn = QToolButton()
        self.menu_btn.setObjectName("panelMenu")
        self.menu_btn.setText("⋯")
        self.menu_btn.setToolTip("Panel menu")
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        self.menu_btn.setMenu(QMenu(self.menu_btn))
        self.menu_btn.menu().aboutToShow.connect(self._fill_menu)
        h.addWidget(self.menu_btn)
        self.close_btn = QToolButton()
        self.close_btn.setIcon(icon("xmark-circle", "muted", hover="error"))
        self.close_btn.setIconSize(ICON_SIZE)
        self.close_btn.setToolTip("Close this panel")
        self.close_btn.clicked.connect(lambda: self.workspace.close_frame(self))
        h.addWidget(self.close_btn)
        for w in (self.header, self.kind_label, self.name_label):
            w.installEventFilter(self)
        lay.addWidget(self.header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(self.body, 1)
        self._content: Optional[QWidget] = None
        self.overlay = DropOverlay(self)
        self.set_panel(None)

    # ----------------------------------------------------------- content
    def set_panel(self, panel: Optional[Panel]) -> None:
        if self._content is not None:
            self.body.removeWidget(self._content)
            self._content.setParent(None)
            self._content.deleteLater()
        while self.extra.count():
            w = self.extra.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
        self.panel = panel
        if panel is None:
            self._content = Picker(self)
        else:
            self._content = panel
            for w in panel.header_widgets():
                self.extra.addWidget(w)
        self.body.addWidget(self._content, 1)
        self._update_title()

    def _update_title(self) -> None:
        if self.panel is None:
            self.kind_label.setText("EMPTY")
            self.name_label.setText("")
        else:
            self.kind_label.setText(self.panel.title.upper())
            self.name_label.setText(self.panel.name)

    # ------------------------------------------------------------- menu
    def _fill_menu(self) -> None:
        m = self.menu_btn.menu()
        m.clear()
        ws = self.workspace
        for label, side in (("Split right", "right"), ("Split left", "left"),
                            ("Split below", "bottom"), ("Split above", "top")):
            m.addAction(label, lambda s=side: ws.split(self, s, ws.new_frame()))
        m.addSeparator()
        change = m.addMenu("Change tool")
        for kind, cls in REGISTRY.items():
            act = change.addAction(cls.title, lambda k=kind: ws.change_kind(self, k))
            act.setEnabled(self.panel is None or self.panel.kind != kind)
        if self.panel is not None:
            m.addAction("Rename", self.begin_rename)
            extra = self.panel.menu_actions()
            if extra:
                m.addSeparator()
                for label, fn in extra:
                    m.addAction(label, fn)
        m.addSeparator()
        m.addAction("Close", lambda: ws.close_frame(self))

    # ----------------------------------------------------------- rename
    def begin_rename(self) -> None:
        if self.panel is None or self.name_edit is not None:
            return
        edit = self.name_edit = QLineEdit(self.panel.name)
        edit.setMaximumWidth(180)
        lay = self.header.layout()
        lay.insertWidget(lay.indexOf(self.name_label), edit)
        self.name_label.hide()
        edit.selectAll()
        edit.setFocus()
        done = [False]

        def finish(commit: bool):
            if done[0]:
                return
            new = edit.text().strip()
            if commit and new and new != self.panel.name and not self.workspace.rename(self, new):
                if edit.hasFocus():                    # Enter on a taken name: keep editing
                    edit.setProperty("invalid", True)
                    edit.setToolTip(f"A panel named {new!r} already exists")
                    edit.style().unpolish(edit)
                    edit.style().polish(edit)
                    return
            done[0] = True
            self.name_edit = None
            edit.deleteLater()
            self.name_label.show()
            self._update_title()

        edit.returnPressed.connect(lambda: finish(True))
        edit.editingFinished.connect(lambda: finish(True) if not edit.hasFocus() else None)
        edit.textEdited.connect(lambda _t: (edit.setProperty("invalid", False),
                                            edit.style().unpolish(edit),
                                            edit.style().polish(edit)))
        esc = _EscapeFilter(lambda: finish(False))
        edit.installEventFilter(esc)
        edit._esc = esc                                  # keep a reference

    # -------------------------------------------------------- dragging
    def eventFilter(self, obj, e):
        t = e.type()
        if t == e.Type.MouseButtonDblClick and obj is self.name_label:
            self.begin_rename()
            return True
        if t == e.Type.MouseButtonPress and e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        elif t == e.Type.MouseMove and self._press is not None and e.buttons() & Qt.LeftButton:
            if (e.position().toPoint() - self._press).manhattanLength() >= 8:
                self._press = None
                self._start_drag()
                return True
        elif t == e.Type.MouseButtonRelease:
            self._press = None
        return super().eventFilter(obj, e)

    def _start_drag(self) -> None:
        ws = self.workspace
        if ws.frame_count() < 2:
            return                                       # nothing to rearrange
        ws.drag_source = self
        self.setProperty("dragSource", True)
        self.style().unpolish(self)
        self.style().polish(self)
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME, b"panel")
        drag.setMimeData(mime)
        shot = self.grab().scaled(QSize(260, 180), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        drag.setPixmap(shot)
        drag.setHotSpot(QPoint(shot.width() // 2, 10))
        try:
            drag.exec(Qt.MoveAction)
        finally:
            ws.drag_source = None
            self.setProperty("dragSource", False)
            self.style().unpolish(self)
            self.style().polish(self)
            for f in ws.frames():
                f.overlay.hide()

    @staticmethod
    def zone_at(pos: QPoint, rect: QRect) -> str:
        x = pos.x() / max(1, rect.width())
        y = pos.y() / max(1, rect.height())
        dist = {"left": x, "right": 1 - x, "top": y, "bottom": 1 - y}
        side = min(dist, key=dist.get)
        return side if dist[side] < 0.3 else "center"

    def dragEnterEvent(self, e):
        src = self.workspace.drag_source
        if src is not None and src is not self and e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        src = self.workspace.drag_source
        if src is None or src is self:
            e.ignore()
            return
        self.overlay.show_zone(self.zone_at(e.position().toPoint(), self.rect()))
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.overlay.hide()

    def dropEvent(self, e):
        self.overlay.hide()
        src = self.workspace.drag_source
        if src is None or src is self:
            return
        zone = self.zone_at(e.position().toPoint(), self.rect())
        e.acceptProposedAction()
        # Re-arrange after the drag loop has fully finished.
        QTimer.singleShot(0, lambda: self.workspace.move_frame(src, self, zone))


def _safe(fn) -> None:
    try:
        fn()
    except RuntimeError:          # the C++ widget was deleted in the meantime
        pass


class _EscapeFilter(QObject):
    def __init__(self, on_escape):
        super().__init__()
        self._on_escape = on_escape

    def eventFilter(self, obj, e):
        if e.type() == e.Type.KeyPress and e.key() == Qt.Key_Escape:
            self._on_escape()
            return True
        return False


# --------------------------------------------------------------- workspace
class Workspace(QWidget):
    changed = Signal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        ctx.workspace = self
        self.drag_source: Optional[PanelFrame] = None
        self._panels: Dict[str, Panel] = {}            # name -> panel (all live panels)

        grid = QGridLayout(self)
        grid.setContentsMargins(4, 0, 4, 4)
        grid.setSpacing(0)
        self.edges = {side: EdgeHandle(self, side) for side in SIDES}
        grid.addWidget(self.edges["top"], 0, 1)
        grid.addWidget(self.edges["left"], 1, 0)
        grid.addWidget(self.edges["right"], 1, 2)
        grid.addWidget(self.edges["bottom"], 2, 1)
        self.center = QWidget()
        self._center_layout = QVBoxLayout(self.center)
        self._center_layout.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(self.center, 1, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(1, 1)
        self.root: Optional[QWidget] = None
        self.set_root(self.new_frame())

    # ---------------------------------------------------------- traversal
    def set_root(self, widget: QWidget) -> None:
        if self.root is not None and self.root is not widget:
            self._center_layout.removeWidget(self.root)
        self.root = widget
        self._center_layout.addWidget(widget)
        widget.show()

    def frames(self) -> Iterator[PanelFrame]:
        def walk(w):
            if isinstance(w, PanelFrame):
                yield w
            elif isinstance(w, QSplitter):
                for i in range(w.count()):
                    yield from walk(w.widget(i))
        if self.root is not None:
            yield from walk(self.root)

    def frame_count(self) -> int:
        return sum(1 for _ in self.frames())

    def panels(self) -> List[Panel]:
        return list(self._panels.values())

    # ------------------------------------------------------------ panels
    def unique_name(self, wanted: str, kind: str) -> str:
        wanted = (wanted or "").strip()
        if wanted and wanted not in self._panels:
            return wanted
        base = wanted or kind
        i = 1
        while f"{base}{i}" in self._panels:
            i += 1
        return f"{base}{i}"

    def create_panel(self, kind: str, name: str = "", state: Optional[dict] = None) -> Optional[Panel]:
        cls = REGISTRY.get(kind)
        if cls is None:
            return None
        panel = cls(self.ctx, self.unique_name(name, kind))
        self._panels[panel.name] = panel
        if state:
            panel.load_state(state)
        return panel

    def _release_panel(self, panel: Optional[Panel]) -> None:
        if panel is not None:
            panel.shutdown()
            self._panels.pop(panel.name, None)

    def new_frame(self, kind: str = "", name: str = "", state: Optional[dict] = None) -> PanelFrame:
        frame = PanelFrame(self)
        if kind:
            frame.set_panel(self.create_panel(kind, name, state))
        return frame

    def fill(self, frame: PanelFrame, kind: str) -> None:
        frame.set_panel(self.create_panel(kind))
        self.changed.emit()

    def change_kind(self, frame: PanelFrame, kind: str) -> None:
        if frame.panel is not None and frame.panel.has_content() and not self._confirm(
                f"Replace {frame.panel.name!r} with a new {REGISTRY[kind].title}? "
                "Its contents will be lost."):
            return
        old = frame.panel
        frame.set_panel(None)
        self._release_panel(old)
        self.fill(frame, kind)

    def rename(self, frame: PanelFrame, new: str) -> bool:
        panel = frame.panel
        if panel is None or new in self._panels:
            return False
        self._panels.pop(panel.name, None)
        panel.renamed(new)
        self._panels[new] = panel
        self.changed.emit()
        return True

    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "Toybox", text) == QMessageBox.Yes

    # -------------------------------------------------------- tree edits
    def _replace_in_parent(self, old: QWidget, new: QWidget) -> None:
        parent = old.parentWidget()
        if isinstance(parent, Splitter):
            idx, sizes = parent.indexOf(old), parent.sizes()
            parent.insertWidget(idx, new)
            old.setParent(None)
            parent.setSizes(sizes)
            new.show()
        elif old is self.root:
            self.set_root(new)
            old.setParent(None)

    def split(self, target: PanelFrame, side: str, frame: PanelFrame) -> None:
        """Put `frame` next to `target` on `side`."""
        orient = _orientation(side)
        after = side in ("right", "bottom")
        parent = target.parentWidget()
        if isinstance(parent, Splitter) and parent.orientation() == orient:
            idx, sizes = parent.indexOf(target), parent.sizes()
            half = sizes[idx] // 2
            new_idx = idx + 1 if after else idx
            parent.insertWidget(new_idx, frame)
            sizes[idx] -= half
            sizes.insert(new_idx, half)
            parent.setSizes(sizes)
        else:
            size = target.width() if orient == Qt.Horizontal else target.height()
            sp = Splitter(orient, self)
            self._replace_in_parent(target, sp)
            for w in ([target, frame] if after else [frame, target]):
                sp.addWidget(w)
                w.show()
            sp.setSizes([size // 2, size - size // 2])
        frame.show()
        self.changed.emit()

    def insert_at_handle(self, splitter: Splitter, index: int) -> None:
        """New empty space where the divider before widget `index` is."""
        sizes = splitter.sizes()
        frame = self.new_frame()
        take_a, take_b = sizes[index - 1] // 3, sizes[index] // 3
        sizes[index - 1] -= take_a
        sizes[index] -= take_b
        sizes.insert(index, take_a + take_b)
        splitter.insertWidget(index, frame)
        splitter.setSizes(sizes)
        frame.show()
        self.changed.emit()

    def add_at_edge(self, side: str, frame: Optional[PanelFrame] = None) -> PanelFrame:
        frame = frame or self.new_frame()
        orient = _orientation(side)
        first = side in ("left", "top")
        root = self.root
        total = root.width() if orient == Qt.Horizontal else root.height()
        new_size = max(160, total // 4)
        if isinstance(root, Splitter) and root.orientation() == orient:
            sizes = root.sizes()
            rest = max(1, sum(sizes))
            scale = max(0.1, (rest - new_size) / rest)
            sizes = [max(1, int(s * scale)) for s in sizes]
            idx = 0 if first else root.count()
            root.insertWidget(idx, frame)
            sizes.insert(idx, new_size)
            root.setSizes(sizes)
        else:
            sp = Splitter(orient, self)
            self._replace_in_parent(root, sp)
            for w in ([frame, root] if first else [root, frame]):
                sp.addWidget(w)
                w.show()
            sp.setSizes([new_size, total - new_size] if first else [total - new_size, new_size])
        frame.show()
        self.changed.emit()
        return frame

    def _detach(self, frame: PanelFrame) -> None:
        parent = frame.parentWidget()
        frame.setParent(None)
        self._normalize(parent)

    def _normalize(self, sp: QWidget) -> None:
        if not isinstance(sp, Splitter):
            return
        n = sp.count()
        if n == 0:
            parent = sp.parentWidget()
            if sp is self.root:
                self.set_root(self.new_frame())
                sp.setParent(None)
            else:
                sp.setParent(None)
                self._normalize(parent)
            sp.deleteLater()
            return
        if n == 1:
            child = sp.widget(0)
            self._replace_in_parent(sp, child)
            sp.deleteLater()
            self._flatten(child.parentWidget())
            return
        self._flatten(sp)

    def _flatten(self, sp: QWidget) -> None:
        """Merge child splitters that have the same orientation as `sp` into it."""
        if not isinstance(sp, Splitter):
            return
        i = 0
        while i < sp.count():
            w = sp.widget(i)
            if isinstance(w, Splitter) and w.orientation() == sp.orientation():
                sizes, inner = sp.sizes(), w.sizes()
                total = max(1, sum(inner))
                children = [w.widget(j) for j in range(w.count())]
                scaled = [max(1, sizes[i] * s // total) for s in inner]
                for j, c in enumerate(children):
                    sp.insertWidget(i + j, c)
                    c.show()
                w.setParent(None)
                w.deleteLater()
                sp.setSizes(sizes[:i] + scaled + sizes[i + 1:])
                i += len(children)
            else:
                i += 1

    def move_frame(self, src: PanelFrame, target: PanelFrame, zone: str) -> None:
        if src is target:
            return
        if zone == "center":
            self._swap(src, target)
        else:
            self._detach(src)
            self.split(target, zone, src)
        self.changed.emit()

    def move_to_edge(self, src: PanelFrame, side: str) -> None:
        if self.frame_count() < 2:
            return
        self._detach(src)
        self.add_at_edge(side, src)

    def _swap(self, a: PanelFrame, b: PanelFrame) -> None:
        pa, pb = a.parentWidget(), b.parentWidget()
        if not (isinstance(pa, Splitter) and isinstance(pb, Splitter)):
            return
        sa, sb = pa.sizes(), pb.sizes()
        ta, tb = QWidget(), QWidget()
        pa.replaceWidget(pa.indexOf(a), ta)
        pb.replaceWidget(pb.indexOf(b), tb)
        pa.replaceWidget(pa.indexOf(ta), b)
        pb.replaceWidget(pb.indexOf(tb), a)
        for t in (ta, tb):
            t.setParent(None)
            t.deleteLater()
        pa.setSizes(sa)
        if pb is not pa:
            pb.setSizes(sb)
        a.show()
        b.show()

    def close_frame(self, frame: PanelFrame) -> None:
        panel = frame.panel
        if panel is not None and panel.has_content() and not self._confirm(
                f"Close {panel.name!r}? Its contents will be lost "
                "(unless they are saved in a project)."):
            return
        frame.set_panel(None)
        self._release_panel(panel)
        if frame is self.root:
            return                                   # the last space stays, now empty
        self._detach(frame)
        frame.deleteLater()
        self.changed.emit()

    # ------------------------------------------------------- serialization
    def layout_dict(self, with_state: bool = True) -> dict:
        def node(w):
            if isinstance(w, PanelFrame):
                p = w.panel
                if p is None:
                    return {"type": "panel", "kind": "empty", "name": "", "state": {}}
                return {"type": "panel", "kind": p.kind, "name": p.name,
                        "state": p.state() if with_state else {}}
            return {"type": "split",
                    "orientation": "h" if w.orientation() == Qt.Horizontal else "v",
                    "sizes": w.sizes(),
                    "children": [node(w.widget(i)) for i in range(w.count())]}
        return node(self.root)

    def clear(self) -> None:
        for panel in list(self._panels.values()):
            self._release_panel(panel)
        old = self.root
        self.root = None
        if old is not None:
            self._center_layout.removeWidget(old)
            old.setParent(None)
            old.deleteLater()

    def load_layout(self, node: dict) -> List[str]:
        """Replace the whole workspace. Returns kinds that are not available."""
        missing: List[str] = []
        self.clear()

        def build(n):
            if n["type"] == "panel":
                kind = n.get("kind", "empty")
                if kind != "empty" and kind not in REGISTRY:
                    missing.append(kind)
                    kind = ""
                return self.new_frame("" if kind == "empty" else kind, n.get("name", ""),
                                      n.get("state"))
            sp = Splitter(Qt.Horizontal if n["orientation"] == "h" else Qt.Vertical, self)
            for c in n["children"]:
                sp.addWidget(build(c))
            sizes = list(n.get("sizes") or [])
            if len(sizes) == sp.count():
                sp.setSizes(sizes)
                # Re-apply once the window has its real size (the splitter may be
                # gone by then if the layout was replaced again).
                QTimer.singleShot(0, lambda s=sp, z=sizes: _safe(lambda: s.setSizes(z)))
            return sp

        self.set_root(build(node))
        self.changed.emit()
        return missing
