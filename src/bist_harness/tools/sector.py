"""Sector relative strength (project brief, sections 6 and 13; Scenario 1).

A stock's lag score is its return over the horizon minus the median return of its peer
group. The group holds the universe stocks of the sector plus reference stocks from
outside the universe; only universe stocks are reported as leaders or laggards.

Nothing after ``as_of`` is used: every series is cut at ``as_of`` first, and the return
runs from the close ``horizon_days`` trading days earlier to the last close on or
before ``as_of``.
"""

from __future__ import annotations

import pandas as pd

from bist_harness.data.peers import MIN_PEERS, PeerGroup
from bist_harness.quality.checks import JUMP_LIMIT

MAX_ROWS = 12
STALE_AFTER_CALENDAR_DAYS = 7


def _window(series: pd.Series | None, as_of: pd.Timestamp, horizon_days: int) -> pd.Series | None:
    """The last ``horizon_days + 1`` closes on or before ``as_of`` (or None if too few)."""
    if series is None:
        return None
    cut = series.loc[:as_of].dropna()
    return cut.iloc[-(horizon_days + 1) :] if len(cut) > horizon_days else None


def _return(window: pd.Series) -> float:
    return float(window.iloc[-1] / window.iloc[0] - 1)


def rank_sector_relative_strength(
    closes: dict[str, pd.Series],
    group: PeerGroup,
    *,
    horizon_days: int,
    as_of: str,
    benchmark: pd.Series | None = None,
) -> dict:
    """Rank the members of ``group`` by return over ``horizon_days`` up to ``as_of``."""
    day = pd.Timestamp(as_of)
    warnings: list[str] = []
    windows: dict[str, pd.Series] = {}
    for ticker in group.members:
        window = _window(closes.get(ticker), day, horizon_days)
        if window is None:
            warnings.append(f"NO_DATA: {ticker} has no {horizon_days}-day history on {as_of}.")
        else:
            windows[ticker] = window

    effective = max((w.index[-1] for w in windows.values()), default=None)
    returns: dict[str, float] = {}
    for ticker, window in windows.items():
        if (effective - window.index[-1]).days > STALE_AFTER_CALENDAR_DAYS:
            last = window.index[-1].date()
            warnings.append(f"STALE_DATA: {ticker} was left out; its last bar is {last}.")
        elif (window.pct_change().abs() > JUMP_LIMIT).any():
            warnings.append(
                f"PRICE_JUMP: {ticker} was left out; a daily move above {JUMP_LIMIT:.0%} in "
                "the window points to an unadjusted corporate action."
            )
        else:
            returns[ticker] = _return(window)

    if effective is not None and (day - effective).days > STALE_AFTER_CALENDAR_DAYS:
        warnings.append(
            f"DATA_ENDS_BEFORE_AS_OF: the latest bar is {effective.date()}; "
            f"the ranking describes that day, not {as_of}."
        )
    median = float(pd.Series(returns).median()) if returns else None
    large_enough = len(returns) >= MIN_PEERS
    if not large_enough:
        warnings.append(
            f"PEER_GROUP_TOO_SMALL: {len(returns)} member(s) with data; a median, a lag "
            f"score and leaders or laggards need at least {MIN_PEERS}."
        )

    benchmark_window = _window(benchmark, day, horizon_days)
    benchmark_return = None if benchmark_window is None else _return(benchmark_window)
    sector_strong = None
    if median is not None and benchmark_return is not None and large_enough:
        sector_strong = median > benchmark_return

    ordered = sorted(returns, key=lambda t: (-returns[t], t))
    members = [
        {
            "ticker": ticker,
            "role": "universe" if ticker in group.universe else "reference",
            "return_pct": round(returns[ticker] * 100, 2),
            "lag_score_pct": (round((returns[ticker] - median) * 100, 2) if large_enough else None),
            "rank": rank,
        }
        for rank, ticker in enumerate(ordered, start=1)
    ]
    own = [row for row in members if row["role"] == "universe"]
    return {
        "sector": group.name,
        "horizon_days": horizon_days,
        "as_of": as_of,
        "effective_date": None if effective is None else str(effective.date()),
        "sector_median_return_pct": None if median is None else round(median * 100, 2),
        "benchmark_return_pct": None
        if benchmark_return is None
        else round(benchmark_return * 100, 2),
        "sector_strong": sector_strong,
        "members": members[:MAX_ROWS],
        "leaders": [row["ticker"] for row in own if large_enough and row["lag_score_pct"] > 0],
        "laggards": [
            row["ticker"] for row in reversed(own) if large_enough and row["lag_score_pct"] < 0
        ],
        "warnings": warnings,
    }
