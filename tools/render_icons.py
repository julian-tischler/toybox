"""
render_icons.py - Render src/assets/icons/svg/*.svg to the themed PNGs the GUI loads.

Only needed when an icon, a colour or a size changes (the PNGs are part of the
project). Requires Pillow:  pip install pillow

    python tools/render_icons.py

Supports the subset of SVG these stroke icons use: <path d="..."> with the
commands M L H V C Z (absolute or relative), stroke-width, round caps/joins.
Drawing is done at 8x and downsampled for anti-aliasing.
"""

import os
import re
import sys
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from icons import ICON_COLORS, ICON_DIR, ICONS, SIZES  # noqa: E402

SVG_DIR = os.path.join(ICON_DIR, "svg")
SUPERSAMPLE = 8
CURVE_STEPS = 24
_TOKEN = re.compile(r"[MLHVCZmlhvcz]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?")


def parse_path(d: str):
    """Path data -> list of (points, closed) polylines in SVG user units."""
    tokens = _TOKEN.findall(d)
    subpaths, pts, closed = [], [], False
    x = y = sx = sy = 0.0
    i, cmd = 0, None

    def num():
        nonlocal i
        i += 1
        return float(tokens[i - 1])

    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
        rel = cmd.islower()
        c = cmd.upper()
        if c == "Z":
            if pts:
                subpaths.append((pts, True))
            pts, x, y = [], sx, sy
            continue
        if c == "M":
            if pts:
                subpaths.append((pts, closed))
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            sx, sy, pts = x, y, [(x, y)]
            cmd = "l" if rel else "L"   # further pairs are implicit line-tos
        elif c == "L":
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            pts.append((x, y))
        elif c == "H":
            nx = num()
            x = x + nx if rel else nx
            pts.append((x, y))
        elif c == "V":
            ny = num()
            y = y + ny if rel else ny
            pts.append((x, y))
        elif c == "C":
            p = [num() for _ in range(6)]
            if rel:
                p = [p[k] + (x if k % 2 == 0 else y) for k in range(6)]
            x0, y0 = x, y
            for s in range(1, CURVE_STEPS + 1):
                t = s / CURVE_STEPS
                mt = 1 - t
                px = mt**3 * x0 + 3 * mt * mt * t * p[0] + 3 * mt * t * t * p[2] + t**3 * p[4]
                py = mt**3 * y0 + 3 * mt * mt * t * p[1] + 3 * mt * t * t * p[3] + t**3 * p[5]
                pts.append((px, py))
            x, y = p[4], p[5]
        else:
            raise ValueError(f"Unsupported path command {cmd!r}")
    if pts:
        subpaths.append((pts, closed))
    return subpaths


def render(svg_path: str, size: int, color: str) -> Image.Image:
    root = ET.parse(svg_path).getroot()
    vb = [float(v) for v in root.get("viewBox", "0 0 24 24").split()]
    big = size * SUPERSAMPLE
    scale = big / vb[2]
    mask = Image.new("L", (big, big), 0)
    draw = ImageDraw.Draw(mask)
    for el in root.iter():
        if not el.tag.endswith("path"):
            continue
        width = float(el.get("stroke-width", "1")) * scale
        for pts, closed in parse_path(el.get("d", "")):
            xy = [((px - vb[0]) * scale, (py - vb[1]) * scale) for px, py in pts]
            if closed:
                xy.append(xy[0])
            if len(xy) > 1:
                draw.line(xy, fill=255, width=max(1, round(width)), joint="curve")
            r = width / 2
            for cx, cy in ((xy[0], xy[-1]) if not closed else ()):
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)   # round caps
    mask = mask.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), color)
    out.putalpha(mask)
    return out


def main() -> None:
    count = 0
    for name, colors in ICONS.items():
        svg = os.path.join(SVG_DIR, f"{name}.svg")
        for color_key in colors:
            for size in SIZES:
                img = render(svg, size, ICON_COLORS[color_key])
                img.save(os.path.join(ICON_DIR, f"{name}-{color_key}-{size}.png"))
                count += 1
    print(f"wrote {count} PNGs to {ICON_DIR}")


if __name__ == "__main__":
    main()
