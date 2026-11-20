"""
main_window.py - The Toybox window: menu bar + modular workspace.

Menus
  File       New / Open / Save / Save As project, Preferences, Exit
  Workspace  add a panel at a window edge, save / load / reset the layout
  Lenses     add a lens, show / hide all lenses

The whole workspace (layout, panel contents, lenses, preferences) is saved to
a session file on exit and restored on the next start, so nothing is lost
between runs even without saving a project.
"""

import os
from typing import Optional

from PySide6.QtCore import QByteArray, QSettings, QStandardPaths, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox

from ..core.project_io import (ProjectError, load_layout, load_project, save_layout,
                               save_project)
from .context import DEFAULT_PREFS, AppContext
from .preferences import PreferencesDialog
from .workspace import Workspace

APP_NAME = "Toybox"
PROJECT_FILTER = "Toybox project (*.toybox.json *.json);;All files (*)"
LAYOUT_FILTER = "Toybox layout (*.layout.json *.json);;All files (*)"
DEFAULT_LAYOUT = {"type": "panel", "kind": "script", "name": "script1", "state": {}}


def _session_path() -> str:
    folder = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "session.toybox.json")


class MainWindow(QMainWindow):
    def __init__(self, restore_session: bool = True):
        super().__init__()
        self.ctx = AppContext()
        self.workspace = Workspace(self.ctx)
        self.setCentralWidget(self.workspace)
        self.current_path: Optional[str] = None
        self.resize(1200, 780)
        self.setMinimumSize(700, 450)
        self._build_menus()

        settings = QSettings()
        geometry = settings.value("window/geometry")
        if isinstance(geometry, QByteArray):
            self.restoreGeometry(geometry)
        self.current_path = settings.value("session/project") or None
        if not (restore_session and self._restore_session()):
            self.current_path = None
            self.workspace.load_layout(DEFAULT_LAYOUT)
        self._update_title()

    # ---------------------------------------------------------------- menus
    def _action(self, menu, text, slot, shortcut=None, tip=None) -> QAction:
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        if tip:
            act.setStatusTip(tip)
        menu.addAction(act)
        return act

    def _build_menus(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self._action(f, "&New project", self.new_project, "Ctrl+N")
        self._action(f, "&Open project…", self.open_project, "Ctrl+O")
        self._action(f, "&Save project", self.save_project, "Ctrl+S")
        self._action(f, "Save project &as…", lambda: self.save_project(as_new=True), "Ctrl+Shift+S")
        f.addSeparator()
        self._action(f, "&Preferences…", self.edit_preferences, "Ctrl+,")
        f.addSeparator()
        self._action(f, "E&xit", self.close, "Ctrl+Q")

        w = mb.addMenu("&Workspace")
        add = w.addMenu("&Add panel")
        for label, side in (("On the &left", "left"), ("On the &right", "right"),
                            ("At the &top", "top"), ("At the &bottom", "bottom")):
            self._action(add, label, lambda _=False, s=side: self.workspace.add_at_edge(s))
        w.addSeparator()
        self._action(w, "&Save layout…", self.save_layout)
        self._action(w, "&Load layout…", self.load_layout)
        self._action(w, "&Reset layout", self.reset_layout)

        lenses = mb.addMenu("&Lenses")
        self._action(lenses, "&Add lens", lambda: self.ctx.lenses.add(), "Ctrl+L")
        self.toggle_lenses = self._action(lenses, "&Hide all lenses", self._toggle_lenses, "Ctrl+H")
        self.ctx.lenses.hidden_changed.connect(
            lambda hidden: self.toggle_lenses.setText("&Show all lenses" if hidden else "&Hide all lenses"))

    def _toggle_lenses(self) -> None:
        self.ctx.lenses.set_manually_hidden(not self.ctx.lenses.manually_hidden)

    def _update_title(self) -> None:
        name = os.path.basename(self.current_path) if self.current_path else "untitled"
        self.setWindowTitle(f"{name} - {APP_NAME}")

    def _workspace_has_content(self) -> bool:
        return bool(self.ctx.lenses.windows) or any(p.has_content() for p in self.workspace.panels())

    def _confirm_replace(self, what: str) -> bool:
        if not self._workspace_has_content():
            return True
        return QMessageBox.question(
            self, APP_NAME, f"{what} replaces the current workspace (unsaved panel contents "
                            "and lenses are lost). Continue?") == QMessageBox.Yes

    # ---------------------------------------------------------- projects
    def _settings(self) -> dict:
        return dict(self.ctx.prefs)

    def _apply_settings(self, settings: dict) -> None:
        for key, default in DEFAULT_PREFS.items():
            value = settings.get(key)
            if isinstance(value, type(default)) and not (isinstance(value, bool) and not isinstance(default, bool)):
                self.ctx.prefs[key] = value
        self.ctx.apply_prefs()

    def _apply_project(self, project: dict) -> None:
        self._apply_settings(project["settings"])
        moved = self.ctx.lenses.load(project["lenses"])
        missing = self.workspace.load_layout(project["layout"])
        if missing:
            QMessageBox.warning(self, APP_NAME, "These tools are not available and were left "
                                "empty: " + ", ".join(sorted(set(missing))))
        if moved:
            self.statusBar().showMessage("Moved onto the visible screen: " + ", ".join(moved), 6000)

    def new_project(self) -> None:
        if not self._confirm_replace("A new project"):
            return
        self.ctx.lenses.clear()
        self.workspace.load_layout(DEFAULT_LAYOUT)
        self.current_path = None
        self._update_title()

    def open_project(self) -> None:
        if not self._confirm_replace("Opening a project"):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", PROJECT_FILTER)
        if not path:
            return
        try:
            project = load_project(path)
        except ProjectError as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self._apply_project(project)
        self.current_path = path
        self._update_title()
        self.statusBar().showMessage(f"Opened {path}", 4000)

    def save_project(self, as_new: bool = False) -> None:
        path = self.current_path
        if as_new or not path:
            start = path or "project.toybox.json"
            path, _ = QFileDialog.getSaveFileName(self, "Save project", start, PROJECT_FILTER)
            if not path:
                return
        try:
            save_project(path, self.workspace.layout_dict(), self.ctx.lenses.specs(), self._settings())
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", f"Could not write {path}:\n{exc}")
            return
        self.current_path = path
        self._update_title()
        self.statusBar().showMessage(f"Saved {path}", 4000)

    # ----------------------------------------------------------- layouts
    def save_layout(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save layout", "workspace.layout.json",
                                              LAYOUT_FILTER)
        if not path:
            return
        try:
            save_layout(path, self.workspace.layout_dict(with_state=False))
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", f"Could not write {path}:\n{exc}")
            return
        self.statusBar().showMessage(f"Layout saved to {path}", 4000)

    def load_layout(self) -> None:
        if any(p.has_content() for p in self.workspace.panels()) and QMessageBox.question(
                self, APP_NAME, "Loading a layout replaces all panels (their contents are lost; "
                                "lenses stay). Continue?") != QMessageBox.Yes:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Load layout", "", LAYOUT_FILTER)
        if not path:
            return
        try:
            layout = load_layout(path)
        except ProjectError as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return
        missing = self.workspace.load_layout(layout)
        if missing:
            QMessageBox.warning(self, APP_NAME, "These tools are not available and were left "
                                "empty: " + ", ".join(sorted(set(missing))))

    def reset_layout(self) -> None:
        if any(p.has_content() for p in self.workspace.panels()) and QMessageBox.question(
                self, APP_NAME, "Reset to a single Script panel? Panel contents are lost "
                                "(lenses stay).") != QMessageBox.Yes:
            return
        self.workspace.load_layout(DEFAULT_LAYOUT)

    # ------------------------------------------------------- preferences
    def edit_preferences(self) -> None:
        dlg = PreferencesDialog(self, self.ctx.prefs)
        if dlg.exec():
            self.ctx.prefs.update(dlg.values())
            self.ctx.apply_prefs()

    # ----------------------------------------------------------- session
    def _restore_session(self) -> bool:
        path = _session_path()
        if not os.path.exists(path):
            return False
        try:
            self._apply_project(load_project(path))
        except (ProjectError, KeyError, TypeError, ValueError):
            return False
        return True

    def save_session(self) -> None:
        try:
            save_project(_session_path(), self.workspace.layout_dict(), self.ctx.lenses.specs(),
                         self._settings())
        except OSError:
            pass
        settings = QSettings()
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("session/project", self.current_path or "")

    def closeEvent(self, e):
        self.save_session()
        for p in self.workspace.panels():
            p.shutdown()
        self.ctx.lenses.clear()
        super().closeEvent(e)
