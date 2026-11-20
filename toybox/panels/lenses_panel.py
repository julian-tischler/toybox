"""
lenses_panel.py - Manage the screen lenses (a view of the app-wide LensManager).

Lenses are global: every Lenses panel shows the same list, and scripts read
them as Lenses["name"] whether or not a Lenses panel is open.
"""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QScrollArea, QVBoxLayout, QWidget)

from ..ui import theme
from ..ui.icons import icon
from ..ui.widgets import icon_button
from .base import Panel, register


class _LensRow(QFrame):
    def __init__(self, panel: "LensesPanel", name: str, color: str):
        super().__init__()
        self.panel = panel
        self.name = name
        self.setObjectName("lensRow")
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 3, 4, 3)
        h.setSpacing(8)
        swatch = QLabel()
        swatch.setFixedSize(10, 10)
        swatch.setStyleSheet(f"background: {color}; border: 1px solid {theme.BORDER};")
        h.addWidget(swatch)
        self.label = QLabel(name)
        self.label.setToolTip("Double-click to rename")
        h.addWidget(self.label, 1)
        self.edit: Optional[QLineEdit] = None
        delete = icon_button("xmark-circle", "Delete lens", "muted", "error")
        delete.clicked.connect(lambda: panel.ctx.lenses.remove(self.name))
        h.addWidget(delete)
        self.label.mouseDoubleClickEvent = lambda _e: self.begin_rename()

    def begin_rename(self) -> None:
        if self.edit is not None:
            return
        edit = self.edit = QLineEdit(self.name)
        self.layout().insertWidget(self.layout().indexOf(self.label), edit, 1)
        self.label.hide()
        edit.selectAll()
        edit.setFocus()
        done = [False]

        def finish(commit: bool):
            if done[0]:
                return
            new = edit.text().strip()
            if commit and new and new != self.name:
                if self.panel.ctx.lenses.rename(self.name, new):
                    done[0] = True
                    return                                  # list is rebuilt
                if edit.hasFocus():                         # name taken: keep editing
                    edit.setProperty("invalid", True)
                    edit.setToolTip(f"A lens named {new!r} already exists")
                    edit.style().unpolish(edit)
                    edit.style().polish(edit)
                    return
            done[0] = True
            self.edit = None
            edit.deleteLater()
            self.label.show()

        edit.returnPressed.connect(lambda: finish(True))
        edit.editingFinished.connect(lambda: None if edit.hasFocus() else finish(True))
        edit.textEdited.connect(lambda _t: (edit.setProperty("invalid", False),
                                            edit.style().unpolish(edit), edit.style().polish(edit)))
        orig = edit.keyPressEvent

        def key(e):
            if e.key() == Qt.Key_Escape:
                finish(False)
            else:
                orig(e)
        edit.keyPressEvent = key


@register
class LensesPanel(Panel):
    kind = "lenses"
    title = "Lenses"
    description = "Screen regions that scripts read as Lenses['name']."

    def __init__(self, ctx, name):
        super().__init__(ctx, name)
        mgr = ctx.lenses
        self.eye = icon_button("eye", "Hide all lenses")
        self.eye.clicked.connect(lambda: mgr.set_manually_hidden(not mgr.manually_hidden))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        add_row = QHBoxLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("New lens name")
        self.name_edit.returnPressed.connect(self.add_lens)
        add_row.addWidget(self.name_edit, 1)
        add = icon_button("plus-circle", "Add lens (Enter)")
        add.clicked.connect(self.add_lens)
        add_row.addWidget(add)
        lay.addLayout(add_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(
            f"QScrollArea {{ background: {theme.FIELD}; border: 1px solid {theme.BORDER}; }}"
            f"QWidget#lensRows {{ background: {theme.FIELD}; }}"
            f"QFrame#lensRow {{ background: transparent; border-radius: 3px; }}"
            f"QFrame#lensRow:hover {{ background: {theme.BTN}; }}")
        self.rows = QWidget()
        self.rows.setObjectName("lensRows")
        self.rows_layout = QVBoxLayout(self.rows)
        self.rows_layout.setContentsMargins(2, 2, 2, 2)
        self.rows_layout.setSpacing(0)
        self.scroll.setWidget(self.rows)
        lay.addWidget(self.scroll, 1)

        hint = QLabel("Drag a lens by its coloured header; resize from its edges.\n"
                      "Double-click a name to rename it.")
        hint.setProperty("muted", True)
        hint.setWordWrap(True)
        lay.addWidget(hint)

        mgr.changed.connect(self.refresh)
        mgr.hidden_changed.connect(self._sync_eye)
        self.refresh()
        self._sync_eye(mgr.manually_hidden)

    def header_widgets(self):
        return [self.eye]

    def _sync_eye(self, hidden: bool) -> None:
        self.eye.setIcon(icon("eye-closed" if hidden else "eye", "muted", hover="fg"))
        self.eye.setToolTip("Show all lenses" if hidden else "Hide all lenses")

    def refresh(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        windows = self.ctx.lenses.windows
        if not windows:
            empty = QLabel("No lenses yet - type a name and press +")
            empty.setProperty("muted", True)
            empty.setWordWrap(True)
            empty.setContentsMargins(8, 6, 8, 6)
            self.rows_layout.addWidget(empty)
        for name, win in windows.items():
            self.rows_layout.addWidget(_LensRow(self, name, win.color))
        self.rows_layout.addStretch(1)

    def add_lens(self) -> None:
        try:
            self.ctx.lenses.add(self.name_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Duplicate name", str(exc))
            return
        self.name_edit.clear()

    def shutdown(self) -> None:
        if getattr(self, "_shut", False):
            return
        self._shut = True
        try:
            self.ctx.lenses.changed.disconnect(self.refresh)
            self.ctx.lenses.hidden_changed.disconnect(self._sync_eye)
        except (RuntimeError, TypeError):
            pass
