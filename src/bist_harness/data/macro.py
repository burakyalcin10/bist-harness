"""Macro series (project brief, section 15): FX, TCMB policy rate, Fed target, CPI.

Each series carries the date on which a value became public; tools align by that date
and never use a value before it. Sources (details in ``docs/data_sources.md``):

* USD/TRY and EUR/TRY: Yahoo Finance daily closes (EVDS needs an API key);
* TCMB policy rate: the decision table of the "1 Hafta Repo" page;
* Fed funds target range: the Federal Reserve's "Open Market Operations" page;
* CPI: the TCMB "Tüketici Fiyatları" page (TÜİK figures), published on the 3rd of the
  following month or the next working day.

Build into the active snapshot:  uv run python -m bist_harness.data.macro build
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from bist_harness.data import snapshot
from bist_harness.data.market import Downloader, _yfinance_download
from bist_harness.errors import DataUnavailableError

SERIES = ("fx", "policy_rate", "fed_target", "cpi")
FX_SYMBOLS = {"USDTRY": "USDTRY=X", "EURTRY": "EURTRY=X"}
_TCMB = "https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu"
SOURCES = {
    "policy_rate": (
        f"{_TCMB}/Temel+Faaliyetler/Para+Politikasi/Merkez+Bankasi+Faiz+Oranlari/1+Hafta+Repo"
    ),
    "cpi": f"{_TCMB}/Istatistikler/Enflasyon+Verileri/Tuketici+Fiyatlari",
    "fed_target": "https://www.federalreserve.gov/monetarypolicy/openmarket.htm",
    "fx": "Yahoo Finance (USDTRY=X, EURTRY=X), daily close",
}
BUILD_HINT = "Run `uv run python -m bist_harness.data.macro build` first."
CPI_RELEASE_DAY = 3
FX_START = "2020-01-01"
USER_AGENT = "Mozilla/5.0 (educational research project; CSE-481)"

Fetcher = Callable[[str], str]


def _http_get(url: str) -> str:
    import httpx

    response = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)
    response.raise_for_status()
    return response.text


def parse_policy_rate(html: str) -> pd.DataFrame:
    """Decision table of the one-week repo rate: effective date and lending rate."""
    table = pd.read_html(io.StringIO(html), header=None)[0]
    dates = pd.to_datetime(table.iloc[:, 0], format="%d.%m.%Y", errors="coerce")
    rates = pd.to_numeric(table.iloc[:, -1], errors="coerce")
    out = pd.DataFrame({"effective_date": dates, "rate": rates}).dropna()
    return out.sort_values("effective_date").reset_index(drop=True)


def cpi_publication_date(period) -> pd.Timestamp:
    """Day the CPI of ``period`` became public: the 3rd of the next month, or the next
    working day when that falls on a weekend."""
    month = period if isinstance(period, pd.Period) else pd.Timestamp(period).to_period("M")
    day = (month + 1).to_timestamp() + pd.Timedelta(days=CPI_RELEASE_DAY - 1)
    while day.day_of_week >= 5:
        day += pd.Timedelta(days=1)
    return day


def parse_cpi(html: str) -> pd.DataFrame:
    """Monthly CPI table: month end, annual and monthly change in percent, release date."""
    table = pd.read_html(io.StringIO(html))[0]
    months = pd.PeriodIndex(
        pd.to_datetime(table.iloc[:, 0].astype(str), format="%m-%Y", errors="coerce"), freq="M"
    )
    out = pd.DataFrame(
        {
            "period": months.to_timestamp(how="end").normalize(),
            "annual_pct": pd.to_numeric(table.iloc[:, 1], errors="coerce"),
            "monthly_pct": pd.to_numeric(table.iloc[:, 2], errors="coerce"),
        }
    ).dropna()
    out["published"] = [cpi_publication_date(p) for p in out["period"]]
    return out.sort_values("period").reset_index(drop=True)


_YEAR_HEADING = re.compile(r"<h4[^>]*>\s*(\d{4})\s*</h4>")


def parse_fed_target(html: str) -> pd.DataFrame:
    """Target-range changes: each yearly table sits under a heading that holds the year."""
    headings = list(_YEAR_HEADING.finditer(html))
    rows = []
    for heading, following in zip(headings, [*headings[1:], None], strict=True):
        chunk = html[heading.end() : following.start() if following else len(html)]
        try:
            table = pd.read_html(io.StringIO(chunk))[0]
        except ValueError:  # a heading without a table
            continue
        for label, level in zip(table.iloc[:, 0], table.iloc[:, -1], strict=True):
            day = re.match(r"\s*([A-Za-z]+)\s+(\d{1,2})", str(label))
            bounds = re.findall(r"\d+(?:\.\d+)?", str(level))
            if not day or not bounds:
                continue
            date = pd.to_datetime(
                f"{day[1]} {day[2]} {heading[1]}", format="%B %d %Y", errors="coerce"
            )
            if pd.isna(date):
                continue
            rows.append((date, float(bounds[0]), float(bounds[-1])))
    out = pd.DataFrame(rows, columns=["effective_date", "lower", "upper"])
    return out.sort_values("effective_date").reset_index(drop=True)


def cpi_index(cpi: pd.DataFrame) -> pd.Series:
    """Price index chained from the monthly changes, 100 in the first month of the table.

    Used to put amounts of different dates on one price level (real growth).
    """
    ordered = cpi.sort_values("period")
    growth = 1 + ordered["monthly_pct"].to_numpy() / 100
    growth[0] = 1.0
    return pd.Series(100.0 * growth.cumprod(), index=pd.DatetimeIndex(ordered["period"]))


def _fetch_fx(downloader: Downloader) -> pd.DataFrame:
    columns = {}
    for name, symbol in FX_SYMBOLS.items():
        raw = downloader(symbol, FX_START, None)
        if raw is None or raw.empty:
            continue
        if isinstance(raw.columns, pd.MultiIndex):
            raw = raw.copy()
            raw.columns = raw.columns.get_level_values(0)
        columns[name] = raw["Close"].astype(float)
    frame = pd.DataFrame(columns)
    frame.index = pd.to_datetime(frame.index)
    return frame.dropna().sort_index()


def build_macro(
    folder: Path, *, fetch: Fetcher | None = None, fx_downloader: Downloader | None = None
) -> dict[str, int]:
    """Download the four series into ``folder/macro``; return the rows written per series.

    A source that fails is reported with 0 rows and leaves no file; the others are kept.
    """
    fetch = fetch or _http_get
    target = folder / "macro"
    target.mkdir(parents=True, exist_ok=True)
    parsers = {"policy_rate": parse_policy_rate, "cpi": parse_cpi, "fed_target": parse_fed_target}
    counts: dict[str, int] = {}
    hashes: dict[str, str] = {}
    for name in SERIES:
        try:
            if name == "fx":
                frame = _fetch_fx(fx_downloader or _yfinance_download)
            else:
                frame = parsers[name](fetch(SOURCES[name]))
        except Exception:  # noqa: BLE001 - one source must not stop the build
            frame = pd.DataFrame()
        counts[name] = int(len(frame))
        if frame.empty:
            continue
        frame.to_parquet(target / f"{name}.parquet")
        hashes[name] = hashlib.sha256(frame.to_csv().encode("utf-8")).hexdigest()
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "sources": SOURCES,
                "rows": counts,
                "sha256": hashes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return counts


def load_macro(
    name: str, *, snapshot_id: str | None = None, root: Path | None = None
) -> pd.DataFrame:
    """One macro series from a snapshot (the active one by default)."""
    if name not in SERIES:
        raise ValueError(f"unknown macro series: {name}")
    snapshot_id = snapshot_id or snapshot.active_snapshot_id(root)
    path = snapshot._root(root) / snapshot_id / "macro" / f"{name}.parquet"
    if not path.is_file():
        raise DataUnavailableError(
            f"Snapshot {snapshot_id} has no macro series {name}. {BUILD_HINT}"
        )
    return pd.read_parquet(path)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] != ["build"]:
        print("usage: python -m bist_harness.data.macro build")
        return 2
    folder = snapshot._root(None) / snapshot.active_snapshot_id()
    print(build_macro(folder))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
