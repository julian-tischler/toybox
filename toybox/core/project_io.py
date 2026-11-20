"""
project_io.py - Save/load of projects and workspace layouts (no GUI code).

Project (everything, *.toybox.json):

    {
      "format": "toybox-project", "version": 1,
      "layout":   <layout node>,                 # panels incl. their contents
      "lenses":   [{"name", "color", "left", "top", "width", "height"}, ...],
      "settings": {"settle_ms": 50, "hide_while_measuring": true, ...}
    }

Layout (structure only, *.layout.json): {"format": "toybox-layout", "version": 1,
"layout": <layout node>} - the same tree with every panel's "state" removed.

Layout node: either
    {"type": "split", "orientation": "h" | "v", "sizes": [int, ...], "children": [node, ...]}
    {"type": "panel", "kind": "script", "name": "script1", "state": {...}}

ScreenLens v1 projects ("screen-lens-project" / "screen-automator-project") still
load: they become a Lenses | Script layout holding the old script.
"""

import json
import os
import tempfile
from typing import Any, Dict, List

FORMAT = "toybox-project"
LAYOUT_FORMAT = "toybox-layout"
VERSION = 1
LEGACY_FORMATS = ("screen-lens-project", "screen-automator-project")
DEFAULT_COLOR = "#00ff66"


class ProjectError(Exception):
    """The file is not valid (message is safe to show to the user)."""


# --------------------------------------------------------------------- files
def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    """Write JSON atomically, so a crash never leaves a half-written file."""
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".toybox_", suffix=".tmp", dir=folder)
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


def _read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, UnicodeDecodeError) as exc:
        raise ProjectError(f"Cannot read file: {exc}") from None
    except json.JSONDecodeError as exc:
        raise ProjectError(f"Not a valid file (invalid JSON: {exc}).") from None


# ------------------------------------------------------------- validation
def _int(value: Any, field: str, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProjectError(f"{where}: {field!r} must be a number.")
    return int(round(value))


def validate_layout(node: Any, path: str = "layout") -> Dict[str, Any]:
    """Return a cleaned copy of a layout node, or raise ProjectError."""
    if not isinstance(node, dict):
        raise ProjectError(f"{path}: must be an object.")
    kind = node.get("type")
    if kind == "panel":
        panel_kind, name = node.get("kind"), node.get("name", "")
        if not isinstance(panel_kind, str) or not panel_kind:
            raise ProjectError(f"{path}: panel needs a 'kind'.")
        state = node.get("state", {})
        return {"type": "panel", "kind": panel_kind,
                "name": name if isinstance(name, str) else "",
                "state": state if isinstance(state, dict) else {}}
    if kind == "split":
        orientation = node.get("orientation")
        if orientation not in ("h", "v"):
            raise ProjectError(f"{path}: orientation must be 'h' or 'v'.")
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise ProjectError(f"{path}: a split needs children.")
        sizes = node.get("sizes", [])
        if not (isinstance(sizes, list) and len(sizes) == len(children)
                and all(isinstance(s, (int, float)) and not isinstance(s, bool) for s in sizes)):
            sizes = [1] * len(children)
        return {"type": "split", "orientation": orientation, "sizes": [int(s) for s in sizes],
                "children": [validate_layout(c, f"{path}.children[{i}]")
                             for i, c in enumerate(children)]}
    raise ProjectError(f"{path}: unknown node type {kind!r}.")


def _validate_lenses(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        raise ProjectError("'lenses' must be a list.")
    lenses, seen = [], set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ProjectError("Each lens must be an object.")
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ProjectError("Every lens needs a non-empty name.")
        name = name.strip()
        if name in seen:
            raise ProjectError(f"Two lenses are both named {name!r}.")
        seen.add(name)
        where = f"Lens {name!r}"
        color = entry.get("color", DEFAULT_COLOR)
        lenses.append({
            "name": name,
            "color": color if isinstance(color, str) and color else DEFAULT_COLOR,
            "left": _int(entry.get("left", 240), "left", where),
            "top": _int(entry.get("top", 180), "top", where),
            "width": _int(entry.get("width", 220), "width", where),
            "height": _int(entry.get("height", 90), "height", where),
        })
    return lenses


def strip_states(node: Dict[str, Any]) -> Dict[str, Any]:
    """Layout copy without panel contents (for layout files)."""
    if node["type"] == "panel":
        return {"type": "panel", "kind": node["kind"], "name": node.get("name", ""), "state": {}}
    return {**node, "children": [strip_states(c) for c in node["children"]]}


# ----------------------------------------------------------------- projects
def save_project(path: str, layout: Dict[str, Any], lenses: List[Dict[str, Any]],
                 settings: Dict[str, Any]) -> None:
    _write_json_atomic(path, {"format": FORMAT, "version": VERSION, "layout": layout,
                              "lenses": lenses, "settings": settings})


def load_project(path: str) -> Dict[str, Any]:
    """Read and validate a project. Returns {"layout", "lenses", "settings"}."""
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ProjectError("This file is not a Toybox project.")
    fmt = data.get("format")
    if fmt in LEGACY_FORMATS:
        return _convert_screenlens(data)
    if fmt != FORMAT:
        raise ProjectError("This file is not a Toybox project.")
    version = data.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise ProjectError(f"Unsupported project version {version!r} (this app reads up to {VERSION}).")
    settings = data.get("settings", {})
    return {"layout": validate_layout(data.get("layout")),
            "lenses": _validate_lenses(data.get("lenses", [])),
            "settings": settings if isinstance(settings, dict) else {}}


def _convert_screenlens(data: Dict[str, Any]) -> Dict[str, Any]:
    script = data.get("script", "")
    if not isinstance(script, str):
        raise ProjectError("'script' must be text.")
    settings = data.get("settings", {})
    settings = settings if isinstance(settings, dict) else {}
    interval = settings.get("interval_ms", 500)
    layout = {"type": "split", "orientation": "h", "sizes": [250, 850], "children": [
        {"type": "panel", "kind": "lenses", "name": "lenses", "state": {}},
        {"type": "panel", "kind": "script", "name": "script1",
         "state": {"source": script, "interval_ms": interval}},
    ]}
    return {"layout": layout, "lenses": _validate_lenses(data.get("lenses", [])),
            "settings": settings}


# ------------------------------------------------------------------ layouts
def save_layout(path: str, layout: Dict[str, Any]) -> None:
    _write_json_atomic(path, {"format": LAYOUT_FORMAT, "version": VERSION,
                              "layout": strip_states(layout)})


def load_layout(path: str) -> Dict[str, Any]:
    data = _read_json(path)
    if not isinstance(data, dict) or data.get("format") != LAYOUT_FORMAT:
        raise ProjectError("This file is not a Toybox layout.")
    return validate_layout(data.get("layout"))
