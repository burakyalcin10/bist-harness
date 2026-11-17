"""Support and resistance levels (project brief, section 13; week 1 slides).

A pivot is the highest high (or lowest low) of a centred window of ``2 * window + 1``
days. A centred window looks ``window`` days ahead, so a pivot is only *known*
``window`` trading days after it happened; levels for an analysis date use only pivots
known by then. Pivots within ``tolerance`` of each other form one level.

Strength (week 1 slides):
    touches * 1.0 + recent_touches * 1.5 + high_volume_reactions * 1.2 + reversal_strength
where ``reversal_strength`` is the average move away from the level, in percent, over
the ``window`` days after each touch.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_ROWS = 30
RECENT_DAYS = 60
VOLUME_WINDOW = 20
HIGH_VOLUME_RATIO = 1.5


def find_pivots(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Mark pivot highs and lows and the day from which each one is known."""
    span = 2 * window + 1
    highest = df["High"].rolling(span, center=True).max()
    lowest = df["Low"].rolling(span, center=True).min()
    known_from = pd.Series(df.index, index=df.index).shift(-window)
    return pd.DataFrame(
        {
            "pivot_high": (df["High"] == highest) & highest.notna(),
            "pivot_low": (df["Low"] == lowest) & lowest.notna(),
            "known_from": known_from,
        },
        index=df.index,
    )


def _clusters(prices: list[float], tolerance: float) -> list[list[int]]:
    """Group sorted prices: a price joins a cluster while it is within tolerance of its mean."""
    order = np.argsort(prices)
    groups: list[list[int]] = []
    for position in order:
        price = prices[position]
        if groups:
            mean = float(np.mean([prices[i] for i in groups[-1]]))
            if abs(price - mean) / mean <= tolerance:
                groups[-1].append(int(position))
                continue
        groups.append([int(position)])
    return groups


def find_support_resistance(
    df: pd.DataFrame,
    *,
    window: int = 5,
    tolerance: float = 0.015,
    as_of: str | None = None,
    max_levels: int = 6,
) -> list[dict]:
    """Levels known on ``as_of`` (default: the last day), strongest first."""
    if as_of is not None:
        df = df.loc[: pd.Timestamp(as_of)]
    if len(df) < MIN_ROWS:
        return []

    pivots = find_pivots(df, window)
    close = df["Close"]
    volume_average = df["Volume"].rolling(VOLUME_WINDOW).mean()
    high_volume = df["Volume"] > HIGH_VOLUME_RATIO * volume_average
    close_later = close.shift(-window)
    recent_start = df.index[-min(RECENT_DAYS, len(df))]

    # One record per pivot: price, date, move away from the level, volume reaction.
    records: list[tuple[float, pd.Timestamp, float, bool]] = []
    for day in pivots.index[pivots["pivot_high"]]:
        price = float(df.at[day, "High"])
        records.append((price, day, 1 - float(close_later[day]) / price, bool(high_volume[day])))
    for day in pivots.index[pivots["pivot_low"]]:
        price = float(df.at[day, "Low"])
        records.append((price, day, float(close_later[day]) / price - 1, bool(high_volume[day])))
    if not records:
        return []

    last_close = float(close.iloc[-1])
    levels = []
    for members in _clusters([r[0] for r in records], tolerance):
        touches = [records[i] for i in members]
        level = float(np.mean([t[0] for t in touches]))
        recent = sum(1 for t in touches if t[1] >= recent_start)
        loud = sum(1 for t in touches if t[3])
        reversal = float(np.mean([t[2] for t in touches])) * 100
        levels.append(
            {
                "level": round(level, 2),
                "kind": "support" if level < last_close else "resistance",
                "touches": len(touches),
                "recent_touches": recent,
                "high_volume_reactions": loud,
                "last_touch_date": str(max(t[1] for t in touches).date()),
                "strength": round(len(touches) * 1.0 + recent * 1.5 + loud * 1.2 + reversal, 2),
            }
        )
    levels.sort(key=lambda lv: (-lv["strength"], lv["level"]))
    return levels[:max_levels]
