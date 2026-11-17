"""Run one strategy variant over a period: signals, trades, portfolio, benchmarks."""

from __future__ import annotations

import pandas as pd

from bist_harness.backtest.engine import (
    COST,
    HOLDING_DAYS,
    portfolio_returns,
    run_trades,
    summarize_backtest,
)
from bist_harness.backtest.periods import market_regime
from bist_harness.backtest.strategies import RULES, StrategyContext, signals
from bist_harness.data.peers import peer_group_of

EXECUTION = (
    "A signal is decided at the close of day t. The trade is entered at the open of the "
    "next trading day and closed at the close 10 trading days after the signal. One trade "
    "per stock at a time; open trades are held with equal weight; cash earns nothing. "
    "Sharpe uses a risk-free rate of 0."
)


def _equal_weight_returns(closes: dict[str, pd.Series], calendar: pd.DatetimeIndex) -> pd.Series:
    """Mean daily return of the given stocks on each calendar day (those with a bar)."""
    if not closes:
        return pd.Series(0.0, index=calendar)
    daily = pd.DataFrame({name: series.pct_change() for name, series in closes.items()})
    return daily.reindex(calendar).mean(axis=1).fillna(0.0)


def run_variant(variant: str, context: StrategyContext, *, start: str, end: str) -> dict:
    """Backtest one variant between ``start`` and ``end`` (both inclusive).

    Signals before ``start`` are not traded, but earlier rows still warm up the
    indicators. A trade needs its whole holding window inside the data.
    """
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    calendar = context.benchmark.loc[first:last].index
    runs = []
    for ticker, signal in signals(variant, context).items():
        history = context.histories[ticker]
        runs.append(run_trades(history, signal & (history.index >= first), ticker=ticker))

    trades = [trade for run in runs for trade in run.trades]
    closes = {t: h["Close"] for t, h in context.histories.items()}
    opens = {t: h["Open"] for t, h in context.histories.items()}
    daily = portfolio_returns(trades, closes, opens, calendar)

    benchmarks = {
        "buy_and_hold": _equal_weight_returns(closes, calendar),
        "xu100": context.benchmark.pct_change().reindex(calendar).fillna(0.0),
    }
    if variant != "A_TECHNICAL":
        members = {m for t in context.histories for m in peer_group_of(t).members}
        peers = {m: context.peer_closes[m] for m in sorted(members) if m in context.peer_closes}
        benchmarks["sector_peers"] = _equal_weight_returns(peers, calendar)

    summary = summarize_backtest(runs, daily, benchmarks, regimes=market_regime(context.benchmark))
    return {
        "strategy": variant,
        "rule": RULES[variant],
        "execution": EXECUTION,
        "holding_days": HOLDING_DAYS,
        "cost_per_side_pct": round(COST * 100, 2),
        **summary,
    }
