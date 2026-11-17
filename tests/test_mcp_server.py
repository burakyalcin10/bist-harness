"""MCP tools of the thin slice: outputs, error objects, determinism and the MCP surface."""

import asyncio
import sys

import numpy as np
import pandas as pd
import pytest
from mcp import Client, StdioServerParameters

from bist_harness.mcp_server import server as srv
from bist_harness.tools.schemas import TOOL_SCHEMAS

IMPLEMENTED = {"get_stock_history", "detect_reversal_events"}


def _history(days: int = 1200, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.025, days)))
    index = pd.date_range("2020-01-02", periods=days, freq="B")
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1.0}, index=index
    )


@pytest.fixture(autouse=True)
def offline_history(monkeypatch):
    """Tools read a synthetic history; no test touches the network."""
    frame = _history()
    monkeypatch.setattr(srv, "load_history", lambda ticker: frame)
    return frame


def test_stock_history_summary_fields_and_values(offline_history):
    out = srv.get_stock_history("asels.is", "2021-01-01", "2021-12-31")
    window = offline_history.loc["2021-01-01":"2021-12-31", "Close"]
    assert out["ticker"] == "ASELS"
    assert (out["start"], out["end"]) == ("2021-01-01", "2021-12-31")
    assert out["rows"] == len(window)
    assert out["first_date"] == str(window.index[0].date())
    assert out["last_date"] == str(window.index[-1].date())
    assert out["first_close"] == round(float(window.iloc[0]), 2)
    assert out["last_close"] == round(float(window.iloc[-1]), 2)
    assert out["period_return_pct"] == round(float(window.iloc[-1] / window.iloc[0] - 1) * 100, 2)
    assert "yfinance" in out["data_source"]
    assert len(out["result_id"]) == 12


def test_reversal_events_summary_matches_the_tool_function(offline_history):
    from bist_harness.tools.reversal import bollinger_lower_touch_summary

    out = srv.detect_reversal_events("ASELS", "2021-01-01", "2023-12-31", forward_days=10)
    expected = bollinger_lower_touch_summary(
        offline_history.loc[:"2023-12-31"], forward_days=10, since="2021-01-01"
    )
    for key, value in expected.items():
        assert out[key] == value
    assert (out["ticker"], out["event_type"], out["forward_days"]) == (
        "ASELS",
        "BOLLINGER_LOWER_TOUCH",
        10,
    )
    assert out["definition"]
    assert len(out["result_id"]) == 12


def test_events_never_use_prices_after_the_requested_end(offline_history, monkeypatch):
    def analysis(output):
        # Coverage fields describe the snapshot itself, so they differ by design.
        skip = {"data_last_date", "coverage_warning", "result_id"}
        return {k: v for k, v in output.items() if k not in skip}

    out_full = srv.detect_reversal_events("ASELS", "2020-06-01", "2022-06-30")
    truncated = offline_history.loc[:"2022-06-30"]
    monkeypatch.setattr(srv, "load_history", lambda ticker: truncated)
    out_cut = srv.detect_reversal_events("ASELS", "2020-06-01", "2022-06-30")
    assert analysis(out_cut) == analysis(out_full)
    assert out_full["event_count"] > 0


def test_same_input_gives_same_result_id_and_different_input_differs():
    a = srv.get_stock_history("ASELS", "2021-01-01", "2021-12-31")
    b = srv.get_stock_history("ASELS", "2021-01-01", "2021-12-31")
    c = srv.get_stock_history("ASELS", "2021-01-01", "2022-12-31")
    assert a == b
    assert a["result_id"] != c["result_id"]


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"ticker": "GARAN", "start": "2021-01-01", "end": "2021-12-31"}, "UNKNOWN_TICKER"),
        ({"ticker": "ASELS", "start": "2021-12-31", "end": "2021-01-01"}, "INVALID_DATE_RANGE"),
        ({"ticker": "ASELS", "start": "01.01.2021", "end": "2021-12-31"}, "INVALID_DATE"),
        ({"ticker": "ASELS", "start": "2021-01-01", "end": "2999-01-01"}, "FUTURE_DATE"),
        ({"ticker": "ASELS", "start": "2019-01-01", "end": "2019-06-30"}, "DATA_UNAVAILABLE"),
    ],
)
def test_bad_input_returns_an_error_object_instead_of_raising(kwargs, code):
    for tool in (srv.get_stock_history, srv.detect_reversal_events):
        out = tool(**kwargs)
        assert set(out) == {"error"}
        assert out["error"]["code"] == code
        assert out["error"]["message"]


def test_event_family_not_built_yet_is_reported_as_not_implemented():
    out = srv.detect_reversal_events("ASELS", "2021-01-01", "2021-12-31", "SUPERTREND_FLIP")
    assert out["error"]["code"] == "NOT_IMPLEMENTED"


def test_unknown_event_type_is_rejected():
    out = srv.detect_reversal_events("ASELS", "2021-01-01", "2021-12-31", "MOON_PHASE")
    assert out["error"]["code"] == "INVALID_ARGUMENT"


def test_data_source_failure_is_an_error_object(monkeypatch):
    from bist_harness.errors import DataUnavailableError

    def boom(ticker):
        raise DataUnavailableError("no market data for ASELS from 2020-01-01")

    monkeypatch.setattr(srv, "load_history", boom)
    out = srv.get_stock_history("ASELS", "2021-01-01", "2021-12-31")
    assert out["error"]["code"] == "DATA_UNAVAILABLE"


def test_mcp_surface_lists_the_tools_with_schema_parameter_names():
    async def scenario():
        async with Client(srv.server) as client:
            listed = await client.list_tools()
            result = await client.call_tool(
                "get_stock_history",
                {"ticker": "ASELS", "start": "2021-01-01", "end": "2021-12-31"},
            )
            return listed.tools, srv.unwrap_tool_result(result)

    tools, output = asyncio.run(scenario())
    assert {t.name for t in tools} == IMPLEMENTED
    for tool in tools:
        ours = TOOL_SCHEMAS[tool.name]
        assert set(tool.input_schema["properties"]) == set(ours["parameters"]["properties"])
        assert tool.description == ours["description"]
    assert output == srv.get_stock_history("ASELS", "2021-01-01", "2021-12-31")


def test_server_starts_as_a_subprocess_over_stdio():
    async def scenario():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "bist_harness.mcp_server.server"]
        )
        async with Client(params) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert asyncio.run(scenario()) == IMPLEMENTED
