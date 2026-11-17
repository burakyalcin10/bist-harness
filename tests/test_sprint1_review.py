"""Regression tests for the Sprint 1 whole-branch review (findings C2, I1-I11)."""

import asyncio
import io
import json

import httpx
import numpy as np
import pandas as pd
import pytest
from mcp import Client

from bist_harness.bakeoff.run import run_model
from bist_harness.bakeoff.score import score_case, summarize
from bist_harness.errors import LLMUnavailableError
from bist_harness.eval.number_check import (
    collect_numbers,
    extract_numbers,
    find_unsupported_dates,
    find_unsupported_numbers,
)
from bist_harness.llm.client import (
    ChatResult,
    OllamaClient,
    ToolCall,
    looks_like_tool_call,
    parse_tool_calls,
)
from bist_harness.mcp_server import server as srv
from bist_harness.slice import run_slice as rs
from bist_harness.tools.schemas import validate_tool_call


def _history() -> pd.DataFrame:
    rng = np.random.default_rng(4)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.025, 1200)))
    index = pd.date_range("2020-01-02", periods=1200, freq="B")
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1.0}, index=index
    )


@pytest.fixture(autouse=True)
def offline_history(monkeypatch):
    frame = _history()
    monkeypatch.setattr(srv, "load_history", lambda ticker: frame)
    return frame


class ScriptedClient:
    model = "scripted"

    def __init__(self, *steps):
        self.steps = list(steps)

    def chat(self, messages, tools=None, **kwargs):
        step = self.steps.pop(0)
        return step(messages) if callable(step) else step


def _result(content="", calls=(), malformed=False):
    return ChatResult(content, tuple(calls), 0, 0, 0.0, None, {}, malformed)


ARGS = {
    "ticker": "ASELS",
    "start": "2021-01-01",
    "end": "2023-12-31",
    "event_type": "BOLLINGER_LOWER_TOUCH",
    "forward_days": 5,
}
PERIOD = {"ticker": "ASELS", "start": "2021-01-01", "end": "2023-12-31"}
QUESTION = (
    "ASELS 2021-01-01 ile 2023-12-31 arasında alt Bollinger dokunuşlarından sonra 5 günlük getiri?"
)


# --- C2: a schema-invalid tool call must not crash the runner -------------------------


def test_mcp_validation_error_is_unwrapped_as_an_error_object():
    async def scenario():
        async with Client(srv.server) as client:
            bad = await client.call_tool("get_stock_history", {"ticker": "ASELS"})
            return srv.unwrap_tool_result(bad)

    out = asyncio.run(scenario())
    assert out["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "arguments",
    [
        {"ticker": "ASELS", "start": "2021-01-01"},  # missing end
        {**ARGS, "forward_days": "five"},  # wrong type
        {**ARGS, "ticker": None},
    ],
)
def test_invalid_tool_call_is_reported_to_the_model_instead_of_crashing(arguments):
    client = ScriptedClient(
        _result(calls=[ToolCall("detect_reversal_events", arguments)]),
        _result("Araç çağrısı geçersizdi."),
    )
    out = rs.run_slice(QUESTION, client, server=srv.server)
    assert out["tool_outputs"][0]["error"]["code"] == "INVALID_ARGUMENT"
    assert out["verdict"] == "NUMBERS_OK"


# --- I9: arguments are validated against the tool schema ------------------------------


def test_valid_call_passes_schema_validation():
    assert validate_tool_call("detect_reversal_events", ARGS) is None


@pytest.mark.parametrize(
    "name,arguments,fragment",
    [
        ("place_order", {}, "unknown tool"),
        ("detect_reversal_events", {**ARGS, "window": 50}, "window"),
        ("detect_reversal_events", {"ticker": "ASELS", "end": "2023-12-31"}, "start"),
        ("detect_reversal_events", {**ARGS, "event_type": "MOON_PHASE"}, "event_type"),
        ("detect_reversal_events", {**ARGS, "forward_days": 7}, "forward_days"),
        ("detect_reversal_events", {**ARGS, "forward_days": "5"}, "forward_days"),
        ("detect_reversal_events", {**ARGS, "forward_days": True}, "forward_days"),
        ("calculate_indicators", {**PERIOD, "indicators": "RSI"}, "indicators"),
        ("get_stock_history", "ASELS", "object"),
    ],
)
def test_schema_violations_are_named(name, arguments, fragment):
    message = validate_tool_call(name, arguments)
    assert message and fragment in message


def test_extra_argument_is_rejected_before_the_tool_runs():
    client = ScriptedClient(
        _result(calls=[ToolCall("detect_reversal_events", {**ARGS, "window": 50})]),
        _result("Geçersiz argüman."),
    )
    out = rs.run_slice(QUESTION, client, server=srv.server)
    assert out["tool_outputs"][0]["error"]["code"] == "INVALID_ARGUMENT"
    assert "window" in out["tool_outputs"][0]["error"]["message"]


# --- I1: tool arguments chosen by the model are not an allow-list ---------------------


def test_number_from_a_rejected_tool_argument_is_still_unsupported():
    client = ScriptedClient(
        _result(calls=[ToolCall("detect_reversal_events", {**ARGS, "forward_days": 7})]),
        _result("Başarı oranı %7."),
    )
    out = rs.run_slice(QUESTION, client, server=srv.server)
    assert out["verdict"] == "UNSUPPORTED_NUMBERS"
    assert out["unsupported_numbers"] == [7.0]


# --- I2: only numeric fields of tool outputs support a number -------------------------


def test_numbers_inside_tool_output_strings_are_not_support():
    output = {"definition": "20-day mean minus 2 standard deviations", "first_date": "2024-01-02"}
    assert collect_numbers(output) == []
    assert find_unsupported_numbers("Getiri %20, 2 olay, 2024 adet.", [output]) == [
        20.0,
        2.0,
        2024.0,
    ]


def test_numbers_in_error_messages_are_not_support():
    output = {"error": {"code": "INVALID_ARGUMENT", "message": "must be one of [1, 3, 5, 10]"}}
    assert find_unsupported_numbers("Oran %10.", [output]) == [10.0]


# --- I3 / I4 / I5: the tokenizer must not skip or misread numbers ---------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("TL62.5", [62.5]),
        ("7x büyüme", [7.0]),
        ("_97.3_", [97.3]),
        ("rate,97.3%", [97.3]),
        ("olay.97", [97.0]),
        ("1e5 lot", [100000.0]),
        ("97th percentile", [97.0]),
        ("No.97", [97.0]),
        ("62.5puan", [62.5]),
        ("1.37TL", [1.37]),
        ("24,000 lot", [24000.0]),
        ("1.719 gün", [1719.0]),
        ("0.625 oran", [0.625]),
        ("62.5,99.9", [62.5, 99.9]),
        ("[62.5,99.9]", [62.5, 99.9]),
        ("1.5,2.5", [1.5, 2.5]),
        ("yarısı yani ½", [0.5]),
        ("–1.37%", [-1.37]),  # en dash
        ("‑1.37%", [-1.37]),  # non-breaking hyphen
        ("%-3,2", [-3.2]),
        ("5-10 gün", [5.0, 10.0]),  # a range, not a negative number
        ("2020–2024", [2020.0, 2024.0]),
        ("BIST 100 ve XU100 endeksi, kanıt E12, kimlik 64373cd5abca", []),
        ("17.05.2023 tarihinde", []),  # dates are checked separately
    ],
)
def test_tokenizer_reads_numbers_next_to_letters_and_symbols(text, expected):
    assert extract_numbers(text) == expected


def test_sign_flip_is_flagged():
    assert find_unsupported_numbers("Getiri –1.37% oldu.", [{"r": 1.37}]) == [-1.37]


def test_thousands_reading_cannot_be_laundered_through_a_small_number():
    assert find_unsupported_numbers("24,000 olay", [{"event_count": 24}]) == [24000.0]


def test_dates_in_the_answer_must_come_from_the_tools_or_the_question():
    outputs = [{"first_date": "2025-01-02", "last_date": "2026-10-30"}]
    question = "2025-01-01 ile 2026-10-31 arası?"
    answer = "2025-01-02 ile 2026-10-30 arasında; soru 2025-01-01 diyordu; zirve 17.05.2023 ve 2024-03-08."
    assert find_unsupported_dates(answer, outputs, question) == ["2023-05-17", "2024-03-08"]


def test_unsupported_date_fails_the_slice_verdict():
    client = ScriptedClient(
        _result(calls=[ToolCall("detect_reversal_events", ARGS)]),
        _result("En güçlü olay 2022-02-30 tarihindeydi."),
    )
    out = rs.run_slice(QUESTION, client, server=srv.server)
    assert out["verdict"] == "UNSUPPORTED_NUMBERS"
    assert out["unsupported_dates"] == ["2022-02-30"]


# --- I6: tool calls written in other shapes, and malformed attempts -------------------

CALL = ToolCall("run_backtest", {"strategy": "A_TECHNICAL"})
OBJ = '{"name": "run_backtest", "arguments": {"strategy": "A_TECHNICAL"}}'


@pytest.mark.parametrize(
    "content",
    [
        f"I will call the tool now: {OBJ} Done.",
        f"[{OBJ}]",
        f"[TOOL_CALLS] [{OBJ}]",
        f"<|python_tag|>{OBJ}",
        f"<tool_call>{OBJ}",  # tag never closed
    ],
)
def test_more_text_shapes_of_a_tool_call_are_recovered(content):
    assert parse_tool_calls({"content": content}) == (CALL,)


def test_two_calls_in_one_message_are_both_recovered():
    other = (
        '{"name": "get_macro_context", "arguments": {"start": "2026-01-01", "end": "2026-06-30"}}'
    )
    calls = parse_tool_calls({"content": f"{OBJ}\n{other}"})
    assert [c.name for c in calls] == ["run_backtest", "get_macro_context"]


def test_native_call_without_arguments_gets_an_empty_object():
    message = {"content": "", "tool_calls": [{"function": {"name": "get_macro_context"}}]}
    assert parse_tool_calls(message) == (ToolCall("get_macro_context", {}),)


def test_unparseable_attempt_is_detected_as_malformed():
    broken = {
        "content": '<tool_call>{"name": "run_backtest", "arguments": {"strategy": </tool_call>'
    }
    assert parse_tool_calls(broken) == ()
    assert looks_like_tool_call(broken) is True
    assert looks_like_tool_call({"content": "The system is educational."}) is False
    assert looks_like_tool_call({"content": OBJ}) is False  # parsed fine, so not malformed


def test_chat_result_marks_a_malformed_tool_call():
    def handler(request: httpx.Request) -> httpx.Response:
        message = {"role": "assistant", "content": '<tool_call>{"name": "x", "arguments": {'}
        return httpx.Response(200, json={"message": message})

    client = OllamaClient("http://llm.test", "m", transport=httpx.MockTransport(handler))
    result = client.chat([])
    assert result.tool_calls == ()
    assert result.malformed_tool_call is True


def test_malformed_call_does_not_pass_a_no_tool_case():
    assert score_case({"expect": "no_tool"}, [], malformed=True).no_tool_ok is False
    assert score_case({"expect": "no_tool"}, [], malformed=False).no_tool_ok is True


def test_summary_counts_malformed_calls():
    scores = [
        score_case({"expect": "no_tool"}, [], malformed=True),
        score_case({"tool": "get_macro_context", "args": {}}, [], malformed=True),
        score_case({"expect": "no_tool"}, []),
    ]
    summary = summarize(scores)
    assert summary["malformed_calls"] == 2
    assert summary["no_tool_ok_pct"] == 50.0


def test_failed_request_counts_as_a_failure_even_for_a_no_tool_case():
    cases = [
        {"id": "a", "lang": "en", "question": "q1", "tool": "get_macro_context", "args": {}},
        {"id": "trap", "lang": "en", "question": "q2", "expect": "no_tool"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["messages"][-1]["content"] == "q2":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "x"}})

    client = OllamaClient("http://llm.test", "m", transport=httpx.MockTransport(handler))
    row = run_model(client, cases)
    assert row["summary"]["no_tool_ok_pct"] == 0.0
    assert "1 request(s) failed" in row["notes"]


def test_malformed_tool_call_in_the_slice_is_not_treated_as_an_answer():
    client = ScriptedClient(_result('<tool_call>{"name": "x", "arguments": {', malformed=True))
    out = rs.run_slice(QUESTION, client, server=srv.server)
    assert out["verdict"] == "INVALID_TOOL_CALL"


# --- I7: nothing from the endpoint's error body or address reaches messages -----------


def test_http_error_body_is_not_copied_into_the_error_message():
    client = OllamaClient(
        "http://llm.test",
        "m",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(502, text="dial tcp secret-host.test:11434: refused")
        ),
    )
    with pytest.raises(LLMUnavailableError) as excinfo:
        client.chat([])
    assert "502" in str(excinfo.value)
    assert "secret-host" not in str(excinfo.value)


def test_non_json_success_response_is_an_unavailable_endpoint():
    client = OllamaClient(
        "http://llm.test",
        "m",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="<html>proxy</html>")
        ),
    )
    with pytest.raises(LLMUnavailableError, match="non-JSON"):
        client.chat([])


def test_invalid_endpoint_address_is_an_unavailable_endpoint_without_the_address():
    with pytest.raises(LLMUnavailableError) as excinfo:
        OllamaClient("http://[secret-host", "m").chat([])
    assert "secret-host" not in str(excinfo.value)


# --- I8: outputs say which dates the data actually covers -----------------------------


def test_outputs_report_data_coverage_and_warn_when_the_request_exceeds_it(offline_history):
    first, last = str(offline_history.index[0].date()), str(offline_history.index[-1].date())
    inside = srv.detect_reversal_events("ASELS", "2021-01-01", "2023-12-31")
    assert (inside["data_first_date"], inside["data_last_date"]) == (first, last)
    assert inside["coverage_warning"] is None

    early = srv.detect_reversal_events("ASELS", "2019-06-01", "2023-12-31")
    assert first in early["coverage_warning"]

    late = srv.get_stock_history("ASELS", "2024-01-01", "2024-12-31")  # data ends 2024-08
    assert last in late["coverage_warning"]
    assert late["last_date"] == last


# --- I10: the runner tells the model the real date ------------------------------------


def test_slice_prompt_uses_the_current_date():
    from datetime import date

    assert f"Today is {date.today().isoformat()}." in rs.system_prompt()


# --- I11: printing Turkish text on a legacy Windows console must not crash ------------


def test_report_printing_survives_a_legacy_console_encoding():
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    rs.safe_print("Fiyat 345.50 ₺ — başarı oranı %61,54 → olumlu", stream=stream)
    stream.flush()
    assert b"345.50" in stream.buffer.getvalue()


def test_log_is_written_before_anything_is_printed(tmp_path, monkeypatch):
    out = {
        "question": "q",
        "model": "m",
        "tool_calls": [],
        "tool_outputs": [],
        "answer": "₺",
        "unsupported_numbers": [],
        "unsupported_dates": [],
        "verdict": "NUMBERS_OK",
    }

    def broken_print(*args, **kwargs):
        raise RuntimeError("console died")

    monkeypatch.setattr(rs, "safe_print", broken_print)
    with pytest.raises(RuntimeError):
        rs.report(out, runs_dir=tmp_path)
    logs = list(tmp_path.glob("slice-*.json"))
    assert len(logs) == 1
    assert json.loads(logs[0].read_text(encoding="utf-8"))["answer"] == "₺"


# --- Review Focus 3 gap: a download whose prices are all missing ----------------------


def test_download_with_only_missing_prices_raises_data_unavailable(tmp_path):
    from bist_harness.data.market import load_stock_data
    from bist_harness.errors import DataUnavailableError

    index = pd.date_range("2024-01-02", periods=3, freq="B")
    empty = pd.DataFrame(
        {c: [np.nan] * 3 for c in ["Open", "High", "Low", "Close", "Volume"]}, index=index
    )
    with pytest.raises(DataUnavailableError):
        load_stock_data("ASELS", "2024-01-01", cache_dir=tmp_path, downloader=lambda *a: empty)
