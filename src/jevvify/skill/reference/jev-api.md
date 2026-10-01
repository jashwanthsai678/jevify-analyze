# Jev API reference

Endpoint: `POST https://openrouter.ai/api/alpha/decisions` · model `typesafe/jev-1.13` · auth `Authorization: Bearer $OPENROUTER_API_KEY`.

A request carries one `state`, which is the text to judge as a single string, and one or more named `questions`
about it. Asking several questions about the same `state` in one request costs one call, not several.

| type | `criteria` | answer fields |
|---|---|---|
| `noul` | `{"true": "<meaning>", "false": "<meaning>"}` | `noul`: probability of true, 0 to 1 |
| `choice` | `{"<label>": "<description>", ...}` | `choice`: chosen label; `probabilities`: label → probability |
| `score` | `["<lowest level>", ..., "<highest level>"]` | `score`: chosen level, plus the distribution |

The model answers; your code owns the workflow. Branch on probabilities and keep a fallback.

## Writing good questions

General advice, not from TypeSafe's documentation:
- Make labels mutually exclusive and describe each one concretely (`"billing": "Payments, invoicing, refunds"`).
- Add an `other` or `unclear` label when real inputs may fit none of them; otherwise Jev must pick a wrong one.
- Reuse the old prompt's own label names, so downstream code that compares strings keeps working.
- Put the data in `state` and the question in `instructions`. With several inputs, label them in `state`
  (`"subject: ...\nbody: ..."`) and refer to them by name in the instructions.

## Hand-written rewrite with fallback

Use this for manual candidates and non-Python code. It does what jevvify's generated code does: ask Jev first, then
fall back to the untouched original call when Jev is unsure or fails.

**Python**

```python
import json, os, urllib.request

def ask_jev(state: str, question: dict, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(
        "https://openrouter.ai/api/alpha/decisions",
        data=json.dumps({"model": "typesafe/jev-1.13", "state": state, "questions": {"q": question}}).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)["answers"]["q"]

def route_ticket(text: str) -> str:
    try:
        a = ask_jev(text, {
            "type": "choice",
            "instructions": "Which team should handle this ticket?",
            "criteria": {"billing": "Payments, invoicing, refunds", "support": "Bugs, accounts, how-to"},
        })
        if a["probabilities"][a["choice"]] >= 0.85:
            return a["choice"]
    except Exception:
        pass  # any Jev problem: use the original call below
    return legacy_route_ticket(text)  # the original LLM call, unchanged
```

**TypeScript**

```ts
async function askJev(state: string, question: object, timeoutMs = 10_000): Promise<any> {
  const res = await fetch("https://openrouter.ai/api/alpha/decisions", {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.OPENROUTER_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: "typesafe/jev-1.13", state, questions: { q: question } }),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`Jev HTTP ${res.status}`);
  return (await res.json()).answers.q;
}

export async function isUrgent(message: string): Promise<boolean> {
  try {
    const a = await askJev(message, {
      type: "noul",
      instructions: "Does this message convey urgency?",
      criteria: { true: "Explicitly time-sensitive", false: "No urgency expressed" },
    });
    if (a.noul >= 0.85) return true;
    if (a.noul <= 0.15) return false;
  } catch {
    // any Jev problem: use the original call below
  }
  return legacyIsUrgent(message); // the original LLM call, unchanged
}
```

For `noul`, confidence means distance from 0.5. Accept above the threshold or below `1 - threshold`, and fall back
in between.

## Raw API templates

**Python (requests)**

```python
import json, os, requests

response = requests.post(
    url="https://openrouter.ai/api/alpha/decisions",
    headers={
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "Content-Type": "application/json",
        "HTTP-Referer": "<YOUR_SITE_URL>",       # optional, for openrouter.ai rankings
        "X-OpenRouter-Title": "<YOUR_SITE_NAME>",  # optional
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

**JavaScript / TypeScript (fetch, no SDK)**

```ts
const response = await fetch("https://openrouter.ai/api/alpha/decisions", {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${process.env.OPENROUTER_API_KEY}`,
    "Content-Type": "application/json",
    "HTTP-Referer": "<YOUR_SITE_URL>",        // optional
    "X-OpenRouter-Title": "<YOUR_SITE_NAME>",  // optional
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
