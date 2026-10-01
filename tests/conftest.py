import sys
import types
from types import SimpleNamespace

import pytest


class FakeJev:
    """Stands in for typesafe_sdk. Set ``FakeJev.reply`` to control answers."""

    reply = {"label": "spam", "confidence": 0.95, "p": 0.95}
    raise_exc: Exception | None = None
    calls: list = []

    class Choice:
        def __init__(self, instructions, criteria):
            self.instructions, self.criteria = instructions, criteria

    class Noul:
        def __init__(self, instructions):
            self.instructions = instructions

    class TypeSafeClient:
        def system_one(self, state, questions):
            FakeJev.calls.append((state, questions))
            if FakeJev.raise_exc:
                raise FakeJev.raise_exc
            q = questions["q"]
            r = FakeJev.reply
            if isinstance(q, FakeJev.Choice):
                ans = SimpleNamespace(choice=r["label"], confidence=r["confidence"],
                                      probabilities={r["label"]: r["confidence"]})
            else:
                ans = SimpleNamespace(noul=r["p"])
            return SimpleNamespace(answers={"q": ans})


@pytest.fixture
def fake_jev(monkeypatch):
    FakeJev.reply = {"label": "spam", "confidence": 0.95, "p": 0.95}
    FakeJev.raise_exc = None
    FakeJev.calls = []
    mod = types.ModuleType("typesafe_sdk")
    mod.Choice, mod.Noul, mod.TypeSafeClient = FakeJev.Choice, FakeJev.Noul, FakeJev.TypeSafeClient
    monkeypatch.setitem(sys.modules, "typesafe_sdk", mod)
    monkeypatch.delenv("JEVVIFY_MODE", raising=False)
    monkeypatch.delenv("JEVVIFY_THRESHOLD", raising=False)
    return FakeJev


@pytest.fixture(autouse=True)
def stub_openai(monkeypatch):
    """Rewritten sample modules import openai; tests never need the real package."""
    if "openai" not in sys.modules:
        mod = types.ModuleType("openai")
        mod.OpenAI = lambda *a, **k: SimpleNamespace()
        monkeypatch.setitem(sys.modules, "openai", mod)
