"""Payment fraud triage with LangChain: a risk decision, an extraction, and an async call."""

from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o", temperature=0)


def risk_level(transaction_json: str) -> str:
    """Closed ordinal labels: a Jev candidate."""
    prompt = (
        "You review card transactions for a payments company. Classify the fraud risk of this transaction as "
        "low, medium, or high. Reply with one word.\n\n"
        f"Transaction: {transaction_json}"
    )
    return llm.invoke(prompt).content.strip().lower()


def merchant_name(raw_descriptor: str) -> str:
    """Extraction of a value, not a decision: left on the LLM."""
    return llm.invoke(f"What is the merchant name in this card statement descriptor? {raw_descriptor}").content


async def risk_level_async(transaction_json: str) -> str:
    """Async: jevvify does not rewrite async Python calls yet, and says so."""
    msg = await llm.ainvoke(f"Classify the fraud risk as low, medium, or high: {transaction_json}")
    return msg.content
