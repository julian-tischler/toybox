"""
script_syntax.py - Toybox's small additions to Python syntax in scripts.

    ! expression        ->  print(expression)

A line whose first non-blank character is "!" prints the value of the rest of
the line, so it takes anything print() takes:

    ! "measuring"                       ->  print("measuring")
    ! Lenses["lens1"].get_text()        ->  print(Lenses["lens1"].get_text())
    ! f"{v:.2f} V", "ok"                ->  print(f"{v:.2f} V", "ok")
    ! v   # comment                     ->  print(v)   # comment

Indentation is kept (so it works inside if/for blocks) and a lone "!" prints an
empty line. The rewrite is one line to one line, so line numbers in tracebacks
stay correct. Lines inside triple-quoted strings are left alone.
"""

from typing import List, Optional

from ..editor.helpers import scan_state, strip_comment


def is_bang_line(line: str) -> bool:
    return line.lstrip().startswith("!")


def _bang_to_print(line: str) -> str:
    stripped = line.lstrip()
    indent = line[:len(line) - len(stripped)]
    rest = stripped[1:]
    code = strip_comment(rest).rstrip()            # "# comment" stays after the call
    comment = rest[len(strip_comment(rest)):]
    expr = code.strip()
    return f"{indent}print({expr}){'  ' + comment if comment else ''}"


def expand(source: str) -> str:
    """Return `source` with every "! expr" line turned into print(expr)."""
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
