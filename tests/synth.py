"""Synthetic daily OHLCV for tests: a seeded random walk with consistent bars."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ohlcv(
    days: int = 600,
    seed: int = 1,
    *,
    start: str = "2020-01-02",
    drift: float = 0.0005,
    vol: float = 0.025,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, vol, days)))
    open_ = np.concatenate([[100.0], close[:-1]]) * (1 + rng.normal(0, 0.004, days))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.008, days)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.008, days)))
    volume = rng.integers(100_000, 2_000_000, days).astype(float)
    index = pd.date_range(start, periods=days, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=index
    )
