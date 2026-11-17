"""Point-in-time feature table and the strategy variants that read it."""

import pandas as pd
import pytest

from bist_harness.backtest import strategies
from bist_harness.data import kap
from bist_harness.data.peers import peer_group_of
from bist_harness.features.table import build_feature_table
from bist_harness.tools.sector import lag_score_series

from .synth import ohlcv
from .test_fundamentals_tools import CPI, _calendar, _statements
from .test_macro import _series as macro_series

TICKER = "TUPRS"
MEMBERS = peer_group_of(TICKER).members


def _history(symbol: str) -> pd.DataFrame:
    return ohlcv(700, seed=sum(map(ord, symbol)), start="2024-01-02")


def _disclosures() -> pd.DataFrame:
    rows = [
        ("2025-03-01 10:00:00", "dividend", 1),  # a Saturday: usable on Monday 2025-03-03
        ("2025-03-10 19:30:00", "contract", 2),  # after the close: usable on 2025-03-11
        ("2025-06-02 11:00:00", "regulation_legal", 3),  # before the close: usable that day
    ]
    return pd.DataFrame(
        [
            {
                "ticker": TICKER,
                "published_at": pd.Timestamp(p),
                "category": "ODA",
                "subject": topic,
                "summary": "",
                "disclosure_index": str(i),
                "url": "",
                "topic": topic,
            }
            for p, topic, i in rows
        ],
        columns=kap.COLUMNS,
    )


def _table(rows: int | None = None, **overrides) -> pd.DataFrame:
    cut = slice(None, rows)
    layers = {
        "peer_closes": {m: _history(m)["Close"].iloc[cut] for m in MEMBERS},
        "benchmark": _history("XU100")["Close"].iloc[cut],
        "statements": _statements(),
        "calendar": _calendar(),
        "cpi_index": CPI,
        "macro": macro_series(),
        "disclosures": _disclosures(),
    }
    layers.update(overrides)
    return build_feature_table(TICKER, _history(TICKER).iloc[cut], **layers)


def test_table_has_one_row_per_trading_day_and_every_layer():
    table = _table()
    assert table.index.equals(_history(TICKER).index)
    for column in [
        "rsi_state",
        "supertrend_state",
        "kama_slope",
        "ichimoku_state",
        "volume_regime",
        "entry_event",
        "bullish_events_60d",
        "bearish_events_60d",
        "lag_score_5d_pct",
        "lag_score_10d_pct",
        "lag_score_20d_pct",
        "lag_score_60d_pct",
        "sector_strong_20d",
        "fundamental_period",
        "fundamental_known_from",
        "fundamental_trend",
        "usdtry_change_20d_pct",
        "policy_rate",
        "policy_rate_raised_60d",
        "cpi_annual_pct",
        "cpi_published",
        "kap_events_5d",
        "kap_regulation_legal_5d",
        "info_date",
    ]:
        assert column in table.columns, column


def test_no_row_uses_information_dated_after_it():
    table = _table()
    assert (table["info_date"] <= table.index).all()
    known = table["fundamental_known_from"].dropna()
    assert (known <= known.index).all()
    published = table["cpi_published"].dropna()
    assert (published <= published.index).all()


def test_rows_do_not_change_when_later_prices_are_removed_while_other_layers_stay_complete():
    full = _table()
    cut = _table(rows=450)  # statements, macro and disclosures still hold later records
    pd.testing.assert_frame_equal(cut, full.iloc[:450], check_freq=False)


def test_a_new_quarter_appears_on_its_first_usable_day():
    table = _table()
    assert table.at[pd.Timestamp("2025-10-31"), "fundamental_period"] == "2025Q2"
    assert table.at[pd.Timestamp("2025-11-03"), "fundamental_period"] == "2025Q3"
    assert table.at[pd.Timestamp("2025-11-03"), "fundamental_trend"] == "Improving"
    assert table.at[pd.Timestamp("2025-11-03"), "fundamental_known_from"] == pd.Timestamp(
        "2025-11-03"
    )
    before_any = table.loc[: pd.Timestamp("2024-08-09"), "fundamental_period"]
    assert before_any.isna().all()


def test_lag_scores_are_those_of_the_sector_tool():
    table = _table()
    lag = lag_score_series(
        {m: _history(m)["Close"] for m in MEMBERS},
        peer_group_of(TICKER),
        TICKER,
        horizon_days=20,
        benchmark=_history("XU100")["Close"],
    )
    day = table.index[300]
    assert table.at[day, "lag_score_20d_pct"] == pytest.approx(lag.at[day, "lag_score"] * 100)
    assert bool(table.at[day, "sector_strong_20d"]) == bool(lag.at[day, "sector_strong"])


def test_policy_rate_and_its_raise_flag_follow_the_decision_dates():
    table = _table()
    # decisions: 2024-03-21 to 50.0 (a raise), 2024-12-26 to 47.5, 2025-01-23 to 45.0
    assert table.at[pd.Timestamp("2024-03-20"), "policy_rate"] == 7.0
    assert table.at[pd.Timestamp("2024-03-21"), "policy_rate"] == 50.0
    assert bool(table.at[pd.Timestamp("2024-03-20"), "policy_rate_raised_60d"]) is False
    assert bool(table.at[pd.Timestamp("2024-03-21"), "policy_rate_raised_60d"]) is True
    assert bool(table.at[pd.Timestamp("2024-05-17"), "policy_rate_raised_60d"]) is True
    assert bool(table.at[pd.Timestamp("2024-05-21"), "policy_rate_raised_60d"]) is False
    assert bool(table.at[pd.Timestamp("2025-01-24"), "policy_rate_raised_60d"]) is False


def test_cpi_is_the_latest_figure_published_by_that_day():
    table = _table()
    # the sample table: August 2026 published 2026-09-03, September on 2026-10-05
    assert pd.isna(table.at[pd.Timestamp("2026-09-02"), "cpi_annual_pct"])
    assert table.at[pd.Timestamp("2026-09-03"), "cpi_annual_pct"] == 31.51
    assert table.at[pd.Timestamp("2026-09-03"), "cpi_published"] == pd.Timestamp("2026-09-03")


def test_disclosures_count_from_the_first_close_after_their_publication():
    table = _table()
    count, legal = table["kap_events_5d"], table["kap_regulation_legal_5d"]
    assert count.at[pd.Timestamp("2025-02-28")] == 0
    assert count.at[pd.Timestamp("2025-03-03")] == 1  # Saturday's disclosure
    assert count.at[pd.Timestamp("2025-03-10")] == 0  # published at 19:30: not yet
    assert count.at[pd.Timestamp("2025-03-11")] == 1
    assert count.at[pd.Timestamp("2025-03-14")] == 1 and count.at[pd.Timestamp("2025-03-17")] == 0
    assert bool(legal.at[pd.Timestamp("2025-05-30")]) is False
    assert bool(legal.at[pd.Timestamp("2025-06-02")]) is True  # 11:00, before the close
    assert bool(legal.at[pd.Timestamp("2025-06-06")]) is True
    assert bool(legal.at[pd.Timestamp("2025-06-09")]) is False


def test_missing_layers_give_empty_columns_not_errors():
    table = _table(statements=None, calendar=None, macro=None, disclosures=None, cpi_index=None)
    assert table["fundamental_trend"].isna().all() and table["policy_rate"].isna().all()
    assert (table["kap_events_5d"] == 0).all() and not table["kap_regulation_legal_5d"].any()
    assert table["rsi_state"].notna().any()


def _context(features=True) -> strategies.StrategyContext:
    return strategies.StrategyContext(
        histories={TICKER: _history(TICKER)},
        peer_closes={m: _history(m)["Close"] for m in MEMBERS},
        benchmark=_history("XU100")["Close"],
        features={TICKER: _table()} if features else None,
    )


def test_each_later_variant_is_a_subset_of_the_one_before():
    context = _context()
    signal = {v: strategies.signals(v, context)[TICKER] for v in strategies.VARIANTS}
    order = list(strategies.VARIANTS)
    for earlier, later in zip(order, order[1:], strict=False):
        assert not (signal[later] & ~signal[earlier]).any(), (earlier, later)
    features = context.features[TICKER]
    c_days = signal["C_TECH_SECTOR_FUND"][signal["C_TECH_SECTOR_FUND"]].index
    assert (features.loc[c_days, "fundamental_trend"] == "Improving").all()
    d_days = signal["D_FULL_STRUCTURED"][signal["D_FULL_STRUCTURED"]].index
    assert not features.loc[d_days, "policy_rate_raised_60d"].any()
    e_days = signal["E_FULL_CONTEXTUAL"][signal["E_FULL_CONTEXTUAL"]].index
    assert not features.loc[e_days, "kap_regulation_legal_5d"].any()


def test_variant_c_drops_exactly_the_b_signals_without_an_improving_trend():
    context = _context()
    b = strategies.signals("B_TECH_SECTOR", context)[TICKER]
    c = strategies.signals("C_TECH_SECTOR_FUND", context)[TICKER]
    improving = context.features[TICKER]["fundamental_trend"] == "Improving"
    pd.testing.assert_series_equal(c, b & improving, check_names=False)


def test_variants_c_to_e_need_the_feature_table():
    with pytest.raises(ValueError, match="feature table"):
        strategies.signals("C_TECH_SECTOR_FUND", _context(features=False))


def test_information_dates_for_the_engine_are_the_statement_days():
    context = _context()
    dates = strategies.information_dates("C_TECH_SECTOR_FUND", context)[TICKER]
    features = context.features[TICKER]
    day = pd.Timestamp("2025-11-05")
    assert dates.at[day] == features.at[day, "fundamental_known_from"] == pd.Timestamp("2025-11-03")
    assert (dates <= dates.index).all()
    assert strategies.information_dates("A_TECHNICAL", context) is None
