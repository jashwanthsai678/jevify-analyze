"""Reports: markdown (stdout), JSON, CSV and a self-contained HTML page, plus `analyze` listings.

Cost and latency figures are projections from explicit, adjustable assumptions, never measurements.
"""

from __future__ import annotations

import csv
import html
import io
import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from . import __version__
from .evaluator import CandidateEval
from .models import Candidate

if TYPE_CHECKING:
    from .pipeline import RunResult


@dataclass
class Assumptions:
    monthly_calls_per_site: int = 10_000
    avg_input_tokens: int = 400
    avg_output_tokens: int = 20
    price_in_per_mtok: float = 2.50
    price_out_per_mtok: float = 10.00
    legacy_latency_ms: float = 800.0
    jev_latency_ms: float = 15.0
    jev_cost_ratio: float = 1 / 400  # TypeSafe's published claim: ~400x cheaper than an LLM
    assumed_fallback_rate: float = 0.10  # used only when no shadow data exists


@dataclass
class Economics:
    fallback_rate: float
    fallback_observed: bool
    legacy_cost_per_call: float
    monthly_before: float
    monthly_after: float
    effective_latency_ms: float
    effective_speedup: float
    best_case_speedup: float

    @property
    def monthly_saving(self) -> float:
        return self.monthly_before - self.monthly_after


def project_economics(refactored: int, evals: dict[str, CandidateEval], a: Assumptions) -> Economics:
    n = sum(e.n for e in evals.values())
    fb = sum(e.fallbacks for e in evals.values())
    observed = n > 0
    rate = fb / n if observed else a.assumed_fallback_rate
    legacy = a.avg_input_tokens * a.price_in_per_mtok / 1e6 + a.avg_output_tokens * a.price_out_per_mtok / 1e6
    jev = legacy * a.jev_cost_ratio
    calls = refactored * a.monthly_calls_per_site
    eff_ms = a.jev_latency_ms + rate * a.legacy_latency_ms  # a fallback pays for Jev first, then the LLM
    return Economics(
        fallback_rate=rate, fallback_observed=observed, legacy_cost_per_call=legacy,
        monthly_before=calls * legacy, monthly_after=calls * (jev + rate * legacy),
        effective_latency_ms=eff_ms, effective_speedup=a.legacy_latency_ms / eff_ms,
        best_case_speedup=a.legacy_latency_ms / a.jev_latency_ms,
    )


# -- per-call-site outcome ------------------------------------------------------------

def outcomes(result: RunResult) -> dict[str, str]:
    """id -> refactored | would-refactor | blocked | manual | skipped."""
    promoted = {c.id for c in result.promoted}
    blocked = {c.id for c, _ in result.blocked}
    manual = {c.id for c in result.manual}
    out = {}
    for c in result.candidates:
        if c.id in promoted:
            out[c.id] = "would-refactor" if result.dry_run else "refactored"
        elif c.id in blocked:
            out[c.id] = "blocked"
        elif c.id in manual:
            out[c.id] = "manual"
        else:
            out[c.id] = "skipped"
    return out


def _evidence(ev: CandidateEval | None) -> str:
    if not ev or ev.status == "unverified":
        return "unverified"
    rate = f"{ev.error_rate:.1%}" if ev.error_rate is not None else "n/a"
    fallback = f"{ev.fallback_rate:.0%}" if ev.fallback_rate is not None else "n/a"
    return f"{ev.status}: {ev.scored} scored, disagreement {rate}, fallback {fallback}"


def _skip_groups(cands: list[Candidate]) -> list[tuple[str, int, list[Candidate]]]:
    groups: dict[str, list[Candidate]] = {}
    for c in cands:
        groups.setdefault(c.reason_code or "other", []).append(c)
    return sorted(((k, len(v), v) for k, v in groups.items()), key=lambda g: -g[1])


_SKIP_EXPLANATIONS = {
    "generative": "the prompt asks for free text (write, summarize, explain...), which needs an LLM",
    "no-label-space": "no closed set of answers (labels or yes/no) was found in the prompt",
    "no-dynamic-input": "the prompt is constant, so there is nothing per-call to classify",
    "low-confidence": "detected as a decision, but the evidence was too weak for --min-confidence",
    "async": "Python async calls are not rewritten automatically yet",
    "streaming": "streaming responses are left alone",
    "tool-calling": "tool or function calling is not a single decision",
    "no-prompt": "the prompt could not be found statically (built elsewhere?): review by hand",
    "structured-extraction": "returns a structured object, not one label",
    "sdk-promise-helpers": "the code uses SDK-specific helpers on the returned promise",
}


# -- markdown ---------------------------------------------------------------------

def render_report(result: RunResult, assumptions: Assumptions) -> str:
    cands = result.candidates
    out = outcomes(result)
    skipped = [c for c in cands if out[c.id] == "skipped"]
    judged = [c for c in cands if c.status == "candidate" or c.reason_code == "low-confidence"]
    eco = project_economics(len(result.promoted), result.evals, assumptions)
    verified = sum(1 for c in result.promoted if result.evals.get(c.id) and result.evals[c.id].status == "pass")
    langs = Counter(c.language for c in cands)
    lines = [
        "# jevvify report", "",
        f"- LLM call sites found: **{len(cands)}**"
        + (f" ({', '.join(f'{n} {lang}' for lang, n in sorted(langs.items()))})" if langs else ""),
        f"- Look like decisions: **{len(judged)}**",
        f"- Refactored to Jev with LLM fallback: **{len(result.promoted)}**"
        + (" (dry run: nothing written)" if result.dry_run else ""),
        f"- Verified against shadow data: **{verified}** of {len(result.promoted)}",
        f"- Manual rewrite needed: **{len(result.manual)}**   Blocked: **{len(result.blocked)}**   "
        f"Skipped: **{len(skipped)}**",
        f"- Confidence threshold at runtime: **{result.threshold:g}** (below it, the original LLM call runs)", "",
    ]
    if result.promoted:
        lines += ["## Refactored" if not result.dry_run else "## Would refactor", "",
                  "| id | location | lang | kind | labels | detection | evidence |", "|---|---|---|---|---|---|---|"]
        for c in result.promoted:
            lines.append(f"| {c.id} | {c.location} | {c.language} | {c.kind} | {', '.join(c.options)} | "
                         f"{c.level} ({c.confidence:.2f}) | {_evidence(result.evals.get(c.id))} |")
        lines.append("")
    if result.manual:
        lines += ["## Manual rewrite needed", "", "Detected as decisions in a language without automatic rewrite. "
                  "See docs/languages.md for the Jev-first pattern.", ""]
        lines += [f"- `{c.location}` ({c.language}, {c.kind}: {', '.join(c.options)}, {c.level})"
                  for c in result.manual] + [""]
    if result.blocked:
        lines += ["## Blocked", ""] + [f"- `{c.location}` ({c.id}): {why}" for c, why in result.blocked] + [""]
    if skipped:
        lines += ["## Skipped, and why", ""]
        for code, count, group in _skip_groups(skipped):
            where = ", ".join(f"`{c.location}`" for c in group[:5]) + (" ..." if count > 5 else "")
            lines.append(f"- **{code}** ({count}): {_SKIP_EXPLANATIONS.get(code, group[0].reason)}. {where}")
        lines.append("")
    if result.promoted:
        a = assumptions
        src = "observed" if eco.fallback_observed else f"assumed ({a.assumed_fallback_rate:.0%}, no shadow data)"
        lines += [
            "## Projected impact (estimates, not measurements)", "",
            f"- Fallback rate: {eco.fallback_rate:.1%} ({src})",
            f"- Latency per call: {a.legacy_latency_ms:.0f} ms -> ~{eco.effective_latency_ms:.0f} ms "
            f"(**{eco.effective_speedup:.1f}x** effective; {eco.best_case_speedup:.0f}x only if nothing falls back)",
            f"- Monthly LLM spend on these sites: ${eco.monthly_before:,.2f} -> ${eco.monthly_after:,.2f} "
            f"(saves **${eco.monthly_saving:,.2f}**/month)",
            f"- Assumptions: {a.monthly_calls_per_site:,} calls/site/month, {a.avg_input_tokens} in / "
            f"{a.avg_output_tokens} out tokens, ${a.price_in_per_mtok}/${a.price_out_per_mtok} per M tokens, "
            f"Jev cost = LLM cost x {a.jev_cost_ratio:.4f} and ~{a.jev_latency_ms:.0f} ms (vendor claims). "
            "Tune with --monthly-calls and the other flags.", "",
        ]
    if result.warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in result.warnings] + [""]
    if result.notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in result.notes] + [""]
    if result.written:
        lines += ["## Files written", ""] + [f"- {w}" for w in result.written] + [
            "", "Originals are saved in `.jevvify/backup/`. "
            "Set `JEVVIFY_MODE=off` to force the legacy path at runtime.", ""]
    return "\n".join(lines)


# -- machine-readable ---------------------------------------------------------------

def result_to_dict(result: RunResult, assumptions: Assumptions) -> dict:
    out = outcomes(result)
    blocked = dict((c.id, why) for c, why in result.blocked)
    eco = project_economics(len(result.promoted), result.evals, assumptions)
    sites = []
    for c in result.candidates:
        ev = result.evals.get(c.id)
        sites.append({**c.to_dict(), "outcome": out[c.id], "blocked_reason": blocked.get(c.id),
                      "evidence": asdict(ev) | {"fallback_rate": ev.fallback_rate} if ev else None})
    return {
        "tool": "jevvify", "version": __version__, "dry_run": result.dry_run, "threshold": result.threshold,
        "summary": dict(Counter(out.values())) | {"call_sites": len(result.candidates)},
        "call_sites": sites,
        "projection": asdict(eco) | {"monthly_saving": eco.monthly_saving, "note": "estimate, not a measurement"},
        "assumptions": asdict(assumptions),
        "warnings": result.warnings, "notes": result.notes, "written": result.written,
    }


CSV_FIELDS = ["id", "file", "line", "language", "provider", "outcome", "status", "reason_code", "reason", "kind",
              "labels", "confidence", "level", "evidence_status", "scored", "disagreement_rate", "fallback_rate"]


def candidates_to_csv(cands: list[Candidate], outcome: dict[str, str] | None = None,
                      evals: dict[str, CandidateEval] | None = None) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, lineterminator="\n")
    w.writeheader()
    for c in cands:
        ev = (evals or {}).get(c.id)
        w.writerow({
            "id": c.id, "file": c.file, "line": c.line, "language": c.language, "provider": c.provider,
            "outcome": (outcome or {}).get(c.id, c.status), "status": c.status, "reason_code": c.reason_code,
            "reason": c.reason, "kind": c.kind or "", "labels": "|".join(c.options),
            "confidence": f"{c.confidence:.2f}" if c.status == "candidate" or c.confidence else "",
            "level": c.level, "evidence_status": ev.status if ev else "",
            "scored": ev.scored if ev else "", "disagreement_rate": "" if not ev or ev.error_rate is None
            else f"{ev.error_rate:.4f}", "fallback_rate": "" if not ev or ev.fallback_rate is None
            else f"{ev.fallback_rate:.4f}",
        })
    return buf.getvalue()


def result_to_csv(result: RunResult) -> str:
    return candidates_to_csv(result.candidates, outcomes(result), result.evals)


# -- HTML ------------------------------------------------------------------------------

_HTML_STYLE = """
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--card:#fff;--line:#e7e5e4;--accent:#2563eb;
--ok:#15803d;--warn:#b45309;--bad:#b91c1c;--skip:#a8a29e}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--card:#292524;
--line:#44403c;--accent:#60a5fa;--ok:#4ade80;--warn:#fbbf24;--bad:#f87171;--skip:#78716c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}main{max-width:1100px;margin:0 auto;padding:32px 16px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 12px}.muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.card b{display:block;font-size:26px;font-variant-numeric:tabular-nums}.bar{display:flex;height:14px;
border-radius:7px;overflow:hidden;margin:18px 0 6px;background:var(--line)}.legend span{margin-right:14px}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;
overflow:hidden;font-size:13.5px}th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;
vertical-align:top}th{color:var(--muted);font-weight:600}.wrap{overflow-x:auto}code{font-size:12.5px}
.pill{padding:1px 8px;border-radius:9px;font-size:12px;border:1px solid var(--line);white-space:nowrap}
.note{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--warn);padding:10px 14px;
border-radius:8px}
"""
_COLORS = {"refactored": "var(--ok)", "would-refactor": "var(--accent)", "manual": "var(--warn)",
           "blocked": "var(--bad)", "skipped": "var(--skip)"}


def result_to_html(result: RunResult, assumptions: Assumptions) -> str:
    e = html.escape
    out = outcomes(result)
    counts = Counter(out.values())
    total = max(1, len(result.candidates))
    eco = project_economics(len(result.promoted), result.evals, assumptions)
    bar = "".join(f'<div style="width:{counts[k] / total * 100:.2f}%;background:{_COLORS[k]}" title="{k}"></div>'
                  for k in _COLORS if counts.get(k))
    legend = "".join(f'<span><i class="dot" style="background:{_COLORS[k]}"></i>{k} {counts[k]}</span>'
                     for k in _COLORS if counts.get(k))
    rows = []
    for c in sorted(result.candidates, key=lambda c: (list(_COLORS).index(out[c.id]), c.file, c.line)):
        ev = result.evals.get(c.id)
        detection = f"{c.level} {c.confidence:.2f}" if c.level else ""
        rows.append(
            f"<tr><td><code>{e(c.location)}</code></td><td>{e(c.language)}</td>"
            f'<td><span class="pill" style="border-color:{_COLORS[out[c.id]]}">{e(out[c.id])}</span></td>'
            f"<td>{e(c.kind or '')} {e(', '.join(c.options))}</td><td>{e(detection)}</td>"
            f"<td>{e(_evidence(ev) if ev else '')}</td><td>{e(c.reason)}</td></tr>")
    saving = (f"${eco.monthly_saving:,.2f}/mo" if result.promoted else "n/a")
    cards = [("call sites", len(result.candidates)), ("refactored" if not result.dry_run else "would refactor",
             len(result.promoted)), ("manual", len(result.manual)), ("blocked", len(result.blocked)),
             ("projected saving*", saving), ("effective speedup*", f"{eco.effective_speedup:.1f}x"
                                              if result.promoted else "n/a")]
    a = assumptions
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>jevvify report</title>
<style>{_HTML_STYLE}</style></head><body><main>
<h1>jevvify report</h1><div class="muted">jevvify {e(__version__)} · threshold {result.threshold:g}
{" · dry run (nothing written)" if result.dry_run else ""}</div>
<div class="cards">{"".join(f'<div class="card"><b>{e(str(v))}</b><span class="muted">{e(k)}</span></div>'
                             for k, v in cards)}</div>
<div class="bar">{bar}</div><div class="legend muted">{legend}</div>
<h2>Call sites</h2><div class="wrap"><table><thead><tr><th>Location</th><th>Lang</th><th>Outcome</th>
<th>Decision</th><th>Detection</th><th>Evidence</th><th>Reason</th></tr></thead><tbody>{"".join(rows)}</tbody>
</table></div>
<h2>Projection</h2><p class="note">* Estimates from assumptions, not measurements: {a.monthly_calls_per_site:,}
calls/site/month, {a.avg_input_tokens} in / {a.avg_output_tokens} out tokens at ${a.price_in_per_mtok} /
${a.price_out_per_mtok} per M tokens, Jev at {a.jev_cost_ratio:.4f}x LLM cost and ~{a.jev_latency_ms:.0f} ms
(vendor claims), fallback rate {eco.fallback_rate:.0%} ({"observed" if eco.fallback_observed else "assumed"}).
Measure real numbers with shadow mode and <code>jevvify stats</code>.</p>
{"".join(f'<p class="note">{e(w)}</p>' for w in result.warnings)}
</main></body></html>
"""


# -- analyze listings -------------------------------------------------------------------

def render_analysis(cands: list[Candidate], fmt: str, warnings: list[str] | None = None) -> str:
    warnings = warnings or []
    if fmt == "json":
        return json.dumps({"call_sites": [c.to_dict() for c in cands], "warnings": warnings}, indent=2)
    if fmt == "csv":
        return candidates_to_csv(cands)
    judged = [c for c in cands if c.status == "candidate"]
    if fmt == "markdown":
        lines = ["## jevvify: LLM calls that look like decisions", "",
                 f"**{len(judged)}** of **{len(cands)}** LLM call sites look like closed-set decisions.", ""]
        if judged:
            lines += ["| location | lang | kind | labels | detection | rewrite |", "|---|---|---|---|---|---|"]
            lines += [f"| `{c.location}` | {c.language} | {c.kind} | {', '.join(c.options)} | "
                      f"{c.level} ({c.confidence:.2f}) | {'auto' if c.rewritable else 'manual'} |" for c in judged]
            lines.append("")
        skipped = [c for c in cands if c.status != "candidate"]
        if skipped:
            lines += ["<details><summary>Skipped call sites</summary>", ""]
            lines += [f"- `{c.location}`: {c.reason}" for c in skipped] + ["", "</details>", ""]
        lines += [f"> {w}" for w in warnings]
        return "\n".join(lines)
    lines = []
    for c in cands:
        if c.status == "candidate":
            tag = "CANDIDATE" if c.rewritable else "MANUAL   "
            lines.append(f"{tag} {c.location}  {c.provider}  {c.reason} [{c.kind}: {', '.join(c.options)}] "
                         f"confidence {c.confidence:.2f} ({c.level})")
        else:
            lines.append(f"skip      {c.location}  {c.provider}  {c.reason}")
    lines.append(f"\n{len(cands)} LLM call sites, {len(judged)} judgment candidates.")
    lines += [f"warning: {w}" for w in warnings]
    return "\n".join(lines)
