import json
import threading

from jevvify.evaluator import Observation, evaluate, load_shadow_log, normalize_label, run_samples
from jevvify.models import Candidate


def cand(cid="jev_1", kind="choice", options=("spam", "ham")):
    return Candidate(id=cid, file="a.py", line=1, end_line=1, col=0, end_col=1, provider="openai",
                     status="candidate", reason="", kind=kind, options=list(options))


def test_normalize_label():
    opts = ["spam", "ham"]
    assert normalize_label("Spam.", opts, "choice") == "spam"
    assert normalize_label('{"label": "ham"}', opts, "choice") == "ham"
    assert normalize_label("I think this is spam", opts, "choice") == "spam"
    assert normalize_label("spam or ham, hard to say", opts, "choice") is None
    assert normalize_label("Yes, it is", ["yes", "no"], "noul") == "yes"
    assert normalize_label("false", ["true", "false"], "noul") == "false"
    assert normalize_label('{"urgent": true}', ["true", "false"], "noul") == "true"
    assert normalize_label(None, opts, "choice") is None


def test_gate_passes_at_error_budget_and_counts_fallbacks():
    obs = [Observation("jev_1", "spam", 0.95, "spam") for _ in range(19)]
    obs += [Observation("jev_1", "ham", 0.95, "spam")]          # 1 disagreement of 20 -> 5%
    obs += [Observation("jev_1", "spam", 0.50, "spam")]         # fallback, not scored
    ev = evaluate([cand()], obs, threshold=0.85, max_error_rate=0.05)["jev_1"]
    assert (ev.n, ev.accepted, ev.fallbacks, ev.scored, ev.disagreements) == (21, 20, 1, 20, 1)
    assert ev.status == "pass" and abs(ev.error_rate - 0.05) < 1e-9


def test_gate_fails_above_error_budget():
    obs = [Observation("jev_1", "ham", 0.99, "spam")] * 3 + [Observation("jev_1", "spam", 0.99, "spam")] * 7
    ev = evaluate([cand()], obs, 0.85, max_error_rate=0.05)["jev_1"]
    assert ev.status == "fail" and "exceeds" in ev.notes[0]


def test_expected_label_beats_legacy_label():
    obs = [Observation("jev_1", "ham", 0.99, legacy_label="spam", expected="ham")]
    assert evaluate([cand()], obs, 0.85)["jev_1"].status == "pass"


def test_no_evidence_is_unverified_not_pass():
    assert evaluate([cand()], [], 0.85)["jev_1"].status == "unverified"
    only_fallbacks = [Observation("jev_1", None, 0.0, "spam", error="boom")]
    assert evaluate([cand()], only_fallbacks, 0.85)["jev_1"].status == "unverified"


def test_shadow_log_roundtrip(tmp_path):
    log = tmp_path / "l.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in [
        {"id": "jev_1", "jev_label": "spam", "confidence": 0.9, "legacy_text": "Spam"},
        {"id": "other", "jev_label": "x", "confidence": 1, "legacy_text": "x"},
    ]) + "\nnot json\n")
    [o] = load_shadow_log(log, {"jev_1": cand()})
    assert (o.jev_label, o.legacy_label) == ("spam", "spam")


def test_run_samples_runs_both_pipelines_concurrently():
    barrier = threading.Barrier(2, timeout=5)  # only passes if legacy and jev run at the same time

    def jev(c, state):
        barrier.wait()
        return ("spam", 0.9)

    def legacy(c, state):
        barrier.wait()
        return "SPAM"

    rows = [{"candidate": "jev_1", "state": {"t": "x"}, "legacy": "ignored"}]
    [o] = run_samples([cand()], rows, jev_fn=jev, legacy_fn=legacy, workers=1)
    assert (o.jev_label, o.legacy_label, o.error) == ("spam", "spam", None)


def test_run_samples_replays_recorded_legacy_by_default():
    rows = [{"candidate": "jev_1", "state": {"t": "x"}, "legacy": "Ham", "expected": "ham"}]
    [o] = run_samples([cand()], rows, jev_fn=lambda c, s: ("ham", 0.99))
    assert (o.legacy_label, o.expected) == ("ham", "ham")
