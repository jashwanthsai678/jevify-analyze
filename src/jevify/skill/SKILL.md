---
name: jevify
description: "Find LLM calls in a Python codebase that are really classification or yes/no decisions (routing, triage, moderation, labelling, boolean checks) and rewrite them to use TypeSafe Jev first, keeping the original LLM call as a fallback. Also gives Jev API call templates (Python, TypeScript, fetch, curl) for projects in other languages. Use when the user wants to cut LLM cost or latency on such calls, asks which of their LLM calls could move to Jev, or wants to call Jev from their code."
trigger: /jevify
---

# /jevify

TypeSafe Jev is a fast model that answers narrow, typed questions about some text (a choice, a yes/no probability,
a score) instead of generating prose. Many production LLM calls are really that kind of decision. This skill finds
them and rewrites them to ask Jev first and fall back to the original LLM call when Jev is unsure or unavailable.

jevify is an independent project, not affiliated with TypeSafe AI. Jev is new (early access as of late 2026): its
accuracy, speed and price are TypeSafe's claims until measured on the user's own data.

## Usage

```
/jevify                      # analyze the current directory, then dry-run
/jevify <path>               # same, for a specific path
/jevify <path> --apply       # after the user has reviewed the dry run, write the changes
/jevify api                  # just show the Jev API templates below
```

## How to run the tool

This skill folder (`~/.claude/skills/jevify/`) contains a bundled copy of the tool. Run it with either:

- `jevify <args>` if the `jevify` command exists (`jevify --version` succeeds), otherwise
- `python ~/.claude/skills/jevify/jevify.py <args>`

It needs Python 3.11+ and nothing else. If the default `python` is older, use `uv run --python 3.13 python ...`
or `py -3.13 ...`. If no Python 3.11+ is available, tell the user instead of trying to install one.

The tool rewrites **Python** sources only. For JavaScript/TypeScript or other languages, use steps 1-3 by reading
the code yourself, then offer the API templates below as hand-written replacements. Do not claim the tool handled them.

## Steps

1. **List call sites.** `jevify analyze <path>`. Show which calls are candidates and which are skipped and why.
2. **Look for what the tool missed.** The analyzer is heuristic (regexes over prompt text). It cannot see prompts
   built in helper functions or loaded from files or templates, and it only knows openai, anthropic, google-genai
   and langchain. Search the code for other LLM calls (`Grep` for `completions.create`, `messages.create`,
   `generate_content`, `.invoke(`, plus any wrapper functions the user has) and read the ones not in the list.
   Report each one that is clearly a classification or yes/no decision as a *manual candidate* with file:line.
   Do not rewrite those yourself unless the user asks.
3. **Sanity-check the candidates.** Read each candidate's prompt. Flag any that is not truly a closed set of answers
   (the tool can misread a prompt that merely contains words like "or" or "categorize").
4. **Dry run.** `jevify run <path> --dry-run --no-uv`. Add `--test-cmd "<the project's test command>"` if the
   project has tests, and `--samples <file.jsonl>` if the user has recorded inputs and outputs. Those are the only
   sources of accuracy evidence, and both make live Jev calls (see Credentials).
5. **Report honestly.**
   - How many sites are verified versus `unverified` (no evidence).
   - Cost and latency figures are projections from stated assumptions, not measurements. Say so.
   - Sites using JSON mode get a guessed output key; point them out for manual review.
   - Mention what is skipped on purpose: generative prompts, streaming, tool calling, `await`ed calls.
6. **Apply only with consent.** After the user agrees, rerun without `--dry-run` (add `--require-evidence` if they
   want unverified sites blocked). Originals are saved in `.jevify/backup/`. `JEVIFY_MODE=off` forces the legacy path.
7. **Next steps for the user:** set the credentials below and run their tests.

## Credentials

Rewritten code calls Jev one of two ways, chosen at runtime:

- **REST (recommended, no extra package):** set `OPENROUTER_API_KEY`. Calls `POST https://openrouter.ai/api/alpha/decisions`
  with model `typesafe/jev-1.13`. Overrides: `JEVIFY_MODEL`, `JEVIFY_ENDPOINT`, `JEVIFY_TIMEOUT` (seconds, default 10).
- **SDK:** set `TYPESAFE_API_KEY` and install `typesafe-sdk` (jevify adds it to `pyproject.toml` or `requirements.txt`).

With neither, every call falls back to the original LLM, so nothing breaks.

## Jev API reference (use these templates; never put a real key in code)

One request carries the `state` (the text to judge, a single string) and one or more named `questions`. Three types:

| type | criteria | answer |
|---|---|---|
| `noul` | `{"true": "...", "false": "..."}` | `answers[name].noul`: probability of true, 0 to 1 |
| `choice` | `{label: description, ...}` | `.choice` plus `.probabilities` (full distribution) |
| `score` | list of level descriptions, low to high | `.score` plus the distribution |

Your code owns the workflow: branch on the probabilities (for example `noul > 0.8`) and keep a fallback.

**Python (requests)**

```python
import json, os, requests

response = requests.post(
    url="https://openrouter.ai/api/alpha/decisions",
    headers={
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "Content-Type": "application/json",
    },
    data=json.dumps({
        "model": "typesafe/jev-1.13",
        "state": "Help! My payouts have been failing for 3 days.",
        "questions": {
            "is_urgent": {
                "type": "noul",
                "instructions": "Does this message convey urgency?",
                "criteria": {"true": "Explicitly time-sensitive", "false": "No urgency expressed"},
            },
            "department": {
                "type": "choice",
                "instructions": "Which team should handle this?",
                "criteria": {
                    "billing": "Payments, invoicing, refunds",
                    "technical": "Bugs, outages, integrations",
                    "sales": "Pricing, upgrades, new accounts",
                },
            },
            "frustration": {
                "type": "score",
                "instructions": "How frustrated is the customer?",
                "criteria": ["Calm", "Frustrated", "Very angry"],
            },
        },
    }),
    timeout=10,
)
answers = response.json()["answers"]
print(answers["is_urgent"]["noul"])
print(answers["department"]["choice"], answers["department"]["probabilities"])
print(answers["frustration"]["score"])

if answers["is_urgent"]["noul"] > 0.8 and answers["department"]["choice"] == "billing":
    pass  # escalate_to_billing(...)
```

**TypeScript (OpenRouter SDK)**

```ts
import { OpenRouter } from "@openrouter/sdk";

const openrouter = new OpenRouter({ apiKey: process.env.OPENROUTER_API_KEY! });

const decision = await openrouter.alpha.decisions.create({
  decisionsRequest: {
    model: "typesafe/jev-1.13",
    state: "Help! My payouts have been failing for 3 days.",
    questions: {
      is_urgent: {
        type: "noul",
        instructions: "Does this message convey urgency?",
        criteria: { true: "Explicitly time-sensitive", false: "No urgency expressed" },
      },
      department: {
        type: "choice",
        instructions: "Which team should handle this?",
        criteria: {
          billing: "Payments, invoicing, refunds",
          technical: "Bugs, outages, integrations",
          sales: "Pricing, upgrades, new accounts",
        },
      },
      frustration: {
        type: "score",
        instructions: "How frustrated is the customer?",
        criteria: ["Calm", "Frustrated", "Very angry"],
      },
    },
  },
});

const { is_urgent, department, frustration } = decision.answers;
if (is_urgent.type === "noul" && department.type === "choice" && frustration.type === "score") {
  console.log(is_urgent.noul, department.choice, department.probabilities, frustration.score);
  if (is_urgent.noul > 0.8 && department.choice === "billing") {
    // escalateToBilling(...)
  }
}
```

**JavaScript / TypeScript (plain fetch, no SDK)**

```ts
const response = await fetch("https://openrouter.ai/api/alpha/decisions", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${process.env.OPENROUTER_API_KEY}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    model: "typesafe/jev-1.13",
    state: "Help! My payouts have been failing for 3 days.",
    questions: {
      is_urgent: {
        type: "noul",
        instructions: "Does this message convey urgency?",
        criteria: { true: "Explicitly time-sensitive", false: "No urgency expressed" },
      },
      department: {
        type: "choice",
        instructions: "Which team should handle this?",
        criteria: {
          billing: "Payments, invoicing, refunds",
          technical: "Bugs, outages, integrations",
          sales: "Pricing, upgrades, new accounts",
        },
      },
      frustration: {
        type: "score",
        instructions: "How frustrated is the customer?",
        criteria: ["Calm", "Frustrated", "Very angry"],
      },
    },
  }),
});

const { answers } = await response.json();
console.log(answers.is_urgent.noul);
console.log(answers.department.choice, answers.department.probabilities);
console.log(answers.frustration.score);

if (answers.is_urgent.noul > 0.8 && answers.department.choice === "billing") {
  // escalateToBilling(...)
}
```

**curl**

```bash
curl https://openrouter.ai/api/alpha/decisions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -d '{
    "model": "typesafe/jev-1.13",
    "state": "Help! My payouts have been failing for 3 days.",
    "questions": {
      "is_urgent": {
        "type": "noul",
        "instructions": "Does this message convey urgency?",
        "criteria": {"true": "Explicitly time-sensitive", "false": "No urgency expressed"}
      },
      "department": {
        "type": "choice",
        "instructions": "Which team should handle this?",
        "criteria": {
          "billing": "Payments, invoicing, refunds",
          "technical": "Bugs, outages, integrations",
          "sales": "Pricing, upgrades, new accounts"
        }
      },
      "frustration": {
        "type": "score",
        "instructions": "How frustrated is the customer?",
        "criteria": ["Calm", "Frustrated", "Very angry"]
      }
    }
  }'
```

When adapting a template for the user's code, keep their original LLM call as the fallback, apply a confidence
threshold to the probability (for `choice`, the probability of the chosen label), and handle HTTP errors and timeouts
by falling back. One request can ask several questions about the same `state`, which is cheaper than several calls.

## Rules

- Never apply changes without the user's explicit go-ahead.
- Never present a saving or speedup as measured; quote the report's assumptions.
- Never write an API key into code or commit one; read it from the environment.
- Do not edit generated `_jevify_route(...)` blocks by hand; rerun the tool instead.
- Generative calls, streaming, tool calling and awaited calls are intentionally left alone.
