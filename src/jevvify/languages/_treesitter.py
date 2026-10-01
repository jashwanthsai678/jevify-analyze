"""Lazy tree-sitter loading. The grammars are optional (`pip install "jevvify[multilang]"`)."""

from __future__ import annotations

import functools
from typing import Any


@functools.cache
def parser(grammar: str) -> Any | None:
    """A tree-sitter Parser for ``grammar`` (javascript, typescript, tsx, go), or None if not installed."""
    try:
        import importlib

        import tree_sitter

        module, func = {"javascript": ("tree_sitter_javascript", "language"),
                        "typescript": ("tree_sitter_typescript", "language_typescript"),
                        "tsx": ("tree_sitter_typescript", "language_tsx"),
                        "go": ("tree_sitter_go", "language")}[grammar]
        lang: Any = getattr(importlib.import_module(module), func)()
        return tree_sitter.Parser(tree_sitter.Language(lang))
    except Exception:  # unknown grammar, ImportError, or an ABI mismatch between tree-sitter and a grammar
        return None


def text(node: Any, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def walk(node: Any):
    """Depth-first iteration over named and anonymous nodes."""
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        stack.extend(reversed(cur.children))


def ancestors(node: Any):
    cur = node.parent
    while cur is not None:
        yield cur
        cur = cur.parent
