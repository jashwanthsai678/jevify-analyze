# Example: spam filter (Go, openai-go)

`filter.go` checks signup bios.

| Call | What jevvify does | Why |
|---|---|---|
| `IsSpam` (line 16) | reports a **manual** candidate (`noul`, yes/no) | Go is detection-only for now: SDK responses are concrete structs, so a drop-in shim would be SDK-version specific |
| `Welcome` (line 28) | leaves alone | generative |

Requires the multilang extra (`pip install "jevvify[multilang]"`).

```bash
jevvify analyze examples/spam_filter_go
```

To migrate `IsSpam` by hand, call Jev first and fall back to the existing code. See the Go section of
[docs/languages.md](../../docs/languages.md).
