"""Discovery and test periods, and the market-regime label."""

import pandas as pd
import pytest

from bist_harness.backtest import periods

from .synth import ohlcv


@pytest.mark.parametrize(
    "day,expected",
    [
        ("2019-12-31", None),
        ("2020-01-01", "discovery"),
        ("2024-12-31", "discovery"),
        ("2025-01-01", "test"),
        ("2026-11-13", "test"),
        ("2026-11-14", None),
    ],
)
def test_boundary_days_fall_into_the_right_period(day, expected):
    assert periods.period_of(day) == expected
    assert periods.period_of(pd.Timestamp(day)) == expected


def test_periods_do_not_overlap_and_test_follows_discovery():
    assert pd.Timestamp(periods.DISCOVERY[1]) < pd.Timestamp(periods.TEST[0])
    assert pd.Timestamp(periods.DISCOVERY[0]) < pd.Timestamp(periods.DISCOVERY[1])
    assert pd.Timestamp(periods.TEST[0]) < pd.Timestamp(periods.TEST[1])


def test_a_request_is_split_into_its_period_parts():
    assert periods.split_period("2023-01-01", "2025-06-30") == {
        "discovery": ("2023-01-01", "2024-12-31"),
        "test": ("2025-01-01", "2025-06-30"),
    }
    assert periods.split_period("2021-03-01", "2021-09-30") == {
        "discovery": ("2021-03-01", "2021-09-30")
    }
    assert periods.split_period("2018-01-01", "2019-06-30") == {}
    assert periods.split_period("2026-01-01", "2027-01-01") == {
        "test": ("2026-01-01", "2026-11-13")
    }


def test_market_regime_compares_the_close_with_its_200_day_average():
    close = ohlcv(600, 3, drift=0.0)["Close"]
    regime = periods.market_regime(close)
    assert regime.iloc[:199].isna().all() and regime.iloc[199:].notna().all()
    average = close.rolling(200).mean()
    day = close.index[400]
    assert regime[day] == ("Uptrend" if close[day] > average[day] else "Downtrend")
    assert set(regime.dropna()) == {"Uptrend", "Downtrend"}


def test_market_regime_does_not_change_when_later_data_is_removed():
    close = ohlcv(600, 3, drift=0.0)["Close"]
    full = periods.market_regime(close)
    cut = periods.market_regime(close.iloc[:450])
    pd.testing.assert_series_equal(cut, full.iloc[:450])
