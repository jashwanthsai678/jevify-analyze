---
name: jevvify
description: "Audit a codebase for LLM calls that are really classification or yes/no decisions (routing, triage, intent, moderation, spam, sentiment, labelling, guardrails, 'is this X?' checks) and move them to TypeSafe Jev, keeping the original LLM call as a fallback. Python and JavaScript/TypeScript call sites are rewritten automatically by the bundled jevvify tool; Go is detected for manual rewrite, and other languages get hand-written Jev calls from bundled API templates. Use when the user wants to cut LLM cost or latency on decision-style calls, asks which LLM calls could move to Jev, or wants to call the Jev API. Not for generative calls (writing, summarizing, chat replies) or for choosing an LLM."
trigger: /jevvify
---

# /jevvify

Jev (TypeSafe AI, served via OpenRouter as `typesafe/jev-1.13`) answers narrow, typed questions about a piece of text:
a yes/no probability (`noul`), a pick from fixed labels (`choice`), or a level on a scale (`score`). Many production
LLM calls are exactly that kind of decision, paid for at LLM prices. This skill finds those calls and makes them ask
Jev first, falling back to the original LLM call whenever Jev is unsure, slow or unavailable.

Be straight with the user about two things throughout. jevvify is independent and not affiliated with TypeSafe AI.
Jev is new (early access since September 2026), so its accuracy, speed and cost are vendor claims until measured on the
user's own data.

## What the user asked → what to do

| Request | Do |
|---|---|
| `/jevvify`, `/jevvify <path>`, "which of my LLM calls could use Jev?" | Steps 1-5 (audit and dry run). Write nothing. |
| `/jevvify <path> --apply`, or "go ahead" after a dry run | Step 6. If no dry run happened in this conversation, do steps 1-5 first. |
| `/jevvify api`, "how do I call Jev?" | Read `reference/jev-api.md` and give the template for their language. |
| Go code, or a language the tool does not parse | Steps 2-3 by reading the code yourself (the tool lists Go decisions as `MANUAL`), then offer hand-written rewrites from `reference/jev-api.md`. Never claim the tool rewrote them. |
| "is it working?" after deploying in shadow mode | Run `jevvify stats <log>` and explain agreement, fallback rate and the threshold sweep. |

## Running the tool

The tool is bundled in this skill folder and needs only Python 3.11+.

1. If `jevvify --version` works, use `jevvify <args>`.
2. Otherwise run `python ~/.claude/skills/jevvify/jevvify.py <args>`.
3. If that Python is older than 3.11, try `py -3.13` (Windows) or `uv run --python 3.13 python ...`.
4. If no Python 3.11+ exists, say so and continue with the manual review (steps 2-3) only. Never install Python yourself.

Commands: `jevvify analyze <path> [--json]` lists call sites, `jevvify run <path> [flags]` runs the full pipeline,
`jevvify stats <log>` summarises shadow logs. Run `jevvify <command> --help` for every flag.

JavaScript/TypeScript and Go need the optional parsers. If `analyze` warns that files were not analyzed, tell the user
to install the multilang extra (`uv tool install "jevvify[multilang] @ git+https://github.com/jashwanthsai678/jevify-analyze.git"`)
and review those files by hand meanwhile.

## Workflow

### 1. Inventory
Run `jevvify analyze <path>`. It reports each call to openai, anthropic, google-genai, langchain or the Vercel AI SDK
as `CANDIDATE` (a decision the tool can rewrite), `MANUAL` (a decision in Go), or `skip` with a reason. Each candidate
has a confidence (low/medium/high) and `--json` lists the signals behind it; `jevvify run` only rewrites `medium` and up
unless `--min-confidence low` is given. Generative prompts, streaming, tool calling, async Python calls and prompts
with no per-call input are skipped on purpose.

### 2. Find what the analyzer missed
The analyzer matches patterns, so it misses prompts built in helper functions, loaded from files or templates, or sent
through wrappers and unsupported SDKs. Search for the rest with Grep: `completions.create`, `messages.create`,
`generate_content`, `.invoke(`, `ainvoke(`, `/chat/completions`, `api.openai.com`, `api.anthropic.com`, plus any
wrapper names you find (`ask_llm`, `classify`, `call_model`, ...). Read every call that is not already in the list.

### 3. Judge each call (the analyzer's candidates and your finds)
A call is a good Jev fit only if **all** of these hold:
- **Closed answer set.** The answer is one of a few labels, yes/no, or a level on a scale, never free text.
- **Code consumes the answer.** The output feeds an `if`, `match`, dict lookup, enum or stored label. It is not shown
  to a person as prose. Checking how the response is used downstream is the strongest signal; do it.
- **Self-contained input.** It judges text passed in the call, not knowledge the model must recall.
- **Short output.** No reasoning, explanation or extraction the code relies on.

Mark analyzer candidates that fail a check as **false positive** with the reason. Mark calls you found that pass all
checks as **manual candidates**. Calls that are async, streaming or inside an agent framework can still be manual
candidates. Do not rewrite manual candidates unless the user asks; then use the pattern in `reference/jev-api.md`.

### 4. Dry run
Run `jevvify run <path> --dry-run --no-uv`. It rewrites the code in a sandbox, checks that it compiles, and changes
nothing in the project. Accuracy evidence comes only from:
- `--test-cmd "<the project's test command>"`, which runs the tests with both paths and compares answers;
- `--samples <file.jsonl>` with recorded cases, one JSON object per line:
  `{"candidate": "<id from analyze --json>", "state": {...}, "legacy": "<old answer>", "expected": "<optional truth>"}`.

Both make live Jev calls, so they need credentials (see below). Without evidence, call sites are marked `unverified`.

### 5. Report
Present it in this shape, keeping it short:

```
**Jev candidates: N of M LLM calls**   (verified: X · unverified: Y · blocked: Z)

| Call site | Decision | Labels | Status |
|---|---|---|---|
| app.py:10 | route ticket | billing, support | unverified |

**False positives**: file:line, reason
**Manual candidates** (not rewritten): file:line, what it decides
**Skipped on purpose**: count by reason

**Projected impact**: <report numbers>. These are estimates from the stated assumptions, not measurements.
**Needs review**: JSON-mode sites (guessed output key) and anything you were unsure about.
```

Then ask whether to apply, recommending `--require-evidence` if nothing is verified.

### 6. Apply (only after the user says yes)
Run `jevvify run <path>` with the same evidence flags as the dry run, adding `--require-evidence` if the user wants
unverified sites blocked. Add `--no-uv` unless the project uses uv (has `uv.lock`). Afterwards:
- show the list of changed files from the report, and the diff of one rewritten call;
- originals are in `.jevvify/backup/`; `JEVVIFY_MODE=off` forces the old path at runtime without a revert;
- run the project's tests if you know the command, and report the result as it is.

If jevvify exits with code 1, some sites were blocked and the rest were applied. Explain each blocked site.

## Credentials (for live Jev calls)

- **REST, recommended:** set `OPENROUTER_API_KEY`. No extra package is needed. Optional settings: `JEVVIFY_MODEL`,
  `JEVVIFY_ENDPOINT`, `JEVVIFY_TIMEOUT` (seconds, default 10).
- **SDK:** set `TYPESAFE_API_KEY` and install `typesafe-sdk`. jevvify adds `typesafe-sdk` to the project's
  dependencies either way; tell the user it can be removed if they use REST only.
- **Neither:** every rewritten call falls back to the original LLM call. Nothing breaks, but nothing is saved either.

Runtime switches: `JEVVIFY_MODE=live|shadow|off` (shadow runs both paths, returns the LLM answer and logs to
`.jevvify_shadow.jsonl`) and `JEVVIFY_THRESHOLD` (default 0.85).

## When things go wrong

| Situation | Response |
|---|---|
| No candidates found | Report it plainly, then list any manual candidates from step 3. Do not stretch the criteria. |
| The tool crashes or errors | Show the error, continue with manual review, and suggest filing an issue with a minimal snippet. |
| `--test-cmd` fails in the sandbox | Everything is blocked. Run the tests on the untouched project to check whether they already failed. |
| A site is blocked for error rate | Jev disagreed with the old model too often on the evidence. Leave it on the LLM. |
| The user wants every LLM call moved | Explain that only closed-set decisions fit; generative calls must stay on an LLM. |

## Rules

- Never write to the project without explicit consent given after the user has seen the dry-run results.
- Never present a cost or latency number as measured. Quote the report's assumptions with it.
- Never put an API key in code, a command line you show, a commit, or a samples file. Use environment variables.
- Never edit generated `_jevvify_route(...)` blocks by hand. Rerun the tool or restore from `.jevvify/backup/`.
- Prefer skipping to guessing. A call left on the LLM costs money; a wrong rewrite breaks behaviour.
