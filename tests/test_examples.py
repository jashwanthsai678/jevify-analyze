"""Each example must behave exactly as its README table says, and its samples must reference real candidates."""

import json
from pathlib import Path

import pytest

from jevvify.analyzer import analyze_project

EXAMPLES = Path(__file__).parent.parent / "examples"

EXPECTED = {
    "ticket_router": [(10, "candidate", True), (22, "skipped", None)],
    "content_moderation": [(15, "candidate", True), (29, "candidate", True), (43, "skipped", None)],
    "fraud_triage": [(15, "candidate", True), (20, "skipped", None), (25, "skipped", None)],
    "intent_router_ts": [(12, "candidate", True), (34, "candidate", True), (43, "skipped", None)],
    "spam_filter_go": [(16, "candidate", False), (28, "skipped", None)],
}
NEEDS_TREE_SITTER = {"intent_router_ts", "spam_filter_go"}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_example_matches_its_readme(name):
    if name in NEEDS_TREE_SITTER:
        pytest.importorskip("tree_sitter")
    cands = analyze_project(EXAMPLES / name)
    got = [(c.line, c.status, c.rewritable if c.status == "candidate" else None) for c in cands]
    assert got == EXPECTED[name]
    readme = (EXAMPLES / name / "README.md").read_text(encoding="utf-8")
    for line, _, _ in EXPECTED[name]:
        assert f"{line}" in readme
    samples = EXAMPLES / name / "samples.jsonl"
    if samples.exists():
        ids = {json.loads(row)["candidate"] for row in samples.read_text(encoding="utf-8").splitlines()}
        assert ids <= {c.id for c in cands if c.status == "candidate"}
