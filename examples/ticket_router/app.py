"""A small support-desk app with two LLM calls: one is a routing decision, one is generative."""

from openai import OpenAI

client = OpenAI()


def route_ticket(text: str) -> str:
    """Pure classification: a good fit for Jev."""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Route to billing or support. Reply with one word."},
            {"role": "user", "content": f"Ticket: {text}"},
        ],
    )
    return response.choices[0].message.content


def draft_reply(text: str) -> str:
    """Generative: jevify leaves this alone."""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"Write a friendly reply to this ticket: {text}"}],
    )
    return response.choices[0].message.content
