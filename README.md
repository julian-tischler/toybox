# ScreenLens

**Programmable screen reading with OCR.** Put transparent "lenses" over parts of your
screen, then write small Python scripts that read them as text, numbers or colours using OCR.
You can run a script once or in a loop.

Typical uses: logging values from a GUI that has no API (instrument software, dashboards,
games, legacy tools), computing derived values live, or reacting when something on screen changes.

```python
v = Lenses["voltage"].get_float()
i = Lenses["current"].get_float()
if v and i:
    print(f"Power: {v * i} W")
```

---

## Features

- **Input lenses**: borderless, see-through windows that stay on top. Drag one by its coloured
  header and resize it from its edges. The capture area is only the see-through inside, so a
  lens never captures its own frame.
- **Built-in mini IDE**: script editor, console, and a lens sidebar where each lens shows its
  colour, can be renamed by double-clicking its name, and deleted with its ✕ icon. The panels
  are separated by divider lines that light up on hover: drag one to resize, or double-click it
  to collapse or restore the sidebar / console. A collapsed panel keeps its divider at the
  window edge, so you can double-click it again to bring the panel back.
  Dark theme, with a dark title bar on Windows 10/11.
- **Run modes**: *Run Once* (`Ctrl+Enter`) or *Run Continuous* at a set interval (minimum 50 ms).
  While anything runs, the *Run Continuous* button turns into *Stop*, which also aborts a long
  *Run Once* script.
- **Persistent namespace**: variables survive between runs, so continuous scripts can keep
  counters, previous values and similar state.
- **Hide while measuring**: lenses briefly become invisible during each capture so they never
  show up in the pixels. The *Settle* delay gives the compositor time to repaint first.
- **OCR tuned for small readouts**: upscaling, Otsu binarisation or grey normalisation,
  optional blur, character whitelists/blacklists (non-ASCII characters work too), and number
  parsing that understands locales (`1.234,5`, `1,234.5`, `90,1`).
- **Colour masking**: `color_mask("green")` returns a lens that only sees one colour, so you can
  read green text next to white text. `channel("g")` keeps a single RGB channel.
- **Projects**: save and load the script, the lens layout and the settings as one JSON file.
  You can also load a plain `.py` file to replace only the script.

## Requirements

- Python 3.8+ with Tkinter (included in the standard Windows/macOS installers)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed on the system
- Python packages: `mss`, `opencv-python`, `numpy`, `pytesseract`

Supported platforms: **Windows** is the main target (true colour-key transparency, DPI
awareness). macOS uses native window transparency. On other platforms lenses fall back to a
translucent window, and its tint may slightly affect captures.

## Installation

```bash
pip install -r requirements.txt
```

Install Tesseract (Windows builds: [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki)).
ScreenLens looks for the executable in this order:

1. the `TESSERACT_CMD` environment variable
2. `tesseract` on `PATH`
3. `C:\Program Files\Tesseract-OCR\tesseract.exe` and `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`

## Running

```bash
cd src
python main.py
```

`main.py` turns on DPI awareness on Windows, so Tk and the screen capture use the same
physical pixels. It also checks for the required packages and tells you what is missing.

## Workflow

1. Type a name in the **Input Lenses** sidebar and click the **+** icon (or press Enter).
2. Drag the lens over the region you want to read and resize it to fit. The eye icon in the
   sidebar header hides or shows all lenses.
3. Write a script that uses `Lenses["name"]`.
4. Press **Run Once** or **Run Continuous** (bottom right of the script panel). `print()` output
   and tracebacks appear in the console.
5. **Save** (`Ctrl+S`), **Save As** (`Ctrl+Shift+S`) or **Load** (`Ctrl+O`) a project; the
   buttons sit at the bottom left of the script panel.

**Preferences** (top left) opens a strip with the run interval, *Hide while measuring* and the
*Settle* delay.

### Editor shortcuts

| Keys | Action |
|---|---|
| `Ctrl+Enter` | Run Once |
| `( [ { " '` | Auto-close; type the closer to step over it; Backspace deletes an empty pair; typed over a selection, wraps it |
| `Enter` | Keeps the indentation, adds a level after `:` or an open bracket |
| `Tab` / `Shift+Tab` | Indent / dedent the selected lines (`Tab` with no selection goes to the next 4-column stop) |
| `Ctrl+#` | Toggle `# ` comment on the current or selected lines |
| `Alt+Up` / `Alt+Down` | Move the current or selected lines up / down |
| `Ctrl+D` | Duplicate the current or selected lines |
| `Ctrl+X` | With no selection: cut the whole current line (`Ctrl+V` pastes it back as a line above the cursor) |
| `Shift+Left` / `Shift+Right` | Jump to the start / end of the word, across line ends (`Ctrl+Shift+Left/Right` still selects by word) |
| `Ctrl+S` / `Ctrl+Shift+S` / `Ctrl+O` | Save / Save As / Load |

## Script API

Each script runs with `exec()` on a worker thread. These names are available in its globals:

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

## Project file format

```json
{
  "format": "screen-lens-project",
  "version": 1,
  "script": "...python source...",
  "lenses": [
    {"name": "voltage", "color": "#00ff66", "left": 240, "top": 180, "width": 220, "height": 90}
  ],
  "settings": {"interval_ms": 500, "settle_ms": 50, "hide_while_measuring": true}
}
```

Lens geometry is the whole lens window in absolute screen pixels. Files saved before the rename
(`"format": "screen-automator-project"`) still load. Saves are atomic (written to
a temp file, then swapped in). On load the file is validated, and lenses that would end up
off-screen are put back in view.

## Environment variables

| Variable | Purpose |
|---|---|
| `TESSERACT_CMD` | Full path to the `tesseract` executable |
| `TESSDATA_DIR` | Alternative model folder, e.g. one with the more accurate `tessdata_best` models (pair with `oem=1`) |
| `OCR_CONFIG_DIR` | Folder with a plain ASCII path, no spaces, used for temporary Tesseract config files when a whitelist/blacklist contains non-ASCII characters |

## Project structure

```
src/
├── main.py         Entry point: DPI awareness, dependency check, starts the GUI
├── gui_ide.py      Main window: preferences, lens sidebar, editor + run bar, console, theme, save/load
├── editor_helpers.py  Editor shortcuts (auto-close, smart Enter, indent, comment, move/duplicate)
├── icons.py        Loads the UI icons as Tk images (picks the size for the screen's DPI)
├── assets/icons/   Pre-rendered icon PNGs; svg/ holds the SVG sources
├── gui_lens.py     LensWindow (transparent overlay) and LensVisibility (hide-during-capture)
├── vision.py       Capture (mss), colour masking + preprocessing (OpenCV), OCR (pytesseract), number parsing, Lens API
├── executor.py     Runs scripts on a thread, redirects stdout/stderr, stop, trimmed tracebacks
└── project_io.py   Saving and validating project JSON (no Tk, testable on its own)
tools/
└── render_icons.py Renders assets/icons/svg/*.svg to the themed PNGs (needs Pillow)
```

Tk 8.6 cannot display SVG, so the icons are shipped as PNGs in two colours and five sizes
(100–200 % scaling). After changing an SVG, a theme colour in `icons.py` or the sizes, run:

```bash
pip install pillow
```

```bash
python tools/render_icons.py
```

### Design notes

- **Thread safety**: scripts run on a worker thread, and Tk is only touched from the GUI thread.
  Script output goes through a queue that the GUI reads every 30 ms. Hide requests from
  `capture_guard` are posted to the GUI thread and picked up by a 5 ms poll.
- **No flicker**: after a capture, lenses stay hidden for a short time (`linger_ms`, 80 ms), so
  reading several lenses in a row doesn't make them blink.
- **Stopping**: *Stop* raises an exception inside the worker thread, which takes effect at the
  next Python bytecode. A script blocked in a long C call (for example a slow Tesseract run)
  stops once that call returns.
- **Hide method**: `CAPTURE_HIDE_METHOD` in `gui_lens.py` can be `"alpha"` (default) or
  `"withdraw"`. If lenses still show up in captures, try the other one.

## Tips for better OCR

- Make the lens fit the text tightly, and use one lens per value.
- For single-line numbers, try `psm=7`, then `13`, then `8`.
- If the lens covers text in several colours, isolate one with `color_mask(...)`.
- If thin glyphs are misread (slashed zeros, `1` vs `l`), try `preprocess="gray"`, a small
  `blur=3`, or a `blacklist`.
- Use `tessdata_best` models (`TESSDATA_DIR`) together with `oem=1` for the best accuracy.
