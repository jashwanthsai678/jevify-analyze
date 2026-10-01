"""Integration files are copies of the lite skill body; keep them in sync."""

from pathlib import Path

ROOT = Path(__file__).parent.parent


def skill_body() -> str:
    text = (ROOT / "skills" / "jevvify-lite" / "SKILL.md").read_text(encoding="utf-8")
    return text.split("\n---\n", 1)[1]


def test_cursor_rule_matches_skill():
    text = (ROOT / "integrations" / "cursor" / "jevvify.mdc").read_text(encoding="utf-8")
    assert text.startswith("---\ndescription:")
    assert text.split("\n---\n", 1)[1] == skill_body()


def test_agents_md_matches_skill():
    lines = (ROOT / "integrations" / "AGENTS.md").read_text(encoding="utf-8").split("\n")
    assert lines[0] == "# jevvify"
    assert "\n".join(lines[4:]) == skill_body()


def test_action_and_docker_exist():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    assert "jevvify analyze" in action and "--format markdown" in action
    assert "multilang" in (ROOT / "Dockerfile").read_text(encoding="utf-8")
