from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..models import Candidate


class LanguageAdapter(Protocol):
    """What the pipeline needs from a language plugin."""

    name: str  # "python", "javascript", "go" (also Candidate.language)
    suffixes: tuple[str, ...]
    can_rewrite: bool  # False: detection only; candidates are reported for manual rewrite

    def available(self) -> bool:
        """False when an optional parser dependency is missing."""
        ...

    def analyze(self, source: str, relpath: str) -> list[Candidate]:
        """Every LLM call site in one file, as candidates or skips."""
        ...

    def translate(self, source: str, candidates: list[Candidate], threshold: float, path: Path) -> str:
        """Rewrite ``candidates`` in ``source``. ``path`` is the file's location in the original project.

        Must raise ``SyntaxError`` if the result does not parse.
        """
        ...

    def runtime_files(self, source: str, path: Path) -> dict[str, str]:
        """Runtime helper files (name -> content) that must sit next to a rewritten ``path``."""
        ...

    def check_syntax(self, source: str, path: Path) -> str | None:
        """An error message if ``source`` does not parse, else None."""
        ...
