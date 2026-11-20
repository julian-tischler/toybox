"""
vision.py - Backend extraction logic (mss + OpenCV + numpy + pytesseract).

The GUI never implements capture/OCR itself; it only hands a "region provider"
(a callable returning absolute screen coordinates) to a `Lens` object. All of
the extraction methods a user script may call live on `Lens`.

Everything here uses plain Python values only (no Tk objects), so Lens methods
are safe to call from the script worker thread.
"""

import atexit
import hashlib
import os
import re
import shlex
import shutil
import string
import sys
import tempfile
from typing import Callable, ContextManager, Optional, Tuple, Union

import cv2
import mss
import numpy as np
import pytesseract

Region = Tuple[int, int, int, int]  # (left, top, width, height) in screen pixels


# --------------------------------------------------------------------------
# Whitelist presets (also injected into every user script by name)
# --------------------------------------------------------------------------
# Plain strings, so they combine freely:  ALPHANUM + "-_"   or   NUMERIC + "%"
NUMERIC = string.digits                                   # 0-9
INTEGER = string.digits + "+-"                            # 0-9 + sign
FLOAT = string.digits + ".,+-"                            # numbers with decimal marks
ALPHA_LOWER = string.ascii_lowercase                      # a-z
ALPHA_UPPER = string.ascii_uppercase                      # A-Z
ALPHA = ALPHA_LOWER + ALPHA_UPPER                         # a-z A-Z
ALPHANUM_LOWER = ALPHA_LOWER + NUMERIC                    # a-z 0-9
ALPHANUM_UPPER = ALPHA_UPPER + NUMERIC                    # A-Z 0-9
ALPHANUM = ALPHA + NUMERIC                                # a-z A-Z 0-9
HEX = string.hexdigits                                    # 0-9 a-f A-F
# Punctuation without quote characters and backslash, which break Tesseract's
# command-line parsing.
PUNCTUATION = "".join(c for c in string.punctuation if c not in "\"'\\")
PRINTABLE = ALPHANUM + PUNCTUATION                        # letters, digits, punctuation

WHITELIST_PRESETS = {
    "NUMERIC": NUMERIC, "INTEGER": INTEGER, "FLOAT": FLOAT,
    "ALPHA": ALPHA, "ALPHA_LOWER": ALPHA_LOWER, "ALPHA_UPPER": ALPHA_UPPER,
    "ALPHANUM": ALPHANUM, "ALPHANUM_LOWER": ALPHANUM_LOWER, "ALPHANUM_UPPER": ALPHANUM_UPPER,
    "HEX": HEX, "PUNCTUATION": PUNCTUATION, "PRINTABLE": PRINTABLE,
}


# --------------------------------------------------------------------------
# Tesseract discovery
# --------------------------------------------------------------------------
def _configure_tesseract() -> None:
    """Locate tesseract: $TESSERACT_CMD, PATH, then common Windows paths.

    $TESSDATA_DIR (optional) points Tesseract at a different model folder, e.g.
    one holding the more accurate `tessdata_best` eng.traineddata.
    """
    cmd = os.environ.get("TESSERACT_CMD")
    if not cmd and not shutil.which("tesseract"):
        for candidate in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if os.path.exists(candidate):
                cmd = candidate
                break
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    if os.environ.get("TESSDATA_DIR"):
        os.environ["TESSDATA_PREFIX"] = os.environ["TESSDATA_DIR"]


_configure_tesseract()


# --------------------------------------------------------------------------
# Low-level helpers
# --------------------------------------------------------------------------
def capture_region(region: Region) -> np.ndarray:
    """Grab a screen region and return it as a BGR uint8 numpy array (OpenCV order)."""
    left, top, width, height = (int(v) for v in region)
    if width <= 0 or height <= 0:
        raise ValueError(f"Lens region has no area: {width}x{height}")
    # A fresh mss instance per grab keeps this safe across threads on every OS.
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
    return np.ascontiguousarray(np.asarray(shot)[:, :, :3])  # BGRA -> BGR


# Tesseract's recogniser works best with characters roughly 30+ px tall. For a
# single-line crop, text is ~60% of the crop height, so aim for crops ~60 px tall.
OCR_TARGET_HEIGHT = 60
OCR_MAX_SCALE = 8.0

PREPROCESS_MODES = ("binary", "gray", "none")


def _normalize_mode(preprocess: Union[bool, str, None]) -> str:
    if preprocess is True:
        return "binary"
    if preprocess is False or preprocess is None:
        return "none"
    if preprocess in PREPROCESS_MODES:
        return preprocess
    raise ValueError(f"preprocess must be True, False or one of {PREPROCESS_MODES}, got {preprocess!r}")


def preprocess_for_ocr(image: np.ndarray, mode: str = "binary",
                       target_height: int = OCR_TARGET_HEIGHT, blur: int = 0) -> np.ndarray:
    """Prepare a BGR crop for Tesseract.

    Steps: grayscale -> upscale small crops to `target_height` (cubic, capped at
    OCR_MAX_SCALE) -> optional Gaussian blur -> mode-specific finishing:

    "binary": Otsu threshold, dark text on white, white padding (crisp, default).
    "gray":   no hard threshold; keeps anti-aliasing, normalises contrast and
              puts dark text on a light background. Often kinder to thin strokes
              such as the slash in a slashed zero.
    "none":   skip all of this and hand Tesseract the raw pixels.

    blur: Gaussian kernel size in px (0 = off). A small value (3-5) can soften or
          erase hairline strokes before thresholding; too much merges digits.
    """
    mode = _normalize_mode(mode)
    if mode == "none":
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height = gray.shape[0]
    if height < target_height:
        scale = min(OCR_MAX_SCALE, target_height / height)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    if blur and blur > 0:
        k = int(blur) | 1  # kernel size must be odd
        gray = cv2.GaussianBlur(gray, (k, k), 0)

    if mode == "binary":
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if bw.mean() < 127:  # mostly black => light text on dark background; invert
            bw = cv2.bitwise_not(bw)
        return cv2.copyMakeBorder(bw, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)

    # mode == "gray"
    if gray.mean() < 127:
        gray = cv2.bitwise_not(gray)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    return cv2.copyMakeBorder(gray, 10, 10, 10, 10, cv2.BORDER_REPLICATE)


# --------------------------------------------------------------------------
# Tesseract parameters containing non-ASCII characters
# --------------------------------------------------------------------------
# `-c name=value` goes through the command line, which Tesseract on Windows
# decodes in the ANSI code page, so a character like "®" arrives mangled and the
# whole whitelist/blacklist is silently ignored. Config files are read as raw
# UTF-8, so non-ASCII values are delivered through a small temporary config file.
_PARAM_DIR: Optional[str] = None


def _is_plain(path: str) -> bool:
    """ASCII, no whitespace or quotes - survives pytesseract's argument splitting."""
    return path.isascii() and not any(c.isspace() or c in "\"'" for c in path)


def _short_path(path: str) -> str:
    """Windows 8.3 short form of an existing path (no spaces / non-ASCII), else unchanged."""
    if sys.platform != "win32":
        return path
    import ctypes
    buf = ctypes.create_unicode_buffer(32768)
    return buf.value if ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf)) else path


def _make_param_dir() -> str:
    """Create a private temp folder whose path is safe to hand to Tesseract."""
    candidates = [os.environ.get("OCR_CONFIG_DIR"), tempfile.gettempdir(),
                  os.environ.get("PUBLIC"), os.environ.get("ProgramData")]
    for base in filter(None, candidates):
        try:
            folder = tempfile.mkdtemp(prefix="screenlens_tess_", dir=base)
        except OSError:
            continue
        path = folder if _is_plain(folder) else _short_path(folder)
        if _is_plain(path):
            atexit.register(shutil.rmtree, folder, True)
            return path
        shutil.rmtree(folder, ignore_errors=True)
    raise RuntimeError(
        "Cannot create a temp folder with a plain ASCII path (no spaces) for Tesseract "
        "parameters containing non-ASCII characters. Set the OCR_CONFIG_DIR environment "
        "variable to such a folder, e.g. C:\\ocr_tmp, or use ASCII-only whitelist/blacklist.")


def _param_config_file(params: dict) -> str:
    """Write {tesseract_param: value} to a UTF-8 config file and return its path."""
    global _PARAM_DIR
    if _PARAM_DIR is None:
        _PARAM_DIR = _make_param_dir()
    content = "".join(f"{key} {value}\n" for key, value in sorted(params.items()))
    name = "p_" + hashlib.sha1(content.encode("utf-8")).hexdigest()[:12] + ".cfg"
    path = os.path.join(_PARAM_DIR, name)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8", newline="\n") as f:   # UTF-8, no BOM
            f.write(content)
    return path


def _build_config(psm: int, oem: Optional[int], whitelist: Optional[str],
                  blacklist: Optional[str]) -> str:
    config = f"--psm {psm}"
    if oem is not None:
        config += f" --oem {oem}"
    file_params = {}
    for key, value in (("tessedit_char_whitelist", whitelist),
                       ("tessedit_char_blacklist", blacklist)):
        if not value:
            continue
        if value.isascii():
            config += f" -c {key}={value}"
        else:
            file_params[key] = value
    if file_params:
        path = _param_config_file(file_params)
        config += " " + (path if sys.platform == "win32" else shlex.quote(path))
    return config


def ocr_text(image: np.ndarray, psm: int = 6, whitelist: Optional[str] = None,
             preprocess: Union[bool, str, None] = "binary",
             target_height: int = OCR_TARGET_HEIGHT, blur: int = 0,
             oem: Optional[int] = None, blacklist: Optional[str] = None) -> str:
    """Run pytesseract.image_to_string() on an image and return stripped text."""
    img = preprocess_for_ocr(image, _normalize_mode(preprocess), target_height, blur)
    config = _build_config(psm, oem, whitelist, blacklist)
    try:
        return pytesseract.image_to_string(img, config=config).strip()
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract OCR executable not found. Install it and either add it to "
            "PATH or set the TESSERACT_CMD environment variable to its full path."
        ) from None


# --------------------------------------------------------------------------
# Number parsing
# --------------------------------------------------------------------------
# A number token: optional sign, digits that may contain . or , separators, or a
# bare ".5" / ",5". Trailing separators ("90,") are not part of the token.
_NUMBER_RE = re.compile(r"[-+]?(?:\d[\d.,]*\d|\d|[.,]\d+)")


def _normalize_number(token: str, decimal: str) -> Optional[float]:
    sign = ""
    if token[0] in "+-":
        sign, token = token[0], token[1:]

    if decimal in (".", ","):
        # Caller says which character is the decimal mark; the other one is grouping.
        other = "," if decimal == "." else "."
        token = token.replace(other, "").replace(decimal, ".")
    else:  # auto
        last_dot, last_comma = token.rfind("."), token.rfind(",")
        if last_dot >= 0 and last_comma >= 0:
            # Both present: whichever comes last is the decimal mark ("1.234,5" / "1,234.5").
            dec = "." if last_dot > last_comma else ","
            grouping = "," if dec == "." else "."
            token = token.replace(grouping, "").replace(dec, ".")
        else:
            sep = "." if last_dot >= 0 else ("," if last_comma >= 0 else None)
            if sep:
                if token.count(sep) > 1:
                    token = token.replace(sep, "")     # "1,234,567" -> grouping
                else:
                    token = token.replace(sep, ".")    # single mark -> decimal ("90,1", "1,234")
    try:
        return float(sign + token)
    except ValueError:
        return None


def extract_float(text: str, decimal: str = "auto") -> Optional[float]:
    """Return the first number in `text` as a float, or None.

    decimal="auto" (default) rules:
      * "," and "." both present  -> the last one is the decimal mark
      * one separator, used once  -> it is the decimal mark ("90,1" -> 90.1,
                                     "1,234" -> 1.234)
      * one separator, repeated   -> grouping ("1,234,567" -> 1234567)
    decimal="." or decimal="," forces which character is the decimal mark and
    treats the other as thousands grouping.
    """
    if decimal not in ("auto", ".", ","):
        raise ValueError('decimal must be "auto", "." or ","')
    for match in _NUMBER_RE.finditer(text):
        value = _normalize_number(match.group(), decimal)
        if value is not None:
            return value
    return None


# --------------------------------------------------------------------------
# Colour masking / channel selection (image -> image transforms)
# --------------------------------------------------------------------------
# Named colours are ranges in OpenCV HSV space (H 0-179, S and V 0-255).
# Chromatic colours: (hue_lo, hue_hi) with a minimum saturation and brightness,
# so white/grey pixels never count as "green". Ranges may wrap (red).
_MIN_SAT = 70
_MIN_VAL = 60
NAMED_HUES = {
    "red": (170, 10), "orange": (11, 22), "yellow": (23, 34), "green": (35, 85),
    "cyan": (86, 100), "blue": (101, 130), "purple": (131, 150), "magenta": (151, 169),
}
NAMED_HUES["pink"] = NAMED_HUES["magenta"]
NAMED_HUES["violet"] = NAMED_HUES["purple"]
# Achromatic colours: (max_saturation, val_lo, val_hi)
NAMED_NEUTRALS = {"white": (50, 170, 255), "gray": (50, 61, 169), "black": (255, 0, 60)}
NAMED_NEUTRALS["grey"] = NAMED_NEUTRALS["gray"]
NAMED_COLORS = tuple(sorted({**NAMED_HUES, **NAMED_NEUTRALS}))

ColorSpec = Union[str, Tuple[int, int, int]]
MaskFn = Callable[[np.ndarray], np.ndarray]  # BGR image -> bool H x W


def _parse_rgb(color) -> Optional[Tuple[int, int, int]]:
    """'#rrggbb' / '#rgb' / (r, g, b) -> (r, g, b); None if `color` is not such a value."""
    if isinstance(color, str) and color.startswith("#"):
        h = color[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            try:
                return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                pass
        raise ValueError(f"Bad hex colour {color!r}; use '#rrggbb'.")
    if isinstance(color, (tuple, list)) and len(color) == 3:
        return tuple(int(c) for c in color)
    return None


def color_mask_array(image: np.ndarray, color: ColorSpec,
                     tolerance: Optional[int] = None) -> np.ndarray:
    """Boolean H x W array: True where a BGR pixel matches `color`.

    color: a name from NAMED_COLORS ("green", "red", "white", ...), a hex string
           "#00ff66", or an (R, G, B) tuple.
    tolerance:
      * named chromatic colour: widens the hue range by this many OpenCV hue
        units on each side (1 unit = 2 degrees; default 0).
      * named neutral (white/gray/black): widens the brightness range (default 0).
      * exact colour (hex / RGB): max Euclidean RGB distance (default 60).
    """
    rgb = _parse_rgb(color)
    if rgb is not None:
        tol = 60 if tolerance is None else tolerance
        target = np.array(rgb[::-1], dtype=np.int32)  # BGR
        dist2 = ((image.astype(np.int32) - target) ** 2).sum(axis=2)
        return dist2 <= tol * tol

    if not isinstance(color, str):
        raise TypeError(f"color must be a name, '#rrggbb' or (R, G, B), got {color!r}")
    key = color.strip().lower()
    tol = tolerance or 0
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0].astype(np.int32), hsv[..., 1], hsv[..., 2]

    if key in NAMED_HUES:
        lo, hi = NAMED_HUES[key]
        lo, hi = (lo - tol) % 180, (hi + tol) % 180
        in_hue = (h >= lo) & (h <= hi) if lo <= hi else (h >= lo) | (h <= hi)
        return in_hue & (s >= _MIN_SAT) & (v >= _MIN_VAL)
    if key in NAMED_NEUTRALS:
        max_s, v_lo, v_hi = NAMED_NEUTRALS[key]
        return (s <= max_s) & (v >= max(0, v_lo - tol)) & (v <= min(255, v_hi + tol))
    raise ValueError(f"Unknown colour {color!r}. Use one of {', '.join(NAMED_COLORS)}, "
                     "a hex string like '#00ff66' or an (R, G, B) tuple.")


def _mask_predicate(color: ColorSpec, tolerance: Optional[int], invert: bool) -> MaskFn:
    color_mask_array(np.zeros((1, 1, 3), np.uint8), color, tolerance)  # validate eagerly

    def predicate(image: np.ndarray) -> np.ndarray:
        mask = color_mask_array(image, color, tolerance)
        return ~mask if invert else mask
    return predicate


_CHANNELS = {"b": 0, "blue": 0, "g": 1, "green": 1, "r": 2, "red": 2}


def _channel_index(name: str) -> int:
    try:
        return _CHANNELS[name.strip().lower()]
    except (KeyError, AttributeError):
        raise ValueError(f"channel must be 'r', 'g' or 'b', got {name!r}") from None


# --------------------------------------------------------------------------
# The object exposed to user scripts
# --------------------------------------------------------------------------
class Lens:
    """User-facing handle for one screen region. Exposed as Lenses["name"]."""

    def __init__(self, name: str, region_provider: Callable[[], Region],
                 capture_guard: Optional[Callable[[], ContextManager]] = None,
                 masks: Tuple[MaskFn, ...] = (), channel: Optional[int] = None,
                 keep_color: bool = False):
        self.name = name
        self._region_provider = region_provider
        # Optional context-manager factory the GUI supplies so lenses can hide
        # themselves while pixels are grabbed. vision.py knows nothing about Tk.
        self._capture_guard = capture_guard
        # Preprocessing set up by color_mask() / channel(). Every mask is tested
        # against the ORIGINAL pixels and the results are AND-ed, so chained
        # masks narrow the selection instead of re-masking a black/white image.
        self._masks = tuple(masks)
        self._channel = channel
        self._keep_color = keep_color

    @property
    def region(self) -> Region:
        """Current absolute (left, top, width, height) of the capture area."""
        return tuple(self._region_provider())

    def capture(self) -> np.ndarray:
        """Grab the pixels under the lens (BGR numpy array), then apply masks/channel.

        Every get_* method goes through here, so the GUI's hide-while-measuring
        guard wraps each individual capture.
        """
        region = self.region
        if self._capture_guard is None:
            image = capture_region(region)
        else:
            with self._capture_guard():
                image = capture_region(region)
        return self._apply_preprocessing(image)

    def _apply_preprocessing(self, image: np.ndarray) -> np.ndarray:
        base = image
        if self._channel is not None:
            base = cv2.cvtColor(np.ascontiguousarray(image[..., self._channel]),
                                cv2.COLOR_GRAY2BGR)
        if not self._masks:
            return base
        selected = np.ones(image.shape[:2], dtype=bool)
        for mask_fn in self._masks:
            selected &= mask_fn(image)
        out = np.full_like(base, 255)                 # unselected pixels become white
        out[selected] = base[selected] if self._keep_color else 0
        return out

    # ------------------------------------------------------- derived lenses
    def _derive(self, label: str, masks=None, channel=None, keep_color=None) -> "Lens":
        return Lens(f"{self.name}|{label}", self._region_provider, self._capture_guard,
                    masks=self._masks + tuple(masks or ()),
                    channel=self._channel if channel is None else channel,
                    keep_color=self._keep_color if keep_color is None else keep_color)

    def color_mask(self, color: ColorSpec, tolerance: Optional[int] = None,
                   invert: bool = False, keep_color: bool = False) -> "Lens":
        """Return a new lens over the same region that only "sees" one colour.

        Matching pixels become black, everything else white - ideal input for
        get_text()/get_float(). The original lens is unchanged, and the new one
        follows it when it is moved or resized. Chained calls combine (AND):
        each colour test runs on the original pixels.

            green = Lenses["lens1"].color_mask("green")
            text = green.get_text()

        color: "red", "orange", "yellow", "green", "cyan", "blue", "purple",
               "magenta"/"pink", "white", "gray"/"grey", "black"; or an exact
               colour as "#00ff66" or (R, G, B).
        tolerance: for names, widens the hue (or, for white/gray/black, the
               brightness) range; for exact colours, the max RGB distance
               (default 60). See color_mask_array.
        invert: keep everything EXCEPT this colour (e.g. drop green, read the rest).
        keep_color: keep the matching pixels' original colour (or the selected
               channel()) instead of black. Unmatched pixels are always white.
        """
        label = f"mask:{'!' if invert else ''}{color}"
        return self._derive(label, masks=[_mask_predicate(color, tolerance, invert)],
                            keep_color=keep_color)

    def channel(self, name: str) -> "Lens":
        """Return a new lens that sees only one colour channel ("r", "g" or "b") as grey.

        Useful when text differs mainly in one channel (e.g. red text on a blue
        background). Note that white contains every channel, so to separate green
        text from white text use color_mask("green") instead.
        """
        return self._derive(f"channel:{name}", channel=_channel_index(name))

    def get_raw(self) -> np.ndarray:
        """OpenCV/numpy array (H x W x 3, BGR) of the bounding box.

        On a lens made by color_mask()/channel() this is the preprocessed image.
        """
        return self.capture()

    def get_text(self, psm: int = 6, whitelist: Optional[str] = None,
                 preprocess: Union[bool, str, None] = "binary",
                 target_height: int = OCR_TARGET_HEIGHT, blur: int = 0,
                 oem: Optional[int] = None, blacklist: Optional[str] = None) -> str:
        """OCR the region and return the text.

        psm: page-segmentation mode (6 = uniform block, 7 = single line,
             8 = single word, 13 = raw line). Controls layout analysis only.
        whitelist: restrict recognised characters. Use a preset (NUMERIC, ALPHA,
             ALPHANUM, ... - see WHITELIST_PRESETS) or your own string, e.g.
             ALPHANUM + "-_".
        blacklist: characters Tesseract must never output, e.g. "Oo" or "|lI".
             Can be combined with whitelist. Non-ASCII characters such as "\u00ae" are
             supported. Avoid spaces and quote characters.
        preprocess: "binary" (default, Otsu threshold), "gray" (no threshold,
             keeps anti-aliasing), or "none"/False (raw pixels). True = "binary".
        target_height: small crops are upscaled to about this height in px.
        blur: Gaussian blur kernel size before thresholding (0 = off).
        oem: Tesseract engine mode (1 = LSTM only). Pair with a tessdata_best
             model via the TESSDATA_DIR environment variable for accuracy.
        """
        return ocr_text(self.capture(), psm=psm, whitelist=whitelist, preprocess=preprocess,
                        target_height=target_height, blur=blur, oem=oem, blacklist=blacklist)

    def get_float(self, psm: int = 7, whitelist: Optional[str] = FLOAT,
                  decimal: str = "auto", blacklist: Optional[str] = None,
                  **ocr_options) -> Optional[float]:
        """OCR the region and return the first number found as a float (or None).

        Defaults to psm=7 (single text line). Try psm=13 or psm=8 if a readout
        misreads, or psm=6 for multi-line lenses.
        decimal: "auto" (see extract_float), or "." / "," to force the decimal mark.
        blacklist: characters Tesseract must never output (see get_text).
        ocr_options: forwarded to get_text (preprocess, target_height, blur, oem).
        """
        text = self.get_text(psm=psm, whitelist=whitelist, blacklist=blacklist, **ocr_options)
        return extract_float(text, decimal=decimal)

    def get_color_avg(self) -> Tuple[int, int, int]:
        """Average colour of the region as an (R, G, B) tuple of ints."""
        bgr = self.capture().reshape(-1, 3).mean(axis=0)
        return (int(round(bgr[2])), int(round(bgr[1])), int(round(bgr[0])))

    def __repr__(self) -> str:
        return f"<Lens {self.name!r} region={self.region}>"