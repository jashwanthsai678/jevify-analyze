# jevify

[![CI](https://github.com/jashwanthsai678/jevify-analyze/actions/workflows/ci.yml/badge.svg)](https://github.com/jashwanthsai678/jevify-analyze/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**Find the LLM calls in your codebase that are really classifiers, and move them to [TypeSafe Jev](https://docs.typesafe.ai). Keep the original LLM call as the fallback.**

Lots of production LLM calls are not generation. They route a ticket, flag spam, pick a category, answer yes or no.
You pay LLM prices and latency for a decision. `jevify` finds those calls, rewrites them to ask Jev first, and only
calls the LLM when Jev is unsure or unavailable. Nothing is written to your project until the rewrite has been built
and checked in a sandbox.

> jevify is an independent open-source project. It is not affiliated with or endorsed by TypeSafe AI.

```diff
- resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": f"Route to billing or support: {text}"}])
+ resp = _jevify_route(
+     "jev_ec7e8bad", {"text": text},
+     lambda: client.chat.completions.create(model="gpt-4o", messages=[...]),   # your original call, unchanged
+     kind="choice", options=["billing", "support"], shape="openai", threshold=0.85, ...)
```

`resp.choices[0].message.content` still works: when Jev is confident, `_jevify_route` returns an object shaped like the
provider's response; otherwise it returns the real LLM response.

## Install

```bash
uv tool install git+https://github.com/jashwanthsai678/jevify-analyze.git
jevify install                    # optional: adds the /jevify skill to Claude Code
```

Or without installing anything permanently: `uvx --from git+https://github.com/jashwanthsai678/jevify-analyze.git jevify analyze .`

Requires Python 3.11+. The command is `jevify`; the Python package is named `jevify-cli` (the name `jevify` is taken on
PyPI by an unrelated project). A PyPI release is planned but not published yet.

## Quick start

```bash
jevify analyze .                  # which calls would be touched, and why others are skipped
jevify run . --dry-run            # full pipeline in a sandbox, nothing written
jevify run . --test-cmd "uv run pytest -q" --samples samples.jsonl
```

Try it on the bundled example: [`examples/ticket_router`](examples/ticket_router).

In Claude Code, run `/jevify` and it walks the same steps and asks before it writes anything.

## How it works

| Phase | Module | What happens |
|---|---|---|
| 1. Analyze | [`analyzer.py`](src/jevify/analyzer.py) | AST scan for openai, anthropic, google-genai and langchain calls. A call is a candidate only if its prompt has a discrete answer space (labels, yes/no); generative prompts are skipped. |
| 2. Translate | [`translator.py`](src/jevify/translator.py), [`sandbox.py`](src/jevify/sandbox.py) | Copy the project to a sandbox, add `typesafe-sdk`, and splice in the Jev-first call. Only the call expression is replaced; formatting and comments stay. |
| 3. Verify | [`evaluator.py`](src/jevify/evaluator.py) | Run Jev and the LLM side by side on your tests or recorded samples, and block call sites whose disagreement rate is too high. |
| 4. Promote | [`pipeline.py`](src/jevify/pipeline.py), [`report.py`](src/jevify/report.py) | Merge verified files back (originals in `.jevify/backup/`) and print a markdown report. |

### Safety model

- The original call is kept verbatim inside the rewrite. If Jev errors, times out, or the SDK is missing, it runs.
- Jev answers below `--threshold` (default 0.85) fall back to the LLM.
- `JEVIFY_MODE=off` disables Jev at runtime; `JEVIFY_MODE=shadow` runs both and returns the LLM answer.
- Not rewritten, and listed as skipped with a reason: generative prompts, streaming, tool or function calling,
  `await`ed calls, prompts with no dynamic input, and prompts whose labels can't be found in the text.

### Evidence

| Source | How |
|---|---|
| Your tests | `--test-cmd "pytest -q"` runs in the sandbox in shadow mode; every rewritten call logs both answers. |
| Recorded samples | `--samples file.jsonl`, one `{"candidate": "...", "state": {...}, "legacy": "...", "expected": "..."}` per line. Jev is called live (see Credentials). |

Call sites above `--max-error-rate` (default 5%) are blocked. Sites with no evidence are promoted but labelled
`unverified` in the report; add `--require-evidence` to block them instead.

### Credentials

Rewritten code calls Jev over its REST endpoint (`POST https://openrouter.ai/api/alpha/decisions`, model
`typesafe/jev-1.13`) when `OPENROUTER_API_KEY` is set. This uses only the standard library. Alternatively set
`TYPESAFE_API_KEY` and install `typesafe-sdk`. With neither, every call falls back to your original LLM call.
The [skill](src/jevify/skill/SKILL.md) also includes copy-paste Jev call templates for Python, TypeScript, `fetch` and `curl`.

### What the report tells you, and what it doesn't

The cost and latency numbers are **projections from stated assumptions** (call volume, token counts, prices, and
TypeSafe's published speed and cost claims), not measurements. The report prints the assumptions; change them with
`--monthly-calls`, `--price-in`, and related flags. The effective speedup accounts for the fallback rate: if 10% of calls
fall back, you do not get the headline speedup.

## Current limits

Python source only. Providers: openai, anthropic, google-genai, langchain. When structured (JSON) output is requested, the
output key is inferred from the prompt or defaults to `label`; review those sites by hand. Prompt-text classification is
heuristic, which is why unclear cases are skipped rather than guessed.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md); the tests run offline with no API keys.
Security reports: [SECURITY.md](SECURITY.md). Changes: [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)
