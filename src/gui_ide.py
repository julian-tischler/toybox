"""
gui_ide.py - The main IDE window: editor, console, lens sidebar, run controls,
dark theme and project save/load.

Layout:
    [ Preferences v ]                                  <- toolbar
    (Interval, Hide while measuring, Settle)           <- collapsible strip
    | INPUT LENSES  (eye) | SCRIPT              file |
    | [name      ] (+)    |                          |
    | # name          (x) |                          |
    |                     | [Load][Save]  [Cont][Run]|
    |---------------------+--------------------------|
    | CONSOLE                                  Clear |

The panels are separated by visible divider lines (highlighted on hover). Drag
one to resize; double-click the one next to the sidebar or above the console to
collapse or restore that panel. A collapsed panel keeps its divider at the edge.
"""

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from editor_helpers import INDENT_WIDTH, EditorEnhancements
from executor import ScriptExecutor
from icons import load_icon
from gui_lens import LensVisibility, LensWindow
from project_io import ProjectError, load_project, save_project

# ------------------------------------------------------------------- theme
BG = "#1f2024"          # window background
EDITOR_BG = "#17181b"   # editor + console
FIELD = "#2a2c31"       # entries, listbox
BTN = "#2f3238"
BTN_HOVER = "#3a3e46"
BTN_PRESSED = "#454a54"
BORDER = "#3a3d44"
FG = "#d7dae0"
MUTED = "#8b919c"
ACCENT = "#4c8dff"
ACCENT_HOVER = "#6aa1ff"
ACCENT_PRESSED = "#3b78e0"
SELECTION = "#2f4b7c"
ERROR_FG = "#ff6b6b"
INFO_FG = "#7aa2f7"

UI_FONT = ("Segoe UI", 9)
UI_FONT_BOLD = ("Segoe UI", 9, "bold")
CODE_FONT = ("Consolas", 11)

PALETTE = ["#00ff66", "#ff2bd6", "#00d5ff", "#ffd400", "#ff7a00", "#ff3b3b"]
SIDEBAR_WIDTH = 250       # default sidebar width (px)
SIDEBAR_MIN = 210         # min sidebar width while expanded
CONSOLE_HEIGHT = 230
CONSOLE_MIN = 90
COLLAPSED_PX = 30         # a panel narrower/shorter than this counts as collapsed
SASH_WIDTH = 9            # divider grab/hover area (logical px, scaled with DPI)
DIVIDER_LINE = 3          # visible divider line inside that area (logical px)
DIVIDER = BORDER          # divider line colour
DIVIDER_HOVER = "#5a5f6a" # divider under the mouse: a little lighter, not the accent
MAX_CONSOLE_LINES = 3000
OUTPUT_POLL_MS = 30
PROJECT_TYPES = [("ScreenLens project", "*.json"), ("Python script (script only)", "*.py")]

DEFAULT_SCRIPT = '''\
# 1. Add lenses in the sidebar and name them "voltage" and "current".
# 2. Drag each lens over the number you want to read.
# 3. Press Run Once (Ctrl+Enter) or Run Continuous.
#
# Whitelist presets you can pass to get_text()/get_float():
#   NUMERIC INTEGER FLOAT ALPHA ALPHA_LOWER ALPHA_UPPER ALPHANUM
#   ALPHANUM_LOWER ALPHANUM_UPPER HEX PUNCTUATION PRINTABLE
#   e.g. Lenses["id"].get_text(whitelist=ALPHANUM_LOWER + "-")
#
# Read only text of one colour:  Lenses["id"].color_mask("green").get_text()

v1 = Lenses["voltage"].get_float()
v2 = Lenses["current"].get_float()
if v1 and v2:
    print(f"Power: {v1 * v2} W")
'''


def _virtual_screen():
    """(left, top, width, height) of all monitors combined, or None if unknown."""
    if not sys.platform.startswith("win"):
        return None
    import ctypes
    metrics = ctypes.windll.user32.GetSystemMetrics
    width, height = metrics(78), metrics(79)
    return (metrics(76), metrics(77), width, height) if width > 0 and height > 0 else None


class Tooltip:
    """Small hover tooltip for a widget. `text` may be a str or a callable."""

    DELAY_MS = 500

    def __init__(self, widget: tk.Widget, text):
        self.widget, self.text = widget, text
        self._job = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._hide()
        self._job = self.widget.after(self.DELAY_MS, self._show)

    def _show(self):
        self._job = None
        text = self.text() if callable(self.text) else self.text
        if not text or not self.widget.winfo_exists() or not self.widget.winfo_ismapped():
            return
        tip = self._tip = tk.Toplevel(self.widget)
        tip.overrideredirect(True)
        tip.wm_attributes("-topmost", True)
        tk.Label(tip, text=text, bg=FIELD, fg=FG, font=UI_FONT, padx=6, pady=2,
                 highlightthickness=1, highlightbackground=BORDER).pack()
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tip.geometry(f"+{x}+{y}")

    def _hide(self, _e=None):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


class IconButton(tk.Label):
    """Flat clickable icon: swaps to `hover_icon` / `hover_bg` under the mouse."""

    def __init__(self, master, icon, hover_icon=None, command=None, bg=BG,
                 hover_bg=BTN_HOVER, tooltip=None):
        super().__init__(master, image=icon, bg=bg, bd=0, padx=3, pady=3, cursor="hand2")
        self.command = command
        self._icons = (icon, hover_icon or icon)
        self._bgs = (bg, hover_bg)
        self._hover = False
        self.bind("<Enter>", lambda _e: self._set_hover(True), add="+")
        self.bind("<Leave>", lambda _e: self._set_hover(False), add="+")
        self.bind("<ButtonRelease-1>", self._on_click)
        if tooltip:
            Tooltip(self, tooltip)

    def set_icons(self, icon, hover_icon=None) -> None:
        self._icons = (icon, hover_icon or icon)
        self._apply()

    def set_bg(self, bg, hover_bg=None) -> None:
        self._bgs = (bg, hover_bg or self._bgs[1])
        self._apply()

    def _set_hover(self, hover: bool) -> None:
        self._hover = hover
        self._apply()

    def _apply(self) -> None:
        i = 1 if self._hover else 0
        self.configure(image=self._icons[i], bg=self._bgs[i])

    def _on_click(self, e) -> None:
        # Only fire if the button is released over the icon (lets users back out).
        if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height() and self.command:
            self.command()


def _double_click_ms() -> int:
    """The system double-click interval (Windows setting), else 500 ms."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            return int(ctypes.windll.user32.GetDoubleClickTime())
        except (AttributeError, OSError):
            pass
    return 500


class DividerLine:
    """Thin visible line centred in a PanedWindow's wider, invisible sash.

    tk.PanedWindow paints the whole sash in its background colour, so the grab
    area and the visible line would always be the same width. Instead the sash
    is wide and background-coloured, and a thin Frame is placed over its
    middle. Mouse events on the line are forwarded to the PanedWindow, so
    dragging and double-clicking work on the line exactly as on the sash.
    """

    _FORWARD = ("<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>", "<Motion>")

    def __init__(self, pane: tk.PanedWindow, thickness: int, on_double, watch=()):
        self.pane = pane
        self.thickness = thickness
        self.horizontal = str(pane.cget("orient")) == "horizontal"
        self._pending = False
        cursor = "sb_h_double_arrow" if self.horizontal else "sb_v_double_arrow"
        self.line = tk.Frame(pane, bg=DIVIDER, bd=0, highlightthickness=0, cursor=cursor)
        for seq in self._FORWARD:
            self.line.bind(seq, lambda e, s=seq: self._forward(s, e))
        # Tk's own double-click detection does not work here: every forwarded press
        # counts as a click on the PanedWindow and resets it. So detect it ourselves.
        self._on_double = on_double
        self._last_press = None               # (time, x_root, y_root)
        self.line.bind("<ButtonPress-1>", self._on_press)
        self.line.bind("<Enter>", lambda _e: self.set_hover(True))
        # The sash moves without the PanedWindow itself changing size, but the
        # panes next to it are resized: re-place the line whenever they are.
        for w in (pane, *watch):
            w.bind("<Configure>", lambda _e: self.schedule_place(), add="+")
        self.schedule_place()

    def _on_press(self, e) -> str:
        last, self._last_press = self._last_press, (e.time, e.x_root, e.y_root)
        if (last is not None and 0 <= e.time - last[0] <= _double_click_ms()
                and abs(e.x_root - last[1]) <= 4 and abs(e.y_root - last[2]) <= 4):
            self._last_press = None           # a third click starts a new pair
            self._on_double(e)
            return "break"                    # no drag for the second click
        return self._forward("<ButtonPress-1>", e)

    def _forward(self, seq: str, e) -> str:
        self.pane.event_generate(seq, x=e.x + self.line.winfo_x(), y=e.y + self.line.winfo_y())
        self.place()
        return "break"

    def schedule_place(self) -> None:
        if not self._pending:
            self._pending = True
            self.pane.after_idle(self.place)

    def place(self) -> None:
        self._pending = False
        if not self.pane.winfo_exists() or len(self.pane.panes()) < 2:
            return
        sx, sy = self.pane.sash_coord(0)
        offset = (int(self.pane.cget("sashwidth")) - self.thickness) // 2
        if self.horizontal:
            self.line.place(x=sx + offset, y=0, width=self.thickness, relheight=1)
        else:
            self.line.place(x=0, y=sy + offset, relwidth=1, height=self.thickness)
        self.line.lift()

    def set_hover(self, hover: bool) -> None:
        color = DIVIDER_HOVER if hover else DIVIDER
        if self.line.cget("bg") != color:
            self.line.configure(bg=color)


class AppMainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ScreenLens")
        self.geometry("1100x720")
        self.minsize(900, 500)

        self.executor = ScriptExecutor()
        self.lens_windows = {}        # name -> LensWindow (insertion ordered)
        self._color_index = 0
        self._continuous = False
        self._tick_job = None
        self.current_path = None      # project file the editor is bound to

        self.name_var = tk.StringVar()
        self.interval_var = tk.StringVar(value="500")
        self.hide_var = tk.BooleanVar(value=True)      # hide lenses while measuring
        self.settle_var = tk.StringVar(value="50")     # ms to wait after hiding
        self.file_var = tk.StringVar()
        self.prefs_open = False
        self._run_state = None        # last state shown by the run buttons
        self._lens_rows = {}          # name -> (row frame, name label)
        self._renaming = None         # name of the lens being renamed inline
        self._sidebar_width = SIDEBAR_WIDTH
        self._console_height = CONSOLE_HEIGHT
        self._scale = self.winfo_fpixels("1i") / 96.0
        self.visibility = LensVisibility(self, lambda: list(self.lens_windows.values()))
        self.settle_var.trace_add("write", self._on_settle_change)

        self._apply_theme()
        self._build_toolbar()
        self._build_panes()
        self._update_file_label()
        self._refresh_lens_list()

        self.executor.install_redirect()   # print()/errors now land in the console
        self._pump_output()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-Return>", lambda _e: self.run_once())
        self.bind("<Control-s>", lambda _e: (self.save_project(), "break")[1])
        self.bind("<Control-S>", lambda _e: (self.save_project(as_new=True), "break")[1])
        self.bind("<Control-o>", lambda _e: (self.load_project(), "break")[1])

        self.update_idletasks()
        self._dark_title_bar()

    # ------------------------------------------------------------- theming
    def _apply_theme(self) -> None:
        self.configure(bg=BG)
        s = ttk.Style(self)
        s.theme_use("clam")   # the only built-in theme that can be fully recoloured

        s.configure(".", background=BG, foreground=FG, fieldbackground=FIELD,
                    bordercolor=BORDER, lightcolor=BG, darkcolor=BG, troughcolor=BG,
                    focuscolor=BG, font=UI_FONT)
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Header.TLabel", foreground=MUTED, font=("Segoe UI", 8, "bold"))

        s.configure("TButton", background=BTN, foreground=FG, bordercolor=BORDER,
                    lightcolor=BTN, darkcolor=BTN, focuscolor=BTN, padding=(10, 4),
                    relief="flat")
        s.map("TButton",
              background=[("disabled", BG), ("pressed", BTN_PRESSED), ("active", BTN_HOVER)],
              foreground=[("disabled", MUTED)],
              bordercolor=[("focus", ACCENT)])
        s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                    bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT, focuscolor=ACCENT)
        s.map("Accent.TButton",
              background=[("disabled", BG), ("pressed", ACCENT_PRESSED), ("active", ACCENT_HOVER)],
              foreground=[("disabled", MUTED)],
              bordercolor=[("disabled", BORDER)])

        # Flat button that blends into the window (toolbar "Preferences").
        s.configure("Ghost.TButton", background=BG, bordercolor=BG, lightcolor=BG,
                    darkcolor=BG, focuscolor=BG, padding=(8, 3))
        s.map("Ghost.TButton", background=[("pressed", BTN_PRESSED), ("active", BTN_HOVER)],
              bordercolor=[("focus", BG)])

        for widget in ("TEntry", "TSpinbox"):
            s.configure(widget, fieldbackground=FIELD, foreground=FG, insertcolor=FG,
                        bordercolor=BORDER, lightcolor=FIELD, darkcolor=FIELD,
                        arrowcolor=FG, background=BTN, padding=3)
            s.map(widget, bordercolor=[("focus", ACCENT)],
                  background=[("active", BTN_HOVER)])

        s.configure("Invalid.TEntry", bordercolor=ERROR_FG)
        s.map("Invalid.TEntry", bordercolor=[("focus", ERROR_FG)])

        s.configure("TCheckbutton", background=BG, foreground=FG, indicatorbackground=FIELD,
                    indicatorforeground="#ffffff", upperbordercolor=BORDER,
                    lowerbordercolor=BORDER)
        s.map("TCheckbutton", background=[("active", BG)],
              indicatorbackground=[("selected", ACCENT), ("active", BTN_HOVER)])

        s.configure("Vertical.TScrollbar", background=BTN, troughcolor=EDITOR_BG,
                    bordercolor=EDITOR_BG, lightcolor=BTN, darkcolor=BTN,
                    arrowcolor=MUTED, gripcount=0)
        s.configure("Horizontal.TScrollbar", background=BTN, troughcolor=EDITOR_BG,
                    bordercolor=EDITOR_BG, lightcolor=BTN, darkcolor=BTN,
                    arrowcolor=MUTED, gripcount=0)
        s.map("Vertical.TScrollbar", background=[("active", BTN_HOVER)])
        s.map("Horizontal.TScrollbar", background=[("active", BTN_HOVER)])

        # Entry drop-down / spinbox text colours inside the clam theme.
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", FG)

    def _dark_title_bar(self) -> None:
        """Ask Windows 10/11 for a dark title bar. Silently does nothing elsewhere."""
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1)
            for attribute in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (new / pre-20H1 id)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
        except Exception:   # noqa: BLE001 - purely cosmetic
            pass

    # ------------------------------------------------------------------ UI
    def _build_toolbar(self) -> None:
        self.toolbar = ttk.Frame(self, padding=(6, 6, 10, 4))
        self.toolbar.pack(side="top", fill="x")
        self.btn_prefs = ttk.Button(self.toolbar, style="Ghost.TButton",
                                    command=self.toggle_preferences)
        self.btn_prefs.pack(side="left")

        # Collapsible preferences strip (packed below the toolbar when open).
        strip = self.prefs_strip = ttk.Frame(self)
        row = ttk.Frame(strip, padding=(12, 2, 10, 8))
        row.pack(fill="x")
        ttk.Label(row, text="Interval (ms)", style="Muted.TLabel").pack(side="left", padx=(0, 4))
        ttk.Spinbox(row, from_=100, to=10000, increment=100, width=6,
                    textvariable=self.interval_var).pack(side="left")
        ttk.Checkbutton(row, text="Hide while measuring", variable=self.hide_var,
                        command=self._on_hide_option_change).pack(side="left", padx=(18, 2))
        ttk.Label(row, text="Settle (ms)", style="Muted.TLabel").pack(side="left", padx=(12, 4))
        ttk.Spinbox(row, from_=0, to=500, increment=10, width=4,
                    textvariable=self.settle_var).pack(side="left")
        tk.Frame(strip, height=1, bg=BORDER).pack(fill="x", padx=8, pady=(0, 6))
        self._sync_prefs_button()

    def toggle_preferences(self) -> None:
        self.prefs_open = not self.prefs_open
        if self.prefs_open:
            self.prefs_strip.pack(side="top", fill="x", after=self.toolbar)
        else:
            self.prefs_strip.pack_forget()
        self._sync_prefs_button()

    def _sync_prefs_button(self) -> None:
        self.btn_prefs.configure(text="⚙  Preferences  " + ("▴" if self.prefs_open else "▾"))

    def _text_widget(self, parent, **kwargs) -> tk.Text:
        return tk.Text(parent, bg=EDITOR_BG, fg=FG, insertbackground=FG, relief="flat", bd=0,
                       highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
                       selectbackground=SELECTION, selectforeground="#ffffff",
                       padx=8, pady=6, **kwargs)

    def _build_panes(self) -> None:
        # Wide, invisible sashes (easy to grab) with a thin DividerLine drawn in the
        # middle that lights up on hover; double-click to collapse/restore a panel.
        sash = dict(sashwidth=max(5, round(SASH_WIDTH * self._scale)), sashrelief="flat",
                    bd=0, bg=BG, opaqueresize=True)
        outer = self.outer_pane = tk.PanedWindow(self, orient="vertical", **sash)
        outer.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        top = self.top_pane = tk.PanedWindow(outer, orient="horizontal", **sash)
        outer.add(top, stretch="always")

        self.sidebar = self._build_sidebar(top)
        top.add(self.sidebar, minsize=SIDEBAR_MIN, width=SIDEBAR_WIDTH)
        editor = self._build_editor(top)
        top.add(editor, stretch="always")
        self.console_frame = self._build_console(outer)
        outer.add(self.console_frame, height=CONSOLE_HEIGHT, minsize=CONSOLE_MIN)

        # Double-click a divider to collapse / restore the panel next to it.
        self._sash_pressed = {}
        self._dividers = {}
        line_px = max(1, round(DIVIDER_LINE * self._scale))
        for pane, toggle, watch in ((top, self.toggle_sidebar, (editor,)),
                                    (outer, self.toggle_console, (top,))):
            pane.bind("<ButtonPress-1>", lambda e, p=pane: self._on_sash_press(p, e))
            pane.bind("<Double-Button-1>",
                      lambda e, p=pane, t=toggle: self._on_sash_double(p, e, t))
            pane.bind("<Motion>", lambda e, p=pane: self._on_sash_hover(p, e))
            pane.bind("<Leave>",
                      lambda _e, p=pane: self.after_idle(self._refresh_divider_hover, p))
            pane.bind("<ButtonRelease-1>",
                      lambda _e, p=pane: self.after_idle(self._refresh_divider_hover, p))
            divider = DividerLine(pane, line_px, watch=watch,
                                  on_double=lambda e, p=pane, t=toggle:
                                  self._on_sash_double(p, e, t))
            divider.line.bind("<Leave>", lambda _e, p=pane:
                              self.after_idle(self._refresh_divider_hover, p))
            self._dividers[str(pane)] = divider

    # ---- Sidebar: lens management
    def _build_sidebar(self, parent) -> ttk.Frame:
        side = ttk.Frame(parent, padding=(0, 0, 6, 0))

        head = ttk.Frame(side)
        head.pack(fill="x", pady=(0, 6))
        ttk.Label(head, text="INPUT LENSES", style="Header.TLabel").pack(side="left")
        self.btn_eye = IconButton(
            head, load_icon(self, "eye"), load_icon(self, "eye", "fg"),
            command=self.toggle_lens_visibility,
            tooltip=lambda: ("Show all lenses" if self.visibility.manually_hidden
                             else "Hide all lenses"))
        self.btn_eye.pack(side="right")

        add_row = ttk.Frame(side)
        add_row.pack(fill="x", pady=(0, 8))
        self.btn_add = IconButton(add_row, load_icon(self, "plus-circle"),
                                  load_icon(self, "plus-circle", "fg"),
                                  command=self.add_lens, tooltip="Add lens (Enter)")
        self.btn_add.pack(side="right", padx=(4, 0))
        self.name_entry = ttk.Entry(add_row, textvariable=self.name_var)
        self.name_entry.pack(side="left", fill="x", expand=True)
        self.name_entry.bind("<Return>", lambda _e: self.add_lens())

        # Scrollable list of lens rows:  [swatch] name ............ (x)
        box = tk.Frame(side, bg=FIELD, highlightthickness=1, highlightbackground=BORDER)
        box.pack(fill="both", expand=True)
        canvas = self.lens_canvas = tk.Canvas(box, bg=FIELD, highlightthickness=0, bd=0,
                                              width=1, yscrollincrement=8)
        lsb = ttk.Scrollbar(box, command=canvas.yview)
        canvas.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.lens_rows = tk.Frame(canvas, bg=FIELD)
        rows_id = canvas.create_window(0, 0, window=self.lens_rows, anchor="nw")
        self.lens_rows.bind("<Configure>",
                            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(rows_id, width=e.width))
        for w in (canvas, self.lens_rows):
            w.bind("<MouseWheel>", self._on_lens_wheel)

        ttk.Label(side, justify="left", style="Muted.TLabel",
                  text="Drag a lens by its coloured header;\nresize from its edges.\n"
                       "Double-click a name to rename it.\n"
                       "Use Lenses[\"name\"] in code.").pack(anchor="w", pady=(8, 0))
        return side

    # ---- Editor with its run bar
    def _build_editor(self, parent) -> ttk.Frame:
        editor_frame = ttk.Frame(parent, padding=(6, 0, 0, 0))
        head = ttk.Frame(editor_frame)
        head.pack(side="top", fill="x", pady=(0, 6))
        ttk.Label(head, text="SCRIPT", style="Header.TLabel").pack(side="left")
        ttk.Label(head, textvariable=self.file_var, style="Muted.TLabel").pack(side="right")

        # Bottom bar:  [Load] [Save] ........ [Run Continuous | Stop] [Run Once]
        bar = ttk.Frame(editor_frame)
        bar.pack(side="bottom", fill="x", pady=(6, 10))
        ttk.Button(bar, text="Load", command=self.load_project).pack(side="left")
        ttk.Button(bar, text="Save", command=self.save_project).pack(side="left", padx=(6, 0))
        self.btn_once = ttk.Button(bar, text="▶  Run Once", style="Accent.TButton",
                                   command=self.run_once)
        self.btn_once.pack(side="right")
        self.btn_cont = ttk.Button(bar, width=17, command=self.toggle_run)
        self.btn_cont.pack(side="right", padx=(0, 6))

        body = ttk.Frame(editor_frame)
        body.pack(side="top", fill="both", expand=True)
        # Tab stops every INDENT_WIDTH characters, so tabs in loaded scripts line up
        # with the spaces the editor helpers insert.
        tab_px = tkfont.Font(root=self, font=CODE_FONT).measure(" " * INDENT_WIDTH)
        self.editor = self._text_widget(body, wrap="none", undo=True, font=CODE_FONT,
                                        tabs=(tab_px,))
        ysb = ttk.Scrollbar(body, command=self.editor.yview)
        xsb = ttk.Scrollbar(body, orient="horizontal", command=self.editor.xview)
        self.editor.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        ysb.pack(side="right", fill="y")
        xsb.pack(side="bottom", fill="x")
        self.editor.pack(fill="both", expand=True)
        self.editor.insert("1.0", DEFAULT_SCRIPT)
        self.editor.edit_reset()
        self.editor.edit_modified(False)
        # Auto-close, smart Enter, (de)indent, comment toggle, move/duplicate lines.
        self.editor_tools = EditorEnhancements(self.editor)
        # EditorEnhancements binds <Return> on the editor and returns "break", which
        # would swallow the window-level Ctrl+Enter, so bind Run Once here as well.
        for seq in ("<Control-Return>", "<Control-KP_Enter>"):
            self.editor.bind(seq, lambda _e: (self.run_once(), "break")[1])
        self.editor.bind("<Control-o>", lambda _e: (self.load_project(), "break")[1])
        self._sync_run_buttons()
        return editor_frame

    # ---- Console (read-only)
    def _build_console(self, parent) -> ttk.Frame:
        console_frame = ttk.Frame(parent, padding=(0, 8, 0, 0))
        chead = ttk.Frame(console_frame)
        chead.pack(fill="x", pady=(0, 6))
        ttk.Label(chead, text="CONSOLE", style="Header.TLabel").pack(side="left")
        ttk.Button(chead, text="Clear", command=self.clear_console,
                   padding=(8, 1)).pack(side="right")
        cbody = ttk.Frame(console_frame)
        cbody.pack(fill="both", expand=True)
        self.console = self._text_widget(cbody, height=10, wrap="word", state="disabled",
                                         font=("Consolas", 10))
        csb = ttk.Scrollbar(cbody, command=self.console.yview)
        self.console.configure(yscrollcommand=csb.set)
        csb.pack(side="right", fill="y")
        self.console.pack(fill="both", expand=True)
        self.console.tag_configure("stderr", foreground=ERROR_FG)
        self.console.tag_configure("info", foreground=INFO_FG)
        return console_frame

    # ------------------------------------------------------ collapsing panes
    @staticmethod
    def _on_sash(pane: tk.PanedWindow, event) -> bool:
        ident = pane.identify(event.x, event.y)
        parts = ident if isinstance(ident, (tuple, list)) else str(ident).split()
        return "sash" in [str(p) for p in parts]

    def _on_sash_hover(self, pane: tk.PanedWindow, event) -> None:
        self._set_divider_hover(pane, self._on_sash(pane, event))

    def _set_divider_hover(self, pane: tk.PanedWindow, hover: bool) -> None:
        self._dividers[str(pane)].set_hover(hover)

    def _refresh_divider_hover(self, pane: tk.PanedWindow) -> None:
        """Re-check the highlight from the current mouse position. Needed when the
        sash moves away under a still mouse (collapse/restore): Tk then sends no
        <Motion>/<Leave>, and the old highlight would stick."""
        x = pane.winfo_pointerx() - pane.winfo_rootx()
        y = pane.winfo_pointery() - pane.winfo_rooty()
        inside = 0 <= x < pane.winfo_width() and 0 <= y < pane.winfo_height()
        ident = pane.identify(x, y) if inside else ""
        parts = ident if isinstance(ident, (tuple, list)) else str(ident).split()
        self._set_divider_hover(pane, "sash" in [str(p) for p in parts])

    def _on_sash_press(self, pane: tk.PanedWindow, event) -> None:
        """Remember whether a click started on the sash. Checked here, before Tk's
        own sash-drag binding runs: during the drag the sash briefly moves, so a
        hit test at double-click time is unreliable."""
        self._sash_pressed[str(pane)] = self._on_sash(pane, event)

    def _on_sash_double(self, pane: tk.PanedWindow, _event, toggle):
        if not self._sash_pressed.get(str(pane)):
            return None
        # "break" keeps Tk's sash-drag binding from handling this click, otherwise
        # the release would drag the sash straight back to the mouse position.
        def run():
            toggle()
            self.update_idletasks()
            self._dividers[str(pane)].place()
            self._refresh_divider_hover(pane)   # the sash moved away from the mouse
        self.after_idle(run)
        return "break"

    # Collapsed state is read from the sash position: Tk unmaps a pane squeezed to
    # zero size without updating its winfo_width/height.
    def _sidebar_px(self) -> int:
        return self.top_pane.sash_coord(0)[0]

    def _console_px(self) -> int:
        outer = self.outer_pane
        return outer.winfo_height() - outer.sash_coord(0)[1] - int(outer.cget("sashwidth"))

    def sidebar_collapsed(self) -> bool:
        return self._sidebar_px() < COLLAPSED_PX

    def console_collapsed(self) -> bool:
        return self._console_px() < COLLAPSED_PX

    def toggle_sidebar(self) -> None:
        top = self.top_pane
        self.update_idletasks()
        if self.sidebar_collapsed():
            top.sash_place(0, max(SIDEBAR_MIN, self._sidebar_width), 0)
            self.update_idletasks()
            top.paneconfigure(self.sidebar, minsize=SIDEBAR_MIN)
        else:
            self._sidebar_width = self._sidebar_px()
            top.paneconfigure(self.sidebar, minsize=0)
            self.update_idletasks()          # the new minsize must apply before moving
            top.sash_place(0, 0, 0)          # the divider stays visible at the left edge

    def toggle_console(self) -> None:
        outer = self.outer_pane
        self.update_idletasks()
        if self.console_collapsed():
            height = max(CONSOLE_MIN, self._console_height)
            total = outer.winfo_height()
            outer.sash_place(0, 0, max(0, total - height - int(outer.cget("sashwidth"))))
            self.update_idletasks()
            outer.paneconfigure(self.console_frame, minsize=CONSOLE_MIN)
        else:
            self._console_height = self._console_px()
            outer.paneconfigure(self.console_frame, minsize=0)
            self.update_idletasks()
            # Tk clamps this so the divider stays fully visible at the bottom edge.
            outer.sash_place(0, 0, outer.winfo_height())

    # ------------------------------------------------------------- console
    def _append_console(self, text: str, tag: str) -> None:
        c = self.console
        c.configure(state="normal")
        c.insert("end", text, tag)
        lines = int(c.index("end-1c").split(".")[0])
        if lines > MAX_CONSOLE_LINES:
            c.delete("1.0", f"{lines - MAX_CONSOLE_LINES}.0")
        c.see("end")
        c.configure(state="disabled")

    def clear_console(self) -> None:
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _pump_output(self) -> None:
        """Main-thread poll: move queued script output into the console widget."""
        items = self.executor.drain()
        if items:
            tag, buf = items[0][0], []
            for t, text in items:
                if t != tag:
                    self._append_console("".join(buf), tag)
                    tag, buf = t, []
                buf.append(text)
            self._append_console("".join(buf), tag)
        self._sync_run_buttons()
        self.after(OUTPUT_POLL_MS, self._pump_output)

    # --------------------------------------------------------------- lenses
    def _next_default_name(self) -> str:
        i = len(self.lens_windows) + 1
        while f"lens{i}" in self.lens_windows:
            i += 1
        return f"lens{i}"

    def _refresh_lens_list(self, *_args) -> None:
        """Rebuild the sidebar rows from self.lens_windows."""
        for child in self.lens_rows.winfo_children():
            child.destroy()
        self._lens_rows = {}
        self._renaming = None
        if not self.lens_windows:
            empty = tk.Label(self.lens_rows, text="No lenses yet - type a name and press +",
                             bg=FIELD, fg=MUTED, font=UI_FONT, anchor="w", padx=8, pady=6)
            empty.pack(fill="x")
            empty.bind("<MouseWheel>", self._on_lens_wheel)
        for name, win in self.lens_windows.items():
            self._add_lens_row(name, win.color)

    def _add_lens_row(self, name: str, color: str) -> None:
        row = tk.Frame(self.lens_rows, bg=FIELD)
        row.pack(fill="x")
        sw_px = max(8, round(10 * self._scale))
        swatch = tk.Frame(row, bg=color, width=sw_px, height=sw_px,
                          highlightthickness=1, highlightbackground=BORDER)
        swatch.pack(side="left", padx=(8, 8))
        label = tk.Label(row, text=name, bg=FIELD, fg=FG, font=UI_FONT, anchor="w")
        label.pack(side="left", fill="x", expand=True, pady=4)
        delete = IconButton(row, load_icon(self, "xmark-circle"),
                            load_icon(self, "xmark-circle", "error"),
                            command=lambda n=name: self.delete_lens(n),
                            bg=FIELD, hover_bg=FIELD, tooltip="Delete lens")
        delete.pack(side="right", padx=(0, 4))

        label.bind("<Double-Button-1>", lambda _e, n=name: self._begin_rename(n))
        Tooltip(label, "Double-click to rename")

        def set_bg(bg):
            if row.winfo_exists():
                row.configure(bg=bg)
                label.configure(bg=bg)
                delete.set_bg(bg, bg)

        def on_leave(e):
            # <Leave> also fires when moving onto a child; only un-hover if truly outside.
            under = self.winfo_containing(e.x_root, e.y_root)
            if under is None or not str(under).startswith(str(row)):
                set_bg(FIELD)

        row.bind("<Enter>", lambda _e: set_bg(BTN))
        row.bind("<Leave>", on_leave)
        for w in (row, swatch, label, delete):
            w.bind("<MouseWheel>", self._on_lens_wheel, add="+")
        self._lens_rows[name] = (row, label)

    def _on_lens_wheel(self, e) -> str:
        c = self.lens_canvas
        if self.lens_rows.winfo_height() > c.winfo_height():
            c.yview_scroll(int(-e.delta / 40), "units")
        return "break"

    # ---- inline rename
    def _begin_rename(self, name: str) -> None:
        if self._renaming is not None or name not in self._lens_rows:
            return
        row, label = self._lens_rows[name]
        self._renaming = name
        var = tk.StringVar(value=name)
        entry = ttk.Entry(row, textvariable=var, font=UI_FONT)
        entry.pack(side="left", fill="x", expand=True, pady=1, padx=(0, 4), before=label)
        label.pack_forget()
        entry.select_range(0, "end")
        entry.icursor("end")
        entry.focus_set()
        done = [False]

        def finish(commit: bool, from_focus: bool = False):
            if done[0]:
                return
            new = var.get().strip()
            changed = commit and bool(new) and new != name
            if changed and new in self.lens_windows:
                if not from_focus:
                    entry.configure(style="Invalid.TEntry")   # keep editing
                    return
                changed = False                               # clicked away: cancel
            done[0] = True
            if changed:
                self.rename_lens(name, new)                   # rebuilds the rows
            else:
                label.pack(side="left", fill="x", expand=True, pady=4, before=entry)
                entry.destroy()
                self._renaming = None

        entry.bind("<Return>", lambda _e: finish(True))
        entry.bind("<KP_Enter>", lambda _e: finish(True))
        entry.bind("<Escape>", lambda _e: finish(False))
        entry.bind("<FocusOut>", lambda _e: finish(True, from_focus=True))
        var.trace_add("write", lambda *_: entry.configure(style="TEntry"))

    def _create_lens(self, name, color, left, top, width, height) -> LensWindow:
        win = LensWindow(self, name, color, left, top, width, height,
                         capture_guard=self.visibility.capture_guard)
        self.lens_windows[name] = win
        return win

    def add_lens(self) -> None:
        name = self.name_var.get().strip() or self._next_default_name()
        if name in self.lens_windows:
            messagebox.showwarning("Duplicate name", f"A lens named {name!r} already exists.")
            return
        self._set_lenses_hidden(False)   # a new lens should never appear hidden
        offset = 40 * (len(self.lens_windows) % 8)
        color = PALETTE[self._color_index % len(PALETTE)]
        self._color_index += 1
        self._create_lens(name, color, 240 + offset, 180 + offset, 220, 90)
        self.name_var.set("")
        self._refresh_lens_list()

    def rename_lens(self, old: str, new: str) -> bool:
        """Rename a lens, keeping its place in the list. False if not possible."""
        new = new.strip()
        if old not in self.lens_windows or not new or (new != old and new in self.lens_windows):
            return False
        self.lens_windows = {(new if k == old else k): v for k, v in self.lens_windows.items()}
        self.lens_windows[new].set_name(new)
        self._refresh_lens_list()
        return True

    def delete_lens(self, name: str) -> None:
        win = self.lens_windows.pop(name, None)
        if win is not None:
            win.close()
            self._refresh_lens_list()

    # ----------------------------------------------------- lens visibility
    def toggle_lens_visibility(self) -> None:
        self._set_lenses_hidden(not self.visibility.manually_hidden)

    def _set_lenses_hidden(self, hidden: bool) -> None:
        self.visibility.set_manually_hidden(hidden)
        name = "eye-closed" if hidden else "eye"
        self.btn_eye.set_icons(load_icon(self, name), load_icon(self, name, "fg"))

    def _on_hide_option_change(self) -> None:
        self.visibility.hide_while_measuring = self.hide_var.get()

    def _on_settle_change(self, *_args) -> None:
        try:
            self.visibility.settle_ms = max(0, int(self.settle_var.get()))
        except ValueError:
            pass   # ignore half-typed values

    def _lens_snapshot(self) -> dict:
        """name -> Lens backend objects, captured on the GUI thread."""
        return {name: win.lens for name, win in self.lens_windows.items()}

    # ------------------------------------------------------------ execution
    def _source(self) -> str:
        return self.editor.get("1.0", "end-1c")

    def _interval_ms(self) -> int:
        try:
            return max(50, int(self.interval_var.get()))
        except ValueError:
            return 500

    def run_once(self) -> None:
        if self._continuous:
            return
        self.executor.reset_namespace()
        if not self.executor.run(self._source(), self._lens_snapshot()):
            self._append_console("[a script is still running - press Stop to abort it]\n", "info")
        self._sync_run_buttons()

    def toggle_run(self) -> None:
        """Run Continuous / Stop toggle. Stop also aborts a long Run Once script."""
        if self._continuous or self.executor.is_running:
            self.stop_all()
        else:
            self.start_continuous()

    def start_continuous(self) -> None:
        if self._continuous:
            return
        self._continuous = True
        self.executor.reset_namespace()   # state persists across ticks from here on
        self._sync_run_buttons()
        self._tick()

    def _sync_run_buttons(self) -> None:
        """Toggle shows Stop while anything runs; Run Once is disabled meanwhile."""
        running = self._continuous or self.executor.is_running
        if running == self._run_state:
            return
        self._run_state = running
        self.btn_cont.configure(text="■  Stop" if running else "⟳  Run Continuous")
        self.btn_once.configure(state="disabled" if running else "normal")

    def _tick(self) -> None:
        if not self._continuous:
            return
        # If the previous run is still going, this tick is simply skipped.
        self.executor.run(self._source(), self._lens_snapshot())
        self._tick_job = self.after(self._interval_ms(), self._tick)

    def _stop_continuous(self) -> None:
        self._continuous = False
        if self._tick_job is not None:
            self.after_cancel(self._tick_job)
            self._tick_job = None
        self._sync_run_buttons()

    def stop_all(self) -> None:
        self._stop_continuous()
        self.executor.stop()

    # ------------------------------------------------------ save / load
    def _update_file_label(self) -> None:
        name = os.path.basename(self.current_path) if self.current_path else "untitled"
        self.file_var.set(name)
        self.title(f"{name} - ScreenLens")

    def save_project(self, as_new: bool = False) -> None:
        """Save script + lens setup to a .json project file."""
        path = self.current_path
        if as_new or not path:
            path = filedialog.asksaveasfilename(
                title="Save project", defaultextension=".json",
                initialfile=os.path.basename(path) if path else "screenlens_project.json",
                filetypes=[("ScreenLens project", "*.json")])
            if not path:
                return
        try:
            save_project(
                path, self._source(),
                [win.to_dict() for win in self.lens_windows.values()],
                {"interval_ms": self._interval_ms(),
                 "settle_ms": self.visibility.settle_ms,
                 "hide_while_measuring": bool(self.hide_var.get())})
        except OSError as exc:
            messagebox.showerror("Save failed", f"Could not write {path}:\n{exc}")
            return
        self.current_path = path
        self.editor.edit_modified(False)
        self._update_file_label()
        self._append_console(f"[saved {path} - {len(self.lens_windows)} lens(es)]\n", "info")

    def load_project(self) -> None:
        """Load a project (script + lenses) or a plain .py script (script only)."""
        if (self.editor.edit_modified() or self.lens_windows) and not messagebox.askyesno(
                "Load", "Loading replaces the current script and lenses. Continue?"):
            return
        path = filedialog.askopenfilename(title="Load project", filetypes=PROJECT_TYPES + [
            ("All files", "*.*")])
        if not path:
            return

        if path.lower().endswith(".py"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    script = f.read()
            except (OSError, UnicodeDecodeError) as exc:
                messagebox.showerror("Load failed", f"Could not read {path}:\n{exc}")
                return
            self._set_script(script)
            self.current_path = None   # a .py is not a project; Save asks for a new file
            self._update_file_label()
            self._append_console(f"[loaded script {path} - lenses unchanged]\n", "info")
            return

        try:
            project = load_project(path)
        except ProjectError as exc:
            messagebox.showerror("Load failed", str(exc))
            return

        self.stop_all()
        self._replace_lenses(project["lenses"])
        self._apply_settings(project["settings"])
        self._set_script(project["script"])
        self.current_path = path
        self._update_file_label()
        self._append_console(
            f"[loaded {path} - {len(project['lenses'])} lens(es) created]\n", "info")

    def _set_script(self, script: str) -> None:
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", script)
        self.editor.edit_reset()
        self.editor.edit_modified(False)
        self.executor.reset_namespace()

    def _apply_settings(self, settings: dict) -> None:
        interval, settle = settings.get("interval_ms"), settings.get("settle_ms")
        if isinstance(interval, int) and not isinstance(interval, bool):
            self.interval_var.set(str(max(50, interval)))
        if isinstance(settle, int) and not isinstance(settle, bool):
            self.settle_var.set(str(max(0, settle)))
        if isinstance(settings.get("hide_while_measuring"), bool):
            self.hide_var.set(settings["hide_while_measuring"])
            self._on_hide_option_change()

    def _replace_lenses(self, specs: list) -> None:
        """Close every lens and recreate them from saved specs."""
        for win in list(self.lens_windows.values()):
            win.close()
        self.lens_windows = {}
        self._set_lenses_hidden(False)
        screen = _virtual_screen()
        moved = []
        for i, spec in enumerate(specs):
            left, top, width, height = spec["left"], spec["top"], spec["width"], spec["height"]
            if screen and not self._on_screen(left, top, width, height, screen):
                # Saved on a monitor that is not connected now: bring it back into view.
                left, top = screen[0] + 240 + 40 * (i % 8), screen[1] + 180 + 40 * (i % 8)
                moved.append(spec["name"])
            self._create_lens(spec["name"], spec["color"], left, top, width, height)
        self._color_index = len(specs)
        self._refresh_lens_list()
        if moved:
            self._append_console(
                "[moved onto the visible screen (saved monitor not found): "
                + ", ".join(moved) + "]\n", "info")

    @staticmethod
    def _on_screen(left, top, width, height, screen) -> bool:
        """True if at least a 40x20 px corner of the lens is inside the screen area."""
        sl, st, sw, sh = screen
        overlap_w = min(left + width, sl + sw) - max(left, sl)
        overlap_h = min(top + height, st + sh) - max(top, st)
        return overlap_w >= 40 and overlap_h >= 20

    def _on_close(self) -> None:
        self.stop_all()
        self.executor.restore_redirect()
        for win in list(self.lens_windows.values()):
            win.close()
        self.destroy()