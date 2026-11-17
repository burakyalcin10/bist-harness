"""Quarterly financial statements and the moment each one became public.

Sources (``docs/data_sources.md``):

* statement items: İş Yatırım's public financial-statement service, cumulative values
  per reporting period, with an item code per line;
* publication times: KAP (the public disclosure platform) financial-report disclosures,
  with a timestamp to the second.

Point-in-time rule: a statement may be used from the first trading day whose close comes
after its publication. Published before 18:00 on a trading day: that day. Otherwise the
next trading day. If a period has several financial-report disclosures (corrections),
the first publication counts and the number of later ones is recorded.

Build into the active snapshot:  uv run python -m bist_harness.data.fundamentals build
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from bist_harness.config import REPO_ROOT
from bist_harness.data import snapshot
from bist_harness.errors import DataUnavailableError
from bist_harness.universe import load_universe, normalize_ticker

STATEMENT_URL = (
    "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo"
)
KAP_MEMBER_URL = "https://www.kap.org.tr/tr/api/member/filter/"
KAP_QUERY_URL = "https://www.kap.org.tr/tr/api/disclosure/members/byCriteria"
STATEMENT_LAYOUT = {"industrial": "XI_29", "bank": "UFRS_K", "insurance": "UFRS_K"}
REPORT_SUBJECT = "Finansal Rapor"
MARKET_CLOSE_HOUR = 18
HALF_DAYS_PATH = REPO_ROOT / "data" / "reference" / "half_day_sessions.csv"
FIRST_PERIOD_YEAR, FIRST_PERIOD_QUARTER = 2022, 4
BUILD_HINT = "Run `uv run python -m bist_harness.data.fundamentals build` first."
STATEMENT_COLUMNS = ["ticker", "year", "quarter", "item_code", "item_name", "value"]
CALENDAR_COLUMNS = ["ticker", "year", "quarter", "published_at", "known_from", "revisions"]

GetJson = Callable[[str, dict], Any]
PostJson = Callable[[str, dict], Any]


@dataclass(frozen=True, order=True)
class Period:
    """A reporting period: quarter 1 to 4 ends in March, June, September, December."""

    year: int
    quarter: int

    def __post_init__(self) -> None:
        if self.quarter not in (1, 2, 3, 4):
            raise ValueError(f"quarter must be 1 to 4, got {self.quarter}")

    def __str__(self) -> str:
        return f"{self.year}Q{self.quarter}"

    @property
    def month(self) -> int:
        return self.quarter * 3

    @property
    def end_date(self) -> pd.Timestamp:
        return pd.Timestamp(year=self.year, month=self.month, day=1) + pd.offsets.MonthEnd(0)

    def previous(self) -> Period:
        return (
            Period(self.year - 1, 4) if self.quarter == 1 else Period(self.year, self.quarter - 1)
        )

    def year_earlier(self) -> Period:
        return Period(self.year - 1, self.quarter)


def periods_between(first: Period, last: Period) -> list[Period]:
    periods, current = [], last
    while current >= first:
        periods.append(current)
        current = current.previous()
    return periods[::-1]


def financial_group(ticker: str) -> str:
    """Statement layout of a stock: banks and insurers report in their own formats."""
    universe = load_universe().set_index("ticker")["sector"]
    sector = universe.get(normalize_ticker(ticker), "")
    if sector == "Banking":
        return "bank"
    if sector == "Insurance":
        return "insurance"
    return "industrial"


def _http_get_json(url: str, params: dict) -> Any:
    import httpx

    headers = {"User-Agent": "Mozilla/5.0 (educational research project; CSE-481)"}
    response = httpx.get(url, params=params or None, headers=headers, timeout=60)
    response.raise_for_status()
    return response.json()


def _http_post_json(url: str, body: dict) -> Any:
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "tr",
        "Content-Type": "application/json",
        "Origin": "https://www.kap.org.tr",
        "Referer": "https://www.kap.org.tr/tr/bildirim-sorgu",
    }
    response = httpx.post(url, json=body, headers=headers, timeout=90)
    response.raise_for_status()
    return response.json()


def fetch_statements(
    ticker: str, periods: Sequence[Period], *, get_json: GetJson | None = None
) -> pd.DataFrame:
    """Statement items of the given periods in long form (values are cumulative, in TRY)."""
    get_json = get_json or _http_get_json
    name = normalize_ticker(ticker)
    layout = STATEMENT_LAYOUT[financial_group(name)]
    rows: list[tuple] = []
    ordered = sorted(periods)
    for start in range(0, len(ordered), 4):
        chunk = ordered[start : start + 4]
        params: dict = {"companyCode": name, "exchange": "TRY", "financialGroup": layout}
        for slot in range(4):
            period = chunk[min(slot, len(chunk) - 1)]
            params[f"year{slot + 1}"] = period.year
            params[f"period{slot + 1}"] = period.month
        reply = get_json(STATEMENT_URL, params)
        for item in (reply or {}).get("value") or []:
            label = (item.get("itemDescEng") or item.get("itemDescTr") or "").strip()
            for slot, period in enumerate(chunk, start=1):
                raw = item.get(f"value{slot}")
                if raw in (None, ""):
                    continue
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                rows.append((name, period.year, period.quarter, item["itemCode"], label, value))
    return pd.DataFrame(rows, columns=STATEMENT_COLUMNS)


def fetch_member_oid(ticker: str, *, get_json: GetJson | None = None) -> str | None:
    """KAP member identifier of a stock."""
    reply = (get_json or _http_get_json)(KAP_MEMBER_URL + normalize_ticker(ticker), {})
    return reply[0]["mkkMemberOid"] if reply else None


def fetch_report_disclosures(
    member_oid: str, start: str, end: str, *, post_json: PostJson | None = None
) -> pd.DataFrame:
    """Financial-report disclosures of one company, one request per calendar year."""
    post_json = post_json or _http_post_json
    rows = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        body = {
            "fromDate": max(start, f"{year}-01-01"),
            "toDate": min(end, f"{year}-12-31"),
            "memberType": "IGS",
            "mkkMemberOidList": [member_oid],
            "disclosureClass": "FR",
            "subjectList": [],
            "bdkMemberOidList": [],
            "inactiveMkkMemberOidList": [],
            "term": "",
            "year": "",
            "ruleType": "",
            "period": "",
            "bdkReview": "",
            "disclosureIndexList": [],
            "mainSector": "",
            "sector": "",
            "subSector": "",
            "market": "",
            "index": "",
            "sdkMemberOidList": [],
            "fromSrc": False,
            "srcCategory": "",
            "isLate": "",
        }
        for item in post_json(KAP_QUERY_URL, body) or []:
            subject = (item.get("subject") or "").strip()
            if item.get("disclosureCategory") != "FR" or not subject.startswith(REPORT_SUBJECT):
                continue
            published = pd.to_datetime(
                item.get("publishDate"), format="%d.%m.%Y %H:%M:%S", errors="coerce"
            )
            if pd.isna(published) or not item.get("year") or not item.get("period"):
                continue
            rows.append(
                (
                    published,
                    int(item["year"]),
                    int(item["period"]),
                    subject,
                    item.get("disclosureIndex"),
                )
            )
    table = pd.DataFrame(
        rows, columns=["published_at", "year", "quarter", "subject", "disclosure_index"]
    )
    return table.sort_values("published_at").reset_index(drop=True)


@lru_cache(maxsize=1)
def half_day_closes() -> dict[pd.Timestamp, tuple[int, int]]:
    """Closing time of each half-day session (``data/reference/half_day_sessions.csv``)."""
    if not HALF_DAYS_PATH.is_file():
        return {}
    table = pd.read_csv(HALF_DAYS_PATH, dtype=str)
    return {
        pd.Timestamp(day): (int(close[:2]), int(close[3:5]))
        for day, close in zip(table["date"], table["close"], strict=True)
    }


def known_from(published_at: pd.Timestamp, calendar: pd.DatetimeIndex) -> pd.Timestamp:
    """First trading day whose close comes after the publication (``NaT`` if none).

    The session closes at 18:00, or at the time given for a half-day session (12:30 on
    the eves of the religious holidays and of Republic Day)."""
    if pd.isna(published_at):
        return pd.NaT
    day = published_at.normalize()
    close = half_day_closes().get(day, (MARKET_CLOSE_HOUR, 0))
    after_close = (published_at.hour, published_at.minute) >= close
    later = calendar[calendar > day] if after_close else calendar[calendar >= day]
    return later[0] if len(later) else pd.NaT


def disclosure_calendar(
    ticker: str, reports: pd.DataFrame, calendar: pd.DatetimeIndex
) -> pd.DataFrame:
    """One row per reporting period: first publication, usable-from day, later corrections."""
    rows = []
    for (year, quarter), group in reports.groupby(["year", "quarter"]):
        first = group["published_at"].min()
        rows.append(
            (ticker, int(year), int(quarter), first, known_from(first, calendar), len(group) - 1)
        )
    return pd.DataFrame(rows, columns=CALENDAR_COLUMNS)


def build_fundamentals(
    folder: Path,
    tickers: Sequence[str],
    *,
    first: Period,
    last: Period,
    calendar: pd.DatetimeIndex,
    get_json: GetJson | None = None,
    post_json: PostJson | None = None,
    pause: float = 0.3,
) -> pd.DataFrame:
    """Download statements and publication times into ``folder/fundamentals``.

    Returns the coverage per stock: periods with a statement and periods with a
    publication time. A stock that fails is reported with zeros; the build goes on.
    """
    target = folder / "fundamentals"
    target.mkdir(parents=True, exist_ok=True)
    periods = periods_between(first, last)
    start, end = f"{first.year}-01-01", f"{last.year + 1}-12-31"
    statements, calendars, coverage = [], [], []
    for ticker in tickers:
        name = normalize_ticker(ticker)
        try:
            table = fetch_statements(name, periods, get_json=get_json)
        except Exception:  # noqa: BLE001 - one stock must not stop the build
            table = pd.DataFrame(columns=STATEMENT_COLUMNS)
        try:
            oid = fetch_member_oid(name, get_json=get_json)
            reports = (
                fetch_report_disclosures(oid, start, end, post_json=post_json) if oid else None
            )
            dates = (
                disclosure_calendar(name, reports, calendar)
                if reports is not None and len(reports)
                else pd.DataFrame(columns=CALENDAR_COLUMNS)
            )
        except Exception:  # noqa: BLE001
            dates = pd.DataFrame(columns=CALENDAR_COLUMNS)
        wanted = {(p.year, p.quarter) for p in periods}
        inside = pd.Series(
            [(y, q) in wanted for y, q in zip(dates["year"], dates["quarter"], strict=True)],
            index=dates.index,
            dtype=bool,
        )
        dates = dates[inside]
        statements.append(table)
        calendars.append(dates)
        coverage.append(
            {
                "ticker": name,
                "statements": int(table[["year", "quarter"]].drop_duplicates().shape[0]),
                "published": int(dates["published_at"].notna().sum()),
            }
        )
        time.sleep(pause)

    pd.concat(statements, ignore_index=True).to_parquet(target / "statements.parquet")
    all_dates = pd.concat(calendars, ignore_index=True)
    all_dates["published_at"] = pd.to_datetime(all_dates["published_at"])
    all_dates["known_from"] = pd.to_datetime(all_dates["known_from"])
    all_dates.astype({"year": int, "quarter": int, "revisions": int}).to_parquet(
        target / "calendar.parquet"
    )
    summary = pd.DataFrame(coverage, columns=["ticker", "statements", "published"])
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "sources": {"statements": STATEMENT_URL, "publication_times": KAP_QUERY_URL},
                "first_period": str(first),
                "last_period": str(last),
                "coverage": summary.to_dict("records"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary


def update_publication_times(
    folder: Path,
    *,
    first: Period,
    last: Period,
    calendar: pd.DatetimeIndex,
    get_json: GetJson | None = None,
    post_json: PostJson | None = None,
    pause: float = 5.0,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    time_budget: float | None = None,
) -> list[str]:
    """Fetch publication times for the stocks that have statements but no times yet.

    KAP drops connections when asked too quickly, so each stock is retried with a
    growing wait, and the file is saved after every stock: an interrupted run loses
    nothing and the next run continues. ``time_budget`` (seconds) ends the run early.
    Returns the stocks that are still missing.
    """
    target = folder / "fundamentals"
    stored = pd.read_parquet(target / "calendar.parquet")
    tickers = list(pd.read_parquet(target / "statements.parquet")["ticker"].drop_duplicates())
    wanted = {(p.year, p.quarter) for p in periods_between(first, last)}
    start, end = f"{first.year}-01-01", f"{last.year + 1}-12-31"
    began = time.monotonic()
    missing: list[str] = []
    for ticker in tickers:
        if (stored["ticker"] == ticker).any():
            continue
        if time_budget is not None and time.monotonic() - began > time_budget:
            missing.append(ticker)
            continue
        dates = None
        for attempt in range(retries):
            try:
                oid = fetch_member_oid(ticker, get_json=get_json)
                reports = fetch_report_disclosures(oid, start, end, post_json=post_json)
                dates = disclosure_calendar(ticker, reports, calendar)
                break
            except Exception:  # noqa: BLE001 - retried below
                sleep(pause * (attempt + 2))
        if dates is None or dates.empty:
            missing.append(ticker)
            continue
        inside = pd.Series(
            [(y, q) in wanted for y, q in zip(dates["year"], dates["quarter"], strict=True)],
            index=dates.index,
            dtype=bool,
        )
        stored = pd.concat([stored, dates[inside]], ignore_index=True)
        stored["published_at"] = pd.to_datetime(stored["published_at"])
        stored["known_from"] = pd.to_datetime(stored["known_from"])
        stored = stored.astype({"year": int, "quarter": int, "revisions": int})
        stored.to_parquet(target / "calendar.parquet")
        sleep(pause)
    return missing


# --- The layer rebuilt from KAP report pages (K-055) ----------------------------------

# Metric keys and the XBRL concepts they are read from; several concepts are summed.
CONCEPTS: dict[str, dict[str, tuple[str, ...]]] = {
    "industrial": {
        "current_assets": ("ifrs-full_CurrentAssets",),
        "cash": ("ifrs-full_CashAndCashEquivalents",),
        "short_term_investments": ("kap-fr_CurrentFinancialInvestments",),
        "inventories": ("ifrs-full_Inventories",),
        "total_assets": ("ifrs-full_Assets",),
        "short_term_liabilities": ("ifrs-full_CurrentLiabilities",),
        "short_term_debt": (
            "ifrs-full_ShorttermBorrowings",
            "kap-fr_CurrentPortionOfNoncurrentBorrowings",
        ),
        "long_term_debt": ("ifrs-full_LongtermBorrowings",),
        "equity": ("ifrs-full_Equity",),
        "parent_equity": ("ifrs-full_EquityAttributableToOwnersOfParent",),
        "paid_in_capital": ("ifrs-full_IssuedCapital",),
        "revenue": ("ifrs-full_Revenue",),
        "operating_profit": ("ifrs-full_ProfitLossFromOperatingActivities",),
        "net_profit": ("ifrs-full_ProfitLoss",),
        "parent_net_profit": ("ifrs-full_ProfitLossAttributableToOwnersOfParent",),
        "depreciation": ("ifrs-full_AdjustmentsForDepreciationAndAmortisationExpense",),
        "operating_cash_flow": ("ifrs-full_CashFlowsFromUsedInOperatingActivities",),
    },
    "bank": {
        "total_assets": ("ifrs-full_Assets",),
        "equity": ("ifrs-full_Equity",),
        "parent_equity": ("ifrs-full_Equity",),
        "paid_in_capital": ("ifrs-full_IssuedCapital",),
        "revenue": ("kap-fr_InterestIncomeOrExpense",),  # net interest income
        "net_profit": ("ifrs-full_ProfitLoss",),
        "parent_net_profit": ("ifrs-full_ProfitLossAttributableToOwnersOfParent",),
    },
    "insurance": {
        "total_assets": ("ifrs-full_Assets",),
        "equity": ("ifrs-full_Equity",),
        "parent_equity": ("ifrs-full_Equity",),
        "paid_in_capital": ("ifrs-full_IssuedCapital",),
        "revenue": (  # gross written premiums, non-life and life
            "kap-fr_GrossWrittenPremiumsClassifiedAsNonlifeTechnicalIncome",
            "kap-fr_GrossWrittenPremiumsClassifiedAsLifeTechnicalIncome",
        ),
        "net_profit": ("ifrs-full_ProfitLoss",),
        "parent_net_profit": ("ifrs-full_ProfitLoss",),
    },
}
# suffix of the metric key -> column of the report it is read from
REPORT_COLUMNS = {
    "": "Current Period",
    "@prior": "Previous Period",
    "@q": "Current Period 3 Months",
}
KAP_CALENDAR_COLUMNS = [
    *CALENDAR_COLUMNS,
    "period_start",
    "period_end",
    "disclosure_index",
    "consolidated",
    "unit",
]
KAP_SOURCE = "KAP financial-report disclosures (XBRL pages), https://www.kap.org.tr/tr/Bildirim/"


def report_values(report, group: str) -> tuple[dict[str, tuple[float, str]], Any, Any]:
    """Metric values of one parsed report, and the start and end of its period.

    Returns ``{key: (value, concepts)}`` with keys like ``revenue`` (current period),
    ``revenue@prior`` (the comparative column of the same report) and ``revenue@q`` (the
    quarter alone, where the report has it).
    """
    first: dict[tuple[str, str], float] = {}
    for fact in report.facts:
        if fact.column.part in (None, "Total"):
            first.setdefault((fact.concept, fact.column.label), fact.value)
    values: dict[str, tuple[float, str]] = {}
    for key, concepts in CONCEPTS[group].items():
        for suffix, label in REPORT_COLUMNS.items():
            found = [(c, first[(c, label)]) for c in concepts if (c, label) in first]
            if found:
                values[key + suffix] = (
                    float(sum(v for _, v in found)),
                    "+".join(c for c, _ in found),
                )
    flow = next(
        (f for f in report.facts if f.column.label == "Current Period" and f.column.start),
        None,
    )
    return values, (flow.column.start if flow else None), (flow.column.end if flow else None)


def build_from_kap_reports(
    folder: Path,
    reports: pd.DataFrame,
    *,
    read_page: Callable[[int], str],
    calendar: pd.DatetimeIndex,
    tickers: Sequence[str],
    first: Period = Period(FIRST_PERIOD_YEAR, FIRST_PERIOD_QUARTER),
) -> pd.DataFrame:
    """Write ``folder/fundamentals`` from the KAP financial-report pages.

    Per stock and period the consolidated report is used when there is one, otherwise
    the solo report; of that kind the first publication counts and later ones are
    counted as corrections. A listed stock without any report stops the build.
    """
    from bist_harness.data.kap_report_parser import parse_report

    wanted = [normalize_ticker(t) for t in tickers]
    missing = [t for t in wanted if not (reports["ticker"] == t).any()]
    if missing:
        raise DataUnavailableError(f"No KAP financial report listed for {', '.join(missing)}.")
    target = folder / "fundamentals"
    target.mkdir(parents=True, exist_ok=True)
    statements, dates = [], []
    for (ticker, year, quarter), group in reports.groupby(["ticker", "year", "quarter"]):
        if ticker not in wanted or Period(int(year), int(quarter)) < first:
            continue
        parsed = [
            (row, parse_report(read_page(int(row.disclosure_index))))
            for row in group.sort_values("published_at").itertuples()
        ]
        pool = [p for p in parsed if p[1].consolidated is True] or parsed
        chosen, report = pool[0]
        values, start, end = report_values(report, financial_group(ticker))
        statements += [
            (ticker, int(year), int(quarter), key, concepts, value)
            for key, (value, concepts) in values.items()
        ]
        published = pd.Timestamp(chosen.published_at)
        dates.append(
            (
                ticker,
                int(year),
                int(quarter),
                published,
                known_from(published, calendar),
                len(pool) - 1,
                pd.Timestamp(start) if start else pd.NaT,
                pd.Timestamp(end) if end else pd.NaT,
                int(chosen.disclosure_index),
                bool(report.consolidated),
                float(report.unit),
            )
        )
    table = pd.DataFrame(statements, columns=STATEMENT_COLUMNS)
    table.to_parquet(target / "statements.parquet")
    calendar_table = pd.DataFrame(dates, columns=KAP_CALENDAR_COLUMNS)
    calendar_table.to_parquet(target / "calendar.parquet")
    coverage = (
        calendar_table.groupby("ticker")
        .agg(periods=("year", "size"), consolidated=("consolidated", "sum"))
        .reset_index()
    )
    (target / "manifest.json").write_text(
        json.dumps(
            {
                "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "sources": {"statements": KAP_SOURCE, "publication_times": KAP_QUERY_URL},
                "first_period": str(first),
                "rule": "consolidated report if any, else solo; first publication of that kind",
                "coverage": coverage.to_dict("records"),
            },
            indent=2,
            default=int,
        ),
        encoding="utf-8",
    )
    return coverage


def _path(name: str, snapshot_id: str | None, root: Path | None) -> Path:
    snapshot_id = snapshot_id or snapshot.active_snapshot_id(root)
    path = snapshot._root(root) / snapshot_id / "fundamentals" / name
    if not path.is_file():
        raise DataUnavailableError(f"Snapshot {snapshot_id} has no fundamental data. {BUILD_HINT}")
    return path


def load_statements(
    ticker: str | None = None, *, snapshot_id: str | None = None, root: Path | None = None
) -> pd.DataFrame:
    """Statement items of one stock (or of all) from a snapshot."""
    table = pd.read_parquet(_path("statements.parquet", snapshot_id, root))
    if ticker is None:
        return table
    return table[table["ticker"] == normalize_ticker(ticker)].reset_index(drop=True)


def load_disclosure_calendar(
    *, snapshot_id: str | None = None, root: Path | None = None
) -> pd.DataFrame:
    """Publication time and usable-from day of every reporting period in the snapshot."""
    return pd.read_parquet(_path("calendar.parquet", snapshot_id, root))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] not in (["build"], ["times"], ["build-kap"]):
        print(
            "usage: python -m bist_harness.data.fundamentals build-kap | build | times "
            "[pause] [seconds]"
        )
        return 2
    folder = snapshot._root(None) / snapshot.active_snapshot_id()
    calendar = snapshot.load_history("XU100").index
    if args[:1] == ["build-kap"]:
        from bist_harness.data import kap_reports

        source = kap_reports.report_folder()
        reports = pd.read_parquet(source / "reports.parquet")
        old, kept = folder / "fundamentals", folder / "fundamentals_isyatirim"
        if old.is_dir() and not kept.exists():
            old.rename(kept)  # the restated-source layer stays for comparison
        coverage = build_from_kap_reports(
            folder,
            reports,
            read_page=lambda index: kap_reports.read_page(source / "pages", index),
            calendar=calendar,
            tickers=list(load_universe()["ticker"]),
        )
        print(coverage.to_string(index=False))
        print("now run: uv run python -m bist_harness.data.snapshot seal")
        return 0
    today = pd.Timestamp.today()
    last = Period(today.year, (today.month - 1) // 3 or 4)
    if today.month <= 3:
        last = Period(today.year - 1, 4)
    if args[:1] == ["times"]:
        left = update_publication_times(
            folder,
            first=Period(FIRST_PERIOD_YEAR, FIRST_PERIOD_QUARTER),
            last=last,
            calendar=calendar,
            pause=float(args[1]) if len(args) > 1 else 5.0,
            time_budget=float(args[2]) if len(args) > 2 else None,
        )
        print("still missing:", left)
        return 1 if left else 0
    summary = build_fundamentals(
        folder,
        list(load_universe()["ticker"]),
        first=Period(FIRST_PERIOD_YEAR, FIRST_PERIOD_QUARTER),
        last=last,
        calendar=calendar,
    )
    print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
