"""Lower-Bollinger reversal summary (the Sprint 1 thin-slice function).

Kept for its parameters (``window``, ``num_std``, ``success_threshold``); the event
families and the shared statistics live in ``bist_harness.tools.events``.
"""

from __future__ import annotations

import pandas as pd

from bist_harness.tools.events import (  # noqa: F401 - re-exported
    LIMITED_SAMPLE,
    VERY_SMALL_SAMPLE,
    sample_warning,
    summarize_events,
)

_KEYS = (
    "event_count",
    "successful_events",
    "success_rate_pct",
    "average_forward_return_pct",
    "median_forward_return_pct",
    "sample_warning",
)


def bollinger_lower_touch_summary(
    df: pd.DataFrame,
    *,
    window: int = 20,
    num_std: float = 2.0,
    forward_days: int = 5,
    success_threshold: float = 0.0,
    since: str | None = None,
    return_event_dates: bool = False,
) -> dict:
    """Summarise lower-Bollinger reversal events and what followed them.

    Event on day t: the previous close was at or below the previous lower band and
    today's close is back above today's lower band. ``since`` keeps only events on or
    after that date while still letting earlier rows warm up the bands.
    """
    close = df["Close"]
    lower = close.rolling(window).mean() - num_std * close.rolling(window).std()
    is_event = (close.shift(1) <= lower.shift(1)) & (close > lower)
    # Only closes are needed here; the shared summary also reads highs and lows.
    frame = df.assign(High=df.get("High", close), Low=df.get("Low", close))
    full = summarize_events(
        frame,
        is_event,
        direction="BULLISH",
        forward_days=forward_days,
        since=since,
        success_threshold=success_threshold,
    )
    summary = {key: full[key] for key in _KEYS}
    if return_event_dates:
        evaluated = is_event & (close.shift(-forward_days) / close - 1).notna()
        if since is not None:
            evaluated &= df.index >= pd.Timestamp(since)
        summary["event_dates"] = list(df.index[evaluated])
    return summary
