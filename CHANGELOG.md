# Changelog

## 0.2.0 (unreleased)

### Added
- **Multi-language foundation.** Language adapters (`jevvify.languages`) with tree-sitter parsing behind the optional
  `multilang` extra:
  - **JavaScript/TypeScript**: detection and rewrite for openai, @anthropic-ai/sdk, @google/genai, langchain and the
    Vercel AI SDK. Supports ESM, CommonJS and TypeScript, matching the file's import style, with a dependency-free
    runtime (`_jevvify_rt.ts` / `.mjs` / `.cjs`).
  - **Go**: detection for openai-go, go-openai, anthropic-sdk-go, genai and langchaingo, reported as manual candidates.
- **Detection confidence.** Every candidate gets a 0-1 score, a level (low/medium/high) and the signals behind it:
  explicit labels, an answer-format constraint, the response compared with the labels downstream, `max_tokens`,
  `temperature`. `jevvify run --min-confidence` (default `medium`) gates rewrites.
- **Reason codes** for every skipped call site (`generative`, `no-label-space`, `streaming`, `async`, `low-confidence`,
  ...), with grouped "why skipped" explanations in the report.
- **Benchmarks.** `jevvify bench` with a 103-prompt tuning set and an 80-prompt held-out set, and a CI regression gate.
  Detection on the held-out set: 93.8% precision, 75.0% recall.
- **Telemetry.** Richer runtime log records (timestamp, decision, threshold, labels, latency), live-mode logging
  (`JEVVIFY_LOG_LIVE=1`), and `jevvify stats` with agreement, fallback rate, latency percentiles and a threshold sweep.
- **Reports.** `--report-json`, `--report-csv`, `--report-html`, plus `analyze --format markdown|json|csv`, `-o` and
  `--fail-on-candidates`.
- **Examples:** content moderation (Anthropic), fraud triage (LangChain), intent router (TypeScript + Vercel AI SDK),
  spam filter (Go).
- **Integrations:** GitHub Action (`action.yml`), Dockerfile, Cursor rule and AGENTS.md versions of the lite skill.
- **Project health:** docs/ (architecture, languages, benchmarking, telemetry, GitHub Action), ROADMAP.md and a
  release checklist. CodeQL and dependency review. The release workflow adds an SBOM and build provenance. CI now runs
  mypy, a coverage gate and macOS, plus a job without the optional parsers.

### Changed
- Runtime logs no longer include the inputs sent to Jev unless `JEVVIFY_LOG_STATE=1`.
- Detection rules: label lists now also come from `"A" | "B"` JSON alternatives, "answer X or Y", questions ending in a
  list, inline numbered lists, headed bullet lists, "rate from 1 to 5" and verbs such as label/assign/score. Fewer false
  positives on "discuss", "list all", "why" and "with a justification" prompts.
- `merge_back()` takes the full list of files to copy; runtime helpers are written per language.

## 0.1.0

- First version: analyzer, translator, shadow evaluator, sandboxed pipeline, markdown report.
- `jevvify analyze`, `jevvify run`, `jevvify install` / `uninstall` (Claude Code `/jevvify` skill).
- Jev backends: REST (`OPENROUTER_API_KEY`, standard library only) or `typesafe-sdk`.
- `/jevvify` skill includes Jev API templates (Python, TypeScript, fetch, curl), and `skills/jevvify-lite` is a
  standalone single-file skill.
- Providers: openai, anthropic, google-genai, langchain (Python sources only).
