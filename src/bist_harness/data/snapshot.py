"""Versioned market-data snapshot.

A snapshot is a directory ``data/snapshots/<snapshot_id>/`` with one Parquet file per
symbol and a ``manifest.json``. The file ``data/snapshots/ACTIVE`` names the snapshot the
tools read. Tools never download: a missing snapshot is an error that names the build
command, so an analysis can always be repeated on exactly the same data.

Build:  uv run python -m bist_harness.data.snapshot build
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from bist_harness.config import REPO_ROOT, Settings
from bist_harness.data.market import DATA_SOURCE, OHLCV, Downloader, _yfinance_download
from bist_harness.errors import DataUnavailableError
from bist_harness.universe import normalize_ticker

INDEX_SYMBOLS = {
    "XU100": "XU100.IS",
    "XU030": "XU030.IS",
    "XBANK": "XBANK.IS",
    "XUSIN": "XUSIN.IS",
}
BUILD_HINT = "Run `uv run python -m bist_harness.data.snapshot build` first."
ADJUSTMENTS_PATH = REPO_ROOT / "data" / "reference" / "price_adjustments.csv"
PRICE_COLUMNS = ["Open", "High", "Low", "Close"]


@dataclass(frozen=True)
class SeriesInfo:
    """One manifest entry. ``rows == 0`` means the source returned nothing."""

    symbol: str
    rows: int
    first_date: str
    last_date: str
    sha256: str


@dataclass(frozen=True)
class Manifest:
    snapshot_id: str
    created_at: str
    source: str
    start: str
    series: tuple[SeriesInfo, ...]


def _root(root: Path | None) -> Path:
    return root or Settings.from_env().data_dir / "snapshots"


def _clean(raw: pd.DataFrame | None) -> pd.DataFrame:
    """Flatten yfinance columns and keep complete, sorted OHLCV rows."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=OHLCV)
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    if "Volume" in df.columns:
        df["Volume"] = df["Volume"].fillna(0.0)
    df = df[OHLCV].astype(float).dropna().sort_index()
    df.index.name = "Date"
    return df


def _content_hash(df: pd.DataFrame) -> str:
    """Hash of the dates and values, independent of how the file encodes them.

    Dates enter as text and values as 64-bit floats, so the hash is the same before
    writing and after reading back, whatever time unit or index name Parquet keeps.
    """
    digest = hashlib.sha256()
    digest.update(",".join(pd.DatetimeIndex(df.index).strftime("%Y-%m-%d")).encode("ascii"))
    digest.update(np.ascontiguousarray(df[OHLCV].to_numpy(dtype="float64")).tobytes())
    return digest.hexdigest()


def build_snapshot(
    symbols: Iterable[str],
    *,
    start: str = "2020-01-01",
    snapshot_id: str | None = None,
    root: Path | None = None,
    downloader: Downloader | None = None,
) -> Manifest:
    """Download every symbol once, write the snapshot and make it the active one.

    A symbol that fails or returns nothing is listed in the manifest with ``rows == 0``
    and gets no file; the build goes on.
    """
    root = _root(root)
    snapshot_id = snapshot_id or datetime.now().strftime("%Y%m%d-%H%M")
    folder = root / snapshot_id
    folder.mkdir(parents=True, exist_ok=True)
    download = downloader or _yfinance_download

    series: list[SeriesInfo] = []
    for symbol in symbols:
        name = normalize_ticker(symbol)
        try:
            df = _clean(download(INDEX_SYMBOLS.get(name, f"{name}.IS"), start, None))
        except Exception:  # noqa: BLE001 - one bad symbol must not stop the build
            df = pd.DataFrame(columns=OHLCV)
        if df.empty:
            series.append(SeriesInfo(name, 0, "", "", ""))
            continue
        df.to_parquet(folder / f"{name}.parquet")
        series.append(
            SeriesInfo(
                name,
                int(len(df)),
                str(df.index[0].date()),
                str(df.index[-1].date()),
                _content_hash(df),
            )
        )

    manifest = Manifest(
        snapshot_id=snapshot_id,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        source=DATA_SOURCE,
        start=start,
        series=tuple(series),
    )
    (folder / "manifest.json").write_text(
        json.dumps(asdict(manifest), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (root / "ACTIVE").write_text(snapshot_id + "\n", encoding="utf-8")
    return manifest


def active_snapshot_id(root: Path | None = None) -> str:
    pointer = _root(root) / "ACTIVE"
    if not pointer.is_file():
        raise DataUnavailableError(f"No market-data snapshot has been built. {BUILD_HINT}")
    return pointer.read_text(encoding="utf-8").strip()


def load_manifest(snapshot_id: str | None = None, root: Path | None = None) -> Manifest:
    snapshot_id = snapshot_id or active_snapshot_id(root)
    path = _root(root) / snapshot_id / "manifest.json"
    if not path.is_file():
        raise DataUnavailableError(f"Snapshot {snapshot_id} has no manifest. {BUILD_HINT}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    series = tuple(SeriesInfo(**entry) for entry in raw["series"])
    # Keys this version does not know (notes added later) are ignored, not fatal.
    known = {key: raw[key] for key in ("snapshot_id", "created_at", "source", "start")}
    return Manifest(**known, series=series)


def load_adjustments(path: Path | None = None) -> pd.DataFrame:
    """Documented corporate-action corrections: ticker, effective_date, factor, reason.

    The file is checked on every read. A row that could silently distort prices (a
    repeated correction, a mistyped ticker or date, a factor that is not a positive
    number) raises ``ValueError`` instead of being applied or ignored.
    """
    path = path or ADJUSTMENTS_PATH
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    for number, row in enumerate(table.itertuples(index=False), start=2):
        where = f"{path.name} line {number}"
        if not re.fullmatch(r"[A-Z0-9]+", row.ticker):
            raise ValueError(f"{where}: ticker must be upper-case letters and digits")
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row.effective_date):
                raise ValueError
            date.fromisoformat(row.effective_date)
        except ValueError:
            raise ValueError(f"{where}: effective date must be written as YYYY-MM-DD") from None
        try:
            factor = float(row.factor)
        except ValueError:
            factor = float("nan")
        if not 0 < factor < float("inf"):
            raise ValueError(f"{where}: factor must be a positive number")
    repeated = table.duplicated(["ticker", "effective_date"])
    if repeated.any():
        row = table[repeated].iloc[0]
        raise ValueError(
            f"{path.name}: duplicate correction for {row['ticker']} on {row['effective_date']}"
        )
    return table


def adjustments_id(path: Path | None = None) -> str:
    """Short hash of the corrections file; part of the identity of every tool result."""
    content = (path or ADJUSTMENTS_PATH).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()[:8]


def verify_snapshot(snapshot_id: str | None = None, root: Path | None = None) -> list[str]:
    """Compare every stored series with the hash in the manifest; return the problems."""
    manifest = load_manifest(snapshot_id, root)
    folder = _root(root) / manifest.snapshot_id
    problems = []
    for entry in manifest.series:
        if entry.rows == 0:
            continue
        path = folder / f"{entry.symbol}.parquet"
        if not path.is_file():
            problems.append(f"{entry.symbol}: file missing")
        elif _content_hash(pd.read_parquet(path)) != entry.sha256:
            problems.append(f"{entry.symbol}: content changed")
    return problems


def _apply_adjustments(df: pd.DataFrame, name: str, path: Path | None) -> pd.DataFrame:
    """Divide prices before each effective date by the factor (and scale volume up).

    The stored snapshot stays exactly as the source delivered it; the correction is
    applied on read, from a reviewed file, so it is visible and reversible.
    """
    table = load_adjustments(path)
    rows = table[table["ticker"] == name]
    if rows.empty:
        return df
    df = df.copy()
    for _, row in rows.iterrows():
        earlier = df.index < pd.Timestamp(row["effective_date"])
        factor = float(row["factor"])
        df.loc[earlier, PRICE_COLUMNS] = df.loc[earlier, PRICE_COLUMNS] / factor
        df.loc[earlier, "Volume"] = df.loc[earlier, "Volume"] * factor
    return df


def load_history(
    symbol: str,
    *,
    snapshot_id: str | None = None,
    root: Path | None = None,
    adjust: bool = True,
    adjustments_path: Path | None = None,
) -> pd.DataFrame:
    """Daily OHLCV of one stock or index from a snapshot (the active one by default).

    ``adjust=False`` returns the series exactly as stored.
    """
    snapshot_id = snapshot_id or active_snapshot_id(root)
    name = normalize_ticker(symbol)
    path = _root(root) / snapshot_id / f"{name}.parquet"
    if not path.is_file():
        raise DataUnavailableError(f"Snapshot {snapshot_id} has no data for {name}. {BUILD_HINT}")
    df = pd.read_parquet(path)
    return _apply_adjustments(df, name, adjustments_path) if adjust else df


def default_symbols() -> list[str]:
    """Everything a full build holds: universe, reference stocks and the four indices."""
    from bist_harness.data.peers import all_symbols

    return [*all_symbols(), *INDEX_SYMBOLS]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["verify"]:
        problems = verify_snapshot()
        if not problems:
            print("snapshot matches its manifest")
            return 0
        print(f"{len(problems)} series do not match the manifest, e.g. {problems[:5]}")
        return 1
    if args[:1] != ["build"]:
        print("usage: python -m bist_harness.data.snapshot build | verify")
        return 2
    manifest = build_snapshot(default_symbols())
    empty = [s.symbol for s in manifest.series if s.rows == 0]
    print(f"snapshot {manifest.snapshot_id}: {len(manifest.series)} symbols, {len(empty)} empty")
    if empty:
        print("empty:", ", ".join(empty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
