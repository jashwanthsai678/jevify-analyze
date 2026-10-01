---
name: jevvify-lite
description: "Audit a codebase in any language for LLM calls that are really classification or yes/no decisions (routing, triage, intent, moderation, spam, sentiment, labelling, guardrails, 'is this X?' checks) and rewrite them to ask TypeSafe Jev first, keeping the original LLM call as a fallback. Self-contained: no tools to install. Use when the user wants to cut LLM cost or latency on decision-style calls, asks which LLM calls could move to Jev, or wants to call the Jev API. Not for generative calls (writing, summarizing, chat replies)."
---

# /jevvify-lite

Jev (TypeSafe AI, served via OpenRouter as `typesafe/jev-1.13`) answers narrow, typed questions about a piece of text:
a yes/no probability (`noul`) or a pick from fixed labels (`choice`). Many production LLM calls are exactly that kind
of decision, paid for at LLM prices. You find them, judge them, and with the user's consent rewrite them so that they
ask Jev first and fall back to the untouched original call whenever Jev is unsure, slow or unavailable.

Tell the user plainly that Jev is new (early access since September 2026). Its accuracy, speed and cost are vendor
claims until measured on their own data, and this skill is not affiliated with TypeSafe AI.

## What the user asked → what to do

| Request | Do |
|---|---|
| `/jevvify-lite [path]`, "which LLM calls could use Jev?" | Steps 1-3. Change nothing. |
| "apply", "go ahead", "rewrite them" after an audit | Step 4 for the calls the user approves. Without an audit in this conversation, do steps 1-3 first. |
| "how do I call Jev?" | Give the API section below in the user's language. |

## Step 1: Find every LLM call

Search the given path (default: the current project) with Grep. Skip `node_modules`, virtual environments, `dist`,
`build`, vendored code and tests.

| Look for | Patterns |
|---|---|
| Python SDKs | `chat.completions.create`, `responses.create`, `messages.create`, `generate_content`, `.invoke(`, `.ainvoke(`, `litellm.completion` |
| JS/TS SDKs | `chat.completions.create`, `messages.create`, `generateContent`, `generateText`, `generateObject`, `.invoke(` |
| Raw HTTP | `/chat/completions`, `/v1/messages`, `api.openai.com`, `api.anthropic.com`, `openrouter.ai/api` |
| Wrappers | functions that wrap the calls above (`ask_llm`, `classify`, `call_model`, ...); search for their callers too |

For each call, read enough of the code to know the prompt (follow variables, template files and helper functions)
and what happens to the response afterwards.

## Step 2: Judge each call

A call is a Jev candidate only if **all four** hold:

1. **Closed answer set.** The answer is one of a few labels or yes/no, never free text.
2. **Code consumes the answer.** The response feeds an `if`, `switch`/`match`, dict lookup, enum, or a stored label.
   It is not shown to a person as prose. This is the strongest signal, so check it.
3. **Self-contained input.** It judges text passed in the call, not knowledge the model must recall.
4. **Short output.** The code does not rely on reasoning, explanations or extracted fields from the response.

For each candidate, write down:
- **type:** `choice` (fixed labels) or `noul` (yes/no);
- **labels:** exactly as the current code expects them, including case;
- **state:** the input text, built from the prompt's variables;
- **instructions:** the question, taken from the prompt without its formatting rules ("reply with one word").

Leave alone: generative calls, tool or function calling, streaming, multi-turn conversations, calls whose output
the code parses into several fields, and anything you are unsure about. Prefer skipping to guessing.

## Step 3: Report (and stop)

```
**Jev candidates: N of M LLM calls**

| # | Call site | Decides | Type | Labels | Notes |
|---|---|---|---|---|---|
| 1 | src/support.py:42 | which team gets a ticket | choice | billing, support | label used in `ROUTES[...]` |

**Not candidates**: file:line with a short reason (or a count by reason if there are many)
**Unsure**: file:line and what would settle it
```

Then say what rewriting involves (one helper file plus a small change per call site; behaviour is unchanged until
`OPENROUTER_API_KEY` is set) and ask which numbers to rewrite. Do not quote cost or speed savings as fact. If the user
asks, explain that savings depend on call volume, the fallback rate and Jev's real price, none of which you know.

## Step 4: Rewrite (only the calls the user approved)

1. **Add the helper once** per project, in the project's language, using the code below. Put it next to the
   existing LLM client code. Match the project's style, but keep the logic.
2. **At each call site**, move the original call and its response parsing into a function that returns the same
   value the code used before (the label string or the boolean). That function is the fallback, and its body is the
   original code, unchanged. Then replace the call with `decide(...)`.
3. **Labels must round-trip.** `choice` returns the label key exactly as written in `criteria`, so use the strings
   the downstream code compares against. `noul` returns a boolean; adapt it if the code expected `"yes"`/`"no"`.
4. **Async code:** in Python, write an `async` variant (`await asyncio.to_thread(_ask, ...)` for the HTTP call,
   `await fallback()`). The TypeScript helper is already async.
5. **Show the diff**, add `OPENROUTER_API_KEY` (and optionally the `JEV_*` settings) to the project's env example
   or docs, and run the tests if you know the command. Report the result as it is.
6. **Suggest shadow mode before going live:** with `JEV_MODE=shadow` the app keeps using the LLM answer and logs
   both answers, so the user can measure agreement on real traffic before switching to `live`.

Settings, all optional: `JEV_MODE` = `live` (default) | `shadow` | `off`; `JEV_THRESHOLD` (default 0.85);
`JEV_MODEL` (default `typesafe/jev-1.13`); `JEV_ENDPOINT`. Without `OPENROUTER_API_KEY`, every call silently uses
the fallback, so deploying the change before the key exists is safe.

### Python helper (`jev_decide.py`)

```python
"""Jev-first decisions with an LLM fallback (written by the jevvify-lite skill)."""

import json
import logging
import os
import urllib.request

log = logging.getLogger("jev")


def _ask(state: str, question: dict, timeout: float = 10.0) -> dict:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    body = {"model": os.environ.get("JEV_MODEL", "typesafe/jev-1.13"), "state": state, "questions": {"q": question}}
    req = urllib.request.Request(
        os.environ.get("JEV_ENDPOINT", "https://openrouter.ai/api/alpha/decisions"),
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)["answers"]["q"]


def decide(state: str, question: dict, fallback, name: str = "decision"):
    """Jev's answer when it is confident enough, otherwise ``fallback()``.

    ``choice`` questions return the label key; ``noul`` questions return True or False.
    ``fallback`` is the original LLM call and must return the same kind of value.
    """
    mode = os.environ.get("JEV_MODE", "live")
    if mode == "off":
        return fallback()
    answer, confidence = None, 0.0
    try:
        a = _ask(state, question)
        if question["type"] == "choice":
            answer, confidence = a["choice"], float(a["probabilities"][a["choice"]])
        else:
            p = float(a["noul"])
            answer, confidence = p >= 0.5, max(p, 1.0 - p)
    except Exception as exc:  # any Jev problem means: use the original call
        log.warning("jev %s failed: %s", name, exc)
    if mode == "shadow":
        legacy = fallback()
        log.info("jev shadow %s", json.dumps(
            {"name": name, "jev": answer, "confidence": confidence, "legacy": legacy}, default=str))
        return legacy
    if answer is not None and confidence >= float(os.environ.get("JEV_THRESHOLD", "0.85")):
        return answer
    return fallback()
```

### TypeScript helper (`jevDecide.ts`)

```ts
// Jev-first decisions with an LLM fallback (written by the jevvify-lite skill).
export type JevQuestion =
  | { type: "choice"; instructions: string; criteria: Record<string, string> }
  | { type: "noul"; instructions: string; criteria: { true: string; false: string } };

async function ask(state: string, question: JevQuestion, timeoutMs = 10_000): Promise<any> {
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) throw new Error("OPENROUTER_API_KEY is not set");
  const res = await fetch(process.env.JEV_ENDPOINT ?? "https://openrouter.ai/api/alpha/decisions", {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: process.env.JEV_MODEL ?? "typesafe/jev-1.13", state, questions: { q: question } }),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`Jev HTTP ${res.status}`);
  return (await res.json()).answers.q;
}

/** Jev's answer when confident enough, otherwise `fallback()` (the original LLM call, same return type). */
export async function decide<T>(state: string, question: JevQuestion, fallback: () => Promise<T>, name = "decision"): Promise<T> {
  const mode = process.env.JEV_MODE ?? "live";
  if (mode === "off") return fallback();
  let answer: unknown = null;
  let confidence = 0;
  try {
    const a = await ask(state, question);
    if (question.type === "choice") {
      answer = a.choice;
      confidence = Number(a.probabilities[a.choice]);
    } else {
      answer = a.noul >= 0.5;
      confidence = Math.max(a.noul, 1 - a.noul);
    }
  } catch (err) {
    console.warn(`jev ${name} failed:`, err); // any Jev problem means: use the original call
  }
  if (mode === "shadow") {
    const legacy = await fallback();
    console.info("jev shadow", JSON.stringify({ name, jev: answer, confidence, legacy }));
    return legacy;
  }
  if (answer !== null && confidence >= Number(process.env.JEV_THRESHOLD ?? "0.85")) return answer as T;
  return fallback();
}
```

### Example rewrite (Python)

Before:

```python
def route_ticket(text: str) -> str:
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": "Route to billing or support. Reply with one word."},
                  {"role": "user", "content": f"Ticket: {text}"}],
    )
    return resp.choices[0].message.content.strip().lower()
```

After:

```python
from jev_decide import decide


def _route_ticket_llm(text: str) -> str:  # the original call, unchanged
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": "Route to billing or support. Reply with one word."},
                  {"role": "user", "content": f"Ticket: {text}"}],
    )
    return resp.choices[0].message.content.strip().lower()


def route_ticket(text: str) -> str:
    return decide(
        state=text,
        question={
            "type": "choice",
            "instructions": "Which team should handle this support ticket?",
            "criteria": {"billing": "Payments, invoices, refunds, charges", "support": "Bugs, accounts, how-to questions"},
        },
        fallback=lambda: _route_ticket_llm(text),
        name="route_ticket",
    )
```

## Jev API essentials

`POST https://openrouter.ai/api/alpha/decisions` with header `Authorization: Bearer $OPENROUTER_API_KEY`. The body
holds one `state` (the text to judge, a single string) and named `questions`. Asking several questions about the same
`state` in one request costs one call.

| type | `criteria` | answer fields |
|---|---|---|
| `noul` | `{"true": "<meaning>", "false": "<meaning>"}` | `noul`: probability of true, 0 to 1 |
| `choice` | `{"<label>": "<description>", ...}` | `choice`: the label; `probabilities`: label → probability |
| `score` | `["<lowest level>", ..., "<highest level>"]` | `score`: the level, plus the distribution |

```bash
curl https://openrouter.ai/api/alpha/decisions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -d '{"model": "typesafe/jev-1.13",
       "state": "Help! My payouts have been failing for 3 days.",
       "questions": {
         "is_urgent": {"type": "noul", "instructions": "Does this message convey urgency?",
                       "criteria": {"true": "Explicitly time-sensitive", "false": "No urgency expressed"}},
         "department": {"type": "choice", "instructions": "Which team should handle this?",
                        "criteria": {"billing": "Payments, invoicing, refunds",
                                     "technical": "Bugs, outages, integrations",
                                     "sales": "Pricing, upgrades, new accounts"}}}}'
# response shape: {"answers": {"is_urgent": {"noul": <0..1>}, "department": {"choice": "<label>", "probabilities": {...}}}}
```

Tips for good questions (general advice, not from TypeSafe's docs):
- Make labels mutually exclusive and describe each one concretely.
- Add an `other` label when real inputs may fit none of them.
- With several inputs, label them in `state` (`"subject: ...\nbody: ..."`) and refer to them by name in the instructions.

## Rules

- Change nothing before the user has seen the audit and approved specific calls.
- Keep every original LLM call intact as the fallback. Never delete or alter its prompt or parsing.
- Never put an API key in code, examples, commits or logs. Read it from the environment.
- Never present cost or latency savings as measured. Recommend shadow mode to measure them.
- When in doubt about a call, leave it on the LLM and list it as unsure.
