from __future__ import annotations

from pathlib import Path

from ..analyzer import analyze_source
from ..fsutil import RUNTIME_FILENAME
from ..models import Candidate
from ..translator import RUNTIME_SOURCE, translate_source


class PythonAdapter:
    name = "python"
    suffixes: tuple[str, ...] = (".py",)
    can_rewrite = True

    def available(self) -> bool:
        return True

    def analyze(self, source: str, relpath: str) -> list[Candidate]:
        return analyze_source(source, relpath)

    def translate(self, source: str, candidates: list[Candidate], threshold: float, path: Path) -> str:
        return translate_source(source, candidates, threshold, (path.parent / "__init__.py").exists())

    def runtime_files(self, source: str, path: Path) -> dict[str, str]:
        return {RUNTIME_FILENAME: RUNTIME_SOURCE.read_text(encoding="utf-8")}

    def check_syntax(self, source: str, path: Path) -> str | None:
        try:
            compile(source, str(path), "exec")
        except (SyntaxError, ValueError) as exc:
            return str(exc)
        return None
