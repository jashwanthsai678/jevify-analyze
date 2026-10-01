import json
from pathlib import Path

from jevify.analyzer import analyze_project

EXAMPLE = Path(__file__).parent.parent / "examples" / "ticket_router"


def test_example_matches_its_documentation():
    cands = analyze_project(EXAMPLE)
    assert [(c.line, c.status) for c in cands] == [(10, "candidate"), (22, "skipped")]
    ids = {json.loads(line)["candidate"] for line in (EXAMPLE / "samples.jsonl").read_text().splitlines()}
    assert ids == {cands[0].id}
