"""MCP tools for fundamentals: get_fundamental_metrics and calculate_fundamental_change."""

import pandas as pd
import pytest

from bist_harness.errors import DataUnavailableError
from bist_harness.mcp_server import server as srv
from bist_harness.tools import fundamentals as fn

from .test_fundamentals_tools import CLOSE, _calendar, _statements

CPI_TABLE = pd.DataFrame(
    {
        "period": pd.to_datetime(["2024-09-30", "2025-09-30"]),
        "annual_pct": [50.0, 30.0],
        "monthly_pct": [2.0, 30.0],  # chained index: 100, then 130
        "published": pd.to_datetime(["2024-10-03", "2025-10-03"]),
    }
)


@pytest.fixture(autouse=True)
def fundamentals(monkeypatch):
    monkeypatch.setattr(srv, "load_statements", lambda: _statements())
    monkeypatch.setattr(srv, "load_disclosure_calendar", lambda: _calendar())
    monkeypatch.setattr(srv, "load_macro", lambda name: CPI_TABLE)
    monkeypatch.setattr(
        srv, "load_history", lambda symbol: pd.DataFrame({"Close": CLOSE}, index=CLOSE.index)
    )
    # no unadjusted prices: the synthetic statements must not meet the real raw layer
    # (valuation is tested in tests/test_fundamentals_point_in_time.py)
    monkeypatch.setattr(srv, "load_raw", lambda ticker: None)


def test_metrics_tool_returns_the_point_in_time_metrics():
    out = srv.get_fundamental_metrics("tuprs", "2025-11-10")
    cpi = pd.Series([100.0, 130.0], index=CPI_TABLE["period"])
    expected = fn.fundamental_metrics(
        _statements(), _calendar(), ticker="TUPRS", as_of="2025-11-10", close=CLOSE, cpi=cpi
    )
    for key, value in expected.items():
        assert out[key] == value, key
    assert out["period"] == "2025Q3" and out["revenue_yoy_pct"] == 50.0 and out["pe"] is None
    assert "KAP" in out["data_source"] and out["snapshot_id"] and len(out["result_id"]) == 12


def test_metrics_tool_the_day_before_publication_reports_the_previous_period():
    assert srv.get_fundamental_metrics("TUPRS", "2025-11-02")["period"] == "2025Q2"
    assert srv.get_fundamental_metrics("TUPRS", "2025-11-03")["period"] == "2025Q3"


def test_change_tool_returns_quarters_and_the_trend():
    out = srv.calculate_fundamental_change("TUPRS", "2025-11-10")
    assert out["fundamental_trend"] == "Improving" and len(out["quarters"]) == 4
    assert out["periods"] == 4
    assert len(srv.calculate_fundamental_change("TUPRS", "2025-11-10", 2)["quarters"]) == 2


def test_tools_work_without_macro_or_price_data(monkeypatch):
    def no_macro(name):
        raise DataUnavailableError("no macro series")

    def no_prices(symbol):
        raise DataUnavailableError("no data")

    monkeypatch.setattr(srv, "load_macro", no_macro)
    monkeypatch.setattr(srv, "load_history", no_prices)
    out = srv.get_fundamental_metrics("TUPRS", "2025-11-10")
    assert out["revenue_yoy_pct"] == 50.0 and out["revenue_real_yoy_pct"] is None
    assert out["pe"] is None


@pytest.mark.parametrize(
    "call,code",
    [
        (lambda: srv.get_fundamental_metrics("GARAN", "2025-11-10"), "UNKNOWN_TICKER"),
        (lambda: srv.get_fundamental_metrics("TUPRS", "10.11.2025"), "INVALID_DATE"),
        (lambda: srv.get_fundamental_metrics("TUPRS", "2999-01-01"), "FUTURE_DATE"),
        (lambda: srv.get_fundamental_metrics("TUPRS", "2024-01-01"), "DATA_UNAVAILABLE"),
        (lambda: srv.get_fundamental_metrics("THYAO", "2025-11-10"), "DATA_UNAVAILABLE"),
        (lambda: srv.calculate_fundamental_change("TUPRS", "2025-11-10", 0), "INVALID_ARGUMENT"),
        (lambda: srv.calculate_fundamental_change("TUPRS", "2025-11-10", 20), "INVALID_ARGUMENT"),
        (lambda: srv.calculate_fundamental_change("TUPRS", "2024-01-01"), "DATA_UNAVAILABLE"),
    ],
)
def test_bad_input_and_missing_data_are_error_objects(call, code):
    out = call()
    assert set(out) == {"error"} and out["error"]["code"] == code


def test_fundamental_data_that_was_never_built_names_the_build_command(monkeypatch):
    def missing():
        raise DataUnavailableError("no fundamental data. Run `... fundamentals build` first.")

    monkeypatch.setattr(srv, "load_statements", missing)
    out = srv.get_fundamental_metrics("TUPRS", "2025-11-10")
    assert out["error"]["code"] == "DATA_UNAVAILABLE"
    assert "fundamentals build" in out["error"]["message"]


def test_change_tool_adds_the_price_reaction_of_each_quarter(monkeypatch):
    from bist_harness.tools.disclosure import post_disclosure_returns

    days = pd.date_range("2024-01-01", "2025-12-31", freq="B")
    frames = {
        "TUPRS": pd.DataFrame(
            {"Close": pd.Series(range(100, 100 + len(days)), index=days, dtype=float)}
        ),
        "XU100": pd.DataFrame({"Close": pd.Series(500.0, index=days)}),
    }

    def load(symbol):
        if symbol not in frames:
            raise DataUnavailableError(f"no data for {symbol}")
        return frames[symbol]

    monkeypatch.setattr(srv, "load_history", load)
    out = srv.calculate_fundamental_change("TUPRS", "2025-11-12")
    latest, previous = out["quarters"][0], out["quarters"][1]
    assert latest["period"] == "2025Q3" and previous["period"] == "2025Q2"
    expected = post_disclosure_returns(
        frames["TUPRS"]["Close"].loc[:"2025-11-12"],
        [pd.Timestamp("2025-11-03"), pd.Timestamp("2025-08-01")],
        benchmark=frames["XU100"]["Close"],
        peers={},
    )
    assert latest["reaction_5d_pct"] == expected.iloc[0]["return_5d_pct"]
    assert latest["reaction_20d_pct"] is None  # not complete seven trading days later
    assert previous["reaction_20d_pct"] == expected.iloc[1]["return_20d_pct"]
    assert previous["abnormal_vs_index_5d_pct"] == expected.iloc[1]["return_5d_pct"]
    assert previous["abnormal_vs_peers_5d_pct"] is None  # no peer data in this test
    summary = out["reaction_summary"]
    assert summary["events"] == 5 and summary["horizons"]["5d"]["events"] == 5
    assert summary["horizons"]["20d"]["events"] == 4
