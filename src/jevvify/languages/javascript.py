"""JavaScript / TypeScript: detection and rewrite via tree-sitter.

Rewrites replace only the call expression, keeping the original call inside an arrow function::

    await jevvifyRoute("jev_ab12cd34", { "text": text }, () => client.chat.completions.create({...}), {...})

JS calls are already promises, so ``await``-ed and ``.then``-chained calls both keep working.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..analyzer import candidate_id, finish_candidate
from ..models import Candidate
from ..splice import indent_of, line_starts, offset
from ._treesitter import ancestors, parser, text, walk

RUNTIME_SOURCE = Path(__file__).parent.parent / "runtime_src" / "jevvify_rt.mjs"
ROUTE = "jevvifyRoute"

_GRAMMAR = {".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
            ".ts": "typescript", ".mts": "typescript", ".cts": "typescript", ".tsx": "tsx"}
_MODULES = [
    (re.compile(r"^openai(/|$)"), "openai"),
    (re.compile(r"^@anthropic-ai/sdk(/|$)"), "anthropic"),
    (re.compile(r"^@google/(genai|generative-ai)(/|$)"), "google"),
    (re.compile(r"^(langchain|@langchain/[\w-]+)(/|$)"), "langchain"),
    (re.compile(r"^(ai|@ai-sdk/[\w-]+)(/|$)"), "vercel"),
]
_IMPORT_RE = re.compile(r"""(?:\bfrom\s*|\brequire\(\s*|\bimport\(\s*|^\s*import\s+)["']([^"']+)["']""", re.M)
_METHODS = [
    (("chat", "completions", "create"), "openai"),
    (("responses", "create"), "openai"),
    (("messages", "create"), "anthropic"),
    (("models", "generateContent"), "google"),
    (("generateContent",), "google"),
    (("invoke",), "langchain"),
]
_FUNCTIONS = {"generateText": "vercel", "streamText": "vercel", "generateObject": "vercel", "streamObject": "vercel"}
_PROMPT_KEYS = {
    "openai": ("instructions", "messages", "input", "prompt"),
    "anthropic": ("system", "messages"),
    "google": ("contents",),
    "vercel": ("system", "prompt", "messages"),
    "langchain": ("input",),
}
_SCOPES = {"function_declaration", "function_expression", "arrow_function", "method_definition",
           "generator_function_declaration", "function", "program"}
_JSON_HINT = re.compile(r"response_format|json_schema|json_object|responseMimeType|responseSchema|"
                        r"withStructuredOutput|output_config")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "'": "'", '"': '"', "`": "`", "\\": "\\"}


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(1)), s)


def _providers(source: str) -> set[str]:
    found = set()
    for spec in _IMPORT_RE.findall(source):
        for pattern, provider in _MODULES:
            if pattern.search(spec):
                found.add(provider)
    return found


def _chain(node: Any, src: bytes) -> list[str]:
    parts: list[str] = []
    while node is not None and node.type == "member_expression":
        prop = node.child_by_field_name("property")
        parts.append(text(prop, src) if prop is not None else "")
        node = node.child_by_field_name("object")
    if node is not None and node.type in ("identifier", "this"):
        parts.append(text(node, src))
    return parts[::-1]


def _object_pairs(obj: Any, src: bytes) -> dict[str, Any]:
    pairs: dict[str, Any] = {}
    if obj is None or obj.type != "object":
        return pairs
    for child in obj.named_children:
        if child.type == "pair":
            key = child.child_by_field_name("key")
            if key is not None:
                pairs[text(key, src).strip("'\"`")] = child.child_by_field_name("value")
        elif child.type == "shorthand_property_identifier":
            pairs[text(child, src)] = child
    return pairs


class _Collector:
    """Flattens prompt expressions into text with `name` placeholders, like the Python analyzer."""

    def __init__(self, src: bytes, call: Any):
        self.src, self.call = src, call
        self.parts: list[str] = []
        self.variables: dict[str, str] = {}
        self._n = 0

    def _key_for(self, node: Any) -> str:
        if node.type in ("identifier", "shorthand_property_identifier"):
            key = text(node, self.src)
        elif node.type == "member_expression" and _chain(node, self.src):
            key = "_".join(p for p in _chain(node, self.src) if p != "this")
        else:
            self._n += 1
            key = f"value_{self._n}"
        expr = text(node, self.src)
        base, i = key, 1
        while key in self.variables and self.variables[key] != expr:
            i += 1
            key = f"{base}_{i}"
        self.variables[key] = expr
        return key

    def _resolve(self, name: str) -> Any | None:
        scope = next((a for a in ancestors(self.call) if a.type in _SCOPES), None)
        best = None
        for n in walk(scope) if scope is not None else []:
            if n.type == "variable_declarator" and n.start_byte < self.call.start_byte:
                ident, value = n.child_by_field_name("name"), n.child_by_field_name("value")
                if ident is not None and value is not None and text(ident, self.src) == name:
                    best = value
        return best

    def add(self, node: Any, depth: int = 0) -> None:
        if node is None:
            return
        t = node.type
        if depth > 8:
            self.parts.append(f"`{self._key_for(node)}`")
        elif t == "string":
            self.parts.append(_unescape(text(node, self.src)[1:-1]))
        elif t == "template_string":
            out = ""
            for ch in node.children:
                if ch.type == "string_fragment":
                    out += text(ch, self.src)
                elif ch.type == "escape_sequence":
                    out += _unescape(text(ch, self.src))
                elif ch.type == "template_substitution":
                    inner = ch.named_children[0] if ch.named_children else ch
                    out += f"`{self._key_for(inner)}`"
            self.parts.append(out)
        elif t in ("identifier", "shorthand_property_identifier"):
            target = self._resolve(text(node, self.src))
            if target is not None:
                self.add(target, depth + 1)
            else:
                self.parts.append(f"`{self._key_for(node)}`")
        elif t == "binary_expression" and text(node.child_by_field_name("operator"), self.src) == "+":
            self.add(node.child_by_field_name("left"), depth + 1)
            self.add(node.child_by_field_name("right"), depth + 1)
        elif t == "array":
            for el in node.named_children:
                self.add(el, depth + 1)
        elif t == "object":
            pairs = _object_pairs(node, self.src)
            for key in ("content", "text", "parts"):
                if key in pairs:
                    self.add(pairs[key], depth + 1)
        elif t in ("parenthesized_expression", "as_expression", "satisfies_expression", "non_null_expression"):
            if node.named_children:
                self.add(node.named_children[0], depth + 1)
        elif t == "call_expression" and node.child_by_field_name("function") is not None \
                and node.child_by_field_name("function").type == "member_expression" \
                and _chain(node.child_by_field_name("function"), self.src)[-1:] == ["trim"]:
            self.add(node.child_by_field_name("function").child_by_field_name("object"), depth + 1)
        else:
            self.parts.append(f"`{self._key_for(node)}`")


def _number(node: Any, src: bytes) -> float | None:
    if node is not None and node.type == "number":
        try:
            return float(text(node, src))
        except ValueError:
            return None
    return None


def _labels_used_downstream(call: Any, src: bytes, options: list[str]) -> bool:
    wanted = {o.lower() for o in options}
    scope = next((a for a in ancestors(call) if a.type in _SCOPES), None)
    for n in walk(scope) if scope is not None else []:
        if n.type == "string" and n.start_byte > call.end_byte and n.parent is not None \
                and n.parent.type in ("binary_expression", "switch_case", "pair", "array", "arguments"):
            if _unescape(text(n, src)[1:-1]).strip().lower() in wanted:
                return True
    return False


def _import_style(path: Path, source: str) -> str:
    suffix = path.suffix
    if suffix in (".ts", ".tsx", ".mts", ".cts"):
        return "ts"
    if suffix == ".cjs":
        return "cjs"
    if suffix == ".mjs":
        return "esm"
    if re.search(r"^\s*(import\s|export\s)", source, re.M):
        return "esm"
    if "require(" in source:
        return "cjs"
    return "esm"


def _ts_extension(source: str) -> str:
    specs = [s for s in _IMPORT_RE.findall(source) if s.startswith(".")]
    if any(s.endswith(".ts") for s in specs):
        return ".ts"
    if any(s.endswith(".js") for s in specs):
        return ".js"
    if specs:
        return ""
    return ".js"


class JavaScriptAdapter:
    name = "javascript"
    suffixes: tuple[str, ...] = tuple(_GRAMMAR)
    can_rewrite = True

    def available(self) -> bool:
        return parser("javascript") is not None and parser("typescript") is not None

    def _parse(self, source: str, relpath: str) -> tuple[Any, bytes] | None:
        p = parser(_GRAMMAR.get(Path(relpath).suffix, "javascript"))
        if p is None:
            return None
        src = source.encode("utf-8")
        return p.parse(src), src

    # -- analysis ---------------------------------------------------------------
    def analyze(self, source: str, relpath: str) -> list[Candidate]:
        providers = _providers(source)
        parsed = self._parse(source, relpath) if providers else None
        if parsed is None:
            return []
        tree, src = parsed
        found = []
        for node in walk(tree.root_node):
            if node.type != "call_expression":
                continue
            fn = node.child_by_field_name("function")
            if fn is None:
                continue
            provider = None
            if fn.type == "member_expression":
                chain = _chain(fn, src)
                for pattern, prov in _METHODS:
                    if prov in providers and tuple(chain[-len(pattern):]) == pattern and len(chain) >= len(pattern):
                        provider = prov
                        break
            elif fn.type == "identifier" and _FUNCTIONS.get(text(fn, src)) in providers:
                provider = _FUNCTIONS[text(fn, src)]
            if provider is None or self._jevvified(node, src):
                continue
            found.append(self._build(node, fn, provider, src, relpath))
        found.sort(key=lambda c: (c.line, c.col))
        return found

    def _jevvified(self, node: Any, src: bytes) -> bool:
        for a in ancestors(node):
            if a.type == "call_expression":
                f = a.child_by_field_name("function")
                if f is not None and text(f, src) == ROUTE:
                    return True
        return False

    def _build(self, node: Any, fn: Any, provider: str, src: bytes, relpath: str) -> Candidate:
        line, col = node.start_point[0] + 1, node.start_point[1]
        base = dict(id=candidate_id(relpath, line, col), file=relpath, line=line, col=col,
                    end_line=node.end_point[0] + 1, end_col=node.end_point[1], provider=provider)

        def skip(code: str, reason: str) -> Candidate:
            return Candidate(**base, status="skipped", reason=reason, reason_code=code,  # type: ignore[arg-type]
                             language="javascript")

        fname = text(fn, src) if fn.type == "identifier" else ""
        if fname.startswith("stream"):
            return skip("streaming", "streaming call")
        if fname == "generateObject":
            return skip("structured-extraction", "generateObject returns a structured object, not a label")
        parent = node.parent
        if parent is not None and parent.type == "member_expression":
            return skip("sdk-promise-helpers", "result used through SDK promise helpers (e.g. .withResponse())")

        args = node.child_by_field_name("arguments")
        first = args.named_children[0] if args is not None and args.named_children else None
        pairs = _object_pairs(first, src)
        if "stream" in pairs and text(pairs["stream"], src) != "false":
            return skip("streaming", "streaming call")
        if any(k in pairs for k in ("tools", "functions", "tool_choice", "toolChoice")):
            return skip("tool-calling", "tool/function calling")

        collector = _Collector(src, node)
        if provider == "langchain":
            collector.add(first)
        for key in _PROMPT_KEYS[provider]:
            if key in pairs:
                collector.add(pairs[key])
        prompt = "\n".join(p for p in collector.parts if p.strip())
        if not prompt:
            return skip("no-prompt", "no prompt text found")

        segment = text(node, src)
        max_tokens = None
        for key in ("max_tokens", "maxTokens", "max_output_tokens", "maxOutputTokens", "max_completion_tokens"):
            max_tokens = max_tokens if max_tokens is not None else _number(pairs.get(key), src)
        return finish_candidate(
            base, prompt=prompt, variables=collector.variables, json_mode=bool(_JSON_HINT.search(segment)),
            language="javascript", max_tokens=int(max_tokens) if max_tokens is not None else None,
            temperature=_number(pairs.get("temperature"), src),
            downstream=lambda options: _labels_used_downstream(node, src, options),
        )

    # -- rewrite ----------------------------------------------------------------
    def render_call(self, c: Candidate, original: str, threshold: float, indent: str) -> str:
        state = "{ " + ", ".join(f"{json.dumps(k)}: {expr}" for k, expr in c.variables.items()) + " }"
        opts = {"kind": c.kind, "instructions": c.instructions, "options": c.options, "shape": c.provider,
                "threshold": threshold, "jsonMode": c.json_mode, "jsonKey": c.json_key}
        inner = indent + "  "
        parts = [json.dumps(c.id), state, f"() => {original}", json.dumps(opts, ensure_ascii=False)]
        return f"{ROUTE}(\n{inner}" + f",\n{inner}".join(parts) + f"\n{indent})"

    def import_line(self, path: Path, source: str) -> str:
        style = _import_style(path, source)
        if style == "cjs":
            return f'const {{ {ROUTE} }} = require("./_jevvify_rt.cjs");'
        if style == "esm":
            return f'import {{ {ROUTE} }} from "./_jevvify_rt.mjs";'
        return f'import {{ {ROUTE} }} from "./_jevvify_rt{_ts_extension(source)}";'

    def translate(self, source: str, candidates: list[Candidate], threshold: float, path: Path) -> str:
        todo = sorted((c for c in candidates if c.status == "candidate" and c.rewritable),
                      key=lambda c: (c.line, c.col), reverse=True)
        if not todo:
            return source
        starts = line_starts(source)
        out, floor, applied = source, len(source) + 1, 0
        for c in todo:
            begin = offset(source, starts, c.line, c.col)
            end = offset(source, starts, c.end_line, c.end_col)
            if end > floor:
                continue
            out = out[:begin] + self.render_call(c, source[begin:end], threshold, indent_of(source, starts, c.line)) \
                + out[end:]
            floor = begin
            applied += 1
        if not applied:
            return source
        line = self.import_line(path, source)
        if line not in out:
            out = self._insert_import(out, line, path)
        err = self.check_syntax(out, path)
        if err:
            raise SyntaxError(err)
        return out

    def _insert_import(self, source: str, line: str, path: Path) -> str:
        parsed = self._parse(source, path.name)
        assert parsed is not None
        tree, src = parsed
        after = 0  # byte offset to insert after
        for child in tree.root_node.named_children:
            is_directive = child.type == "expression_statement" and child.named_children \
                and child.named_children[0].type == "string"
            if is_directive or child.type in ("import_statement", "comment", "hash_bang_line") \
                    or (line.startswith("const") and "require(" in text(child, src)
                        and child.type in ("lexical_declaration", "variable_declaration")):
                after = child.end_byte
            else:
                break
        head = src[:after].decode("utf-8")
        tail = src[after:].decode("utf-8")
        if not head:
            return f"{line}\n{tail}"
        return f"{head}\n{line}{tail if tail.startswith(chr(10)) else chr(10) + tail}"

    def runtime_files(self, source: str, path: Path) -> dict[str, str]:
        js = RUNTIME_SOURCE.read_text(encoding="utf-8")
        style = _import_style(path, source)
        if style == "cjs":
            body = js.replace("export async function", "async function").replace("export function", "function")
            return {"_jevvify_rt.cjs": body + "\nmodule.exports = { jevvifyRoute, askJev };\n"}
        if style == "esm":
            return {"_jevvify_rt.mjs": js}
        return {"_jevvify_rt.ts": "// @ts-nocheck\n" + js}

    def check_syntax(self, source: str, path: Path) -> str | None:
        parsed = self._parse(source, path.name)
        if parsed is None:
            return None
        tree, _ = parsed
        if tree.root_node.has_error:
            return f"{path.name}: rewritten source does not parse"
        return None
