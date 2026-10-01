# Examples

Each example is a small, realistic slice of an app. Every one has at least one LLM call that is a decision (and so a
Jev candidate) next to one that is not, so you can see both what jevvify changes and what it deliberately leaves alone.

| Example | Language / SDK | Decisions jevvify finds | Left alone, and why |
|---|---|---|---|
| [ticket_router](ticket_router) | Python · openai | route ticket: billing / support | reply drafting (generative) |
| [content_moderation](content_moderation) | Python · anthropic | moderation label (4 labels); human-review gate (yes/no) | removal note (generative) |
| [fraud_triage](fraud_triage) | Python · langchain | fraud risk: low / medium / high | merchant extraction (not a label); async call |
| [intent_router_ts](intent_router_ts) | TypeScript · openai + Vercel AI SDK | intent (4 labels); on-topic guardrail (yes/no) | streamed reply |
| [spam_filter_go](spam_filter_go) | Go · openai-go | spam yes/no, reported for **manual** rewrite | welcome message (generative) |

Try any of them from the repository root:

```bash
jevvify analyze examples/content_moderation
jevvify run examples/content_moderation --dry-run --no-uv --report-html /tmp/report.html
```

## About the numbers

These examples ship **no accuracy, cost or latency results**, because none have been measured against the live Jev
API yet. Each `samples.jsonl` holds a few hand-written inputs with the answer the old model gave (`legacy`) and the
correct answer (`expected`). To measure your own numbers:

```bash
export OPENROUTER_API_KEY=...
jevvify run examples/content_moderation --dry-run --no-uv --samples examples/content_moderation/samples.jsonl
```

For real traffic, deploy a rewrite with `JEVVIFY_MODE=shadow`, then run `jevvify stats .jevvify_shadow.jsonl` to see
agreement with the old model, the fallback rate, and latency, including a threshold sweep. A handful of samples is
a smoke test, not evidence; aim for a few hundred real inputs per call site before trusting a call site.

Candidate ids in `samples.jsonl` are derived from the file path relative to the directory you pass to jevvify, so run
the commands on the example folder, as shown.
