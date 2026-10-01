# jevvify

[![CI](https://github.com/jashwanthsai678/jevify-analyze/actions/workflows/ci.yml/badge.svg)](https://github.com/jashwanthsai678/jevify-analyze/actions/workflows/ci.yml)
[![CodeQL](https://github.com/jashwanthsai678/jevify-analyze/actions/workflows/codeql.yml/badge.svg)](https://github.com/jashwanthsai678/jevify-analyze/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**Find the LLM calls in your codebase that are really decisions, and move them to a model built for decisions,
without giving up the LLM as a safety net.**

Most production LLM calls don't generate anything. They route a ticket, flag a post, pick an intent, or answer
"is this spam?". Those calls pay LLM prices and LLM latency for one word. [TypeSafe Jev](https://docs.typesafe.ai)
(`typesafe/jev-1.13` on OpenRouter) answers exactly that kind of typed question with a label and a probability.

jevvify finds those calls in Python, JavaScript/TypeScript and Go. It rewrites the Python and JS/TS ones to ask Jev
first, and keeps your original call, verbatim, as the fallback whenever Jev is unsure, slow or down. Every rewrite is
built and checked in a sandbox before anything touches your project.

> jevvify is an independent open-source project, not affiliated with or endorsed by TypeSafe AI. Jev is new (early
> access since September 2026). Its speed, cost and accuracy figures are vendor claims until you measure them on your
> traffic, and jevvify ships the tools to do that.

```diff
- const resp = await client.chat.completions.create({ model: "gpt-4o", messages: [...] });
+ const resp = await jevvifyRoute("jev_859c753f", { message },
+   () => client.chat.completions.create({ model: "gpt-4o", messages: [...] }),   // your call, unchanged
+   { kind: "choice", options: ["order_status", "refund", "product_question", "other"], threshold: 0.85, ... });
```

`resp.choices[0].message.content` keeps working: when Jev is confident, the wrapper returns a response-shaped object
holding Jev's label; otherwise it returns the real LLM response.

## Who it's for

- Teams with LLM calls in production that **classify, route, moderate, gate or score** text.
- Agent builders whose loops make many small decisions: which tool, is the task done, is this on topic.
- Anyone who wants a **list of their decision-style LLM calls** before deciding anything (`jevvify analyze` writes nothing).

## When to use it, and when not

| Good fit | Not a fit |
|---|---|
| The answer is one of a few labels or yes/no | The answer is text a person reads (replies, summaries, explanations) |
| Code branches on the answer (`if`, `switch`, dict lookup) | You extract values (names, dates, amounts) or need several fields |
| High call volume, or latency matters | Tool calling, streaming, multi-turn chat |
| You can run it in shadow mode first | You can't send the inputs to a third-party API |

## Install

```bash
uv tool install "jevvify[multilang] @ git+https://github.com/jashwanthsai678/jevify-analyze.git"
# or: pipx install "jevvify[multilang] @ git+https://github.com/jashwanthsai678/jevify-analyze.git"
# Python-only, no optional parsers: drop "[multilang]"
```

Requires Python 3.11+. A PyPI release (`pip install jevvify`) is planned; the package is release-ready. Note the
spelling: `jevify` on PyPI is an unrelated project.

Other ways in:
- **Docker:** `docker build -t jevvify . && docker run --rm -v "$PWD:/work" jevvify`
- **GitHub Action:** audit every pull request with the bundled action, see [docs/github-action.md](docs/github-action.md).
- **Claude Code, Cursor, Codex, Windsurf, Copilot:** [`skills/jevvify-lite/SKILL.md`](skills/jevvify-lite/SKILL.md)
  is a single-file skill (no install). [integrations/](integrations) has Cursor and AGENTS.md versions. `jevvify install`
  adds the tool-backed `/jevvify` skill.

## Quick start

```bash
jevvify analyze .                              # which calls look like decisions, with confidence and reasons
jevvify run . --dry-run --report-html out.html # full pipeline in a sandbox; nothing written
jevvify run . --test-cmd "pytest -q"           # rewrite, shadow-test with your suite, then promote
```

Try it on the bundled [examples](examples): support routing, content moderation, fraud triage, a TypeScript intent
router, and a Go spam filter.

## How it works

| Phase | What happens |
|---|---|
| 1. Analyze | Per-language parsers (Python `ast`; tree-sitter for JS/TS and Go) find calls to openai, anthropic, google-genai, langchain and the Vercel AI SDK. They follow the prompt through variables, f-strings and template literals, and decide if it has a closed answer set. Each call site gets a **confidence score with the signals behind it**, or a **reason code** for why it was skipped. |
| 2. Rewrite | The project is copied to a sandbox. Only the call expression is replaced; formatting stays. Each rewritten file must parse, and a small dependency-free runtime is added next to it. |
| 3. Verify | Optionally runs your tests in shadow mode and replays recorded samples, comparing Jev with the LLM. Call sites above `--max-error-rate` disagreement are blocked. |
| 4. Promote | Verified files are merged back, with originals in `.jevvify/backup/`. You get a report in markdown, plus `--report-json`, `--report-csv` and `--report-html` if you want them. |

**Safety by construction.** The fallback is your original call, untouched. A missing key, error, timeout or low
confidence all run it. `JEVVIFY_MODE=off` turns Jev off at runtime without a revert; `JEVVIFY_MODE=shadow` runs both
and keeps the LLM answer. Rewrites below `--min-confidence` (default `medium`) are not made. Runtime logs exclude your
inputs unless you opt in. More in [docs/architecture.md](docs/architecture.md).

## Measuring before you trust it

```bash
JEVVIFY_MODE=shadow ...your app or tests...    # every rewritten call logs Jev's and the LLM's answers
jevvify stats .jevvify_shadow.jsonl             # agreement, fallback rate, latency, and a threshold sweep
```

The threshold sweep shows, for each confidence threshold, what share of calls Jev would answer and how often it would
agree with your current model. That is the number to decide on. See [docs/telemetry.md](docs/telemetry.md).

The cost and latency figures in `jevvify run` reports are projections from stated, adjustable assumptions. They also
account for the fallback rate: if 10% of calls fall back, you don't get the headline speedup.

## How good is the detection?

Measured with `jevvify bench` on labelled prompts (details and caveats in [docs/benchmarking.md](docs/benchmarking.md)):

| | Precision | Recall |
|---|---|---|
| Held-out set (80 prompts, never tuned on) | 93.8% | 75.0% |
| … only what would be rewritten at the default `--min-confidence medium` | 96.7% | 72.5% |

When jevvify calls something a decision it's usually right; it misses about a quarter of real decisions, which stay
on the LLM. The datasets are small and synthetic: treat this as a regression signal, and run `bench` on your own prompts.

## Language support

| | Detect | Rewrite |
|---|---|---|
| Python | ✅ | ✅ (sync calls) |
| JavaScript / TypeScript | ✅ | ✅ (ESM, CommonJS, TS; import style matched to the file) |
| Go | ✅ | manual, with a pattern in [docs/languages.md](docs/languages.md) |

## Compared with what you'd do otherwise

- **Rewriting by hand:** fine for two call sites. jevvify finds them all, keeps the fallback consistent, and gives you
  evidence before you merge.
- **Routing to a cheaper LLM or a semantic cache** (gateways): still pays for text generation, and caches miss on new
  inputs. jevvify moves decisions to a model that returns typed answers, and you can combine it with either.
- **Fine-tuning your own classifier:** more control, but you need data, training and hosting. Shadow logs from jevvify
  are a good start for that dataset if you go that way later.

## Project

[Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) (tests run offline, no API keys) ·
[Security](SECURITY.md) · [Docs](docs) · [MIT license](LICENSE)
