# Example: ticket router

`app.py` has two LLM calls. `route_ticket` is a classification (billing or support); `draft_reply` is generative.

```bash
# from the repository root
jevify analyze examples/ticket_router
jevify run examples/ticket_router --dry-run --no-uv

# with accuracy evidence (needs TYPESAFE_API_KEY and the typesafe-sdk package):
jevify run examples/ticket_router --dry-run --samples examples/ticket_router/samples.jsonl
```

Expected: one candidate (`app.py:10`) and one skip (`app.py:22`, generative). `samples.jsonl` holds recorded
legacy answers and ground truth; the candidate ids in it are derived from the file path relative to the directory
you pass to `jevify`, so run it on `examples/ticket_router` as shown.
