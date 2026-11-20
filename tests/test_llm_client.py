"""OllamaClient: deterministic request options, tool-call parsing and failure modes."""

import json

import httpx
import pytest

from bist_harness.errors import LLMUnavailableError
from bist_harness.llm.client import OllamaClient, ToolCall, parse_tool_calls


def _client(handler) -> OllamaClient:
    return OllamaClient("http://llm.test", "m", transport=httpx.MockTransport(handler))


def _reply(message: dict, **extra) -> httpx.Response:
    body = {"model": "m", "message": {"role": "assistant", **message}, "done": True, **extra}
    return httpx.Response(200, json=body)


def test_chat_sends_deterministic_options_and_no_streaming():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return _reply({"content": "ok"})

    _client(handler).chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])

    body = seen["body"]
    assert seen["url"] == "http://llm.test/api/chat"
    assert body["model"] == "m"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["options"]["temperature"] == 0.0
    assert body["options"]["seed"] == 42
    assert body["tools"] == [{"type": "function"}]
    assert "format" not in body  # only sent when a response format is requested


def test_response_format_and_context_size_are_forwarded():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _reply({"content": "{}"})

    schema = {"type": "object", "properties": {}}
    _client(handler).chat([], response_format=schema, num_ctx=8192)
    assert seen["body"]["format"] == schema
    assert seen["body"]["options"]["num_ctx"] == 8192


def test_native_tool_calls_are_parsed():
    def handler(request: httpx.Request) -> httpx.Response:
        call = {"function": {"name": "get_stock_history", "arguments": {"ticker": "ASELS"}}}
        return _reply({"content": "", "tool_calls": [call]})

    result = _client(handler).chat([])
    assert result.tool_calls == (ToolCall("get_stock_history", {"ticker": "ASELS"}),)
    assert result.content == ""


def test_tool_call_arguments_given_as_json_string_are_decoded():
    message = {
        "content": "",
        "tool_calls": [{"function": {"name": "t", "arguments": '{"a": 1}'}}],
    }
    assert parse_tool_calls(message) == (ToolCall("t", {"a": 1}),)


@pytest.mark.parametrize(
    "content",
    [
        '<tool_call>\n{"name": "run_backtest", "arguments": {"strategy": "A_TECHNICAL"}}\n</tool_call>',
        'Sure.\n```json\n{"name": "run_backtest", "arguments": {"strategy": "A_TECHNICAL"}}\n```',
        '{"name": "run_backtest", "arguments": {"strategy": "A_TECHNICAL"}}',
        '{"name": "run_backtest", "parameters": {"strategy": "A_TECHNICAL"}}',
    ],
)
def test_tool_call_written_as_text_is_recovered(content):
    assert parse_tool_calls({"content": content}) == (
        ToolCall("run_backtest", {"strategy": "A_TECHNICAL"}),
    )


def test_plain_text_and_ordinary_json_are_not_tool_calls():
    assert parse_tool_calls({"content": "The system is educational."}) == ()
    assert parse_tool_calls({"content": '{"answer": 42}'}) == ()


def test_token_counts_and_speed_are_converted_from_nanoseconds():
    def handler(request: httpx.Request) -> httpx.Response:
        return _reply(
            {"content": "x"},
            prompt_eval_count=120,
            eval_count=100,
            eval_duration=2_000_000_000,
            total_duration=3_500_000_000,
        )

    r = _client(handler).chat([])
    assert (r.prompt_tokens, r.completion_tokens) == (120, 100)
    assert r.total_duration_s == pytest.approx(3.5)
    assert r.eval_tokens_per_s == pytest.approx(50.0)


def test_missing_metrics_do_not_crash():
    r = _client(lambda request: _reply({"content": "x"})).chat([])
    assert (r.prompt_tokens, r.completion_tokens, r.eval_tokens_per_s) == (0, 0, None)


def test_connection_error_raises_llm_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(LLMUnavailableError, match="cannot reach"):
        _client(handler).chat([])


def test_http_error_raises_llm_unavailable_with_status_and_no_address():
    client = OllamaClient(
        "http://secret-host.test",
        "m",
        transport=httpx.MockTransport(lambda request: httpx.Response(403, text="forbidden")),
    )
    with pytest.raises(LLMUnavailableError) as excinfo:
        client.chat([])
    assert "403" in str(excinfo.value)
    assert "secret-host" not in str(excinfo.value)  # endpoint address never leaks into logs


def test_list_models_returns_tag_names():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "a:1b"}, {"name": "b:2b"}]})

    assert _client(handler).list_models() == ["a:1b", "b:2b"]


def test_http_library_logging_does_not_reveal_the_endpoint(caplog):
    """httpx logs every request URL at INFO; that would leak a private server address."""
    import logging

    client = OllamaClient(
        "http://secret-host.test",
        "m",
        transport=httpx.MockTransport(lambda request: _reply({"content": "x"})),
    )
    logging.getLogger("httpx").setLevel(logging.INFO)  # as a host application might do
    with caplog.at_level(logging.INFO):
        client.chat([])
        client.list_models()
    assert "secret-host" not in caplog.text


# --- the OpenAI-compatible route (a gateway that passes only /v1/chat/completions) -------
def _compat_client(handler) -> OllamaClient:
    return OllamaClient(
        "http://llm.test", "m", api="openai", transport=httpx.MockTransport(handler)
    )


def _compat_reply(message: dict, usage: dict | None = None) -> httpx.Response:
    body = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "model": "m",
        "choices": [{"index": 0, "message": {"role": "assistant", **message}}],
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def test_compat_route_sends_the_same_deterministic_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return _compat_reply({"content": "ok"})

    tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    schema = {"type": "object", "properties": {}}
    _compat_client(handler).chat(
        [{"role": "user", "content": "hi"}], tools=tools, response_format=schema
    )

    body = seen["body"]
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert body["model"] == "m"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["stream"] is False
    assert body["reasoning_effort"] == "none"  # Ollama's think: false on this route
    assert (body["temperature"], body["seed"]) == (0.0, 42)
    assert body["tools"] == tools
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "response", "schema": schema},
    }


def test_compat_route_without_format_or_tools_sends_neither():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _compat_reply({"content": "ok"})

    _compat_client(handler).chat([], think=True)
    assert "tools" not in seen["body"]
    assert "response_format" not in seen["body"]
    assert "reasoning_effort" not in seen["body"]  # thinking left at the model's default


def test_compat_route_drops_the_context_size():
    """The route has no context-size field: the model's own context applies, and a caller
    that sets one (the slice does) still works."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _compat_reply({"content": "x"})

    assert _compat_client(handler).chat([], num_ctx=8192).content == "x"
    assert "num_ctx" not in json.dumps(seen["body"])
    assert "options" not in seen["body"]


def test_compat_route_translates_tool_history_to_openai_shape():
    """Native history (dict arguments, no ids, ``tool_name``) becomes OpenAI history: each
    assistant call gets an id, ``type`` and string arguments; each tool result is paired with
    its call's id, by name when the message names its tool, else in order."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _compat_reply({"content": "done"})

    history = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "a", "arguments": {"ticker": "ASELS"}}},
                {"function": {"name": "b", "arguments": {"n": 1}}},
            ],
        },
        {"role": "tool", "tool_name": "b", "content": "out-b"},
        {"role": "tool", "tool_name": "a", "content": "out-a"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "a", "arguments": {"ticker": "THYAO"}}}],
        },
        {"role": "tool", "content": "out-a2"},  # experiment B: no tool name
    ]
    _compat_client(handler).chat(history)
    sent = seen["body"]["messages"]

    assert sent[:2] == history[:2]
    first = sent[2]["tool_calls"]
    assert [c["type"] for c in first] == ["function", "function"]
    assert [c["function"]["name"] for c in first] == ["a", "b"]
    assert [json.loads(c["function"]["arguments"]) for c in first] == [
        {"ticker": "ASELS"},
        {"n": 1},
    ]
    assert all(isinstance(c["function"]["arguments"], str) for c in first)
    ids = [c["id"] for c in first]
    assert len(set(ids)) == 2
    assert sent[3] == {"role": "tool", "tool_call_id": ids[1], "content": "out-b"}
    assert sent[4] == {"role": "tool", "tool_call_id": ids[0], "content": "out-a"}
    second = sent[5]["tool_calls"][0]
    assert second["id"] not in ids
    assert sent[6] == {"role": "tool", "tool_call_id": second["id"], "content": "out-a2"}
    assert history[2]["tool_calls"][0]["function"]["arguments"] == {"ticker": "ASELS"}  # unchanged


def test_compat_route_keeps_ids_and_string_arguments_it_is_given():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _compat_reply({"content": "x"})

    call = {"id": "call_x", "type": "function", "function": {"name": "a", "arguments": "{}"}}
    history = [
        {"role": "assistant", "content": "", "tool_calls": [call]},
        {"role": "tool", "tool_call_id": "call_x", "content": "o"},
    ]
    _compat_client(handler).chat(history)
    assert seen["body"]["messages"] == history


def test_compat_route_tool_calls_and_token_counts_are_read():
    def handler(request: httpx.Request) -> httpx.Response:
        call = {
            "id": "call_1",
            "index": 0,
            "type": "function",
            "function": {"name": "get_stock_history", "arguments": '{"ticker":"ASELS"}'},
        }
        return _compat_reply(
            {"content": "", "tool_calls": [call]},
            usage={"prompt_tokens": 300, "completion_tokens": 40, "total_tokens": 340},
        )

    result = _compat_client(handler).chat([])
    assert result.tool_calls == (ToolCall("get_stock_history", {"ticker": "ASELS"}),)
    assert (result.prompt_tokens, result.completion_tokens) == (300, 40)
    assert result.eval_tokens_per_s is None  # the route reports no generation time
    assert result.total_duration_s >= 0.0
    assert result.malformed_tool_call is False


def test_compat_route_text_tool_call_is_still_recovered():
    content = '<tool_call>{"name": "get_stock_history", "arguments": {"ticker": "ASELS"}}'
    result = _compat_client(lambda request: _compat_reply({"content": content})).chat([])
    assert result.tool_calls == (ToolCall("get_stock_history", {"ticker": "ASELS"}),)


def test_compat_route_errors_name_no_address():
    client = OllamaClient(
        "http://secret-host.test",
        "m",
        api="openai",
        transport=httpx.MockTransport(lambda request: httpx.Response(404, text="secret-host")),
    )
    with pytest.raises(LLMUnavailableError) as excinfo:
        client.chat([])
    assert "404" in str(excinfo.value)
    assert "secret-host" not in str(excinfo.value)


def test_compat_route_without_choices_is_unavailable():
    client = _compat_client(lambda request: httpx.Response(200, json={"object": "error"}))
    with pytest.raises(LLMUnavailableError, match="no choices"):
        client.chat([])


@pytest.mark.parametrize("body", [[], ["x"], {"choices": ["x"]}, {"choices": [{"message": "x"}]}])
def test_compat_route_with_an_unexpected_body_shape_is_unavailable(body):
    client = _compat_client(lambda request: httpx.Response(200, json=body))
    with pytest.raises(LLMUnavailableError, match="unexpected"):
        client.chat([])


@pytest.mark.parametrize("body", [[], "text", {"message": "x"}])
def test_native_route_with_an_unexpected_body_shape_is_unavailable(body):
    client = OllamaClient(
        "http://llm.test",
        "m",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
    )
    with pytest.raises(LLMUnavailableError, match="unexpected"):
        client.chat([])


def test_unknown_api_is_refused():
    with pytest.raises(ValueError, match="api"):
        OllamaClient("http://llm.test", "m", api="grpc")
