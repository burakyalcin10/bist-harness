"""Backtest engine: next-open execution, costs, portfolio returns and performance figures."""

import numpy as np
import pandas as pd
import pytest

from bist_harness.backtest import engine

INDEX = pd.date_range("2024-01-01", periods=30, freq="B")


def bars(n: int = 30) -> pd.DataFrame:
    """Open 100, 101, ...; close half a point above the open."""
    opens = 100.0 + np.arange(n)
    return pd.DataFrame(
        {"Open": opens, "High": opens + 1, "Low": opens - 1, "Close": opens + 0.5, "Volume": 1.0},
        index=INDEX[:n],
    )


def signal(*positions: int, n: int = 30) -> pd.Series:
    mask = pd.Series(False, index=INDEX[:n])
    mask.iloc[list(positions)] = True
    return mask


def test_entry_is_the_next_open_and_exit_the_close_ten_days_after_the_signal():
    run = engine.run_trades(bars(), signal(5), ticker="ASELS")
    assert (run.signals, len(run.trades), run.skipped_overlapping, run.skipped_incomplete) == (
        1,
        1,
        0,
        0,
    )
    trade = run.trades[0]
    assert trade.ticker == "ASELS"
    assert trade.signal_date == str(INDEX[5].date())
    assert trade.entry_date == str(INDEX[6].date())
    assert trade.exit_date == str(INDEX[15].date())
    assert (trade.entry_price, trade.exit_price) == (106.0, 115.5)
    expected = (115.5 / 106.0 * (1 - 0.0015) ** 2 - 1) * 100
    assert trade.return_pct == pytest.approx(expected, abs=1e-4)
    assert trade.info_date == trade.signal_date


def test_without_cost_the_return_is_the_plain_price_ratio():
    trade = engine.run_trades(bars(), signal(5), ticker="X", cost=0.0).trades[0]
    assert trade.return_pct == pytest.approx((115.5 / 106.0 - 1) * 100, abs=1e-4)


def test_holding_period_is_configurable():
    trade = engine.run_trades(bars(), signal(5), ticker="X", holding_days=3).trades[0]
    assert trade.exit_date == str(INDEX[8].date())


def test_signal_without_a_full_holding_window_opens_no_trade():
    run = engine.run_trades(bars(), signal(19, 20, 29), ticker="X")
    assert [t.signal_date for t in run.trades] == [str(INDEX[19].date())]
    assert run.skipped_incomplete == 1 and run.skipped_overlapping == 1


def test_signal_during_an_open_trade_is_ignored_and_the_exit_day_is_free_again():
    run = engine.run_trades(bars(), signal(2, 5, 11, 12), ticker="X")
    # trade 1: signal day 2, open until the close of day 12; day 12 is free again
    assert [t.signal_date for t in run.trades] == [str(INDEX[2].date()), str(INDEX[12].date())]
    assert run.skipped_overlapping == 2 and run.signals == 4


def test_changing_prices_after_the_signal_does_not_move_the_signal_or_entry_day():
    base = engine.run_trades(bars(), signal(5), ticker="X").trades[0]
    changed = bars()
    changed.iloc[6:] *= 2.0
    other = engine.run_trades(changed, signal(5), ticker="X").trades[0]
    assert (other.signal_date, other.entry_date, other.exit_date) == (
        base.signal_date,
        base.entry_date,
        base.exit_date,
    )
    assert other.entry_price == 2 * base.entry_price


def test_information_dated_after_the_signal_is_refused():
    info = pd.Series(INDEX, index=INDEX)
    ok = engine.run_trades(bars(), signal(5), ticker="X", info_dates=info.shift(3).bfill())
    assert ok.trades[0].info_date <= ok.trades[0].signal_date
    with pytest.raises(ValueError, match="look-ahead"):
        engine.run_trades(bars(), signal(5), ticker="X", info_dates=info.shift(-1).ffill())


def _daily(trades, frames, cost=0.0015):
    closes = {t: f["Close"] for t, f in frames.items()}
    opens = {t: f["Open"] for t, f in frames.items()}
    return engine.portfolio_returns(trades, closes, opens, INDEX, cost=cost)


def test_daily_portfolio_returns_compound_to_the_trade_return():
    trades = engine.run_trades(bars(), signal(5), ticker="X").trades
    daily = _daily(trades, {"X": bars()})
    assert list(daily.columns) == ["return", "open_trades"]
    assert daily["open_trades"].sum() == 10
    assert (daily.loc[daily["open_trades"] == 0, "return"] == 0).all()
    compounded = (1 + daily["return"]).prod() - 1
    assert compounded * 100 == pytest.approx(trades[0].return_pct, abs=1e-4)


def test_two_open_trades_are_averaged_with_equal_weight():
    cheap, rich = bars(), bars()
    rich.iloc[:, :4] *= 3
    rich.iloc[10:, :4] *= 1.1  # a jump on day 10 in one stock only
    trades = [
        *engine.run_trades(cheap, signal(5), ticker="A").trades,
        *engine.run_trades(rich, signal(5), ticker="B").trades,
    ]
    daily = _daily(trades, {"A": cheap, "B": rich}, cost=0.0)
    day = INDEX[10]
    a = cheap["Close"][day] / cheap["Close"].shift(1)[day] - 1
    b = rich["Close"][day] / rich["Close"].shift(1)[day] - 1
    assert daily.at[day, "open_trades"] == 2
    assert daily.at[day, "return"] == pytest.approx((a + b) / 2)


def test_performance_on_a_constant_daily_gain():
    daily = pd.DataFrame({"return": 0.01, "open_trades": 1}, index=INDEX[:20])
    out = engine.performance(daily)
    assert out["cumulative_return_pct"] == round((1.01**20 - 1) * 100, 2)
    assert out["cagr_pct"] == round((1.01**252 - 1) * 100, 2)
    assert out["max_drawdown_pct"] == 0.0
    assert out["exposure_pct"] == 100.0
    assert out["sharpe"] is None  # no variation: the ratio is undefined


def test_performance_reports_the_deepest_drawdown_and_a_finite_sharpe():
    returns = [0.10, -0.20, -0.10, 0.05, 0.30, -0.05]
    daily = pd.DataFrame({"return": returns, "open_trades": [1, 1, 1, 0, 1, 1]}, index=INDEX[:6])
    out = engine.performance(daily)
    # equity 1.10 -> 0.88 -> 0.792: the low is 28% below the peak of 1.10
    assert out["max_drawdown_pct"] == -28.0
    assert out["exposure_pct"] == round(5 / 6 * 100, 2)
    expected = np.mean(returns) / np.std(returns, ddof=1) * np.sqrt(252)
    assert out["sharpe"] == round(float(expected), 2)


def test_performance_of_an_empty_period_is_all_none():
    out = engine.performance(pd.DataFrame({"return": [], "open_trades": []}))
    assert out == {
        "cumulative_return_pct": None,
        "cagr_pct": None,
        "sharpe": None,
        "max_drawdown_pct": None,
        "exposure_pct": None,
    }


def _summary(positions, **kwargs):
    frame = bars()
    run = engine.run_trades(frame, signal(*positions), ticker="X", holding_days=2)
    daily = _daily(run.trades, {"X": frame})
    benchmark = frame["Close"].pct_change().fillna(0.0)
    return engine.summarize_backtest([run], daily, {"buy_and_hold": benchmark}, **kwargs)


def test_summary_counts_trades_and_compares_with_the_benchmark():
    out = _summary([1, 5, 9, 13, 17, 21])
    assert (out["signals"], out["trades"]) == (6, 6)
    assert out["skipped_overlapping"] == 0 and out["skipped_incomplete"] == 0
    assert out["win_rate_pct"] == 100.0
    assert out["average_trade_return_pct"] > 0 and out["median_trade_return_pct"] > 0
    assert out["benchmark_buy_and_hold_return_pct"] == round((129.5 / 100.5 - 1) * 100, 2)
    assert out["excess_vs_buy_and_hold_pct"] == round(
        out["cumulative_return_pct"] - out["benchmark_buy_and_hold_return_pct"], 2
    )
    assert out["sample_warning"] == "Limited sample size"
    assert "UNDERPERFORMS_BUY_AND_HOLD" in out["flags"] and "FEW_TRADES" not in out["flags"]


def test_summary_flags_a_result_built_on_very_few_trades():
    out = _summary([1, 9])
    assert out["trades"] == 2 and "FEW_TRADES" in out["flags"]
    assert out["sample_warning"] == "Very small sample size"


def test_summary_without_trades_has_no_statistics():
    out = _summary([])
    assert out["trades"] == 0 and out["win_rate_pct"] is None
    assert out["average_trade_return_pct"] is None and "FEW_TRADES" in out["flags"]
    assert out["cumulative_return_pct"] == 0.0


def test_summary_breaks_trades_down_by_regime_and_period():
    regimes = pd.Series("Uptrend", index=INDEX, dtype=object)
    regimes.iloc[:8] = "Downtrend"
    out = _summary([1, 5, 9, 13, 17, 21], regimes=regimes)
    assert out["by_regime"]["Downtrend"]["trades"] == 2
    assert out["by_regime"]["Uptrend"]["trades"] == 4
    assert out["by_period"] == {
        "discovery": {
            "trades": 6,
            "win_rate_pct": 100.0,
            "average_trade_return_pct": out["average_trade_return_pct"],
        }
    }


def test_trade_sample_is_capped_and_holds_the_latest_trades():
    out = _summary([1, 5, 9, 13, 17, 21], sample_size=4)
    assert len(out["trade_sample"]) == 4
    assert out["trade_sample"][0]["signal_date"] == str(INDEX[21].date())
    assert set(out["trade_sample"][0]) == {
        "ticker",
        "signal_date",
        "entry_date",
        "exit_date",
        "entry_price",
        "exit_price",
        "return_pct",
    }


def test_trades_signalled_before_the_regime_is_defined_are_counted_as_undefined():
    regimes = pd.Series("Uptrend", index=INDEX, dtype=object)
    regimes.iloc[:8] = None
    out = _summary([1, 5, 9, 13, 17, 21], regimes=regimes)
    assert out["by_regime"]["Undefined"]["trades"] == 2
    assert out["by_regime"]["Uptrend"]["trades"] == 4
    assert sum(group["trades"] for group in out["by_regime"].values()) == out["trades"]
