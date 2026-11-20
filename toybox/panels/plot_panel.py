"""
plot_panel.py - Script-steered plots (pyqtgraph).

The script decides *what* is plotted; the panel owns *how you look at it*
(colour palette, mouse zoom/pan, auto-range, grid, legend, crosshair, saving).

    p = Plots["plot1"]
    p.line(x, y, name="voltage")       # also scatter(), bar(), hist()
    p.append("voltage", 12.3)          # live logging: x = seconds since the first point
    p.title("Supply"); p.xlabel("t [s]"); p.ylabel("V")
    p.xlim(0, 10); p.ylim()            # ylim() with no limits = automatic again
    p.remove("voltage"); p.clear()

Series are identified by name: plotting a name again replaces that series in
place (so Run Continuous redraws instead of piling up); calls without a name
add a new series. Plotted data is not saved in projects - use the Save button
(image or CSV). Projects keep the view settings.

Threading: the handle validates and converts data in the script's thread,
then queues the command; the panel applies all queued commands at once on the
GUI thread (one redraw), so even tight loops stay smooth.
"""

import csv
import threading
import time
from typing import Dict, List, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QToolButton, QVBoxLayout

from ..core.bridge import gui_call
from ..ui import theme
from .base import Panel, register

pg.setConfigOptions(antialias=True)

PALETTES = {
    "Toybox": ["#4c8dff", "#00d084", "#ff7a45", "#c792ea", "#ffd400", "#00c2e0", "#ff5c8a", "#a3be8c"],
    "Colorblind": ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#999999"],
    "Pastel": ["#8fb8ff", "#8be0b8", "#ffb38f", "#d7b8f3", "#ffe58f", "#8fe3f0", "#ffa3bd", "#c5d9b5"],
}
LINE_STYLES = {"-": Qt.SolidLine, "--": Qt.DashLine, ":": Qt.DotLine, "-.": Qt.DashDotLine}
# Subtle axis colours, so the data stands out.
AXIS_LINE = "#2c2f35"     # axis lines and tick marks
AXIS_TEXT = "#5f6570"     # tick numbers
AXIS_LABEL = "#737985"    # axis titles (xlabel / ylabel)
ZERO_LINE = "#4a4f59"     # the x = 0 / y = 0 lines
ZERO_MODES = ("auto", "on", "off")   # auto = shown when there is a line or scatter series
SYMBOLS = {"o": "o", "s": "s", "t": "t", "d": "d", "+": "+", "x": "x", "*": "star"}


# ----------------------------------------------------------------- script side
def _color(value) -> Optional[str]:
    """Validate a colour in the script thread: name, '#rrggbb' or (r, g, b)."""
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and len(value) in (3, 4):
        return QColor(*[int(v) for v in value]).name()
    c = QColor(str(value))
    if not c.isValid():
        raise ValueError(f"Unknown colour {value!r}. Use a name like 'red', '#ff8800' or (255, 136, 0).")
    return c.name()


def _floats(values, what: str) -> np.ndarray:
    try:
        arr = np.asarray(values, dtype=float).ravel()
    except (TypeError, ValueError):
        raise TypeError(f"{what} must be numbers") from None
    return arr


def _xy(x, y, kind: str):
    """(x, y) arrays; with only one sequence it is y and x is 0, 1, 2, ..."""
    if y is None:
        y = _floats(x, "y")
        return np.arange(len(y), dtype=float), y
    xa, ya = _floats(x, "x"), _floats(y, "y")
    if len(xa) != len(ya):
        raise ValueError(f"{kind}: x has {len(xa)} values but y has {len(ya)}")
    return xa, ya


class PlotHandle:
    """What a script gets as Plots["name"]. Safe to use from the script thread."""

    def __init__(self, panel: "PlotPanel"):
        self._panel = panel
        self.name = panel.name

    def _send(self, op: str, *args) -> None:
        if not self._panel.alive:
            raise RuntimeError(f"The plot {self.name!r} was closed.")
        self._panel.queue(op, args)

    # -- series -----------------------------------------------------------
    def line(self, x, y=None, name: Optional[str] = None, color=None, width: float = 2,
             style: str = "-") -> None:
        """Line through the points. line(y) uses x = 0, 1, 2, ...
        style: '-' solid, '--' dashed, ':' dotted, '-.' dash-dot."""
        if style not in LINE_STYLES:
            raise ValueError(f"style must be one of {', '.join(LINE_STYLES)}")
        xa, ya = _xy(x, y, "line")
        self._send("line", name, xa, ya, _color(color), float(width), style)

    def scatter(self, x, y=None, name: Optional[str] = None, color=None, size: float = 7,
                symbol: str = "o") -> None:
        """Points only. symbol: 'o' circle, 's' square, 't' triangle, 'd' diamond, '+', 'x', '*'."""
        if symbol not in SYMBOLS:
            raise ValueError(f"symbol must be one of {', '.join(SYMBOLS)}")
        xa, ya = _xy(x, y, "scatter")
        self._send("scatter", name, xa, ya, _color(color), float(size), symbol)

    def bar(self, x, heights=None, name: Optional[str] = None, color=None,
            width: float = 0.8) -> None:
        """Bars. x may be numbers or labels (strings): bar(["a", "b"], [3, 5]).
        bar(heights) puts the bars at 0, 1, 2, ..."""
        labels = None
        if heights is None:
            heights, x = x, None
        h = _floats(heights, "heights")
        if x is None:
            xa = np.arange(len(h), dtype=float)
        elif any(isinstance(v, str) for v in x):
            labels = [str(v) for v in x]
            xa = np.arange(len(labels), dtype=float)
        else:
            xa = _floats(x, "x")
        if len(xa) != len(h):
            raise ValueError(f"bar: {len(xa)} positions but {len(h)} heights")
        self._send("bar", name, xa, h, _color(color), float(width), labels)

    def hist(self, values, bins=20, name: Optional[str] = None, color=None,
             range=None) -> None:
        """Histogram of `values` (bins: a count or the list of bin edges)."""
        v = _floats(values, "values")
        v = v[np.isfinite(v)]
        counts, edges = np.histogram(v, bins=bins, range=range)
        self._send("hist", name, edges.astype(float), counts.astype(float), _color(color))

    def append(self, name: str, y, x=None, color=None, max_points: Optional[int] = None) -> None:
        """Add one point to series `name` (created as a line if new).
        Without x, x = seconds since this plot's first appended point (first is 0).
        max_points keeps only the newest points (a rolling window)."""
        if not isinstance(name, str) or not name:
            raise ValueError("append needs a series name, e.g. p.append('voltage', v)")
        y = float(y)
        t = time.monotonic() if x is None else None
        self._send("append", name, y, None if x is None else float(x), t, _color(color),
                   None if max_points is None else max(1, int(max_points)))

    def remove(self, name: str) -> None:
        """Remove one series."""
        self._send("remove", name)

    def clear(self) -> None:
        """Remove all series (and restart the append clock at 0)."""
        self._send("clear")

    # -- labels and axes ----------------------------------------------------
    def title(self, text: str = "") -> None:
        self._send("title", str(text))

    def xlabel(self, text: str = "") -> None:
        self._send("xlabel", str(text))

    def ylabel(self, text: str = "") -> None:
        self._send("ylabel", str(text))

    def xlim(self, low: Optional[float] = None, high: Optional[float] = None) -> None:
        """Fix the x range; xlim() with no arguments makes it automatic again."""
        self._send("xlim", None if low is None else float(low), None if high is None else float(high))

    def ylim(self, low: Optional[float] = None, high: Optional[float] = None) -> None:
        """Fix the y range; ylim() with no arguments makes it automatic again."""
        self._send("ylim", None if low is None else float(low), None if high is None else float(high))

    def __repr__(self) -> str:
        return f"<Plot {self.name!r}>"


# ------------------------------------------------------------------- panel
class _Series:
    def __init__(self, name: str, kind: str, item, color: Optional[str], auto_color: bool):
        self.name = name
        self.kind = kind              # line | scatter | bar | hist
        self.item = item
        self.color = color
        self.auto_color = auto_color  # follows the palette (no explicit colour)
        self.x = np.empty(0)
        self.y = np.empty(0)
        self.labels: Optional[List[str]] = None
        self.extra: dict = {}


@register
class PlotPanel(Panel):
    kind = "plot"
    title = "Plot"
    description = "Line, scatter, bar and histogram plots drawn by scripts (Plots['plot1'])."

    def __init__(self, ctx, name):
        super().__init__(ctx, name)
        self.alive = True
        self._lock = threading.Lock()
        self._pending: List[tuple] = []
        self._flush_posted = False
        self.series: Dict[str, _Series] = {}
        self._unnamed = 0
        self._t0: Optional[float] = None
        self.palette = "Toybox"
        self._xlabel_set = False

        # ---- header buttons
        self.auto_btn = QToolButton()
        self.auto_btn.setText("Auto")
        self.auto_btn.setToolTip("Fit the view to the data again (after zooming)")
        self.auto_btn.clicked.connect(self.auto_range)
        self.save_btn = QToolButton()
        self.save_btn.setText("Save")
        self.save_btn.setToolTip("Save the plot as an image or its data as CSV")
        self.save_btn.setPopupMode(QToolButton.InstantPopup)
        save_menu = QMenu(self.save_btn)
        save_menu.addAction("Image (PNG)…", self.save_image)
        save_menu.addAction("Data (CSV)…", self.save_csv)
        self.save_btn.setMenu(save_menu)

        # ---- plot widget, themed
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.pw = pg.PlotWidget(background=theme.EDITOR_BG)
        self.pw.setStyleSheet(f"border: 1px solid {theme.BORDER};")
        self.plot = self.pw.getPlotItem()
        self.plot.setMenuEnabled(False, enableViewBoxMenu=True)   # keep zoom options
        self.pw.sceneObj.contextMenu = []                          # Save button instead
        for side in ("left", "bottom"):
            ax = self.plot.getAxis(side)
            ax.setPen(pg.mkPen(AXIS_LINE))
            ax.setTextPen(pg.mkPen(AXIS_TEXT))
        self.legend = self.plot.addLegend(offset=(10, 10), labelTextColor=theme.FG,
                                          brush=pg.mkBrush(QColor(37, 39, 44, 210)),
                                          pen=pg.mkPen(theme.BORDER))
        lay.addWidget(self.pw, 1)

        zero_pen = pg.mkPen(ZERO_LINE, width=1)
        self._zero_x = pg.InfiniteLine(pos=0, angle=90, movable=False, pen=zero_pen)
        self._zero_y = pg.InfiniteLine(pos=0, angle=0, movable=False, pen=zero_pen)
        for line in (self._zero_x, self._zero_y):
            line.setZValue(-10)                             # under the data
            self.plot.addItem(line, ignoreBounds=True)      # never affects auto-range
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(theme.MUTED, style=Qt.DashLine))
        self._hline = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(theme.MUTED, style=Qt.DashLine))
        for line in (self._vline, self._hline):
            line.setZValue(100)
            self.plot.addItem(line, ignoreBounds=True)
        self.readout = QLabel(" ")
        self.readout.setProperty("muted", True)
        foot = QHBoxLayout()
        foot.addWidget(self.readout, 1)
        lay.addLayout(foot)
        self.pw.scene().sigMouseMoved.connect(self._mouse_moved)

        self.grid = True
        self.show_legend = True
        self.crosshair = False
        self.zero_lines = "auto"
        self._apply_view()

    # ------------------------------------------------------- command queue
    def queue(self, op: str, args: tuple) -> None:
        """Called from any thread: store the command, ensure one flush is posted."""
        with self._lock:
            self._pending.append((op, args))
            if self._flush_posted:
                return
            self._flush_posted = True
        gui_call(self._flush, wait=False)

    def _flush(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, []
            self._flush_posted = False
        if not self.alive:
            return
        for op, args in pending:
            try:
                getattr(self, "_op_" + op)(*args)
            except RuntimeError:
                return                          # widgets deleted while closing

    # --------------------------------------------------------- operations
    def _next_color(self) -> str:
        colors = PALETTES[self.palette]
        used = sum(1 for s in self.series.values() if s.auto_color)
        return colors[used % len(colors)]

    def _series_for(self, name: Optional[str], kind: str, color: Optional[str]) -> _Series:
        if name is None:
            self._unnamed += 1
            name = f"{kind}{self._unnamed}"
            while name in self.series:
                self._unnamed += 1
                name = f"{kind}{self._unnamed}"
        old = self.series.get(name)
        if old is not None and old.kind == kind:
            if color is not None:
                old.color, old.auto_color = color, False
            return old
        if old is not None:
            self._remove_item(old)
        auto = color is None
        s = _Series(name, kind, None, color or self._next_color(), auto)
        self.series[name] = s
        return s

    def _remove_item(self, s: _Series) -> None:
        if s.item is not None:
            self.plot.removeItem(s.item)
            try:
                self.legend.removeItem(s.item)
            except Exception:  # noqa: BLE001 - not in the legend
                pass
            s.item = None

    def _place(self, s: _Series, item) -> None:
        if s.item is not None and s.item is not item:
            self._remove_item(s)
        if s.item is None:
            self.plot.addItem(item)
            self.legend.addItem(item, s.name)
        s.item = item

    def _draw(self, s: _Series) -> None:
        """(Re)build the graphics item of a series from its data and style."""
        c = QColor(s.color)
        if s.kind == "line":
            pen = pg.mkPen(c, width=s.extra.get("width", 2), style=LINE_STYLES[s.extra.get("style", "-")])
            if isinstance(s.item, pg.PlotDataItem):
                s.item.setData(s.x, s.y)
                s.item.setPen(pen)
            else:
                self._place(s, pg.PlotDataItem(s.x, s.y, pen=pen))
        elif s.kind == "scatter":
            kw = dict(pen=None, symbol=SYMBOLS[s.extra.get("symbol", "o")],
                      symbolSize=s.extra.get("size", 7), symbolBrush=pg.mkBrush(c),
                      symbolPen=pg.mkPen(c))
            if isinstance(s.item, pg.PlotDataItem):
                s.item.setData(s.x, s.y, **kw)
            else:
                self._place(s, pg.PlotDataItem(s.x, s.y, **kw))
        else:                                               # bar / hist
            fill = QColor(c)
            fill.setAlpha(190)
            if s.kind == "bar":
                w = s.extra.get("width", 0.8)
                opts = dict(x0=s.x - w / 2, x1=s.x + w / 2, height=s.y)
            else:
                edges = s.extra["edges"]
                opts = dict(x0=edges[:-1], x1=edges[1:], height=s.y)
            opts.update(brush=pg.mkBrush(fill), pen=pg.mkPen(c))
            if isinstance(s.item, pg.BarGraphItem):
                s.item.setOpts(**opts)
            else:
                self._place(s, pg.BarGraphItem(**opts))
        self._series_changed()

    def _op_line(self, name, x, y, color, width, style):
        s = self._series_for(name, "line", color)
        s.x, s.y = x, y
        s.extra.update(width=width, style=style)
        self._draw(s)

    def _op_scatter(self, name, x, y, color, size, symbol):
        s = self._series_for(name, "scatter", color)
        s.x, s.y = x, y
        s.extra.update(size=size, symbol=symbol)
        self._draw(s)

    def _op_bar(self, name, x, h, color, width, labels):
        s = self._series_for(name, "bar", color)
        s.x, s.y, s.labels = x, h, labels
        s.extra.update(width=width)
        self._draw(s)

    def _op_hist(self, name, edges, counts, color):
        s = self._series_for(name, "hist", color)
        s.x = (edges[:-1] + edges[1:]) / 2
        s.y = counts
        s.extra["edges"] = edges
        self._draw(s)

    def _op_append(self, name, y, x, t, color, max_points):
        s = self.series.get(name)
        if s is None or s.kind != "line":
            s = self._series_for(name, "line", color)
            s.extra.setdefault("width", 2)
            s.extra.setdefault("style", "-")
        elif color is not None:
            s.color, s.auto_color = color, False
        if x is None:
            if self._t0 is None:
                self._t0 = t
            x = t - self._t0
            if not self._xlabel_set:
                self.plot.setLabel("bottom", "t [s]", color=AXIS_LABEL)
        s.x = np.append(s.x, x)
        s.y = np.append(s.y, y)
        if max_points is not None and len(s.x) > max_points:
            s.x, s.y = s.x[-max_points:], s.y[-max_points:]
        self._draw(s)

    def _op_remove(self, name):
        s = self.series.pop(name, None)
        if s is not None:
            self._remove_item(s)
            self._series_changed()

    def _op_clear(self):
        for s in list(self.series.values()):
            self._remove_item(s)
        self.series.clear()
        self._unnamed = 0
        self._t0 = None
        self._series_changed()

    def _op_title(self, text):
        self.plot.setTitle(text or None, color=theme.FG)

    def _op_xlabel(self, text):
        self._xlabel_set = bool(text)
        self.plot.setLabel("bottom", text or None, color=AXIS_LABEL)

    def _op_ylabel(self, text):
        self.plot.setLabel("left", text or None, color=AXIS_LABEL)

    def _op_xlim(self, low, high):
        self._set_limits("x", low, high)

    def _op_ylim(self, low, high):
        self._set_limits("y", low, high)

    def _set_limits(self, axis: str, low, high) -> None:
        vb = self.plot.getViewBox()
        if low is None and high is None:
            vb.enableAutoRange(axis=axis)
            return
        cur = vb.viewRange()[0 if axis == "x" else 1]
        low = cur[0] if low is None else low
        high = cur[1] if high is None else high
        (vb.setXRange if axis == "x" else vb.setYRange)(low, high, padding=0)

    def _series_changed(self) -> None:
        self._update_category_ticks()
        self._update_zero_lines()

    def _update_zero_lines(self) -> None:
        if self.zero_lines == "auto":
            show = any(s.kind in ("line", "scatter") for s in self.series.values())
        else:
            show = self.zero_lines == "on"
        self._zero_x.setVisible(show)
        self._zero_y.setVisible(show)

    def set_zero_lines(self, mode: str) -> None:
        self.zero_lines = mode
        self._update_zero_lines()

    def _update_category_ticks(self) -> None:
        labels = None
        for s in self.series.values():
            if s.kind == "bar" and s.labels:
                labels = [(float(xv), lab) for xv, lab in zip(s.x, s.labels)]
        self.plot.getAxis("bottom").setTicks([labels] if labels else None)

    # --------------------------------------------------------- view (UI)
    def auto_range(self) -> None:
        self.plot.getViewBox().enableAutoRange()

    def _apply_view(self) -> None:
        self._update_zero_lines()
        self.plot.showGrid(x=self.grid, y=self.grid, alpha=0.18)
        self.legend.setVisible(self.show_legend)
        self._vline.setVisible(self.crosshair)
        self._hline.setVisible(self.crosshair)
        if not self.crosshair:
            self.readout.setText(" ")

    def set_palette(self, name: str) -> None:
        self.palette = name
        colors = PALETTES[name]
        i = 0
        for s in self.series.values():
            if s.auto_color:
                s.color = colors[i % len(colors)]
                i += 1
                self._draw(s)

    def _mouse_moved(self, pos) -> None:
        if not self.crosshair or not self.plot.sceneBoundingRect().contains(pos):
            return
        p = self.plot.getViewBox().mapSceneToView(pos)
        self._vline.setPos(p.x())
        self._hline.setPos(p.y())
        self.readout.setText(f"x = {p.x():.6g}    y = {p.y():.6g}")

    def _toggle(self, attr: str) -> None:
        setattr(self, attr, not getattr(self, attr))
        self._apply_view()

    # -------------------------------------------------------------- saving
    def save_image(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save plot image", f"{self.name}.png",
                                              "PNG image (*.png)")
        if path and not self.pw.grab().save(path, "PNG"):
            QMessageBox.critical(self, "Save failed", f"Could not write {path}")

    def save_csv(self, path: Optional[str] = None) -> bool:
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Save plot data", f"{self.name}.csv",
                                                  "CSV (*.csv)")
            if not path:
                return False
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["series", "kind", "x", "y", "label"])
                for s in self.series.values():
                    for i, (xv, yv) in enumerate(zip(s.x, s.y)):
                        label = s.labels[i] if s.labels else ""
                        writer.writerow([s.name, s.kind, f"{xv:.10g}", f"{yv:.10g}", label])
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", f"Could not write {path}:\n{exc}")
            return False
        return True

    # ----------------------------------------------------------- panel API
    def header_widgets(self):
        return [self.auto_btn, self.save_btn]

    def menu_actions(self):
        acts = [("Hide grid" if self.grid else "Show grid", lambda: self._toggle("grid")),
                ("Hide legend" if self.show_legend else "Show legend", lambda: self._toggle("show_legend")),
                ("Hide crosshair" if self.crosshair else "Show crosshair", lambda: self._toggle("crosshair"))]
        for name in PALETTES:
            mark = "✓ " if name == self.palette else "    "
            acts.append((f"{mark}Palette: {name}", lambda n=name: self.set_palette(n)))
        for mode in ZERO_MODES:
            mark = "✓ " if mode == self.zero_lines else "    "
            label = {"auto": "Zero lines: auto (line/scatter)", "on": "Zero lines: always",
                     "off": "Zero lines: off"}[mode]
            acts.append((mark + label, lambda m=mode: self.set_zero_lines(m)))
        acts.append(("Clear plot", self._op_clear))
        return acts

    def state(self) -> dict:
        """View settings only; plotted data is not saved (use Save → CSV)."""
        return {"grid": self.grid, "legend": self.show_legend, "crosshair": self.crosshair,
                "palette": self.palette, "zero_lines": self.zero_lines}

    def load_state(self, state: dict) -> None:
        for key, attr in (("grid", "grid"), ("legend", "show_legend"), ("crosshair", "crosshair")):
            if isinstance(state.get(key), bool):
                setattr(self, attr, state[key])
        if state.get("palette") in PALETTES:
            self.palette = state["palette"]
        if state.get("zero_lines") in ZERO_MODES:
            self.zero_lines = state["zero_lines"]
        self._apply_view()

    @classmethod
    def script_collection(cls):
        return "Plots"

    def script_handle(self):
        return PlotHandle(self)

    def shutdown(self) -> None:
        self.alive = False
