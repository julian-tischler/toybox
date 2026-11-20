"""
icons.py - Loads the toolbar/sidebar icons as Tk images.

Tk 8.6 cannot read SVG, so the SVG sources in assets/icons/svg/ are rendered
ahead of time to PNG files by tools/render_icons.py, one file per icon, colour
and size:  assets/icons/<name>-<color>-<size>.png

At runtime only tk.PhotoImage is needed (no extra packages). The size closest
to the screen's DPI scaling is picked automatically.
"""

import os
import tkinter as tk
from typing import Dict, Tuple

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")

# Colour keys -> hex. Must match the theme in gui_ide.py; re-run
# tools/render_icons.py after changing them.
ICON_COLORS = {"fg": "#d7dae0", "muted": "#8b919c", "error": "#ff6b6b"}
# icon name -> colour keys rendered for it
ICONS = {
    "eye": ("muted", "fg"),
    "eye-closed": ("muted", "fg"),
    "plus-circle": ("muted", "fg"),
    "xmark-circle": ("muted", "error"),
}
BASE_SIZE = 16                          # logical px at 100 % scaling
SIZES = (16, 20, 24, 28, 32)            # 100 % ... 200 %

_cache: Dict[Tuple[str, str, int], tk.PhotoImage] = {}


def icon_size(widget: tk.Misc) -> int:
    """Rendered size closest to BASE_SIZE at the current DPI."""
    scale = widget.winfo_fpixels("1i") / 96.0
    want = BASE_SIZE * scale
    return min(SIZES, key=lambda s: abs(s - want))


def load_icon(widget: tk.Misc, name: str, color: str = "muted") -> tk.PhotoImage:
    """PhotoImage for an icon. Images are cached (Tk drops images nobody references)."""
    size = icon_size(widget)
    key = (name, color, size)
    if key not in _cache:
        path = os.path.join(ICON_DIR, f"{name}-{color}-{size}.png")
        _cache[key] = tk.PhotoImage(master=widget, file=path)
    return _cache[key]
