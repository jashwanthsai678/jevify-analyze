"""Language-independent prompt analysis: is this prompt a judgment task, and how sure are we?"""

from __future__ import annotations

import re

# Words that mean the model must produce free text. Nouns like "summary" or "description" are deliberately
# absent: "based on the usage summary" is input, not a request for prose.
_GENERATIVE = re.compile(
    r"\b(write|compose|draft|essay|story|poem|summari[sz]e|explain|describe|translate|rewrite|paraphrase|"
    r"brainstorm|generate|elaborate|expand on|continue|discuss|justify|suggest|propose|why)\b|"
    r"\b(?:list|enumerate|identify|point out|outline)\s+(?:all|every|each|the|any|which|those|its)\b|"
    r"\bwith (?:a |an )?(?:short |brief )?(?:explanation|justification|reason|rationale)\b",
    re.I)
_NEGATED_GENERATIVE = re.compile(
    r"\b(?:do not|don't|never|without|no)\s+(?:any\s+|extra\s+|other\s+)?"
    r"(?:explanations?|explain(?:ing)?|summary|summari[sz]e|description|describe|extra text|commentary|"
    r"justification|justify|reasoning|rationale)(?:\s+your\s+\w+)?\b", re.I)

_VERBS = r"(?:classify|categori[sz]e|label|tag|rate|score|grade|assign|route|sort|mark|flag|bucket|triage)"
_LIST_INTRO = re.compile(
    r"\b(?:" + _VERBS + r"\b[^.\n:?]{0,60}?\b(?:as|into|to)|one of|choose from|choose between|pick one of|"
    r"options?(?: are| include)?|categories(?: are)?|labels?(?: are)?|classes(?: are)?|choices(?: are)?|"
    r"exactly one (?:of|category|label)|either)\b[: \t\-]*",
    re.I)
_ANSWER_INTRO = re.compile(
    r"\b(?:answer|respond|reply|output|return|say)(?: with)?(?: only| just| exactly)?(?: one of)?[: \t]+", re.I)
_PIPE_ALTERNATIVES = re.compile(r"""["']([^"'|\n]{1,30})["'](?:\s*\|\s*["']([^"'|\n]{1,30})["'])+""")
_QUESTION_TAIL = re.compile(
    r"\b(?:which|what|should|is|are|does|do|would|will)\b[^?\n]{0,200}?[:,]?\s+"
    r"((?:[\w&\-]+(?: [\w&\-]+)?,\s*)*[\w&\-]+(?: [\w&\-]+)?,?\s+or\s+[\w&\-]+(?: [\w&\-]+)?)\s*\?", re.I)
_NUMBERED_INLINE = re.compile(r"(?:^|\s)1[.)]\s*([A-Za-z0-9][\w\-]*)(?:\s+\d[.)]\s*[A-Za-z0-9][\w\-]*)+", re.M)
_RANGE = re.compile(r"\b(?:rate|score|grade|rank)\b[^.\n]{0,40}?\b(?:from|between|on a scale of)\s+(\d+)\s*"
                    r"(?:to|-|and)\s*(\d+)\b", re.I)
_CLASSIFY_HEADER = re.compile(r"classif|categor|label|tag|sentiment|priority|severity|intent|type|kind|option|"
                              r"choice|route|bucket|class", re.I)
_BOOL_PAIR = re.compile(r"\b(true\s*(?:/|or)\s*false|yes\s*(?:/|or)\s*no)\b", re.I)
_BOOL_QUESTION = re.compile(
    r"(?:^|[.\n:]\s*)(is|are|does|do|did|should|can|could|has|have|was|were|will|would)\b[^?\n]{3,300}\?", re.I)
_RESPONSE_FORMAT_SENTENCE = re.compile(
    r"\b(respond|reply|return|output|answer with|json|format|only the|nothing else)\b", re.I)
_OPTION_TOKEN = re.compile(r"[A-Za-z0-9][\w\-& ]{0,29}")
_STOPWORDS = {"the", "this", "that", "one", "only", "label", "category", "team", "name"}
# "LOW, MEDIUM, or HIGH based on the usage summary": the qualifier is not part of the last label
_QUALIFIER = re.compile(r"\s+(?:based on|given|according to|depending on|for (?:the|this)|from the|in the|"
                        r"using|only|please)\b.*$", re.I)


def _tokens(rest: str) -> list[str] | None:
    rest = re.sub(r"\(.*?\)", "", rest)
    tokens = re.split(r"\s*,\s*(?:or\s+|and\s+)?|\s+or\s+|\s*/\s*|\s*\|\s*", rest)
    options: list[str] = []
    if tokens:
        tokens[-1] = _QUALIFIER.sub("", tokens[-1])
    for tok in tokens:
        tok = tok.strip().strip("`'\"[]{}() .?")
        if not tok:
            continue
        if not _OPTION_TOKEN.fullmatch(tok) or len(tok.split()) > 3 or tok.lower() in _STOPWORDS:
            return None
        if tok not in options:
            options.append(tok)
    return options if len(options) >= 2 else None


def _split_options(rest: str) -> list[str] | None:
    rest = re.sub(r"^(?:one of|either|the following|[:\s])+", "", rest.strip(), flags=re.I)
    rest = re.split(r"[`\n]", rest, maxsplit=1)[0]
    m = re.search(r"\.(?:\s|$)", rest)
    if m:
        rest = rest[: m.start()]
    before, _, after = rest.partition(":")
    # "to sales or support: `msg`" -> before the colon; "to the right team: HR, IT, Legal" -> after it
    return _tokens(before) or (_tokens(after) if after.strip() else None)


def _bullet_options(lines: list[str]) -> list[str] | None:
    options: list[str] = []
    for line in lines:
        m = re.match(r"\s*(?:[-*•]|\d+[.)])\s*[`'\"]?([A-Za-z0-9][\w\-& ]{0,29}?)[`'\"]?\s*(?:[:–-].*)?$", line)
        if not m:
            if options:
                break
            continue
        options.append(m.group(1).strip())
    return options if len(options) >= 2 else None


def extract_options(text: str) -> list[str] | None:
    """The closed label set a prompt asks the model to choose from, or None."""
    pipe = _PIPE_ALTERNATIVES.search(text)
    if pipe:
        found = re.findall(r"""["']([^"'|\n]{1,30})["']""", pipe.group(0))
        opts = _tokens(", ".join(found))
        if opts:
            return opts
    for pattern in (_LIST_INTRO, _ANSWER_INTRO):
        for m in pattern.finditer(text):
            line_end = text.find("\n", m.end())
            rest = text[m.end(): line_end if line_end != -1 else len(text)]
            if rest.strip():
                opts = _split_options(rest)
            else:
                opts = _bullet_options(text[m.end():].split("\n")[1:])
            if opts:
                return opts
    q = _QUESTION_TAIL.search(text)
    if q:
        opts = _tokens(q.group(1))
        if opts and len(opts[0].split()) > 1 and all(len(o.split()) == 1 for o in opts[1:]):
            opts[0] = opts[0].split()[-1]  # "the agent retry, ask_user, or abort" -> retry
        if opts:
            return opts
    inline = _NUMBERED_INLINE.search(text)
    if inline:
        opts = _tokens(", ".join(re.findall(r"\d[.)]\s*([A-Za-z0-9][\w\-]*)", inline.group(0))))
        if opts:
            return opts
    lines = text.split("\n")
    for i, line in enumerate(lines[:-1]):
        if line.rstrip().endswith(":") and _CLASSIFY_HEADER.search(line):
            opts = _bullet_options(lines[i + 1:])
            if opts:
                return opts
    rng = _RANGE.search(text)
    if rng:
        lo, hi = int(rng.group(1)), int(rng.group(2))
        if 0 <= lo < hi <= 10:
            return [str(i) for i in range(lo, hi + 1)]
    return None


def classify_prompt(text: str) -> tuple[str | None, list[str], str]:
    """Return (kind, options, reason). ``kind`` is None when the prompt is not a judgment task."""
    cleaned = _NEGATED_GENERATIVE.sub("", text)
    gen = _GENERATIVE.search(cleaned)
    if gen:
        return None, [], f"generative prompt (matched '{gen.group(0).lower()}')"
    options = extract_options(text)
    if options:
        lowered = {o.lower() for o in options}
        if lowered == {"true", "false"}:
            return "noul", ["true", "false"], "true/false question"
        if lowered == {"yes", "no"}:
            return "noul", ["yes", "no"], "yes/no question"
        return "choice", options, f"classification over {len(options)} labels"
    pair = _BOOL_PAIR.search(text)
    if pair:
        pos = "true" if pair.group(1).lower().startswith("true") else "yes"
        return "noul", [pos, "false" if pos == "true" else "no"], "boolean question"
    if _BOOL_QUESTION.search(text):
        return "noul", ["true", "false"], "boolean question"
    return None, [], "no discrete label space found (not a judgment task)"


def build_instructions(text: str) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    kept = [s for s in sentences if not _RESPONSE_FORMAT_SENTENCE.search(s)]
    return " ".join(kept or sentences)




# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

_CONSTRAINED_ANSWER = re.compile(
    r"\b(reply with (?:only|just|one)|respond with (?:only|just|one)|answer with (?:only|just|one)|"
    r"only (?:the|one) (?:label|word|category)|one word|single word|nothing else|no other text|label only|"
    r"just the (?:label|category|word))\b", re.I)
_OPEN_QUESTION = re.compile(r"\b(why|how|what are|list|which (?:parts|lines|sections))\b", re.I)


def assess(
    prompt: str,
    kind: str,
    options: list[str],
    why: str,
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
    labels_used_downstream: bool = False,
    json_mode: bool = False,
) -> tuple[float, list[str]]:
    """Confidence (0-1) that a prompt classify_prompt() accepted really is a closed-set decision.

    Returns the score and the signals behind it, each formatted as ``"+0.35 explicit label list"``.
    """
    signals: list[tuple[float, str]] = [(0.35, "base: prompt passed the judgment filter")]
    if why.startswith("classification over"):
        signals.append((0.35, f"explicit list of {len(options)} labels"))
    elif why in ("true/false question", "yes/no question"):
        signals.append((0.35, "explicit yes/no or true/false answer set"))
    elif why == "boolean question" and _has_answer_pair(prompt):
        signals.append((0.30, "answer words stated (yes/no or true/false)"))
    else:
        signals.append((0.15, "phrased as a yes/no question, answer words not stated"))
    if _CONSTRAINED_ANSWER.search(prompt):
        signals.append((0.10, "output constrained to the label"))
    if labels_used_downstream:
        signals.append((0.15, "code compares the response with the labels"))
    if max_tokens is not None:
        if max_tokens <= 16:
            signals.append((0.15, f"max_tokens={max_tokens} leaves no room for prose"))
        elif max_tokens >= 256:
            signals.append((-0.25, f"max_tokens={max_tokens} suggests a long answer"))
    if temperature is not None and temperature == 0:
        signals.append((0.05, "temperature=0"))
    if json_mode:
        signals.append((0.0, "structured output requested (output key is inferred)"))
    if len(options) > 12:
        signals.append((-0.20, f"{len(options)} labels is a large label space"))
    if _OPEN_QUESTION.search(prompt) and kind == "noul":
        signals.append((-0.15, "contains open-question words (why/how/list)"))
    if len(prompt) > 3000:
        signals.append((-0.10, "very long prompt"))
    score = max(0.0, min(1.0, sum(w for w, _ in signals)))
    return round(score, 2), [f"{w:+.2f} {text}" for w, text in signals]


def _has_answer_pair(text: str) -> bool:
    return bool(_BOOL_PAIR.search(text))
