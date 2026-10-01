"""Community forum moderation with Anthropic: two decisions and one generative call."""

import anthropic

client = anthropic.Anthropic()

MODERATION_PROMPT = (
    "You are a content moderator for a gaming forum. Label the post as SAFE, NSFW, HATE, or VIOLENCE. "
    "Reply with the label only."
)


def moderate(post: str) -> str:
    """Closed label set, short output, result drives an if/else: a strong Jev candidate."""
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=5,
        system=MODERATION_PROMPT,
        messages=[{"role": "user", "content": post}],
    )
    label = response.content[0].text.strip()
    if label == "SAFE":
        return "publish"
    return "hold for review"


def needs_human_review(post: str, label: str) -> bool:
    """Yes/no gate."""
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=3,
        messages=[{
            "role": "user",
            "content": f"A classifier labelled this post {label}. Is the post borderline enough that a human "
                       f"moderator should check it? Answer yes or no.\n\nPost: {post}",
        }],
    )
    return response.content[0].text.strip().lower().startswith("yes")


def explain_removal(post: str, label: str) -> str:
    """Generative: the user sees this text, so it stays on the LLM."""
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=300,
        messages=[{"role": "user", "content": f"Write a short, polite note explaining why this post was "
                                              f"removed as {label}: {post}"}],
    )
    return response.content[0].text
