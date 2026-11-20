"""
helpers.py - Editing rules for the script editor, as pure functions on strings.

They have no GUI code, so they can be tested without a display; code_editor.py
wires them to the Qt editor widget. Shortcuts they implement:
---------
Typing ( [ { " '     auto-close, type the closer to step over it, Backspace removes an
                     empty pair, and typing an opener over a selection wraps it
Enter                keeps the indentation; adds one level after ':' or an open
                     bracket; Enter between () [] {} opens an indented block
Tab / Shift+Tab      indent / dedent the selected lines (Tab with no selection moves
                     to the next 4-column stop; Shift+Tab dedents the current line)
Ctrl+#               toggle "# " comment on the current line / selected lines
Alt+Up / Alt+Down    move the current line / selected lines up or down
Ctrl+D               duplicate the current line / selected lines
Ctrl+X               with no selection: cut the whole current line (Ctrl+V then
                     pastes it back as a whole line above the cursor's line)
Shift+Left / Right   jump to the start / end of the word (crosses line ends);
                     Ctrl+Shift+Left / Right keep the default select-by-word
Ctrl+Enter           run the script (handled by the Script panel)
"""

import re
from typing import List, Optional, Tuple

INDENT_WIDTH = 4
INDENT = " " * INDENT_WIDTH
QUOTES = "\"'"
PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
CLOSERS = ")]}" + QUOTES
# Auto-close only when the next character is one of these (or end of line), so
# typing "(" in front of an existing word does not leave a stray ")".
_AUTOCLOSE_BEFORE = " \t;:.,=}])>"
_STRING_PREFIX = re.compile(r"(?<![A-Za-z0-9_])[rRbBuUfF]{1,2}$")


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------
def _scan(s: str) -> Tuple[Optional[str], int]:
    """Walk one line. Returns (open string delimiter or None, index of a '#' comment or -1)."""
    quote: Optional[str] = None
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if quote is None:
            if c == "#":
                return None, i
            if c in QUOTES:
                quote = c * 3 if s.startswith(c * 3, i) else c
                i += len(quote)
                continue
            i += 1
        else:
            if c == "\\":
                i += 2
                continue
            if s.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
            i += 1
    return quote, -1


def scan_state(s: str) -> Tuple[Optional[str], bool]:
    """(open string delimiter, inside a comment) at the end of `s`. One line only."""
    quote, comment = _scan(s)
    return quote, comment >= 0


def strip_comment(s: str) -> str:
    """`s` without a trailing '# comment' (a '#' inside a string is kept)."""
    _, idx = _scan(s)
    return s if idx < 0 else s[:idx]


def shift_col(col: int, old: str, new: str) -> int:
    """Where a cursor column ends up when line `old` was edited into `new`.

    Works for a single insertion or removal, such as indenting or commenting.
    """
    delta = len(new) - len(old)
    if delta == 0:
        return col
    prefix = 0
    for a, b in zip(old, new):
        if a != b:
            break
        prefix += 1
    if delta > 0:
        return col + delta if col >= prefix else col
    return max(prefix, col + delta) if col > prefix else col


def toggle_comment(lines: List[str]) -> List[str]:
    """Comment the lines, or uncomment them if every non-blank line is a comment."""
    nonblank = [i for i, l in enumerate(lines) if l.strip()]
    if not nonblank:                      # only blank lines: start a comment here
        return [l + "# " for l in lines]
    out = list(lines)
    if all(lines[i].lstrip().startswith("#") for i in nonblank):
        for i in nonblank:
            line = lines[i]
            k = len(line) - len(line.lstrip())
            rest = line[k + 1:]
            out[i] = line[:k] + (rest[1:] if rest.startswith(" ") else rest)
        return out
    col = min(len(lines[i]) - len(lines[i].lstrip()) for i in nonblank)
    for i in nonblank:
        out[i] = lines[i][:col] + "# " + lines[i][col:]
    return out


def indent_lines(lines: List[str]) -> List[str]:
    return [INDENT + l if l.strip() else l for l in lines]


def dedent_lines(lines: List[str]) -> List[str]:
    out = []
    for l in lines:
        if l.startswith("\t"):
            out.append(l[1:])
        else:
            spaces = len(l) - len(l.lstrip(" "))
            out.append(l[min(INDENT_WIDTH, spaces):])
    return out


def move_block(lines: List[str], first: int, last: int, direction: int):
    """Swap lines[first..last] (0-based, inclusive) with the line above/below.

    Returns (lo, hi, new_lines_for_lo..hi, new_first, new_last) or None if the
    block is already at the edge.
    """
    block = lines[first:last + 1]
    if direction < 0:
        if first == 0:
            return None
        return first - 1, last, block + [lines[first - 1]], first - 1, last - 1
    if last >= len(lines) - 1:
        return None
    return first, last + 1, [lines[last + 1]] + block, first + 1, last + 1


def _char_class(c: str) -> str:
    """'s' whitespace, 'w' identifier character, 'p' any other symbol."""
    if c.isspace():
        return "s"
    return "w" if c.isalnum() or c == "_" else "p"


def word_end(s: str, col: int) -> Optional[int]:
    """Column after the word at/after `col` in line `s`; None if `col` is at line end.

    Leading whitespace is skipped. A word is a run of identifier characters or a
    run of other symbols, so "x.get_text()" stops at x | . | get_text | ().
    """
    n = len(s)
    if col >= n:
        return None
    i = col
    while i < n and s[i].isspace():
        i += 1
    if i < n:
        cls = _char_class(s[i])
        while i < n and _char_class(s[i]) == cls:
            i += 1
    return i


def word_start(s: str, col: int) -> Optional[int]:
    """Column of the start of the word at/before `col`; None if `col` is 0."""
    if col <= 0:
        return None
    i = min(col, len(s))
    while i > 0 and s[i - 1].isspace():
        i -= 1
    if i > 0:
        cls = _char_class(s[i - 1])
        while i > 0 and _char_class(s[i - 1]) == cls:
            i -= 1
    return i


def _next_char_ok(after: str) -> bool:
    return after == "" or after[0] in _AUTOCLOSE_BEFORE


def autoclose_action(before: str, after: str, ch: str):
    """Decide what typing `ch` does, given the line text before/after the cursor.

    Returns None (let Tk insert the character normally), ("overtype",) to step over
    an existing closer, or ("insert", text, cursor_offset) to insert a pair.
    """
    quote, in_comment = scan_state(before)
    if in_comment:
        return None
    is_quote = ch in QUOTES

    # Step over a closer that is already there.
    if after.startswith(ch) and ch in CLOSERS:
        if not is_quote:
            return ("overtype",)
        if quote is not None and quote[0] == ch:
            return ("overtype",)

    if ch in ")]}" or not _next_char_ok(after):
        return None
    if ch in "([{":
        return ("insert", ch + PAIRS[ch], 1)

    # Quotes: never inside a string, never for an apostrophe in a word.
    if quote is not None:
        return None
    if (before.endswith(ch * 2) and (len(before) < 3 or before[-3] != ch)
            and scan_state(before[:-2])[0] is None):
        return ("insert", ch * 4, 1)      # third quote -> """|"""
    prev = before[-1:]
    if prev and (prev.isalnum() or prev == "_") and not _STRING_PREFIX.search(before):
        return None
    return ("insert", ch * 2, 1)


def smart_newline(before: str, after: str) -> Tuple[str, int]:
    """Text to insert for Enter, plus the cursor offset inside that text."""
    indent = re.match(r"[ \t]*", before).group()
    code = strip_comment(before).rstrip()
    if before and after and before[-1] in "([{" and after[0] == PAIRS[before[-1]]:
        head = "\n" + indent + INDENT
        return head + "\n" + indent, len(head)
    extra = INDENT if code.endswith(":") or (code and code[-1] in "([{") else ""
    text = "\n" + indent + extra
    return text, len(text)
