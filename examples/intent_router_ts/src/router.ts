// Chat assistant front door in TypeScript: route intents, guard topics, stream replies.
import OpenAI from "openai";
import { generateText, streamText } from "ai";
import { openai } from "@ai-sdk/openai";

const client = new OpenAI();

export type Intent = "order_status" | "refund" | "product_question" | "other";

/** Closed label set used in a switch: a strong Jev candidate. */
export async function detectIntent(message: string): Promise<Intent> {
  const resp = await client.chat.completions.create({
    model: "gpt-4o-mini",
    max_tokens: 4,
    temperature: 0,
    messages: [
      { role: "system", content: "Classify the customer message as order_status, refund, product_question, or other. Reply with the label only." },
      { role: "user", content: message },
    ],
  });
  const intent = resp.choices[0].message.content?.trim();
  switch (intent) {
    case "order_status":
    case "refund":
    case "product_question":
      return intent;
    default:
      return "other";
  }
}

/** Yes/no guardrail with the Vercel AI SDK. */
export async function isOnTopic(message: string): Promise<boolean> {
  const { text } = await generateText({
    model: openai("gpt-4o-mini"),
    prompt: `Is this message about our online store (orders, refunds, products)? Answer yes or no.\n\n${message}`,
  });
  return text.trim().toLowerCase() === "yes";
}

/** Streaming chat reply: generative and streamed, so jevvify leaves it alone. */
export function reply(message: string) {
  return streamText({ model: openai("gpt-4o"), prompt: `Reply helpfully to: ${message}` });
}
