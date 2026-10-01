from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Candidate:
    """One LLM call site found in the codebase (either refactorable or skipped)."""

    id: str
    file: str  # path relative to the project root, posix separators
    line: int
    end_line: int
    col: int  # utf-8 byte offsets, as reported by ``ast``
    end_col: int
    provider: str  # openai | anthropic | google | langchain
    status: str  # "candidate" | "skipped"
    reason: str
    kind: str | None = None  # "choice" | "noul"
    options: list[str] = field(default_factory=list)
    instructions: str = ""
    prompt: str = ""  # prompt text, dynamic parts rendered as `name`
    variables: dict[str, str] = field(default_factory=dict)  # state key -> source expr
    json_mode: bool = False
    json_key: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Candidate:
        return cls(**data)
