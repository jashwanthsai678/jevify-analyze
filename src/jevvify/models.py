from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

LEVELS = ("low", "medium", "high")


@dataclass
class Candidate:
    """One LLM call site found in the codebase (refactorable, manual-only, or skipped)."""

    id: str
    file: str  # path relative to the project root, posix separators
    line: int
    end_line: int
    col: int  # utf-8 byte offsets within the line
    end_col: int
    provider: str  # openai | anthropic | google | langchain | vercel
    status: str  # "candidate" | "skipped"
    reason: str
    kind: str | None = None  # "choice" | "noul"
    options: list[str] = field(default_factory=list)
    instructions: str = ""
    prompt: str = ""  # prompt text, dynamic parts rendered as `name`
    variables: dict[str, str] = field(default_factory=dict)  # state key -> source expr
    json_mode: bool = False
    json_key: str | None = None
    language: str = "python"
    reason_code: str = ""  # machine-readable reason, e.g. "generative", "streaming"
    confidence: float = 0.0  # how sure the analyzer is that this is a judgment task (0-1)
    level: str = ""  # low | medium | high, derived from confidence
    signals: list[str] = field(default_factory=list)  # evidence behind the confidence
    rewritable: bool = True  # False: detected, but this language has no automatic rewrite yet

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Candidate:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def level_for(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.55:
        return "medium"
    return "low"


def meets(level: str, minimum: str) -> bool:
    return LEVELS.index(level) >= LEVELS.index(minimum)
