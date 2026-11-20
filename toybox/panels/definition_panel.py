"""
definition_panel.py - A predefined calculation with input fields and a result.

A script hands the panel a function; the panel shows one input field per
parameter, runs the function when you press Calculate (or Enter, or on every
keystroke in Live mode) and shows the result plus a small history.

    Definitions["calc1"].assign(lambda a, b: a + b)
    Definitions["calc1"].assign(lambda u, r: u / r, u=float, r=float)   # optional types

    def ohm(u: float, r: float = 100):
        "Current through a resistor [A]"
        return u / r
    Definitions["calc1"].assign(ohm)

Field types, most explicit first: annotation, type given to assign(), type of
the default value, else "auto" (a Python literal such as 3, 2.5, [1, 2], True,
'text' - anything that is not a literal is taken as text). A type can be any
callable that converts the field text, e.g. assign(f, name=str.upper).

The function runs on a background thread (it may read lenses or be slow);
print() inside it goes to the console of the script that assigned it. The
script only hands over the function - it is never run by the panel.
"""

import ast
import inspect
import threading
from typing import List, Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QToolButton,
                               QVBoxLayout, QWidget)

from ..core.bridge import gui_call
from ..core.executor import current_output_queue, output_routed_to
from ..ui import theme
from .base import Panel, register

MAX_HISTORY = 30
LIVE_DELAY_MS = 200
_OMIT = object()                       # empty field with a default: leave the argument out
_AUTO_DEFAULT_TYPES = (int, float, str, bool, list, tuple, dict)
_TRUE = {"true", "1", "yes", "y", "on"}
_FALSE = {"false", "0", "no", "n", "off"}


# ------------------------------------------------------------ conversion
def _type_name(t) -> str:
    if t is None:
        return "auto"
    return getattr(t, "__name__", None) or type(t).__name__


def convert(text: str, spec: dict):
    """Field text -> argument value according to the parameter's type."""
    name, t = spec["name"], spec["type"]
    if text == "":
        if spec["has_default"]:
            return _OMIT
        if t is str:
            return ""
        raise ValueError(f"{name}: needs a value")
    if t is None:                                      # auto
        try:
            return ast.literal_eval(text.strip())
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            return text                                # not a literal -> text
    if t is str:
        return text
    if t is bool:
        low = text.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise ValueError(f"{name}: {text!r} is not true/false")
    if t in (list, tuple, dict, set):
        try:
            return t(ast.literal_eval(text.strip()))
        except (ValueError, SyntaxError, TypeError):
            raise ValueError(f"{name}: {text!r} is not a {t.__name__}") from None
    try:
        return t(text.strip() if t in (int, float, complex) else text)
    except Exception as exc:  # noqa: BLE001 - any converter may fail
        detail = "" if t in (int, float, complex) else f" ({exc})"
        raise ValueError(f"{name}: {text!r} is not {_type_name(t)}{detail}") from None


def format_result(value) -> str:
    if isinstance(value, float):
        return f"{value:.12g}"
    if isinstance(value, str):
        return value
    return repr(value) if isinstance(value, (list, tuple, dict, set)) else str(value)


def _default_text(spec: dict) -> str:
    if not spec["has_default"] or spec["default"] is None:
        return ""
    d = spec["default"]
    return d if isinstance(d, str) else repr(d)


# ----------------------------------------------------------- script side
class DefinitionHandle:
    """What a script gets as Definitions["name"]."""

    def __init__(self, panel: "DefinitionPanel"):
        self._panel = panel
        self.name = panel.name

    def assign(self, fn, **types) -> None:
        """Show `fn` in the panel: one input field per parameter.
        Optional types per parameter: assign(f, a=float, b=int, s=str)."""
        if not callable(fn):
            raise TypeError("assign() needs a function, e.g. assign(lambda a, b: a + b)")
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            raise TypeError("assign(): cannot read this function's parameters - "
                            "wrap it, e.g. assign(lambda x: math.sqrt(x))") from None
        params = []
        for p in sig.parameters.values():
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                raise ValueError(f"assign(): *{p.name} / **{p.name} parameters are not supported; "
                                 "use named parameters")
            t = types.pop(p.name, None)
            if t is None and p.annotation is not p.empty:
                t = p.annotation if callable(p.annotation) else \
                    {"int": int, "float": float, "str": str, "bool": bool}.get(str(p.annotation))
            has_default = p.default is not p.empty
            if t is None and has_default and type(p.default) in _AUTO_DEFAULT_TYPES:
                t = type(p.default)
            if t is not None and not callable(t):
                raise TypeError(f"assign(): the type for {p.name!r} must be callable (e.g. float)")
            params.append({"name": p.name, "type": t, "hint": _type_name(t),
                           "has_default": has_default, "default": p.default if has_default else None,
                           "positional_only": p.kind == p.POSITIONAL_ONLY})
        if types:
            raise ValueError(f"assign(): the function has no parameter named "
                             f"{', '.join(map(repr, types))}")
        doc = (inspect.getdoc(fn) or "").strip().splitlines()
        title = getattr(fn, "__name__", "")
        description = doc[0] if doc else ""
        if title and title != "<lambda>":
            description = f"{title}({', '.join(p['name'] for p in params)})" + (
                f" — {description}" if description else "")
        if not self._panel.alive:
            raise RuntimeError(f"The definition {self.name!r} was closed.")
        gui_call(self._panel.set_function, fn, params, description, current_output_queue())

    def __repr__(self) -> str:
        return f"<Definition {self.name!r}>"


# ------------------------------------------------------------------ panel
@register
class DefinitionPanel(Panel):
    kind = "definition"
    title = "Definition"
    description = "Input fields for a function a script assigns; calculate on demand or live."

    def __init__(self, ctx, name):
        super().__init__(ctx, name)
        self.alive = True
        self.fn = None
        self.params: List[dict] = []
        self.route = None
        self.fields: dict = {}
        self.history: List[dict] = []
        self._busy = False
        self._queued: Optional[bool] = None            # pending request (add_history flag)

        self.live_btn = QToolButton()
        self.live_btn.setText("Live")
        self.live_btn.setCheckable(True)
        self.live_btn.setToolTip("Recalculate while you type")
        self.live_btn.toggled.connect(lambda on: on and self.request(False))
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(LIVE_DELAY_MS)
        self._live_timer.timeout.connect(lambda: self.request(False))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setProperty("muted", True)
        lay.addWidget(self.desc)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setHorizontalSpacing(10)
        self.form.setVerticalSpacing(6)
        scroll.setWidget(self.form_host)
        self.scroll = scroll
        lay.addWidget(scroll)

        row = QHBoxLayout()
        self.calc_btn = QPushButton("Calculate")
        self.calc_btn.setProperty("accent", True)
        self.calc_btn.setToolTip("Run the function (Enter in any field)")
        self.calc_btn.clicked.connect(lambda: self.request(True))
        row.addWidget(self.calc_btn)
        self.output = QLineEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("result")
        f = QFont("Consolas", 11)
        self.output.setFont(f)
        row.addWidget(self.output, 1)
        copy = QToolButton()
        copy.setText("Copy")
        copy.setToolTip("Copy the result to the clipboard")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.output.text()))
        row.addWidget(copy)
        lay.addLayout(row)

        head = QLabel("HISTORY")
        head.setProperty("header", True)
        lay.addWidget(head)
        self.history_list = QListWidget()
        self.history_list.setToolTip("Double-click an entry to put its inputs back")
        self.history_list.setStyleSheet(
            f"QListWidget {{ background: {theme.BG}; border: 1px solid {theme.BORDER}; "
            f"color: {theme.MUTED}; font-family: Consolas; font-size: 9pt; }}"
            f"QListWidget::item {{ padding: 2px 4px; }}"
            f"QListWidget::item:selected {{ background: {theme.BTN}; color: {theme.FG}; }}")
        self.history_list.setMinimumHeight(60)
        self.history_list.itemDoubleClicked.connect(self._restore_from_history)
        lay.addWidget(self.history_list, 1)
        self._show_function()

    # ------------------------------------------------------------- fields
    def set_function(self, fn, params: List[dict], description: str, route) -> None:
        """Called (on the GUI thread) by assign(): build / update the fields."""
        old = {name: f.text() for name, f in self.fields.items()}   # kept for same names
        self.fn, self.route = fn, route
        self.params = params
        self.description_text = description
        self._build_fields(old)
        self._show_function()

    def _build_fields(self, values: dict) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = {}
        for spec in self.params:
            edit = QLineEdit()
            edit.setText(values[spec["name"]] if spec["name"] in values else _default_text(spec))
            if spec.get("has_default"):
                edit.setPlaceholderText(f"default: {_default_text(spec) or 'None'}")
            edit.returnPressed.connect(lambda: self.request(True))
            edit.textEdited.connect(self._on_edit)
            hint = QLabel(spec["hint"])
            hint.setProperty("muted", True)
            hint.setToolTip("Type the field is converted to ('auto' = Python literal, else text)")
            cell = QHBoxLayout()
            cell.setSpacing(6)
            cell.addWidget(edit, 1)
            cell.addWidget(hint)
            self.form.addRow(spec["name"], cell)
            self.fields[spec["name"]] = edit
        # Fields take the height they need (scrolling only beyond ~8 rows).
        self.form_host.adjustSize()
        self.scroll.setVisible(bool(self.params))
        if self.params:
            self.scroll.setFixedHeight(min(self.form_host.sizeHint().height(), 8 * 34))

    def _show_function(self) -> None:
        assigned = self.fn is not None
        if assigned:
            self.desc.setText(getattr(self, "description_text", "") or "")
            self.desc.setVisible(bool(self.desc.text()))
        else:
            self.desc.setText(f'Not assigned — run a script with '
                              f'Definitions["{self.name}"].assign(lambda a, b: a + b)')
            self.desc.setVisible(True)
        self.calc_btn.setEnabled(assigned)

    def _on_edit(self, _text) -> None:
        if self.live_btn.isChecked():
            self._live_timer.start()

    def _set_output(self, text: str, error: bool = False) -> None:
        self.output.setText(text)
        self.output.setStyleSheet(f"color: {theme.ERROR_FG};" if error else "")

    # ------------------------------------------------------------ running
    def request(self, add_history: bool) -> None:
        """Calculate now, or right after the running calculation finishes."""
        if self.fn is None:
            return
        if self._busy:
            self._queued = bool(add_history or self._queued)
            return
        try:
            args, kwargs = self._collect()
        except ValueError as exc:
            self._set_output(str(exc), error=True)
            return
        self._busy = True
        inputs = {name: f.text() for name, f in self.fields.items()}
        fn, route = self.fn, self.route
        QTimer.singleShot(300, self._show_running)

        def work():
            try:
                with output_routed_to(route):
                    result, ok = fn(*args, **kwargs), True
            except Exception as exc:  # noqa: BLE001 - shown in the output field
                result, ok = f"{type(exc).__name__}: {exc}", False
            try:
                gui_call(self._done, result, ok, inputs, add_history, wait=False)
            except RuntimeError:
                pass
        threading.Thread(target=work, name="Definition", daemon=True).start()

    def _collect(self):
        args, kwargs = [], {}
        for spec in self.params:
            value = convert(self.fields[spec["name"]].text(), spec)
            if value is _OMIT:
                continue
            if spec.get("positional_only"):
                args.append(value)
            else:
                kwargs[spec["name"]] = value
        return args, kwargs

    def _show_running(self) -> None:
        if self.alive and self._busy:
            self._set_output("Running…")

    def _done(self, result, ok: bool, inputs: dict, add_history: bool) -> None:
        if not self.alive:
            return
        self._busy = False
        text = format_result(result) if ok else str(result)
        self._set_output(text, error=not ok)
        if ok and add_history:
            self._add_history({"inputs": inputs, "result": text})
        queued, self._queued = self._queued, None
        if queued is not None:
            self.request(queued)

    # ------------------------------------------------------------ history
    def _add_history(self, entry: dict) -> None:
        self.history.insert(0, entry)
        del self.history[MAX_HISTORY:]
        self._render_history()

    def _render_history(self) -> None:
        self.history_list.clear()
        for entry in self.history:
            args = ", ".join(f"{k}={v}" for k, v in entry["inputs"].items())
            item = QListWidgetItem(f"{args}  →  {entry['result']}")
            item.setToolTip(entry["result"])
            self.history_list.addItem(item)

    def _restore_from_history(self, item: QListWidgetItem) -> None:
        entry = self.history[self.history_list.row(item)]
        for name, text in entry["inputs"].items():
            if name in self.fields:
                self.fields[name].setText(text)
        self._set_output(entry["result"])

    def clear_history(self) -> None:
        self.history = []
        self._render_history()

    # ---------------------------------------------------------- panel API
    def header_widgets(self):
        return [self.live_btn]

    def menu_actions(self):
        return [("Clear history", self.clear_history)]

    def state(self) -> dict:
        return {"inputs": {n: f.text() for n, f in self.fields.items()},
                "params": [{"name": p["name"], "hint": p["hint"]} for p in self.params],
                "description": getattr(self, "description_text", ""),
                "history": self.history, "live": self.live_btn.isChecked()}

    def load_state(self, state: dict) -> None:
        """Restore inputs and history; the function itself must be re-assigned."""
        params = state.get("params") or []
        self.params = [{"name": p["name"], "type": None, "hint": p.get("hint", "auto"),
                        "has_default": False, "default": None, "positional_only": False}
                       for p in params if isinstance(p, dict) and isinstance(p.get("name"), str)]
        inputs = state.get("inputs") if isinstance(state.get("inputs"), dict) else {}
        self._build_fields({k: str(v) for k, v in inputs.items()})
        hist = state.get("history")
        if isinstance(hist, list):
            self.history = [h for h in hist if isinstance(h, dict) and "inputs" in h and "result" in h]
            self._render_history()
        self.live_btn.setChecked(bool(state.get("live")))
        self._show_function()

    def has_content(self) -> bool:
        return bool(self.history)

    @classmethod
    def script_collection(cls):
        return "Definitions"

    def script_handle(self):
        return DefinitionHandle(self)

    def renamed(self, name: str) -> None:
        super().renamed(name)
        self._show_function()

    def shutdown(self) -> None:
        self.alive = False
        self._live_timer.stop()
