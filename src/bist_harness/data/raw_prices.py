"""Unadjusted daily closes, for market values (Sprint 4, Task 0).

The price snapshot holds closes adjusted for dividends and splits (``auto_adjust=True``):
right for returns, wrong for a market value of the time. This layer keeps Yahoo's close
with ``auto_adjust=False`` (not adjusted for dividends, but still divided by every later
split) together with the split events, and undoes the splits:

    raw_close(t) = close(t) x product of the split ratios after day t

so ``raw_close`` is the price quoted on day t. Bonus issues of BIST stocks are recorded
as splits. Build into the active snapshot:

    uv run python -m bist_harness.data.raw_prices build
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from bist_harness.data import snapshot
from bist_harness.universe import load_universe, normalize_ticker

LAYER = "prices_raw"
COLUMNS = ["close", "splits", "raw_close"]
SOURCE = "Yahoo Finance via yfinance, auto_adjust=False, with split events"

Downloader = Callable[[str, str, str | None], pd.DataFrame]


def _yahoo(symbol: str, start: str, end: str | None) -> pd.DataFrame:
    import yfinance as yf

    exclusive = None if end is None else (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    frame = yf.download(
        symbol, start=start, end=exclusive, auto_adjust=False, actions=True, progress=False
    )
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    return frame


def raw_close(frame: pd.DataFrame) -> pd.Series:
    """The quoted close of each day: Yahoo's close times the ratios of later splits."""
    ratios = frame["Stock Splits"].fillna(0.0).where(lambda r: r > 0, 1.0).astype(float)
    later = ratios[::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    return frame["Close"].astype(float) * later


def build_raw_prices(
    folder: Path,
    tickers: Sequence[str],
    *,
    downloader: Downloader = _yahoo,
    start: str = "2020-01-01",
    end: str | None = None,
) -> dict[str, int]:
    """Write ``folder/prices_raw/<TICKER>.parquet`` for each stock; return the rows."""
    target = folder / LAYER
    target.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for raw in tickers:
        ticker = normalize_ticker(raw)
        try:
            frame = downloader(f"{ticker}.IS", start, end)
        except Exception:  # noqa: BLE001 - one stock must not stop the build
            frame = pd.DataFrame()
        if frame is None or frame.empty or "Close" not in frame:
            counts[ticker] = 0
            continue
        if "Stock Splits" not in frame:
            frame = frame.assign(**{"Stock Splits": 0.0})
        table = pd.DataFrame(
            {
                "close": frame["Close"].astype(float),
                "splits": frame["Stock Splits"].fillna(0.0).astype(float),
                "raw_close": raw_close(frame),
            }
        )
        table.index = pd.DatetimeIndex(table.index).tz_localize(None).normalize()
        table.to_parquet(target / f"{ticker}.parquet")
        counts[ticker] = int(len(table))
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "source": SOURCE,
                "start": start,
                "end": end,
                "rows": counts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return counts


def load_raw(
    ticker: str, *, snapshot_id: str | None = None, root: Path | None = None
) -> pd.DataFrame | None:
    """Unadjusted closes of one stock, or ``None`` when the layer does not hold it."""
    snapshot_id = snapshot_id or snapshot.active_snapshot_id(root)
    path = snapshot._root(root) / snapshot_id / LAYER / f"{normalize_ticker(ticker)}.parquet"
    return pd.read_parquet(path)[COLUMNS] if path.is_file() else None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] != ["build"]:
        print("usage: python -m bist_harness.data.raw_prices build")
        return 2
    folder = snapshot._root(None) / snapshot.active_snapshot_id()
    last = str(snapshot.load_history("XU100").index[-1].date())
    counts = build_raw_prices(folder, list(load_universe()["ticker"]), end=last)
    empty = [t for t, n in counts.items() if n == 0]
    print(f"{len(counts)} stocks, {len(empty)} without data {empty}")
    print("now run: uv run python -m bist_harness.data.snapshot seal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
