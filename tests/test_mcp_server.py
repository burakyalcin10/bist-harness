"""MCP tools of the thin slice: outputs, error objects, determinism and the MCP surface."""

import asyncio
import sys

import pandas as pd
import pytest
from mcp import Client, StdioServerParameters

from bist_harness.mcp_server import server as srv
from bist_harness.tools.schemas import REVERSAL_EVENT_TYPES, TOOL_SCHEMAS

from .conftest import IMPLEMENTED_TOOLS as IMPLEMENTED
from .synth import ohlcv


def _history(days: int = 1200, seed: int = 4) -> pd.DataFrame:
    """Random-walk bars with real highs, lows and volumes."""
    return ohlcv(days, seed)


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


@pytest.mark.parametrize("event_type", REVERSAL_EVENT_TYPES)
@pytest.mark.parametrize("direction", ["BULLISH", "BEARISH"])
def test_every_event_family_runs_in_both_directions(event_type, direction, offline_history):
    from bist_harness.tools.events import detect_events

    out = srv.detect_reversal_events("ASELS", "2021-01-01", "2023-12-31", event_type, 5, direction)
    expected = detect_events(
        offline_history.loc[:"2023-12-31"], event_type, direction, since="2021-01-01"
    )
    for key, value in expected.items():
        assert out[key] == value
    assert out["event_type"] == event_type and out["direction"] == expected["direction"]
    assert out["definition"] and len(out["result_id"]) == 12


def test_invalid_direction_is_rejected():
    out = srv.detect_reversal_events(
        "ASELS", "2021-01-01", "2021-12-31", "SUPERTREND_FLIP", 5, "SIDEWAYS"
    )
    assert out["error"]["code"] == "INVALID_ARGUMENT"


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


def test_every_output_names_the_snapshot_and_the_result_id_depends_on_it(monkeypatch):
    a = srv.get_stock_history("ASELS", "2021-01-01", "2021-12-31")
    events = srv.detect_reversal_events("ASELS", "2021-01-01", "2021-12-31")
    assert a["snapshot_id"] == events["snapshot_id"] == "test-snapshot"
    monkeypatch.setattr(srv, "current_snapshot_id", lambda: "another-snapshot")
    b = srv.get_stock_history("ASELS", "2021-01-01", "2021-12-31")
    assert b["snapshot_id"] == "another-snapshot"
    assert a["result_id"] != b["result_id"]


def test_index_history_has_the_stock_history_fields_under_an_index_key():
    stock = srv.get_stock_history("ASELS", "2021-01-01", "2021-12-31")
    index = srv.get_index_history("xu100", "2021-01-01", "2021-12-31")
    assert index["index"] == "XU100"
    assert set(index) - {"index"} == set(stock) - {"ticker"}
    assert index["period_return_pct"] == stock["period_return_pct"]


def test_index_outside_the_snapshot_list_is_unknown():
    out = srv.get_index_history("XELKT", "2021-01-01", "2021-12-31")
    assert out["error"]["code"] == "UNKNOWN_INDEX"
    out = srv.get_stock_history("XU100", "2021-01-01", "2021-12-31")
    assert out["error"]["code"] == "UNKNOWN_TICKER"


def test_missing_snapshot_is_reported_with_the_build_command(monkeypatch, tmp_path):
    from bist_harness.data import snapshot

    monkeypatch.setattr(
        srv, "load_history", lambda symbol: snapshot.load_history(symbol, root=tmp_path)
    )
    out = srv.get_stock_history("ASELS", "2021-01-01", "2021-12-31")
    assert out["error"]["code"] == "DATA_UNAVAILABLE"
    assert "snapshot build" in out["error"]["message"]


def test_calculate_indicators_reports_the_last_day_on_or_before_end(offline_history):
    from bist_harness.tools.indicators import add_all_indicators, indicator_state

    out = srv.calculate_indicators("ASELS", "2021-01-01", "2022-06-30", ["RSI", "SUPERTREND"])
    window = add_all_indicators(offline_history.loc[:"2022-06-30"])
    expected = indicator_state(window, ["RSI", "SUPERTREND"])
    for key, value in expected.items():
        assert out[key] == value
    assert out["as_of"] == "2022-06-30"
    assert out["indicators"] == ["RSI", "SUPERTREND"]
    assert "sma_20" not in out and out["snapshot_id"] and len(out["result_id"]) == 12


def test_calculate_indicators_with_an_empty_list_returns_every_group():
    out = srv.calculate_indicators("ASELS", "2021-01-01", "2022-06-30", [])
    for key in (
        "sma_20",
        "ema_20",
        "kama",
        "rsi",
        "macd",
        "bb_upper",
        "atr",
        "supertrend_state",
        "ichimoku_state",
        "volume_regime",
    ):
        assert key in out
    assert len(out["indicators"]) == 10


def test_calculate_indicators_rejects_an_unknown_indicator():
    out = srv.calculate_indicators("ASELS", "2021-01-01", "2022-06-30", ["RSI", "MOON"])
    assert out["error"]["code"] == "INVALID_ARGUMENT"


def test_calculate_indicators_on_a_short_history_returns_none_values(monkeypatch, offline_history):
    monkeypatch.setattr(srv, "load_history", lambda symbol: offline_history.iloc[:15])
    out = srv.calculate_indicators("ASELS", "2020-01-01", "2020-03-31", [])
    assert out["sma_20"] is None and out["ichimoku_state"] is None and out["rsi"] is not None


def test_support_resistance_tool_reports_levels_of_the_period(offline_history):
    from bist_harness.tools.support_resistance import find_support_resistance

    out = srv.find_support_resistance("ASELS", "2021-01-01", "2022-06-30")
    window = offline_history.loc["2021-01-01":"2022-06-30"]
    assert out["levels"] == find_support_resistance(window)
    assert 0 < len(out["levels"]) <= 6
    assert out["tolerance"] == 0.015
    assert out["last_close"] == round(float(window["Close"].iloc[-1]), 2)
    supports = [lv["level"] for lv in out["levels"] if lv["kind"] == "support"]
    resistances = [lv["level"] for lv in out["levels"] if lv["kind"] == "resistance"]
    assert out["nearest_support"] == (max(supports) if supports else None)
    assert out["nearest_resistance"] == (min(resistances) if resistances else None)
    assert out["method"] and out["snapshot_id"] and len(out["result_id"]) == 12


def test_support_resistance_tolerance_must_be_a_small_positive_share():
    for bad in (0, -0.1, 0.5):
        out = srv.find_support_resistance("ASELS", "2021-01-01", "2022-06-30", bad)
        assert out["error"]["code"] == "INVALID_ARGUMENT"


@pytest.fixture
def sector_histories(monkeypatch):
    """A different random walk per symbol, so sector members have different returns."""
    frames: dict[str, pd.DataFrame] = {}

    def load(symbol):
        if symbol not in frames:
            frames[symbol] = _history(seed=sum(map(ord, symbol)))
        return frames[symbol]

    monkeypatch.setattr(srv, "load_history", load)
    return load


def test_sector_tool_ranks_the_peer_group_against_xu100(sector_histories):
    from bist_harness.data.peers import resolve_sector
    from bist_harness.tools.sector import rank_sector_relative_strength

    out = srv.rank_sector_relative_strength("Banking", 20, "2022-06-30")
    group = resolve_sector("Banking")
    expected = rank_sector_relative_strength(
        {t: sector_histories(t)["Close"] for t in group.members},
        group,
        horizon_days=20,
        as_of="2022-06-30",
        benchmark=sector_histories("XU100")["Close"],
    )
    for key, value in expected.items():
        assert out[key] == value
    assert len(out["members"]) == 6 and out["sector_strong"] in (True, False)
    assert out["snapshot_id"] and len(out["result_id"]) == 12


def test_sector_tool_accepts_a_universe_sector_label(sector_histories):
    out = srv.rank_sector_relative_strength("Basic Metals / Steel", 60, "2022-06-30")
    assert out["sector"] == "Steel"


def test_sector_tool_reports_members_missing_from_the_snapshot(sector_histories, monkeypatch):
    from bist_harness.errors import DataUnavailableError

    def load(symbol):
        if symbol == "GARAN":
            raise DataUnavailableError("Snapshot s has no data for GARAN.")
        return sector_histories(symbol)

    monkeypatch.setattr(srv, "load_history", load)
    out = srv.rank_sector_relative_strength("Banking", 20, "2022-06-30")
    assert len(out["members"]) == 5
    assert any("GARAN" in w for w in out["warnings"])


@pytest.mark.parametrize(
    "args,code",
    [
        (("Crypto", 20, "2022-06-30"), "UNKNOWN_SECTOR"),
        (("Banking", 7, "2022-06-30"), "INVALID_ARGUMENT"),
        (("Banking", 20, "30.06.2022"), "INVALID_DATE"),
        (("Banking", 20, "2999-01-01"), "FUTURE_DATE"),
        (("Banking", 20, "2019-06-30"), "DATA_UNAVAILABLE"),
    ],
)
def test_sector_tool_bad_input(args, code, sector_histories):
    out = srv.rank_sector_relative_strength(*args)
    assert out["error"]["code"] == code


@pytest.mark.parametrize(
    "pattern", ["WEEKDAY_MEANS", "MON_WEAK_FRI_STRONG", "POST_LARGE_DOWN_REVERSION"]
)
def test_weekday_pattern_tool_tests_the_requested_period(pattern, offline_history):
    from bist_harness.tools.calendar_patterns import evaluate_pattern

    out = srv.test_weekday_pattern("ASELS", pattern, "2021-01-01", "2023-12-31")
    expected = evaluate_pattern(offline_history.loc[:"2023-12-31"], pattern, since="2021-01-01")
    for key, value in expected.items():
        assert out[key] == value
    assert out["ticker"] == "ASELS" and out["pattern"] == pattern
    assert out["definition"] and out["snapshot_id"] and len(out["result_id"]) == 12


def test_weekday_pattern_tool_rejects_an_unknown_pattern():
    out = srv.test_weekday_pattern("ASELS", "FULL_MOON", "2021-01-01", "2023-12-31")
    assert out["error"]["code"] == "INVALID_ARGUMENT"
    out = srv.test_weekday_pattern("GARAN", "WEEKDAY_MEANS", "2021-01-01", "2023-12-31")
    assert out["error"]["code"] == "UNKNOWN_TICKER"
