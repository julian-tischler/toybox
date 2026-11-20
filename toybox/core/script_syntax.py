"""
script_syntax.py - Toybox's small additions to Python syntax in scripts.

    ! some text        ->  print('some text')

A line whose first non-blank character is "!" prints the rest of the line
literally (one space after "!" is dropped, indentation is kept, so it also
works inside if/for blocks). The rewrite is one line to one line, so line
numbers in tracebacks stay correct. Lines inside triple-quoted strings are
left alone.
"""

from typing import List, Optional

from ..editor.helpers import scan_state


def is_bang_line(line: str) -> bool:
    return line.lstrip().startswith("!")


def _bang_to_print(line: str) -> str:
    stripped = line.lstrip()
    indent = line[:len(line) - len(stripped)]
    text = stripped[1:]
    if text.startswith(" "):
        text = text[1:]
    return f"{indent}print({text!r})"


def expand(source: str) -> str:
    """Return `source` with every "! text" line turned into print('text')."""
    out: List[str] = []
    open_triple: Optional[str] = None          # ''' or """ left open by an earlier line
    for line in source.split("\n"):
        if open_triple is None and is_bang_line(line):
            out.append(_bang_to_print(line))
            continue
        out.append(line)
        rest = line
        if open_triple is not None:
            end = line.find(open_triple)
            if end < 0:
                continue                       # still inside the string
            rest, open_triple = line[end + 3:], None
        quote, _ = scan_state(rest)
        if quote is not None and len(quote) == 3:
            open_triple = quote
    return "\n".join(out)
