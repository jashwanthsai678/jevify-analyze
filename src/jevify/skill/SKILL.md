---
name: jevify
description: "Find LLM calls in a Python codebase that are really classification or yes/no decisions (routing, triage, moderation, labelling, boolean checks) and rewrite them to use TypeSafe Jev first, keeping the original LLM call as a fallback. Use when the user wants to cut LLM cost or latency on such calls, or asks which of their LLM calls could move to Jev."
trigger: /jevify
---

# /jevify

TypeSafe Jev is a fast model that returns typed answers (a choice, a yes/no probability, a score) with a confidence,
instead of generated text. Many production LLM calls are really that kind of decision. This skill finds them and
rewrites them to ask Jev first and fall back to the original LLM call when Jev is unsure or unavailable.

jevify is an independent project, not affiliated with TypeSafe AI. Jev is new (early access as of late 2026): its
accuracy, speed and price are TypeSafe's claims until measured on the user's own data.

## Usage

```
/jevify                      # analyze the current directory, then dry-run
/jevify <path>               # same, for a specific path
/jevify <path> --apply       # after the user has reviewed the dry run, write the changes
```

## How to run the tool

This skill folder (`~/.claude/skills/jevify/`) contains a bundled copy of the tool. Run it with either:

- `jevify <args>` if the `jevify` command exists (`jevify --version` succeeds), otherwise
- `python ~/.claude/skills/jevify/jevify.py <args>`

It needs Python 3.11+ and nothing else. If the default `python` is older, use `uv run --python 3.13 python ...`
or `py -3.13 ...`. If no Python 3.11+ is available, tell the user instead of trying to install one.

## Steps

1. **List call sites.** `jevify analyze <path>`. Show which calls are candidates and which are skipped and why.
2. **Look for what the tool missed.** The analyzer is heuristic (regexes over prompt text). It cannot see prompts
   built in helper functions or loaded from files or templates, and it only knows openai, anthropic, google-genai
   and langchain. Search the code for other LLM calls (`Grep` for `completions.create`, `messages.create`,
   `generate_content`, `.invoke(`, plus any wrapper functions the user has) and read the ones not in the list.
   Report each one that is clearly a classification or yes/no decision as a *manual candidate* with file:line.
   Do not rewrite those yourself unless the user asks.
3. **Sanity-check the candidates.** Read each candidate's prompt. Flag any that is not truly a closed set of answers
   (the tool can misread a prompt that merely contains words like "or" or "categorize").
4. **Dry run.** `jevify run <path> --dry-run --no-uv`. Add `--test-cmd "<the project's test command>"` if the
   project has tests, and `--samples <file.jsonl>` if the user has recorded inputs and outputs. Those are the only
   sources of accuracy evidence, and both need `TYPESAFE_API_KEY` plus the `typesafe-sdk` package to make live Jev calls.
5. **Report honestly.**
   - How many sites are verified versus `unverified` (no evidence).
   - Cost and latency figures are projections from stated assumptions, not measurements. Say so.
   - Sites using JSON mode get a guessed output key; point them out for manual review.
   - Mention what is skipped on purpose: generative prompts, streaming, tool calling, `await`ed calls.
6. **Apply only with consent.** After the user agrees, rerun without `--dry-run` (add `--require-evidence` if they
   want unverified sites blocked). Originals are saved in `.jevify/backup/`. `JEVIFY_MODE=off` forces the legacy path.
7. **Next steps for the user:** set `TYPESAFE_API_KEY`, install `typesafe-sdk` (jevify adds it to `pyproject.toml`
   or `requirements.txt`), and run their tests.

## Rules

- Never apply changes without the user's explicit go-ahead.
- Never present a saving or speedup as measured; quote the report's assumptions.
- Do not edit generated `_jevify_route(...)` blocks by hand; rerun the tool instead.
- Generative calls, streaming, tool calling and awaited calls are intentionally left alone.
