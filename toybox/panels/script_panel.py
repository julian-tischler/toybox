"""
script_panel.py - A Python editor with its own console and run controls.

Every Script panel has its own executor (worker thread + namespace) and its own
console, so several scripts can run side by side. A script runs only when you
press Run (or Ctrl+Enter); Run Continuous repeats it every N ms, keeping its
variables between runs.
"""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..core.executor import ScriptExecutor
from ..editor.code_editor import CodeEditor
from ..ui import theme
from ..ui.widgets import LineSplitter
from .base import Panel, register

MAX_CONSOLE_LINES = 3000
OUTPUT_POLL_MS = 30

DEFAULT_SCRIPT = '''\
# Lenses["name"].get_text() / .get_float() / .get_color_avg() / .get_raw()
# Only one colour:  Lenses["name"].color_mask("green").get_text()
# Notes["note1"].get_text() / .set_text("...")
# A line "! some text" prints some text.
# Run: Ctrl+Enter.  Run Continuous keeps variables between runs.

'''


@register
class ScriptPanel(Panel):
    kind = "script"
    title = "Script"
    description = "Python editor with its own console; run once or continuously."

    def __init__(self, ctx, name):
        super().__init__(ctx, name)
        self.executor = ScriptExecutor()
        self._continuous = False
        self._run_state = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        split = self.split = LineSplitter(Qt.Vertical)
        lay.addWidget(split)

        # ---- editor + run bar
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        self.editor = CodeEditor()
        self.editor.setPlainText(DEFAULT_SCRIPT)
        self.editor.moveCursor(QTextCursor.End)
        self.editor.run_requested.connect(self.run_once)
        tl.addWidget(self.editor, 1)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 4)
        every = QLabel("Every")
        every.setProperty("muted", True)
        bar.addWidget(every)
        self.interval = QSpinBox()
        self.interval.setRange(50, 3_600_000)
        self.interval.setSingleStep(100)
        self.interval.setSuffix(" ms")
        self.interval.setValue(int(ctx.prefs.get("interval_ms", 500)))
        self.interval.setToolTip("Run Continuous interval")
        self.interval.valueChanged.connect(lambda v: self._tick_timer.setInterval(v))
        bar.addWidget(self.interval)
        bar.addStretch(1)
        self.btn_cont = QPushButton()
        self.btn_cont.setMinimumWidth(140)
        self.btn_cont.clicked.connect(self.toggle_run)
        bar.addWidget(self.btn_cont)
        self.btn_once = QPushButton("▶  Run Once")
        self.btn_once.setProperty("accent", True)
        self.btn_once.setToolTip("Run the script once (Ctrl+Enter)")
        self.btn_once.clicked.connect(self.run_once)
        bar.addWidget(self.btn_once)
        tl.addLayout(bar)
        split.addWidget(top)

        # ---- console
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)
        head = QHBoxLayout()
        label = QLabel("CONSOLE")
        label.setProperty("header", True)
        head.addWidget(label)
        head.addStretch(1)
        clear = QPushButton("Clear")
        clear.setStyleSheet("padding: 2px 10px;")
        clear.clicked.connect(self.clear_console)
        head.addWidget(clear)
        bl.addLayout(head)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(MAX_CONSOLE_LINES)
        self.console.setFont(self.editor.font())
        self.console.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        bl.addWidget(self.console, 1)
        split.addWidget(bottom)
        split.setSizes([400, 160])
        split.setStretchFactor(0, 1)

        self._formats = {}
        for tag, color in (("stdout", theme.FG), ("stderr", theme.ERROR_FG), ("info", theme.INFO_FG)):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            self._formats[tag] = f

        self._pump_timer = QTimer(self)
        self._pump_timer.timeout.connect(self._pump_output)
        self._pump_timer.start(OUTPUT_POLL_MS)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(self.interval.value())
        self._tick_timer.timeout.connect(self._tick)
        self._sync_run_buttons()

    # ------------------------------------------------------------- console
    def _append(self, text: str, tag: str) -> None:
        c = self.console.textCursor()
        c.movePosition(QTextCursor.End)
        c.insertText(text, self._formats.get(tag, self._formats["stdout"]))
        self.console.setTextCursor(c)
        self.console.ensureCursorVisible()

    def clear_console(self) -> None:
        self.console.clear()

    def _pump_output(self) -> None:
        items = self.executor.drain()
        if items:
            tag, buf = items[0][0], []
            for t, text in items:
                if t != tag:
                    self._append("".join(buf), tag)
                    tag, buf = t, []
                buf.append(text)
            self._append("".join(buf), tag)
        self._sync_run_buttons()

    # ----------------------------------------------------------- running
    def source(self) -> str:
        return self.editor.toPlainText()

    def run_once(self) -> None:
        if self._continuous:
            return
        self.executor.reset_namespace()
        if not self.executor.run(self.source(), self.ctx.script_namespace()):
            self._append("[a script is still running - press Stop to abort it]\n", "info")
        self._sync_run_buttons()

    def toggle_run(self) -> None:
        """Run Continuous / Stop toggle. Stop also aborts a long Run Once."""
        if self._continuous or self.executor.is_running:
            self.stop()
        else:
            self.start_continuous()

    def start_continuous(self) -> None:
        if self._continuous:
            return
        self._continuous = True
        self.executor.reset_namespace()       # state persists across ticks from here on
        self._tick()
        self._tick_timer.start(self.interval.value())
        self._sync_run_buttons()

    def _tick(self) -> None:
        if self._continuous:
            # If the previous run is still going, this tick is simply skipped.
            self.executor.run(self.source(), self.ctx.script_namespace())

    def stop(self) -> None:
        self._continuous = False
        self._tick_timer.stop()
        self.executor.stop()
        self._sync_run_buttons()

    def _sync_run_buttons(self) -> None:
        running = self._continuous or self.executor.is_running
        if running == self._run_state:
            return
        self._run_state = running
        self.btn_cont.setText("■  Stop" if running else "⟳  Run Continuous")
        self.btn_once.setEnabled(not running)

    # ---------------------------------------------------------- panel API
    def state(self) -> dict:
        return {"source": self.source(), "interval_ms": self.interval.value(),
                "split": self.split.sizes()}

    def load_state(self, state: dict) -> None:
        if isinstance(state.get("source"), str):
            self.editor.setPlainText(state["source"])
        if isinstance(state.get("interval_ms"), int):
            self.interval.setValue(max(50, state["interval_ms"]))
        sizes = state.get("split")
        if isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(s, int) for s in sizes):
            self.split.setSizes(sizes)

    def has_content(self) -> bool:
        text = self.source().strip()
        return bool(text) and text != DEFAULT_SCRIPT.strip()

    def menu_actions(self):
        return [("Import .py…", self.import_py), ("Export .py…", self.export_py),
                ("Clear console", self.clear_console)]

    def import_py(self) -> None:
        if self.has_content() and QMessageBox.question(
                self, "Import", f"Replace the script in {self.name!r}?") != QMessageBox.Yes:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import script", "", "Python (*.py);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.editor.setPlainText(f.read())
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.critical(self, "Import failed", f"Could not read {path}:\n{exc}")
            return
        self.executor.reset_namespace()
        self._append(f"[imported {os.path.basename(path)}]\n", "info")

    def export_py(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export script", f"{self.name}.py",
                                              "Python (*.py)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(self.source())
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", f"Could not write {path}:\n{exc}")
            return
        self._append(f"[exported {os.path.basename(path)}]\n", "info")

    def shutdown(self) -> None:
        self.stop()
        self._pump_timer.stop()
