"""jevvify runtime, copied next to refactored files as ``_jevvify_rt.py``.

``route`` asks TypeSafe Jev first and only calls the original LLM (``fallback``) when Jev is
unavailable, errors, or is less confident than the threshold. Standard library only; the
``typesafe_sdk`` import is lazy so the legacy path never depends on it.

Backends: with OPENROUTER_API_KEY set, Jev is called over REST (POST /api/alpha/decisions, model
typesafe/jev-1.13); otherwise the ``typesafe-sdk`` package is used.

Environment:
  OPENROUTER_API_KEY  selects the REST backend
  JEVVIFY_MODEL / JEVVIFY_ENDPOINT / JEVVIFY_TIMEOUT  REST overrides (timeout default 10s)
  JEVVIFY_MODE       live (default) | shadow (run both, return legacy, log) | off (legacy only)
  JEVVIFY_THRESHOLD  overrides the generated threshold
  JEVVIFY_LOG        shadow log path (default ./.jevvify_shadow.jsonl)
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

_client = None
_lock = threading.Lock()


def _get_client():
    global _client
    with _lock:
        if _client is None:
            from typesafe_sdk import TypeSafeClient

            _client = TypeSafeClient()
        return _client


def _answer(response: Any, key: str) -> Any:
    for attr in ("answers", "choices"):
        container = getattr(response, attr, None)
        if container is not None:
            try:
                return container[key]
            except (KeyError, TypeError, IndexError):
                continue
    raise LookupError(f"no answer {key!r} in Jev response")


def _state_text(state: dict) -> str:
    """Jev's `state` is one string; label each input so instructions can refer to it by name."""
    return "\n".join(f"{k}: {v}" for k, v in state.items())


def _ask_rest(kind: str, instructions: str, options: list[str], state: dict) -> tuple[str, float]:
    """POST /api/alpha/decisions (OpenRouter). Standard library only; no SDK needed."""
    import urllib.request

    if kind == "choice":
        question = {"type": "choice", "instructions": instructions, "criteria": {o: o for o in options}}
    else:
        question = {"type": "noul", "instructions": instructions,
                    "criteria": {"true": options[0], "false": options[1]}}
    body = json.dumps({
        "model": os.environ.get("JEVVIFY_MODEL", "typesafe/jev-1.13"),
        "state": _state_text(state),
        "questions": {"q": question},
    }).encode("utf-8")
    req = urllib.request.Request(
        os.environ.get("JEVVIFY_ENDPOINT", "https://openrouter.ai/api/alpha/decisions"),
        data=body, method="POST",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=float(os.environ.get("JEVVIFY_TIMEOUT", "10"))) as resp:
        ans = json.loads(resp.read().decode("utf-8"))["answers"]["q"]
    if kind == "choice":
        label = ans["choice"]
        probs = ans.get("probabilities") or {}
        conf = probs.get(label, ans.get("confidence", max(probs.values()) if probs else 0.0))
        return str(label), float(conf)
    p = float(ans["noul"])  # probability of "true"
    return (options[0] if p >= 0.5 else options[1]), max(p, 1.0 - p)


def ask_jev(kind: str, instructions: str, options: list[str], state: dict) -> tuple[str, float]:
    """Return (label, confidence in [0, 1]). Raises on any failure.

    Uses the REST endpoint when OPENROUTER_API_KEY is set, otherwise the typesafe-sdk package.
    """
    if os.environ.get("OPENROUTER_API_KEY"):
        return _ask_rest(kind, instructions, options, state)
    from typesafe_sdk import Choice, Noul

    state = {k: v if isinstance(v, str) else str(v) for k, v in state.items()}
    if kind == "choice":
        question = Choice(instructions=instructions, criteria={o: None for o in options})
    else:
        question = Noul(instructions=instructions)
    ans = _answer(_get_client().system_one(state=state, questions={"q": question}), "q")
    if kind == "choice":
        label = ans.choice
        probs = getattr(ans, "probabilities", None) or {}
        conf = getattr(ans, "confidence", None)
        if conf is None:
            conf = probs.get(label) if probs else None
        if conf is None:
            conf = max(probs.values()) if probs else 0.0
        return str(label), float(conf)
    p = float(ans.noul)
    return (options[0] if p >= 0.5 else options[1]), max(p, 1.0 - p)


def _text_for(label: str, options: list[str], kind: str, json_mode: bool, json_key: str | None) -> str:
    if not json_mode:
        return label
    value: Any = label
    if kind == "noul" and label in ("true", "false"):
        value = label == "true"
    return json.dumps({json_key or "label": value})


def _shim(shape: str, text: str) -> Any:
    ns = SimpleNamespace
    if shape == "openai":
        msg = ns(role="assistant", content=text, tool_calls=None, refusal=None)
        return ns(
            choices=[ns(index=0, message=msg, finish_reason="stop")], model="jev",
            output_text=text, usage=None, _jevvify=True,
        )
    if shape == "anthropic":
        return ns(
            content=[ns(type="text", text=text)], role="assistant", stop_reason="end_turn",
            model="jev", usage=None, _jevvify=True,
        )
    if shape == "google":
        return ns(text=text, candidates=[], _jevvify=True)
    try:
        from langchain_core.messages import AIMessage

        return AIMessage(content=text)
    except Exception:
        return ns(content=text, type="ai", _jevvify=True)


def _extract_text(resp: Any) -> str | None:
    """Best-effort text from a legacy provider response, for shadow comparison."""
    try:
        if isinstance(resp, str):
            return resp
        if getattr(resp, "output_text", None):
            return resp.output_text
        if getattr(resp, "choices", None):
            return resp.choices[0].message.content
        content = getattr(resp, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list) and content:
            return getattr(content[0], "text", None)
        return getattr(resp, "text", None)
    except Exception:
        return None


def _log(record: dict) -> None:
    path = os.environ.get("JEVVIFY_LOG", ".jevvify_shadow.jsonl")
    try:
        with _lock, open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def route(
    cid: str,
    state: dict,
    fallback: Callable[[], Any],
    *,
    kind: str,
    instructions: str,
    options: list[str],
    shape: str,
    threshold: float = 0.85,
    json_mode: bool = False,
    json_key: str | None = None,
) -> Any:
    mode = os.environ.get("JEVVIFY_MODE", "live")
    if mode == "off":
        return fallback()
    thr = float(os.environ.get("JEVVIFY_THRESHOLD", threshold))
    label: str | None = None
    conf = 0.0
    error: str | None = None
    t0 = time.perf_counter()
    try:
        label, conf = ask_jev(kind, instructions, options, state)
    except Exception as exc:  # any Jev failure must degrade to the legacy path
        error = f"{type(exc).__name__}: {exc}"
    jev_ms = (time.perf_counter() - t0) * 1000

    if mode == "shadow":
        t1 = time.perf_counter()
        legacy = fallback()
        _log({
            "id": cid, "jev_label": label, "confidence": conf, "error": error, "jev_ms": jev_ms,
            "legacy_ms": (time.perf_counter() - t1) * 1000, "legacy_text": _extract_text(legacy),
            "state": state,
        })
        return legacy

    if label is not None and conf >= thr:
        return _shim(shape, _text_for(label, options, kind, json_mode, json_key))
    return fallback()
