"""
editor_helpers.py - Editing conveniences for the script editor (a tk.Text).

Shortcuts
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
                     Ctrl+Shift+Left / Right keep Tk's select-by-word

Ctrl+/ is deliberately left alone (Tk's default: select all).

The rules are pure functions on strings and lists so they can be tested without a
display; `EditorEnhancements` only wires them to a Text widget.
"""

import re
from contextlib import contextmanager
from tkinter import TclError
from typing import Callable, List, Optional, Tuple

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


# --------------------------------------------------------------------------
# Widget wiring
# --------------------------------------------------------------------------
class EditorEnhancements:
    """Attach the shortcuts above to a tk.Text (which must have undo=True)."""

    def __init__(self, text):
        self.text = text
        t = text
        t.bind("<KeyPress>", self._on_key)
        t.bind("<BackSpace>", self._on_backspace)
        t.bind("<Return>", self._on_return)
        t.bind("<KP_Enter>", self._on_return)
        t.bind("<Tab>", self._on_tab)
        for seq in ("<Shift-Tab>", "<ISO_Left_Tab>"):     # the latter exists on X11 only
            try:
                t.bind(seq, self._on_shift_tab)
            except TclError:
                pass
        t.bind("<Control-numbersign>", self._on_toggle_comment)
        t.bind("<Alt-Up>", lambda e: self._on_move(-1))
        t.bind("<Alt-Down>", lambda e: self._on_move(1))
        t.bind("<Control-d>", self._on_duplicate)
        t.bind("<Control-D>", self._on_duplicate)
        t.bind("<Control-x>", self._on_cut_line)
        t.bind("<Control-X>", self._on_cut_line)     # Caps Lock on
        t.bind("<<Paste>>", self._on_paste)
        t.bind("<Shift-Left>", lambda e: self._on_word_jump(e, -1))
        t.bind("<Shift-Right>", lambda e: self._on_word_jump(e, 1))
        self._line_clip: Optional[str] = None        # text of the last Ctrl+X line cut

    # ----------------------------------------------------------- utilities
    def _pos(self, index: str) -> Tuple[int, int]:
        line, col = str(self.text.index(index)).split(".")
        return int(line), int(col)

    def _line_text(self, line: int) -> str:
        return self.text.get(f"{line}.0", f"{line}.end")

    def _get_lines(self, first: int, last: int) -> List[str]:
        return self.text.get(f"{first}.0", f"{last}.end").split("\n")

    def _replace_lines(self, first: int, last: int, new: List[str]) -> None:
        self.text.delete(f"{first}.0", f"{last}.end")
        self.text.insert(f"{first}.0", "\n".join(new))

    def _selection(self):
        """((line, col), (line, col)) of the selection, or None."""
        ranges = self.text.tag_ranges("sel")
        if not ranges:
            return None
        a, b = str(ranges[0]), str(ranges[1])
        return self._pos(a), self._pos(b)

    def _line_range(self):
        """(first_line, last_line, selection). A selection that ends at column 0 of
        a later line does not include that line."""
        sel = self._selection()
        if not sel:
            line = self._pos("insert")[0]
            return line, line, None
        (sl, _), (el, ec) = sel
        return sl, (el - 1 if ec == 0 and el > sl else el), sel

    def _restore(self, sel, cursor, mapper: Callable[[int, int], Tuple[int, int]]) -> None:
        if sel:
            (sl, sc), (el, ec) = mapper(*sel[0]), mapper(*sel[1])
            self.text.tag_remove("sel", "1.0", "end")
            self.text.tag_add("sel", f"{sl}.{sc}", f"{el}.{ec}")
            self.text.mark_set("insert", f"{el}.{ec}")
        else:
            line, col = mapper(*cursor)
            self.text.mark_set("insert", f"{line}.{col}")
        self.text.see("insert")

    @contextmanager
    def _undo_group(self):
        """Make everything inside one Ctrl+Z step (Tk would otherwise split it)."""
        t = self.text
        t.configure(autoseparators=False)
        t.edit_separator()
        try:
            yield
        finally:
            t.edit_separator()
            t.configure(autoseparators=True)

    # ------------------------------------------------- brackets and quotes
    def _on_key(self, event):
        ch = event.char
        if len(ch) != 1 or (ch not in PAIRS and ch not in CLOSERS):
            return None
        sel = self._selection()
        if sel:
            if ch in PAIRS:
                self._wrap_selection(ch, sel)
                return "break"
            return None
        line, col = self._pos("insert")
        text = self._line_text(line)
        action = autoclose_action(text[:col], text[col:], ch)
        if action is None:
            return None
        if action[0] == "overtype":
            self.text.mark_set("insert", "insert+1c")
        else:
            _, inserted, offset = action
            self.text.insert("insert", inserted)
            self.text.mark_set("insert", f"insert-{len(inserted) - offset}c")
        self.text.see("insert")
        return "break"

    def _wrap_selection(self, ch: str, sel) -> None:
        (sl, sc), (el, ec) = sel
        with self._undo_group():
            self.text.insert(f"{el}.{ec}", PAIRS[ch])
            self.text.insert(f"{sl}.{sc}", ch)
        new_start = (sl, sc + 1)
        new_end = (el, ec + 1) if el == sl else (el, ec)
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", f"{new_start[0]}.{new_start[1]}", f"{new_end[0]}.{new_end[1]}")
        self.text.mark_set("insert", f"{new_end[0]}.{new_end[1]}")

    def _on_backspace(self, _event):
        if self._selection():
            return None
        line, col = self._pos("insert")
        text = self._line_text(line)
        before, after = text[:col], text[col:]
        if before and after and before[-1] in PAIRS and PAIRS[before[-1]] == after[0]:
            with self._undo_group():
                self.text.delete("insert-1c", "insert+1c")
            return "break"
        return None

    # ---------------------------------------------------------------- Enter
    def _on_return(self, _event):
        with self._undo_group():
            sel = self._selection()
            if sel:
                self.text.delete(f"{sel[0][0]}.{sel[0][1]}", f"{sel[1][0]}.{sel[1][1]}")
            line, col = self._pos("insert")
            text = self._line_text(line)
            inserted, offset = smart_newline(text[:col], text[col:])
            start = self.text.index("insert")
            self.text.insert(start, inserted)
            self.text.mark_set("insert", f"{start}+{offset}c")
        self.text.see("insert")
        return "break"

    # ----------------------------------------------- block transformations
    def _transform(self, func: Callable[[List[str]], List[str]]) -> str:
        first, last, sel = self._line_range()
        cursor = self._pos("insert")
        old = self._get_lines(first, last)
        new = func(old)
        if new == old:
            return "break"
        with self._undo_group():
            self._replace_lines(first, last, new)

        def mapper(line: int, col: int) -> Tuple[int, int]:
            if first <= line <= last:
                i = line - first
                return line, shift_col(col, old[i], new[i])
            return line, col

        self._restore(sel, cursor, mapper)
        return "break"

    def _on_tab(self, _event):
        if self._selection():
            return self._transform(indent_lines)
        col = self._pos("insert")[1]
        self.text.insert("insert", " " * (INDENT_WIDTH - col % INDENT_WIDTH))
        return "break"

    def _on_shift_tab(self, _event):
        return self._transform(dedent_lines)

    def _on_toggle_comment(self, _event):
        return self._transform(toggle_comment)

    # --------------------------------------------------- move / duplicate
    def _on_move(self, direction: int):
        first, last, sel = self._line_range()
        cursor = self._pos("insert")
        total = int(self.text.index("end-1c").split(".")[0])
        lines = self._get_lines(1, total)
        moved = move_block(lines, first - 1, last - 1, direction)
        if moved is None:
            return "break"
        lo, hi, new_span, new_first, _new_last = moved
        with self._undo_group():
            self._replace_lines(lo + 1, hi + 1, new_span)
        shift = new_first - (first - 1)
        self._restore(sel, cursor, lambda line, col: (line + shift, col))
        return "break"

    def _on_duplicate(self, _event):
        first, last, sel = self._line_range()
        cursor = self._pos("insert")
        block = self._get_lines(first, last)
        count = last - first + 1
        with self._undo_group():
            self.text.insert(f"{last}.end", "\n" + "\n".join(block))
        self._restore(sel, cursor, lambda line, col: (line + count, col))
        return "break"

    # ------------------------------------------------------ cut / paste line
    def _on_cut_line(self, _event):
        if self._selection():
            return None                   # normal cut of the selection (Tk's <<Cut>>)
        t = self.text
        line = self._pos("insert")[0]
        total = int(t.index("end-1c").split(".")[0])
        clip = self._line_text(line) + "\n"
        with self._undo_group():
            if line < total:
                t.delete(f"{line}.0", f"{line + 1}.0")
            elif line > 1:                # last line: take the newline before it
                t.delete(f"{line - 1}.end", f"{line}.end")
                line -= 1
            else:                         # the only line
                t.delete("1.0", "1.end")
        t.clipboard_clear()
        t.clipboard_append(clip)
        self._line_clip = clip
        t.mark_set("insert", f"{line}.0")
        t.see("insert")
        return "break"

    def _on_paste(self, _event):
        """A line cut with Ctrl+X is pasted as a whole line above the current line."""
        if self._line_clip is None or self._selection():
            return None
        try:
            clip = self.text.clipboard_get()
        except TclError:
            return None
        if clip != self._line_clip:
            self._line_clip = None        # clipboard changed elsewhere: paste normally
            return None
        line, col = self._pos("insert")
        with self._undo_group():
            self.text.insert(f"{line}.0", clip)
        self.text.mark_set("insert", f"{line + 1}.{col}")
        self.text.see("insert")
        return "break"

    # ------------------------------------------------------------ word jump
    def _on_word_jump(self, event, direction: int):
        if event.state & 0x4:             # Ctrl held: keep Tk's select-by-word
            return None
        t = self.text
        line, col = self._pos("insert")
        text = self._line_text(line)
        if direction > 0:
            new = word_end(text, col)
            if new is None:               # at line end: end of first word on next line
                if line >= int(t.index("end-1c").split(".")[0]):
                    return "break"
                line += 1
                new = word_end(self._line_text(line), 0) or 0
        else:
            new = word_start(text, col)
            if new is None:               # at line start: start of last word above
                if line <= 1:
                    return "break"
                line -= 1
                prev = self._line_text(line)
                new = word_start(prev, len(prev)) or 0
        t.tag_remove("sel", "1.0", "end")
        t.mark_set("insert", f"{line}.{new}")
        t.see("insert")
        return "break"