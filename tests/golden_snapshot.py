"""A small seeded market-data snapshot for the contract tests.

Prices, macro series, fundamentals, KAP disclosures and unadjusted closes of a few
stocks, written in the layout of a real snapshot under ``root`` (a temporary folder).
Everything is a function of fixed seeds, so the tool outputs built on it can be pinned
in ``tests/golden``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bist_harness.data import kap as kap_data
from bist_harness.data.fundamentals import KAP_CALENDAR_COLUMNS, STATEMENT_COLUMNS

from .synth import ohlcv

SNAPSHOT_ID = "golden"
STOCKS = {"ASELS": 11, "TUPRS": 12, "AKBNK": 13, "GARAN": 14, "ISCTR": 15, "THYAO": 16}
INDEX_SEEDS = {"XU100": 21, "XU030": 22}
FIRST_DAY = "2023-01-02"
DAYS = 800  # business days, to the beginning of 2026
M = 1e6

# period -> known-from day of each report
REPORT_DAYS = {
    (2024, 3): "2024-11-05",
    (2024, 4): "2025-02-20",
    (2025, 1): "2025-05-12",
    (2025, 2): "2025-08-01",
    (2025, 3): "2025-11-03",
}
FLOW_CODES = [
    "revenue",
    "operating_profit",
    "depreciation",
    "net_profit",
    "parent_net_profit",
    "operating_cash_flow",
]
FLOWS = {
    (2024, 3): (600, 60, 15, 30, 30, 45),
    (2024, 4): (1000, 100, 20, 50, 50, 80),
    (2025, 1): (260, 26, 5, 14, 14, 10),
    (2025, 2): (500, 55, 11, 28, 28, 20),
    (2025, 3): (900, 108, 18, 54, 54, 90),
}
BALANCE_CODES = [
    "current_assets",
    "cash",
    "short_term_investments",
    "inventories",
    "total_assets",
    "short_term_liabilities",
    "short_term_debt",
    "long_term_debt",
    "equity",
    "parent_equity",
    "paid_in_capital",
]
BALANCES = {
    (2024, 3): (250, 40, 0, 50, 900, 210, 100, 130, 500, 480, 100),
    (2024, 4): (270, 45, 5, 55, 950, 205, 90, 125, 560, 540, 100),
    (2025, 1): (280, 47, 5, 57, 970, 202, 85, 122, 600, 580, 100),
    (2025, 2): (290, 48, 8, 58, 985, 201, 82, 121, 620, 590, 100),
    (2025, 3): (300, 50, 10, 60, 1000, 200, 80, 120, 650, 600, 100),
}
PRIOR_CODES = ["revenue", "net_profit", "parent_net_profit", "operating_cash_flow"]


def _stock_prices(seed: int) -> pd.DataFrame:
    frame = ohlcv(DAYS, seed, start=FIRST_DAY)
    return frame.round(2)


def _statements(ticker: str, scale: float) -> pd.DataFrame:
    rows = []
    for (year, quarter), flows in FLOWS.items():
        items = dict(zip(FLOW_CODES, flows, strict=True))
        items.update(zip(BALANCE_CODES, BALANCES[(year, quarter)], strict=True))
        if (year, quarter) == (2025, 3):  # the comparative column of the same report
            for code in PRIOR_CODES:
                items[f"{code}@prior"] = FLOWS[(2024, 3)][FLOW_CODES.index(code)] * 1.3
        rows += [(ticker, year, quarter, code, code, v * M * scale) for code, v in items.items()]
    return pd.DataFrame(rows, columns=STATEMENT_COLUMNS)


def _calendar(ticker: str) -> pd.DataFrame:
    rows = []
    for index, ((year, quarter), day) in enumerate(REPORT_DAYS.items()):
        end = pd.Period(f"{year}-{quarter * 3:02d}", "M").to_timestamp(how="end").normalize()
        start = pd.Timestamp(year=year, month=1, day=1)
        rows.append(
            (
                ticker,
                year,
                quarter,
                pd.Timestamp(day) - pd.Timedelta(hours=6),
                pd.Timestamp(day),
                0,
                start,
                end,
                1000 + index,
                True,
                1.0,
            )
        )
    return pd.DataFrame(rows, columns=KAP_CALENDAR_COLUMNS)


def _macro() -> dict[str, pd.DataFrame]:
    days = pd.bdate_range(FIRST_DAY, periods=DAYS)
    fx = pd.DataFrame(
        {
            "USDTRY": (28.0 + 0.012 * pd.RangeIndex(DAYS)).round(4),
            "EURTRY": (30.0 + 0.013 * pd.RangeIndex(DAYS)).round(4),
        },
        index=days,
    )
    policy = pd.DataFrame(
        {
            "effective_date": pd.to_datetime(["2023-06-22", "2024-03-21", "2025-03-06"]),
            "rate": [15.0, 50.0, 42.5],
        }
    )
    fed = pd.DataFrame(
        {
            "effective_date": pd.to_datetime(["2023-07-26", "2024-09-18", "2025-09-17"]),
            "lower": [5.25, 4.75, 4.0],
            "upper": [5.5, 5.0, 4.25],
        }
    )
    periods = pd.date_range("2023-01-31", periods=36, freq="ME")
    cpi = pd.DataFrame(
        {
            "period": periods,
            "annual_pct": [60.0 - 0.8 * i for i in range(36)],
            "monthly_pct": [3.0 - 0.03 * i for i in range(36)],
            "published": [p + pd.Timedelta(days=3) for p in periods],
        }
    )
    return {"fx": fx, "policy_rate": policy, "fed_target": fed, "cpi": cpi}


def _disclosures() -> pd.DataFrame:
    rows = [
        ("ASELS", "2025-03-04 10:05:00", "Sözleşme", "Yeni iş ilişkisi", "contract"),
        ("ASELS", "2025-06-18 19:30:00", "Kar Payı", "Temettü kararı", "dividend"),
        ("ASELS", "2025-09-02 09:00:00", "Dava", "Dava bilgilendirmesi", "regulation_legal"),
        ("TUPRS", "2025-04-10 12:00:00", "Sözleşme", "Tedarik anlaşması", "contract"),
        ("TUPRS", "2025-08-21 18:45:00", "Kar Payı", "Temettü ödemesi", "dividend"),
    ]
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "published_at": pd.Timestamp(at),
                "category": "ODA",
                "subject": subject,
                "summary": summary,
                "disclosure_index": 5000 + i,
                "url": f"{kap_data.DISCLOSURE_URL}{5000 + i}",
                "topic": topic,
            }
            for i, (ticker, at, subject, summary, topic) in enumerate(rows)
        ],
        columns=kap_data.COLUMNS,
    )


def build_golden_snapshot(root: Path) -> Path:
    """Write the snapshot under ``root`` (the ``snapshots`` folder); return its folder."""
    folder = root / SNAPSHOT_ID
    (folder / "macro").mkdir(parents=True)
    (folder / "fundamentals").mkdir()
    (folder / "kap").mkdir()
    (folder / "prices_raw").mkdir()
    (root / "ACTIVE").write_text(SNAPSHOT_ID, encoding="utf-8")

    for symbol, seed in {**STOCKS, **INDEX_SEEDS}.items():
        frame = _stock_prices(seed)
        frame.to_parquet(folder / f"{symbol}.parquet")
        if symbol in STOCKS:
            raw = pd.DataFrame(
                {"close": frame["Close"], "splits": 0.0, "raw_close": frame["Close"] * 1.4}
            ).round(2)
            raw.to_parquet(folder / "prices_raw" / f"{symbol}.parquet")
    for name, table in _macro().items():
        table.to_parquet(folder / "macro" / f"{name}.parquet")
    statements = pd.concat(
        [_statements("ASELS", 1.0), _statements("TUPRS", 2.0)], ignore_index=True
    )
    statements.to_parquet(folder / "fundamentals" / "statements.parquet")
    calendar = pd.concat([_calendar("ASELS"), _calendar("TUPRS")], ignore_index=True)
    calendar.to_parquet(folder / "fundamentals" / "calendar.parquet")
    _disclosures().to_parquet(folder / "kap" / "disclosures.parquet")
    return folder
