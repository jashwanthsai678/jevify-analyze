"""Phase 3: shadow evaluation of Jev against the legacy LLM, and the promotion gate.

Evidence comes from two places, both optional:
  * a shadow log written by the runtime while the project's tests run with JEVIFY_MODE=shadow
  * a samples file (JSONL) replayed here, running the legacy and Jev functions concurrently:
      {"candidate": "jev_ab12cd34", "state": {...}, "legacy": "spam", "expected": "spam"}
    ``legacy`` is a recorded output of the old LLM call; ``expected`` is optional ground truth.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .models import Candidate


@dataclass
class Observation:
    candidate_id: str
    jev_label: str | None
    confidence: float
    legacy_label: str | None
    expected: str | None = None
    error: str | None = None


@dataclass
class CandidateEval:
    candidate_id: str
    n: int = 0
    accepted: int = 0  # Jev answered with confidence >= threshold
    fallbacks: int = 0  # below threshold or Jev error: the LLM would have been called
    scored: int = 0  # accepted answers that have a reference label
    disagreements: int = 0
    mean_confidence: float = 0.0
    error_rate: float | None = None
    status: str = "unverified"  # pass | fail | unverified
    notes: list[str] = field(default_factory=list)

    @property
    def fallback_rate(self) -> float | None:
        return self.fallbacks / self.n if self.n else None


# -- label normalisation -------------------------------------------------------

_TRUE = {"true", "yes", "1", "y"}
_FALSE = {"false", "no", "0", "n"}


def normalize_label(text: str | None, options: list[str], kind: str | None) -> str | None:
    """Map free-form legacy model output onto one of ``options`` (None if ambiguous)."""
    if text is None:
        return None
    raw = text.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and len(parsed) == 1:
            parsed = next(iter(parsed.values()))
        if isinstance(parsed, bool):
            raw = "true" if parsed else "false"
        elif isinstance(parsed, (str, int, float)):
            raw = str(parsed)
    except ValueError:
        pass
    low = raw.strip().strip("`'\".! ").lower()
    by_lower = {o.lower(): o for o in options}
    if low in by_lower:
        return by_lower[low]
    if kind == "noul":
        word = low.split()[0] if low.split() else ""
        pos, neg = options[0], options[1]
        if low in _TRUE or word in _TRUE:
            return pos
        if low in _FALSE or word in _FALSE:
            return neg
    hits = [(m.start(), o) for o in options for m in [re.search(rf"\b{re.escape(o.lower())}\b", low)] if m]
    if len(hits) == 1:
        return hits[0][1]
    return None


# -- evidence collection -------------------------------------------------------

def load_shadow_log(path: Path, by_id: dict[str, Candidate]) -> list[Observation]:
    path = Path(path)
    if not path.exists():
        return []
    out: list[Observation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        cand = by_id.get(rec.get("id"))
        if cand is None:
            continue
        out.append(Observation(
            candidate_id=cand.id, jev_label=rec.get("jev_label"), confidence=float(rec.get("confidence") or 0.0),
            legacy_label=normalize_label(rec.get("legacy_text"), cand.options, cand.kind), error=rec.get("error"),
        ))
    return out


def load_samples(path: Path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def run_samples(
    candidates: list[Candidate],
    samples: list[dict],
    jev_fn: Callable[[Candidate, dict], tuple[str, float]] | None = None,
    legacy_fn: Callable[[Candidate, dict], str | None] | None = None,
    workers: int = 8,
) -> list[Observation]:
    """Run the legacy and Jev pipelines side by side on every sample."""
    by_id = {c.id: c for c in candidates}
    if jev_fn is None:
        from .runtime_loader import load_runtime

        rt = load_runtime()
        jev_fn = lambda c, state: rt.ask_jev(c.kind, c.instructions, c.options, state)  # noqa: E731
    if legacy_fn is None:
        legacy_fn = lambda c, state: state.get("__legacy__")  # replay of recorded output  # noqa: E731

    def one(pool: ThreadPoolExecutor, row: dict) -> Observation | None:
        cand = by_id.get(row.get("candidate"))
        if cand is None:
            return None
        state = row.get("state", {})
        legacy_state = {**state, "__legacy__": row.get("legacy")}
        f_legacy = pool.submit(legacy_fn, cand, legacy_state)
        f_jev = pool.submit(jev_fn, cand, state)
        error, label, conf = None, None, 0.0
        try:
            label, conf = f_jev.result()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        try:
            legacy = normalize_label(f_legacy.result(), cand.options, cand.kind)
        except Exception as exc:
            legacy, error = None, error or f"legacy: {type(exc).__name__}: {exc}"
        expected = normalize_label(row.get("expected"), cand.options, cand.kind) if row.get("expected") else None
        return Observation(cand.id, label, conf, legacy, expected, error)

    with ThreadPoolExecutor(max_workers=workers * 2) as pool, ThreadPoolExecutor(max_workers=workers) as outer:
        results = list(outer.map(lambda r: one(pool, r), samples))
    return [r for r in results if r is not None]


# -- scoring and gate ------------------------------------------------------------

def evaluate(
    candidates: list[Candidate],
    observations: list[Observation],
    threshold: float,
    max_error_rate: float = 0.05,
    min_samples: int = 1,
) -> dict[str, CandidateEval]:
    results = {c.id: CandidateEval(c.id) for c in candidates if c.status == "candidate"}
    conf_sums: dict[str, float] = {cid: 0.0 for cid in results}
    for obs in observations:
        ev = results.get(obs.candidate_id)
        if ev is None:
            continue
        ev.n += 1
        if obs.jev_label is None or obs.confidence < threshold:
            ev.fallbacks += 1
            continue
        ev.accepted += 1
        conf_sums[ev.candidate_id] += obs.confidence
        truth = obs.expected or obs.legacy_label
        if truth is None:
            continue
        ev.scored += 1
        if obs.jev_label != truth:
            ev.disagreements += 1
    for ev in results.values():
        ev.mean_confidence = conf_sums[ev.candidate_id] / ev.accepted if ev.accepted else 0.0
        if ev.n == 0:
            ev.notes.append("no shadow evidence collected")
        elif ev.scored < min_samples:
            ev.notes.append(f"only {ev.scored} scored answers (need {min_samples})")
        else:
            ev.error_rate = ev.disagreements / ev.scored
            ev.status = "pass" if ev.error_rate <= max_error_rate else "fail"
            if ev.status == "fail":
                ev.notes.append(f"error rate {ev.error_rate:.1%} exceeds {max_error_rate:.1%}")
    return results


# -- sandbox checks ----------------------------------------------------------------

def check_syntax(paths: list[Path]) -> dict[Path, str]:
    """Return {path: error} for every file that no longer compiles."""
    bad = {}
    for p in paths:
        try:
            compile(Path(p).read_bytes(), str(p), "exec")
        except (SyntaxError, ValueError) as exc:
            bad[p] = str(exc)
    return bad


def run_test_command(cmd: str, cwd: Path, env: dict[str, str], timeout: int = 900) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, shell=True, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-15:]
    return proc.returncode == 0, "\n".join(tail)
