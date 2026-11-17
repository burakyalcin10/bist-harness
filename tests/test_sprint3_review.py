"""Regression tests for the findings of the Sprint 3 code review."""

import numpy as np
import pandas as pd
import pytest

from bist_harness.backtest import engine, runner, strategies
from bist_harness.data import kap
from bist_harness.mcp_server import server as srv
from bist_harness.tools import fundamentals as fn
from bist_harness.tools.macro import macro_context
from bist_harness.tools.schemas import TOOL_SCHEMAS, validate_tool_call

from .synth import ohlcv
from .test_fundamentals_tools import CLOSE, CPI, _calendar, _statements
from .test_macro import _series as macro_series

# --- fundamentals: the source restates earlier periods, prices are dividend-adjusted --------


def _metrics():
    return fn.fundamental_metrics(
        _statements(), _calendar(), ticker="TUPRS", as_of="2025-11-10", close=CLOSE, cpi=CPI
    )


def test_without_a_comparative_column_real_growth_is_not_guessed():
    """Superseded by K-055: the layer now comes from KAP reports with their comparative
    column (tests/test_fundamentals_point_in_time.py). Data without that column still
    gets no real growth, and says why."""
    out = _metrics()
    assert out["revenue_yoy_pct"] == 50.0
    for key in ("revenue_real_yoy_pct", "ebitda_real_yoy_pct", "net_profit_real_yoy_pct"):
        assert out[key] is None
    codes = [w.split(":")[0] for w in out["warnings"]]
    assert "NO_COMPARABLE_YEAR" in codes and "RESTATED_SOURCE" not in codes


def test_valuation_is_withheld_without_unadjusted_prices():
    """The dividend-adjusted close is never used for a market value (Sprint 4: the
    unadjusted close comes from the prices_raw layer, tests/test_raw_prices.py)."""
    out = _metrics()
    assert out["market_cap_mn"] is None and out["pe"] is None
    assert out["pb"] is None and out["ev_ebitda"] is None
    assert out["valuation_note"] == "WITHHELD_NO_UNADJUSTED_PRICE"


def test_change_tool_carries_the_same_warning_and_still_gives_a_trend():
    out = fn.fundamental_change(
        _statements(), _calendar(), ticker="TUPRS", as_of="2025-11-10", cpi=CPI
    )
    assert any(w.startswith("NO_COMPARABLE_YEAR") for w in out["warnings"])
    assert out["revenue_real_yoy_pct"] is None and out["fundamental_trend"] == "Improving"


def test_variants_that_read_fundamentals_say_the_source_is_not_point_in_time(monkeypatch):
    from .test_feature_table import _disclosures

    frames: dict[str, pd.DataFrame] = {}
    macro = macro_series()
    monkeypatch.setattr(
        srv, "load_history", lambda s: frames.setdefault(s, ohlcv(1750, sum(map(ord, s))))
    )
    monkeypatch.setattr(srv, "load_statements", lambda: _statements())
    monkeypatch.setattr(srv, "load_disclosure_calendar", lambda: _calendar())
    monkeypatch.setattr(srv, "load_macro", lambda name: macro[name])
    monkeypatch.setattr(srv, "load_disclosures", lambda: _disclosures())
    out = srv.run_backtest("C_TECH_SECTOR_FUND", ["TUPRS"], "2025-01-01", "2026-06-30")
    # superseded by K-055: the layer is rebuilt from as-published KAP reports, so the
    # Sprint 3 warning about a restating source no longer applies
    assert not any(w.startswith("FUNDAMENTALS_NOT_POINT_IN_TIME") for w in out["warnings"])
    plain = srv.run_backtest("A_TECHNICAL", ["TUPRS"], "2025-01-01", "2026-06-30")
    assert not any(w.startswith("FUNDAMENTALS") for w in plain["warnings"])


# --- backtest: calendar, benchmark, flags, coverage ------------------------------------------

DAYS = pd.date_range("2024-01-01", periods=40, freq="B")


def _bars(scale: float = 1.0) -> pd.DataFrame:
    opens = (100.0 + np.arange(40)) * scale
    return pd.DataFrame(
        {"Open": opens, "High": opens + 1, "Low": opens - 1, "Close": opens + 0.5, "Volume": 1.0},
        index=DAYS,
    )


def test_a_session_missing_from_the_index_calendar_is_not_dropped_from_the_portfolio(monkeypatch):
    stock = _bars()
    signal = pd.Series(False, index=DAYS)
    signal.iloc[5] = True
    monkeypatch.setattr(strategies, "technical_signal", lambda history: signal)
    benchmark = stock["Close"].drop(DAYS[10])  # the index has no bar on a day the stock traded
    context = strategies.StrategyContext(
        histories={"ASELS": stock}, peer_closes={}, benchmark=benchmark
    )
    out = runner.run_variant(
        "A_TECHNICAL", context, start=str(DAYS[0].date()), end=str(DAYS[-1].date())
    )
    trade = engine.run_trades(stock, signal, ticker="ASELS").trades[0]
    assert out["trades"] == 1
    assert out["cumulative_return_pct"] == round(trade.return_pct, 2)


def test_buy_and_hold_is_a_basket_bought_once_and_never_rebalanced(monkeypatch):
    doubles = pd.DataFrame({"Open": 100.0, "Close": np.linspace(100.0, 200.0, 40)}, index=DAYS)
    flat = pd.DataFrame({"Open": 100.0, "Close": 100.0}, index=DAYS)
    for frame in (doubles, flat):
        frame["High"], frame["Low"], frame["Volume"] = frame["Close"], frame["Close"], 1.0
    monkeypatch.setattr(strategies, "technical_signal", lambda h: pd.Series(False, index=h.index))
    context = strategies.StrategyContext(
        histories={"ASELS": doubles, "THYAO": flat}, peer_closes={}, benchmark=flat["Close"]
    )
    out = runner.run_variant(
        "A_TECHNICAL", context, start=str(DAYS[0].date()), end=str(DAYS[-1].date())
    )
    # half the money doubles, half stays: +50%; daily rebalancing would give about +41%
    assert out["benchmark_buy_and_hold_return_pct"] == 50.0


def test_a_backtest_without_trades_is_not_called_an_underperformer(monkeypatch):
    monkeypatch.setattr(strategies, "technical_signal", lambda h: pd.Series(False, index=h.index))
    context = strategies.StrategyContext(
        histories={"ASELS": _bars()}, peer_closes={}, benchmark=_bars()["Close"]
    )
    out = runner.run_variant(
        "A_TECHNICAL", context, start=str(DAYS[0].date()), end=str(DAYS[-1].date())
    )
    assert out["trades"] == 0 and out["flags"] == ["FEW_TRADES"]


def test_backtest_tool_warns_when_the_period_starts_before_the_data(monkeypatch):
    frames: dict[str, pd.DataFrame] = {}
    monkeypatch.setattr(
        srv, "load_history", lambda s: frames.setdefault(s, ohlcv(1200, sum(map(ord, s))))
    )
    out = srv.run_backtest("A_TECHNICAL", ["ASELS"], "2010-01-01", "2022-12-30")
    assert out["data_first_date"] == "2020-01-02"
    assert any(w.startswith("DATA_STARTS_LATER") for w in out["warnings"])
    inside = srv.run_backtest("A_TECHNICAL", ["ASELS"], "2021-01-01", "2022-12-30")
    assert not any(w.startswith("DATA_STARTS_LATER") for w in inside["warnings"])


# --- macro and news: coverage ------------------------------------------------------------------


def test_fx_start_is_the_rate_in_effect_and_a_period_before_the_data_is_flagged():
    series = macro_series()
    fx = series["fx"]
    inside = macro_context(series, start="2025-03-01", end="2025-03-31")  # the 1st is a Saturday
    assert inside["usdtry_start"] == round(float(fx["USDTRY"].loc[:"2025-03-01"].iloc[-1]), 4)
    early = macro_context(series, start="2015-01-01", end="2024-06-28")
    assert early["usdtry_start"] is None and early["usdtry_change_pct"] is None
    assert any(w.startswith("FX_DATA_STARTS_LATER") for w in early["warnings"])
    assert early["usdtry_end"] is not None


def test_news_topic_is_an_enumerated_argument():
    spec = TOOL_SCHEMAS["get_news_events"]["parameters"]["properties"]["topic"]
    assert spec["enum"] == list(kap.TOPICS)
    base = {"start": "2025-01-01", "end": "2025-06-30"}
    assert validate_tool_call("get_news_events", {**base, "topic": "dividend"}) is None
    assert "topic" in validate_tool_call("get_news_events", {**base, "topic": "regulation"})


def test_news_tool_says_from_when_disclosures_are_held(monkeypatch):
    from .test_kap import _table

    monkeypatch.setattr(srv, "load_disclosures", lambda: _table())
    before = srv.get_news_events("2024-01-01", "2024-12-31")
    assert before["total"] == 0 and before["data_first_date"] == "2025-03-01"
    assert any(w.startswith("COVERAGE_STARTS_LATER") for w in before["warnings"])
    assert srv.get_news_events("2025-03-01", "2025-04-30")["warnings"] == []


@pytest.mark.parametrize(
    "subject,summary,topic",
    [
        ("Özel Durum Açıklaması (Genel)", "İhracat sözleşmesi imzalanması", "contract"),
        ("Özel Durum Açıklaması (Genel)", "Yurtdışı Piyasalara Tahvil İhracı", "financing"),
        ("Özel Durum Açıklaması (Genel)", "Yatırımcı sunumu hakkında", "other"),
        ("Özel Durum Açıklaması (Genel)", "Yeni yatırım kararı", "investment"),
    ],
)
def test_export_and_investor_notices_are_not_mistaken_for_issues_and_investments(
    subject, summary, topic
):
    assert kap.tag_topic(subject, summary) == topic
