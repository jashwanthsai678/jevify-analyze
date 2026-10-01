"""`jevvify bench`: measure the prompt classifier against a labelled dataset.

Each JSONL row: {"id", "prompt", "judgment": bool, "kind": "choice"|"noul"|null, "labels": [...], "note"}.
"Predicted positive" means classify_prompt() accepted the prompt; the ``at_min_confidence`` numbers also require
the confidence level that `jevvify run` uses by default, i.e. what would actually be rewritten.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path

from .classify import assess, classify_prompt
from .models import level_for, meets


def default_dataset() -> Path | None:
    bundled = resources.files("jevvify") / "data" / "prompts.jsonl"
    if bundled.is_file():
        return Path(str(bundled))
    repo = Path(__file__).resolve().parents[2] / "benchmarks" / "prompts.jsonl"
    return repo if repo.exists() else None


@dataclass
class Scores:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def as_dict(self) -> dict:
        return asdict(self) | {"precision": round(self.precision, 4), "recall": round(self.recall, 4),
                               "f1": round(self.f1, 4)}


@dataclass
class BenchResult:
    rows: int
    detection: Scores
    at_min_confidence: Scores
    min_confidence: str
    label_exact: float  # among true positives: extracted labels equal the expected labels
    kind_accuracy: float
    errors: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"rows": self.rows, "min_confidence": self.min_confidence, "detection": self.detection.as_dict(),
                "at_min_confidence": self.at_min_confidence.as_dict(), "label_exact": round(self.label_exact, 4),
                "kind_accuracy": round(self.kind_accuracy, 4), "errors": self.errors}


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def run(rows: list[dict], min_confidence: str = "medium") -> BenchResult:
    det, gated = Scores(), Scores()
    label_hits = kind_hits = tp_rows = 0
    errors = []
    for row in rows:
        kind, options, why = classify_prompt(row["prompt"])
        predicted = kind is not None
        level = ""
        if predicted:
            conf, _ = assess(row["prompt"], kind or "", options, why)
            level = level_for(conf)
        gated_pred = predicted and meets(level, min_confidence)
        truth = bool(row["judgment"])
        for scores, pred in ((det, predicted), (gated, gated_pred)):
            if pred and truth:
                scores.tp += 1
            elif pred and not truth:
                scores.fp += 1
            elif truth:
                scores.fn += 1
            else:
                scores.tn += 1
        if predicted and truth:
            tp_rows += 1
            kind_hits += kind == row.get("kind")
            label_hits += [o.lower() for o in options] == [lbl.lower() for lbl in row.get("labels") or []]
        if predicted != truth or (predicted and truth and kind != row.get("kind")):
            errors.append({"id": row.get("id"), "expected": truth, "predicted": predicted, "kind": kind,
                           "labels": options, "level": level, "why": why, "note": row.get("note", "")})
    return BenchResult(len(rows), det, gated, min_confidence,
                       label_hits / tp_rows if tp_rows else 0.0, kind_hits / tp_rows if tp_rows else 0.0, errors)


def render(result: BenchResult, fmt: str, show_errors: bool = False) -> str:
    if fmt == "json":
        return json.dumps(result.as_dict(), indent=2)
    d, g = result.detection, result.at_min_confidence
    lines = [
        f"Prompt classifier benchmark: {result.rows} labelled prompts", "",
        "| | precision | recall | F1 | TP | FP | FN | TN |", "|---|---|---|---|---|---|---|---|",
        f"| detection | {d.precision:.1%} | {d.recall:.1%} | {d.f1:.2f} | {d.tp} | {d.fp} | {d.fn} | {d.tn} |",
        f"| rewritten at --min-confidence {result.min_confidence} | {g.precision:.1%} | {g.recall:.1%} | "
        f"{g.f1:.2f} | {g.tp} | {g.fp} | {g.fn} | {g.tn} |", "",
        f"Among correctly detected prompts: kind correct {result.kind_accuracy:.1%}, "
        f"labels extracted exactly {result.label_exact:.1%}.",
    ]
    if show_errors and result.errors:
        lines += ["", "Misclassified:"]
        for e in result.errors:
            exp = "judgment" if e["expected"] else "generative"
            got = f"{e['kind']} {e['labels']} ({e['level']})" if e["predicted"] else e["why"]
            lines.append(f"- {e['id']}: expected {exp}, got {got}. {e['note']}")
    return "\n".join(lines)
