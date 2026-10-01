# Architecture

jevvify turns decision-style LLM calls into "ask Jev first, fall back to the original call". Four phases, each with
one job, and a hard rule throughout: the original call is kept verbatim and always runs when Jev cannot answer.

```
            ┌────────────┐   ┌──────────────────────┐   ┌──────────────┐   ┌──────────────────┐
 project ──►│ 1 Analyze  │──►│ 2 Sandbox + rewrite  │──►│ 3 Verify     │──►│ 4 Promote/report │──► project
            │ per-language│   │ copy, splice, parse  │   │ tests,shadow │   │ merge + backups  │
            │ adapters    │   │ check, runtime files │   │ samples, gate│   │ md/json/csv/html │
            └────────────┘   └──────────────────────┘   └──────────────┘   └──────────────────┘
```

## Modules

| Module | Responsibility |
|---|---|
| `languages/` | One adapter per language: find call sites, collect prompt text, rewrite, parse-check. `python.py` uses `ast`; `javascript.py` and `go.py` use tree-sitter (optional `multilang` extra). |
| `classify.py` | Language-independent: is this prompt a closed-set decision, which labels, and how confident are we (`assess`). |
| `analyzer.py` | The Python analyzer, `finish_candidate` (shared by all adapters), and `analyze_project`. |
| `translator.py` | The Python rewriter. JS/TS rewriting lives in its adapter. |
| `runtime_src/` | The helper copied next to rewritten files: `jevvify_rt.py` and `jevvify_rt.mjs` (also emitted as `.ts`/`.cjs`). Standard library / built-ins only. |
| `sandbox.py` | Copy the project, inject `typesafe-sdk` for Python, merge verified files back with backups. |
| `evaluator.py` | Shadow evidence (test runs, replayed samples), label normalisation, the promotion gate. |
| `telemetry.py` | `jevvify stats`: per-call-site agreement, fallback rate, latency, threshold sweep. |
| `benchmark.py` | `jevvify bench`: precision/recall of `classify.py` on labelled prompts. |
| `report.py` | Markdown, JSON, CSV and HTML reports. |
| `pipeline.py` | Orchestration of the four phases. |

## Data model

Everything flows through `models.Candidate`: location, provider, language, `status` (`candidate`/`skipped`), a
machine-readable `reason_code` plus human `reason`, the decision (`kind`, `options`, `instructions`), the dynamic inputs
(`variables`: state key → source expression), and detection `confidence` with the `signals` behind it.
`rewritable=False` marks languages that are detected but not rewritten (Go).

## Detection confidence

`classify.assess` starts at 0.35 for a prompt that passed the judgment filter and adds or subtracts named signals:
an explicit label list or stated yes/no words, "reply with only the label", the code comparing the response with the
labels, a small `max_tokens`, `temperature=0`; and penalties for a large `max_tokens`, a very large label space,
open-question words, or a very long prompt. Levels: high ≥ 0.75, medium ≥ 0.55, low below. `jevvify run` rewrites
`medium` and up by default (`--min-confidence`). Every candidate carries its signals, so the score is explainable.

## Safety properties

- **Fallback by construction.** The original call is the body of a lambda / arrow function passed as `fallback`.
  Any Jev error, timeout, missing key, missing SDK, or confidence below the threshold runs it.
- **Nothing lands unverified by accident.** Rewrites happen in a sandbox, every changed file must parse, project
  tests can run in shadow mode, and sites above `--max-error-rate` disagreement are blocked. `--require-evidence`
  blocks sites without evidence.
- **Reversible.** Originals go to `.jevvify/backup/`; `JEVVIFY_MODE=off` disables Jev at runtime with no revert.
- **Idempotent.** Calls already inside `_jevvify_route(...)` / `jevvifyRoute(...)` are ignored on later runs.
- **Privacy.** Runtime logs exclude the inputs unless `JEVVIFY_LOG_STATE=1`.

## Adding a language

Implement `languages/base.py:LanguageAdapter` (`analyze`, `translate`, `runtime_files`, `check_syntax`,
`available`), append it to `ADAPTERS`, reuse `analyzer.finish_candidate` so classification and confidence stay
identical across languages, and add tests that parse and, if possible, execute the rewritten code. Detection-only is a
fine first step: set `can_rewrite = False` and create candidates with `rewritable=False`.
