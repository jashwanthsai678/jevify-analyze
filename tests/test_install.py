import subprocess
import sys

from jevify.cli import main


def test_install_and_uninstall_skill(tmp_path, capsys):
    assert main(["install", "--skills-dir", str(tmp_path)]) == 0
    folder = tmp_path / "jevify"
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: jevify\n") and "trigger: /jevify" in text
    assert (folder / "lib" / "jevify" / "cli.py").exists()
    assert (folder / "lib" / "jevify" / "runtime_src" / "jevify_rt.py").exists()
    assert not (folder / "lib" / "jevify" / "skill").exists()
    assert main(["uninstall", "--skills-dir", str(tmp_path)]) == 0
    assert not folder.exists()
    assert main(["uninstall", "--skills-dir", str(tmp_path)]) == 0
    assert "not installed" in capsys.readouterr().out


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
        [sys.executable, str(tmp_path / "jevify" / "jevify.py"), "run", str(project), "--dry-run", "--no-uv"],
        capture_output=True, text=True, cwd=tmp_path, env={"PATH": "", "SYSTEMROOT": "C:\\Windows"},
    )
    assert out.returncode == 0, out.stderr
    assert "Refactored to Jev with LLM fallback: **1**" in out.stdout


def test_uninstall_keeps_folder_with_other_files(tmp_path):
    main(["install", "--skills-dir", str(tmp_path)])
    (tmp_path / "jevify" / "notes.txt").write_text("mine")
    main(["uninstall", "--skills-dir", str(tmp_path)])
    assert (tmp_path / "jevify" / "notes.txt").exists()
    assert not (tmp_path / "jevify" / "SKILL.md").exists()
