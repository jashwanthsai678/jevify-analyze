"""Go: detection only (via tree-sitter). Candidates are reported for a manual rewrite.

Go SDK responses are concrete struct types, so a drop-in response shim is not possible without
SDK-version-specific code. The report points to the hand-written Jev-first pattern instead.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..analyzer import candidate_id, finish_candidate
from ..models import Candidate
from ._treesitter import ancestors, parser, text, walk

_IMPORTS = [
    ("github.com/openai/openai-go", "openai"),
    ("github.com/sashabaranov/go-openai", "openai"),
    ("github.com/anthropics/anthropic-sdk-go", "anthropic"),
    ("google.golang.org/genai", "google"),
    ("github.com/google/generative-ai-go", "google"),
    ("github.com/tmc/langchaingo", "langchain"),
]
_METHODS = [
    (("Chat", "Completions", "New"), "openai"),
    (("Responses", "New"), "openai"),
    (("CreateChatCompletion",), "openai"),
    (("Messages", "New"), "anthropic"),
    (("Models", "GenerateContent"), "google"),
    (("GenerateContent",), "google"),
    (("GenerateFromSinglePrompt",), "langchain"),
]
_STREAM = re.compile(r"Stream", re.I)
_SKIP_KEYS = {"Model", "Role", "MaxTokens", "MaxCompletionTokens", "Temperature", "TopP", "N", "Seed"}
_MANUAL = "Go rewrite not automated yet: use the Jev-first pattern from the docs"


def _chain(node: Any, src: bytes) -> list[str]:
    parts: list[str] = []
    while node is not None and node.type == "selector_expression":
        field = node.child_by_field_name("field")
        parts.append(text(field, src) if field is not None else "")
        node = node.child_by_field_name("operand")
    if node is not None and node.type == "identifier":
        parts.append(text(node, src))
    return parts[::-1]


def _go_string(node: Any, src: bytes) -> str:
    raw = text(node, src)
    if node.type == "raw_string_literal":
        return raw[1:-1]
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(m.group(1), m.group(1)),
                  raw[1:-1])


class _Collector:
    def __init__(self, src: bytes, call: Any):
        self.src, self.call = src, call
        self.parts: list[str] = []
        self.variables: dict[str, str] = {}

    def _key(self, node: Any) -> str:
        if node.type == "identifier":
            key = text(node, self.src)
        elif node.type == "selector_expression":
            key = "_".join(_chain(node, self.src)) or f"value_{len(self.variables) + 1}"
        else:
            key = f"value_{len(self.variables) + 1}"
        self.variables[key] = text(node, self.src)
        return key

    def _resolve(self, name: str) -> Any | None:
        scope = next((a for a in ancestors(self.call) if a.type in ("function_declaration", "method_declaration",
                                                                   "func_literal", "source_file")), None)
        best = None
        for n in walk(scope) if scope is not None else []:
            if n.type in ("short_var_declaration", "var_spec", "const_spec") and n.start_byte < self.call.start_byte:
                left = n.child_by_field_name("left") or n.child_by_field_name("name")
                right = n.child_by_field_name("right") or n.child_by_field_name("value")
                if left is not None and right is not None and text(left, self.src).split(",")[0].strip() == name:
                    best = right.named_children[0] if right.type == "expression_list" and right.named_children \
                        else right
        return best

    def add(self, node: Any, depth: int = 0) -> None:
        if node is None or depth > 30:
            return
        t = node.type
        if t in ("interpreted_string_literal", "raw_string_literal"):
            self.parts.append(_go_string(node, self.src))
        elif t == "identifier":
            target = self._resolve(text(node, self.src))
            if target is not None:
                self.add(target, depth + 1)
            elif text(node, self.src) not in ("ctx", "nil", "true", "false"):
                self.parts.append(f"`{self._key(node)}`")
        elif t == "binary_expression" and "+" in [text(c, self.src) for c in node.children if not c.is_named]:
            for c in node.named_children:
                self.add(c, depth + 1)
        elif t == "call_expression":
            fn = node.child_by_field_name("function")
            args = node.child_by_field_name("arguments")
            items = args.named_children if args is not None else []
            if fn is not None and text(fn, self.src) == "fmt.Sprintf" and items and \
                    items[0].type in ("interpreted_string_literal", "raw_string_literal"):
                fmt, rest = _go_string(items[0], self.src), items[1:]
                pieces = re.split(r"%[-+# 0-9.]*[vsdqfx]", fmt)
                out = pieces[0]
                for i, piece in enumerate(pieces[1:]):
                    out += f"`{self._key(rest[i])}`" if i < len(rest) else ""
                    out += piece
                self.parts.append(out)
            else:
                for c in items:
                    self.add(c, depth + 1)
        elif t == "keyed_element":
            kids = node.named_children
            key = text(kids[0], self.src) if kids else ""
            if key not in _SKIP_KEYS and len(kids) > 1:
                self.add(kids[-1], depth + 1)
        elif t in ("composite_literal", "literal_value", "argument_list", "expression_list", "unary_expression",
                   "literal_element", "parenthesized_expression"):
            for c in node.named_children:
                if c.type not in ("type_identifier", "qualified_type", "generic_type"):
                    self.add(c, depth + 1)


class GoAdapter:
    name = "go"
    suffixes: tuple[str, ...] = (".go",)
    can_rewrite = False

    def available(self) -> bool:
        return parser("go") is not None

    def analyze(self, source: str, relpath: str) -> list[Candidate]:
        providers = {prov for path, prov in _IMPORTS if f'"{path}' in source}
        p = parser("go") if providers else None
        if p is None:
            return []
        src = source.encode("utf-8")
        tree = p.parse(src)
        found = []
        for node in walk(tree.root_node):
            if node.type != "call_expression":
                continue
            fn = node.child_by_field_name("function")
            if fn is None or fn.type != "selector_expression":
                continue
            chain = _chain(fn, src)
            provider = next((prov for pattern, prov in _METHODS
                             if prov in providers and len(chain) >= len(pattern)
                             and tuple(chain[-len(pattern):]) == pattern), None)
            if provider is None and providers and chain and _STREAM.search(chain[-1]) \
                    and any(k in chain for k in ("Completions", "Messages", "Models")):
                provider = next(iter(sorted(providers)))
            if provider is None:
                continue
            found.append(self._build(node, chain, provider, src, relpath))
        found.sort(key=lambda c: (c.line, c.col))
        return found

    def _build(self, node: Any, chain: list[str], provider: str, src: bytes, relpath: str) -> Candidate:
        line, col = node.start_point[0] + 1, node.start_point[1]
        base = dict(id=candidate_id(relpath, line, col), file=relpath, line=line, col=col,
                    end_line=node.end_point[0] + 1, end_col=node.end_point[1], provider=provider)
        segment = text(node, src)
        if _STREAM.search(chain[-1]):
            return Candidate(**base, status="skipped", reason="streaming call", reason_code="streaming",  # type: ignore[arg-type]
                             language="go")
        if re.search(r"\bTools\s*:", segment):
            return Candidate(**base, status="skipped", reason="tool/function calling",  # type: ignore[arg-type]
                             reason_code="tool-calling", language="go")
        collector = _Collector(src, node)
        args = node.child_by_field_name("arguments")
        for arg in args.named_children if args is not None else []:
            collector.add(arg)
        prompt = "\n".join(p for p in collector.parts if p.strip())
        if not prompt:
            return Candidate(**base, status="skipped", reason="no prompt text found",  # type: ignore[arg-type]
                             reason_code="no-prompt", language="go")
        mt = re.search(r"MaxTokens\s*:\s*(?:\w+\.Int\()?(\d+)", segment)
        return finish_candidate(
            base, prompt=prompt, variables=collector.variables, language="go",
            json_mode=bool(re.search(r"ResponseFormat|JSONSchema|ResponseMIMEType", segment)),
            max_tokens=int(mt.group(1)) if mt else None, rewritable=False, manual_reason=_MANUAL,
        )

    def translate(self, source: str, candidates: list[Candidate], threshold: float, path: Path) -> str:
        return source

    def runtime_files(self, source: str, path: Path) -> dict[str, str]:
        return {}

    def check_syntax(self, source: str, path: Path) -> str | None:
        p = parser("go")
        if p is None:
            return None
        return "does not parse" if p.parse(source.encode("utf-8")).root_node.has_error else None
