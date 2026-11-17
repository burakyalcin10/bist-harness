"""The bake-off runner: per-model rows, unreachable endpoints, and the rendered table."""

import json

import httpx

from bist_harness.bakeoff.run import endpoint_label, render_markdown, run_model
from bist_harness.llm.client import OllamaClient

CASES = [
    {
        "id": "rev-01",
        "lang": "en",
        "question": "q1",
        "tool": "get_stock_history",
        "args": {"ticker": "ASELS"},
    },
    {"id": "trap-01", "lang": "en", "question": "q2", "expect": "no_tool"},
]


def _client(handler) -> OllamaClient:
    return OllamaClient("http://private-host.test", "m:1b", transport=httpx.MockTransport(handler))


def test_reachable_model_is_scored_per_case():
    def handler(request: httpx.Request) -> httpx.Response:
        question = json.loads(request.content)["messages"][-1]["content"]
        message = {"role": "assistant", "content": "I cannot give advice."}
        if question == "q1":
            call = {"function": {"name": "get_stock_history", "arguments": {"ticker": "asels"}}}
            message = {"role": "assistant", "content": "", "tool_calls": [call]}
        return httpx.Response(
            200, json={"message": message, "eval_count": 10, "eval_duration": 1_000_000_000}
        )

    row = run_model(_client(handler), CASES)
    assert row["model"] == "m:1b"
    assert row["reachable"] is True
    assert row["summary"]["args_ok_pct"] == 100.0
    assert row["summary"]["no_tool_ok_pct"] == 100.0
    assert row["tokens_per_s"] == 10.0
    assert [d["id"] for d in row["details"]] == ["rev-01", "trap-01"]


def test_request_carries_system_prompt_all_tools_and_context_size():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "x"}})

    run_model(_client(handler), CASES[:1])
    body = seen["body"]
    assert body["messages"][0]["role"] == "system"
    assert "Study universe" in body["messages"][0]["content"]
    assert len(body["tools"]) == 15
    assert body["options"]["num_ctx"] == 8192


def test_unreachable_model_is_reported_and_not_retried_for_every_case():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("down", request=request)

    row = run_model(_client(handler), CASES)
    assert row["reachable"] is False
    assert row["details"] == []
    assert len(calls) == 1
    assert "cannot reach" in row["notes"]


def test_markdown_table_names_models_but_never_the_endpoint_address():
    rows = [
        {
            "model": "m:1b",
            "reachable": True,
            "summary": {
                "tool_ok_pct": 80.0,
                "args_ok_pct": 60.0,
                "no_tool_ok_pct": 100.0,
                "tool_cases": 25,
                "no_tool_cases": 5,
            },
            "median_latency_s": 1.23,
            "tokens_per_s": 45.6,
            "notes": "",
            "details": [],
        },
        {
            "model": "n:2b",
            "reachable": False,
            "summary": None,
            "median_latency_s": None,
            "tokens_per_s": None,
            "notes": "cannot reach the LLM endpoint (ConnectError)",
            "details": [],
        },
    ]
    text = render_markdown(rows, endpoint="private remote endpoint", generated="2026-11-17 04:00")
    assert "| m:1b | yes | 80.0 | 60.0 | 100.0 | 1.23 | 45.6 |" in text
    assert "| n:2b | no |" in text
    assert "private-host" not in text


def test_endpoint_label_hides_private_addresses():
    assert endpoint_label("http://127.0.0.1:11434") == "local Ollama on this machine"
    assert endpoint_label("http://localhost:11434") == "local Ollama on this machine"
    assert endpoint_label("https://anything.example") == "private remote endpoint"
