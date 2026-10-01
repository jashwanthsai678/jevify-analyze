import re
import subprocess
import sys
from pathlib import Path

from jevvify.cli import main


def test_install_and_uninstall_skill(tmp_path, capsys):
    assert main(["install", "--skills-dir", str(tmp_path)]) == 0
    folder = tmp_path / "jevvify"
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: jevvify\n") and "trigger: /jevvify" in text
    assert (folder / "lib" / "jevvify" / "cli.py").exists()
    assert (folder / "lib" / "jevvify" / "runtime_src" / "jevvify_rt.py").exists()
    assert not (folder / "lib" / "jevvify" / "skill").exists()
    assert "typesafe/jev-1.13" in (folder / "reference" / "jev-api.md").read_text(encoding="utf-8")
    assert main(["uninstall", "--skills-dir", str(tmp_path)]) == 0
    assert not folder.exists()
    assert main(["uninstall", "--skills-dir", str(tmp_path)]) == 0
    assert "not installed" in capsys.readouterr().out


def test_skill_only_references_files_that_ship_with_it(tmp_path):
    main(["install", "--skills-dir", str(tmp_path)])
    folder = tmp_path / "jevvify"
    skill = (folder / "SKILL.md").read_text(encoding="utf-8")
    refs = set(re.findall(r"`(reference/[\w./-]+)`", skill))
    assert refs and all((folder / r).exists() for r in refs)
    assert len(skill.splitlines()) < 200  # the long templates live in reference/, not in the always-loaded file


def test_skill_mentions_only_real_cli_flags():
    from jevvify.cli import _build_parser

    run_parser = _build_parser()._subparsers._group_actions[0].choices["run"]
    real = {opt for action in run_parser._actions for opt in action.option_strings}
    text = (Path(__file__).parent.parent / "src" / "jevvify" / "skill" / "SKILL.md").read_text(encoding="utf-8")
    # --apply is the skill's own argument, --python is uv's; the rest belong to `analyze` or the top-level parser
    not_run_flags = {"--apply", "--python", "--version", "--json", "--help"}
    mentioned = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", text)) - not_run_flags
    assert mentioned and mentioned <= real, mentioned - real


def test_installed_skill_runs_without_the_package_on_path(tmp_path):
    main(["install", "--skills-dir", str(tmp_path)])
    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text(
        "from openai import OpenAI\nc = OpenAI()\n"
        "def f(t):\n    return c.chat.completions.create(model='m', "
        "messages=[{'role': 'user', 'content': f'Route to sales or support: {t}'}])\n",
        encoding="utf-8",
    )
    out = subprocess.run(
        [sys.executable, str(tmp_path / "jevvify" / "jevvify.py"), "run", str(project), "--dry-run", "--no-uv"],
        capture_output=True, text=True, cwd=tmp_path, env={"PATH": "", "SYSTEMROOT": "C:\\Windows"},
    )
    assert out.returncode == 0, out.stderr
    assert "Refactored to Jev with LLM fallback: **1**" in out.stdout


def test_uninstall_keeps_folder_with_other_files(tmp_path):
    main(["install", "--skills-dir", str(tmp_path)])
    (tmp_path / "jevvify" / "notes.txt").write_text("mine")
    main(["uninstall", "--skills-dir", str(tmp_path)])
    assert (tmp_path / "jevvify" / "notes.txt").exists()
    assert not (tmp_path / "jevvify" / "SKILL.md").exists()
