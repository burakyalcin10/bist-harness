"""Reversal event families: equal to the instructor's script, mirrored, and free of look-ahead."""

import numpy as np
import pandas as pd
import pytest

from bist_harness.tools import events as ev
from bist_harness.tools.indicators import add_all_indicators, indicator_state
from bist_harness.tools.schemas import REVERSAL_EVENT_TYPES

from .instructor import scenario3
from .synth import ohlcv
from .test_support_resistance import SERIES

SEEDS = [1, 2, 3]
INSTRUCTOR_COLUMNS = {
    "BOLLINGER_LOWER_TOUCH": "Bollinger_Reversal",
    "RSI_LOCAL_TROUGH": "RSI_Local_Trough",
    "KAMA_TURN": "KAMA_Bullish_Turn",
    "ICHIMOKU_BREAKOUT": "Ichimoku_Bullish_Breakout",
}
ALL_CASES = [(t, d) for t in REVERSAL_EVENT_TYPES for d in ("BULLISH", "BEARISH")]


def _instructor_frame(df: pd.DataFrame, forward_days: int) -> pd.DataFrame:
    m = scenario3()
    out = m.add_kama(m.add_rsi(m.add_bollinger_bands(df)))
    out = m.add_volume_features(m.add_ichimoku(m.add_supertrend(out)))
    return m.detect_reversal_events(m.add_forward_returns(out, forward_days))


def test_event_types_are_the_schema_list():
    assert list(ev.EVENT_TYPES) == REVERSAL_EVENT_TYPES


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("event_type", INSTRUCTOR_COLUMNS)
@pytest.mark.parametrize("forward_days", [5, 10])
def test_mask_and_summary_equal_the_instructor_script(event_type, seed, forward_days):
    df = ohlcv(600, seed)
    theirs = _instructor_frame(df, forward_days)
    column = INSTRUCTOR_COLUMNS[event_type]
    mask = ev.event_mask(add_all_indicators(df), event_type, "BULLISH")
    pd.testing.assert_series_equal(mask, theirs[column].astype(bool), check_names=False)

    expected = scenario3().event_summary(theirs, column, f"Forward_{forward_days}D_Return")
    ours = ev.summarize_events(df, mask, direction="BULLISH", forward_days=forward_days)
    assert ours["event_count"] == expected["Event_Count"] > 0
    assert ours["successful_events"] == expected["Successful_Events"]
    assert ours["success_rate_pct"] == round(float(expected["Success_Rate_%"]), 2)
    assert ours["average_forward_return_pct"] == round(
        float(expected["Average_Forward_Return_%"]), 2
    )
    assert ours["median_forward_return_pct"] == round(float(expected["Median_Forward_Return_%"]), 2)


def _mirrored(df: pd.DataFrame) -> pd.DataFrame:
    """Reflect prices around a constant: highs become lows, rises become falls."""
    top = 1000.0
    return pd.DataFrame(
        {
            "Open": top - df["Open"],
            "High": top - df["Low"],
            "Low": top - df["High"],
            "Close": top - df["Close"],
            "Volume": df["Volume"],
        },
        index=df.index,
    )


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize(
    "bullish,bearish",
    [
        ("BOLLINGER_LOWER_TOUCH", "BOLLINGER_UPPER_TOUCH"),
        ("RSI_LOCAL_TROUGH", "RSI_LOCAL_PEAK"),
        ("KAMA_TURN", "KAMA_TURN"),
        ("ICHIMOKU_BREAKOUT", "ICHIMOKU_BREAKOUT"),
        ("BOLLINGER_MIDDLE_TEST", "BOLLINGER_MIDDLE_TEST"),
    ],
)
def test_bearish_event_on_reflected_prices_is_the_bullish_event(bullish, bearish, seed):
    df = ohlcv(600, seed, vol=0.012)
    up = ev.event_mask(add_all_indicators(df), bullish, "BULLISH")
    down = ev.event_mask(add_all_indicators(_mirrored(df)), bearish, "BEARISH")
    pd.testing.assert_series_equal(up, down, check_names=False)
    assert up.sum() > 0


@pytest.mark.parametrize("event_type,direction", ALL_CASES)
def test_events_up_to_day_t_do_not_change_when_later_data_is_removed(event_type, direction):
    df = ohlcv(500, 11)
    full = ev.event_mask(add_all_indicators(df), event_type, direction)
    for k in (250, 401):
        cut = ev.event_mask(add_all_indicators(df.iloc[:k]), event_type, direction)
        pd.testing.assert_series_equal(cut, full.iloc[:k], check_names=False)
    assert full.dtype == bool


@pytest.mark.parametrize("event_type,direction", ALL_CASES)
def test_every_family_finds_events_on_a_long_random_walk(event_type, direction):
    df = add_all_indicators(ohlcv(1200, 21))
    assert ev.event_mask(df, event_type, direction).sum() > 0


def test_single_direction_families_ignore_the_requested_direction():
    df = add_all_indicators(ohlcv(400, 2))
    for event_type, actual in [
        ("BOLLINGER_LOWER_TOUCH", "BULLISH"),
        ("RSI_LOCAL_TROUGH", "BULLISH"),
        ("BOLLINGER_UPPER_TOUCH", "BEARISH"),
        ("RSI_LOCAL_PEAK", "BEARISH"),
    ]:
        assert ev.effective_direction(event_type, "BULLISH") == actual
        assert ev.effective_direction(event_type, "BEARISH") == actual
        pd.testing.assert_series_equal(
            ev.event_mask(df, event_type, "BULLISH"), ev.event_mask(df, event_type, "BEARISH")
        )
    assert ev.effective_direction("KAMA_TURN", "BEARISH") == "BEARISH"


def test_supertrend_flips_alternate_and_match_the_direction_column():
    df = add_all_indicators(ohlcv(800, 3))
    up = ev.event_mask(df, "SUPERTREND_FLIP", "BULLISH")
    down = ev.event_mask(df, "SUPERTREND_FLIP", "BEARISH")
    pd.testing.assert_series_equal(
        up, df["Supertrend_Bullish_Flip"].astype(bool), check_names=False
    )
    assert (df.loc[down, "Supertrend_Direction"] == -1).all()
    sequence = [("up" if up[d] else "down") for d in df.index[up | down]]
    assert all(a != b for a, b in zip(sequence, sequence[1:], strict=False))
    assert len(sequence) > 4


def test_bollinger_middle_test_fires_on_the_first_dip_to_the_middle_band():
    close = 100.0 + np.arange(40.0)
    index = pd.date_range("2024-01-01", periods=40, freq="B")
    df = pd.DataFrame(
        {"Open": close, "High": close + 0.5, "Low": close - 0.5, "Close": close, "Volume": 1.0},
        index=index,
    )
    df.iloc[30, df.columns.get_loc("Low")] = 100.0  # dips through the middle band, closes above
    mask = ev.event_mask(add_all_indicators(df), "BOLLINGER_MIDDLE_TEST", "BULLISH")
    assert [df.index.get_loc(d) for d in mask[mask].index] == [30]
    assert ev.event_mask(add_all_indicators(df), "BOLLINGER_MIDDLE_TEST", "BEARISH").sum() == 0


def test_support_and_resistance_touches_on_a_zigzag():
    df = add_all_indicators(SERIES)

    def days(direction):
        mask = ev.event_mask(df, "SUPPORT_RESISTANCE_TOUCH", direction)
        return [df.index.get_loc(d) for d in mask[mask].index]

    # Support 99.8 (pivot low on day 20, known on day 25) is approached again on day 39.
    assert days("BULLISH") == [39]
    # Resistance 110.2 (pivot high on day 10) is approached on days 29 and 47, and tested
    # from below again on day 54 after the price fell back through it.
    assert days("BEARISH") == [29, 47, 54]


def test_summary_counts_success_by_direction_and_measures_reversal_strength():
    index = pd.date_range("2024-01-01", periods=8, freq="B")
    close = pd.Series([100, 100, 104, 102, 98, 100, 100, 100.0], index=index)
    df = pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1.0}
    )
    mask = pd.Series(False, index=index)
    mask.iloc[[1, 2]] = True

    up = ev.summarize_events(df, mask, direction="BULLISH", forward_days=2)
    # day 1: 100 -> 102 (+2%), day 2: 104 -> 98 (-5.77%)
    assert (up["event_count"], up["successful_events"], up["success_rate_pct"]) == (2, 1, 50.0)
    assert up["average_forward_return_pct"] == round((2.0 + (98 / 104 - 1) * 100) / 2, 2)
    # strongest high in the next two days: day 1 -> 105 (+5%), day 2 -> 103 (-0.96%)
    assert up["average_reversal_strength_pct"] == round((5.0 + (103 / 104 - 1) * 100) / 2, 2)

    down = ev.summarize_events(df, mask, direction="BEARISH", forward_days=2)
    assert (down["event_count"], down["successful_events"]) == (2, 1)
    # lowest low in the next two days: day 1 -> 101 (strength -1%), day 2 -> 97 (6.73%)
    assert down["average_reversal_strength_pct"] == round((-1.0 + (1 - 97 / 104) * 100) / 2, 2)
    assert up["sample_warning"] == "Very small sample size"


def test_summary_without_events_has_zero_count_and_no_statistics():
    df = ohlcv(100, 1)
    out = ev.summarize_events(df, pd.Series(False, index=df.index), direction="BULLISH")
    assert out["event_count"] == 0 and out["successful_events"] == 0
    for key in ("success_rate_pct", "average_forward_return_pct", "median_reversal_strength_pct"):
        assert out[key] is None
    assert out["sample_warning"] == "Very small sample size"


def test_since_keeps_warm_up_rows_but_drops_earlier_events():
    df = ohlcv(600, 2)
    mask = ev.event_mask(add_all_indicators(df), "KAMA_TURN", "BULLISH")
    since = df.index[300]
    out = ev.summarize_events(df, mask, direction="BULLISH", since=str(since.date()))
    forward = (df["Close"].shift(-5) / df["Close"] - 1).notna()
    assert out["event_count"] == int((mask & forward).loc[since:].sum())


def test_market_state_equals_the_indicator_labels_of_that_day():
    df = add_all_indicators(ohlcv(400, 4))
    for position in (5, 60, 199, 399):
        day = df.index[position]
        labels = indicator_state(df.iloc[: position + 1], [])
        assert ev.market_state(df, day) == {
            "rsi_state": labels["rsi_state"],
            "supertrend_state": labels["supertrend_state"],
            "kama_slope": labels["kama_slope_state"],
            "ichimoku_state": labels["ichimoku_state"],
            "volume_regime": labels["volume_regime"],
        }


def test_event_records_carry_the_market_state_and_forward_returns():
    raw = ohlcv(600, 2)
    df = add_all_indicators(raw)
    mask = ev.event_mask(df, "RSI_LOCAL_TROUGH")
    records = ev.event_records(
        df, mask, ticker="ASELS", event_type="RSI_LOCAL_TROUGH", direction="BULLISH"
    )
    assert list(records.columns) == [
        "ticker",
        "event",
        "direction",
        "date",
        "rsi_state",
        "supertrend_state",
        "kama_slope",
        "ichimoku_state",
        "volume_regime",
        "forward_1d_return_pct",
        "forward_3d_return_pct",
        "forward_5d_return_pct",
        "forward_10d_return_pct",
        "reversal_strength_pct",
    ]
    assert len(records) == int(mask.sum())
    first = records.iloc[0]
    position = raw.index.get_loc(pd.Timestamp(first["date"]))
    assert first["rsi_state"] == "Local Low" and first["event"] == "RSI_LOCAL_TROUGH"
    expected = (raw["Close"].iloc[position + 3] / raw["Close"].iloc[position] - 1) * 100
    assert first["forward_3d_return_pct"] == round(float(expected), 2)


def test_detect_events_adds_direction_definition_and_family_specific_counts():
    df = ohlcv(900, 6)
    middle = ev.detect_events(df, "BOLLINGER_MIDDLE_TEST", "BULLISH", forward_days=5)
    assert middle["direction"] == "BULLISH" and middle["definition"]
    assert middle["continuation_count"] == middle["successful_events"]
    assert middle["continuation_count"] + middle["rejection_count"] == middle["event_count"]

    ichimoku = ev.detect_events(df, "ICHIMOKU_BREAKOUT", "BEARISH")
    assert 0 <= ichimoku["rejection_count"] <= ichimoku["event_count"]
    assert "continuation_count" not in ichimoku

    lower = ev.detect_events(df, "BOLLINGER_LOWER_TOUCH", "BEARISH")
    assert lower["direction"] == "BULLISH"
    assert "rejection_count" not in lower


def test_detect_events_reports_recent_events_that_cannot_be_evaluated_yet():
    df = ohlcv(600, 2)
    mask = ev.event_mask(add_all_indicators(df), "KAMA_TURN", "BULLISH")
    last_event = mask[mask].index[-1]
    cut = df.loc[: last_event + pd.offsets.BDay(2)]
    out = ev.detect_events(cut, "KAMA_TURN", "BULLISH", forward_days=5)
    assert out["last_event_date"] == str(last_event.date())
    assert out["pending_events"] >= 1
    assert out["event_count"] == int(mask.loc[: cut.index[-6]].sum())


def test_detect_events_rejects_unknown_types_and_directions():
    df = ohlcv(100, 1)
    with pytest.raises(ValueError):
        ev.detect_events(df, "MOON_PHASE")
    with pytest.raises(ValueError):
        ev.detect_events(df, "KAMA_TURN", "SIDEWAYS")


def test_short_history_gives_zero_events_and_a_small_sample_warning():
    out = ev.detect_events(ohlcv(40, 1), "ICHIMOKU_BREAKOUT")
    assert out["event_count"] == 0 and out["sample_warning"] == "Very small sample size"
