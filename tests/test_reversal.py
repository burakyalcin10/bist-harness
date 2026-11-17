"""Bollinger lower-band reversal summary, checked against the instructor's own script."""

import numpy as np
import pandas as pd
import pytest

from bist_harness.tools.reversal import bollinger_lower_touch_summary

from .instructor import scenario3


def _prices(seed: int, days: int = 900) -> pd.DataFrame:
    """A reproducible random-walk OHLCV frame that is volatile enough to touch the bands."""
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.025, days)))
    index = pd.date_range("2020-01-02", periods=days, freq="B")
    return pd.DataFrame(
        {
            "Open": close * (1 + rng.normal(0, 0.004, days)),
            "High": close * 1.015,
            "Low": close * 0.985,
            "Close": close,
            "Volume": rng.integers(1_000_000, 5_000_000, days).astype(float),
        },
        index=index,
    )


def _instructor_summary(df: pd.DataFrame, forward_days: int) -> pd.Series:
    ref = scenario3()
    out = ref.add_bollinger_bands(df)
    out = ref.add_rsi(out)
    out = ref.add_kama(out)
    out = ref.add_supertrend(out)
    out = ref.add_ichimoku(out)
    out = ref.add_volume_features(out)
    out = ref.add_forward_returns(out, forward_days=forward_days)
    out = ref.detect_reversal_events(out)
    return ref.event_summary(out, "Bollinger_Reversal", f"Forward_{forward_days}D_Return")


@pytest.mark.parametrize("seed", [1, 7, 42])
@pytest.mark.parametrize("forward_days", [5, 10])
def test_summary_equals_the_instructor_script(seed, forward_days):
    df = _prices(seed)
    expected = _instructor_summary(df, forward_days)
    ours = bollinger_lower_touch_summary(df, forward_days=forward_days)

    assert expected["Event_Count"] >= 5  # the fixture must actually exercise the event
    assert ours["event_count"] == int(expected["Event_Count"])
    assert ours["successful_events"] == int(expected["Successful_Events"])
    assert ours["success_rate_pct"] == round(float(expected["Success_Rate_%"]), 2)
    assert ours["average_forward_return_pct"] == round(
        float(expected["Average_Forward_Return_%"]), 2
    )
    assert ours["median_forward_return_pct"] == round(float(expected["Median_Forward_Return_%"]), 2)


def test_values_are_plain_python_numbers_rounded_to_two_decimals():
    summary = bollinger_lower_touch_summary(_prices(1))
    assert type(summary["event_count"]) is int
    assert type(summary["successful_events"]) is int
    for key in ("success_rate_pct", "average_forward_return_pct", "median_forward_return_pct"):
        assert type(summary[key]) is float
        assert summary[key] == round(summary[key], 2)


def test_no_events_gives_zero_count_and_no_statistics():
    index = pd.date_range("2020-01-02", periods=120, freq="B")
    flat = pd.DataFrame({"Close": np.linspace(100, 160, 120)}, index=index)  # steady rise
    assert bollinger_lower_touch_summary(flat) == {
        "event_count": 0,
        "successful_events": 0,
        "success_rate_pct": None,
        "average_forward_return_pct": None,
        "median_forward_return_pct": None,
        "sample_warning": "Very small sample size",
    }


@pytest.mark.parametrize(
    "days,expected_warning",
    [(150, "Very small sample size"), (400, "Limited sample size")],
)
def test_small_samples_carry_the_instructor_warning(days, expected_warning):
    df = _prices(3, days)
    summary = bollinger_lower_touch_summary(df)
    count = summary["event_count"]
    assert (count < 5) if expected_warning.startswith("Very") else (5 <= count < 20)
    assert summary["sample_warning"] == expected_warning


def test_large_sample_has_no_warning():
    summary = bollinger_lower_touch_summary(_prices(5, 3000))
    assert summary["event_count"] >= 20
    assert summary["sample_warning"] is None


def test_event_uses_only_data_up_to_the_event_day():
    """Truncating the future must not change which past days are events."""
    df = _prices(11)
    full = bollinger_lower_touch_summary(df, forward_days=5, return_event_dates=True)
    cut = bollinger_lower_touch_summary(df.iloc[:600], forward_days=5, return_event_dates=True)
    cutoff = df.index[600 - 5 - 1]  # events needing forward data beyond the cut are excluded
    assert [d for d in full["event_dates"] if d <= cutoff] == [
        d for d in cut["event_dates"] if d <= cutoff
    ]


def test_since_keeps_only_later_events_but_lets_earlier_rows_warm_up_the_bands():
    df = _prices(11)
    full = bollinger_lower_touch_summary(df, return_event_dates=True)
    since = "2021-06-01"
    late = bollinger_lower_touch_summary(df, since=since, return_event_dates=True)
    expected_dates = [d for d in full["event_dates"] if d >= pd.Timestamp(since)]
    assert late["event_dates"] == expected_dates
    assert late["event_count"] == len(expected_dates)
    assert 0 < late["event_count"] < full["event_count"]
