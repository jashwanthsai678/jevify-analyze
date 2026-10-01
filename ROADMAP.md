# Roadmap

This is a plan, not a promise. Priorities change with feedback, so if something here matters to you (or something
missing does), [open an issue](https://github.com/jashwanthsai678/jevify-analyze/issues).

A note on evidence: nothing in jevvify has been benchmarked against the real Jev API yet. The cost and latency figures
in reports are projections from stated assumptions and TypeSafe's published claims, not measurements. Getting real
numbers is on this roadmap.

## Now: 0.2, multi-language foundation

- **Python**: full pipeline (analyze, rewrite, verify, promote), as in 0.1.
- **JavaScript / TypeScript**: detect candidate calls and rewrite them to ask Jev first, with the original call as
  fallback.
- **Go**: detection only.
- **Confidence scoring** for each candidate, so borderline sites are clearly marked instead of silently included.
- **Reports** in JSON, CSV and HTML in addition to the terminal and markdown output.
- **Shadow stats**: summaries of shadow-mode logs (agreement rate, fallback rate per call site).

## Next

- Close the detection gaps found by the held-out benchmark (labels that look like generative words, parenthesised
  and lettered option lists, few-shot prompts, label + prose JSON). See [docs/benchmarking.md](docs/benchmarking.md).
- Rewriting `await`ed (async) Python calls.
- Go rewrites.
- Java and Kotlin detection.
- A release on PyPI as `jevvify`.
- More SDKs and frameworks: deeper Vercel AI SDK support, LiteLLM, LlamaIndex.

## Later

- VS Code extension.
- Homebrew formula.
- Codemod plugins, so others can add providers and languages without changing the core.
- Batching several questions about the same input (state) into one Jev request.
- A live benchmark against the real Jev API on public datasets, with the method and raw results published.

## Contributing

Pick anything above, or propose something else: open an issue first for larger changes so we can agree on the
approach. See [CONTRIBUTING.md](CONTRIBUTING.md).
