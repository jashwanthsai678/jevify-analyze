# Integrations

The same jevvify instructions, packaged for different coding agents and CI.

| Tool | How |
|---|---|
| Claude Code | Copy [`skills/jevvify-lite/SKILL.md`](../skills/jevvify-lite/SKILL.md) to `~/.claude/skills/jevvify-lite/SKILL.md` (or `.claude/skills/jevvify-lite/SKILL.md` in your project) and run `/jevvify-lite`. Or install the tool and run `jevvify install` to add the `/jevvify` skill. |
| Cursor | Copy [`cursor/jevvify.mdc`](cursor/jevvify.mdc) into your project's `.cursor/rules/`. It is not always applied; ask Cursor to use the jevvify rule. |
| Windsurf, Codex, Aider and other agents that read `AGENTS.md` | Copy the contents of [`AGENTS.md`](AGENTS.md) into your repository's `AGENTS.md` (append if you already have one). |
| GitHub Copilot | Same as above via `AGENTS.md`, or put the contents in `.github/copilot-instructions.md`. |
| GitHub Actions | Use the composite action at the repository root. See [docs/github-action.md](../docs/github-action.md). |

`cursor/jevvify.mdc` and `AGENTS.md` contain the same body as `skills/jevvify-lite/SKILL.md`; edit the skill and copy
the change into both.
