import json
import textwrap

from jevvify.cli import main
from jevvify.pipeline import Options, run

APP = textwrap.dedent('''
    from openai import OpenAI
    client = OpenAI()

    def triage(email):
        return client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": f"Categorize as spam or ham: {email}"}],
        )

    def essay():
        return client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "Write an essay about a flower"}])
''')
PYPROJECT = '[project]\nname = "demo"\nversion = "0"\ndependencies = ["openai"]\n'


def make_project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "pkg").mkdir(parents=True)
    (proj / "pkg" / "__init__.py").write_text("")
    (proj / "pkg" / "app.py").write_text(APP)
    (proj / "pyproject.toml").write_text(PYPROJECT)
    return proj


def test_dry_run_changes_nothing(tmp_path):
    proj = make_project(tmp_path)
    res = run(Options(project=proj, dry_run=True, use_uv=False))
    assert len(res.promoted) == 1 and res.written == []
    assert (proj / "pkg" / "app.py").read_text() == APP
    assert not (proj / "pkg" / "_jevvify_rt.py").exists()
    assert "nothing written" in res.report


def test_run_promotes_and_backs_up(tmp_path):
    proj = make_project(tmp_path)
    res = run(Options(project=proj, use_uv=False))
    app = (proj / "pkg" / "app.py").read_text()
    assert "from ._jevvify_rt import route as _jevvify_route" in app and "Write an essay" in app
    assert (proj / "pkg" / "_jevvify_rt.py").exists()
    assert '"typesafe-sdk"' in (proj / "pyproject.toml").read_text()
    assert (proj / ".jevvify" / "backup" / "pkg" / "app.py").read_text() == APP
    assert "Refactored to Jev with LLM fallback: **1**" in res.report
    assert "Skipped" in res.report and "generative" in res.report
    assert "estimates, not measurements" in res.report
    again = run(Options(project=proj, use_uv=False))  # second run finds nothing new to rewrite
    assert again.promoted == []


def test_failing_project_tests_block_promotion(tmp_path):
    proj = make_project(tmp_path)
    res = run(Options(project=proj, use_uv=False, test_cmd='python -c "import sys; sys.exit(3)"'))
    assert res.promoted == [] and len(res.blocked) == 1 and not res.ok
    assert (proj / "pkg" / "app.py").read_text() == APP


def test_samples_gate_blocks_inaccurate_site(tmp_path, fake_jev):
    proj = make_project(tmp_path)
    cid = run(Options(project=proj, dry_run=True, use_uv=False)).promoted[0].id
    samples = tmp_path / "s.jsonl"
    samples.write_text("\n".join(json.dumps(
        {"candidate": cid, "state": {"email": "x"}, "legacy": "ham"}) for _ in range(10)))
    fake_jev.reply = {"label": "spam", "confidence": 0.99, "p": 0}  # disagrees with every legacy answer
    res = run(Options(project=proj, use_uv=False, samples=samples))
    assert res.promoted == [] and "exceeds" in res.blocked[0][1]
    assert (proj / "pkg" / "app.py").read_text() == APP

    fake_jev.reply = {"label": "ham", "confidence": 0.99, "p": 0}
    res = run(Options(project=proj, use_uv=False, samples=samples))
    assert len(res.promoted) == 1 and res.evals[cid].status == "pass"
    assert "pass" in res.report


def test_require_evidence_blocks_unverified(tmp_path):
    proj = make_project(tmp_path)
    res = run(Options(project=proj, use_uv=False, require_evidence=True))
    assert res.promoted == [] and (proj / "pkg" / "app.py").read_text() == APP


def test_sandbox_dir_inside_project_and_reuse_guard(tmp_path):
    proj = make_project(tmp_path)
    sb = proj / "tmp_sandbox"
    run(Options(project=proj, dry_run=True, use_uv=False, sandbox_dir=sb))
    run(Options(project=proj, dry_run=True, use_uv=False, sandbox_dir=sb))  # marker allows reuse
    (tmp_path / "precious").mkdir()
    (tmp_path / "precious" / "f.txt").write_text("keep")
    try:
        run(Options(project=proj, dry_run=True, use_uv=False, sandbox_dir=tmp_path / "precious"))
        raise AssertionError("should have refused")
    except SystemExit as exc:
        assert "refusing" in str(exc)
    assert (tmp_path / "precious" / "f.txt").read_text() == "keep"


def test_cli_analyze_and_run(tmp_path, capsys):
    proj = make_project(tmp_path)
    assert main(["analyze", str(proj)]) == 0
    assert "CANDIDATE pkg/app.py" in capsys.readouterr().out
    assert main(["run", str(proj), "--dry-run", "--no-uv", "--threshold", "0.9"]) == 0
    assert "# jevvify report" in capsys.readouterr().out
    assert main(["run", str(proj), "--threshold", "2"]) == 2
