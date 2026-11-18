"""The OpenAI-compatible route end to end: every experiment (A-E) and the slice, through
``OllamaClient(api="openai")`` with the HTTP layer mocked by a strict stand-in for Ollama's
OpenAI layer. It refuses what that layer cannot decode (dict tool arguments, calls without
an id or type, tool results without a matching ``tool_call_id``, native-only fields) with
HTTP 400, the way the real layer fails a request it cannot read.
"""

import json

import httpx
import pytest

from bist_harness.eval import run_eval
from bist_harness.llm.client import ChatResult, OllamaClient, ToolCall
from bist_harness.mcp_server import server as srv
from bist_harness.slice.run_slice import run_slice

from . import test_run_eval as te
from . import test_run_slice as ts

ALLOWED_KEYS = {
    "model",
    "messages",
    "stream",
    "temperature",
    "seed",
    "reasoning_effort",
    "tools",
    "response_format",
}


def check_openai_request(body: dict) -> str | None:
    """Why Ollama's OpenAI layer would refuse ``body``, or None."""
    extra = set(body) - ALLOWED_KEYS
    if extra:
        return f"unexpected fields {sorted(extra)}"
    open_ids: list[str] = []
    for message in body["messages"]:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            for call in message["tool_calls"]:
                function = call.get("function") or {}
                if not isinstance(call.get("id"), str) or call.get("type") != "function":
                    return "tool call without id or type"
                if not isinstance(function.get("arguments"), str):
                    return "tool call arguments are not a JSON string"
                json.loads(function["arguments"])
                open_ids.append(call["id"])
        elif message.get("role") == "tool":
            if "tool_name" in message:
                return "native field tool_name"
            if message.get("tool_call_id") not in open_ids:
                return "tool result without a matching tool_call_id"
            open_ids.remove(message["tool_call_id"])
    return None


def _openai_reply(result: ChatResult) -> httpx.Response:
    message: dict = {"role": "assistant", "content": result.content}
    if result.tool_calls:
        message["tool_calls"] = [
            {
                "id": f"call_{n}",
                "index": n,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
            }
            for n, c in enumerate(result.tool_calls)
        ]
    body = {
        "object": "chat.completion",
        "choices": [{"index": 0, "message": message}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    return httpx.Response(200, json=body)


class StrictOpenAILayer:
    """Answers through ``model`` (any object with the client's ``chat``) after checking the
    request the way the OpenAI layer decodes it."""

    def __init__(self, model):
        self.model = model
        self.bodies: list[dict] = []
        self.refused: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        self.bodies.append(body)
        problem = check_openai_request(body)
        if problem:
            self.refused.append(problem)
            return httpx.Response(400, json={"error": {"message": problem}})
        schema = (body.get("response_format") or {}).get("json_schema", {}).get("schema")
        kwargs = {"response_format": schema} if schema is not None else {}
        return _openai_reply(self.model.chat(body["messages"], tools=body.get("tools"), **kwargs))


def _client(layer) -> OllamaClient:
    return OllamaClient(
        "http://llm.test", "fake-model", api="openai", transport=httpx.MockTransport(layer)
    )


def _strip_ids(value):
    if isinstance(value, dict):
        return {k: _strip_ids(v) for k, v in value.items() if k != "analysis_id"}
    if isinstance(value, list):
        return [_strip_ids(v) for v in value]
    return value


def _shape(records):
    return {
        (r["experiment"], r["question_id"], r["repeat"]): (
            r["outcome"],
            r["error"],
            [(c["tool"], _strip_ids(c["arguments"]), c["allowed"]) for c in r["tool_calls"]],
        )
        for r in records
    }


def _records(out):
    return [
        json.loads(line)
        for line in (out / "records.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def _run(chosen, client, out):
    run_eval.run_eval(
        chosen,
        client,
        experiments=run_eval.EXPERIMENTS,
        call_tool=te.GoldenTools(),
        today=te.TODAY,
        repeats=1,
        out_dir=out,
        replay_options={"verify": lambda snapshot_id: []},
    )
    return _records(out)


@pytest.fixture(autouse=True)
def private_store(monkeypatch, tmp_path):
    from bist_harness.harness import session

    monkeypatch.setattr(session, "_store_path", lambda: tmp_path / "default-store.sqlite")


@pytest.fixture(autouse=True)
def offline_history(monkeypatch):
    monkeypatch.setattr(srv, "load_history", lambda ticker: ts._history())


@pytest.fixture(scope="module")
def chosen():
    by_id = {q["id"]: q for q in te.qs.load_questions()}
    return [by_id[i] for i in te.IDS]


def test_every_experiment_runs_the_same_through_the_openai_route(chosen, tmp_path):
    intents = {q["question"]: te.INTENTS[q["id"]] for q in chosen}
    direct = _run(chosen, te.RuleClient(intents), tmp_path / "direct")
    layer = StrictOpenAILayer(te.RuleClient(intents))
    routed = _run(chosen, _client(layer), tmp_path / "routed")

    assert layer.refused == []
    assert not any(r["outcome"] == "MODEL_UNAVAILABLE" for r in routed)
    assert _shape(routed) == _shape(direct)
    # Experiment B's tool rounds really went through the route as history.
    with_history = [
        b
        for b in layer.bodies
        if any(m.get("role") == "tool" for m in b["messages"])
        and any(m.get("tool_calls") for m in b["messages"])
    ]
    assert with_history


def test_the_strict_layer_refuses_native_history():
    """The stand-in is strict enough to catch the bug the translation fixes."""
    native = {
        "model": "m",
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "a", "arguments": {"x": 1}}}],
            },
            {"role": "tool", "content": "o"},
        ],
    }
    assert check_openai_request(native) is not None


def test_the_slice_runs_through_the_openai_route():
    scripted = ts.ScriptedClient(
        ts._result(calls=[ToolCall("detect_reversal_events", ts.ARGS)]), ts._faithful_answer
    )
    layer = StrictOpenAILayer(scripted)
    out = run_slice(ts.QUESTION, _client(layer), server=srv.server)

    assert layer.refused == []
    assert out["verdict"] == "NUMBERS_OK"
    assert out["tool_calls"] == [{"name": "detect_reversal_events", "arguments": ts.ARGS}]
    second = layer.bodies[1]["messages"]
    call_id = second[-2]["tool_calls"][0]["id"]
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == call_id
