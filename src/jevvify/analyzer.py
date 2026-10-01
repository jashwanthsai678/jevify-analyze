"""Phase 1: find LLM call sites and decide whether each is a judgment task Jev can take."""

from __future__ import annotations

import ast
import hashlib
import re
import string
from collections.abc import Callable
from pathlib import Path

from .classify import assess, build_instructions, classify_prompt, extract_options  # noqa: F401  (re-exported)
from .fsutil import iter_source_files, read_source
from .models import Candidate, level_for

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
            best: ast.Assign | ast.AnnAssign | None = None
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
# Per-file analysis
# ---------------------------------------------------------------------------

def _candidate_id(file: str, node: ast.Call) -> str:
    return candidate_id(file, node.lineno, node.col_offset)


def candidate_id(file: str, line: int, col: int) -> str:
    """Stable id for a call site; shared by every language analyzer."""
    return "jev_" + hashlib.sha1(f"{file}:{line}:{col}".encode()).hexdigest()[:8]


def _truthy_kw(call: ast.Call, name: str) -> bool:
    for kw in call.keywords:
        if kw.arg == name:
            return not (isinstance(kw.value, ast.Constant) and not kw.value.value)
    return False


def _number_kw(call: ast.Call, *names: str) -> float | None:
    for kw in call.keywords:
        if kw.arg in names and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, (int, float)) \
                and not isinstance(kw.value.value, bool):
            return float(kw.value.value)
    return None


def _labels_used_downstream(call: ast.Call, parents: dict[ast.AST, ast.AST], tree: ast.Module,
                            options: list[str]) -> bool:
    """True if code after the call compares something with the label strings (==, in, dict keys, match)."""
    wanted = {o.lower() for o in options}
    scope: ast.AST | None = parents.get(call)
    while scope is not None and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        scope = parents.get(scope)
    for node in ast.walk(scope or tree):
        if getattr(node, "lineno", 0) < call.lineno:
            continue
        consts: list[ast.AST] = []
        if isinstance(node, ast.Compare):
            consts = [node.left, *node.comparators]
            consts += [e for c in node.comparators if isinstance(c, (ast.Tuple, ast.List, ast.Set)) for e in c.elts]
        elif isinstance(node, ast.Dict):
            consts = [k for k in node.keys if k is not None]
        elif isinstance(node, ast.MatchValue):
            consts = [node.value]
        for c in consts:
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.strip().lower() in wanted:
                return True
    return False


def analyze_source(source: str, relpath: str) -> list[Candidate]:
    """Analyze one Python file."""
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

    def skip(code: str, reason: str) -> Candidate:
        return Candidate(**base, status="skipped", reason=reason, reason_code=code)  # type: ignore[arg-type]

    if isinstance(parents.get(node), ast.Await) or _chain(node.func)[-1:] == ["ainvoke"]:
        return skip("async", "async call (Python async rewrite is not supported yet)")
    if _truthy_kw(node, "stream"):
        return skip("streaming", "streaming call")
    if any(kw.arg in {"tools", "functions", "tool_choice"} for kw in node.keywords):
        return skip("tool-calling", "tool/function calling")

    collector = _PromptCollector(tree, parents, node)
    kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
    for name in _PROMPT_KWARGS[provider]:
        if name in kwargs:
            collector.add(kwargs[name])
    if provider == "langchain" and node.args:
        collector.add(node.args[0])
    prompt = "\n".join(p for p in collector.parts if p.strip())
    if not prompt:
        return skip("no-prompt", "no prompt text found")

    json_mode = bool(re.search(
        r"response_format|json_schema|json_object|response_mime_type|response_schema|with_structured_output", segment))
    max_tokens = _number_kw(node, "max_tokens", "max_completion_tokens", "max_output_tokens")
    return finish_candidate(
        base, prompt=prompt, variables=collector.variables, json_mode=json_mode, language="python",
        max_tokens=int(max_tokens) if max_tokens is not None else None,
        temperature=_number_kw(node, "temperature"),
        downstream=lambda options: _labels_used_downstream(node, parents, tree, options),
    )


def finish_candidate(base: dict, *, prompt: str, variables: dict[str, str], json_mode: bool, language: str,
                     max_tokens: int | None = None, temperature: float | None = None,
                     downstream: Callable[[list[str]], bool] | None = None,
                     rewritable: bool = True, manual_reason: str = "") -> Candidate:
    """Shared tail of every language analyzer: classify the prompt text, score it, build the Candidate."""
    kind, options, why = classify_prompt(prompt)
    if kind is None:
        code = "generative" if why.startswith("generative") else "no-label-space"
        return Candidate(**base, status="skipped", reason=why, reason_code=code, prompt=prompt,
                         json_mode=json_mode, language=language)
    if not variables:
        return Candidate(**base, status="skipped", reason="prompt has no dynamic input to classify",
                         reason_code="no-dynamic-input", prompt=prompt, json_mode=json_mode, language=language)
    used = bool(downstream(options)) if downstream else False
    confidence, signals = assess(prompt, kind, options, why, max_tokens=max_tokens, temperature=temperature,
                                 labels_used_downstream=used, json_mode=json_mode)
    key_match = re.search(r'"(\w+)"\s*:', prompt)
    reason = why + (" + structured output requested" if json_mode else "")
    if not rewritable:
        reason += f" ({manual_reason})" if manual_reason else " (manual rewrite)"
    return Candidate(
        **base, status="candidate", reason=reason, reason_code="judgment", kind=kind, options=options,
        instructions=build_instructions(prompt), prompt=prompt, variables=dict(variables),
        json_mode=json_mode, json_key=key_match.group(1) if (json_mode and key_match) else None,
        language=language, confidence=confidence, level=level_for(confidence), signals=signals,
        rewritable=rewritable,
    )


def analyze_project(root: Path, exclude: tuple[Path, ...] = (), warnings: list[str] | None = None) -> list[Candidate]:
    """Analyze every supported source file under ``root``.

    Files whose language adapter is unavailable (e.g. tree-sitter not installed) are counted in ``warnings``.
    """
    from .languages import adapter_for

    root = Path(root).resolve()
    out: list[Candidate] = []
    missing: dict[str, int] = {}
    for path in iter_source_files(root, exclude):
        adapter = adapter_for(path)
        if adapter is None:
            continue
        if not adapter.available():
            missing[adapter.name] = missing.get(adapter.name, 0) + 1
            continue
        try:
            source, _ = read_source(path)
        except (OSError, UnicodeDecodeError):
            continue
        out.extend(adapter.analyze(source, path.relative_to(root).as_posix()))
    if warnings is not None:
        for name, count in sorted(missing.items()):
            warnings.append(f"{count} {name} file(s) not analyzed: install the multilang extra "
                            f"(`pip install \"jevvify[multilang]\"`)")
    return out
