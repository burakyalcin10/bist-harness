"""Backtest engine (project brief, section 18).

Timing, fixed in ``docs/preregistration.md``:

* a signal is decided at the close of day t, from data up to day t;
* the trade is entered at the **open of day t+1** and left at the close of day
  t + ``holding_days``; no trade is ever filled at the price of the bar that produced
  its signal;
* one trade per stock at a time: a signal that would enter during an open trade is
  ignored; a signal without a full holding window in the data opens no trade.

Cost is charged once on entry and once on exit (commission plus slippage). The portfolio
holds the open trades with equal weight and earns nothing while it holds none.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from bist_harness.backtest.periods import period_of
from bist_harness.tools.events import sample_warning

COST = 0.0015  # 0.10% commission + 0.05% slippage, per side
HOLDING_DAYS = 10
TRADING_DAYS_PER_YEAR = 252
FEW_TRADES = 5
SAMPLE_FIELDS = (
    "ticker",
    "signal_date",
    "entry_date",
    "exit_date",
    "entry_price",
    "exit_price",
    "return_pct",
)


@dataclass(frozen=True)
class Trade:
    ticker: str
    signal_date: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    return_pct: float
    info_date: str  # date of the latest information the signal used


@dataclass(frozen=True)
class TradeRun:
    """Trades of one stock, with what happened to the signals that opened none."""

    trades: tuple[Trade, ...]
    signals: int
    skipped_overlapping: int
    skipped_incomplete: int


def run_trades(
    df: pd.DataFrame,
    signal: pd.Series,
    *,
    ticker: str,
    holding_days: int = HOLDING_DAYS,
    cost: float = COST,
    info_dates: pd.Series | None = None,
) -> TradeRun:
    """Turn the signal days of one stock into trades.

    ``info_dates`` gives, for each day, the date of the latest information behind that
    day's signal (a disclosure date, a macro release). A date after the signal day is a
    look-ahead error and raises.
    """
    opens = df["Open"].to_numpy(dtype=float)
    closes = df["Close"].to_numpy(dtype=float)
    days = df.index
    flags = signal.reindex(days, fill_value=False).to_numpy(dtype=bool)
    n = len(days)

    trades: list[Trade] = []
    overlapping = incomplete = 0
    busy_until = -1  # position of the exit bar of the open trade
    for i in np.flatnonzero(flags):
        if i < busy_until:
            overlapping += 1
            continue
        exit_at = i + holding_days
        if exit_at >= n:
            incomplete += 1
            continue
        signal_day = days[i]
        info_day = signal_day if info_dates is None else pd.Timestamp(info_dates.loc[signal_day])
        if info_day > signal_day:
            raise ValueError(
                f"look-ahead: {ticker} signal on {signal_day.date()} uses information "
                f"dated {info_day.date()}"
            )
        entry_price, exit_price = opens[i + 1], closes[exit_at]
        trades.append(
            Trade(
                ticker=ticker,
                signal_date=str(signal_day.date()),
                entry_date=str(days[i + 1].date()),
                exit_date=str(days[exit_at].date()),
                entry_price=round(float(entry_price), 4),
                exit_price=round(float(exit_price), 4),
                return_pct=round(float(exit_price / entry_price * (1 - cost) ** 2 - 1) * 100, 4),
                info_date=str(info_day.date()),
            )
        )
        busy_until = exit_at
    return TradeRun(tuple(trades), int(flags.sum()), overlapping, incomplete)


def portfolio_returns(
    trades: Sequence[Trade],
    closes: dict[str, pd.Series],
    opens: dict[str, pd.Series],
    calendar: pd.DatetimeIndex,
    *,
    cost: float = COST,
) -> pd.DataFrame:
    """Daily portfolio return and number of open trades over ``calendar``.

    A trade earns open-to-close on its entry day and close-to-close afterwards; cost is
    taken on the entry day and on the exit day. The day's portfolio return is the mean
    over the trades open that day.
    """
    total = pd.Series(0.0, index=calendar)
    count = pd.Series(0, index=calendar)
    for trade in trades:
        close, open_ = closes[trade.ticker], opens[trade.ticker]
        entry, exit_ = pd.Timestamp(trade.entry_date), pd.Timestamp(trade.exit_date)
        daily = close.pct_change().loc[entry:exit_].copy()
        daily.loc[entry] = close.loc[entry] / open_.loc[entry] - 1
        growth = 1 + daily
        growth.loc[entry] *= 1 - cost
        growth.loc[exit_] *= 1 - cost
        held = growth.index.intersection(calendar)
        total.loc[held] += growth.loc[held] - 1
        count.loc[held] += 1
    average = (total / count.where(count > 0)).fillna(0.0)
    return pd.DataFrame({"return": average, "open_trades": count})


def performance(daily: pd.DataFrame) -> dict:
    """Cumulative return, CAGR, Sharpe (risk-free rate 0), deepest drawdown and exposure."""
    returns = daily["return"].astype(float)
    if returns.empty:
        return {
            "cumulative_return_pct": None,
            "cagr_pct": None,
            "sharpe": None,
            "max_drawdown_pct": None,
            "exposure_pct": None,
        }
    equity = (1 + returns).cumprod()
    cumulative = float(equity.iloc[-1] - 1)
    deviation = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    sharpe = None
    if deviation > 1e-12:
        ratio = float(returns.mean()) / deviation * TRADING_DAYS_PER_YEAR**0.5
        sharpe = round(float(ratio), 2)
    cagr = None
    if cumulative > -1:
        cagr = round(((1 + cumulative) ** (TRADING_DAYS_PER_YEAR / len(returns)) - 1) * 100, 2)
    peak = equity.cummax().clip(lower=1.0)  # the starting capital counts as the first peak
    return {
        "cumulative_return_pct": round(cumulative * 100, 2),
        "cagr_pct": cagr,
        "sharpe": sharpe,
        "max_drawdown_pct": round(float((equity / peak - 1).min()) * 100, 2),
        "exposure_pct": round(float((daily["open_trades"] > 0).mean()) * 100, 2),
    }


def _trade_stats(trades: Sequence[Trade]) -> dict:
    if not trades:
        return {"trades": 0, "win_rate_pct": None, "average_trade_return_pct": None}
    returns = np.array([t.return_pct for t in trades])
    return {
        "trades": len(trades),
        "win_rate_pct": round(float((returns > 0).mean()) * 100, 2),
        "average_trade_return_pct": round(float(returns.mean()), 2),
    }


def _grouped(trades: Sequence[Trade], key) -> dict[str, dict]:
    groups: dict[str, list[Trade]] = {}
    for trade in trades:
        name = key(trade)
        if name is not None:
            groups.setdefault(name, []).append(trade)
    return {name: _trade_stats(members) for name, members in sorted(groups.items())}


def summarize_backtest(
    runs: Sequence[TradeRun],
    daily: pd.DataFrame,
    benchmarks: dict[str, pd.Series],
    *,
    regimes: pd.Series | None = None,
    sample_size: int = 12,
) -> dict:
    """Trade statistics, portfolio performance, benchmark comparison and warning flags.

    ``benchmarks`` maps a name to a series of daily returns; ``regimes`` maps a day to
    its market-regime label, read on the signal day.
    """
    trades = sorted((t for run in runs for t in run.trades), key=lambda t: t.signal_date)
    stats = _trade_stats(trades)
    results = performance(daily)
    output: dict = {
        "signals": sum(run.signals for run in runs),
        **stats,
        "median_trade_return_pct": (
            round(float(np.median([t.return_pct for t in trades])), 2) if trades else None
        ),
        "skipped_overlapping": sum(run.skipped_overlapping for run in runs),
        "skipped_incomplete": sum(run.skipped_incomplete for run in runs),
        **results,
    }

    flags = []
    if len(trades) < FEW_TRADES:
        flags.append("FEW_TRADES")
    if trades and stats["average_trade_return_pct"] <= 0:
        flags.append("NEGATIVE_AFTER_COST")
    for name, series in benchmarks.items():
        aligned = series.reindex(daily.index).fillna(0.0)
        cumulative = round(float((1 + aligned).prod() - 1) * 100, 2) if len(aligned) else None
        output[f"benchmark_{name}_return_pct"] = cumulative
        excess = None
        if cumulative is not None and results["cumulative_return_pct"] is not None:
            excess = round(results["cumulative_return_pct"] - cumulative, 2)
            if excess < 0 and trades:  # no trades: nothing to compare
                flags.append(f"UNDERPERFORMS_{name.upper()}")
        output[f"excess_vs_{name}_pct"] = excess

    output["by_period"] = _grouped(trades, lambda t: period_of(t.signal_date))
    if regimes is not None:
        # The regime needs 200 closes; a signal before that is counted as "Undefined".
        output["by_regime"] = _grouped(
            trades, lambda t: regimes.get(pd.Timestamp(t.signal_date)) or "Undefined"
        )
    output["sample_warning"] = sample_warning(len(trades))
    output["flags"] = flags
    latest = sorted(trades, key=lambda t: (t.signal_date, t.ticker), reverse=True)[:sample_size]
    output["trade_sample"] = [{k: asdict(t)[k] for k in SAMPLE_FIELDS} for t in latest]
    return output
