# Example: intent router (TypeScript, OpenAI + Vercel AI SDK)

`src/router.ts` is the front door of a store's chat assistant.

| Call | What jevvify does | Why |
|---|---|---|
| `detectIntent` (line 12) | rewrites: `choice` over order_status, refund, product_question, other | closed labels used in a `switch`, `max_tokens: 4`, `temperature: 0` |
| `isOnTopic` (line 34) | rewrites: `noul` (yes/no) | yes/no guardrail via `generateText` |
| `reply` (line 43) | leaves alone | streaming and generative |

Requires the multilang extra (`pip install "jevvify[multilang]"`).

```bash
jevvify analyze examples/intent_router_ts
jevvify run examples/intent_router_ts --dry-run --no-uv
```

The rewrite adds `src/_jevvify_rt.ts` (no npm packages: it uses built-in `fetch`) and an import that follows the
file's existing import style. The original call stays inside `() => ...` as the fallback, and `await` keeps working
because the wrapper returns a promise.
