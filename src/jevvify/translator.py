"""Phase 2: source-to-source rewrite of candidate calls into Jev-first calls with LLM fallback.

Each ``client.chat.completions.create(...)`` becomes::

    _jevvify_route("jev_ab12cd34", {"email": email}, lambda: client.chat.completions.create(...),
                  kind="choice", instructions="...", options=[...], shape="openai", threshold=0.85)

The original call is kept verbatim inside the lambda, so the legacy path is byte-for-byte what
it was. Only the call expression is replaced; surrounding formatting and comments are untouched.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .fsutil import RUNTIME_FILENAME
from .models import Candidate

IMPORT_NAME = "_jevvify_route"
RUNTIME_SOURCE = Path(__file__).parent / "runtime_src" / "jevvify_rt.py"


def runtime_import_line(directory_is_package: bool) -> str:
    module = f".{RUNTIME_FILENAME[:-3]}" if directory_is_package else RUNTIME_FILENAME[:-3]
    return f"from {module} import route as {IMPORT_NAME}"


def render_call(c: Candidate, original: str, threshold: float, indent: str = "") -> str:
    state = "{" + ", ".join(f"{k!r}: {expr}" for k, expr in c.variables.items()) + "}"
    parts = [
        repr(c.id), state, f"lambda: {original}",
        f"kind={c.kind!r}", f"instructions={c.instructions!r}", f"options={c.options!r}",
        f"shape={c.provider!r}", f"threshold={threshold!r}",
    ]
    if c.json_mode:
        parts.append("json_mode=True")
        parts.append(f"json_key={c.json_key!r}")
    inner = indent + "    "
    return f"{IMPORT_NAME}(\n{inner}" + f",\n{inner}".join(parts) + f",\n{indent})"


def _line_starts(text: str) -> list[int]:
    starts, pos = [0], 0
    for line in text.split("\n"):
        pos += len(line) + 1
        starts.append(pos)
    return starts


def _offset(text: str, starts: list[int], lineno: int, byte_col: int) -> int:
    line = text[starts[lineno - 1]: starts[lineno] - 1]
    return starts[lineno - 1] + len(line.encode("utf-8")[:byte_col].decode("utf-8"))


def _import_insert_line(tree: ast.Module) -> int:
    """1-based line after which the runtime import goes (0 = top of file)."""
    last = 0
    for i, node in enumerate(tree.body):
        is_doc = i == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
            and isinstance(node.value.value, str)
        if is_doc or isinstance(node, (ast.Import, ast.ImportFrom)):
            last = node.end_lineno or node.lineno
        else:
            break
    return last


def translate_source(source: str, candidates: list[Candidate], threshold: float,
                     directory_is_package: bool) -> str:
    """Rewrite ``candidates`` (status == "candidate") in ``source``. Raises SyntaxError if the
    result does not compile, so callers can refuse to write it."""
    todo = sorted((c for c in candidates if c.status == "candidate"), key=lambda c: (c.line, c.col), reverse=True)
    if not todo:
        return source
    starts = _line_starts(source)
    out, floor = source, len(source) + 1
    applied = 0
    for c in todo:
        begin = _offset(source, starts, c.line, c.col)
        end = _offset(source, starts, c.end_line, c.end_col)
        if end > floor:  # overlaps a call already rewritten after it; skip the outer one
            continue
        line_start = starts[c.line - 1]
        stripped = source[line_start:begin].lstrip(" \t")
        indent = source[line_start:begin][: len(source[line_start:begin]) - len(stripped)]
        out = out[:begin] + render_call(c, source[begin:end], threshold, indent) + out[end:]
        floor = begin
        applied += 1
    if not applied:
        return source

    line = runtime_import_line(directory_is_package)
    if line not in out:
        lines = out.split("\n")
        at = _import_insert_line(ast.parse(out))
        lines.insert(at, line)
        out = "\n".join(lines)
    compile(out, "<jevvify>", "exec")
    return out
