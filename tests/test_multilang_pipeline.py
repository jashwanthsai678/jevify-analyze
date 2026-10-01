import csv
import io
import json
import textwrap

import pytest

pytest.importorskip("tree_sitter_typescript")
pytest.importorskip("tree_sitter_go")

from jevvify.cli import main  # noqa: E402
from jevvify.pipeline import Options, run  # noqa: E402
from jevvify.report import Assumptions, result_to_csv, result_to_dict, result_to_html  # noqa: E402

PY = textwrap.dedent('''
    from openai import OpenAI
    client = OpenAI()
    def is_spam(text):
        return client.chat.completions.create(model="m", max_tokens=3, messages=[
            {"role": "user", "content": f"Is this spam? Answer yes or no.\\n{text}"}])
''')
TS = textwrap.dedent('''
    import OpenAI from "openai";
    const client = new OpenAI();
    export async function route(t: string) {
      return client.chat.completions.create({ model: "m", messages: [{ role: "user", content: `Route to sales or support: ${t}` }] });
    }
''')
GO = textwrap.dedent('''
    package x
    import "github.com/openai/openai-go"
    func F(ctx any, c openai.Client, t string) {
        c.Chat.Completions.New(ctx, openai.ChatCompletionNewParams{
            Messages: []openai.ChatCompletionMessageParamUnion{openai.UserMessage("Classify as low, medium or high: " + t)},
        })
    }
''')


def project(tmp_path):
    p = tmp_path / "proj"
    (p / "web").mkdir(parents=True)
    (p / "svc").mkdir()
    (p / "app.py").write_text(PY)
    (p / "web" / "route.ts").write_text(TS)
    (p / "svc" / "x.go").write_text(GO)
    (p / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0"\ndependencies = []\n')
    return p


def test_mixed_project_end_to_end(tmp_path):
    p = project(tmp_path)
    res = run(Options(project=p, use_uv=False))
    langs = sorted(c.language for c in res.promoted)
    assert langs == ["javascript", "python"]
    assert [c.language for c in res.manual] == ["go"]
    assert "_jevvify_route(" in (p / "app.py").read_text() and (p / "_jevvify_rt.py").exists()
    assert "jevvifyRoute(" in (p / "web" / "route.ts").read_text() and (p / "web" / "_jevvify_rt.ts").exists()
    assert (p / "svc" / "x.go").read_text() == GO  # Go is reported, never rewritten
    assert "## Manual rewrite needed" in res.report and "svc/x.go" in res.report
    assert sorted(res.written) == sorted(["app.py", "_jevvify_rt.py", "web/route.ts", "web/_jevvify_rt.ts",
                                          "pyproject.toml"])


def test_js_only_project_does_not_touch_python_dependencies(tmp_path):
    p = tmp_path / "web"
    p.mkdir()
    (p / "route.ts").write_text(TS)
    (p / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0"\ndependencies = []\n')
    res = run(Options(project=p, use_uv=False))
    assert len(res.promoted) == 1 and "typesafe-sdk" not in (p / "pyproject.toml").read_text()


def test_min_confidence_gate(tmp_path):
    p = tmp_path / "p"
    p.mkdir()
    (p / "a.py").write_text(textwrap.dedent('''
        import openai
        def f(c, t):
            return c.chat.completions.create(model="m", max_tokens=500,
                messages=[{"role": "user", "content": f"Is this message friendly? {t}"}])
    '''))
    res = run(Options(project=p, dry_run=True, use_uv=False))
    [c] = res.candidates
    assert c.reason_code == "low-confidence" and res.promoted == []
    res = run(Options(project=p, dry_run=True, use_uv=False, min_confidence="low"))
    assert len(res.promoted) == 1


def test_exports(tmp_path):
    res = run(Options(project=project(tmp_path), dry_run=True, use_uv=False))
    data = result_to_dict(res, Assumptions())
    assert data["summary"]["call_sites"] == 3 and data["summary"]["would-refactor"] == 2
    assert data["projection"]["note"] == "estimate, not a measurement"
    json.dumps(data)  # serialisable
    rows = list(csv.DictReader(io.StringIO(result_to_csv(res))))
    assert {r["outcome"] for r in rows} == {"would-refactor", "manual"}
    page = result_to_html(res, Assumptions())
    assert page.startswith("<!doctype html>") and "svc/x.go" in page and "not measurements" in page
    assert "<script" not in page  # static, self-contained


def test_cli_report_files_and_analyze_formats(tmp_path, capsys):
    p = project(tmp_path)
    out = tmp_path / "r"
    out.mkdir()
    assert main(["run", str(p), "--dry-run", "--no-uv", "--report-json", str(out / "r.json"),
                 "--report-csv", str(out / "r.csv"), "--report-html", str(out / "r.html")]) == 0
    assert json.loads((out / "r.json").read_text())["dry_run"] is True
    assert (out / "r.csv").read_text().startswith("id,file,line")
    capsys.readouterr()
    assert main(["analyze", str(p), "--format", "markdown"]) == 0
    md = capsys.readouterr().out
    assert "| `web/route.ts:5` | javascript |" in md and "manual" in md
    assert main(["analyze", str(p), "--fail-on-candidates"]) == 1
    assert main(["analyze", str(p), "--format", "csv", "-o", str(out / "a.csv")]) == 0
    assert len((out / "a.csv").read_text().splitlines()) == 4


def test_missing_parsers_are_reported_not_fatal(tmp_path, monkeypatch, capsys):
    from jevvify.languages import javascript

    monkeypatch.setattr(javascript.JavaScriptAdapter, "available", lambda self: False)
    p = project(tmp_path)
    assert main(["analyze", str(p)]) == 0
    out = capsys.readouterr().out
    assert "1 javascript file(s) not analyzed" in out and "app.py" in out
