"""Phase 4 reporting: markdown summary with explicit, adjustable cost/latency assumptions."""

from __future__ import annotations

from dataclasses import dataclass

from .evaluator import CandidateEval
from .models import Candidate


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


def render_report(
    *, candidates: list[Candidate], promoted: list[Candidate], blocked: list[tuple[Candidate, str]],
    evals: dict[str, CandidateEval], threshold: float, dry_run: bool, notes: list[str],
    written: list[str], assumptions: Assumptions,
) -> str:
    skipped = [c for c in candidates if c.status == "skipped"]
    judged = [c for c in candidates if c.status == "candidate"]
    eco = project_economics(len(promoted), evals, assumptions)
    verified = sum(1 for c in promoted if evals.get(c.id) and evals[c.id].status == "pass")
    lines = [
        "# jevify report", "",
        f"- LLM call sites found: **{len(candidates)}**",
        f"- Judgment tasks (refactor candidates): **{len(judged)}**",
        f"- Refactored to Jev with LLM fallback: **{len(promoted)}**"
        + (" (dry run: nothing written)" if dry_run else ""),
        f"- Verified against shadow data: **{verified}** of {len(promoted)}",
        f"- Blocked: **{len(blocked)}**   Skipped (not judgment / unsupported): **{len(skipped)}**",
        f"- Confidence threshold: **{threshold:g}** (below it, the original LLM call runs)", "",
    ]
    if promoted:
        lines += ["## Refactored", "", "| id | location | kind | labels | evidence |", "|---|---|---|---|---|"]
        for c in promoted:
            ev = evals.get(c.id)
            if not ev or ev.status == "unverified":
                evidence = "unverified"
            else:
                evidence = (f"{ev.status}: {ev.scored} scored, error {ev.error_rate:.1%}, "
                            f"fallback {ev.fallback_rate:.0%}")
            lines.append(f"| {c.id} | {c.file}:{c.line} | {c.kind} | {', '.join(c.options)} | {evidence} |")
        lines.append("")
    if blocked:
        lines += ["## Blocked", ""] + [f"- `{c.file}:{c.line}` ({c.id}): {why}" for c, why in blocked] + [""]
    if skipped:
        lines += ["## Skipped", ""] + [f"- `{c.file}:{c.line}`: {c.reason}" for c in skipped] + [""]
    if promoted:
        a = assumptions
        src = "observed" if eco.fallback_observed else f"assumed ({a.assumed_fallback_rate:.0%}, no shadow data)"
        lines += [
            "## Projected impact (estimates, not measurements)", "",
            f"- Fallback rate: {eco.fallback_rate:.1%} ({src})",
            f"- Latency per call: {a.legacy_latency_ms:.0f} ms -> ~{eco.effective_latency_ms:.0f} ms "
            f"(**{eco.effective_speedup:.1f}x** effective; {eco.best_case_speedup:.0f}x only if nothing falls back)",
            f"- Monthly LLM spend on these sites: ${eco.monthly_before:,.2f} -> ${eco.monthly_after:,.2f} "
            f"(saves **${eco.monthly_before - eco.monthly_after:,.2f}**/month)",
            f"- Assumptions: {a.monthly_calls_per_site:,} calls/site/month, {a.avg_input_tokens} in / "
            f"{a.avg_output_tokens} out tokens, ${a.price_in_per_mtok}/${a.price_out_per_mtok} per M tokens, "
            f"Jev cost = LLM cost x {a.jev_cost_ratio:.4f} and ~{a.jev_latency_ms:.0f} ms (vendor claims). "
            "Tune with --monthly-calls and the other flags.", "",
        ]
    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    if written:
        lines += ["## Files written", ""] + [f"- {w}" for w in written] + [
            "", "Originals are saved in `.jevify/backup/`. "
            "Set `JEVIFY_MODE=off` to force the legacy path at runtime.", ""]
    return "\n".join(lines)

