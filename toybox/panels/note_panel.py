"""
note_panel.py - Notes: write in Markdown (or plain text), preview it rendered.

* Edit mode: a plain-text editor holding the Markdown source.
* Preview mode: Qt's built-in Markdown renderer (CommonMark + GitHub
  extensions: headings, lists, task lists, tables, code, links, ...).
  Double-click the preview to go back to editing.
* Open / Save / Save as .md or .txt from the panel's ⋯ menu; the note remembers
  its file and shows it under the text (• = changed since saved).
* Scripts: Notes["note1"].get_text() and Notes["note1"].set_text("...").
"""

import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QStackedWidget, QTextBrowser, QToolButton, QVBoxLayout)

from ..core.bridge import gui_call
from ..ui import theme
from .base import Panel, register

FILE_FILTER = "Markdown (*.md);;Text (*.txt);;All files (*)"


class NoteHandle:
    """What a script gets as Notes["name"]. Safe to use from the script thread."""

    def __init__(self, panel: "NotePanel"):
        self._panel = panel
        self.name = panel.name

    def _call(self, fn, *args):
        try:
            return gui_call(fn, *args)
        except RuntimeError as exc:            # the panel was closed meanwhile
            if "deleted" in str(exc):
                raise RuntimeError(f"The note {self.name!r} was closed.") from None
            raise

    def get_text(self) -> str:
        """The note's text (the Markdown source)."""
        return self._call(self._panel.text)

    def set_text(self, new_text) -> None:
        """Replace the note's text (can be undone with Ctrl+Z in the note)."""
        self._call(self._panel.set_text, str(new_text))

    def __repr__(self) -> str:
        return f"<Note {self.name!r}>"


@register
class NotePanel(Panel):
    kind = "note"
    title = "Note"
    description = "Notes in Markdown or plain text, with preview, files and script access."

    def __init__(self, ctx, name):
        super().__init__(ctx, name)
        self.path: Optional[str] = None

        self.preview_btn = QToolButton()
        self.preview_btn.setText("Preview")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setToolTip("Show the note rendered as Markdown")
        self.preview_btn.toggled.connect(self.set_preview)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.stack = QStackedWidget()
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Write a note… (Markdown works: # heading, - list, "
                                       "**bold**, `code`, [link](https://…))")
        font = QFont("Segoe UI", 10)
        self.editor.setFont(font)
        self.editor.setTabStopDistance(self.editor.fontMetrics().horizontalAdvance(" ") * 4)
        self.editor.modificationChanged.connect(lambda _m: self._update_file_label())
        self.viewer = QTextBrowser()
        self.viewer.setOpenExternalLinks(True)
        self.viewer.setFont(font)
        self.viewer.setStyleSheet(f"QTextBrowser {{ background: {theme.EDITOR_BG}; "
                                  f"border: 1px solid {theme.BORDER}; padding: 4px; }}")
        self.viewer.viewport().installEventFilter(self)
        self.stack.addWidget(self.editor)
        self.stack.addWidget(self.viewer)
        lay.addWidget(self.stack, 1)

        foot = QHBoxLayout()
        self.file_label = QLabel()
        self.file_label.setProperty("muted", True)
        foot.addWidget(self.file_label, 1)
        lay.addLayout(foot)
        self._update_file_label()

    # ------------------------------------------------------------ content
    def text(self) -> str:
        return self.editor.toPlainText()

    def set_text(self, text: str) -> None:
        """Replace all text as one undoable edit (keeps Ctrl+Z history)."""
        c = self.editor.textCursor()
        c.beginEditBlock()
        c.select(QTextCursor.Document)
        c.insertText(text)
        c.endEditBlock()
        if self.preview_btn.isChecked():
            self._render()

    def _render(self) -> None:
        self.viewer.setMarkdown(self.text())

    def set_preview(self, on: bool) -> None:
        if self.preview_btn.isChecked() != on:
            self.preview_btn.setChecked(on)           # re-enters via toggled
            return
        if on:
            self._render()
            self.stack.setCurrentWidget(self.viewer)
            self.preview_btn.setText("Edit")
            self.preview_btn.setToolTip("Edit the note's text")
        else:
            self.stack.setCurrentWidget(self.editor)
            self.preview_btn.setText("Preview")
            self.preview_btn.setToolTip("Show the note rendered as Markdown")
            self.editor.setFocus()

    def eventFilter(self, obj, e):
        if obj is self.viewer.viewport() and e.type() == e.Type.MouseButtonDblClick:
            self.set_preview(False)
            return True
        return super().eventFilter(obj, e)

    # -------------------------------------------------------------- files
    def _update_file_label(self) -> None:
        if self.path:
            mark = " •" if self.editor.document().isModified() else ""
            self.file_label.setText(os.path.basename(self.path) + mark)
            self.file_label.setToolTip(self.path)
        else:
            self.file_label.setText("not saved to a file")
            self.file_label.setToolTip("")

    def open_file(self, path: Optional[str] = None) -> None:
        if path is None:
            if self.has_content() and QMessageBox.question(
                    self, "Open", f"Replace the text of {self.name!r}?") != QMessageBox.Yes:
                return
            path, _ = QFileDialog.getOpenFileName(self, "Open note", "", FILE_FILTER)
            if not path:
                return
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.critical(self, "Open failed", f"Could not read {path}:\n{exc}")
            return
        self.editor.setPlainText(text)
        self.path = path
        self.editor.document().setModified(False)
        if self.preview_btn.isChecked():
            self._render()
        self._update_file_label()

    def save_file(self, as_new: bool = False) -> bool:
        path = self.path
        if as_new or not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save note", path or f"{self.name}.md",
                                                  FILE_FILTER)
            if not path:
                return False
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(self.text())
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", f"Could not write {path}:\n{exc}")
            return False
        self.path = path
        self.editor.document().setModified(False)
        self._update_file_label()
        return True

    # ---------------------------------------------------------- panel API
    def header_widgets(self):
        return [self.preview_btn]

    def menu_actions(self):
        return [("Open file…", self.open_file), ("Save", self.save_file),
                ("Save as…", lambda: self.save_file(as_new=True))]

    def state(self) -> dict:
        return {"text": self.text(), "preview": self.preview_btn.isChecked(),
                "path": self.path or "", "modified": self.editor.document().isModified()}

    def load_state(self, state: dict) -> None:
        if isinstance(state.get("text"), str):
            self.editor.setPlainText(state["text"])
        self.path = state.get("path") or None
        self.editor.document().setModified(bool(state.get("modified")) if self.path else False)
        self._update_file_label()
        if state.get("preview"):
            self.set_preview(True)

    def has_content(self) -> bool:
        return bool(self.text().strip())

    @classmethod
    def script_collection(cls):
        return "Notes"

    def script_handle(self):
        return NoteHandle(self)
