"""Financial-report pages from KAP: the source of as-published statement figures (K-055).

Each financial-report disclosure on KAP carries the statements as XBRL-tagged HTML, with
the current period and the comparative period side by side, the presentation unit and
whether the report is consolidated. This module lists those disclosures and downloads
their pages; ``data/kap_report_parser.py`` reads the figures.

KAP drops connections when asked too quickly, so every request is followed by a pause,
failed requests are retried with growing waits, and both steps resume where they
stopped: the listing is cached per stock and calendar year, pages already saved are not
downloaded again.

    uv run python -m bist_harness.data.kap_reports download [pause_seconds]
"""

from __future__ import annotations

import gzip
import json
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from bist_harness.config import Settings
from bist_harness.data import fundamentals
from bist_harness.errors import DataUnavailableError
from bist_harness.universe import load_universe, normalize_ticker

REPORT_PAGE_URL = "https://www.kap.org.tr/tr/Bildirim/"
LIST_COLUMNS = ["ticker", "published_at", "year", "quarter", "disclosure_index"]
DOWNLOAD_HINT = "Run `uv run python -m bist_harness.data.kap_reports download` first."

GetPage = Callable[[int], bytes]
Sleep = Callable[[float], None]


def _http_get_page(index: int) -> bytes:
    import httpx

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    response = httpx.get(f"{REPORT_PAGE_URL}{int(index)}", headers=headers, timeout=120)
    response.raise_for_status()
    return response.content


def _with_retries(call: Callable[[], Any], *, sleep: Sleep, pause: float, retries: int) -> Any:
    """Run ``call``; on failure wait longer each time; after success wait ``pause``."""
    for attempt in range(retries):
        try:
            result = call()
        except Exception:  # noqa: BLE001 - network errors of any kind are retried
            if attempt == retries - 1:
                raise
            sleep(pause * (attempt + 2))
            continue
        sleep(pause)
        return result
    raise AssertionError("unreachable")


def list_reports(
    tickers: Sequence[str],
    start: str,
    end: str,
    *,
    cache_file: Path,
    get_json: fundamentals.GetJson | None = None,
    post_json: fundamentals.PostJson | None = None,
    sleep: Sleep = time.sleep,
    pause: float = 15.0,
    retries: int = 3,
) -> pd.DataFrame:
    """Financial-report disclosures of every stock, one KAP request per stock and year.

    The cache is written after every request. A stock whose KAP member id cannot be
    found stops the listing: a silent gap would drop the stock from every study.
    """
    cache: dict[str, Any] = json.loads(cache_file.read_text()) if cache_file.is_file() else {}

    def save() -> None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, indent=1), encoding="utf-8")

    rows: list[tuple] = []
    for raw in tickers:
        ticker = normalize_ticker(raw)
        entry = cache.setdefault(ticker, {"oid": None, "years": {}})
        if not entry["oid"]:
            oid = _with_retries(
                lambda t=ticker: fundamentals.fetch_member_oid(t, get_json=get_json),
                sleep=sleep,
                pause=pause,
                retries=retries,
            )
            if not oid:
                raise DataUnavailableError(f"KAP has no member id for {ticker}.")
            entry["oid"] = oid
            save()
        for year in range(int(start[:4]), int(end[:4]) + 1):
            key = str(year)
            if key not in entry["years"]:
                first, last = max(start, f"{year}-01-01"), min(end, f"{year}-12-31")
                table = _with_retries(
                    lambda o=entry["oid"], a=first, b=last: fundamentals.fetch_report_disclosures(
                        o, a, b, post_json=post_json
                    ),
                    sleep=sleep,
                    pause=pause,
                    retries=retries,
                )
                entry["years"][key] = [
                    {
                        "published_at": str(r.published_at),
                        "year": int(r.year),
                        "quarter": int(r.quarter),
                        "disclosure_index": int(r.disclosure_index),
                    }
                    for r in table.itertuples()
                ]
                save()
            for item in entry["years"][key]:
                rows.append(
                    (
                        ticker,
                        pd.Timestamp(item["published_at"]),
                        item["year"],
                        item["quarter"],
                        item["disclosure_index"],
                    )
                )
    table = pd.DataFrame(rows, columns=LIST_COLUMNS)
    order = {normalize_ticker(t): i for i, t in enumerate(tickers)}
    table["_order"] = table["ticker"].map(order)
    table = table.sort_values(["_order", "published_at"], kind="stable")
    return table.drop(columns="_order").reset_index(drop=True)


def page_path(folder: Path, disclosure_index: int) -> Path:
    return folder / f"{int(disclosure_index)}.html.gz"


def download_pages(
    indices: Iterable[int],
    folder: Path,
    *,
    get_page: GetPage | None = None,
    sleep: Sleep = time.sleep,
    pause: float = 15.0,
    retries: int = 3,
    progress: Callable[[str], None] | None = None,
) -> list[int]:
    """Save every page as gzip; skip saved pages; return the ones that kept failing."""
    get_page = get_page or _http_get_page
    folder.mkdir(parents=True, exist_ok=True)
    failed: list[int] = []
    for index in indices:
        path = page_path(folder, index)
        if path.is_file():
            continue
        try:
            content = _with_retries(
                lambda i=index: get_page(int(i)), sleep=sleep, pause=pause, retries=retries
            )
        except Exception as error:  # noqa: BLE001 - reported, the run goes on
            failed.append(int(index))
            if progress:
                progress(f"failed {index}: {type(error).__name__}")
            continue
        partial = path.with_suffix(".part")
        partial.write_bytes(gzip.compress(content))
        partial.replace(path)
        if progress:
            progress(f"saved {index} ({len(content)} bytes)")
    return failed


def read_page(folder: Path, disclosure_index: int) -> str:
    """Text of a saved page."""
    path = page_path(folder, disclosure_index)
    if not path.is_file():
        raise DataUnavailableError(
            f"KAP report {disclosure_index} is not downloaded. {DOWNLOAD_HINT}"
        )
    return gzip.decompress(path.read_bytes()).decode("utf-8", errors="replace")


def report_folder(root: Path | None = None) -> Path:
    """Where pages and the listing live (outside git, shared by every snapshot)."""
    return (root or Settings.from_env().data_dir / "cache") / "kap_reports"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] != ["download"]:
        print("usage: python -m bist_harness.data.kap_reports download [pause_seconds]")
        return 2
    pause = float(args[1]) if len(args) > 1 else 15.0
    folder = report_folder()
    first = fundamentals.Period(fundamentals.FIRST_PERIOD_YEAR, fundamentals.FIRST_PERIOD_QUARTER)
    start = (first.end_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    end = pd.Timestamp.today().strftime("%Y-%m-%d")
    tickers = list(load_universe()["ticker"])
    reports = list_reports(tickers, start, end, cache_file=folder / "list.json", pause=pause)
    wanted = reports[
        [
            fundamentals.Period(int(y), int(q)) >= first
            for y, q in zip(reports["year"], reports["quarter"], strict=True)
        ]
    ]
    wanted.to_parquet(folder / "reports.parquet")
    print(f"{len(wanted)} report disclosures for {wanted['ticker'].nunique()} stocks", flush=True)
    failed = download_pages(
        wanted["disclosure_index"].tolist(),
        folder / "pages",
        pause=pause,
        progress=lambda line: print(line, flush=True),
    )
    print("failed:", failed, flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
