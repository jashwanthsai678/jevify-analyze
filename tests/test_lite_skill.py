"""The standalone skill ships code for users to paste; make sure that code works."""

import io
import json
import re
import shutil
import subprocess
import types
import urllib.error
from pathlib import Path

import pytest

SKILL = Path(__file__).parent.parent / "skills" / "jevvify-lite" / "SKILL.md"
TEXT = SKILL.read_text(encoding="utf-8")


def block(heading: str, lang: str) -> str:
    """Code block of ``lang`` that follows ``heading``."""
    start = TEXT.index(heading)
    m = re.compile(rf"```{lang}\n(.*?)```", re.S).search(TEXT, start)
    return m.group(1)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def helper(monkeypatch):
    mod = types.ModuleType("jev_decide")
    exec(compile(block("### Python helper", "python"), "jev_decide.py", "exec"), mod.__dict__)
    for var in ("JEV_MODE", "JEV_THRESHOLD", "JEV_MODEL", "JEV_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    return mod


def reply(monkeypatch, answer):
    sent = {}

    def fake(req, timeout):
        sent["body"] = json.loads(req.data)
        sent["auth"] = req.get_header("Authorization")
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(json.dumps({"answers": {"q": answer}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake)
    return sent


CHOICE = {"type": "choice", "instructions": "Which team?", "criteria": {"billing": "money", "support": "bugs"}}
NOUL = {"type": "noul", "instructions": "Urgent?", "criteria": {"true": "yes", "false": "no"}}


def test_confident_choice_skips_the_llm(helper, monkeypatch):
    sent = reply(monkeypatch, {"choice": "billing", "probabilities": {"billing": 0.95, "support": 0.05}})
    calls = []
    assert helper.decide("charged twice", CHOICE, lambda: calls.append(1) or "support") == "billing"
    assert calls == []
    assert sent["auth"] == "Bearer sk-test"
    assert sent["body"] == {"model": "typesafe/jev-1.13", "state": "charged twice", "questions": {"q": CHOICE}}


def test_unsure_failing_or_keyless_jev_uses_the_fallback(helper, monkeypatch):
    reply(monkeypatch, {"choice": "billing", "probabilities": {"billing": 0.6, "support": 0.4}})
    assert helper.decide("x", CHOICE, lambda: "LLM") == "LLM"
    reply(monkeypatch, urllib.error.URLError("down"))
    assert helper.decide("x", CHOICE, lambda: "LLM") == "LLM"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert helper.decide("x", CHOICE, lambda: "LLM") == "LLM"


def test_noul_returns_booleans_and_respects_the_threshold(helper, monkeypatch):
    reply(monkeypatch, {"noul": 0.97})
    assert helper.decide("x", NOUL, lambda: None) is True
    reply(monkeypatch, {"noul": 0.02})
    assert helper.decide("x", NOUL, lambda: None) is False
    reply(monkeypatch, {"noul": 0.6})
    assert helper.decide("x", NOUL, lambda: "LLM") == "LLM"


def test_modes(helper, monkeypatch, caplog):
    reply(monkeypatch, {"choice": "billing", "probabilities": {"billing": 0.99}})
    monkeypatch.setenv("JEV_MODE", "off")
    assert helper.decide("x", CHOICE, lambda: "LLM") == "LLM"
    monkeypatch.setenv("JEV_MODE", "shadow")
    with caplog.at_level("INFO", logger="jev"):
        assert helper.decide("x", CHOICE, lambda: "support", name="route") == "support"
    logged = json.loads(caplog.records[-1].getMessage().split("jev shadow ", 1)[1])
    assert logged == {"name": "route", "jev": "billing", "confidence": 0.99, "legacy": "support"}


def test_example_rewrite_runs_against_the_helper(helper, monkeypatch):
    reply(monkeypatch, {"choice": "support", "probabilities": {"support": 0.9}})
    after = block("After:", "python").replace("from jev_decide import decide\n", "")
    ns = {"decide": helper.decide, "client": None}
    exec(compile(after, "example.py", "exec"), ns)
    assert ns["route_ticket"]("app crashes") == "support"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_typescript_helper_runs(tmp_path):
    src = block("### TypeScript helper", "ts") + """
let calls = 0;
globalThis.fetch = async (url, init) => {
  const body = JSON.parse(init.body);
  if (body.model !== "typesafe/jev-1.13" || body.questions.q.type !== "choice") throw new Error("bad body");
  return { ok: true, json: async () => ({ answers: { q: { choice: "billing", probabilities: { billing: 0.95 } } } }) };
};
process.env.OPENROUTER_API_KEY = "sk-test";
const q = { type: "choice", instructions: "Which team?", criteria: { billing: "money", support: "bugs" } } as const;
const a = await decide("charged twice", q, async () => { calls++; return "support"; });
globalThis.fetch = async () => ({ ok: false, status: 500, json: async () => ({}) });
const b = await decide("x", q, async () => { calls++; return "support"; });
console.log(JSON.stringify({ a, b, calls }));
"""
    path = tmp_path / "check.mts"
    path.write_text(src, encoding="utf-8")
    out = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(path)],
                         capture_output=True, text=True, timeout=60)
    if "Unknown or unexpected option" in out.stderr or "ERR_UNKNOWN_FILE_EXTENSION" in out.stderr:
        pytest.skip("node too old to strip TypeScript types")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip().splitlines()[-1]) == {"a": "billing", "b": "support", "calls": 1}


def test_frontmatter_and_size():
    assert TEXT.startswith("---\nname: jevvify-lite\ndescription: ")
    assert "reference/" not in TEXT  # truly single-file
    assert len(TEXT.splitlines()) < 400
