import ast
import importlib.util
import json
import sys
import textwrap
from types import SimpleNamespace as NS

from jevvify.analyzer import analyze_source
from jevvify.fsutil import RUNTIME_FILENAME
from jevvify.sandbox import install_runtime
from jevvify.translator import translate_source

SRC = textwrap.dedent('''
    """Module doc."""
    from __future__ import annotations
    import os
    from openai import OpenAI

    client = OpenAI()
    CALLS = []


    def triage(email):  # keep this comment
        return client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": f"Categorize as spam or ham: {email}"}],
        )


    def essay():
        return client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "Write an essay about a flower"}])
''')


def rewrite(src=SRC, threshold=0.85):
    return translate_source(src, analyze_source(src, "m.py"), threshold, directory_is_package=False)


def test_output_compiles_and_keeps_surroundings():
    out = rewrite()
    ast.parse(out)
    assert "# keep this comment" in out
    assert out.index("from __future__") < out.index("from _jevvify_rt import route as _jevvify_route")
    assert out.index("import os") < out.index("from _jevvify_rt")
    assert "Write an essay about a flower" in out and out.count("_jevvify_route(") == 1


def test_original_call_is_preserved_inside_lambda():
    out = rewrite()
    assert 'lambda: client.chat.completions.create(\n        model="gpt-4o"' in out
    assert "    return _jevvify_route(\n        'jev_" in out and "\n    )\n" in out


def test_package_directories_use_relative_import():
    out = translate_source(SRC, analyze_source(SRC, "m.py"), 0.9, directory_is_package=True)
    assert "from ._jevvify_rt import route as _jevvify_route" in out
    assert "threshold=0.9" in out


def test_no_candidates_returns_source_unchanged():
    src = "import openai\nx = 1\n"
    assert translate_source(src, analyze_source(src, "m.py"), 0.85, False) == src


def test_rewrite_is_idempotent():
    once = rewrite()
    assert all(c.status == "skipped" for c in analyze_source(once, "m.py"))
    assert translate_source(once, analyze_source(once, "m.py"), 0.85, False) == once


def test_non_ascii_source_offsets():
    src = textwrap.dedent('''
        import openai
        def f(client, t):
            label = "café ✓"; return client.chat.completions.create(model="m", messages=[{"role": "user", "content": f"Is {t} ok? yes or no"}])
    ''')
    out = rewrite(src)
    ast.parse(out)
    assert 'label = "café ✓"; return _jevvify_route(' in out


# -- behaviour of the rewritten code, executed against a fake SDK -----------------

def load_rewritten(tmp_path, monkeypatch):
    (tmp_path / "m.py").write_text(rewrite(), encoding="utf-8")
    install_runtime(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in ("m", "_jevvify_rt"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("m", tmp_path / "m.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (tmp_path / RUNTIME_FILENAME).exists()
    return mod


class StubClient:
    def __init__(self):
        self.calls = 0
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.calls += 1
        return NS(choices=[NS(message=NS(content="LEGACY"))])


def test_confident_jev_answer_skips_the_llm(tmp_path, monkeypatch, fake_jev):
    mod = load_rewritten(tmp_path, monkeypatch)
    mod.client = StubClient()
    fake_jev.reply = {"label": "spam", "confidence": 0.97, "p": 0}
    resp = mod.triage("buy now")
    assert resp.choices[0].message.content == "spam"
    assert mod.client.calls == 0
    state, questions = fake_jev.calls[0]
    assert state == {"email": "buy now"}
    assert list(questions["q"].criteria) == ["spam", "ham"]


def test_low_confidence_falls_back_to_llm(tmp_path, monkeypatch, fake_jev):
    mod = load_rewritten(tmp_path, monkeypatch)
    mod.client = StubClient()
    fake_jev.reply = {"label": "spam", "confidence": 0.60, "p": 0}
    assert mod.triage("hmm").choices[0].message.content == "LEGACY"
    assert mod.client.calls == 1


def test_jev_error_falls_back_to_llm(tmp_path, monkeypatch, fake_jev):
    mod = load_rewritten(tmp_path, monkeypatch)
    mod.client = StubClient()
    fake_jev.raise_exc = TimeoutError("boom")
    assert mod.triage("x").choices[0].message.content == "LEGACY"


def test_missing_sdk_falls_back_to_llm(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "typesafe_sdk", None)  # import raises ImportError
    mod = load_rewritten(tmp_path, monkeypatch)
    mod.client = StubClient()
    assert mod.triage("x").choices[0].message.content == "LEGACY"


def test_env_threshold_and_off_switch(tmp_path, monkeypatch, fake_jev):
    mod = load_rewritten(tmp_path, monkeypatch)
    mod.client = StubClient()
    fake_jev.reply = {"label": "ham", "confidence": 0.90, "p": 0}
    assert mod.triage("x").choices[0].message.content == "ham"
    monkeypatch.setenv("JEVVIFY_THRESHOLD", "0.95")
    assert mod.triage("x").choices[0].message.content == "LEGACY"
    monkeypatch.delenv("JEVVIFY_THRESHOLD")
    monkeypatch.setenv("JEVVIFY_MODE", "off")
    assert mod.triage("x").choices[0].message.content == "LEGACY"


def test_shadow_mode_returns_legacy_and_logs(tmp_path, monkeypatch, fake_jev):
    mod = load_rewritten(tmp_path, monkeypatch)
    mod.client = StubClient()
    log = tmp_path / "shadow.jsonl"
    monkeypatch.setenv("JEVVIFY_MODE", "shadow")
    monkeypatch.setenv("JEVVIFY_LOG", str(log))
    assert mod.triage("x").choices[0].message.content == "LEGACY"
    rec = json.loads(log.read_text().splitlines()[0])
    assert rec["jev_label"] == "spam" and rec["legacy_text"] == "LEGACY" and rec["id"].startswith("jev_")
