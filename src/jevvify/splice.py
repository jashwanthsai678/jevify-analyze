"""Replace spans of source text addressed by (line, utf-8 byte column), as every parser reports them."""

from __future__ import annotations


def line_starts(text: str) -> list[int]:
    starts, pos = [0], 0
    for line in text.split("\n"):
        pos += len(line) + 1
        starts.append(pos)
    return starts


def offset(text: str, starts: list[int], lineno: int, byte_col: int) -> int:
    """Character offset of a 1-based line and a utf-8 byte column."""
    line = text[starts[lineno - 1]: starts[lineno] - 1]
    return starts[lineno - 1] + len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def indent_of(text: str, starts: list[int], lineno: int) -> str:
    line = text[starts[lineno - 1]: starts[lineno] - 1]
    return line[: len(line) - len(line.lstrip(" \t"))]
