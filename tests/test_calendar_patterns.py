"""Weekday and multi-day patterns: instructor parity, significance diagnostics, no look-ahead."""

import numpy as np
import pandas as pd
import pytest

from bist_harness.tools import calendar_patterns as cal
from bist_harness.tools.schemas import WEEKDAY_PATTERNS

from .instructor import scenario2

CONDITIONAL = [p for p in WEEKDAY_PATTERNS if p != "WEEKDAY_MEANS"]


def prices(returns: np.ndarray, start: str = "2020-01-06", index=None) -> pd.DataFrame:
    """Close prices whose daily returns are exactly ``returns`` (one extra base row first)."""
    if index is None:
        index = pd.date_range(start, periods=len(returns) + 1, freq="B")
    close = 100 * np.concatenate([[1.0], np.cumprod(1 + returns)])
    return pd.DataFrame({"Close": close}, index=index)


def random_returns(days: int = 1500, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0005, 0.02, days)


def weekday_of_returns(days: int, start: str = "2020-01-06") -> np.ndarray:
    return pd.date_range(start, periods=days + 1, freq="B")[1:].day_of_week.to_numpy()


def _instructor_frame(df: pd.DataFrame) -> pd.DataFrame:
    """The frame the instructor's loader builds, from our prices instead of a download."""
    out = df.copy()
    out["Return"] = out["Close"].pct_change()
    out["WeekdayNum"] = out.index.day_of_week
    out["Weekday"] = out["WeekdayNum"].map({0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"})
    iso = out.index.isocalendar()
    out["ISO_Year"] = iso.year.astype(int)
    out["ISO_Week"] = iso.week.astype(int)
    return out.dropna(subset=["Return"])


def test_patterns_are_the_schema_list():
    assert list(cal.PATTERNS) == WEEKDAY_PATTERNS


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_weekday_means_equal_the_instructor_statistics(seed):
    df = prices(random_returns(seed=seed))
    theirs = scenario2().weekday_statistics(_instructor_frame(df))
    out = cal.evaluate_pattern(df, "WEEKDAY_MEANS")
    assert [row["weekday"] for row in out["weekdays"]] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    for row in out["weekdays"]:
        expected = theirs.loc[row["weekday"]]
        assert row["observations"] == int(expected["Observations"])
        assert row["average_return_pct"] == round(float(expected["Average_Return"]), 2)
        assert row["median_return_pct"] == round(float(expected["Median_Return"]), 2)
        assert row["positive_rate_pct"] == round(float(expected["Positive_Rate"]), 2)
    assert out["occurrences"] == int(theirs["Observations"].sum())
    best = theirs["Average_Return"].idxmax()
    assert out["best_day"] == best and out["worst_day"] == theirs["Average_Return"].idxmin()


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_week_counts_equal_the_instructor_pattern_summary(seed):
    df = prices(random_returns(seed=seed))
    m = scenario2()
    weekly = m.detect_pattern(m.build_weekly_pattern_table(_instructor_frame(df)))
    theirs = m.pattern_summary(weekly)
    out = cal.evaluate_pattern(df, "THREE_DOWN_TWO_UP")
    assert out["complete_weeks"] == int(theirs["Complete weeks"])
    assert out["instructor_full_pattern_count"] == int(theirs["Pattern occurrences"])
    assert out["occurrences"] >= out["instructor_full_pattern_count"] > 0
    # The script's "return after the pattern" is positive by construction; ours is not.
    assert theirs["Positive Thu-Fri rate (%)"] == 100.0
    assert out["positive_rate_pct"] < 100.0


def test_time_split_is_at_the_instructor_split_point():
    df = prices(random_returns(days=999))
    prepared = cal.prepare(df)
    train, test = cal.split_by_time(prepared)
    theirs_train, theirs_test = scenario2().train_test_split_by_time(_instructor_frame(df))
    assert (len(train), len(test)) == (len(theirs_train), len(theirs_test)) == (699, 300)
    assert train.index[-1] == theirs_train.index[-1] and test.index[0] == theirs_test.index[0]


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("pattern", WEEKDAY_PATTERNS)
def test_random_walk_shows_no_significant_pattern_after_bonferroni(pattern, seed):
    out = cal.evaluate_pattern(prices(random_returns(seed=seed)), pattern)
    assert out["patterns_in_family"] == 5
    assert out["p_value_bonferroni"] == min(1.0, round(out["p_value"] * 5, 4))
    assert out["p_value_bonferroni"] >= 0.05
    assert "NOT_SIGNIFICANT" in out["interpretation_flags"]


def _monday_effect(days: int = 1500, seed: int = 1, until: int | None = None) -> pd.DataFrame:
    """Random returns, plus 1% on Friday in weeks that began with a negative Monday."""
    returns = random_returns(days, seed)
    weekday = weekday_of_returns(days)
    for i in np.flatnonzero(weekday == 0):
        if i + 4 < days and returns[i] < 0 and (until is None or i < until):
            returns[i + 4] += 0.01
    return prices(returns)


def test_an_injected_monday_friday_effect_is_found_significant():
    out = cal.evaluate_pattern(_monday_effect(), "MON_WEAK_FRI_STRONG")
    assert out["p_value_bonferroni"] < 0.05
    assert out["interpretation_flags"] == []
    assert out["conditional_mean_return_pct"] > out["unconditional_mean_return_pct"] + 0.3
    assert out["mean_after_cost_pct"] == round(out["conditional_mean_return_pct"] - 0.1, 2)
    assert out["train"]["occurrences"] + out["test"]["occurrences"] <= out["occurrences"]
    assert out["sample_warning"] is None


def test_an_effect_that_exists_only_in_the_first_part_is_flagged_unstable():
    out = cal.evaluate_pattern(_monday_effect(until=600, seed=4), "MON_WEAK_FRI_STRONG")
    train_excess = (
        out["train"]["conditional_mean_return_pct"] - out["train"]["unconditional_mean_return_pct"]
    )
    test_excess = (
        out["test"]["conditional_mean_return_pct"] - out["test"]["unconditional_mean_return_pct"]
    )
    assert train_excess > 0
    assert ("UNSTABLE_OUT_OF_SAMPLE" in out["interpretation_flags"]) == (test_excess <= 0)


@pytest.mark.parametrize("pattern", ["MON_WEAK_FRI_STRONG", "THREE_DOWN_TWO_UP"])
def test_the_condition_reads_only_days_before_the_outcome(pattern):
    returns = random_returns()
    weekday = weekday_of_returns(len(returns))
    base = cal.evaluate_pattern(prices(returns), pattern)
    changed = returns.copy()
    changed[weekday >= 3] += 0.03  # Thursdays and Fridays are the outcome days
    after = cal.evaluate_pattern(prices(changed), pattern)
    assert after["occurrences"] == base["occurrences"] > 0
    assert after["conditional_mean_return_pct"] > base["conditional_mean_return_pct"]


def test_large_drop_condition_uses_volatility_known_before_the_drop():
    returns = np.full(200, 0.001)
    returns[::2] = -0.001  # quiet series: daily moves of 0.1%
    returns[150] = -0.05  # one large drop
    returns[151] = 0.02  # the day after
    out = cal.evaluate_pattern(prices(returns), "POST_LARGE_DOWN_REVERSION")
    assert out["occurrences"] == 1
    assert out["conditional_mean_return_pct"] == 2.0
    assert out["mean_after_cost_pct"] == 1.9
    assert out["sample_warning"] == "Very small sample size"

    later = returns.copy()
    later[151:] = 0.0
    assert cal.evaluate_pattern(prices(later), "POST_LARGE_DOWN_REVERSION")["occurrences"] == 1


def test_end_of_week_continuation_measures_fridays_in_the_direction_of_the_week():
    days = 1000
    returns = random_returns(days, seed=7)
    weekday = weekday_of_returns(days)
    for i in np.flatnonzero(weekday == 4):  # Friday follows the sign of Monday to Thursday
        if i >= 4:
            week = np.prod(1 + returns[i - 4 : i]) - 1
            returns[i] = 0.01 * np.sign(week)
    out = cal.evaluate_pattern(prices(returns), "END_OF_WEEK_CONTINUATION")
    assert out["positive_rate_pct"] == 100.0
    assert out["conditional_mean_return_pct"] == 1.0
    assert out["p_value_bonferroni"] < 0.05
    assert "NOT_SIGNIFICANT" not in out["interpretation_flags"]


def test_weeks_with_a_missing_day_are_skipped_and_counted():
    df = prices(random_returns(days=300))
    full = cal.evaluate_pattern(df, "MON_WEAK_FRI_STRONG")
    holiday = df.index[df.index.day_of_week == 2][10]  # a Wednesday in the middle
    cut = cal.evaluate_pattern(df.drop(holiday), "MON_WEAK_FRI_STRONG")
    assert cut["complete_weeks"] == full["complete_weeks"] - 1
    assert cut["incomplete_weeks_skipped"] == full["incomplete_weeks_skipped"] + 1


@pytest.mark.parametrize("pattern", WEEKDAY_PATTERNS)
def test_the_same_input_gives_the_same_p_value(pattern):
    df = prices(random_returns(days=600, seed=9))
    first, second = cal.evaluate_pattern(df, pattern), cal.evaluate_pattern(df, pattern)
    assert first == second and 0 < first["p_value"] <= 1


def test_negative_after_cost_is_flagged_when_the_edge_is_smaller_than_the_cost():
    out = cal.evaluate_pattern(prices(random_returns(seed=2)), "MON_WEAK_FRI_STRONG")
    assert (out["mean_after_cost_pct"] <= 0) == (
        "NEGATIVE_AFTER_COST" in out["interpretation_flags"]
    )


def test_since_limits_the_period_but_keeps_the_first_return():
    df = prices(random_returns(days=600))
    since = df.index[300]
    out = cal.evaluate_pattern(df, "WEEKDAY_MEANS", since=str(since.date()))
    assert out["occurrences"] == 301


@pytest.mark.parametrize("pattern", CONDITIONAL)
def test_a_series_too_short_for_any_occurrence_reports_nothing(pattern):
    out = cal.evaluate_pattern(prices(np.full(3, 0.001)), pattern)
    assert out["occurrences"] == 0 and out["conditional_mean_return_pct"] is None
    assert out["p_value"] is None and out["p_value_bonferroni"] is None
    assert out["sample_warning"] == "Very small sample size"
    assert "NOT_SIGNIFICANT" in out["interpretation_flags"]


def test_unknown_pattern_is_rejected():
    with pytest.raises(ValueError):
        cal.evaluate_pattern(prices(random_returns(days=50)), "FULL_MOON")
