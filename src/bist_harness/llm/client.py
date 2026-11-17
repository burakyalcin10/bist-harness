"""Minimal client for an Ollama-compatible chat endpoint.

Only the native ``/api/chat`` and ``/api/tags`` routes are used. Every call is
deterministic by default (temperature 0, fixed seed, no thinking output), so the same
question against the same data gives the same tool calls.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import httpx

from bist_harness.errors import LLMUnavailableError


class _NoRequestUrls(logging.Filter):
    """Drop httpx's per-request log lines: they contain the full endpoint URL.

    Other libraries (the MCP SDK among them) switch logging to INFO, at which point
    httpx would print the private server address on every call. A filter on the logger
    holds whatever level the host application picks.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.getMessage().startswith("HTTP Request:")


for _name in ("httpx", "httpcore"):
    _logger = logging.getLogger(_name)
    if not any(isinstance(f, _NoRequestUrls) for f in _logger.filters):
        _logger.addFilter(_NoRequestUrls())


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass(frozen=True)
class ChatResult:
    content: str
    tool_calls: tuple[ToolCall, ...]
    prompt_tokens: int
    completion_tokens: int
    total_duration_s: float
    eval_tokens_per_s: float | None
    raw: dict = field(repr=False, compare=False)
    # True when the text looks like a tool-call attempt that could not be parsed. Such a
    # message is neither an answer nor a call; callers count it as an invalid tool call.
    malformed_tool_call: bool = False


_WRAPPERS = ("<tool_call>", "[TOOL_CALLS]", "<|python_tag|>")
_CALL_KEYS = re.compile(r'"name"\s*:.*"(?:arguments|parameters)"\s*:', re.DOTALL)


def _as_tool_call(obj: object, *, allow_missing_args: bool = False) -> ToolCall | None:
    """Accept {"name": ..., "arguments"|"parameters": {...}}; reject anything else."""
    if not isinstance(obj, dict):
        return None
    obj = obj.get("function", obj) if isinstance(obj.get("function"), dict) else obj
    name = obj.get("name")
    args = obj.get("arguments", obj.get("parameters"))
    if args is None and allow_missing_args:
        args = {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if not isinstance(name, str) or not name or not isinstance(args, dict):
        return None
    return ToolCall(name, args)


def _json_values(text: str):
    """Yield every JSON object or array embedded anywhere in ``text``."""
    decoder = json.JSONDecoder()
    position = 0
    while True:
        starts = [i for i in (text.find("{", position), text.find("[", position)) if i != -1]
        if not starts:
            return
        start = min(starts)
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            position = start + 1
            continue
        yield value
        position = end


def parse_tool_calls(message: dict) -> tuple[ToolCall, ...]:
    """Extract tool calls from a chat message.

    Native ``tool_calls`` win. Small models sometimes write the call into the text
    instead: inside ``<tool_call>`` tags, after ``[TOOL_CALLS]`` or ``<|python_tag|>``,
    in a fenced block, as a list, or as a bare object surrounded by prose. Every JSON
    value in the text is examined. Text that is not shaped like a call yields no calls.
    """
    native = message.get("tool_calls") or []
    parsed = [c for c in (_as_tool_call(c, allow_missing_args=True) for c in native) if c]
    if parsed:
        return tuple(parsed)

    content = message.get("content") or ""
    wrapped = any(marker in content for marker in _WRAPPERS)
    calls: list[ToolCall] = []
    for value in _json_values(content):
        for item in value if isinstance(value, list) else [value]:
            call = _as_tool_call(item, allow_missing_args=wrapped)
            if call:
                calls.append(call)
    return tuple(calls)


def looks_like_tool_call(message: dict) -> bool:
    """True when a message tries to call a tool but nothing could be parsed from it."""
    if parse_tool_calls(message):
        return False
    if message.get("tool_calls"):
        return True
    content = message.get("content") or ""
    return any(marker in content for marker in _WRAPPERS) or bool(_CALL_KEYS.search(content))


class OllamaClient:
    """Chat with one model on one endpoint. The endpoint address never appears in errors."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_s: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        try:
            self._http = httpx.Client(
                base_url=base_url.rstrip("/"), timeout=timeout_s, transport=transport
            )
        except (httpx.InvalidURL, ValueError):
            raise LLMUnavailableError("the LLM endpoint address is not a valid URL") from None

    def _request(self, method: str, path: str, **kwargs) -> dict:
        # Error messages name the failure, never the address or the server's own text:
        # a proxy error body can contain the private host name.
        try:
            response = self._http.request(method, path, **kwargs)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise LLMUnavailableError(
                f"cannot reach the LLM endpoint ({type(exc).__name__})"
            ) from None
        if response.status_code >= 400:
            raise LLMUnavailableError(f"LLM endpoint returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise LLMUnavailableError("LLM endpoint returned a non-JSON response") from None

    def list_models(self) -> list[str]:
        return [m["name"] for m in self._request("GET", "/api/tags").get("models", [])]

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        temperature: float = 0.0,
        seed: int = 42,
        think: bool = False,
        response_format: dict | None = None,
        num_ctx: int | None = None,
    ) -> ChatResult:
        options: dict = {"temperature": temperature, "seed": seed}
        if num_ctx is not None:
            options["num_ctx"] = num_ctx
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": think,
            "options": options,
        }
        if tools:
            payload["tools"] = tools
        if response_format is not None:
            payload["format"] = response_format

        raw = self._request("POST", "/api/chat", json=payload)
        message = raw.get("message") or {}
        eval_count = int(raw.get("eval_count") or 0)
        eval_ns = int(raw.get("eval_duration") or 0)
        return ChatResult(
            content=message.get("content") or "",
            tool_calls=parse_tool_calls(message),
            prompt_tokens=int(raw.get("prompt_eval_count") or 0),
            completion_tokens=eval_count,
            total_duration_s=int(raw.get("total_duration") or 0) / 1e9,
            eval_tokens_per_s=(eval_count / (eval_ns / 1e9)) if eval_ns else None,
            raw=raw,
            malformed_tool_call=looks_like_tool_call(message),
        )
