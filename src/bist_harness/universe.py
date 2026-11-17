"""The frozen study universe: 30 BIST 100 stocks and their simplified sectors."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_PATH = REPO_ROOT / "data" / "reference" / "universe.csv"
COLUMNS = ["ticker", "yahoo_symbol", "sector"]


def normalize_ticker(ticker: str) -> str:
    """Upper-case a ticker and drop surrounding spaces and the Yahoo ``.IS`` suffix."""
    t = ticker.strip().upper()
    return t[:-3] if t.endswith(".IS") else t


def load_universe(path: Path | None = None) -> pd.DataFrame:
    """Return the universe as a DataFrame with columns ticker, yahoo_symbol, sector."""
    df = pd.read_csv(path or UNIVERSE_PATH, dtype=str, keep_default_na=False)
    return df[COLUMNS].copy()


@lru_cache(maxsize=1)
def _tickers() -> frozenset[str]:
    return frozenset(load_universe()["ticker"])


def is_in_universe(ticker: str) -> bool:
    """True when the ticker (any case, with or without .IS) is one of the 30 stocks."""
    return normalize_ticker(ticker) in _tickers()
