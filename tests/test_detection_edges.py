"""Negative and edge cases for the prompt classifier and the Python analyzer."""

import textwrap

import pytest

from jevvify.analyzer import analyze_source
from jevvify.classify import assess, classify_prompt, extract_options


@pytest.mark.parametrize("prompt", [
    "Summarize the ticket and categorize it as billing or support: `t`",
    "Explain whether this code has a bug: `code`",
    "Is there anything wrong with this contract? Explain the issues. `c`",
    "Write a reply. Is the customer angry? `msg`",
    "Generate 5 category names for these products: `items`",
    "List all the categories this product could belong to: `p`",
    "Should we use Postgres or MySQL here? Discuss the trade-offs. `ctx`",
    "Rate this essay from 1 to 10 with a short justification. `essay`",
    "Translate to French or Spanish depending on `locale`: `text`",
    "Is this a good idea? Why? `plan`",
])
def test_generative_or_open_prompts_are_rejected(prompt):
    kind, options, why = classify_prompt(prompt)
    assert kind is None, (options, why)


@pytest.mark.parametrize("prompt,kind,options", [
    ('Respond with JSON only: {"priority": "URGENT" | "NORMAL" | "LOW"}\n`t`', "choice", ["URGENT", "NORMAL", "LOW"]),
    ("Which tool should handle this: search, calculator, or none?\n`q`", "choice", ["search", "calculator", "none"]),
    ("Should the agent retry, ask_user, or abort? `err`", "choice", ["retry", "ask_user", "abort"]),
    ("Answer ON_TOPIC or OFF_TOPIC.\n`req`", "choice", ["ON_TOPIC", "OFF_TOPIC"]),
    ("Rate the urgency.\n1) P1 2) P2 3) P3\n`incident`", "choice", ["P1", "P2", "P3"]),
    ("Classify the tweet sentiment:\n1) positive\n2) negative\n3) mixed\n`tweet`", "choice",
     ["positive", "negative", "mixed"]),
    ("Rate the review from 1 to 5 stars. Respond with a single digit. `r`", "choice", ["1", "2", "3", "4", "5"]),
    ("Classify churn risk as LOW, MEDIUM, or HIGH based on the summary below.\n`s`", "choice",
     ["LOW", "MEDIUM", "HIGH"]),
    ("Route the email to the correct department: HR, Finance, IT, Legal.\n`body`", "choice",
     ["HR", "Finance", "IT", "Legal"]),
    ("Assign exactly one category: Electronics, Home & Kitchen, Books.\n`title`", "choice",
     ["Electronics", "Home & Kitchen", "Books"]),
    ("Which response is better, A or B? Output only A or B.\n`a`\n`b`", "choice", ["A", "B"]),
    ("Is this review written by a bot? Answer yes or no only. `r`", "noul", ["yes", "no"]),
    ("Classify as safe or unsafe. Do not explain your reasoning. `x`", "choice", ["safe", "unsafe"]),
])
def test_closed_set_prompts(prompt, kind, options):
    got_kind, got_options, _ = classify_prompt(prompt)
    assert (got_kind, got_options) == (kind, options)


def test_options_never_include_sentences():
    assert extract_options("Classify as the thing that best matches what the user wants to do today.") is None


def test_confidence_rises_with_evidence_and_falls_with_room_for_prose():
    weak, _ = assess("Is this friendly? `t`", "noul", ["true", "false"], "boolean question")
    strong, signals = assess("Classify as spam or ham. Reply with one word. `t`", "choice", ["spam", "ham"],
                             "classification over 2 labels", max_tokens=3, temperature=0,
                             labels_used_downstream=True)
    long_answer, _ = assess("Classify as spam or ham. `t`", "choice", ["spam", "ham"],
                            "classification over 2 labels", max_tokens=1000)
    assert weak < 0.55 and long_answer < 0.55 and strong == 1.0  # room for prose drops it below medium
    assert any("compares the response" in s for s in signals)


def test_python_downstream_label_comparison_is_a_signal():
    [c] = analyze_source(textwrap.dedent('''
        import openai
        def f(client, t):
            r = client.chat.completions.create(model="m", messages=[{"role": "user", "content": f"Classify as spam or ham: {t}"}])
            label = r.choices[0].message.content
            return {"spam": 1, "ham": 0}[label]
    '''), "a.py")
    assert any("compares the response" in s for s in c.signals)


def test_unparseable_python_is_ignored():
    assert analyze_source("import openai\ndef broken(:\n", "a.py") == []
