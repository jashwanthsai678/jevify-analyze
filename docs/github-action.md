# GitHub Action: jevvify audit

The repository root contains a composite action, [`action.yml`](../action.yml), that runs `jevvify analyze` on your
code in CI and writes the result to the job summary. It only reads your code. It does not rewrite anything, call Jev,
or need API keys.

## Example

```yaml
name: jevvify audit

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: jashwanthsai678/jevify-analyze@main
        with:
          path: "."
          fail-on-candidates: "false"
```

Pin `@main` to a tag or commit SHA once you depend on it, and set `version` to the same ref so the action and the
installed tool match.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `path` | `.` | Directory to analyze, relative to the workspace. |
| `python-version` | `3.13` | Python used to run jevvify (installed by `astral-sh/setup-uv`). |
| `fail-on-candidates` | `false` | `"true"` makes the step fail when any candidate call site is found. |
| `version` | `main` | Git ref (branch, tag or commit) of jevvify to install. |

## What it does

1. Sets up `uv` with `astral-sh/setup-uv@v5`.
2. Installs jevvify with the `multilang` extra from this repository at `version`, via `uv tool install`.
3. Runs `jevvify analyze <path> --format markdown` and appends the output to `$GITHUB_STEP_SUMMARY`, so the report
   shows up on the run's summary page.
4. If `fail-on-candidates` is `"true"`, runs `jevvify analyze <path> --fail-on-candidates`, which exits non-zero when
   candidates are found.

## Output

A markdown report in the job summary listing the LLM call sites found, which ones look like classification or yes/no
decisions (candidates for Jev), and why the others were skipped. The action sets no step outputs.

To act on the report, run `jevvify run . --dry-run` locally (see the [README](../README.md)) or use the
[`jevvify-lite`](../skills/jevvify-lite/SKILL.md) skill.

## Using the CLI flags directly

The two flags the action relies on also work outside the action:

```bash
jevvify analyze . --format markdown        # markdown report on stdout
jevvify analyze . --fail-on-candidates     # exit non-zero if any candidate is found
```

Run `jevvify analyze --help` for the full list of flags in your installed version.
