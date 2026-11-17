"""Strategy variants: entry rules, subset relations and no look-ahead."""

import pandas as pd
import pytest

from bist_harness.backtest import strategies
from bist_harness.data.peers import load_peer_groups, peer_group_of
from bist_harness.tools import events as ev
from bist_harness.tools.indicators import add_all_indicators
from bist_harness.tools.sector import lag_score_series, rank_sector_relative_strength

from .synth import ohlcv

TICKERS = ["AKBNK", "THYAO", "PGSUS"]


def _history(symbol: str, days: int = 700) -> pd.DataFrame:
    return ohlcv(days, seed=sum(map(ord, symbol)))


def _context(days: int = 700, rows: int | None = None) -> strategies.StrategyContext:
    members = {m for t in TICKERS for m in peer_group_of(t).members}
    cut = slice(None, rows)
    return strategies.StrategyContext(
        histories={t: _history(t, days).iloc[cut] for t in TICKERS},
        peer_closes={m: _history(m, days)["Close"].iloc[cut] for m in members},
        benchmark=_history("XU100", days)["Close"].iloc[cut],
    )


def test_lag_score_series_equals_the_ranking_tool_on_sample_days():
    banking = load_peer_groups()["Banking"]
    closes = {m: _history(m)["Close"] for m in banking.members}
    benchmark = _history("XU100")["Close"]
    series = lag_score_series(closes, banking, "AKBNK", horizon_days=20, benchmark=benchmark)
    assert list(series.columns) == ["lag_score", "sector_median", "sector_strong"]
    assert series["lag_score"].iloc[:20].isna().all()
    for position in (20, 137, 400, 699):
        day = series.index[position]
        ranking = rank_sector_relative_strength(
            closes, banking, horizon_days=20, as_of=str(day.date()), benchmark=benchmark
        )
        row = next(r for r in ranking["members"] if r["ticker"] == "AKBNK")
        assert round(series.at[day, "lag_score"] * 100, 2) == row["lag_score_pct"]
        assert (
            round(series.at[day, "sector_median"] * 100, 2) == ranking["sector_median_return_pct"]
        )
        assert bool(series.at[day, "sector_strong"]) == ranking["sector_strong"]


def test_lag_score_is_undefined_for_an_undersized_group():
    telecom = load_peer_groups()["Telecom"]
    closes = {m: _history(m)["Close"] for m in telecom.members}
    series = lag_score_series(
        closes, telecom, "TCELL", horizon_days=20, benchmark=_history("XU100")["Close"]
    )
    assert series["lag_score"].isna().all() and not series["sector_strong"].any()


def test_variant_a_is_the_union_of_the_two_reversal_events():
    context = _context()
    out = strategies.signals("A_TECHNICAL", context)
    assert set(out) == set(TICKERS)
    for ticker in TICKERS:
        frame = add_all_indicators(context.histories[ticker])
        trough = ev.event_mask(frame, "RSI_LOCAL_TROUGH")
        trough.iloc[:16] = False
        expected = trough | ev.event_mask(frame, "BOLLINGER_LOWER_TOUCH")
        pd.testing.assert_series_equal(out[ticker], expected, check_names=False)
        assert out[ticker].sum() > 5


def test_variant_b_keeps_only_laggards_of_a_strong_sector():
    context = _context()
    a = strategies.signals("A_TECHNICAL", context)
    b = strategies.signals("B_TECH_SECTOR", context)
    kept = 0
    for ticker in TICKERS:
        assert not (b[ticker] & ~a[ticker]).any()
        lag = lag_score_series(
            context.peer_closes,
            peer_group_of(ticker),
            ticker,
            horizon_days=20,
            benchmark=context.benchmark,
        )
        days = b[ticker][b[ticker]].index
        assert (lag.loc[days, "lag_score"] < 0).all() and lag.loc[days, "sector_strong"].all()
        dropped = a[ticker] & ~b[ticker]
        still_ok = (lag.loc[dropped[dropped].index, "lag_score"] < 0) & lag.loc[
            dropped[dropped].index, "sector_strong"
        ].astype(bool)
        assert not still_ok.any()
        kept += int(b[ticker].sum())
    assert kept > 0


@pytest.mark.parametrize("variant", ["A_TECHNICAL", "B_TECH_SECTOR"])
def test_signals_up_to_day_t_do_not_change_when_later_data_is_removed(variant):
    full = strategies.signals(variant, _context())
    cut = strategies.signals(variant, _context(rows=450))
    for ticker in TICKERS:
        pd.testing.assert_series_equal(cut[ticker], full[ticker].iloc[:450], check_names=False)


def test_variants_that_need_later_layers_are_not_available_yet():
    with pytest.raises(NotImplementedError):
        strategies.signals("C_TECH_SECTOR_FUND", _context())
    with pytest.raises(ValueError):
        strategies.signals("Z_UNKNOWN", _context())


def test_every_variant_has_a_rule_text():
    assert set(strategies.RULES) == set(strategies.VARIANTS)
    assert all(strategies.RULES[v] for v in strategies.VARIANTS)
