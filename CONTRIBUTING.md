# Contributing

```bash
git clone https://github.com/jashwanthsai678/jevify-analyze.git
cd jevify-analyze
uv run --python 3.13 --with pytest python -m pytest -q     # run the tests
uv run jevify analyze path/to/some/project                 # try it
```

## Where things go

| Change | Look at |
|---|---|
| Detect another SDK or call style | `_CALL_PATTERNS`, `_PROMPT_KWARGS` in `analyzer.py`, and a response shim in `runtime_src/jevify_rt.py` |
| Smarter judgment-vs-generative detection | `classify_prompt`, `extract_options` in `analyzer.py` |
| Change the generated code | `translator.py` (and the runtime `route()` it calls) |
| New evidence source or gate rule | `evaluator.py` |

## Ground rules

- **The fallback must stay intact.** Every rewrite keeps the original call verbatim, and any Jev failure must end in the original call. A change that can break this needs a test in `tests/test_translator.py` that executes the rewritten code.
- **Skipping is better than guessing.** If a new pattern can't be proven to be a judgment task, report it as skipped with a reason.
- **No invented numbers.** Anything in the report that is not measured must be labelled as an assumption.
- Add a test with every behaviour change. The suite must pass without network access or API keys (`tests/conftest.py` fakes `typesafe_sdk`).
- Runtime code (`runtime_src/jevify_rt.py`) is copied into users' projects: standard library only.

## Releasing (maintainers)

Bump the version in `pyproject.toml` and `CHANGELOG.md`, tag `vX.Y.Z`, and push the tag. `.github/workflows/release.yml` builds and publishes to PyPI via trusted publishing once it is configured on PyPI.
