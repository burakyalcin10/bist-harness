"""The fundamental layer rebuilt from KAP report pages (K-055)."""

import pandas as pd
import pytest

from bist_harness.data import fundamentals as fd
from bist_harness.errors import DataUnavailableError

from .test_kap_report_parser import _context, _header_table, _page, _row, _table


def _report(start: str, end: str, prior_start: str, prior_end: str, values: dict, nature: str):
    """A one-statement industrial report: revenue and profit, current and prior columns."""

    def header(a, b):
        return f"{a[8:10]}.{a[5:7]}.{a[:4]} - {b[8:10]}.{b[5:7]}.{b[:4]}"

    income = _table(
        "general_role_310000",
        [
            _context(
                f"Cari Dönem<br/>{header(start, end)}", f"Current Period<br/>{header(start, end)}"
            )
            + _context(
                f"Önceki Dönem<br/>{header(prior_start, prior_end)}",
                f"Previous Period<br/>{header(prior_start, prior_end)}",
            )
        ],
        [
            _row("ifrs-full_Revenue", [str(values["revenue"]), str(values["revenue_prior"])]),
            _row("ifrs-full_ProfitLoss", [str(values["profit"]), str(values["profit_prior"])]),
        ],
    )
    balance = _table(
        "general_role_210015",
        [
            _context(
                f"Cari Dönem<br/>{end[8:10]}.{end[5:7]}.{end[:4]}",
                f"Current Period<br/>{end[8:10]}.{end[5:7]}.{end[:4]}",
            )
            + _context("Önceki Dönem<br/>31.12.2023", "Previous Period<br/>31.12.2023")
        ],
        [_row("ifrs-full_Equity", [str(values["equity"]), "1"])],
    )
    return _page(_header_table("1.000 TL", nature), income, balance)


PAGES = {
    # TUPRS 2024Q3: a solo report first, the consolidated one a minute later, then a correction
    101: _report(
        "2024-01-01",
        "2024-09-30",
        "2023-01-01",
        "2023-09-30",
        {"revenue": 900, "revenue_prior": 600, "profit": 50, "profit_prior": -10, "equity": 700},
        "Konsolide Olmayan",
    ),
    102: _report(
        "2024-01-01",
        "2024-09-30",
        "2023-01-01",
        "2023-09-30",
        {"revenue": 1000, "revenue_prior": 700, "profit": 60, "profit_prior": -5, "equity": 800},
        "Konsolide",
    ),
    103: _report(
        "2024-01-01",
        "2024-09-30",
        "2023-01-01",
        "2023-09-30",
        {"revenue": 1001, "revenue_prior": 700, "profit": 60, "profit_prior": -5, "equity": 800},
        "Konsolide",
    ),
    # MAVI "2024Q4": its fiscal year ends on 31 January 2025
    201: _report(
        "2024-02-01",
        "2025-01-31",
        "2023-02-01",
        "2024-01-31",
        {"revenue": 500, "revenue_prior": 400, "profit": 30, "profit_prior": 20, "equity": 90},
        "Konsolide",
    ),
}
REPORTS = pd.DataFrame(
    [
        ("TUPRS", pd.Timestamp("2024-10-30 18:10:00"), 2024, 3, 101),
        ("TUPRS", pd.Timestamp("2024-10-30 18:11:00"), 2024, 3, 102),
        ("TUPRS", pd.Timestamp("2024-11-20 10:00:00"), 2024, 3, 103),
        ("MAVI", pd.Timestamp("2025-03-18 18:26:35"), 2024, 4, 201),
    ],
    columns=["ticker", "published_at", "year", "quarter", "disclosure_index"],
)
CALENDAR = pd.bdate_range("2024-10-01", "2025-04-30")


def _build(tmp_path, reports=REPORTS, tickers=("TUPRS", "MAVI")):
    return fd.build_from_kap_reports(
        tmp_path, reports, read_page=PAGES.__getitem__, calendar=CALENDAR, tickers=tickers
    )


def test_the_consolidated_report_is_used_and_later_ones_count_as_corrections(tmp_path):
    _build(tmp_path)
    calendar = pd.read_parquet(tmp_path / "fundamentals" / "calendar.parquet")
    row = calendar[calendar["ticker"] == "TUPRS"].iloc[0]
    assert row["disclosure_index"] == 102 and bool(row["consolidated"]) is True
    assert row["published_at"] == pd.Timestamp("2024-10-30 18:11:00")
    assert row["known_from"] == pd.Timestamp("2024-10-31")
    assert row["revisions"] == 1


def test_current_and_prior_columns_come_from_the_same_report(tmp_path):
    _build(tmp_path)
    st = pd.read_parquet(tmp_path / "fundamentals" / "statements.parquet")
    tuprs = st[st["ticker"] == "TUPRS"].set_index("item_code")["value"]
    assert tuprs["revenue"] == 1_000_000.0 and tuprs["revenue@prior"] == 700_000.0
    assert tuprs["net_profit"] == 60_000.0 and tuprs["net_profit@prior"] == -5_000.0
    assert tuprs["equity"] == 800_000.0
    names = st[st["ticker"] == "TUPRS"].set_index("item_code")["item_name"]
    assert names["revenue"] == "ifrs-full_Revenue"


def test_period_dates_come_from_the_report_itself(tmp_path):
    _build(tmp_path)
    calendar = pd.read_parquet(tmp_path / "fundamentals" / "calendar.parquet").set_index("ticker")
    assert calendar.loc["MAVI", "period_end"] == pd.Timestamp("2025-01-31")
    assert calendar.loc["MAVI", "period_start"] == pd.Timestamp("2024-02-01")
    assert calendar.loc["TUPRS", "period_end"] == pd.Timestamp("2024-09-30")


def test_a_stock_with_no_report_stops_the_build(tmp_path):
    with pytest.raises(DataUnavailableError, match="ASELS"):
        _build(tmp_path, tickers=("TUPRS", "ASELS"))
