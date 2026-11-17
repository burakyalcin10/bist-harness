"""Technical reversal events (project brief, sections 8 and 13).

Definitions follow the instructor's Scenario 3 script so that results are directly
comparable with the course material. Only the lower-Bollinger reversal is implemented
in Sprint 1; the other event families are added in Sprint 2.
"""

from __future__ import annotations

import pandas as pd

VERY_SMALL_SAMPLE = "Very small sample size"
LIMITED_SAMPLE = "Limited sample size"


def sample_warning(event_count: int) -> str | None:
    """Sample-size warning used across event tools (instructor thresholds: 5 and 20)."""
    if event_count < 5:
        return VERY_SMALL_SAMPLE
    if event_count < 20:
        return LIMITED_SAMPLE
    return None


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
    today's close is back above today's lower band. The event is known at the close of
    day t and uses data up to t only. The forward return runs from the close of day t
    to the close ``forward_days`` trading days later; events without that much future
    data are left out, as in the instructor's script.

    ``since`` keeps only events on or after that date while still letting earlier rows
    warm up the bands.
    """
    close = df["Close"]
    middle = close.rolling(window).mean()
    lower = middle - num_std * close.rolling(window).std()
    is_event = (close.shift(1) <= lower.shift(1)) & (close > lower)
    forward_return = close.shift(-forward_days) / close - 1
    returns = forward_return[is_event].dropna()
    if since is not None:
        returns = returns[returns.index >= pd.Timestamp(since)]

    count = int(len(returns))
    summary: dict = {
        "event_count": count,
        "successful_events": 0,
        "success_rate_pct": None,
        "average_forward_return_pct": None,
        "median_forward_return_pct": None,
        "sample_warning": sample_warning(count),
    }
    if count:
        successful = int((returns > success_threshold).sum())
        summary.update(
            successful_events=successful,
            success_rate_pct=round(float(successful / count * 100), 2),
            average_forward_return_pct=round(float(returns.mean() * 100), 2),
            median_forward_return_pct=round(float(returns.median() * 100), 2),
        )
    if return_event_dates:
        summary["event_dates"] = list(returns.index)
    return summary
