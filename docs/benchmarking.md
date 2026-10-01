# Benchmarking

Two different questions, two different tools.

| Question | Tool | Needs Jev access |
|---|---|---|
| Does jevvify find the right call sites and labels? | `jevvify bench` | no |
| Is Jev as good as my LLM on my traffic, and how much faster/cheaper? | shadow mode + `jevvify stats`, or `jevvify run --samples` | yes |

## Detection benchmark (`jevvify bench`)

`benchmarks/prompts.jsonl` (103 prompts) and `benchmarks/holdout.jsonl` (80 prompts) are labelled examples of prompts
as they appear in code: decisions (closed labels or yes/no) and non-decisions (generation, extraction, open questions),
including many deliberately hard cases on both sides. Both were written for this project by AI assistants (not hand-reviewed row by row);
they are small and synthetic, so treat the numbers as a regression signal, not a guarantee for your codebase.

- **Tuning set** (`prompts.jsonl`): the classifier rules were improved while looking at its errors, so its score is
  optimistic by construction. CI fails if it regresses below 95% precision / 90% recall.
- **Held-out set** (`holdout.jsonl`): written blind (its author did not see the code or the tuning set), and never used
  for tuning. This is the honest estimate.

Results for v0.2.0:

| Set | Rows | Precision | Recall | F1 | Precision at default `--min-confidence medium` |
|---|---|---|---|---|---|
| Tuning set (before tuning) | 103 | 94.7% | 69.2% | 0.80 | n/a |
| Tuning set (after tuning) | 103 | 100% | 100% | 1.00 | 100% (recall 90.4%) |
| **Held-out set** | 80 | **93.8%** | **75.0%** | **0.83** | **96.7%** (recall 72.5%) |

Reading it: when jevvify calls something a decision, it is right about 94% of the time on unseen prompts, and the
confidence gate pushes that to about 97% for what it would actually rewrite. It misses about a quarter of real
decisions, which then simply stay on the LLM (safe, but no saving). Known misses on the held-out set:

- labels that are also "generative" words (an agent label `continue` trips the generative filter);
- options in parentheses or lettered lists (`(a) ... (b) ...`), few-shot prompts that state the labels in examples;
- label lists introduced with nouns jevvify does not know (`topic`, `emotion`, rating codes);
- false positives: JSON outputs that ask for a label *plus* a prose `reason`, and yes/no-shaped questions that expect
  analysis.

Run it yourself:

```bash
jevvify bench --show-errors                                  # bundled tuning set
jevvify bench --dataset benchmarks/holdout.jsonl --show-errors
jevvify bench --dataset my_prompts.jsonl --format json       # your own prompts, same format
```

Row format: `{"id", "prompt", "judgment": true|false, "kind": "choice"|"noul"|null, "labels": [...], "note"}`, with
code-interpolated values written in backticks. Contributions of real (anonymised) prompts are very welcome; when you fix
a miss, add the prompt to `prompts.jsonl`, and keep `holdout.jsonl` untouched so it stays honest. A fresh held-out set
should be written for each release.

## Jev vs. your LLM

jevvify does not ship accuracy, latency or cost results for Jev itself: none have been measured against the live API
yet. Measure them on your traffic:

1. Apply the rewrite and deploy with `JEVVIFY_MODE=shadow`. The app keeps using the LLM answer; each call logs Jev's
   answer, confidence and latency next to the LLM's.
2. Run `jevvify stats .jevvify_shadow.jsonl`. For each call site you get agreement with the LLM, fallback rate,
   Jev p50/p95 latency vs. LLM latency, and a **threshold sweep**: at each threshold, the share of calls Jev would
   answer and its agreement on those.
3. Pick a threshold per call site from the sweep, then switch to `JEVVIFY_MODE=live`. Keep `JEVVIFY_LOG_LIVE=1` for a
   while to watch the fallback rate.

Agreement with the old model is not accuracy. Where you have ground truth, put it in `--samples` rows as `expected`.
