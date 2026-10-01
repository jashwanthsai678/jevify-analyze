// jevvify runtime for JavaScript/TypeScript, copied next to rewritten files.
//
// jevvifyRoute() asks TypeSafe Jev first (POST /api/alpha/decisions via OpenRouter, built-in fetch, no npm
// packages) and only calls the original LLM (`fallback`) when Jev is unavailable, errors, times out, or is less
// confident than the threshold.
//
// Environment:
//   OPENROUTER_API_KEY   required for Jev; without it every call uses the fallback
//   JEVVIFY_MODE         live (default) | shadow (run both, return the LLM answer, log) | off (LLM only)
//   JEVVIFY_THRESHOLD    overrides the generated threshold
//   JEVVIFY_MODEL / JEVVIFY_ENDPOINT / JEVVIFY_TIMEOUT (seconds, default 10)
//   JEVVIFY_LOG          JSONL log path for shadow (and, with JEVVIFY_LOG_LIVE=1, live) decisions
//   JEVVIFY_LOG_STATE=1  also log the inputs sent to Jev (off by default: they may contain user data)

const env = () => (globalThis.process && globalThis.process.env) || {};

export async function askJev(kind, instructions, options, state) {
  const e = env();
  if (!e.OPENROUTER_API_KEY) throw new Error("OPENROUTER_API_KEY is not set");
  const question = kind === "choice"
    ? { type: "choice", instructions, criteria: Object.fromEntries(options.map((o) => [o, o])) }
    : { type: "noul", instructions, criteria: { true: options[0], false: options[1] } };
  const stateText = Object.entries(state).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("\n");
  const res = await fetch(e.JEVVIFY_ENDPOINT || "https://openrouter.ai/api/alpha/decisions", {
    method: "POST",
    headers: { Authorization: `Bearer ${e.OPENROUTER_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ model: e.JEVVIFY_MODEL || "typesafe/jev-1.13", state: stateText, questions: { q: question } }),
    signal: AbortSignal.timeout(Number(e.JEVVIFY_TIMEOUT || 10) * 1000),
  });
  if (!res.ok) throw new Error(`Jev HTTP ${res.status}`);
  const a = (await res.json()).answers.q;
  if (kind === "choice") {
    const probs = a.probabilities || {};
    const conf = probs[a.choice] ?? a.confidence ?? Math.max(0, ...Object.values(probs));
    return [String(a.choice), Number(conf)];
  }
  const p = Number(a.noul);
  return [p >= 0.5 ? options[0] : options[1], Math.max(p, 1 - p)];
}

function textFor(label, kind, jsonMode, jsonKey) {
  if (!jsonMode) return label;
  const value = kind === "noul" && (label === "true" || label === "false") ? label === "true" : label;
  return JSON.stringify({ [jsonKey || "label"]: value });
}

function shim(shape, text) {
  const tag = { _jevvify: true, model: "jev" };
  switch (shape) {
    case "openai":
      return { ...tag, choices: [{ index: 0, message: { role: "assistant", content: text, refusal: null },
        finish_reason: "stop" }], output_text: text, usage: null };
    case "anthropic":
      return { ...tag, role: "assistant", content: [{ type: "text", text }], stop_reason: "end_turn", usage: null };
    case "google":
      return { ...tag, text, candidates: [{ content: { parts: [{ text }] } }], response: { text: () => text } };
    case "vercel":
      return { ...tag, text, finishReason: "stop" };
    default: // langchain: AIMessage-like
      return { ...tag, content: text, text };
  }
}

function legacyText(resp) {
  try {
    if (typeof resp === "string") return resp;
    if (resp?.output_text) return resp.output_text;
    if (resp?.choices?.length) return resp.choices[0].message.content;
    if (typeof resp?.content === "string") return resp.content;
    if (Array.isArray(resp?.content) && resp.content.length) return resp.content[0].text ?? null;
    if (typeof resp?.text === "string") return resp.text;
    if (typeof resp?.response?.text === "function") return resp.response.text();
  } catch {
    // fall through
  }
  return null;
}

function log(record) {
  const line = JSON.stringify(record);
  const fs = globalThis.process?.getBuiltinModule?.("node:fs");
  if (fs) {
    try {
      fs.appendFileSync(env().JEVVIFY_LOG || ".jevvify_shadow.jsonl", line + "\n");
      return;
    } catch {
      // fall back to the console
    }
  }
  console.info("[jevvify] " + line);
}

export async function jevvifyRoute(cid, state, fallback, opts) {
  const e = env();
  const mode = e.JEVVIFY_MODE || "live";
  if (mode === "off") return fallback();
  const threshold = Number(e.JEVVIFY_THRESHOLD ?? opts.threshold ?? 0.85);
  let label = null;
  let confidence = 0;
  let error = null;
  const t0 = performance.now();
  try {
    [label, confidence] = await askJev(opts.kind, opts.instructions, opts.options, state);
  } catch (err) {
    error = String(err && err.message ? err.message : err);
  }
  const jevMs = performance.now() - t0;
  const accepted = label !== null && confidence >= threshold;
  const record = { ts: new Date().toISOString(), id: cid, mode, kind: opts.kind, options: opts.options, threshold,
    jev_label: label, confidence, error, jev_ms: jevMs, decision: error ? "error" : accepted ? "jev" : "fallback" };
  if (e.JEVVIFY_LOG_STATE === "1") record.state = state;

  if (mode === "shadow") {
    const t1 = performance.now();
    const legacy = await fallback();
    log({ ...record, legacy_ms: performance.now() - t1, legacy_text: legacyText(legacy) });
    return legacy;
  }
  if (e.JEVVIFY_LOG_LIVE === "1") log(record);
  if (accepted) return shim(opts.shape, textFor(label, opts.kind, opts.jsonMode, opts.jsonKey));
  return fallback();
}
