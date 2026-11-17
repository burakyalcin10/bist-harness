"""Daily market data with an on-disk snapshot cache.

Mirrors ``load_stock_data`` from the instructor's example scripts (yfinance,
``auto_adjust=True``, flattened columns) and adds a Parquet snapshot so that an analysis
can be repeated offline and always sees the same data until an explicit refresh.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from bist_harness.config import Settings
from bist_harness.errors import DataUnavailableError
from bist_harness.universe import normalize_ticker

OHLCV = ["Open", "High", "Low", "Close", "Volume"]
DATA_SOURCE = "Yahoo Finance via yfinance, auto_adjust=True"

Downloader = Callable[[str, str, str | None], pd.DataFrame]


def _yfinance_download(symbol: str, start: str, end: str | None) -> pd.DataFrame:
    """Download daily bars; ``end`` is inclusive here (yfinance treats it as exclusive)."""
    import yfinance as yf

    exclusive_end = None
    if end is not None:
        exclusive_end = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    return yf.download(symbol, start=start, end=exclusive_end, auto_adjust=True, progress=False)


def load_stock_data(
    ticker: str,
    start: str,
    end: str | None = None,
    *,
    cache_dir: Path | None = None,
    refresh: bool = False,
    downloader: Downloader | None = None,
) -> pd.DataFrame:
    """Return daily OHLCV for ``ticker`` between ``start`` and ``end`` (both inclusive).

    The first call downloads and writes ``<TICKER>_<start>_<end|latest>.parquet``; later
    calls read that snapshot. ``refresh=True`` downloads again and overwrites it.
    """
    symbol_ticker = normalize_ticker(ticker)
    cache_dir = cache_dir or Settings.from_env().data_dir / "cache"
    snapshot = cache_dir / f"{symbol_ticker}_{start}_{end or 'latest'}.parquet"

    if snapshot.is_file() and not refresh:
        return pd.read_parquet(snapshot)

    raw = (downloader or _yfinance_download)(f"{symbol_ticker}.IS", start, end)
    if raw is None or raw.empty:
        raise DataUnavailableError(f"no market data for {symbol_ticker} from {start}")

    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    df = df[OHLCV].dropna().sort_index()
    if end is not None:
        df = df.loc[: pd.Timestamp(end)]
    if df.empty:
        raise DataUnavailableError(f"no market data for {symbol_ticker} from {start}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(snapshot)
    return pd.read_parquet(snapshot)
