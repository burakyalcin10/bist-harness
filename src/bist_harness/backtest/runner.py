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
from bist_harness.backtest.strategies import (
    RULES,
    StrategyContext,
    information_dates,
    signals,
)
from bist_harness.data.peers import peer_group_of

EXECUTION = (
    "A signal is decided at the close of day t. The trade is entered at the open of the "
    "next trading day and closed at the close 10 trading days after the signal. One trade "
    "per stock at a time; open trades are held with equal weight; cash earns nothing. "
    "Sharpe uses a risk-free rate of 0."
)


def _buy_and_hold_returns(closes: dict[str, pd.Series], calendar: pd.DatetimeIndex) -> pd.Series:
    """Daily return of a basket bought once with equal money in each stock and then held.

    Each stock is bought at its last close before the period (or its first close in it)
    and never rebalanced; the basket's value is the average of the stocks' growth.
    """
    if not closes or not len(calendar):
        return pd.Series(0.0, index=calendar)
    growth = {}
    for name, series in closes.items():
        series = series.dropna()
        before = series.loc[series.index < calendar[0]]
        inside = series.loc[calendar[0] : calendar[-1]]
        if inside.empty:
            continue
        base = float(before.iloc[-1]) if len(before) else float(inside.iloc[0])
        growth[name] = (series.reindex(calendar, method="ffill") / base).fillna(1.0)
    if not growth:
        return pd.Series(0.0, index=calendar)
    value = pd.DataFrame(growth).mean(axis=1)
    returns = value / value.shift(1) - 1
    returns.iloc[0] = value.iloc[0] - 1
    return returns


def run_variant(variant: str, context: StrategyContext, *, start: str, end: str) -> dict:
    """Backtest one variant between ``start`` and ``end`` (both inclusive).

    Signals before ``start`` are not traded, but earlier rows still warm up the
    indicators. A trade needs its whole holding window inside the data.
    """
    first, last = pd.Timestamp(start), pd.Timestamp(end)
    # Every day on which the index or one of the stocks has a bar: a session missing
    # from the index file must not drop a day of an open trade.
    calendar = context.benchmark.loc[first:last].index
    for history in context.histories.values():
        calendar = calendar.union(history.loc[first:last].index)
    runs = []
    info = information_dates(variant, context)
    for ticker, signal in signals(variant, context).items():
        history = context.histories[ticker]
        runs.append(
            run_trades(
                history,
                signal & (history.index >= first),
                ticker=ticker,
                info_dates=None if info is None else info[ticker],
            )
        )

    trades = [trade for run in runs for trade in run.trades]
    closes = {t: h["Close"] for t, h in context.histories.items()}
    opens = {t: h["Open"] for t, h in context.histories.items()}
    daily = portfolio_returns(trades, closes, opens, calendar)

    benchmarks = {
        "buy_and_hold": _buy_and_hold_returns(closes, calendar),
        "xu100": context.benchmark.pct_change().reindex(calendar).fillna(0.0),
    }
    if variant != "A_TECHNICAL":
        members = {m for t in context.histories for m in peer_group_of(t).members}
        peers = {m: context.peer_closes[m] for m in sorted(members) if m in context.peer_closes}
        benchmarks["sector_peers"] = _buy_and_hold_returns(peers, calendar)

    summary = summarize_backtest(runs, daily, benchmarks, regimes=market_regime(context.benchmark))
    return {
        "strategy": variant,
        "rule": RULES[variant],
        "execution": EXECUTION,
        "holding_days": HOLDING_DAYS,
        "cost_per_side_pct": round(COST * 100, 2),
        **summary,
    }
