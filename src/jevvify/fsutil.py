from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

EXCLUDED_DIRS = {
    ".git", ".hg", ".venv", "venv", "env", "node_modules", "__pycache__", ".tox", ".next", ".nuxt",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".jevvify", "build", "dist", "site-packages", "vendor",
    "coverage", ".turbo",
}
RUNTIME_FILENAME = "_jevvify_rt.py"
RUNTIME_STEM = "_jevvify_rt"
SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts", ".go"}


def iter_source_files(root: Path, exclude: tuple[Path, ...] = (), suffixes: set[str] | None = None) -> Iterator[Path]:
    """Source files under ``root``, skipping dependency/build folders and jevvify's own runtime files."""
    wanted = suffixes or SOURCE_SUFFIXES
    root = Path(root)
    skip = {p.resolve() for p in exclude}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in EXCLUDED_DIRS
            and not d.endswith(".egg-info")
            and (Path(dirpath) / d).resolve() not in skip
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix in wanted and not name.startswith(RUNTIME_STEM) and not name.endswith(".d.ts"):
                yield path


def iter_python_files(root: Path, exclude: tuple[Path, ...] = ()) -> Iterator[Path]:
    return iter_source_files(root, exclude, {".py"})


def read_source(path: Path) -> tuple[str, bool]:
    """Return (text with \\n newlines, was_crlf)."""
    raw = Path(path).read_bytes().decode("utf-8-sig")
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def write_source(path: Path, text: str, crlf: bool) -> None:
    if crlf:
        text = text.replace("\n", "\r\n")
    Path(path).write_bytes(text.encode("utf-8"))
