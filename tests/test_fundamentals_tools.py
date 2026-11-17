"""Point-in-time fundamental metrics: every ratio against a hand calculation."""

import pandas as pd
import pytest

from bist_harness.tools import fundamentals as fn

M = 1e6  # amounts below are in million TRY

# Cumulative flows of an industrial company (ticker TUPRS).
FLOWS = {
    # period: revenue, operating profit, depreciation, net profit, parent net profit, op. cash flow
    (2024, 2): (400, 40, 10, 20, 20, 30),
    (2024, 3): (600, 60, 15, 30, 30, 45),
    (2024, 4): (1000, 100, 20, 50, 50, 80),
    (2025, 2): (500, 55, 11, 28, 28, 20),
    (2025, 3): (900, 108, 18, 54, 54, 90),
}
BALANCES = {
    # period: current assets, cash, short-term investments, inventories, total assets,
    #         short-term liabilities, short-term debt, long-term debt, equity, parent equity
    (2024, 3): (250, 40, 0, 50, 900, 210, 100, 130, 500, 480),
    (2025, 3): (300, 50, 10, 60, 1000, 200, 80, 120, 650, 600),
}
FLOW_CODES = [
    "revenue",
    "operating_profit",
    "depreciation",
    "net_profit",
    "parent_net_profit",
    "operating_cash_flow",
]
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
]
KNOWN = {
    (2024, 2): "2024-08-12",
    (2024, 3): "2024-11-05",
    (2024, 4): "2025-02-20",
    (2025, 2): "2025-08-01",
    (2025, 3): "2025-11-03",
}


def _statements(ticker="TUPRS", shares=100.0, shares_before=None) -> pd.DataFrame:
    rows = []
    for (year, quarter), values in FLOWS.items():
        rows += [
            (ticker, year, quarter, c, c, v * M) for c, v in zip(FLOW_CODES, values, strict=True)
        ]
        count = (
            shares_before if shares_before is not None and (year, quarter) < (2025, 3) else shares
        )
        rows.append((ticker, year, quarter, "paid_in_capital", "Share Capital", count * M))
    for (year, quarter), values in BALANCES.items():
        rows += [
            (ticker, year, quarter, c, c, v * M) for c, v in zip(BALANCE_CODES, values, strict=True)
        ]
    return pd.DataFrame(
        rows, columns=["ticker", "year", "quarter", "item_code", "item_name", "value"]
    )


def _calendar(ticker="TUPRS", skip=()) -> pd.DataFrame:
    rows = []
    for (year, quarter), day in KNOWN.items():
        known = pd.NaT if (year, quarter) in skip else pd.Timestamp(day)
        rows.append((ticker, year, quarter, pd.Timestamp(day) - pd.Timedelta(hours=6), known, 0))
    return pd.DataFrame(
        rows, columns=["ticker", "year", "quarter", "published_at", "known_from", "revisions"]
    )


CLOSE = pd.Series(37.0, index=pd.date_range("2024-01-01", "2025-12-31", freq="B"))
CPI = pd.Series(
    {
        pd.Timestamp("2024-09-30"): 100.0,
        pd.Timestamp("2025-09-30"): 130.0,
        pd.Timestamp("2024-06-30"): 95.0,
    }
).sort_index()


def _metrics(as_of="2025-11-10", **kwargs):
    kwargs.setdefault("close", CLOSE)
    kwargs.setdefault("cpi", CPI)
    return fn.fundamental_metrics(_statements(), _calendar(), ticker="tuprs", as_of=as_of, **kwargs)


def test_header_names_the_period_and_when_it_became_public():
    out = _metrics()
    assert (out["ticker"], out["as_of"], out["period"]) == ("TUPRS", "2025-11-10", "2025Q3")
    assert out["period_end"] == "2025-09-30" and out["known_from"] == "2025-11-03"
    assert out["published_at"] == "2025-11-02T18:00:00"
    assert out["financial_group"] == "industrial" and out["revenue_meaning"] == "net sales"
    assert out["not_applicable"] == []


def test_amounts_growth_and_margins():
    out = _metrics()
    assert (out["revenue_mn"], out["net_profit_mn"], out["ebitda_mn"]) == (900.0, 54.0, 126.0)
    assert out["operating_cash_flow_mn"] == 90.0 and out["total_assets_mn"] == 1000.0
    assert out["revenue_yoy_pct"] == 50.0  # 900 against 600
    assert out["ebitda_yoy_pct"] == 68.0  # 126 against 75
    assert out["net_profit_yoy_pct"] == 80.0  # 54 against 30
    assert out["ebitda_margin_pct"] == 14.0 and out["net_margin_pct"] == 6.0


def test_real_growth_is_not_reported():
    """The source already restates the comparative; see tests/test_sprint3_review.py."""
    out = _metrics()
    assert out["revenue_real_yoy_pct"] is None and out["net_profit_real_yoy_pct"] is None
    assert _metrics(cpi=None)["revenue_yoy_pct"] == 50.0


def test_returns_use_the_last_twelve_months():
    out = _metrics()
    # TTM net profit: 54 + 50 - 30 = 74
    assert out["roe_pct"] == round(74 / 600 * 100, 2)  # 12.33
    assert out["roa_pct"] == 7.4


def test_leverage_and_liquidity():
    out = _metrics()
    # net debt: 80 + 120 - 50 - 10 = 140; TTM EBITDA: 126 + 120 - 75 = 171
    assert out["net_debt_mn"] == 140.0
    assert out["net_debt_to_ebitda"] == round(140 / 171, 2)  # 0.82
    assert out["debt_to_equity"] == round(200 / 650, 2)  # 0.31
    assert out["current_ratio"] == 1.5 and out["quick_ratio"] == 1.2
    assert out["cash_conversion"] == round(90 / 54, 2)  # 1.67


def test_valuation_is_withheld():
    out = _metrics()
    assert out["market_cap_mn"] is None and out["pe"] is None and out["ev_ebitda"] is None
    assert out["valuation_note"] == "WITHHELD_NO_UNADJUSTED_PRICE"  # adjusted close is never used


def test_valuation_is_withheld_when_the_share_count_changed_after_the_period():
    statements = _statements(shares=1100.0, shares_before=100.0)
    out = fn.fundamental_metrics(
        statements, _calendar(), ticker="TUPRS", as_of="2025-09-01", close=CLOSE, cpi=CPI
    )
    assert out["period"] == "2025Q2"
    assert out["pe"] is None and out["market_cap_mn"] is None
    assert out["valuation_note"] == "WITHHELD_NO_UNADJUSTED_PRICE"  # adjusted close is never used


@pytest.mark.parametrize(
    "as_of,period",
    [
        ("2025-11-02", "2025Q2"),  # the day before the third quarter became usable
        ("2025-11-03", "2025Q3"),
        ("2025-07-31", "2024Q4"),
        ("2024-08-12", "2024Q2"),
    ],
)
def test_only_periods_public_on_the_analysis_date_are_used(as_of, period):
    assert _metrics(as_of=as_of)["period"] == period


def test_nothing_public_yet_gives_no_result():
    assert _metrics(as_of="2024-08-11") is None
    assert (
        fn.fundamental_metrics(_statements(), _calendar(), ticker="THYAO", as_of="2025-11-10")
        is None
    )
    assert (
        fn.fundamental_change(_statements(), _calendar(), ticker="TUPRS", as_of="2024-01-01")
        is None
    )


def test_a_period_without_a_publication_time_is_never_used():
    calendar = _calendar(skip={(2025, 3)})
    out = fn.fundamental_metrics(_statements(), calendar, ticker="TUPRS", as_of="2025-12-01")
    assert out["period"] == "2025Q2"


def test_a_ratio_with_a_zero_or_negative_base_is_none():
    statements = _statements()
    loss = statements["item_code"].isin(["net_profit", "net_profit"]) & (statements["year"] == 2025)
    statements.loc[loss, "value"] = -5 * M
    equity = statements["item_code"].isin(["equity", "parent_equity"]) & (
        statements["year"] == 2025
    )
    statements.loc[equity, "value"] = -10 * M
    out = fn.fundamental_metrics(
        statements, _calendar(), ticker="TUPRS", as_of="2025-11-10", close=CLOSE, cpi=CPI
    )
    assert out["roe_pct"] is None and out["debt_to_equity"] is None and out["pb"] is None
    assert out["cash_conversion"] is None
    assert out["pe"] is None  # valuation is withheld altogether
    assert out["net_profit_mn"] == -5.0 and out["net_margin_pct"] == round(-5 / 900 * 100, 2)


def test_comparative_before_inflation_accounting_is_flagged():
    statements = _statements()
    statements["year"] -= 1  # periods 2023Q2 .. 2024Q3: the comparative of 2024Q3 is 2023Q3
    calendar = _calendar()
    calendar["year"] -= 1
    calendar["known_from"] -= pd.Timedelta(days=365)
    out = fn.fundamental_metrics(statements, calendar, ticker="TUPRS", as_of="2024-12-31")
    assert out["period"] == "2024Q3"
    assert any(w.startswith("COMPARATIVE_BEFORE_TMS29") for w in out["warnings"])


def _bank_statements() -> pd.DataFrame:
    rows = []
    data = {
        (2024, 3): {
            "total_assets": 2000,
            "equity": 200,
            "parent_equity": 200,
            "paid_in_capital": 52,
            "revenue": 60,
            "net_profit": 30,
            "parent_net_profit": 30,
        },
        (2024, 4): {
            "total_assets": 2200,
            "equity": 215,
            "parent_equity": 215,
            "paid_in_capital": 52,
            "revenue": 85,
            "net_profit": 42,
            "parent_net_profit": 42,
        },
        (2025, 3): {
            "total_assets": 3000,
            "equity": 280,
            "parent_equity": 280,
            "paid_in_capital": 52,
            "revenue": 75,
            "net_profit": 39,
            "parent_net_profit": 39,
        },
    }
    for (year, quarter), items in data.items():
        rows += [("AKBNK", year, quarter, code, code, value * M) for code, value in items.items()]
    return pd.DataFrame(
        rows, columns=["ticker", "year", "quarter", "item_code", "item_name", "value"]
    )


def test_bank_gets_no_industrial_ratios():
    calendar = _calendar("AKBNK")
    out = fn.fundamental_metrics(
        _bank_statements(), calendar, ticker="AKBNK", as_of="2025-11-10", close=CLOSE, cpi=CPI
    )
    assert out["financial_group"] == "bank" and out["revenue_meaning"] == "net interest income"
    assert out["revenue_mn"] == 75.0 and out["revenue_yoy_pct"] == 25.0
    # TTM profit: 39 + 42 - 30 = 51
    assert out["roe_pct"] == round(51 / 280 * 100, 2) and out["roa_pct"] == 1.7
    for key in ("ebitda_mn", "net_debt_to_ebitda", "current_ratio", "quick_ratio", "ev_ebitda"):
        assert out[key] is None and key in out["not_applicable"]
    assert out["pe"] is None and out["pb"] is None
    codes = [w.split(":")[0] for w in out["warnings"]]
    assert "RESTATED_SOURCE" not in codes and "COMPARATIVE_BEFORE_TMS29" not in codes


def test_change_lists_quarters_latest_first_with_their_own_values():
    out = fn.fundamental_change(
        _statements(), _calendar(), ticker="TUPRS", as_of="2025-11-10", cpi=CPI
    )
    assert out["period"] == "2025Q3" and out["compared_with"] == "2024Q3"
    assert [q["period"] for q in out["quarters"]] == ["2025Q3", "2025Q2", "2024Q4", "2024Q3"]
    latest = out["quarters"][0]
    # the third quarter alone: 900 - 500 revenue, 126 - 66 EBITDA, 54 - 28 net profit
    assert (latest["revenue_q_mn"], latest["ebitda_q_mn"], latest["net_profit_q_mn"]) == (
        400.0,
        60.0,
        26.0,
    )
    assert latest["ebitda_margin_q_pct"] == 15.0 and latest["net_margin_q_pct"] == 6.5
    assert latest["revenue_q_yoy_pct"] == 100.0  # 400 against 600 - 400
    assert latest["known_from"] == "2025-11-03"
    second = out["quarters"][1]
    assert second["revenue_q_mn"] is None  # the first quarter of 2025 is not in the data
    assert (
        len(
            fn.fundamental_change(
                _statements(), _calendar(), ticker="TUPRS", as_of="2025-11-10", periods=2
            )["quarters"]
        )
        == 2
    )


def test_change_compares_the_latest_period_with_a_year_earlier():
    out = fn.fundamental_change(
        _statements(), _calendar(), ticker="TUPRS", as_of="2025-11-10", cpi=CPI
    )
    assert out["revenue_real_yoy_pct"] is None and out["revenue_yoy_pct"] == 50.0
    # EBITDA margin 14.0% against 75 / 600 = 12.5%
    assert out["ebitda_margin_change_pp"] == 1.5
    # current ratio 1.5 against 250 / 210 = 1.19
    assert out["current_ratio_change"] == round(1.5 - 1.19, 2)
    assert out["roe_change_pp"] is None  # last year's TTM needs 2023 data
    assert out["net_debt_to_ebitda_change"] is None


def test_trend_is_improving_when_most_checks_are_positive():
    out = fn.fundamental_change(
        _statements(), _calendar(), ticker="TUPRS", as_of="2025-11-10", cpi=CPI
    )
    assert out["improvement_flags"] == ["REVENUE_UP", "PROFIT_UP", "MARGIN_UP", "CASH_FLOW_UP"]
    assert out["fundamental_trend"] == "Improving"


def test_trend_is_deteriorating_when_most_checks_are_negative():
    statements = _statements()
    latest = (statements["year"] == 2025) & (statements["quarter"] == 3)
    scale = {
        "revenue": 0.6,
        "operating_profit": 0.3,
        "net_profit": 0.3,
        "parent_net_profit": 0.3,
        "operating_cash_flow": 0.2,
    }
    for code, factor in scale.items():
        statements.loc[latest & (statements["item_code"] == code), "value"] *= factor
    out = fn.fundamental_change(
        statements, _calendar(), ticker="TUPRS", as_of="2025-11-10", cpi=CPI
    )
    assert out["improvement_flags"] == [] and out["fundamental_trend"] == "Deteriorating"


def test_trend_needs_at_least_three_checks():
    out = fn.fundamental_change(_statements(), _calendar(), ticker="TUPRS", as_of="2024-08-12")
    assert out["period"] == "2024Q2" and out["fundamental_trend"] is None


def test_trend_at_an_earlier_date_ignores_later_statements():
    full = fn.fundamental_change(
        _statements(), _calendar(), ticker="TUPRS", as_of="2025-08-15", cpi=CPI
    )
    statements = _statements()
    cut = statements[~((statements["year"] == 2025) & (statements["quarter"] == 3))]
    calendar = _calendar()
    calendar = calendar[~((calendar["year"] == 2025) & (calendar["quarter"] == 3))]
    assert fn.fundamental_change(cut, calendar, ticker="TUPRS", as_of="2025-08-15", cpi=CPI) == full
