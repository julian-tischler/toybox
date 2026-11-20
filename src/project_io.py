"""
project_io.py - Save/load of a project: the script plus the lens setup.

A project is one JSON file:

    {
      "format": "screen-lens-project",
      "version": 1,
      "script": "...python source...",
      "lenses": [{"name": "voltage", "color": "#00ff66",
                  "left": 240, "top": 180, "width": 220, "height": 90}, ...],
      "settings": {"interval_ms": 500, "settle_ms": 50, "hide_while_measuring": true}
    }

`left`/`top`/`width`/`height` are the geometry of the whole lens window in
absolute screen pixels. No Tk code here, so it can be tested on its own.
"""

import json
import os
import tempfile
from typing import Any, Dict, List

FORMAT = "screen-lens-project"
LEGACY_FORMATS = ("screen-automator-project",)  # still readable
VERSION = 1
DEFAULT_COLOR = "#00ff66"


class ProjectError(Exception):
    """The file is not a valid project (message is safe to show to the user)."""


def save_project(path: str, script: str, lenses: List[Dict[str, Any]],
                 settings: Dict[str, Any]) -> None:
    """Write a project atomically, so a crash never leaves a half-written file."""
    data = {"format": FORMAT, "version": VERSION, "script": script,
            "lenses": lenses, "settings": settings}
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".screenlens_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _int(value: Any, field: str, lens_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProjectError(f"Lens {lens_name!r}: {field!r} must be a number.")
    return int(round(value))


def load_project(path: str) -> Dict[str, Any]:
    """Read and validate a project file. Returns {"script", "lenses", "settings"}."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, UnicodeDecodeError) as exc:
        raise ProjectError(f"Cannot read file: {exc}") from None
    except json.JSONDecodeError as exc:
        raise ProjectError(f"Not a valid project file (invalid JSON: {exc}).") from None

    if not isinstance(data, dict) or data.get("format") not in (FORMAT, *LEGACY_FORMATS):
        raise ProjectError("This file is not a ScreenLens project.")
    version = data.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise ProjectError(f"Unsupported project version {version!r} (this app reads up to {VERSION}).")

    script = data.get("script", "")
    if not isinstance(script, str):
        raise ProjectError("'script' must be text.")

    raw_lenses = data.get("lenses", [])
    if not isinstance(raw_lenses, list):
        raise ProjectError("'lenses' must be a list.")
    lenses, seen = [], set()
    for entry in raw_lenses:
        if not isinstance(entry, dict):
            raise ProjectError("Each lens must be an object.")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ProjectError("Every lens needs a non-empty name.")
        name = name.strip()
        if name in seen:
            raise ProjectError(f"Two lenses are both named {name!r}.")
        seen.add(name)
        color = entry.get("color", DEFAULT_COLOR)
        lenses.append({
            "name": name,
            "color": color if isinstance(color, str) and color else DEFAULT_COLOR,
            "left": _int(entry.get("left", 240), "left", name),
            "top": _int(entry.get("top", 180), "top", name),
            "width": _int(entry.get("width", 220), "width", name),
            "height": _int(entry.get("height", 90), "height", name),
        })

    raw_settings = data.get("settings", {})
    settings = raw_settings if isinstance(raw_settings, dict) else {}
    return {"script": script, "lenses": lenses, "settings": settings}