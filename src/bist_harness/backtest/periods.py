"""Research periods and the market-regime label (project brief, sections 18 and 34).

Rules are developed on the discovery period and checked once on the test period. The
dates are fixed in ``docs/preregistration.md`` before any test-period result is produced.
"""

from __future__ import annotations

import pandas as pd

DISCOVERY = ("2020-01-01", "2024-12-31")
TEST = ("2025-01-01", "2026-11-13")
PERIODS = {"discovery": DISCOVERY, "test": TEST}
REGIME_WINDOW = 200


def period_of(day) -> str | None:
    """Name of the period a day belongs to, or ``None`` when it is outside both."""
    moment = pd.Timestamp(day)
    for name, (start, end) in PERIODS.items():
        if pd.Timestamp(start) <= moment <= pd.Timestamp(end):
            return name
    return None


def split_period(start: str, end: str) -> dict[str, tuple[str, str]]:
    """Cut a requested range into the parts that fall into each research period."""
    parts: dict[str, tuple[str, str]] = {}
    for name, (first, last) in PERIODS.items():
        part_start, part_end = max(start, first), min(end, last)
        if part_start <= part_end:
            parts[name] = (part_start, part_end)
    return parts


def market_regime(benchmark_close: pd.Series) -> pd.Series:
    """ "Uptrend" when the benchmark closes above its 200-day average, else "Downtrend".

    Undefined (``None``) until 200 closes exist. Uses closes up to each day only.
    """
    average = benchmark_close.rolling(REGIME_WINDOW).mean()
    regime = pd.Series("Downtrend", index=benchmark_close.index, dtype=object)
    regime[benchmark_close > average] = "Uptrend"
    regime[average.isna()] = None
    return regime
