"""
code_editor.py - The script editor widget: QPlainTextEdit + line numbers +
Python highlighting + the editing rules from helpers.py.
"""

import keyword
import re
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QKeySequence,
                           QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from . import helpers as H

CODE_FONT = ("Consolas", 11)

# ------------------------------------------------------------- highlighting
_COLORS = {
    "keyword": "#c792ea", "builtin": "#82aaff", "string": "#c3e88d", "comment": "#6b7280",
    "number": "#f78c6c", "def": "#ffcb6b", "decorator": "#89ddff", "self": "#f07178",
}


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    f.setFontItalic(italic)
    return f


class PythonHighlighter(QSyntaxHighlighter):
    """Keywords, builtins, numbers, def/class names, strings (incl. triple-quoted
    across lines) and comments."""

    _BUILTINS = ("print len range int float str list dict set tuple min max abs round sum "
                 "sorted enumerate zip map filter isinstance any all open type bool None "
                 "True False Lenses").split()

    def __init__(self, document):
        super().__init__(document)
        # (pattern, format, capture group to colour)
        self._rules = [
            (re.compile(r"\b(?:" + "|".join(keyword.kwlist) + r")\b"), _fmt(_COLORS["keyword"]), 0),
            (re.compile(r"\b(?:" + "|".join(self._BUILTINS) + r")\b"), _fmt(_COLORS["builtin"]), 0),
            (re.compile(r"\bself\b"), _fmt(_COLORS["self"], italic=True), 0),
            (re.compile(r"\b[0-9]+(?:\.[0-9]*)?(?:[eE][-+]?[0-9]+)?\b"), _fmt(_COLORS["number"]), 0),
            (re.compile(r"^\s*@[\w.]+"), _fmt(_COLORS["decorator"]), 0),
            (re.compile(r"\b(?:def|class)\s+(\w+)"), _fmt(_COLORS["def"], bold=True), 1),
        ]
        self._string = _fmt(_COLORS["string"])
        self._comment = _fmt(_COLORS["comment"], italic=True)

    def highlightBlock(self, text: str) -> None:
        for rx, fmt, group in self._rules:
            for m in rx.finditer(text):
                self.setFormat(m.start(group), m.end(group) - m.start(group), fmt)

        # Strings and comments win over the rules above. State: 0 = normal,
        # 1 = inside ''' ... ''', 2 = inside """ ... """ (from previous lines).
        state = self.previousBlockState()
        i, n = 0, len(text)
        if state in (1, 2):
            delim = "'''" if state == 1 else '"""'
            end = text.find(delim)
            if end < 0:
                self.setFormat(0, n, self._string)
                self.setCurrentBlockState(state)
                return
            self.setFormat(0, end + 3, self._string)
            i = end + 3
        self.setCurrentBlockState(0)
        while i < n:
            c = text[i]
            if c == "#":
                self.setFormat(i, n - i, self._comment)
                return
            if c in "'\"":
                triple = text[i:i + 3] if text[i:i + 3] in ("'''", '"""') else None
                if triple:
                    end = text.find(triple, i + 3)
                    if end < 0:
                        self.setFormat(i, n - i, self._string)
                        self.setCurrentBlockState(1 if triple == "'''" else 2)
                        return
                    self.setFormat(i, end + 3 - i, self._string)
                    i = end + 3
                    continue
                j = i + 1
                while j < n and text[j] != c:
                    j += 2 if text[j] == "\\" else 1
                self.setFormat(i, min(j + 1, n) - i, self._string)
                i = j + 1
                continue
            i += 1


# ------------------------------------------------------------- line numbers
class _LineNumbers(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.line_number_width(), 0)

    def paintEvent(self, e):
        self.editor.paint_line_numbers(e)


# ------------------------------------------------------------------ editor
class CodeEditor(QPlainTextEdit):
    run_requested = Signal()

    GUTTER_BG = "#17181b"
    GUTTER_FG = "#5b606b"
    GUTTER_CURRENT = "#aeb4be"

    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFont(*CODE_FONT)
        font.setStyleHint(QFont.Monospace)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(QFontMetricsF(font).horizontalAdvance(" ") * H.INDENT_WIDTH)
        self.highlighter = PythonHighlighter(self.document())
        self._line_clip: Optional[str] = None
        self._gutter = _LineNumbers(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._gutter.update)
        self._update_gutter_width()

    # ------------------------------------------------------- line numbers
    def line_number_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self, *_):
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.line_number_width(), cr.height()))

    def paint_line_numbers(self, e):
        p = QPainter(self._gutter)
        p.fillRect(e.rect(), QColor(self.GUTTER_BG))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        width = self._gutter.width() - 8
        while block.isValid() and top <= e.rect().bottom():
            if block.isVisible() and bottom >= e.rect().top():
                p.setPen(QColor(self.GUTTER_CURRENT if number == current else self.GUTTER_FG))
                p.drawText(0, top, width, self.fontMetrics().height(), Qt.AlignRight,
                           str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    # ---------------------------------------------------------- utilities
    def _line(self, n: int) -> str:
        return self.document().findBlockByNumber(n).text()

    def _lines(self, first: int, last: int) -> List[str]:
        return [self._line(i) for i in range(first, last + 1)]

    def _pos(self, line: int, col: int) -> int:
        block = self.document().findBlockByNumber(line)
        return block.position() + min(col, len(block.text()))

    def _line_col(self, pos: int) -> Tuple[int, int]:
        block = self.document().findBlock(pos)
        return block.blockNumber(), pos - block.position()

    def _line_range(self):
        """(first, last, selection) - a selection ending at column 0 of a later
        line does not include that line. selection = ((l, c) anchor, (l, c) pos)."""
        c = self.textCursor()
        if not c.hasSelection():
            n = c.blockNumber()
            return n, n, None
        a, p = self._line_col(c.anchor()), self._line_col(c.position())
        (sl, _), (el, ec) = min(a, p), max(a, p)
        return sl, (el - 1 if ec == 0 and el > sl else el), (a, p)

    def _replace_lines(self, first: int, last: int, new: List[str]) -> None:
        c = QTextCursor(self.document())
        c.setPosition(self._pos(first, 0))
        c.setPosition(self.document().findBlockByNumber(last).position()
                      + len(self._line(last)), QTextCursor.KeepAnchor)
        c.insertText("\n".join(new))

    def _restore(self, sel, cursor_lc, mapper: Callable[[int, int], Tuple[int, int]]) -> None:
        c = self.textCursor()
        if sel:
            c.setPosition(self._pos(*mapper(*sel[0])))
            c.setPosition(self._pos(*mapper(*sel[1])), QTextCursor.KeepAnchor)
        else:
            c.setPosition(self._pos(*mapper(*cursor_lc)))
        self.setTextCursor(c)

    def _edit(self):
        """Context manager-ish: one undo step for everything in the block."""
        cursor = self.textCursor()
        cursor.beginEditBlock()
        return cursor

    # ------------------------------------------------------------- keys
    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        ctrl, shift, alt = bool(mods & Qt.ControlModifier), bool(mods & Qt.ShiftModifier), \
            bool(mods & Qt.AltModifier)

        if key in (Qt.Key_Return, Qt.Key_Enter):
            if ctrl:
                self.run_requested.emit()
            else:
                self._smart_newline()
            return
        if key == Qt.Key_Tab and not ctrl:
            self._tab()
            return
        if key == Qt.Key_Backtab:
            self._transform(H.dedent_lines)
            return
        if key == Qt.Key_Backspace and not mods and self._backspace_pair():
            return
        if key == Qt.Key_NumberSign and ctrl:
            self._transform(H.toggle_comment)
            return
        if alt and not ctrl and key in (Qt.Key_Up, Qt.Key_Down):
            self._move(-1 if key == Qt.Key_Up else 1)
            return
        if ctrl and not alt and key == Qt.Key_D:
            self._duplicate()
            return
        if e.matches(QKeySequence.Cut) and not self.textCursor().hasSelection():
            self._cut_line()
            return
        if e.matches(QKeySequence.Paste) and self._paste_line():
            return
        if shift and not ctrl and not alt and key in (Qt.Key_Left, Qt.Key_Right):
            self._word_jump(-1 if key == Qt.Key_Left else 1)
            return
        ch = e.text()
        if len(ch) == 1 and (ch in H.PAIRS or ch in H.CLOSERS) and self._bracket(ch):
            return
        super().keyPressEvent(e)

    # ------------------------------------------------ brackets and quotes
    def _bracket(self, ch: str) -> bool:
        c = self.textCursor()
        if c.hasSelection():
            if ch not in H.PAIRS:
                return False
            start, end = c.selectionStart(), c.selectionEnd()
            c.beginEditBlock()
            c.setPosition(end)
            c.insertText(H.PAIRS[ch])
            c.setPosition(start)
            c.insertText(ch)
            c.endEditBlock()
            c.setPosition(start + 1)
            c.setPosition(end + 1, QTextCursor.KeepAnchor)
            self.setTextCursor(c)
            return True
        text, col = c.block().text(), c.positionInBlock()
        action = H.autoclose_action(text[:col], text[col:], ch)
        if action is None:
            return False
        if action[0] == "overtype":
            c.movePosition(QTextCursor.Right)
        else:
            _, inserted, offset = action
            c.insertText(inserted)
            c.movePosition(QTextCursor.Left, n=len(inserted) - offset)
        self.setTextCursor(c)
        return True

    def _backspace_pair(self) -> bool:
        c = self.textCursor()
        if c.hasSelection():
            return False
        text, col = c.block().text(), c.positionInBlock()
        before, after = text[:col], text[col:]
        if before and after and before[-1] in H.PAIRS and H.PAIRS[before[-1]] == after[0]:
            c.movePosition(QTextCursor.Left)
            c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, 2)
            c.removeSelectedText()
            self.setTextCursor(c)
            return True
        return False

    # ------------------------------------------------------------- Enter
    def _smart_newline(self) -> None:
        c = self.textCursor()
        c.beginEditBlock()
        c.removeSelectedText()
        text, col = c.block().text(), c.positionInBlock()
        inserted, offset = H.smart_newline(text[:col], text[col:])
        start = c.position()
        c.insertText(inserted)
        c.endEditBlock()
        c.setPosition(start + offset)
        self.setTextCursor(c)
        self.ensureCursorVisible()

    def _tab(self) -> None:
        c = self.textCursor()
        if c.hasSelection():
            self._transform(H.indent_lines)
            return
        col = c.positionInBlock()
        c.insertText(" " * (H.INDENT_WIDTH - col % H.INDENT_WIDTH))

    # ---------------------------------------------- block transformations
    def _transform(self, func) -> None:
        first, last, sel = self._line_range()
        cursor_lc = self._line_col(self.textCursor().position())
        old = self._lines(first, last)
        new = func(old)
        if new == old:
            return
        c = self._edit()
        self._replace_lines(first, last, new)
        c.endEditBlock()

        def mapper(line, col):
            if first <= line <= last:
                i = line - first
                return line, H.shift_col(col, old[i], new[i])
            return line, col
        self._restore(sel, cursor_lc, mapper)

    def _move(self, direction: int) -> None:
        first, last, sel = self._line_range()
        cursor_lc = self._line_col(self.textCursor().position())
        lines = self._lines(0, self.blockCount() - 1)
        moved = H.move_block(lines, first, last, direction)
        if moved is None:
            return
        lo, hi, new_span, new_first, _ = moved
        c = self._edit()
        self._replace_lines(lo, hi, new_span)
        c.endEditBlock()
        shift = new_first - first
        self._restore(sel, cursor_lc, lambda line, col: (line + shift, col))

    def _duplicate(self) -> None:
        first, last, sel = self._line_range()
        cursor_lc = self._line_col(self.textCursor().position())
        block = self._lines(first, last)
        count = last - first + 1
        c = QTextCursor(self.document())
        c.setPosition(self._pos(last, len(self._line(last))))
        c.insertText("\n" + "\n".join(block))
        self._restore(sel, cursor_lc, lambda line, col: (line + count, col))

    # ---------------------------------------------------- cut / paste line
    def _cut_line(self) -> None:
        c = self.textCursor()
        line, total = c.blockNumber(), self.blockCount()
        clip = self._line(line) + "\n"
        d = QTextCursor(self.document())
        if line < total - 1:
            d.setPosition(self._pos(line, 0))
            d.setPosition(self._pos(line + 1, 0), QTextCursor.KeepAnchor)
        elif line > 0:                        # last line: take the newline before it
            d.setPosition(self._pos(line - 1, len(self._line(line - 1))))
            d.setPosition(self._pos(line, len(self._line(line))), QTextCursor.KeepAnchor)
            line -= 1
        else:                                 # the only line
            d.setPosition(0)
            d.setPosition(len(self._line(0)), QTextCursor.KeepAnchor)
        d.removeSelectedText()
        QGuiApplication.clipboard().setText(clip)
        self._line_clip = clip
        c.setPosition(self._pos(line, 0))
        self.setTextCursor(c)

    def _paste_line(self) -> bool:
        """A line cut with Ctrl+X is pasted as a whole line above the cursor's line."""
        if self._line_clip is None or self.textCursor().hasSelection():
            return False
        clip = QGuiApplication.clipboard().text()
        if clip != self._line_clip:
            self._line_clip = None            # clipboard changed elsewhere: paste normally
            return False
        line, col = self._line_col(self.textCursor().position())
        c = QTextCursor(self.document())
        c.setPosition(self._pos(line, 0))
        c.insertText(clip)
        c.setPosition(self._pos(line + 1, col))
        self.setTextCursor(c)
        return True

    # ------------------------------------------------------- word jump
    def _word_jump(self, direction: int) -> None:
        c = self.textCursor()
        line, col = c.blockNumber(), c.positionInBlock()
        text = self._line(line)
        if direction > 0:
            new = H.word_end(text, col)
            if new is None:
                if line >= self.blockCount() - 1:
                    return
                line += 1
                new = H.word_end(self._line(line), 0) or 0
        else:
            new = H.word_start(text, col)
            if new is None:
                if line == 0:
                    return
                line -= 1
                prev = self._line(line)
                new = H.word_start(prev, len(prev)) or 0
        c.setPosition(self._pos(line, new))     # moves without selecting
        self.setTextCursor(c)
