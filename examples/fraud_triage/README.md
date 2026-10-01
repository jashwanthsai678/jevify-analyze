# Example: fraud triage (Python, LangChain)

`triage.py` scores card transactions.

| Call | What jevvify does | Why |
|---|---|---|
| `risk_level` (line 15) | rewrites: `choice` over low, medium, high | ordinal closed labels; prompt built from a local variable, which jevvify follows |
| `merchant_name` (line 20) | leaves alone | extraction of a value, not one of a fixed set of labels |
| `risk_level_async` (line 25) | leaves alone, reported as `async` | Python async rewrite is not automated yet (see the roadmap); you can apply the hand-written pattern in docs/languages.md |

```bash
jevvify analyze examples/fraud_triage
jevvify run examples/fraud_triage --dry-run --no-uv --samples examples/fraud_triage/samples.jsonl  # live Jev
```

Fraud decisions are high-stakes. Keep the threshold high (`--threshold 0.9` or more), run in shadow mode on real traffic,
and check `jevvify stats` before switching to live.
