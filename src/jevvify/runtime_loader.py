from __future__ import annotations

import importlib.util
from types import ModuleType

from .translator import RUNTIME_SOURCE


def load_runtime() -> ModuleType:
    """Import the bundled runtime file as a module (same code that ships into target projects)."""
    spec = importlib.util.spec_from_file_location("_jevvify_rt_bundled", RUNTIME_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
