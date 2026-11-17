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

_TOOL_CALL_TAG = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


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


def _as_tool_call(obj: object) -> ToolCall | None:
    """Accept {"name": ..., "arguments"|"parameters": {...}}; reject anything else."""
    if not isinstance(obj, dict):
        return None
    obj = obj.get("function", obj) if isinstance(obj.get("function"), dict) else obj
    name = obj.get("name")
    args = obj.get("arguments", obj.get("parameters"))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if not isinstance(name, str) or not name or not isinstance(args, dict):
        return None
    return ToolCall(name, args)


def _loads(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def parse_tool_calls(message: dict) -> tuple[ToolCall, ...]:
    """Extract tool calls from a chat message.

    Native ``tool_calls`` win. Small models sometimes write the call into the text
    instead, so ``<tool_call>`` tags, a fenced JSON block and a bare JSON object are
    also recognised. Text that is not shaped like a call yields no calls.
    """
    native = [c for c in map(_as_tool_call, message.get("tool_calls") or []) if c]
    if native:
        return tuple(native)

    content = (message.get("content") or "").strip()
    if not content:
        return ()
    candidates = _TOOL_CALL_TAG.findall(content) or _JSON_FENCE.findall(content)
    if not candidates and content.startswith("{"):
        candidates = [content]
    calls = [c for c in (_as_tool_call(_loads(text.strip())) for text in candidates) if c]
    return tuple(calls)


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
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout_s, transport=transport
        )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(
                f"cannot reach the LLM endpoint ({type(exc).__name__})"
            ) from None
        if response.status_code >= 400:
            detail = response.text.strip().replace("\n", " ")[:200]
            raise LLMUnavailableError(
                f"LLM endpoint returned HTTP {response.status_code}: {detail}"
            )
        return response.json()

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
        )
