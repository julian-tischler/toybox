# Toybox

**A modular workspace of small tools you can script.** Arrange panels — screen lenses, Python
scripts, and more tools to come — in any layout you like, then write short scripts that read
from them. Toybox grew out of *ScreenLens* (tag `v1.0`), whose transparent OCR lenses are now
one tool among several.

```python
v = Lenses["voltage"].get_float()
i = Lenses["current"].get_float()
if v and i:
    print(f"Power: {v * i} W")
```

---

## Features

- **Modular workspace**: every space holds one tool. Double-click a divider (between two
  panels) or a window-edge line to open a new space there and pick a tool for it. Split
  panels in any direction, drag a panel by its header to dock it next to another panel or
  along a window edge, or drop it in the middle of another panel to swap the two.
- **Multiple instances**: several Script panels can run side by side, each with its own editor,
  console, interval and variables.
- **Scripts are one-way and predictable**: a script runs only when you press *Run* (or
  `Ctrl+Enter`). It can read and write tools (lenses, notes, …); nothing in the workspace
  triggers it. A line like `! Lenses["lens1"].get_text()` is shorthand for `print(...)`.
- **Plots**: line, scatter, bar and histogram plots drawn entirely by scripts
  (`Plots["plot1"].line(x, y)`), including live logging with `append`. Zoom and pan with the
  mouse; the panel handles colours, grid, legend, crosshair and saving (PNG / CSV).
- **Notes**: write in Markdown or plain text, preview it rendered, open/save `.md` / `.txt`
  files, and read or replace a note from scripts as `Notes["note1"]`.
- **Lenses**: borderless, see-through windows that stay on top. Scripts read them as
  `Lenses["name"]` (text, numbers, average colour, raw pixels, colour masks). Lenses briefly
  become invisible during each capture, so they never appear in the pixels.
- **Code editor**: line numbers, Python highlighting, auto-closing brackets and quotes, smart
  indentation, comment toggle, line move/duplicate/cut, word jumps.
- **Projects and layouts**: save everything (layout, panel contents, lenses, preferences) as a
  project, or save just the arrangement of panels as a reusable layout. The last workspace is
  restored automatically on the next start.
- **OCR tuned for small readouts**: upscaling, Otsu binarisation or grey normalisation,
  character whitelists/blacklists, colour masking, locale-aware number parsing.

## Requirements

- Python 3.9+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed on the system
- Python packages: `PySide6`, `pyqtgraph`, `mss`, `opencv-python`, `numpy`, `pytesseract`

Windows is the main target (lens capture uses physical-pixel window positions there). Other
platforms work with lens positions scaled from Qt's logical coordinates.

## Installation

```bash
pip install -r requirements.txt
```

Install Tesseract (Windows builds: [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki)).
Toybox looks for the executable in this order:

1. the `TESSERACT_CMD` environment variable
2. `tesseract` on `PATH`
3. `C:\Program Files\Tesseract-OCR\tesseract.exe` and `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`

## Running

From the project folder:

```bash
python -m toybox
```

On Windows, `toybox.bat` starts it from the project's `.venv` without a console window.

## Using the workspace

| Do this | To |
|---|---|
| Double-click a **divider** between panels | Open a new empty space there |
| Double-click a **window-edge line** (left, right, top, bottom) | Open a new space along that edge |
| Click a tool in an empty space | Fill it (Lenses, Note, Plot, Script) |
| Drag a panel's **header** onto another panel | Dock it on that side (drop near an edge) or swap the two (drop in the middle) |
| Drag a panel's header onto a **window-edge line** | Dock it along that whole edge |
| Drag a divider | Resize |
| Double-click a panel's **name** | Rename it (scripts use the name, e.g. `Lenses`, later `Plots["name"]`) |
| Panel **⋯** menu | Split right/left/below/above, change tool, rename, tool actions (e.g. import/export `.py`) |
| Panel **✕** | Close it (asks first if it has content) |

**Menus**

- **File**: New / Open / Save / Save As project (`Ctrl+N` / `Ctrl+O` / `Ctrl+S` / `Ctrl+Shift+S`),
  Preferences (`Ctrl+,`).
- **Workspace**: add a panel at an edge, save / load / reset the layout.
- **Lenses**: add a lens (`Ctrl+L`), hide or show all lenses (`Ctrl+H`).

**Preferences**: *Hide lenses while measuring*, the *Settle* delay after hiding, and the default
run interval for new Script panels.

### Lenses panel

Type a name and press **+** (or Enter) to create a lens, then drag it over the region to read
by its coloured header and resize it from its edges. Each row shows the lens colour; double-click
a name to rename it, ✕ deletes it. The eye icon in the header hides or shows all lenses. Lenses
belong to the whole app: several Lenses panels show the same list, and scripts can read lenses
even when no Lenses panel is open.

### Script panel

An editor, a run bar and its own console. *Run Once* (`Ctrl+Enter`) runs the script with fresh
variables. *Run Continuous* repeats it every *Every* ms and keeps variables between runs; while
anything runs, the button becomes *Stop*, which also aborts a long *Run Once*.

A line whose first non-blank character is `!` prints the value of the rest of the line — it is
shorthand for `print(...)`, so it takes anything `print` takes:

```python
! "Starting measurement"              # -> print("Starting measurement")
! Lenses["lens1"].get_text()          # prints the text the lens read
for i in range(3):
    ! f"run {i}: {v:.2f} V", "ok"     # indentation is kept, so it works in blocks
```

A lone `!` prints an empty line, and a `# comment` at the end stays a comment. `!` lines inside
triple-quoted strings are left alone, and line numbers in tracebacks stay correct.

### Note panel

Write in the editor; the **Preview** button in the header renders the note as Markdown
(headings, lists, task lists `- [ ]`, tables, **bold**, `code`, links). Double-click the
preview (or press **Edit**) to go back to the text. Plain text works too — it is shown as is.
The ⋯ menu has **Open file…**, **Save** and **Save as…** for `.md` / `.txt` files; the line
under the note shows its file, with `•` when it has unsaved changes. Notes are named `note1`,
`note2`, … (double-click the name to rename) and their text is saved in projects.

### Plot panel

A plot is drawn by scripts (see `Plots` below); the panel controls how you look at it:

- **Mouse**: wheel to zoom, drag to pan, drag an axis to zoom just that axis; right-click for
  more view options (mouse mode, manual ranges, log scale per axis).
- **Auto** (header): fit the view to the data again. While you haven't zoomed, the view follows
  the data automatically; after you zoom or pan, it stays where you put it until you press Auto.
- **Save** (header): the plot as a PNG image, or its data as CSV (`series, kind, x, y, label`).
- **Zero lines**: subtle lines at x = 0 and y = 0. By default (*auto*) they are shown when the
  plot has a line or scatter series and hidden for pure bar / histogram plots; the ⋯ menu can
  switch them to *always* or *off*. They never stretch the automatic zoom range.
- **⋯ menu**: show/hide grid, legend and crosshair (shows the x/y under the mouse below the
  plot), zero lines, colour palette (Toybox, Colorblind, Pastel), clear the plot.

Plotted data is not stored in projects (use Save); the view settings above are.

### Editor shortcuts

| Keys | Action |
|---|---|
| `Ctrl+Enter` | Run Once (this panel) |
| `( [ { " '` | Auto-close; type the closer to step over it; Backspace deletes an empty pair; typed over a selection, wraps it |
| `Enter` | Keeps the indentation, adds a level after `:` or an open bracket |
| `Tab` / `Shift+Tab` | Indent / dedent the selected lines (`Tab` with no selection goes to the next 4-column stop) |
| `Ctrl+#` | Toggle `# ` comment on the current or selected lines |
| `Alt+Up` / `Alt+Down` | Move the current or selected lines up / down |
| `Ctrl+D` | Duplicate the current or selected lines |
| `Ctrl+X` | With no selection: cut the whole current line (`Ctrl+V` pastes it back as a line above the cursor) |
| `Shift+Left` / `Shift+Right` | Jump to the start / end of the word, across line ends (`Ctrl+Shift+Left/Right` still selects by word) |

## Script API

Each script runs with `exec()` on its own worker thread. These names are available in its globals:

### `Lenses`

A dict that maps lens names to `Lens` objects. An unknown name raises a `KeyError` that lists
the available lenses.

| Method / property | Returns | Description |
|---|---|---|
| `lens.region` | `(left, top, width, height)` | Current capture area in absolute screen pixels |
| `lens.get_raw()` | `numpy.ndarray` (H×W×3, BGR) | Raw pixels, ready for your own OpenCV processing |
| `lens.get_text(...)` | `str` | OCR text from the region |
| `lens.get_float(...)` | `float` or `None` | First number found in the OCR text |
| `lens.get_color_avg()` | `(R, G, B)` | Average colour of the region |
| `lens.color_mask(color, ...)` | `Lens` | New lens that only sees pixels of one colour (see below) |
| `lens.channel("r" \| "g" \| "b")` | `Lens` | New lens that sees one RGB channel as greyscale |

#### `get_text(psm=6, whitelist=None, preprocess="binary", target_height=60, blur=0, oem=None, blacklist=None)`

| Parameter | Meaning |
|---|---|
| `psm` | Tesseract page-segmentation mode: `6` uniform block, `7` single line, `8` single word, `13` raw line |
| `whitelist` | Only these characters can be recognised (a preset or any string) |
| `blacklist` | These characters are never output, e.g. `"Oo"` or `"\|lI"` |
| `preprocess` | `"binary"` (Otsu threshold, default), `"gray"` (keeps anti-aliasing, helps thin strokes), `"none"`/`False` (raw pixels) |
| `target_height` | Crops smaller than this (in px) are upscaled toward it, at most 8× |
| `blur` | Gaussian kernel size applied before thresholding (`0` = off) |
| `oem` | Tesseract engine mode, e.g. `1` = LSTM only |

#### `get_float(psm=7, whitelist=FLOAT, decimal="auto", blacklist=None, **ocr_options)`

Runs OCR on a single line and parses the first number. `decimal="auto"` works like this:

- both `,` and `.` present → the one that comes last is the decimal mark
- one separator used once → it is the decimal mark (`"90,1"` → `90.1`)
- one separator used more than once → it is digit grouping (`"1,234,567"` → `1234567`)

Pass `decimal="."` or `decimal=","` to choose the decimal mark yourself.

#### `color_mask(color, tolerance=None, invert=False, keep_color=False)`

Returns a **new lens** over the same region; the original stays unchanged, and the new one
follows it when you move or resize it. Before OCR, pixels that match the colour become black
and everything else becomes white.

```python
# One lens over "HELLO WORLD": HELLO is green, WORLD is white.
green_lens = Lenses["lens1"].color_mask("green")
print(green_lens.get_text())                     # HELLO
print(Lenses["lens1"].color_mask("white").get_text())   # WORLD
```

| Parameter | Meaning |
|---|---|
| `color` | A name: `red`, `orange`, `yellow`, `green`, `cyan`, `blue`, `purple`/`violet`, `magenta`/`pink`, `white`, `gray`/`grey`, `black`. Or an exact colour: `"#00ff66"` or `(R, G, B)` |
| `tolerance` | Named colours: widens the hue range (white/gray/black: the brightness range) by this many units. Exact colours: maximum RGB distance (default `60`) |
| `invert` | Keep everything *except* this colour |
| `keep_color` | Keep the matching pixels' original colour instead of making them black |

Named colours are matched by hue in HSV and need some saturation, so white or grey pixels never
count as "green". Chained masks combine with AND, and each colour test runs on the original
pixels. For example, `lens.color_mask("green", invert=True).color_mask("white")` keeps white
pixels that are not green.

`channel("g")` keeps only one channel. It helps when text and background differ mainly in one
channel. White contains every channel, though, so use `color_mask` to separate coloured text
from white text.

### `Notes`

A dict that maps Note panel names to note handles (only notes that are open in the workspace).

| Method | Description |
|---|---|
| `Notes["note1"].get_text()` | The note's text (its Markdown source) as a `str` |
| `Notes["note1"].set_text(new_text)` | Replace the note's text (one `Ctrl+Z` in the note undoes it); a shown preview updates too |

```python
log = Notes["log"]
log.set_text(log.get_text() + f"\n- {Lenses['voltage'].get_float()} V")
```

Using a note after its panel was closed raises a clear `RuntimeError`.

### `Plots`

A dict that maps Plot panel names to plot handles. Every series has a **name**: plotting the
same name again replaces that series in place (ideal for *Run Continuous*); calls without
`name=` add a new series (`line1`, `bar1`, …). Colours come from the panel's palette unless you
pass `color=` (a name like `"red"`, `"#ff8800"` or `(255, 136, 0)`).

| Method | Description |
|---|---|
| `line(x, y=None, name=None, color=None, width=2, style="-")` | Line through the points; `line(y)` uses x = 0, 1, 2, …; `style` `"-"`, `"--"`, `":"`, `"-."` |
| `scatter(x, y=None, name=None, color=None, size=7, symbol="o")` | Points; `symbol` `"o"`, `"s"`, `"t"`, `"d"`, `"+"`, `"x"`, `"*"` |
| `bar(x, heights=None, name=None, color=None, width=0.8)` | Bars; `x` may be numbers or labels (`bar(["mon", "tue"], [3, 5])`); `bar(heights)` puts them at 0, 1, 2, … |
| `hist(values, bins=20, name=None, color=None, range=None)` | Histogram; `bins` is a count or a list of bin edges |
| `append(name, y, x=None, color=None, max_points=None)` | Add one point to a line series (created if new). Without `x`, x is the **seconds since the plot's first appended point** (the first point is 0). `max_points` keeps only the newest points |
| `remove(name)` / `clear()` | Remove one series / all series (`clear` also restarts the `append` clock at 0) |
| `title(text)`, `xlabel(text)`, `ylabel(text)` | Labels (stay after `clear()`); an empty text removes them |
| `xlim(low, high)`, `ylim(low, high)` | Fix an axis range; `xlim()` with no arguments makes it automatic again |

```python
# Run Continuous: log a lens reading every interval (x = 0, 0.5, 1.0, ... s)
p = Plots["plot1"]
if "started" not in globals():
    p.clear()
    p.title("Supply voltage"); p.ylabel("V")
    started = True
p.append("voltage", Lenses["voltage"].get_float() or 0, max_points=600)
```

Data is checked in the script (wrong lengths or unknown colours raise a clear error there) and
drawn in batches, so even `for` loops with thousands of `append` calls stay smooth. Using a plot
after its panel was closed raises a clear `RuntimeError`.

### Whitelist presets

Plain strings that you can combine, e.g. `ALPHANUM + "-_"` or `NUMERIC + "%"`:

`NUMERIC` · `INTEGER` · `FLOAT` · `ALPHA` · `ALPHA_LOWER` · `ALPHA_UPPER` · `ALPHANUM` ·
`ALPHANUM_LOWER` · `ALPHANUM_UPPER` · `HEX` · `PUNCTUATION` · `PRINTABLE`

### Example: change detector

```python
# Runs continuously; `last` persists between runs.
status = Lenses["status"].get_text(psm=7, whitelist=ALPHA_UPPER)
if status != globals().get("last"):
    print("Status changed:", status)
    last = status
```

## File formats

**Project** (`*.toybox.json`) — everything:

```json
{
  "format": "toybox-project",
  "version": 1,
  "layout": {"type": "split", "orientation": "h", "sizes": [260, 900], "children": [
    {"type": "panel", "kind": "lenses", "name": "lenses1", "state": {}},
    {"type": "panel", "kind": "script", "name": "script1",
     "state": {"source": "print('hi')\n", "interval_ms": 500}}
  ]},
  "lenses": [
    {"name": "voltage", "color": "#00ff66", "left": 240, "top": 180, "width": 220, "height": 90}
  ],
  "settings": {"hide_while_measuring": true, "settle_ms": 50, "interval_ms": 500}
}
```

**Layout** (`*.layout.json`) — the same `layout` tree without panel contents, under
`"format": "toybox-layout"`.

A layout node is either a split (`orientation` `"h"` or `"v"`, `sizes`, `children`) or a
panel (`kind`, `name`, `state`). Saves are atomic. ScreenLens v1 project files still open: they
become a Lenses | Script layout holding the old script, lenses and settings.

The last workspace is kept in `session.toybox.json` in the app-data folder
(`%APPDATA%\Toybox\Toybox` on Windows) and restored on start.

## Environment variables

| Variable | Purpose |
|---|---|
| `TESSERACT_CMD` | Full path to the `tesseract` executable |
| `TESSDATA_DIR` | Alternative model folder, e.g. one with the more accurate `tessdata_best` models (pair with `oem=1`) |
| `OCR_CONFIG_DIR` | Folder with a plain ASCII path, no spaces, used for temporary Tesseract config files when a whitelist/blacklist contains non-ASCII characters |

## Project structure

```
toybox/
├── __main__.py          Entry point: dependency check, Qt app, theme, main window
├── core/                No widgets (except the Qt lens windows); usable on its own
│   ├── vision.py        Capture (mss), colour masking + preprocessing (OpenCV), OCR, number parsing, Lens API
│   ├── lenses.py        LensWindow (transparent overlay) + LensManager (registry, hide-while-measuring)
│   ├── executor.py      Script runner: worker thread per script, per-thread print() routing, stop
│   ├── bridge.py        gui_call(): run a function on the GUI thread from a script thread
│   ├── project_io.py    Project / layout files (validation, atomic save, v1 import)
│   └── script_syntax.py "! expr" print shorthand
├── editor/
│   ├── helpers.py       Editing rules as pure string functions (testable without a display)
│   └── code_editor.py   QPlainTextEdit + line numbers + Python highlighting + the rules
├── panels/              One module per tool
│   ├── base.py          Panel contract + registry
│   ├── lenses_panel.py
│   ├── note_panel.py
│   ├── plot_panel.py
│   └── script_panel.py
├── ui/
│   ├── main_window.py   Menus, projects, layouts, preferences, session restore
│   ├── workspace.py     Split tree, dividers, edge lines, drag & drop, picker, (de)serialisation
│   ├── context.py       AppContext (lenses, preferences, workspace) + script namespace
│   ├── theme.py · icons.py · widgets.py · preferences.py
└── assets/icons/        SVG icons (recoloured at runtime)
```

### Adding a tool

Subclass `Panel` in a new module under `toybox/panels/`, give it a `kind` and `title`, decorate
it with `@register`, and import the module in `panels/__init__.py`. Implement `state()` /
`load_state()` to have its contents saved in projects. It then appears in every empty space's
picker and in each panel's *Change tool* menu.

To make a tool readable from scripts, return a global name from `script_collection()` (e.g.
`"Plots"`) and an object from `script_handle()`. Scripts then get `Plots["panel name"]`.
Scripts run on worker threads, so anything a handle does with widgets must go through
`core.bridge.gui_call`.

### Design notes

- **Threads**: every script runs on its own worker thread; Qt widgets are only touched on the
  GUI thread. `print()` is routed by thread to the right panel's console.
- **Lens capture**: a capture asks the GUI thread (through the bridge) to make all lenses
  transparent, waits *Settle* ms for the compositor, grabs the pixels, and shows the lenses
  again 80 ms after the last capture, so reading several lenses in a row doesn't flicker. Lens
  regions are kept as plain physical-pixel integers that scripts read without touching Qt.
- **Stopping**: *Stop* raises an exception inside the script's thread at the next Python
  bytecode; a script blocked in a long C call (e.g. a slow OCR) stops once that call returns.
- **Workspace tree**: a split with one child is replaced by that child, and a split nested in a
  split of the same orientation is merged into it, so the layout stays tidy however panels move.

## Tips for better OCR

- Make the lens fit the text tightly, and use one lens per value.
- For single-line numbers, try `psm=7`, then `13`, then `8`.
- If the lens covers text in several colours, isolate one with `color_mask(...)`.
- If thin glyphs are misread (slashed zeros, `1` vs `l`), try `preprocess="gray"`, a small
  `blur=3`, or a `blacklist`.
- Use `tessdata_best` models (`TESSDATA_DIR`) together with `oem=1` for the best accuracy.
