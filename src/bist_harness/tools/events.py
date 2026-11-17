"""Technical reversal event families (project brief, sections 8 and 13).

Every event is decided at the close of day t with data up to day t only. Five bullish
definitions are the instructor's (Scenario 3 script); their bearish counterparts are
mirror images. Two families are defined here: the middle-band test and the touch of a
support or resistance level.

A forward return runs from the close of the event day to the close ``forward_days``
trading days later. Events too recent to have that much data are counted separately
(``pending_events``) and stay out of the statistics, as in the instructor's script.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from bist_harness.tools.indicators import (
    HIGH_VOLUME_RATIO,
    KAMA_FLAT_SHARE,
    LOW_VOLUME_RATIO,
    RSI_MIN_ROWS,
    RSI_PEAK_LEVEL,
    RSI_TROUGH_LEVEL,
    add_all_indicators,
)
from bist_harness.tools.schemas import REVERSAL_EVENT_TYPES
from bist_harness.tools.support_resistance import find_pivots

EVENT_TYPES: tuple[str, ...] = tuple(REVERSAL_EVENT_TYPES)
DIRECTIONS = ("BULLISH", "BEARISH")
SINGLE_DIRECTION = {
    "BOLLINGER_LOWER_TOUCH": "BULLISH",
    "BOLLINGER_UPPER_TOUCH": "BEARISH",
    "RSI_LOCAL_TROUGH": "BULLISH",
    "RSI_LOCAL_PEAK": "BEARISH",
}
MIDDLE_TEST_DAYS = 5
LEVEL_TOLERANCE = 0.015
LEVEL_PIVOT_WINDOW = 5
LEVEL_LOOKBACK_DAYS = 250
# First bar position on which an event of the family may be counted: the indicator
# behind it has no meaning before that (RSI needs 14 changes and the trough is confirmed
# a day later; the Ichimoku cloud needs both spans: 52 + 26 bars).
FIRST_EVENT_BAR = {"RSI_LOCAL_TROUGH": 16, "RSI_LOCAL_PEAK": 16, "ICHIMOKU_BREAKOUT": 78}
VERY_SMALL_SAMPLE = "Very small sample size"
LIMITED_SAMPLE = "Limited sample size"

DEFINITIONS = {
    "BOLLINGER_LOWER_TOUCH": (
        "Previous close at or below the lower Bollinger band (20-day mean minus 2 standard "
        "deviations) and today's close back above it."
    ),
    "BOLLINGER_UPPER_TOUCH": (
        "Previous close at or above the upper Bollinger band (20-day mean plus 2 standard "
        "deviations) and today's close back below it."
    ),
    "BOLLINGER_MIDDLE_TEST": (
        "The previous 5 closes were all above the middle Bollinger band and today's low "
        "reaches it (bullish); mirrored with the high for bearish. Success means the earlier "
        "trend continued; a failure is counted as a rejection."
    ),
    "RSI_LOCAL_TROUGH": (
        "Yesterday's RSI(14) was lower than the day before and than today, and below 40."
    ),
    "RSI_LOCAL_PEAK": (
        "Yesterday's RSI(14) was higher than the day before and than today, and above 60."
    ),
    "SUPERTREND_FLIP": (
        "Supertrend (10, 3.0) changes from bearish to bullish (bullish) or from bullish to "
        "bearish (bearish)."
    ),
    "KAMA_TURN": (
        "The one-day slope of KAMA (10, 2, 30) turns from zero or negative to positive "
        "(bullish) or from zero or positive to negative (bearish)."
    ),
    "ICHIMOKU_BREAKOUT": (
        "The close moves from inside or below the Ichimoku cloud to above it (bullish) or "
        "from inside or above it to below it (bearish). A rejection is a close back at or "
        "inside the cloud within the forward window."
    ),
    "SUPPORT_RESISTANCE_TOUCH": (
        "First day on which the low comes within 1.5% of a known pivot low of the last 250 "
        "trading days while yesterday's and today's close stay above it (bullish); mirrored "
        "with the high and a pivot high for bearish. A pivot is known 5 trading days after "
        "it happened."
    ),
}


def sample_warning(event_count: int) -> str | None:
    """Sample-size warning used across event tools (instructor thresholds: 5 and 20)."""
    if event_count < 5:
        return VERY_SMALL_SAMPLE
    if event_count < 20:
        return LIMITED_SAMPLE
    return None


def effective_direction(event_type: str, direction: str = "BULLISH") -> str:
    """Direction an event really has; single-direction families ignore the request."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {event_type}")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}")
    return SINGLE_DIRECTION.get(event_type, direction)


def _level_touch(df: pd.DataFrame, bullish: bool) -> pd.Series:
    """First day of each approach to a known pivot level (see DEFINITIONS)."""
    n = len(df)
    pivots = find_pivots(df, LEVEL_PIVOT_WINDOW)
    is_pivot = pivots["pivot_low" if bullish else "pivot_high"].to_numpy()
    extreme = df["Low" if bullish else "High"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    previous_close = np.concatenate([[np.nan], close[:-1]])
    touch = np.zeros(n, dtype=bool)
    for i in np.flatnonzero(is_pivot):
        level = extreme[i]
        first, last = i + LEVEL_PIVOT_WINDOW, min(n, i + LEVEL_LOOKBACK_DAYS + 1)
        if first >= last:
            continue
        days = slice(first, last)
        near = np.abs(extreme[days] - level) <= LEVEL_TOLERANCE * level
        if bullish:
            held = (close[days] > level) & (previous_close[days] > level)
        else:
            held = (close[days] < level) & (previous_close[days] < level)
        touch[days] |= near & held
    first_day = touch & ~np.concatenate([[False], touch[:-1]])
    return pd.Series(first_day, index=df.index)


def event_mask(df: pd.DataFrame, event_type: str, direction: str = "BULLISH") -> pd.Series:
    """Boolean series: True on the days the event occurs. ``df`` has the indicator columns."""
    bullish = effective_direction(event_type, direction) == "BULLISH"
    close = df["Close"]

    if event_type == "BOLLINGER_LOWER_TOUCH":
        mask = (close.shift(1) <= df["BB_Lower"].shift(1)) & (close > df["BB_Lower"])
    elif event_type == "BOLLINGER_UPPER_TOUCH":
        mask = (close.shift(1) >= df["BB_Upper"].shift(1)) & (close < df["BB_Upper"])
    elif event_type == "BOLLINGER_MIDDLE_TEST":
        middle = df["BB_Middle"]
        side = (close > middle) if bullish else (close < middle)
        trend = side.astype(float).shift(1).rolling(MIDDLE_TEST_DAYS).sum() == MIDDLE_TEST_DAYS
        reach = (df["Low"] <= middle) if bullish else (df["High"] >= middle)
        mask = trend & reach
    elif event_type == "RSI_LOCAL_TROUGH":
        rsi = df["RSI"]
        mask = (
            (rsi.shift(1) < rsi.shift(2)) & (rsi.shift(1) < rsi) & (rsi.shift(1) < RSI_TROUGH_LEVEL)
        )
    elif event_type == "RSI_LOCAL_PEAK":
        rsi = df["RSI"]
        mask = (
            (rsi.shift(1) > rsi.shift(2)) & (rsi.shift(1) > rsi) & (rsi.shift(1) > RSI_PEAK_LEVEL)
        )
    elif event_type == "SUPERTREND_FLIP":
        state = df["Supertrend_Direction"]
        before, after = (-1, 1) if bullish else (1, -1)
        mask = (state.shift(1) == before) & (state == after)
    elif event_type == "KAMA_TURN":
        slope = df["KAMA_Slope"]
        if bullish:
            mask = (slope.shift(1) <= 0) & (slope > 0)
        else:
            mask = (slope.shift(1) >= 0) & (slope < 0)
    elif event_type == "ICHIMOKU_BREAKOUT":
        if bullish:
            mask = (close.shift(1) <= df["Cloud_Top"].shift(1)) & (close > df["Cloud_Top"])
        else:
            mask = (close.shift(1) >= df["Cloud_Bottom"].shift(1)) & (close < df["Cloud_Bottom"])
    else:  # SUPPORT_RESISTANCE_TOUCH
        mask = _level_touch(df, bullish)
    return mask.fillna(False).astype(bool)


def counted_mask(df: pd.DataFrame, event_type: str, direction: str = "BULLISH") -> pd.Series:
    """``event_mask`` without the events inside the warm-up of the indicator behind them."""
    mask = event_mask(df, event_type, direction)
    mask.iloc[: FIRST_EVENT_BAR.get(event_type, 0)] = False
    return mask


def _labels(condition_labels: list[tuple[pd.Series, str]], known: pd.Series, default: str):
    """Label series: the first matching condition wins; ``None`` where the input is unknown."""
    out = pd.Series(default, index=known.index, dtype=object)
    for condition, label in reversed(condition_labels):
        out[condition.fillna(False)] = label
    out[~known] = None
    return out


def state_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Market-state labels for every day (the same labels as ``indicator_state``)."""
    rsi, close = df["RSI"], df["Close"]
    trough = (
        (rsi.shift(1) < rsi.shift(2)) & (rsi.shift(1) < rsi) & (rsi.shift(1) < RSI_TROUGH_LEVEL)
    )
    peak = (rsi.shift(1) > rsi.shift(2)) & (rsi.shift(1) > rsi) & (rsi.shift(1) > RSI_PEAK_LEVEL)
    slope = df["KAMA_Slope"]
    flat = slope.abs() < KAMA_FLAT_SHARE * close
    top, bottom = df["Cloud_Top"], df["Cloud_Bottom"]
    cloud_known = df["Senkou_A"].notna() & df["Senkou_B"].notna()
    rsi_known = rsi.notna() & (np.arange(len(df)) >= RSI_MIN_ROWS - 1)
    ratio = df["Volume"] / df["Volume_MA"].where(df["Volume_MA"] != 0)
    direction = df["Supertrend_Direction"]
    return pd.DataFrame(
        {
            "rsi_state": _labels(
                [(trough, "Local Low"), (peak, "Local High")], rsi_known, "Neutral"
            ),
            "supertrend_state": _labels(
                [(direction == 1, "Bullish"), (direction == -1, "Bearish")],
                direction.isin([1, -1]),
                "Bullish",
            ),
            "kama_slope": _labels(
                [(flat, "Flattening"), (slope > 0, "Rising")], slope.notna(), "Falling"
            ),
            "ichimoku_state": _labels(
                [(close > top, "Above Cloud"), (close < bottom, "Below Cloud")],
                cloud_known,
                "In Cloud",
            ),
            "volume_regime": _labels(
                [(ratio > HIGH_VOLUME_RATIO, "High"), (ratio < LOW_VOLUME_RATIO, "Low")],
                ratio.notna(),
                "Normal",
            ),
        },
        index=df.index,
    )


def market_state(df: pd.DataFrame, day) -> dict:
    """Market-state record of one day (section 8): the labels known at that day's close."""
    return state_frame(df).loc[pd.Timestamp(day)].to_dict()


def _forward_return(close: pd.Series, days: int) -> pd.Series:
    return close.shift(-days) / close - 1


def _reversal_strength(df: pd.DataFrame, days: int, bullish: bool) -> pd.Series:
    """Best move in the event's direction within the next ``days`` days, from the close."""
    if bullish:
        best = df["High"][::-1].rolling(days).max()[::-1].shift(-1)
        return best / df["Close"] - 1
    worst = df["Low"][::-1].rolling(days).min()[::-1].shift(-1)
    return 1 - worst / df["Close"]


def _pct(value: float) -> float:
    return round(float(value) * 100, 2)


def summarize_events(
    df: pd.DataFrame,
    mask: pd.Series,
    *,
    direction: str,
    forward_days: int = 5,
    since: str | None = None,
    success_threshold: float = 0.0,
) -> dict:
    """Count the events and describe what followed them.

    Success: a forward return above the threshold for a bullish event, below minus the
    threshold for a bearish one. ``since`` drops earlier events but keeps earlier rows
    for indicator warm-up.
    """
    bullish = direction == "BULLISH"
    forward = _forward_return(df["Close"], forward_days)
    keep = mask & forward.notna()
    if since is not None:
        keep &= df.index >= pd.Timestamp(since)
    returns = forward[keep]
    strength = _reversal_strength(df, forward_days, bullish)[keep]

    count = int(len(returns))
    summary: dict = {
        "event_count": count,
        "successful_events": 0,
        "success_rate_pct": None,
        "average_forward_return_pct": None,
        "median_forward_return_pct": None,
        "average_reversal_strength_pct": None,
        "median_reversal_strength_pct": None,
        "sample_warning": sample_warning(count),
    }
    if count:
        if bullish:
            successful = int((returns > success_threshold).sum())
        else:
            successful = int((returns < -success_threshold).sum())
        summary.update(
            successful_events=successful,
            success_rate_pct=round(successful / count * 100, 2),
            average_forward_return_pct=_pct(returns.mean()),
            median_forward_return_pct=_pct(returns.median()),
            average_reversal_strength_pct=_pct(strength.mean()),
            median_reversal_strength_pct=_pct(strength.median()),
        )
    return summary


def event_records(
    df: pd.DataFrame,
    mask: pd.Series,
    *,
    ticker: str,
    event_type: str,
    direction: str,
    horizons: Sequence[int] = (1, 3, 5, 10),
    since: str | None = None,
    strength_days: int = 5,
) -> pd.DataFrame:
    """One row per event (section 8): market state and forward returns.

    Every event is listed; a forward return that is not available yet is NaN.
    """
    keep = mask.copy()
    if since is not None:
        keep &= df.index >= pd.Timestamp(since)
    days = df.index[keep]
    records = state_frame(df).loc[days].reset_index(drop=True)
    records.insert(0, "date", [str(d.date()) for d in days])
    records.insert(0, "direction", direction)
    records.insert(0, "event", event_type)
    records.insert(0, "ticker", ticker)
    for horizon in horizons:
        values = (_forward_return(df["Close"], horizon)[keep] * 100).round(2)
        records[f"forward_{horizon}d_return_pct"] = values.to_numpy()
    strength = _reversal_strength(df, strength_days, direction == "BULLISH")[keep] * 100
    records["reversal_strength_pct"] = strength.round(2).to_numpy()
    return records


def _cloud_rejections(df: pd.DataFrame, keep: pd.Series, days: int, bullish: bool) -> int:
    """Breakouts followed, within ``days`` days, by a close back at or inside the cloud."""
    if bullish:
        back = df["Close"] <= df["Cloud_Top"]
    else:
        back = df["Close"] >= df["Cloud_Bottom"]
    returned = back.astype(float)[::-1].rolling(days).max()[::-1].shift(-1) > 0
    return int((keep & returned).sum())


def detect_events(
    df: pd.DataFrame,
    event_type: str,
    direction: str = "BULLISH",
    *,
    forward_days: int = 5,
    since: str | None = None,
) -> dict:
    """Detect one event family on raw OHLCV and summarise what followed."""
    actual = effective_direction(event_type, direction)
    frame = add_all_indicators(df)
    mask = counted_mask(frame, event_type, actual)
    in_period = mask if since is None else mask & (frame.index >= pd.Timestamp(since))
    summary = summarize_events(
        frame, mask, direction=actual, forward_days=forward_days, since=since
    )
    evaluated = in_period & _forward_return(frame["Close"], forward_days).notna()
    event_days = frame.index[in_period]
    output = {
        "direction": actual,
        **summary,
        "pending_events": int(in_period.sum()) - summary["event_count"],
        "last_event_date": str(event_days[-1].date()) if len(event_days) else None,
    }
    if event_type == "BOLLINGER_MIDDLE_TEST":
        output["continuation_count"] = summary["successful_events"]
        output["rejection_count"] = summary["event_count"] - summary["successful_events"]
    elif event_type == "ICHIMOKU_BREAKOUT":
        output["rejection_count"] = _cloud_rejections(
            frame, evaluated, forward_days, actual == "BULLISH"
        )
    output["definition"] = DEFINITIONS[event_type]
    return output
