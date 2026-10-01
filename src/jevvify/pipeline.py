"""Orchestrates the four phases: analyze -> sandbox + translate -> verify -> promote + report."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import evaluator
from .analyzer import analyze_project
from .fsutil import read_source, write_source
from .models import Candidate
from .report import Assumptions, render_report
from .sandbox import create_sandbox, inject_dependency, install_runtime, merge_back
from .translator import translate_source

DEPENDENCY_FILES = ["pyproject.toml", "uv.lock", "requirements.txt"]
SHADOW_LOG = ".jevvify_shadow.jsonl"


@dataclass
class Options:
    project: Path
    threshold: float = 0.85
    sandbox_dir: Path | None = None
    dry_run: bool = False
    samples: Path | None = None
    test_cmd: str | None = None
    max_error_rate: float = 0.05
    min_samples: int = 1
    require_evidence: bool = False
    use_uv: bool = True
    keep_sandbox: bool = False
    assumptions: Assumptions = field(default_factory=Assumptions)


@dataclass
class RunResult:
    candidates: list[Candidate]
    promoted: list[Candidate]
    blocked: list[tuple[Candidate, str]]
    evals: dict[str, evaluator.CandidateEval]
    notes: list[str]
    written: list[str]
    report: str

    @property
    def ok(self) -> bool:
        return not self.blocked


def run(opts: Options) -> RunResult:
    project = Path(opts.project).resolve()
    exclude = (Path(opts.sandbox_dir),) if opts.sandbox_dir else ()

    # Phase 1
    candidates = analyze_project(project, exclude)
    judged = [c for c in candidates if c.status == "candidate"]
    by_id = {c.id: c for c in judged}
    notes: list[str] = []
    blocked: dict[str, str] = {}

    # Phase 2
    sandbox = create_sandbox(project, opts.sandbox_dir)
    (sandbox / ".jevvify").mkdir(exist_ok=True)
    (sandbox / ".jevvify" / "candidates.json").write_text(
        json.dumps([c.to_dict() for c in candidates], indent=2), encoding="utf-8")
    if judged:
        notes.append(inject_dependency(sandbox, opts.use_uv))

    by_file: dict[str, list[Candidate]] = {}
    for c in judged:
        by_file.setdefault(c.file, []).append(c)
    originals = {rel: read_source(project / rel) for rel in by_file}

    def apply(rel: str, include: list[Candidate]) -> None:
        text, crlf = originals[rel]
        is_pkg = (project / rel).parent.joinpath("__init__.py").exists()
        try:
            new = translate_source(text, include, opts.threshold, is_pkg)
        except SyntaxError as exc:
            for c in include:
                blocked[c.id] = f"rewrite did not compile: {exc}"
            new = text
        write_source(sandbox / rel, new, crlf)
        if new != text:
            install_runtime((sandbox / rel).parent)

    for rel, cands in by_file.items():
        apply(rel, cands)

    # Phase 3
    live = [c for c in judged if c.id not in blocked]
    evals: dict[str, evaluator.CandidateEval] = {}
    if live:
        log = sandbox / SHADOW_LOG
        if opts.test_cmd:
            env = {**os.environ, "JEVVIFY_MODE": "shadow", "JEVVIFY_LOG": str(log),
                   "JEVVIFY_THRESHOLD": str(opts.threshold)}
            ok, tail = evaluator.run_test_command(opts.test_cmd, sandbox, env)
            if not ok:
                for c in live:
                    blocked[c.id] = "project tests failed in the sandbox"
                notes.append(f"test command failed:\n{tail}")
        observations = evaluator.load_shadow_log(log, by_id)
        if opts.samples:
            observations += evaluator.run_samples(live, evaluator.load_samples(opts.samples))
        evals = evaluator.evaluate(live, observations, opts.threshold, opts.max_error_rate, opts.min_samples)
        for c in live:
            ev = evals[c.id]
            if c.id in blocked:
                continue
            if ev.status == "fail":
                blocked[c.id] = "; ".join(ev.notes)
            elif ev.status == "unverified" and opts.require_evidence:
                blocked[c.id] = "no shadow evidence and --require-evidence is set"
        if any(c.id not in blocked and evals[c.id].status == "unverified" for c in live):
            notes.append("some call sites have no shadow evidence: they fall back to the LLM below the "
                         "threshold but their Jev answers were not compared with the LLM. Provide "
                         "--samples or --test-cmd, or use --require-evidence to block such rewrites.")

    # Re-apply the rewrite with only the call sites that survived the gate.
    for rel, cands in by_file.items():
        keep = [c for c in cands if c.id not in blocked]
        if len(keep) != len(cands):
            apply(rel, keep)
    promoted = [c for c in judged if c.id not in blocked]
    changed = sorted({c.file for c in promoted})
    bad = evaluator.check_syntax([sandbox / rel for rel in changed])
    if bad:
        raise RuntimeError(f"internal error: sandbox files do not compile: {bad}")

    # Phase 4
    written: list[str] = []
    if promoted and not opts.dry_run:
        runtime_dirs = {Path(rel).parent.as_posix() for rel in changed}
        written = merge_back(project, sandbox, changed, runtime_dirs, DEPENDENCY_FILES)
        (project / ".jevvify").mkdir(exist_ok=True)
        (project / ".jevvify" / "candidates.json").write_text(
            json.dumps([c.to_dict() for c in candidates], indent=2), encoding="utf-8")

    if opts.sandbox_dir is None and not opts.keep_sandbox:
        shutil.rmtree(sandbox, ignore_errors=True)
    else:
        notes.append(f"sandbox kept at {sandbox}")

    blocked_pairs = [(by_id[i], why) for i, why in blocked.items()]
    report = render_report(
        candidates=candidates, promoted=promoted, blocked=blocked_pairs, evals=evals,
        threshold=opts.threshold, dry_run=opts.dry_run, notes=notes, written=written,
        assumptions=opts.assumptions,
    )
    return RunResult(candidates, promoted, blocked_pairs, evals, notes, written, report)
