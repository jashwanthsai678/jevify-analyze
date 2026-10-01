# Example: content moderation (Python, Anthropic)

`moderation.py` moderates forum posts.

| Call | What jevvify does | Why |
|---|---|---|
| `moderate` (line 15) | rewrites: `choice` over SAFE, NSFW, HATE, VIOLENCE, confidence high | closed labels, `max_tokens=5`, "reply with the label only", result compared with `"SAFE"` |
| `needs_human_review` (line 29) | rewrites: `noul` (yes/no), confidence high | yes/no question with stated answer words and `max_tokens=3` |
| `explain_removal` (line 43) | leaves alone | generative: the user reads this text |

```bash
jevvify analyze examples/content_moderation
jevvify run examples/content_moderation --dry-run --no-uv
jevvify run examples/content_moderation --dry-run --no-uv --samples examples/content_moderation/samples.jsonl  # live Jev
```

After a rewrite, `moderate()` still returns `"publish"` or `"hold for review"`: when Jev is confident, the response object
it receives carries Jev's label in `response.content[0].text`; otherwise the original Anthropic call runs unchanged.
