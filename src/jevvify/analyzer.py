"""Phase 1: find LLM call sites and decide whether each is a judgment task Jev can take."""

from __future__ import annotations

import ast
import hashlib
import re
import string
from pathlib import Path

from .fsutil import iter_python_files, read_source
from .models import Candidate

# ---------------------------------------------------------------------------
# Call-site detection
# ---------------------------------------------------------------------------

_LANGCHAIN_ROOTS = {
    "langchain", "langchain_core", "langchain_openai", "langchain_anthropic",
    "langchain_community", "langchain_google_genai",
}
_CALL_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("chat", "completions", "create"), "openai"),
    (("responses", "create"), "openai"),
    (("messages", "create"), "anthropic"),
    (("generate_content",), "google"),
    (("invoke",), "langchain"),
    (("ainvoke",), "langchain"),
]
_PROMPT_KWARGS = {
    "openai": ("instructions", "messages", "input", "prompt"),
    "anthropic": ("system", "messages"),
    "google": ("contents",),
    "langchain": ("input",),
}
_ROLES = {"system", "user", "human", "ai", "assistant", "developer"}


def _imported_providers(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
            if node.module == "google":
                names += [f"google.{a.name}" for a in node.names]
        for name in names:
            root = name.split(".")[0]
            if root == "openai":
                found.add("openai")
            elif root == "anthropic":
                found.add("anthropic")
            elif root in _LANGCHAIN_ROOTS:
                found.add("langchain")
            elif name.startswith(("google.genai", "google.generativeai")):
                found.add("google")
    return found


def _chain(func: ast.AST) -> list[str]:
    """``client.chat.completions.create`` -> [client, chat, completions, create]."""
    parts: list[str] = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return parts[::-1]


def _match_provider(call: ast.Call, providers: set[str]) -> str | None:
    chain = _chain(call.func)
    for pattern, provider in _CALL_PATTERNS:
        if provider in providers and len(chain) >= len(pattern) and tuple(chain[-len(pattern):]) == pattern:
            return provider
    return None


def _is_jevified(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Name) and cur.func.id == "_jevvify_route":
            return True
        cur = parents.get(cur)
    return False


# ---------------------------------------------------------------------------
# Prompt extraction
# ---------------------------------------------------------------------------

class _PromptCollector:
    """Flattens the prompt arguments of a call into text plus a ``variables`` map.

    Dynamic pieces (f-string fields, unresolved names, arbitrary expressions) become
    `name` placeholders in the text and entries in ``variables`` (state key -> source).
    """

    def __init__(self, tree: ast.Module, parents: dict[ast.AST, ast.AST], call: ast.Call):
        self.tree, self.parents, self.call = tree, parents, call
        self.parts: list[str] = []
        self.variables: dict[str, str] = {}
        self._counter = 0

    # -- helpers
    def _bind(self, key: str, expr: str) -> str:
        base, n = key, 1
        while key in self.variables and self.variables[key] != expr:
            n += 1
            key = f"{base}_{n}"
        self.variables[key] = expr
        return key

    def _key_for(self, node: ast.AST) -> str:
        names = _chain(node) if isinstance(node, ast.Attribute) else ([node.id] if isinstance(node, ast.Name) else [])
        if names:
            key = "_".join(names)
        else:
            self._counter += 1
            key = f"value_{self._counter}"
        return self._bind(key, ast.unparse(node))

    def _enclosing_scope(self) -> ast.AST:
        cur = self.parents.get(self.call)
        while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cur = self.parents.get(cur)
        return cur or self.tree

    def _resolve(self, name: str) -> ast.AST | None:
        scope = self._enclosing_scope()
        scopes = [scope] if scope is self.tree else [scope, self.tree]
        for sc in scopes:
            best = None
            for n in ast.walk(sc):
                if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                        and n.targets[0].id == name and n.lineno < self.call.lineno:
                    if best is None or n.lineno > best.lineno:
                        best = n
                elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == name \
                        and n.value is not None and n.lineno < self.call.lineno:
                    if best is None or n.lineno > best.lineno:
                        best = n
            if best is not None:
                return best.value
        return None

    # -- main walk
    def add(self, node: ast.AST, depth: int = 0) -> None:
        if depth > 8:
            self._key_for(node)
            return
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                self.parts.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            text = ""
            for v in node.values:
                if isinstance(v, ast.Constant):
                    text += str(v.value)
                elif isinstance(v, ast.FormattedValue):
                    text += f"`{self._key_for(v.value)}`"
            self.parts.append(text)
        elif isinstance(node, ast.Name):
            target = self._resolve(node.id)
            if target is not None:
                self.add(target, depth + 1)
            else:
                self.parts.append(f"`{self._key_for(node)}`")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            self.add(node.left, depth + 1)
            self.add(node.right, depth + 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant):
            self.add(node.left, depth + 1)
            self._bind("args", ast.unparse(node.right))
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=True):
                if isinstance(k, ast.Constant) and k.value in ("content", "text"):
                    self.add(v, depth + 1)
        elif isinstance(node, ast.Tuple) and len(node.elts) == 2 and isinstance(node.elts[0], ast.Constant) \
                and isinstance(node.elts[0].value, str) and node.elts[0].value.lower() in _ROLES:
            self.add(node.elts[1], depth + 1)
        elif isinstance(node, (ast.List, ast.Tuple)):
            for e in node.elts:
                self.add(e, depth + 1)
        elif isinstance(node, ast.Call):
            self._add_call(node, depth)
        else:
            self.parts.append(f"`{self._key_for(node)}`")

    def _add_call(self, node: ast.Call, depth: int) -> None:
        chain = _chain(node.func)
        last = chain[-1] if chain else ""
        if last.endswith("Message") or last == "ChatMessage":
            arg = next((k.value for k in node.keywords if k.arg == "content"), node.args[0] if node.args else None)
            if arg is not None:
                self.add(arg, depth + 1)
                return
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"strip", "lstrip", "rstrip"}:
            self.add(node.func.value, depth + 1)
            return
        if isinstance(node.func, ast.Attribute) and node.func.attr == "format" \
                and isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str):
            self._add_format(node, node.func.value.value)
            return
        self.parts.append(f"`{self._key_for(node)}`")

    def _add_format(self, node: ast.Call, template: str) -> None:
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        pos = list(node.args)
        text, auto = "", 0
        for literal, field, _spec, _conv in string.Formatter().parse(template):
            text += literal
            if field is None:
                continue
            head = re.split(r"[.\[]", field)[0]
            expr: ast.AST | None
            if head == "":
                expr, auto = (pos[auto] if auto < len(pos) else None), auto + 1
            elif head.isdigit():
                expr = pos[int(head)] if int(head) < len(pos) else None
            else:
                expr = kw.get(head)
            key = self._key_for(expr) if expr is not None else head or "value"
            text += f"`{key}`"
        self.parts.append(text)


# ---------------------------------------------------------------------------
# Judgment-vs-generative classification
# ---------------------------------------------------------------------------

_GENERATIVE = re.compile(
    r"\b(write|compose|draft|essay|story|poem|summari[sz]e|summary|explain|describe|translate|"
    r"rewrite|paraphrase|brainstorm|generate|elaborate|expand|continue)\b", re.I)
_NEGATED_GENERATIVE = re.compile(
    r"\b(?:do not|don't|never|without|no)\s+(?:any\s+|extra\s+)?"
    r"(?:explanations?|explain|summary|summari[sz]e|description|describe|extra text|commentary)\b", re.I)
_LIST_INTRO = re.compile(
    r"\b(?:one of|choose from|choose between|options?(?: are| include)?|categories(?: are)?|labels?(?: are)?|"
    r"categori[sz]e (?:it |this |the |each )?(?:\w+ )?(?:as|into)|"
    r"classify (?:it |this |the |each )?(?:\w+ )?(?:as|into)|"
    r"route (?:it |this |the )?(?:\w+ )?to|either)\b[: \t\-]*",
    re.I)
_BOOL_PAIR = re.compile(r"\b(true\s*(?:/|or)\s*false|yes\s*(?:/|or)\s*no)\b", re.I)
_BOOL_QUESTION = re.compile(
    r"(?:^|[.\n:]\s*)(is|are|does|do|did|should|can|could|has|have|was|were|will|would)\b[^?\n]{3,300}\?", re.I)
_RESPONSE_FORMAT_SENTENCE = re.compile(
    r"\b(respond|reply|return|output|answer with|json|format|only the|nothing else)\b", re.I)
_OPTION_TOKEN = re.compile(r"[A-Za-z][\w\- ]{0,29}")


def _split_options(rest: str) -> list[str] | None:
    rest = re.sub(r"^(?:one of|either|the following|[:\s])+", "", rest.strip(), flags=re.I)
    rest = re.split(r"[:`\n]", rest, maxsplit=1)[0]
    m = re.search(r"\.(?:\s|$)", rest)
    if m:
        rest = rest[: m.start()]
    rest = re.sub(r"\(.*?\)", "", rest)
    tokens = re.split(r"\s*,\s*(?:or\s+|and\s+)?|\s+or\s+|\s*/\s*|\s*\|\s*", rest)
    options: list[str] = []
    for tok in tokens:
        tok = tok.strip().strip("`'\"[]{}() .")
        if not tok:
            continue
        if not _OPTION_TOKEN.fullmatch(tok) or len(tok.split()) > 3:
            return None
        if tok not in options:
            options.append(tok)
    return options if len(options) >= 2 else None


def _bullet_options(text: str, start: int) -> list[str] | None:
    options: list[str] = []
    for line in text[start:].split("\n")[1:]:
        m = re.match(r"\s*(?:[-*•]|\d+[.)])\s*[`'\"]?([A-Za-z][\w\- ]{0,29}?)[`'\"]?\s*(?:[:–-].*)?$", line)
        if not m:
            if options:
                break
            continue
        options.append(m.group(1).strip())
    return options if len(options) >= 2 else None


def extract_options(text: str) -> list[str] | None:
    for m in _LIST_INTRO.finditer(text):
        line_end = text.find("\n", m.end())
        rest = text[m.end(): line_end if line_end != -1 else len(text)]
        opts = _split_options(rest) if rest.strip() else _bullet_options(text, m.start())
        if opts:
            return opts
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
# Per-file analysis
# ---------------------------------------------------------------------------

def _candidate_id(file: str, node: ast.Call) -> str:
    return "jev_" + hashlib.sha1(f"{file}:{node.lineno}:{node.col_offset}".encode()).hexdigest()[:8]


def _truthy_kw(call: ast.Call, name: str) -> bool:
    for kw in call.keywords:
        if kw.arg == name:
            return not (isinstance(kw.value, ast.Constant) and not kw.value.value)
    return False


def analyze_source(source: str, relpath: str) -> list[Candidate]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    providers = _imported_providers(tree)
    if not providers:
        return []
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    found: list[Candidate] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        provider = _match_provider(node, providers)
        if provider is None or _is_jevified(node, parents):
            continue
        found.append(_build(node, provider, source, tree, parents, relpath))
    found.sort(key=lambda c: (c.line, c.col))
    return found


def _build(node: ast.Call, provider: str, source: str, tree: ast.Module,
           parents: dict[ast.AST, ast.AST], relpath: str) -> Candidate:
    segment = ast.get_source_segment(source, node) or ""
    base = dict(
        id=_candidate_id(relpath, node), file=relpath, line=node.lineno, end_line=node.end_lineno or node.lineno,
        col=node.col_offset, end_col=node.end_col_offset or node.col_offset, provider=provider,
    )

    def skip(reason: str, **extra) -> Candidate:
        return Candidate(**base, status="skipped", reason=reason, **extra)

    if isinstance(parents.get(node), ast.Await) or _chain(node.func)[-1:] == ["ainvoke"]:
        return skip("async call (not rewritten)")
    if _truthy_kw(node, "stream"):
        return skip("streaming call")
    if any(kw.arg in {"tools", "functions", "tool_choice"} for kw in node.keywords):
        return skip("tool/function calling")

    collector = _PromptCollector(tree, parents, node)
    kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
    for name in _PROMPT_KWARGS[provider]:
        if name in kwargs:
            collector.add(kwargs[name])
    if provider == "langchain" and node.args:
        collector.add(node.args[0])
    prompt = "\n".join(p for p in collector.parts if p.strip())
    if not prompt:
        return skip("no prompt text found")

    json_mode = bool(re.search(
        r"response_format|json_schema|json_object|response_mime_type|response_schema|with_structured_output", segment))
    kind, options, why = classify_prompt(prompt)
    if kind is None:
        return skip(why, prompt=prompt, json_mode=json_mode)
    if not collector.variables:
        return skip("prompt has no dynamic input to classify", prompt=prompt, json_mode=json_mode)

    key_match = re.search(r'"(\w+)"\s*:', prompt)
    reason = why + (" + structured output requested" if json_mode else "")
    return Candidate(
        **base, status="candidate", reason=reason, kind=kind, options=options,
        instructions=build_instructions(prompt), prompt=prompt, variables=dict(collector.variables),
        json_mode=json_mode, json_key=key_match.group(1) if (json_mode and key_match) else None,
    )


def analyze_project(root: Path, exclude: tuple[Path, ...] = ()) -> list[Candidate]:
    root = Path(root).resolve()
    out: list[Candidate] = []
    for path in iter_python_files(root, exclude):
        try:
            source, _ = read_source(path)
        except (OSError, UnicodeDecodeError):
            continue
        out.extend(analyze_source(source, path.relative_to(root).as_posix()))
    return out
