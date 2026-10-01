"""Language plugins. Each adapter knows how to find LLM call sites in one language and, if it can, rewrite them.

To add a language, implement :class:`LanguageAdapter` and append an instance to ``ADAPTERS``.
"""

from __future__ import annotations

from pathlib import Path

from .base import LanguageAdapter
from .go import GoAdapter
from .javascript import JavaScriptAdapter
from .python import PythonAdapter

ADAPTERS: list[LanguageAdapter] = [PythonAdapter(), JavaScriptAdapter(), GoAdapter()]


def adapter_for(path: Path) -> LanguageAdapter | None:
    suffix = Path(path).suffix
    for adapter in ADAPTERS:
        if suffix in adapter.suffixes:
            return adapter
    return None


def adapter_named(name: str) -> LanguageAdapter:
    for adapter in ADAPTERS:
        if adapter.name == name:
            return adapter
    raise KeyError(name)


__all__ = ["ADAPTERS", "LanguageAdapter", "adapter_for", "adapter_named"]
