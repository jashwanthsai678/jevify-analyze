import json
from pathlib import Path

from jevvify import benchmark
from jevvify.cli import main
from jevvify.telemetry import load_records, render, summarize

ROOT = Path(__file__).parent.parent


def write_log(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")


def rec(conf, jev, legacy, **kw):
    return {"id": "jev_a", "mode": "shadow", "kind": "choice", "options": ["spam", "ham"], "threshold": 0.85,
            "jev_label": jev, "confidence": conf, "error": None, "jev_ms": 12.0, "legacy_ms": 700.0,
            "legacy_text": legacy, **kw}


def test_summary_agreement_fallback_and_sweep(tmp_path):
    log = tmp_path / "l.jsonl"
    write_log(log, [rec(0.95, "spam", "Spam."), rec(0.9, "ham", "spam"), rec(0.6, "spam", "spam"),
                    rec(0.0, None, "ham", error="TimeoutError")])
    [s] = summarize(load_records([log]))
    assert (s.records, s.jev_answers, s.errors, s.compared) == (4, 2, 1, 3)
    assert s.fallback_rate == 0.5 and s.agreement == 0.5  # of the two accepted answers, one agrees
    sweep = {row["threshold"]: row for row in s.sweep}
    assert sweep[0.5]["jev_share"] == 1.0 and sweep[0.95]["agreement"] == 1.0
    assert s.jev_ms_p50 == 12.0 and s.legacy_ms_p50 == 700.0
    assert "Threshold sweep" in render([s], "text")
    assert render([s], "csv").splitlines()[0].startswith("id,records")


def test_threshold_override_and_empty(tmp_path):
    log = tmp_path / "l.jsonl"
    write_log(log, [rec(0.9, "spam", "spam")])
    assert summarize(load_records([log]), threshold=0.95)[0].jev_answers == 0
    assert "No jevvify log records" in render([], "text")


def test_stats_cli(tmp_path, capsys):
    log = tmp_path / "l.jsonl"
    write_log(log, [rec(0.95, "spam", "spam")])
    assert main(["stats", str(log), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["agreement"] == 1.0
    assert main(["stats", str(tmp_path / "missing.jsonl")]) == 2


def test_bundled_benchmark_quality_gate():
    """Regression gate on the labelled prompt set. Lower these only with a written reason."""
    result = benchmark.run(benchmark.load(ROOT / "benchmarks" / "prompts.jsonl"))
    assert result.rows >= 100
    assert result.detection.precision >= 0.95
    assert result.detection.recall >= 0.90
    assert result.at_min_confidence.precision >= 0.97
    assert result.label_exact >= 0.9


def test_benchmark_rows_are_well_formed():
    for name in ("prompts.jsonl", "holdout.jsonl"):
        path = ROOT / "benchmarks" / name
        if not path.exists():
            continue
        rows = benchmark.load(path)
        assert len({r["id"] for r in rows}) == len(rows)
        for r in rows:
            assert "`" in r["prompt"], r["id"]
            assert (r["kind"] is None) == (not r["judgment"]), r["id"]


def test_bench_cli_gates(capsys):
    assert main(["bench", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["rows"] >= 100 and "precision" in data["detection"]
    assert main(["bench", "--min-precision", "1.01"]) == 1
