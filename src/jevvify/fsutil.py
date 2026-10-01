from __future__ import annotations

import os
from pathlib import Path

EXCLUDED_DIRS = {
    ".git", ".hg", ".venv", "venv", "env", "node_modules", "__pycache__", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".jevvify", "build", "dist", "site-packages",
}
RUNTIME_FILENAME = "_jevvify_rt.py"


def iter_python_files(root: Path, exclude: tuple[Path, ...] = ()):
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
            if name.endswith(".py") and name != RUNTIME_FILENAME:
                yield Path(dirpath) / name


def read_source(path: Path) -> tuple[str, bool]:
    """Return (text with \n newlines, was_crlf)."""
    raw = Path(path).read_bytes().decode("utf-8-sig")
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def write_source(path: Path, text: str, crlf: bool) -> None:
    if crlf:
        text = text.replace("\n", "\r\n")
    Path(path).write_bytes(text.encode("utf-8"))
