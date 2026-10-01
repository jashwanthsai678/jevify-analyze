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
from .languages import adapter_for
from .models import Candidate, meets
from .report import Assumptions, render_report
from .sandbox import create_sandbox, inject_dependency, merge_back

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
    min_confidence: str = "medium"  # low | medium | high: weakest detection that may be rewritten
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
    manual: list[Candidate] = field(default_factory=list)  # judgment calls in languages without auto-rewrite
    warnings: list[str] = field(default_factory=list)
    threshold: float = 0.85
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not self.blocked


def _apply_confidence_gate(candidates: list[Candidate], minimum: str) -> None:
    for c in candidates:
        if c.status == "candidate" and not meets(c.level, minimum):
            c.status, c.reason_code = "skipped", "low-confidence"
            c.reason = f"confidence {c.confidence:.2f} ({c.level}) is below --min-confidence {minimum}"


def run(opts: Options) -> RunResult:
    project = Path(opts.project).resolve()
    exclude = (Path(opts.sandbox_dir),) if opts.sandbox_dir else ()

    # Phase 1: analyze
    warnings: list[str] = []
    candidates = analyze_project(project, exclude, warnings)
    _apply_confidence_gate(candidates, opts.min_confidence)
    manual = [c for c in candidates if c.status == "candidate" and not c.rewritable]
    judged = [c for c in candidates if c.status == "candidate" and c.rewritable]
    by_id = {c.id: c for c in judged}
    notes: list[str] = []
    blocked: dict[str, str] = {}

    # Phase 2: sandbox + translate
    sandbox = create_sandbox(project, opts.sandbox_dir)
    (sandbox / ".jevvify").mkdir(exist_ok=True)
    (sandbox / ".jevvify" / "candidates.json").write_text(
        json.dumps([c.to_dict() for c in candidates], indent=2), encoding="utf-8")
    if any(c.language == "python" for c in judged):
        notes.append(inject_dependency(sandbox, opts.use_uv))

    by_file: dict[str, list[Candidate]] = {}
    for c in judged:
        by_file.setdefault(c.file, []).append(c)
    originals = {rel: read_source(project / rel) for rel in by_file}
    runtime_for: dict[str, list[str]] = {}  # rewritten file -> runtime helper files it needs

    def apply(rel: str, include: list[Candidate]) -> None:
        text, crlf = originals[rel]
        adapter = adapter_for(project / rel)
        assert adapter is not None
        try:
            new = adapter.translate(text, include, opts.threshold, project / rel)
        except SyntaxError as exc:
            for c in include:
                blocked[c.id] = f"rewrite did not parse: {exc}"
            new = text
        write_source(sandbox / rel, new, crlf)
        runtime_for.pop(rel, None)
        if new != text:
            folder = Path(rel).parent
            for name, content in adapter.runtime_files(text, project / rel).items():
                (sandbox / folder / name).write_text(content, encoding="utf-8")
                runtime_for.setdefault(rel, []).append((folder / name).as_posix())

    for rel, cands in by_file.items():
        apply(rel, cands)

    # Phase 3: verify
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

    # Re-apply with only the call sites that survived the gate.
    for rel, cands in by_file.items():
        keep = [c for c in cands if c.id not in blocked]
        if len(keep) != len(cands):
            apply(rel, keep)
    promoted = [c for c in judged if c.id not in blocked]
    changed = sorted({c.file for c in promoted})
    for rel in changed:
        adapter = adapter_for(project / rel)
        assert adapter is not None
        err = adapter.check_syntax((sandbox / rel).read_text(encoding="utf-8"), project / rel)
        if err:
            raise RuntimeError(f"internal error: sandbox file {rel} does not parse: {err}")

    # Phase 4: promote + report
    written: list[str] = []
    if promoted and not opts.dry_run:
        runtime_files = sorted({f for rel in changed for f in runtime_for.get(rel, [])})
        deps = DEPENDENCY_FILES if any(c.language == "python" for c in promoted) else []
        written = merge_back(project, sandbox, changed + runtime_files, deps)
        (project / ".jevvify").mkdir(exist_ok=True)
        (project / ".jevvify" / "candidates.json").write_text(
            json.dumps([c.to_dict() for c in candidates], indent=2), encoding="utf-8")

    if opts.sandbox_dir is None and not opts.keep_sandbox:
        shutil.rmtree(sandbox, ignore_errors=True)
    else:
        notes.append(f"sandbox kept at {sandbox}")

    blocked_pairs = [(by_id[i], why) for i, why in blocked.items()]
    result = RunResult(candidates, promoted, blocked_pairs, evals, notes, written, "", manual, warnings,
                       opts.threshold, opts.dry_run)
    result.report = render_report(result, opts.assumptions)
    return result
