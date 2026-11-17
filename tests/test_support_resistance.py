"""Support and resistance: pivots, clustering, strength order and no look-ahead."""

import numpy as np
import pandas as pd

from bist_harness.tools.support_resistance import find_pivots, find_support_resistance


def zigzag(points: list[tuple[int, float]]) -> pd.DataFrame:
    """Straight lines between (day, price) turning points; bars reach 0.2 beyond the close."""
    days = np.arange(points[-1][0] + 1)
    close = np.interp(days, [d for d, _ in points], [p for _, p in points])
    index = pd.date_range("2024-01-01", periods=len(days), freq="B")
    return pd.DataFrame(
        {"Open": close, "High": close + 0.2, "Low": close - 0.2, "Close": close, "Volume": 1000.0},
        index=index,
    )


SERIES = zigzag([(0, 100), (10, 110), (20, 100), (30, 110), (40, 100), (50, 112), (60, 104)])


def _days(mask: pd.Series) -> list[int]:
    return [SERIES.index.get_loc(day) for day in mask[mask].index]


def test_pivots_are_the_extremes_of_a_centred_window_and_known_five_days_later():
    pivots = find_pivots(SERIES, window=5)
    assert _days(pivots["pivot_high"]) == [10, 30, 50]
    assert _days(pivots["pivot_low"]) == [20, 40]
    assert pivots["known_from"].iloc[10] == SERIES.index[15]
    assert pd.isna(pivots["known_from"].iloc[58])


def test_close_pivots_form_one_level_and_a_distant_pivot_stays_separate():
    df = zigzag([(0, 100), (10, 110), (20, 100), (30, 110.5), (40, 100), (50, 120), (60, 106)])
    levels = find_support_resistance(df)
    resistance = sorted((lv["level"], lv["touches"]) for lv in levels if lv["kind"] == "resistance")
    assert resistance == [(110.45, 2), (120.2, 1)]
    support = [lv for lv in levels if lv["kind"] == "support"]
    assert [(lv["level"], lv["touches"]) for lv in support] == [(99.8, 2)]
    assert support[0]["last_touch_date"] == str(df.index[40].date())


def test_a_pivot_is_invisible_until_its_window_is_complete():
    def has_level_112(as_of):
        levels = find_support_resistance(SERIES, as_of=str(as_of.date()))
        return any(lv["level"] == 112.2 for lv in levels)

    assert not has_level_112(SERIES.index[54])
    assert has_level_112(SERIES.index[55])


def test_levels_do_not_change_when_later_data_is_removed():
    as_of = SERIES.index[47]
    with_future = find_support_resistance(SERIES, as_of=str(as_of.date()))
    without_future = find_support_resistance(SERIES.loc[:as_of])
    assert with_future == without_future and with_future


def test_levels_are_ordered_by_strength_and_capped():
    levels = find_support_resistance(SERIES)
    strengths = [lv["strength"] for lv in levels]
    assert strengths == sorted(strengths, reverse=True) and len(levels) == 3
    assert len(find_support_resistance(SERIES, max_levels=2)) == 2
    assert find_support_resistance(SERIES, max_levels=2) == levels[:2]


def test_recent_touches_count_only_the_last_sixty_trading_days():
    points = [(d, 110.0 if (d // 10) % 2 else 100.0) for d in range(0, 201, 10)]
    levels = find_support_resistance(zigzag(points))
    resistance = next(lv for lv in levels if lv["kind"] == "resistance")
    assert (resistance["touches"], resistance["recent_touches"]) == (10, 3)


def test_high_volume_reactions_and_reversal_strength_raise_the_score():
    quiet = find_support_resistance(SERIES)
    loud_frame = SERIES.copy()
    loud_frame.iloc[30, loud_frame.columns.get_loc("Volume")] = 5000.0
    loud = find_support_resistance(loud_frame)
    quiet_110 = next(lv for lv in quiet if lv["level"] == 110.2)
    loud_110 = next(lv for lv in loud if lv["level"] == 110.2)
    assert loud_110["strength"] == round(quiet_110["strength"] + 1.2, 2)
    # 2 touches, both recent, no volume reaction, 4.72% average move away within 5 days
    assert quiet_110["strength"] == round(2 * 1.0 + 2 * 1.5 + 0 * 1.2 + 4.72, 2)


def test_short_series_gives_no_levels():
    assert find_support_resistance(SERIES.iloc[:15]) == []
    assert find_support_resistance(SERIES.iloc[:0]) == []
