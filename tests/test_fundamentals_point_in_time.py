"""Fundamental metrics on as-published KAP figures (K-055): comparatives and price levels."""

import pandas as pd

from bist_harness.tools import fundamentals as fn

M = 1e6
CPI = pd.Series(
    {
        pd.Timestamp("2024-09-30"): 100.0,
        pd.Timestamp("2024-12-31"): 110.0,
        pd.Timestamp("2025-06-30"): 120.0,
        pd.Timestamp("2025-09-30"): 130.0,
        pd.Timestamp("2025-10-31"): 132.0,
    }
)


def _book(ticker: str, restated: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    """2024Q3, 2024Q4, 2025Q2 and 2025Q3 of one industrial company, as published.

    The 2025Q3 report carries the 2024 nine months in its comparative column: restated
    to September 2025 prices (x1.3) by a company under inflation accounting, unchanged
    by one that is not.
    """
    lift = 1.3 if restated else 1.0
    values = {
        (2024, 3): {
            "revenue": 600,
            "net_profit": -10,
            "parent_net_profit": -10,
            "operating_cash_flow": 45,
            "parent_equity": 480,
            "equity": 500,
        },
        (2024, 4): {
            "revenue": 1000,
            "net_profit": 50,
            "parent_net_profit": 50,
            "operating_cash_flow": 80,
            "parent_equity": 520,
            "equity": 540,
        },
        (2025, 2): {
            "revenue": 500,
            "net_profit": 28,
            "parent_net_profit": 28,
            "operating_cash_flow": 20,
            "parent_equity": 560,
            "equity": 580,
        },
        (2025, 3): {
            "revenue": 900,
            "net_profit": 54,
            "parent_net_profit": 54,
            "operating_cash_flow": 90,
            "parent_equity": 600,
            "equity": 650,
            "revenue@prior": 600 * lift,
            "net_profit@prior": -10 * lift,
            "parent_net_profit@prior": -10 * lift,
            "operating_cash_flow@prior": 45 * lift,
        },
    }
    rows = [
        (ticker, y, q, key, key, v * M)
        for (y, q), items in values.items()
        for key, v in items.items()
    ]
    statements = pd.DataFrame(
        rows, columns=["ticker", "year", "quarter", "item_code", "item_name", "value"]
    )
    known = {
        (2024, 3): "2024-11-05",
        (2024, 4): "2025-02-20",
        (2025, 2): "2025-08-01",
        (2025, 3): "2025-11-03",
    }
    calendar = pd.DataFrame(
        [
            (
                ticker,
                y,
                q,
                pd.Timestamp(d) - pd.Timedelta(hours=6),
                pd.Timestamp(d),
                0,
                pd.Period(f"{y}-{q * 3:02d}", "M").to_timestamp(how="end").normalize(),
            )
            for (y, q), d in known.items()
        ],
        columns=[
            "ticker",
            "year",
            "quarter",
            "published_at",
            "known_from",
            "revisions",
            "period_end",
        ],
    )
    return statements, calendar


def _metrics(ticker="TUPRS", restated=True, **kwargs):
    statements, calendar = _book(ticker, restated)
    return fn.fundamental_metrics(
        statements, calendar, ticker=ticker, as_of="2025-11-10", cpi=CPI, **kwargs
    )


def _change(ticker="TUPRS", restated=True):
    statements, calendar = _book(ticker, restated)
    return fn.fundamental_change(statements, calendar, ticker=ticker, as_of="2025-11-10", cpi=CPI)


def test_real_growth_comes_from_the_restated_comparative_of_the_same_report():
    out = _metrics()
    assert out["revenue_yoy_pct"] == 50.0  # 900 against the 600 published a year ago
    assert out["revenue_real_yoy_pct"] == round((900 / 780 - 1) * 100, 2)  # 15.38
    assert out["net_profit_real_yoy_pct"] is None  # the base is a loss


def test_without_restatement_real_growth_uses_the_cpi():
    out = _metrics("THYAO", restated=False)
    assert out["revenue_real_yoy_pct"] == round((900 / (600 * 1.3) - 1) * 100, 2)
    assert any(w.startswith("COMPARATIVE_NOT_RESTATED") for w in out["warnings"])


def test_old_source_warnings_are_gone():
    codes = {w.split(":")[0] for w in _metrics()["warnings"]}
    assert "RESTATED_SOURCE" not in codes and "REAL_GROWTH_WITHHELD" not in codes


def test_twelve_month_sums_bring_last_year_end_to_the_same_price_level():
    # 54 + 50 x 130/110 - (-13) under inflation accounting
    expected = (54 + 50 * 130 / 110 + 13) / 600 * 100
    assert _metrics()["roe_pct"] == round(expected, 2)
    # nominal company: 54 + 50 - (-10)
    assert _metrics("THYAO", restated=False)["roe_pct"] == round(114 / 600 * 100, 2)


def test_a_quarter_alone_restates_the_earlier_cumulative_figure():
    out = _change()
    latest = out["quarters"][0]
    assert latest["period"] == "2025Q3"
    assert latest["revenue_q_mn"] == round(900 - 500 * 130 / 120, 2)  # 358.33
    nominal = _change("THYAO", restated=False)["quarters"][0]
    assert nominal["revenue_q_mn"] == 400.0


def test_improvement_checks_compare_on_one_price_level_and_count_a_loss_turned_profit():
    flags = _change()["improvement_flags"]
    assert "PROFIT_UP" in flags  # 54 against a restated loss of 13
    assert "REVENUE_UP" in flags  # 900 against 780
    assert "CASH_FLOW_UP" in flags  # 90 against 58.5


def test_the_period_end_is_the_one_in_the_calendar():
    statements, calendar = _book("MAVI", restated=True)
    calendar.loc[calendar["year"].eq(2025) & calendar["quarter"].eq(3), "period_end"] = (
        pd.Timestamp("2025-10-31")
    )
    out = fn.fundamental_metrics(statements, calendar, ticker="MAVI", as_of="2025-11-10", cpi=CPI)
    assert out["period_end"] == "2025-10-31"


def _raw(split_on=None):
    days = pd.bdate_range("2025-09-01", "2025-11-14")
    frame = pd.DataFrame({"close": 50.0, "splits": 0.0, "raw_close": 50.0}, index=days)
    if split_on:
        frame.loc[pd.Timestamp(split_on), "splits"] = 2.0
    return frame


def _with_capital(ticker="TUPRS"):
    statements, calendar = _book(ticker, True)
    extra = pd.DataFrame(
        [(ticker, 2025, 3, "paid_in_capital", "paid_in_capital", 10 * M)],
        columns=statements.columns,
    )
    return pd.concat([statements, extra], ignore_index=True), calendar


def test_market_value_is_the_unadjusted_close_times_the_paid_in_capital():
    statements, calendar = _with_capital()
    out = fn.fundamental_metrics(
        statements, calendar, ticker="TUPRS", as_of="2025-11-10", cpi=CPI, raw_prices=_raw()
    )
    assert out["market_cap_mn"] == 500.0  # 50 TL x 10 million shares of 1 TL nominal
    ttm_parent = 54 + 50 * 130 / 110 + 13
    assert out["pe"] == round(500 / ttm_parent, 2)
    assert out["pb"] == round(500 / 600, 2)
    assert out["valuation_note"] == "UNADJUSTED_CLOSE_TIMES_PAID_IN_CAPITAL"


def test_valuation_is_withheld_when_shares_changed_after_the_period():
    statements, calendar = _with_capital()
    out = fn.fundamental_metrics(
        statements,
        calendar,
        ticker="TUPRS",
        as_of="2025-11-10",
        cpi=CPI,
        raw_prices=_raw(split_on="2025-10-15"),
    )
    assert out["market_cap_mn"] is None and out["pe"] is None
    assert out["valuation_note"] == "WITHHELD_SHARE_COUNT_CHANGED"
