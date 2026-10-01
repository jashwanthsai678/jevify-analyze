# Runtime modes, logs and `jevvify stats`

## Environment variables (Python and JS/TS runtimes)

| Variable | Default | Effect |
|---|---|---|
| `OPENROUTER_API_KEY` | none | Calls Jev over REST. Without it (and, in Python, without `TYPESAFE_API_KEY` + `typesafe-sdk`) every call falls back. |
| `JEVVIFY_MODE` | `live` | `live`: use Jev when confident. `shadow`: call both, return the LLM answer, log both. `off`: LLM only. |
| `JEVVIFY_THRESHOLD` | generated (0.85) | Minimum confidence for using Jev's answer. |
| `JEVVIFY_LOG` | `.jevvify_shadow.jsonl` | JSONL log file (Node falls back to `console.info` where there is no filesystem). |
| `JEVVIFY_LOG_LIVE` | off | `1` also logs live decisions (no extra LLM call) to watch fallback rate and latency in production. |
| `JEVVIFY_LOG_STATE` | off | `1` adds the inputs sent to Jev to each record. Off by default because inputs often contain user data. |
| `JEVVIFY_MODEL`, `JEVVIFY_ENDPOINT`, `JEVVIFY_TIMEOUT` | `typesafe/jev-1.13`, OpenRouter URL, 10 s | REST overrides. |

## Log record

```json
{"ts": "2026-10-01T09:30:00Z", "id": "jev_ec7e8bad", "mode": "shadow", "kind": "choice",
 "options": ["billing", "support"], "threshold": 0.85, "jev_label": "billing", "confidence": 0.93,
 "error": null, "jev_ms": 14.2, "decision": "jev", "legacy_ms": 812.5, "legacy_text": "billing"}
```

`decision` is `jev` (answered by Jev), `fallback` (below threshold) or `error` (Jev failed; the LLM ran).
`legacy_*` fields appear only in shadow mode.

## `jevvify stats`

```bash
jevvify stats .jevvify_shadow.jsonl                  # markdown table + threshold sweep
jevvify stats logs/*.jsonl --threshold 0.9          # what-if at another threshold
jevvify stats .jevvify_shadow.jsonl --format csv     # or json, for dashboards
```

Per call site: records, Jev answers, fallback rate, agreement with the LLM (shadow records whose LLM text maps onto a
label), mean confidence, confidence histogram, Jev p50/p95 and LLM p50 latency, and the threshold sweep.

## Privacy

- jevvify itself never sends your code anywhere.
- Rewritten code sends the prompt's dynamic inputs to OpenRouter / TypeSafe when Jev is enabled. Review what each call
  site passes before enabling it on sensitive data.
- Logs exclude inputs unless `JEVVIFY_LOG_STATE=1`. Keep `.jevvify_shadow.jsonl` out of version control (it is in the
  default `.gitignore` of this repo; add it to yours).
