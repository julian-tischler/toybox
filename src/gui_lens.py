"""
gui_lens.py - Transparent, draggable, resizable "Input Lens" windows, plus the
controller that hides them while the screen is being captured.

Layout of a lens window (all drawn on one Canvas):

    +--------------------------+  <- header strip (drag handle, shows the name)
    |########## name ##########|
    +--------------------------+
    |##########################|  <- bright border frame (resize by its edges)
    |##                      ##|
    |##   see-through area   ##|  <- the capture region (excludes header + border,
    |##                      ##|     so the lens never captures its own paint)
    |##########################|
    +--------------------------+

The lens keeps its absolute screen coordinates as plain ints so the worker
thread can read them without touching Tk.
"""

import queue
import sys
import threading
import time
import tkinter as tk
from contextlib import contextmanager
from typing import Callable, Iterator, List, Optional

from vision import Lens

TRANSPARENT_KEY = "black"
LABEL_COLOR = "#111111"   # solid near-black; must differ from TRANSPARENT_KEY

# How lenses are hidden for a capture: "alpha" (fully transparent, no focus or
# z-order side effects) or "withdraw" (unmap the window). If lenses still show up
# in captures, try the other one.
CAPTURE_HIDE_METHOD = "alpha"


class LensWindow(tk.Toplevel):
    BORDER = 4      # px thickness of the visible frame
    HEADER = 18     # px height of the name/drag strip above the frame
    GRAB = 8        # px edge zone that starts a resize
    MIN_W = 50
    MIN_H = HEADER + 30

    _CURSORS = {
        "move": "fleur", "n": "size_ns", "s": "size_ns", "e": "size_we", "w": "size_we",
        "nw": "size_nw_se", "se": "size_nw_se", "ne": "size_ne_sw", "sw": "size_ne_sw",
    }

    def __init__(self, master, name: str, color: str, left: int, top: int,
                 width: int, height: int,
                 on_change: Optional[Callable[["LensWindow"], None]] = None,
                 capture_guard: Optional[Callable[[], object]] = None):
        super().__init__(master)
        self.lens_name = name
        self.color = color
        self.on_change = on_change

        # Absolute screen geometry of the whole lens window (plain ints).
        self.left, self.top = int(left), int(top)
        self.width = max(self.MIN_W, int(width))
        self.height = max(self.MIN_H, int(height))

        self._drag_zone = "move"
        self._drag_start = (0, 0, 0, 0, 0, 0)

        # Visibility state: manual (toolbar button) and per-capture (automatic).
        self._manual_hidden = False
        self._capture_hidden = False
        self._base_alpha = 1.0
        self._current_alpha = 1.0

        self.overrideredirect(True)                 # borderless
        self.wm_attributes("-topmost", True)        # always on top
        self._canvas_bg = TRANSPARENT_KEY
        self.configure(bg=TRANSPARENT_KEY)
        self._setup_transparency()
        self._current_alpha = self._base_alpha

        self.canvas = tk.Canvas(self, bg=self._canvas_bg, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_hover)

        self._apply_geometry()

        # Backend object handed to user scripts. It only reads plain ints.
        self.lens = Lens(name, lambda: self.capture_region, capture_guard=capture_guard)

    # ------------------------------------------------------------------ API
    @property
    def capture_region(self):
        """(left, top, width, height) of the see-through area, in screen pixels."""
        b = self.BORDER
        return (self.left + b,
                self.top + self.HEADER + b,
                self.width - 2 * b,
                self.height - self.HEADER - 2 * b)

    def to_dict(self) -> dict:
        """Plain-data description used by project_io when saving."""
        return {"name": self.lens_name, "color": self.color, "left": self.left,
                "top": self.top, "width": self.width, "height": self.height}

    def set_name(self, name: str) -> None:
        self.lens_name = name
        self.lens.name = name
        self._redraw()

    def set_manual_hidden(self, hidden: bool) -> None:
        """Toolbar hide/show. Must be called on the GUI thread."""
        self._manual_hidden = hidden
        self._apply_visibility()

    def set_capture_hidden(self, hidden: bool) -> None:
        """Temporary hide around a screen grab. Must be called on the GUI thread."""
        self._capture_hidden = hidden
        self._apply_visibility()

    def close(self) -> None:
        self.destroy()

    # ------------------------------------------------------------ rendering
    def _setup_transparency(self) -> None:
        """Black becomes see-through (Windows). Fall back gracefully elsewhere."""
        try:
            if sys.platform.startswith("win"):
                self.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
            elif sys.platform == "darwin":
                self.wm_attributes("-transparent", True)
                self.configure(bg="systemTransparent")
                self._canvas_bg = "systemTransparent"
            else:
                raise tk.TclError("no colour-key transparency on this platform")
        except tk.TclError:
            # Fallback: translucent window. The tint may slightly affect captures.
            self._base_alpha = 0.35
            self.wm_attributes("-alpha", self._base_alpha)

    def _apply_visibility(self) -> None:
        try:
            withdraw = self._manual_hidden or (
                self._capture_hidden and CAPTURE_HIDE_METHOD == "withdraw")
            alpha = 0.0 if (self._capture_hidden and CAPTURE_HIDE_METHOD == "alpha") \
                else self._base_alpha
            if alpha != self._current_alpha:
                self.wm_attributes("-alpha", alpha)
                self._current_alpha = alpha
            if withdraw:
                if self.state() != "withdrawn":
                    self.withdraw()
            elif self.state() == "withdrawn":
                self.deiconify()
                self.wm_attributes("-topmost", True)
                self.lift()
        except tk.TclError:
            pass  # window was destroyed in the meantime

    def _apply_geometry(self) -> None:
        # Always "+x+y" (never "-x"): in Tk a bare minus means "offset from the right/bottom
        # screen edge", so negative absolute coords must be written as "+-1920".
        self.geometry(f"{self.width}x{self.height}+{self.left}+{self.top}")
        self._redraw()

    def _redraw(self) -> None:
        c, w, h, b, hd = self.canvas, self.width, self.height, self.BORDER, self.HEADER
        c.delete("all")
        fill = {"fill": self.color, "outline": ""}
        c.create_rectangle(0, 0, w, hd, **fill)                 # header strip
        c.create_rectangle(0, hd, b, h, **fill)                 # left
        c.create_rectangle(w - b, hd, w, h, **fill)             # right
        c.create_rectangle(0, hd, w, hd + b, **fill)            # top of frame
        c.create_rectangle(0, h - b, w, h, **fill)              # bottom
        # NOT pure black: black is the transparent colour key on Windows, so black
        # text would be punched through and look see-through.
        c.create_text(6, hd // 2, anchor="w", fill=LABEL_COLOR,
                      font=("Segoe UI", 9, "bold"), text=self.lens_name)

    # ---------------------------------------------------------- interaction
    def _zone(self, x: int, y: int) -> str:
        """Which part of the lens is under (x, y): 'move' or a resize edge/corner."""
        if y < self.HEADER:
            return "move"
        g = self.GRAB
        vertical = "n" if y < self.HEADER + g else ("s" if y >= self.height - g else "")
        horizontal = "w" if x < g else ("e" if x >= self.width - g else "")
        return (vertical + horizontal) or "move"

    def _on_hover(self, e) -> None:
        zone = self._zone(e.x, e.y)
        try:
            self.canvas.configure(cursor=self._CURSORS[zone])
        except tk.TclError:
            self.canvas.configure(cursor="fleur" if zone == "move" else "sizing")

    def _on_press(self, e) -> None:
        self._drag_zone = self._zone(e.x, e.y)
        self._drag_start = (e.x_root, e.y_root, self.left, self.top, self.width, self.height)

    def _on_drag(self, e) -> None:
        sx, sy, l, t, w, h = self._drag_start
        dx, dy = e.x_root - sx, e.y_root - sy
        zone = self._drag_zone

        if zone == "move":
            self.left, self.top = l + dx, t + dy
        else:
            nl, nt, nw, nh = l, t, w, h
            if "e" in zone:
                nw = max(self.MIN_W, w + dx)
            if "s" in zone:
                nh = max(self.MIN_H, h + dy)
            if "w" in zone:
                nw = max(self.MIN_W, w - dx)
                nl = l + w - nw
            if "n" in zone:
                nh = max(self.MIN_H, h - dy)
                nt = t + h - nh
            self.left, self.top, self.width, self.height = nl, nt, nw, nh
        self._apply_geometry()

    def _on_release(self, _e) -> None:
        if self.on_change:
            self.on_change(self)


class LensVisibility:
    """Hides lenses on request, from any thread, so they never appear in a capture.

    Two independent features:

    * Manual toggle (`set_manually_hidden`) - the toolbar's Hide/Show button.
    * Hide-while-measuring (`capture_guard`) - wrapped around every Lens capture.
      A script runs on a worker thread, but Tk may only be touched from the GUI
      thread, so the guard posts a request that the GUI thread picks up (a 5 ms
      poll), waits until the lenses are hidden, then waits `settle_ms` for the
      desktop compositor to actually repaint before the pixels are grabbed.

    To avoid flicker when a script reads several lenses back to back, lenses stay
    hidden for `linger_ms` after the last capture ends, and only reappear if no
    new capture starts in that window.
    """

    POLL_MS = 5

    def __init__(self, root: tk.Tk, windows_provider: Callable[[], List[LensWindow]],
                 settle_ms: int = 50, linger_ms: int = 80):
        self.root = root
        self._windows = windows_provider
        self.settle_ms = settle_ms
        self.linger_ms = linger_ms
        self.hide_while_measuring = True
        self.manually_hidden = False

        self._lock = threading.Lock()
        self._active = 0                      # captures currently in progress
        self._capture_hidden = False          # lenses are (being) hidden for a capture
        self._hidden_windows: List[LensWindow] = []
        self._requests: "queue.Queue" = queue.Queue()
        self._show_deadline: Optional[float] = None
        self._pump()

    # --------------------------------------------------------- manual toggle
    def set_manually_hidden(self, hidden: bool) -> None:
        """GUI thread only."""
        self.manually_hidden = hidden
        for win in self._windows():
            win.set_manual_hidden(hidden)

    # ------------------------------------------------------ per-capture hide
    @contextmanager
    def capture_guard(self) -> Iterator[None]:
        """Context manager that keeps lenses hidden while the body grabs pixels."""
        if not self.hide_while_measuring or self.manually_hidden:
            yield
            return

        if threading.current_thread() is threading.main_thread():
            # Called on the GUI thread itself: no hand-off needed (and waiting on
            # ourselves would deadlock), so hide, repaint, grab, restore directly.
            windows = list(self._windows())
            for win in windows:
                win.set_capture_hidden(True)
            self.root.update()
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
                done = threading.Event()
                self._requests.put(("hide", done))
                done.wait(timeout=1.0)                  # GUI thread hid the lenses...
                time.sleep(self.settle_ms / 1000)       # ...now let the screen repaint
            yield
        finally:
            with self._lock:
                self._active -= 1
                idle = self._active == 0
            if idle:
                self._requests.put(("release", None))

    # ------------------------------------------------------ GUI-thread side
    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self._requests.get_nowait()
                if kind == "hide":
                    self._hidden_windows = list(self._windows())
                    for win in self._hidden_windows:
                        win.set_capture_hidden(True)
                    self.root.update_idletasks()
                    payload.set()
                elif kind == "release":
                    self._show_deadline = time.monotonic() + self.linger_ms / 1000
        except queue.Empty:
            pass

        if self._show_deadline is not None and time.monotonic() >= self._show_deadline:
            self._show_deadline = None
            self._restore_if_idle()
        self.root.after(self.POLL_MS, self._pump)

    def _restore_if_idle(self) -> None:
        with self._lock:
            if self._active == 0 and self._capture_hidden:
                self._capture_hidden = False
                for win in self._hidden_windows:
                    win.set_capture_hidden(False)
                self._hidden_windows = []