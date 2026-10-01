import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_typescript")

from jevvify.languages import adapter_named  # noqa: E402

JS = adapter_named("javascript")
NODE = shutil.which("node")


def analyze(src: str, name: str = "app.ts"):
    return JS.analyze(textwrap.dedent(src), name)


TS_APP = textwrap.dedent('''
    import OpenAI from "openai";
    import { helper } from "./helper.js";

    const client = new OpenAI();

    export async function triage(email: string): Promise<string> {
      const resp = await client.chat.completions.create({
        model: "gpt-4o",
        max_tokens: 5,
        messages: [
          { role: "system", content: "Categorize as spam or ham. Reply with one word." },
          { role: "user", content: `Email: ${email}` },
        ],
      });
      const label = resp.choices[0].message.content;
      if (label === "spam") return "spam";
      return "ham";
    }

    export async function essay(topic: string) {
      return client.chat.completions.create({ model: "gpt-4o", messages: [{ role: "user", content: `Write an essay about ${topic}` }] });
    }
''')


def test_openai_typescript_candidate_with_signals():
    first, second = analyze(TS_APP)
    assert (first.status, first.kind, first.options, first.language) == ("candidate", "choice", ["spam", "ham"],
                                                                         "javascript")
    assert first.variables == {"email": "email"}
    assert first.level == "high" and any("max_tokens=5" in s for s in first.signals)
    assert any("compares the response" in s for s in first.signals)
    assert (second.status, second.reason_code) == ("skipped", "generative")


def test_providers_and_call_styles():
    cands = analyze('''
        import Anthropic from "@anthropic-ai/sdk";
        import { generateText, streamText, generateObject } from "ai";
        import { ChatOpenAI } from "@langchain/openai";
        const anthropic = new Anthropic();
        const llm = new ChatOpenAI();
        export async function f(t: string) {
          await anthropic.messages.create({ model: "m", max_tokens: 3, system: "Is this toxic? Answer yes or no.", messages: [{ role: "user", content: t }] });
          await generateText({ model, prompt: `Route to sales or support: ${t}` });
          await streamText({ model, prompt: `Route to sales or support: ${t}` });
          await generateObject({ model, schema, prompt: `Route to sales or support: ${t}` });
          await llm.invoke(`Classify as positive, negative or neutral: ${t}`);
        }
    ''')
    got = [(c.provider, c.status, c.reason_code) for c in cands]
    assert got == [("anthropic", "candidate", "judgment"), ("vercel", "candidate", "judgment"),
                   ("vercel", "skipped", "streaming"), ("vercel", "skipped", "structured-extraction"),
                   ("langchain", "candidate", "judgment")]
    assert cands[0].kind == "noul" and cands[0].variables == {"t": "t"}


def test_skips_streaming_tools_and_promise_helpers():
    cands = analyze('''
        import OpenAI from "openai";
        const c = new OpenAI();
        async function f(t) {
          await c.chat.completions.create({ model: "m", stream: true, messages: [{ role: "user", content: `Is ${t} spam? yes or no` }] });
          await c.chat.completions.create({ model: "m", tools: [], messages: [{ role: "user", content: `Is ${t} spam? yes or no` }] });
          await c.chat.completions.create({ model: "m", messages: [{ role: "user", content: `Is ${t} spam? yes or no` }] }).withResponse();
        }
    ''', "app.js")
    assert [c.reason_code for c in cands] == ["streaming", "tool-calling", "sdk-promise-helpers"]


def test_resolves_local_prompt_variables():
    [c] = analyze('''
        import OpenAI from "openai";
        const c = new OpenAI();
        export async function f(body: string) {
          const prompt = "Route to billing or support: " + body;
          return c.chat.completions.create({ model: "m", messages: [{ role: "user", content: prompt }] });
        }
    ''')
    assert c.options == ["billing", "support"] and c.variables == {"body": "body"}


def test_no_provider_import_means_no_findings():
    assert analyze('const r = await client.chat.completions.create({ messages: [{ role: "user", content: `Is ${x} ok? yes or no` }] });') == []


def test_rewrite_typescript_parses_and_matches_import_style():
    cands = analyze(TS_APP)
    out = JS.translate(TS_APP, cands, 0.85, Path("src/app.ts"))
    assert 'import { jevvifyRoute } from "./_jevvify_rt.js";' in out  # file already uses .js specifiers
    assert out.index('import { helper }') < out.index("jevvifyRoute }")
    assert "() => client.chat.completions.create({" in out
    assert out.count("jevvifyRoute(") == 1 and "Write an essay" in out
    assert JS.check_syntax(out, Path("src/app.ts")) is None
    assert set(JS.runtime_files(TS_APP, Path("src/app.ts"))) == {"_jevvify_rt.ts"}
    assert JS.translate(out, analyze(out), 0.85, Path("src/app.ts")) == out  # idempotent


@pytest.mark.parametrize("name,src,needle,runtime", [
    ("a.mjs", 'import OpenAI from "openai";\nconst c = new OpenAI();\n', 'from "./_jevvify_rt.mjs"', "_jevvify_rt.mjs"),
    ("a.cjs", 'const OpenAI = require("openai");\nconst c = new OpenAI();\n', 'require("./_jevvify_rt.cjs")',
     "_jevvify_rt.cjs"),
    ("a.ts", '"use client";\nimport OpenAI from "openai";\nconst c = new OpenAI();\n', 'from "./_jevvify_rt.js"',
     "_jevvify_rt.ts"),
])
def test_module_styles(name, src, needle, runtime):
    src += "async function f(t) {\n  return c.chat.completions.create({ messages: [{ role: \"user\", content: `Route to sales or support: ${t}` }] });\n}\n"
    out = JS.translate(src, JS.analyze(src, name), 0.85, Path(name))
    assert needle in out and JS.check_syntax(out, Path(name)) is None
    assert list(JS.runtime_files(src, Path(name))) == [runtime]
    if src.startswith('"use client"'):
        assert out.startswith('"use client";\n')


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("confidence,expected,llm_calls", [(0.97, "spam", 0), (0.40, "LLM", 1), (None, "LLM", 1)])
def test_rewritten_typescript_runs(tmp_path, confidence, expected, llm_calls):
    out = JS.translate(TS_APP, analyze(TS_APP), 0.85, tmp_path / "app.ts")
    out = out.replace('import OpenAI from "openai";', "").replace('import { helper } from "./helper.js";', "")
    out = out.replace("new OpenAI()", "globalThis.fakeClient").replace('from "./_jevvify_rt.js"',
                                                                         'from "./_jevvify_rt.ts"')
    (tmp_path / "app.ts").write_text(out, encoding="utf-8")
    for name, content in JS.runtime_files(TS_APP, tmp_path / "app.ts").items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    jev = "throw new Error('down')" if confidence is None else \
        f"return {{ ok: true, json: async () => ({{ answers: {{ q: {{ choice: 'spam', probabilities: {{ spam: {confidence} }} }} }} }}) }}"
    (tmp_path / "main.ts").write_text(textwrap.dedent(f"""
        let llm = 0;
        globalThis.fakeClient = {{ chat: {{ completions: {{ create: async () => {{ llm++; return {{ choices: [{{ message: {{ content: "LLM" }} }}] }}; }} }} }} }};
        globalThis.fetch = async (url, init) => {{ {jev} }};
        process.env.OPENROUTER_API_KEY = "sk-test";
        const {{ triage }} = await import("./app.ts");
        const r = await (await import("./_jevvify_rt.ts")).jevvifyRoute("x", {{}}, async () => "LLM",
          {{ kind: "choice", instructions: "?", options: ["spam", "ham"], shape: "openai", threshold: 0.85 }});
        const label = typeof r === "string" ? r : r.choices[0].message.content;
        await triage("buy now");
        console.log(JSON.stringify({{ label, llm }}));
    """), encoding="utf-8")
    proc = subprocess.run([NODE, "--experimental-strip-types", "--no-warnings", str(tmp_path / "main.ts")],
                          capture_output=True, text=True, timeout=60)
    if "ERR_UNKNOWN_FILE_EXTENSION" in proc.stderr or "bad option" in proc.stderr:
        pytest.skip("node too old to run TypeScript")
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    assert got == {"label": expected, "llm": llm_calls}


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_cjs_runtime_and_shadow_log(tmp_path):
    src = 'const OpenAI = require("openai");\n'
    rt = JS.runtime_files(src, Path("a.cjs"))["_jevvify_rt.cjs"]
    (tmp_path / "_jevvify_rt.cjs").write_text(rt, encoding="utf-8")
    log = tmp_path / "shadow.jsonl"
    (tmp_path / "main.cjs").write_text(textwrap.dedent(f"""
        const {{ jevvifyRoute }} = require("./_jevvify_rt.cjs");
        globalThis.fetch = async () => ({{ ok: true, json: async () => ({{ answers: {{ q: {{ noul: 0.9 }} }} }}) }});
        Object.assign(process.env, {{ OPENROUTER_API_KEY: "k", JEVVIFY_MODE: "shadow", JEVVIFY_LOG: {json.dumps(str(log))} }});
        jevvifyRoute("jev_s", {{ t: "x" }}, async () => ({{ content: [{{ type: "text", text: "no" }}] }}),
          {{ kind: "noul", instructions: "?", options: ["yes", "no"], shape: "anthropic", threshold: 0.85 }})
          .then((r) => console.log(r.content[0].text));
    """), encoding="utf-8")
    proc = subprocess.run([NODE, str(tmp_path / "main.cjs")], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "no"  # shadow mode returns the LLM answer
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert rec["jev_label"] == "yes" and rec["legacy_text"] == "no" and rec["decision"] == "jev"
    assert "state" not in rec  # inputs are not logged unless JEVVIFY_LOG_STATE=1
