import io
import json
import urllib.error

import pytest

from jevvify.runtime_loader import load_runtime


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def rt(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    return load_runtime()


def capture(monkeypatch, answers):
    sent = {}

    def fake_urlopen(req, timeout):
        sent["url"], sent["timeout"] = req.full_url, timeout
        sent["headers"] = {k.lower(): v for k, v in req.header_items()}
        sent["body"] = json.loads(req.data)
        return FakeResponse(json.dumps({"answers": answers}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return sent


def test_choice_request_matches_documented_format(rt, monkeypatch):
    sent = capture(monkeypatch, {"q": {"choice": "billing", "probabilities": {"billing": 0.91, "support": 0.09}}})
    label, conf = rt.ask_jev("choice", "Which team?", ["billing", "support"], {"email": "I was charged twice"})
    assert (label, conf) == ("billing", 0.91)
    assert sent["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert sent["headers"]["authorization"] == "Bearer sk-test"
    assert sent["body"] == {
        "model": "typesafe/jev-1.13",
        "state": "email: I was charged twice",
        "questions": {"q": {"type": "choice", "instructions": "Which team?",
                            "criteria": {"billing": "billing", "support": "support"}}},
    }


def test_noul_maps_probability_to_the_positive_option(rt, monkeypatch):
    sent = capture(monkeypatch, {"q": {"noul": 0.07}})
    label, conf = rt.ask_jev("noul", "Is it spam?", ["yes", "no"], {"t": "hi"})
    assert label == "no" and conf == pytest.approx(0.93)
    assert sent["body"]["questions"]["q"]["criteria"] == {"true": "yes", "false": "no"}
    capture(monkeypatch, {"q": {"noul": 0.9}})
    assert rt.ask_jev("noul", "Is it spam?", ["yes", "no"], {"t": "hi"}) == ("yes", 0.9)


def test_multiple_inputs_are_labelled_lines(rt, monkeypatch):
    sent = capture(monkeypatch, {"q": {"noul": 0.5}})
    rt.ask_jev("noul", "?", ["true", "false"], {"subject": "S", "body": "B"})
    assert sent["body"]["state"] == "subject: S\nbody: B"


def test_http_failure_falls_back_to_the_llm(rt, monkeypatch):
    def boom(req, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    called = []
    result = rt.route("jev_x", {"t": "x"}, lambda: called.append(1) or "LEGACY",
                      kind="noul", instructions="?", options=["yes", "no"], shape="openai")
    assert result == "LEGACY" and called == [1]


def test_sdk_is_used_when_no_openrouter_key(monkeypatch, fake_jev):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    rt = load_runtime()
    fake_jev.reply = {"label": "ham", "confidence": 0.9, "p": 0}
    assert rt.ask_jev("choice", "?", ["spam", "ham"], {"t": "x"}) == ("ham", 0.9)
