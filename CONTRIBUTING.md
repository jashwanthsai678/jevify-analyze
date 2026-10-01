# Contributing

```bash
git clone https://github.com/jashwanthsai678/jevify-analyze.git
cd jevify-analyze
uv run --python 3.13 --extra dev --extra multilang python -m pytest -q   # tests (Node 22.6+ also runs the JS ones)
uv run --python 3.13 --extra dev --extra multilang ruff check src tests  # lint
uv run --python 3.13 --extra dev --extra multilang mypy src --ignore-missing-imports
uv run --extra multilang jevvify analyze examples                        # try it
uv run jevvify bench --show-errors                                       # detection benchmark
```

## Where things go

| Change | Look at |
|---|---|
| Detect another SDK or call style | the language adapter in `languages/` (Python: `_CALL_PATTERNS` in `analyzer.py`), plus a response shim in `runtime_src/` |
| A new language | implement `languages/base.py:LanguageAdapter`, see [docs/architecture.md](docs/architecture.md#adding-a-language) |
| Smarter judgment-vs-generative detection | `classify.py`; add the prompt that motivated it to `benchmarks/prompts.jsonl` |
| Confidence scoring | `classify.assess` |
| Change the generated code | `translator.py` (Python) or `languages/javascript.py`, and the runtimes in `runtime_src/` |
| New evidence source or gate rule | `evaluator.py`; runtime log analysis in `telemetry.py` |
| Reports | `report.py` |

## Ground rules

- **The fallback must stay intact.** Every rewrite keeps the original call verbatim, and any Jev failure must end in the original call. A change that can break this needs a test in `tests/test_translator.py` that executes the rewritten code.
- **Skipping is better than guessing.** If a new pattern can't be proven to be a judgment task, report it as skipped with a reason.
- **No invented numbers.** Anything in the report that is not measured must be labelled as an assumption.
- Add a test with every behaviour change. The suite must pass without network access or API keys (`tests/conftest.py` fakes `typesafe_sdk`).
- Runtime code (`runtime_src/`) is copied into users' projects: standard library / built-ins only, no npm packages.
- **Benchmarks stay honest.** Fix detection misses using `benchmarks/prompts.jsonl`; never tune on
  `benchmarks/holdout.jsonl`. `jevvify bench` must not regress (CI gate).
- New examples need a README table that matches `jevvify analyze` exactly (`tests/test_examples.py` checks it).

## Releasing (maintainers)

See [.github/RELEASING.md](.github/RELEASING.md).
