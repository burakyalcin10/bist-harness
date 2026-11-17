"""Point-in-time fundamental metrics and quarterly change (project brief, sections 9 and 14).

Only the latest reporting period that was **public on the analysis date** is used: a
period counts from its ``known_from`` day (see ``data/fundamentals.py``).

Statement values are cumulative within the fiscal year. From them:

* a quarter's own value is the cumulative value minus the previous cumulative value;
* the last twelve months (TTM) are this period plus last year's full year minus last
  year's same period;
* EBITDA is operating profit plus depreciation and amortisation.

Banks and insurers report in their own formats: EBITDA, net debt and the liquidity
ratios do not exist for them and are returned as ``None`` and listed in
``not_applicable``. Their "revenue" is net interest income and gross premiums.

Inflation accounting (TMS 29) applies to non-bank statements from the 2023 year end on.
**The statement source is not point-in-time for such companies**: once the following
year's report is out, it shows a period's figures as restated in that report (at the
later price level). Every output therefore carries a ``RESTATED_SOURCE`` warning, real
growth is not computed (it would deflate an already restated comparative a second time)
and valuation ratios are withheld (prices in the snapshot are dividend-adjusted).
Rebuilding this layer from as-published figures is the first task of the next sprint.
"""

from __future__ import annotations

import math

import pandas as pd

from bist_harness.data.fundamentals import Period, financial_group
from bist_harness.universe import normalize_ticker

ITEMS = {
    "industrial": {
        "current_assets": "1A",
        "cash": "1AA",
        "short_term_investments": "1AB",
        "inventories": "1AF",
        "total_assets": "1BL",
        "short_term_liabilities": "2A",
        "short_term_debt": "2AA",
        "long_term_debt": "2BA",
        "equity": "2N",
        "parent_equity": "2O",
        "paid_in_capital": "2OA",
        "revenue": "3C",
        "operating_profit": "3DF",
        "net_profit": "3L",
        "parent_net_profit": "3Z",
        "depreciation": "4B",
        "operating_cash_flow": "4C",
    },
    "bank": {
        "total_assets": "1Z",
        "equity": "2O",
        "parent_equity": "2O",
        "paid_in_capital": "2OA",
        "revenue": "3C",  # net interest income
        "net_profit": "3Z",
        "parent_net_profit": "3ZA",
    },
    "insurance": {
        "total_assets": "1Z",
        "equity": "2O",
        "parent_equity": "2O",
        "paid_in_capital": "2MEA",
        "revenue": "3AAAA",  # gross written premiums
        "net_profit": "3NJA",
        "parent_net_profit": "3NJA",
    },
}
FLOWS = {
    "revenue",
    "operating_profit",
    "net_profit",
    "parent_net_profit",
    "depreciation",
    "operating_cash_flow",
    "ebitda",
}
REVENUE_MEANING = {
    "industrial": "net sales",
    "bank": "net interest income",
    "insurance": "gross written premiums",
}
INDUSTRIAL_ONLY = (
    "ebitda_mn",
    "ebitda_margin_pct",
    "ebitda_yoy_pct",
    "ebitda_real_yoy_pct",
    "net_debt_mn",
    "net_debt_to_ebitda",
    "debt_to_equity",
    "current_ratio",
    "quick_ratio",
    "ev_ebitda",
    "operating_cash_flow_mn",
    "cash_conversion",
)
TMS29_FIRST = Period(2023, 4)
MILLION = 1e6


class Book:
    """Statements of one stock, addressed by period and field name."""

    def __init__(self, statements: pd.DataFrame, ticker: str):
        self.ticker = normalize_ticker(ticker)
        self.group = financial_group(self.ticker)
        self.codes = ITEMS[self.group]
        own = statements[statements["ticker"] == self.ticker]
        self._values = {
            (int(y), int(q), code): float(v)
            for y, q, code, v in zip(
                own["year"], own["quarter"], own["item_code"], own["value"], strict=True
            )
        }
        self.periods = sorted({Period(y, q) for y, q, _ in self._values})

    def value(self, period: Period, field: str) -> float | None:
        """Cumulative value of a flow, or the balance at the period end."""
        if field == "ebitda":
            profit, depreciation = (
                self.value(period, "operating_profit"),
                self.value(period, "depreciation"),
            )
            return None if profit is None or depreciation is None else profit + depreciation
        code = self.codes.get(field)
        return None if code is None else self._values.get((period.year, period.quarter, code))

    def quarter(self, period: Period, field: str) -> float | None:
        """The quarter's own value of a flow."""
        current = self.value(period, field)
        if current is None or period.quarter == 1:
            return current
        before = self.value(period.previous(), field)
        return None if before is None else current - before

    def ttm(self, period: Period, field: str) -> float | None:
        """Last twelve months of a flow."""
        current = self.value(period, field)
        if current is None or period.quarter == 4:
            return current
        last_year = self.value(Period(period.year - 1, 4), field)
        same_last_year = self.value(period.year_earlier(), field)
        if last_year is None or same_last_year is None:
            return None
        return current + last_year - same_last_year


def _ratio(numerator: float | None, denominator: float | None, *, scale: float = 1.0):
    """numerator / denominator, or None when either is missing or the base is not positive."""
    if numerator is None or denominator is None or not denominator > 0:
        return None
    value = numerator / denominator * scale
    return round(value, 2) if math.isfinite(value) else None


def _growth(now: float | None, before: float | None, factor: float = 1.0) -> float | None:
    """Percentage change against ``before`` brought to today's prices by ``factor``."""
    if now is None or before is None or not before * factor > 0:
        return None
    return round((now / (before * factor) - 1) * 100, 2)


def _millions(value: float | None) -> float | None:
    return None if value is None else round(value / MILLION, 2)


def _price_factor(cpi: pd.Series | None, now: Period, before: Period) -> float | None:
    """How much prices rose between the two period ends, from the CPI index."""
    if cpi is None:
        return None
    try:
        return float(cpi.loc[now.end_date] / cpi.loc[before.end_date])
    except KeyError:
        return None


def known_periods(calendar: pd.DataFrame, ticker: str, as_of: str) -> pd.DataFrame:
    """Reporting periods of a stock that were public on ``as_of``, oldest first."""
    rows = calendar[
        (calendar["ticker"] == normalize_ticker(ticker))
        & calendar["known_from"].notna()
        & (calendar["known_from"] <= pd.Timestamp(as_of))
    ]
    return rows.sort_values(["year", "quarter"]).reset_index(drop=True)


def latest_known_period(calendar: pd.DataFrame, ticker: str, as_of: str) -> Period | None:
    rows = known_periods(calendar, ticker, as_of)
    if rows.empty:
        return None
    last = rows.iloc[-1]
    return Period(int(last["year"]), int(last["quarter"]))


def _net_debt(book: Book, period: Period) -> float | None:
    parts = [book.value(period, f) for f in ("short_term_debt", "long_term_debt", "cash")]
    if any(p is None for p in parts):
        return None
    investments = book.value(period, "short_term_investments") or 0.0
    return parts[0] + parts[1] - parts[2] - investments


def _debt(book: Book, period: Period) -> float | None:
    short, long = book.value(period, "short_term_debt"), book.value(period, "long_term_debt")
    return None if short is None or long is None else short + long


def period_metrics(book: Book, period: Period, cpi: pd.Series | None = None) -> dict:
    """Every metric that needs only the statements of ``period`` and of earlier periods."""
    earlier = period.year_earlier()
    factor = _price_factor(cpi, period, earlier)
    revenue, net_profit = book.value(period, "revenue"), book.value(period, "net_profit")
    ebitda = book.value(period, "ebitda")
    ttm_ebitda = book.ttm(period, "ebitda")
    net_debt = _net_debt(book, period)
    current_assets = book.value(period, "current_assets")
    inventories = book.value(period, "inventories")
    liquid = None if current_assets is None else current_assets - (inventories or 0.0)
    cash_flow = book.value(period, "operating_cash_flow")

    def growth(field: str, real: bool) -> float | None:
        if real:  # withheld: see _warnings (the source already restates the comparative)
            return None
        return _growth(
            book.value(period, field), book.value(earlier, field), factor if real else 1.0
        )

    return {
        "revenue_mn": _millions(revenue),
        "ebitda_mn": _millions(ebitda),
        "net_profit_mn": _millions(net_profit),
        "operating_cash_flow_mn": _millions(cash_flow),
        "total_assets_mn": _millions(book.value(period, "total_assets")),
        "equity_mn": _millions(book.value(period, "equity")),
        "net_debt_mn": _millions(net_debt),
        "revenue_yoy_pct": growth("revenue", False),
        "revenue_real_yoy_pct": growth("revenue", True),
        "ebitda_yoy_pct": growth("ebitda", False),
        "ebitda_real_yoy_pct": growth("ebitda", True),
        "net_profit_yoy_pct": growth("net_profit", False),
        "net_profit_real_yoy_pct": growth("net_profit", True),
        "ebitda_margin_pct": _ratio(ebitda, revenue, scale=100),
        "net_margin_pct": _ratio(net_profit, revenue, scale=100),
        "roe_pct": _ratio(
            book.ttm(period, "parent_net_profit"), book.value(period, "parent_equity"), scale=100
        ),
        "roa_pct": _ratio(
            book.ttm(period, "net_profit"), book.value(period, "total_assets"), scale=100
        ),
        "net_debt_to_ebitda": _ratio(net_debt, ttm_ebitda),
        "debt_to_equity": _ratio(_debt(book, period), book.value(period, "equity")),
        "current_ratio": _ratio(current_assets, book.value(period, "short_term_liabilities")),
        "quick_ratio": _ratio(liquid, book.value(period, "short_term_liabilities")),
        "cash_conversion": _ratio(cash_flow, net_profit),
    }


def _valuation(book: Book, period: Period, close: pd.Series | None, as_of: str) -> dict:
    """Valuation ratios are withheld.

    The snapshot holds prices adjusted for dividends as well as splits
    (``auto_adjust=True``), so a past close is lower than the price that was quoted that
    day, and close times share count understates the market value of the time. Until an
    unadjusted close is stored, P/E, P/B and EV/EBITDA are not computed rather than
    reported wrong.
    """
    return {
        "market_cap_mn": None,
        "pe": None,
        "pb": None,
        "ev_ebitda": None,
        "valuation_note": "WITHHELD_PRICES_ARE_DIVIDEND_ADJUSTED",
    }


def _header(book: Book, row: pd.Series, period: Period) -> dict:
    return {
        "period": str(period),
        "period_end": str(period.end_date.date()),
        "published_at": pd.Timestamp(row["published_at"]).isoformat(timespec="seconds"),
        "known_from": str(pd.Timestamp(row["known_from"]).date()),
        "financial_group": book.group,
        "revenue_meaning": REVENUE_MEANING[book.group],
    }


def _warnings(book: Book, period: Period, cpi: pd.Series | None) -> list[str]:
    warnings = []
    if book.group != "bank":
        warnings.append(
            "RESTATED_SOURCE: the statement source replaces a period's figures with the "
            "restated comparative of the following year's report (inflation accounting), "
            "so amounts of earlier periods are at a later price level than the one "
            "published at the time, and their changes are not the published ones."
        )
        if period.year_earlier() < TMS29_FIRST:
            warnings.append(
                "COMPARATIVE_BEFORE_TMS29: the year-earlier period predates inflation "
                "accounting; year-over-year changes mix two bases."
            )
    warnings.append(
        "REAL_GROWTH_WITHHELD: for the latest year the stored comparative is already at "
        "the current price level, so the year-over-year change is close to real growth; a "
        "separate CPI adjustment would deflate twice and is not reported."
    )
    return warnings


def fundamental_metrics(
    statements: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    ticker: str,
    as_of: str,
    close: pd.Series | None = None,
    cpi: pd.Series | None = None,
) -> dict | None:
    """Metrics of the latest period public on ``as_of``; ``None`` when there is none."""
    known = known_periods(calendar, ticker, as_of)
    if known.empty:
        return None
    row = known.iloc[-1]
    period = Period(int(row["year"]), int(row["quarter"]))
    book = Book(statements, ticker)
    metrics = {**period_metrics(book, period, cpi), **_valuation(book, period, close, as_of)}
    return {
        "ticker": book.ticker,
        "as_of": as_of,
        **_header(book, row, period),
        **metrics,
        "not_applicable": [] if book.group == "industrial" else list(INDUSTRIAL_ONLY),
        "warnings": _warnings(book, period, cpi),
    }


def _trend(now: dict, before: dict, group: str) -> tuple[list[str], str | None]:
    """Improvement flags of a period against the same period a year earlier, and the trend.

    Real growth is used when available, nominal otherwise. With fewer than three
    applicable checks no trend is given.
    """

    def pick(real: str, nominal: str) -> float | None:
        return now[real] if now[real] is not None else now[nominal]

    def change(key: str) -> float | None:
        return None if now[key] is None or before[key] is None else now[key] - before[key]

    margin_key = "ebitda_margin_pct" if group == "industrial" else "net_margin_pct"
    checks = {
        "REVENUE_UP": pick("revenue_real_yoy_pct", "revenue_yoy_pct"),
        "PROFIT_UP": pick("net_profit_real_yoy_pct", "net_profit_yoy_pct"),
        "MARGIN_UP": change(margin_key),
        "RETURN_ON_EQUITY_UP": change("roe_pct"),
    }
    if group == "industrial":
        leverage = change("net_debt_to_ebitda")
        checks["LEVERAGE_DOWN"] = None if leverage is None else -leverage
        checks["CASH_FLOW_UP"] = change("operating_cash_flow_mn")
    applicable = {name: value for name, value in checks.items() if value is not None}
    flags = [name for name, value in applicable.items() if value > 0]
    if len(applicable) < 3:
        return flags, None
    share = len(flags) / len(applicable)
    if share >= 2 / 3:
        return flags, "Improving"
    if share <= 1 / 3:
        return flags, "Deteriorating"
    return flags, "Mixed"


def fundamental_change(
    statements: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    ticker: str,
    as_of: str,
    periods: int = 4,
    cpi: pd.Series | None = None,
) -> dict | None:
    """Quarter-by-quarter figures of the latest ``periods`` public periods, and the trend."""
    known = known_periods(calendar, ticker, as_of)
    if known.empty:
        return None
    book = Book(statements, ticker)
    rows = []
    for _, row in known.iloc[::-1].head(periods).iterrows():
        period = Period(int(row["year"]), int(row["quarter"]))
        own = {f: book.quarter(period, f) for f in ("revenue", "ebitda", "net_profit")}
        earlier = {
            f: book.quarter(period.year_earlier(), f) for f in ("revenue", "ebitda", "net_profit")
        }
        before = {
            f: book.quarter(period.previous(), f) for f in ("revenue", "ebitda", "net_profit")
        }
        rows.append(
            {
                "period": str(period),
                "known_from": str(pd.Timestamp(row["known_from"]).date()),
                "revenue_q_mn": _millions(own["revenue"]),
                "ebitda_q_mn": _millions(own["ebitda"]),
                "net_profit_q_mn": _millions(own["net_profit"]),
                "ebitda_margin_q_pct": _ratio(own["ebitda"], own["revenue"], scale=100),
                "net_margin_q_pct": _ratio(own["net_profit"], own["revenue"], scale=100),
                "revenue_qoq_pct": _growth(own["revenue"], before["revenue"]),
                "revenue_q_yoy_pct": _growth(own["revenue"], earlier["revenue"]),
                "net_profit_q_yoy_pct": _growth(own["net_profit"], earlier["net_profit"]),
            }
        )

    last = known.iloc[-1]
    period = Period(int(last["year"]), int(last["quarter"]))
    now = period_metrics(book, period, cpi)
    year_ago = period_metrics(book, period.year_earlier(), cpi)
    flags, trend = _trend(now, year_ago, book.group)

    def change(key: str) -> float | None:
        if now[key] is None or year_ago[key] is None:
            return None
        return round(now[key] - year_ago[key], 2)

    return {
        "ticker": book.ticker,
        "as_of": as_of,
        **_header(book, last, period),
        "compared_with": str(period.year_earlier()),
        "quarters": rows,
        "revenue_yoy_pct": now["revenue_yoy_pct"],
        "revenue_real_yoy_pct": now["revenue_real_yoy_pct"],
        "net_profit_yoy_pct": now["net_profit_yoy_pct"],
        "net_profit_real_yoy_pct": now["net_profit_real_yoy_pct"],
        "ebitda_margin_change_pp": change("ebitda_margin_pct"),
        "net_margin_change_pp": change("net_margin_pct"),
        "roe_change_pp": change("roe_pct"),
        "net_debt_to_ebitda_change": change("net_debt_to_ebitda"),
        "current_ratio_change": change("current_ratio"),
        "improvement_flags": flags,
        "fundamental_trend": trend,
        "not_applicable": [] if book.group == "industrial" else list(INDUSTRIAL_ONLY),
        "warnings": _warnings(book, period, cpi),
    }
