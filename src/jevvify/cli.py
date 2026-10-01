"""Command line entry point.

Exit codes: 0 success; 1 something was blocked, a gate failed, or --fail-on-candidates matched; 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .analyzer import analyze_project
from .install import install_skill, uninstall_skill
from .models import LEVELS, meets
from .report import Assumptions, render_analysis, result_to_csv, result_to_dict, result_to_html


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jevvify", description="Move decision-style LLM calls onto TypeSafe Jev, "
                                "keeping the original call as a fallback.")
    p.add_argument("--version", action="version", version=f"jevvify {__version__}")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    a = sub.add_parser("analyze", help="List LLM call sites and which look like decisions (writes nothing).")
    a.add_argument("path", type=Path, nargs="?", default=Path("."))
    a.add_argument("--format", choices=["text", "markdown", "json", "csv"], default="text")
    a.add_argument("--json", action="store_true", help="shorthand for --format json")
    a.add_argument("--min-confidence", choices=LEVELS, default="low", help="hide candidates below this level")
    a.add_argument("--fail-on-candidates", action="store_true",
                   help="exit 1 if any candidate at --min-confidence or above is found (for CI)")
    a.add_argument("-o", "--output", type=Path, help="write to a file instead of stdout")

    r = sub.add_parser("run", help="Analyze, rewrite in a sandbox, verify, and promote.")
    r.add_argument("path", type=Path, nargs="?", default=Path("."))
    r.add_argument("--threshold", type=float, default=0.85, help="min Jev confidence before falling back (0-1)")
    r.add_argument("--min-confidence", choices=LEVELS, default="medium",
                   help="weakest detection confidence that may be rewritten (default: medium)")
    r.add_argument("--sandbox-dir", type=Path, default=None, help="sandbox location (default: temp dir)")
    r.add_argument("--dry-run", action="store_true", help="do everything except writing to the project")
    r.add_argument("--samples", type=Path, help="JSONL of recorded inputs/outputs to replay (live Jev calls)")
    r.add_argument("--test-cmd", help="run in the sandbox with JEVVIFY_MODE=shadow, e.g. 'uv run pytest -q'")
    r.add_argument("--max-error-rate", type=float, default=0.05, help="block a call site above this disagreement rate")
    r.add_argument("--min-samples", type=int, default=1, help="scored answers needed before a call site can pass")
    r.add_argument("--require-evidence", action="store_true", help="block call sites with no shadow evidence")
    r.add_argument("--no-uv", action="store_true", help="edit pyproject.toml directly instead of `uv add`")
    r.add_argument("--keep-sandbox", action="store_true")
    r.add_argument("--report-json", type=Path, help="also write the full result as JSON")
    r.add_argument("--report-csv", type=Path, help="also write one CSV row per call site")
    r.add_argument("--report-html", type=Path, help="also write a self-contained HTML report")
    g = r.add_argument_group("projection assumptions (estimates only)")
    d = Assumptions()
    g.add_argument("--monthly-calls", type=int, default=d.monthly_calls_per_site, help="calls per call site per month")
    g.add_argument("--input-tokens", type=int, default=d.avg_input_tokens)
    g.add_argument("--output-tokens", type=int, default=d.avg_output_tokens)
    g.add_argument("--price-in", type=float, default=d.price_in_per_mtok, help="$ per 1M input tokens")
    g.add_argument("--price-out", type=float, default=d.price_out_per_mtok, help="$ per 1M output tokens")
    g.add_argument("--legacy-latency-ms", type=float, default=d.legacy_latency_ms)

    s = sub.add_parser("stats", help="Summarise runtime logs: fallback rate, agreement, confidence, latency.")
    s.add_argument("logs", type=Path, nargs="*", default=[Path(".jevvify_shadow.jsonl")])
    s.add_argument("--threshold", type=float, help="evaluate as if this threshold were in force")
    s.add_argument("--format", choices=["text", "json", "csv"], default="text")

    b = sub.add_parser("bench", help="Measure the prompt classifier against a labelled dataset.")
    b.add_argument("--dataset", type=Path, help="JSONL dataset (default: the bundled benchmark)")
    b.add_argument("--min-confidence", choices=LEVELS, default="medium")
    b.add_argument("--format", choices=["text", "json"], default="text")
    b.add_argument("--show-errors", action="store_true")
    b.add_argument("--min-precision", type=float, help="exit 1 if detection precision is below this (0-1)")
    b.add_argument("--min-recall", type=float, help="exit 1 if detection recall is below this (0-1)")

    for name, text in (("install", "Install the /jevvify skill for Claude Code."),
                       ("uninstall", "Remove the /jevvify skill.")):
        i = sub.add_parser(name, help=text)
        i.add_argument("--skills-dir", type=Path, default=None, help="default: ~/.claude/skills")
    return p


def _fail(message: str) -> int:
    print(f"jevvify: error: {message}", file=sys.stderr)
    return 2


def _emit(text: str, output: Path | None) -> None:
    if output:
        output.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    else:
        print(text)


def _cmd_analyze(args: argparse.Namespace) -> int:
    if not args.path.exists():
        return _fail(f"path not found: {args.path}")
    warnings: list[str] = []
    cands = analyze_project(args.path, warnings=warnings)
    shown = [c for c in cands if c.status != "candidate" or meets(c.level, args.min_confidence)]
    _emit(render_analysis(shown, "json" if args.json else args.format, warnings), args.output)
    if args.fail_on_candidates and any(c.status == "candidate" for c in shown):
        return 1
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from .pipeline import Options, run

    if not 0.0 <= args.threshold <= 1.0:
        return _fail("--threshold must be between 0 and 1")
    if not args.path.exists():
        return _fail(f"path not found: {args.path}")
    if args.samples and not args.samples.exists():
        return _fail(f"samples file not found: {args.samples}")
    assumptions = Assumptions(
        monthly_calls_per_site=args.monthly_calls, avg_input_tokens=args.input_tokens,
        avg_output_tokens=args.output_tokens, price_in_per_mtok=args.price_in,
        price_out_per_mtok=args.price_out, legacy_latency_ms=args.legacy_latency_ms)
    opts = Options(
        project=args.path, threshold=args.threshold, sandbox_dir=args.sandbox_dir, dry_run=args.dry_run,
        samples=args.samples, test_cmd=args.test_cmd, max_error_rate=args.max_error_rate,
        min_samples=args.min_samples, require_evidence=args.require_evidence, min_confidence=args.min_confidence,
        use_uv=not args.no_uv, keep_sandbox=args.keep_sandbox, assumptions=assumptions,
    )
    result = run(opts)
    print(result.report)
    if args.report_json:
        import json

        args.report_json.write_text(json.dumps(result_to_dict(result, assumptions), indent=2), encoding="utf-8")
    if args.report_csv:
        args.report_csv.write_text(result_to_csv(result), encoding="utf-8")
    if args.report_html:
        args.report_html.write_text(result_to_html(result, assumptions), encoding="utf-8")
    return 0 if result.ok else 1


def _cmd_stats(args: argparse.Namespace) -> int:
    from .telemetry import load_records, render, summarize

    missing = [p for p in args.logs if not p.exists()]
    if missing:
        return _fail(f"log file not found: {missing[0]} (enable logging with JEVVIFY_MODE=shadow or "
                     "JEVVIFY_LOG_LIVE=1)")
    print(render(summarize(load_records(args.logs), args.threshold), args.format))
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    from . import benchmark

    dataset = args.dataset or benchmark.default_dataset()
    if dataset is None or not Path(dataset).exists():
        return _fail("no dataset found; pass --dataset path/to/prompts.jsonl")
    result = benchmark.run(benchmark.load(dataset), args.min_confidence)
    print(benchmark.render(result, args.format, args.show_errors))
    if args.min_precision is not None and result.detection.precision < args.min_precision:
        return 1
    if args.min_recall is not None and result.detection.recall < args.min_recall:
        return 1
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    print(f"installed skill: {install_skill(args.skills_dir)}\nUse it in Claude Code with /jevvify")
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    removed = uninstall_skill(args.skills_dir)
    print("skill removed" if removed else "skill was not installed")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    commands = {"analyze": _cmd_analyze, "run": _cmd_run, "stats": _cmd_stats, "bench": _cmd_bench,
                "install": _cmd_install, "uninstall": _cmd_uninstall}
    try:
        return commands[args.command](args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
