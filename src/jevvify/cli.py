from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analyzer import analyze_project
from .install import install_skill, uninstall_skill
from .pipeline import Options, run
from .report import Assumptions


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jevvify", description="Move judgment-style LLM calls onto TypeSafe Jev.")
    p.add_argument("--version", action="version", version=f"jevvify {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="Phase 1 only: list LLM call sites and which are judgment tasks.")
    a.add_argument("path", type=Path, nargs="?", default=Path("."))
    a.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    for name, text in (("install", "Install the /jevvify skill for Claude Code."),
                       ("uninstall", "Remove the /jevvify skill.")):
        s = sub.add_parser(name, help=text)
        s.add_argument("--skills-dir", type=Path, default=None, help="default: ~/.claude/skills")

    r = sub.add_parser("run", help="Analyze, rewrite in a sandbox, verify, and promote.")
    r.add_argument("path", type=Path, nargs="?", default=Path("."))
    r.add_argument("--threshold", type=float, default=0.85, help="min Jev confidence before falling back (0-1)")
    r.add_argument("--sandbox-dir", type=Path, default=None, help="sandbox location (default: temp dir)")
    r.add_argument("--dry-run", action="store_true", help="do everything except writing to the project")
    r.add_argument("--samples", type=Path, help="JSONL of recorded inputs/outputs to replay (needs TYPESAFE_API_KEY)")
    r.add_argument("--test-cmd", help="run in the sandbox with JEVVIFY_MODE=shadow, e.g. 'uv run pytest -q'")
    r.add_argument("--max-error-rate", type=float, default=0.05, help="block a call site above this disagreement rate")
    r.add_argument("--min-samples", type=int, default=1, help="scored answers needed before a call site can pass")
    r.add_argument("--require-evidence", action="store_true", help="block call sites with no shadow evidence")
    r.add_argument("--no-uv", action="store_true", help="edit pyproject.toml directly instead of `uv add`")
    r.add_argument("--keep-sandbox", action="store_true")
    g = r.add_argument_group("projection assumptions")
    d = Assumptions()
    g.add_argument("--monthly-calls", type=int, default=d.monthly_calls_per_site, help="calls per call site per month")
    g.add_argument("--input-tokens", type=int, default=d.avg_input_tokens)
    g.add_argument("--output-tokens", type=int, default=d.avg_output_tokens)
    g.add_argument("--price-in", type=float, default=d.price_in_per_mtok, help="$ per 1M input tokens")
    g.add_argument("--price-out", type=float, default=d.price_out_per_mtok, help="$ per 1M output tokens")
    g.add_argument("--legacy-latency-ms", type=float, default=d.legacy_latency_ms)
    return p


def _cmd_analyze(args: argparse.Namespace) -> int:
    cands = analyze_project(args.path)
    if args.json:
        print(json.dumps([c.to_dict() for c in cands], indent=2))
        return 0
    for c in cands:
        tag = "CANDIDATE" if c.status == "candidate" else "skip     "
        extra = f" [{c.kind}: {', '.join(c.options)}]" if c.status == "candidate" else ""
        print(f"{tag} {c.file}:{c.line}  {c.provider}  {c.reason}{extra}")
    judged = sum(c.status == "candidate" for c in cands)
    print(f"\n{len(cands)} LLM call sites, {judged} judgment candidates.")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    if not 0.0 <= args.threshold <= 1.0:
        print("error: --threshold must be between 0 and 1", file=sys.stderr)
        return 2
    opts = Options(
        project=args.path, threshold=args.threshold, sandbox_dir=args.sandbox_dir, dry_run=args.dry_run,
        samples=args.samples, test_cmd=args.test_cmd, max_error_rate=args.max_error_rate,
        min_samples=args.min_samples, require_evidence=args.require_evidence, use_uv=not args.no_uv,
        keep_sandbox=args.keep_sandbox,
        assumptions=Assumptions(
            monthly_calls_per_site=args.monthly_calls, avg_input_tokens=args.input_tokens,
            avg_output_tokens=args.output_tokens, price_in_per_mtok=args.price_in,
            price_out_per_mtok=args.price_out, legacy_latency_ms=args.legacy_latency_ms),
    )
    result = run(opts)
    print(result.report)
    return 0 if result.ok else 1


def _cmd_install(args: argparse.Namespace) -> int:
    print(f"installed skill: {install_skill(args.skills_dir)}\nUse it in Claude Code with /jevvify")
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    removed = uninstall_skill(args.skills_dir)
    print("skill removed" if removed else "skill was not installed")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    commands = {"analyze": _cmd_analyze, "run": _cmd_run, "install": _cmd_install, "uninstall": _cmd_uninstall}
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
