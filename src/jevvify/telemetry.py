"""`jevvify stats`: summarise runtime logs (shadow, and live with JEVVIFY_LOG_LIVE=1) per call site.

Shadow records hold both answers, so they give agreement; live records give fallback rate and latency.
The threshold sweep answers "what if the threshold were X": how many calls Jev would answer, and how often
it would agree with the LLM on those.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .evaluator import normalize_label

SWEEP = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95)
BUCKETS = ((0.0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 0.95), (0.95, 1.01))


@dataclass
class SiteStats:
    id: str
    records: int = 0
    shadow: int = 0
    errors: int = 0
    jev_answers: int = 0  # Jev returned a label at or above the threshold in force
    fallback_rate: float | None = None
    mean_confidence: float | None = None
    compared: int = 0  # shadow records where both answers could be read
    agreement: float | None = None
    jev_ms_p50: float | None = None
    jev_ms_p95: float | None = None
    legacy_ms_p50: float | None = None
    confidence_histogram: dict[str, int] = field(default_factory=dict)
    sweep: list[dict] = field(default_factory=list)


def load_records(paths: list[Path]) -> list[dict]:
    records = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("id"):
                records.append(rec)
    return records


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))], 2)


def summarize(records: list[dict], threshold: float | None = None) -> list[SiteStats]:
    by_id: dict[str, list[dict]] = {}
    for rec in records:
        by_id.setdefault(rec["id"], []).append(rec)
    out = []
    for cid, recs in sorted(by_id.items()):
        s = SiteStats(cid, records=len(recs))
        confs = [float(r.get("confidence") or 0) for r in recs if r.get("jev_label") is not None]
        s.errors = sum(1 for r in recs if r.get("error"))
        s.shadow = sum(1 for r in recs if r.get("mode") == "shadow" or "legacy_text" in r)
        thr = lambda r: threshold if threshold is not None else float(r.get("threshold", 0.85))  # noqa: E731
        s.jev_answers = sum(1 for r in recs if r.get("jev_label") is not None and
                            float(r.get("confidence") or 0) >= thr(r))
        s.fallback_rate = round(1 - s.jev_answers / len(recs), 4)
        s.mean_confidence = round(sum(confs) / len(confs), 4) if confs else None
        s.jev_ms_p50 = _pct([float(r["jev_ms"]) for r in recs if r.get("jev_ms") is not None], 0.5)
        s.jev_ms_p95 = _pct([float(r["jev_ms"]) for r in recs if r.get("jev_ms") is not None], 0.95)
        s.legacy_ms_p50 = _pct([float(r["legacy_ms"]) for r in recs if r.get("legacy_ms") is not None], 0.5)
        for lo, hi in BUCKETS:
            s.confidence_histogram[f"{lo:.2f}-{min(hi, 1.0):.2f}"] = sum(1 for c in confs if lo <= c < hi)

        pairs = []  # (confidence, agrees) for shadow records with both answers
        for r in recs:
            if r.get("jev_label") is None or "legacy_text" not in r:
                continue
            legacy = normalize_label(r.get("legacy_text"), list(r.get("options") or []), r.get("kind"))
            if legacy is None:
                continue
            pairs.append((float(r.get("confidence") or 0), str(r["jev_label"]) == legacy))
        s.compared = len(pairs)
        if pairs:
            accepted = [ok for conf, ok in pairs if conf >= (threshold if threshold is not None else 0.85)]
            s.agreement = round(sum(accepted) / len(accepted), 4) if accepted else None
            for t in SWEEP:
                acc = [ok for conf, ok in pairs if conf >= t]
                s.sweep.append({"threshold": t, "jev_share": round(len(acc) / len(pairs), 4),
                                "agreement": round(sum(acc) / len(acc), 4) if acc else None})
        out.append(s)
    return out


def render(stats: list[SiteStats], fmt: str) -> str:
    if fmt == "json":
        return json.dumps([asdict(s) for s in stats], indent=2)
    if fmt == "csv":
        buf = io.StringIO()
        cols = ["id", "records", "shadow", "errors", "jev_answers", "fallback_rate", "mean_confidence", "compared",
                "agreement", "jev_ms_p50", "jev_ms_p95", "legacy_ms_p50"]
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(cols)
        for s in stats:
            w.writerow(["" if getattr(s, c) is None else getattr(s, c) for c in cols])
        return buf.getvalue()

    def f(v: float | None, pct: bool = True) -> str:
        if v is None:
            return "-"
        return f"{v:.1%}" if pct else f"{v:g}"

    lines = ["| call site | records | Jev answered | fallback | agreement (shadow) | conf. mean | Jev p50/p95 ms |",
             "|---|---|---|---|---|---|---|"]
    for s in stats:
        lines.append(f"| {s.id} | {s.records} | {s.jev_answers} | {f(s.fallback_rate)} | "
                     f"{f(s.agreement)} (n={s.compared}) | {f(s.mean_confidence, False)} | "
                     f"{f(s.jev_ms_p50, False)}/{f(s.jev_ms_p95, False)} |")
    for s in stats:
        if s.sweep:
            lines += ["", f"Threshold sweep for {s.id} (shadow records):", "",
                      "| threshold | share answered by Jev | agreement with LLM |", "|---|---|---|"]
            lines += [f"| {row['threshold']} | {f(row['jev_share'])} | {f(row['agreement'])} |" for row in s.sweep]
    if not stats:
        lines = ["No jevvify log records found. Run with JEVVIFY_MODE=shadow (or JEVVIFY_LOG_LIVE=1) first."]
    return "\n".join(lines)
