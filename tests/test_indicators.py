"""Technical indicators: equal to the instructor's script, no look-ahead, safe on short data."""

import numpy as np
import pandas as pd
import pytest

from bist_harness.tools import indicators as ind

from .instructor import scenario3
from .synth import ohlcv

SEEDS = [1, 2, 3]
INSTRUCTOR_FUNCTIONS = [
    "add_bollinger_bands",
    "add_rsi",
    "add_kama",
    "add_atr",
    "add_ichimoku",
    "add_volume_features",
]
ALL_FUNCTIONS = [
    *INSTRUCTOR_FUNCTIONS,
    "add_supertrend",
    "add_sma",
    "add_ema",
    "add_macd",
    "add_all_indicators",
]


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("name", INSTRUCTOR_FUNCTIONS)
def test_output_equals_the_instructor_script(name, seed):
    df = ohlcv(400, seed)
    ours = getattr(ind, name)(df)
    theirs = getattr(scenario3(), name)(df)
    pd.testing.assert_frame_equal(ours[theirs.columns], theirs, check_exact=False, rtol=1e-9)
    assert list(ours.columns) == list(theirs.columns)


def _ema(values, span):
    alpha, out = 2 / (span + 1), [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def test_sma_ema_and_macd_on_a_hand_calculated_series():
    df = pd.DataFrame({"Close": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})
    sma = ind.add_sma(df, 3)["SMA_3"]
    assert sma.isna().tolist() == [True, True, False, False, False, False]
    assert sma.dropna().tolist() == [2.0, 3.0, 4.0, 5.0]
    assert ind.add_ema(df, 3)["EMA_3"].tolist() == [1.0, 1.5, 2.25, 3.125, 4.0625, 5.03125]

    macd = ind.add_macd(df, fast=2, slow=3, signal=2)
    line = [
        f - s
        for f, s in zip(_ema(df["Close"].tolist(), 2), _ema(df["Close"].tolist(), 3), strict=True)
    ]
    signal = _ema(line, 2)
    assert macd["MACD"].tolist() == pytest.approx(line)
    assert macd["MACD_Signal"].tolist() == pytest.approx(signal)
    assert macd["MACD_Hist"].tolist() == pytest.approx(
        [a - b for a, b in zip(line, signal, strict=True)]
    )


@pytest.mark.parametrize("name", ALL_FUNCTIONS)
def test_values_up_to_day_t_do_not_change_when_later_data_is_removed(name):
    df = ohlcv(300, 5)
    function = getattr(ind, name)
    full = function(df)
    for k in (120, 201, 299):
        pd.testing.assert_frame_equal(
            function(df.iloc[:k]), full.iloc[:k], check_exact=False, rtol=1e-9
        )


@pytest.mark.parametrize("rows", [0, 1, 5, 30])
def test_short_series_gives_nan_columns_instead_of_an_error(rows):
    out = ind.add_all_indicators(ohlcv(60, 2).iloc[:rows])
    assert len(out) == rows
    if rows == 30:
        assert out["SMA_50"].isna().all() and out["Senkou_B"].isna().all()
        assert out["SMA_20"].notna().sum() == 11
    state = ind.indicator_state(out, [])
    if rows < 20:
        assert state["sma_20"] is None and state["supertrend_state"] in (None, "Bullish", "Bearish")


def test_indicator_state_reports_last_day_values_rounded_to_two_decimals():
    df = ind.add_all_indicators(ohlcv(400, 7))
    last = df.iloc[-1]
    state = ind.indicator_state(df, [])
    assert state["as_of"] == str(df.index[-1].date())
    assert state["close"] == round(float(last["Close"]), 2)
    for key, column in [
        ("sma_20", "SMA_20"),
        ("sma_50", "SMA_50"),
        ("ema_20", "EMA_20"),
        ("macd", "MACD"),
        ("macd_signal", "MACD_Signal"),
        ("rsi", "RSI"),
        ("kama", "KAMA"),
        ("atr", "ATR"),
        ("supertrend", "Supertrend"),
        ("bb_upper", "BB_Upper"),
        ("bb_lower", "BB_Lower"),
        ("cloud_top", "Cloud_Top"),
        ("cloud_bottom", "Cloud_Bottom"),
    ]:
        assert state[key] == round(float(last[column]), 2), key
    assert state["supertrend_state"] == (
        "Bullish" if last["Supertrend_Direction"] == 1 else "Bearish"
    )
    assert state["macd_state"] == ("Bullish" if last["MACD"] > last["MACD_Signal"] else "Bearish")


def test_indicator_state_returns_only_the_requested_groups():
    df = ind.add_all_indicators(ohlcv(200, 7))
    state = ind.indicator_state(df, ["RSI", "ATR"])
    assert set(state) == {"as_of", "close", "rsi", "rsi_state", "atr", "atr_pct"}
    with pytest.raises(ValueError):
        ind.indicator_state(df, ["MOON"])


def _frame(**columns):
    index = pd.date_range("2024-01-01", periods=len(next(iter(columns.values()))), freq="B")
    return pd.DataFrame(columns, index=index)


@pytest.mark.parametrize(
    "rsi,expected",
    [
        ([50, 35, 42], "Local Low"),  # trough yesterday below 40, confirmed today
        ([50, 45, 48], "Neutral"),  # trough but not below 40
        ([50, 70, 65], "Local High"),  # peak yesterday above 60
        ([50, 55, 52], "Neutral"),
        ([30, 28, 25], "Neutral"),  # still falling: no trough yet
    ],
)
def test_rsi_state_uses_the_instructor_trough_and_its_mirror(rsi, expected):
    padded = [50.0] * 12 + [float(v) for v in rsi]  # 15 rows: the RSI warm-up is over
    df = _frame(Close=[10.0] * 15, RSI=padded)
    assert ind.indicator_state(df, ["RSI"])["rsi_state"] == expected


@pytest.mark.parametrize(
    "slope,expected",
    [(0.2, "Rising"), (-0.2, "Falling"), (0.04, "Flattening"), (-0.04, "Flattening")],
)
def test_kama_slope_is_flat_below_five_hundredths_of_a_percent_of_the_close(slope, expected):
    df = _frame(Close=[100.0, 100.0], KAMA=[99.0, 99.0 + slope], KAMA_Slope=[np.nan, slope])
    assert ind.indicator_state(df, ["KAMA"])["kama_slope_state"] == expected


@pytest.mark.parametrize(
    "close,expected", [(12.0, "Above Cloud"), (10.5, "In Cloud"), (9.0, "Below Cloud")]
)
def test_ichimoku_state_compares_the_close_with_todays_cloud(close, expected):
    df = _frame(
        Close=[close],
        Tenkan=[10.0],
        Kijun=[10.0],
        Senkou_A=[11.0],
        Senkou_B=[10.0],
        Cloud_Top=[11.0],
        Cloud_Bottom=[10.0],
    )
    assert ind.indicator_state(df, ["ICHIMOKU"])["ichimoku_state"] == expected


@pytest.mark.parametrize("volume,expected", [(160.0, "High"), (100.0, "Normal"), (40.0, "Low")])
def test_volume_regime_thresholds(volume, expected):
    df = _frame(Close=[1.0], Volume=[volume], Volume_MA=[100.0])
    assert ind.indicator_state(df, ["VOLUME"])["volume_regime"] == expected


@pytest.mark.parametrize(
    "close,expected",
    [(13.0, "Above Upper"), (11.5, "Upper Half"), (10.5, "Lower Half"), (9.0, "Below Lower")],
)
def test_bollinger_position(close, expected):
    df = _frame(Close=[close], BB_Upper=[12.0], BB_Middle=[11.0], BB_Lower=[10.0])
    assert ind.indicator_state(df, ["BOLLINGER"])["bollinger_position"] == expected


@pytest.mark.parametrize("seed", SEEDS)
def test_the_instructor_supertrend_never_produces_a_value(seed):
    """Documents a defect of the course script: the ATR gap of the first days is carried
    through the band recursion forever, so the line is always NaN and no flip is found."""
    theirs = scenario3().add_supertrend(ohlcv(400, seed))
    assert theirs["Supertrend"].notna().sum() == 0
    assert set(theirs["Supertrend_Direction"].iloc[1:]) == {1.0}
    assert theirs["Supertrend_Bullish_Flip"].sum() == 0


@pytest.mark.parametrize("seed", SEEDS)
def test_supertrend_recursion_equals_the_instructor_loop_once_its_atr_has_no_gap(seed, monkeypatch):
    module = scenario3()
    original = module.add_atr

    def atr_without_gap(df, period=10):
        out = original(df, period=period)
        out["ATR"] = out["ATR"].bfill()
        return out

    monkeypatch.setattr(module, "add_atr", atr_without_gap)
    df = ohlcv(400, seed)
    theirs = module.add_supertrend(df)
    line, direction = ind.supertrend_bands(df["High"], df["Low"], df["Close"], theirs["ATR"])
    pd.testing.assert_series_equal(line, theirs["Supertrend"], check_names=False)
    pd.testing.assert_series_equal(direction, theirs["Supertrend_Direction"], check_names=False)
    assert theirs["Supertrend_Bullish_Flip"].sum() > 0


@pytest.mark.parametrize("seed", SEEDS)
def test_supertrend_starts_with_the_first_atr_and_stays_on_the_right_side_of_the_close(seed):
    out = ind.add_supertrend(ohlcv(400, seed))
    first_atr = out["ATR"].first_valid_index()
    assert out.loc[:first_atr, "Supertrend"].isna().all()
    assert (out.loc[:first_atr, "Supertrend_Direction"] == 0).all()
    after = out.loc[first_atr:].iloc[1:]
    assert after["Supertrend"].notna().all()
    bullish, bearish = (
        after[after["Supertrend_Direction"] == 1],
        after[after["Supertrend_Direction"] == -1],
    )
    assert len(bullish) > 0 and len(bearish) > 0
    assert (bullish["Supertrend"] <= bullish["Close"]).all()
    assert (bearish["Supertrend"] >= bearish["Close"]).all()
    assert out["Supertrend_Bullish_Flip"].sum() > 0
