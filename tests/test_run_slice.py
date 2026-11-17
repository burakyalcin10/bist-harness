"""The thin end-to-end slice: question -> tool call over MCP -> answer -> number check."""

import numpy as np
import pandas as pd
import pytest

from bist_harness.llm.client import ChatResult, ToolCall
from bist_harness.mcp_server import server as srv
from bist_harness.slice.run_slice import run_slice


def _history() -> pd.DataFrame:
    rng = np.random.default_rng(4)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.025, 1200)))
    index = pd.date_range("2020-01-02", periods=1200, freq="B")
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1.0}, index=index
    )


@pytest.fixture(autouse=True)
def offline_history(monkeypatch):
    monkeypatch.setattr(srv, "load_history", lambda ticker: _history())


class ScriptedClient:
    """Stands in for OllamaClient: returns prepared results and records what it was sent."""

    model = "scripted"

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []

    def chat(self, messages, tools=None, **kwargs):
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tools})
        step = self.steps.pop(0)
        if callable(step):
            step = step(messages)
        return step


def _result(content="", calls=()):
    return ChatResult(content, tuple(calls), 0, 0, 0.0, None, {})


ARGS = {"ticker": "ASELS", "start": "2021-01-01", "end": "2023-12-31", "forward_days": 5}
QUESTION = "ASELS'te 2021-01-01 ile 2023-12-31 arasında alt Bollinger dokunuşlarından sonra 5 günlük getiri nasıl?"


def _faithful_answer(messages):
    import json

    out = json.loads(messages[-1]["content"])
    return _result(
        f"{out['event_count']} olayın {out['successful_events']} tanesinde getiri pozitif; "
        f"başarı oranı %{out['success_rate_pct']}, ortalama getiri %{out['average_forward_return_pct']}."
    )


def test_tool_call_then_faithful_answer_is_numbers_ok():
    client = ScriptedClient(
        _result(calls=[ToolCall("detect_reversal_events", ARGS)]), _faithful_answer
    )
    out = run_slice(QUESTION, client, server=srv.server)

    assert out["verdict"] == "NUMBERS_OK"
    assert out["unsupported_numbers"] == []
    assert out["tool_calls"] == [{"name": "detect_reversal_events", "arguments": ARGS}]
    assert out["tool_outputs"][0] == srv.detect_reversal_events(**ARGS)
    assert out["answer"].startswith(str(out["tool_outputs"][0]["event_count"]))


def test_model_sees_only_implemented_tools_and_then_the_tool_result():
    client = ScriptedClient(
        _result(calls=[ToolCall("detect_reversal_events", ARGS)]), _faithful_answer
    )
    run_slice(QUESTION, client, server=srv.server)

    first, second = client.requests
    assert {t["function"]["name"] for t in first["tools"]} == {
        "get_stock_history",
        "detect_reversal_events",
    }
    assert [m["role"] for m in first["messages"]] == ["system", "user"]
    assert [m["role"] for m in second["messages"]] == ["system", "user", "assistant", "tool"]
    assert second["messages"][2]["tool_calls"][0]["function"]["name"] == "detect_reversal_events"


def test_invented_number_in_the_answer_is_flagged():
    client = ScriptedClient(
        _result(calls=[ToolCall("detect_reversal_events", ARGS)]),
        _result("Başarı oranı %97.31 ve bu çok güçlü bir sinyal."),
    )
    out = run_slice(QUESTION, client, server=srv.server)
    assert out["verdict"] == "UNSUPPORTED_NUMBERS"
    assert out["unsupported_numbers"] == [97.31]


def test_numbers_repeated_from_the_question_are_allowed():
    client = ScriptedClient(_result("5 günlük getiri için önce veriye bakmam gerekir."))
    out = run_slice(QUESTION, client, server=srv.server)
    assert out["verdict"] == "NUMBERS_OK"
    assert out["tool_calls"] == []


def test_call_to_a_tool_outside_the_slice_is_refused_and_logged():
    client = ScriptedClient(
        _result(calls=[ToolCall("run_backtest", {"strategy": "A_TECHNICAL"})]),
        _result("Bu araç şu an kullanılamıyor."),
    )
    out = run_slice(QUESTION, client, server=srv.server)
    assert out["tool_outputs"][0]["error"]["code"] == "TOOL_NOT_ALLOWED"
    assert out["verdict"] == "NUMBERS_OK"


def test_model_that_never_answers_ends_as_no_answer():
    call = _result(calls=[ToolCall("detect_reversal_events", ARGS)])
    client = ScriptedClient(call, call, call)
    out = run_slice(QUESTION, client, server=srv.server, max_turns=3)
    assert out["verdict"] == "NO_ANSWER"
    assert len(out["tool_calls"]) == 3
