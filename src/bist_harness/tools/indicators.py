"""Technical indicators (project brief, section 13).

Column names and formulas follow the instructor's Scenario 3 script, so results can be
compared with the course material; tests check equality on synthetic data. One
deliberate difference: the script's Supertrend never produces a value (the missing ATR
of the first days is carried through the band recursion forever), so here the recursion
starts on the first day that has an ATR. The recursion itself is the script's.

Every value on day t uses data up to day t only. The Ichimoku spans are the script's:
shifted 26 days forward, so the cloud on day t was computed from data up to t-26.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

INDICATOR_GROUPS = (
    "SMA",
    "EMA",
    "KAMA",
    "RSI",
    "MACD",
    "BOLLINGER",
    "ATR",
    "SUPERTREND",
    "ICHIMOKU",
    "VOLUME",
)
KAMA_FLAT_SHARE = 0.0005  # |slope| below 0.05% of the close counts as flat
HIGH_VOLUME_RATIO = 1.5
LOW_VOLUME_RATIO = 0.5
RSI_TROUGH_LEVEL = 40
RSI_PEAK_LEVEL = 60


def add_sma(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    df = df.copy()
    df[f"SMA_{window}"] = df["Close"].rolling(window).mean()
    return df


def add_ema(df: pd.DataFrame, span: int = 20) -> pd.DataFrame:
    df = df.copy()
    df[f"EMA_{span}"] = df["Close"].ewm(span=span, adjust=False).mean()
    return df


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    df = df.copy()
    close = df["Close"]
    df["MACD"] = (
        close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    )
    df["MACD_Signal"] = df["MACD"].ewm(span=signal, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]
    return df


def add_bollinger_bands(df: pd.DataFrame, window: int = 20, num_std: float = 2) -> pd.DataFrame:
    df = df.copy()
    df["BB_Middle"] = df["Close"].rolling(window).mean()
    std = df["Close"].rolling(window).std()
    df["BB_Upper"] = df["BB_Middle"] + num_std * std
    df["BB_Lower"] = df["BB_Middle"] - num_std * std
    return df


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Wilder's RSI (exponential smoothing with alpha = 1/period)."""
    df = df.copy()
    delta = df["Close"].diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


def add_kama(df: pd.DataFrame, er_period: int = 10, fast: int = 2, slow: int = 30) -> pd.DataFrame:
    """Kaufman's adaptive moving average and its one-day slope."""
    df = df.copy()
    close = df["Close"]
    change = (close - close.shift(er_period)).abs()
    volatility = close.diff().abs().rolling(er_period).sum()
    er = change / volatility.replace(0, np.nan)
    fast_sc, slow_sc = 2 / (fast + 1), 2 / (slow + 1)
    sc = ((er * (fast_sc - slow_sc) + slow_sc) ** 2).to_numpy(dtype=float)

    prices = close.to_numpy(dtype=float)
    kama = np.full(len(df), np.nan)
    if len(df) > er_period:
        kama[er_period] = prices[er_period]
        for i in range(er_period + 1, len(df)):
            previous = kama[i - 1]
            kama[i] = previous if np.isnan(sc[i]) else previous + sc[i] * (prices[i] - previous)
    df["KAMA"] = kama
    df["KAMA_Slope"] = df["KAMA"].diff()
    return df


def add_atr(df: pd.DataFrame, period: int = 10) -> pd.DataFrame:
    """Average true range as a simple moving average of the true range (the script's choice)."""
    df = df.copy()
    previous_close = df["Close"].shift(1)
    true_range = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - previous_close).abs(),
            (df["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["ATR"] = true_range.rolling(period).mean()
    return df


def supertrend_bands(
    high: pd.Series, low: pd.Series, close: pd.Series, atr: pd.Series, multiplier: float = 3.0
) -> tuple[pd.Series, pd.Series]:
    """Supertrend line and direction (1 bullish, -1 bearish, 0 undefined).

    The recursion is the instructor's; it starts on the first day with an ATR. On that
    day the bands are set and the direction is 0; from the next day on the line follows
    the lower band while the close holds above it and the upper band otherwise.
    """
    n = len(close)
    hl2 = ((high + low) / 2).to_numpy(dtype=float)
    atr_values = atr.to_numpy(dtype=float)
    prices = close.to_numpy(dtype=float)
    basic_upper = hl2 + multiplier * atr_values
    basic_lower = hl2 - multiplier * atr_values
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    line = np.full(n, np.nan)
    direction = np.zeros(n)

    valid = np.flatnonzero(~np.isnan(atr_values))
    if len(valid):
        first = int(valid[0])
        final_upper[first], final_lower[first] = basic_upper[first], basic_lower[first]
        for i in range(first + 1, n):
            if basic_upper[i] < final_upper[i - 1] or prices[i - 1] > final_upper[i - 1]:
                final_upper[i] = basic_upper[i]
            else:
                final_upper[i] = final_upper[i - 1]
            if basic_lower[i] > final_lower[i - 1] or prices[i - 1] < final_lower[i - 1]:
                final_lower[i] = basic_lower[i]
            else:
                final_lower[i] = final_lower[i - 1]

            previous = line[i - 1]
            if np.isnan(previous):
                line[i], direction[i] = final_lower[i], 1
            elif previous == final_upper[i - 1]:
                if prices[i] <= final_upper[i]:
                    line[i], direction[i] = final_upper[i], -1
                else:
                    line[i], direction[i] = final_lower[i], 1
            elif prices[i] >= final_lower[i]:
                line[i], direction[i] = final_lower[i], 1
            else:
                line[i], direction[i] = final_upper[i], -1
    return pd.Series(line, index=close.index), pd.Series(direction, index=close.index)


def add_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    df = add_atr(df, period=period)
    line, direction = supertrend_bands(df["High"], df["Low"], df["Close"], df["ATR"], multiplier)
    df["Supertrend"] = line
    df["Supertrend_Direction"] = direction
    df["Supertrend_Bullish_Flip"] = (direction.shift(1) == -1) & (direction == 1)
    return df


def add_ichimoku(df: pd.DataFrame) -> pd.DataFrame:
    """Ichimoku 9/26/52. The spans are shifted 26 days forward, as in the script."""
    df = df.copy()
    df["Tenkan"] = (df["High"].rolling(9).max() + df["Low"].rolling(9).min()) / 2
    df["Kijun"] = (df["High"].rolling(26).max() + df["Low"].rolling(26).min()) / 2
    df["Senkou_A"] = ((df["Tenkan"] + df["Kijun"]) / 2).shift(26)
    df["Senkou_B"] = ((df["High"].rolling(52).max() + df["Low"].rolling(52).min()) / 2).shift(26)
    df["Cloud_Top"] = df[["Senkou_A", "Senkou_B"]].max(axis=1)
    df["Cloud_Bottom"] = df[["Senkou_A", "Senkou_B"]].min(axis=1)
    df["Ichimoku_Bullish_Breakout"] = (df["Close"].shift(1) <= df["Cloud_Top"].shift(1)) & (
        df["Close"] > df["Cloud_Top"]
    )
    return df


def add_volume_features(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    df = df.copy()
    df["Volume_MA"] = df["Volume"].rolling(window).mean()
    df["Volume_Rise"] = df["Volume"] > df["Volume_MA"]
    return df


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Every indicator with its default parameters (SMA 20 and 50, EMA 20)."""
    df = add_sma(add_sma(df, 20), 50)
    df = add_macd(add_ema(df, 20))
    df = add_kama(add_rsi(add_bollinger_bands(df)))
    return add_volume_features(add_ichimoku(add_supertrend(df)))


def _value(row: pd.Series, column: str) -> float | None:
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    return round(float(value), 2)


def _raw(row: pd.Series, column: str) -> float:
    value = row.get(column)
    return float("nan") if value is None or pd.isna(value) else float(value)


def _rsi_state(rsi: pd.Series) -> str | None:
    """Local low: yesterday's RSI below both neighbours and below 40 (the script's trough)."""
    if rsi.empty or pd.isna(rsi.iloc[-1]):
        return None
    if len(rsi) < 3:
        return "Neutral"
    before, trough, today = (float(v) for v in rsi.iloc[-3:])
    if trough < before and trough < today and trough < RSI_TROUGH_LEVEL:
        return "Local Low"
    if trough > before and trough > today and trough > RSI_PEAK_LEVEL:
        return "Local High"
    return "Neutral"


def _state_sma(df: pd.DataFrame, row: pd.Series) -> dict:
    close, sma = _raw(row, "Close"), _raw(row, "SMA_20")
    position = None if np.isnan(sma) else ("Above" if close > sma else "Below")
    return {
        "sma_20": _value(row, "SMA_20"),
        "sma_50": _value(row, "SMA_50"),
        "close_vs_sma_20": position,
    }


def _state_ema(df: pd.DataFrame, row: pd.Series) -> dict:
    return {"ema_20": _value(row, "EMA_20")}


def _state_kama(df: pd.DataFrame, row: pd.Series) -> dict:
    slope, close = _raw(row, "KAMA_Slope"), _raw(row, "Close")
    if np.isnan(slope):
        state = None
    elif abs(slope) < KAMA_FLAT_SHARE * close:
        state = "Flattening"
    else:
        state = "Rising" if slope > 0 else "Falling"
    return {
        "kama": _value(row, "KAMA"),
        "kama_slope": _value(row, "KAMA_Slope"),
        "kama_slope_state": state,
    }


def _state_rsi(df: pd.DataFrame, row: pd.Series) -> dict:
    return {"rsi": _value(row, "RSI"), "rsi_state": _rsi_state(df["RSI"])}


def _state_macd(df: pd.DataFrame, row: pd.Series) -> dict:
    macd, signal = _raw(row, "MACD"), _raw(row, "MACD_Signal")
    state = (
        None if np.isnan(macd) or np.isnan(signal) else ("Bullish" if macd > signal else "Bearish")
    )
    return {
        "macd": _value(row, "MACD"),
        "macd_signal": _value(row, "MACD_Signal"),
        "macd_hist": _value(row, "MACD_Hist"),
        "macd_state": state,
    }


def _state_bollinger(df: pd.DataFrame, row: pd.Series) -> dict:
    close = _raw(row, "Close")
    upper, middle, lower = (_raw(row, c) for c in ("BB_Upper", "BB_Middle", "BB_Lower"))
    if np.isnan(upper):
        position = None
    elif close > upper:
        position = "Above Upper"
    elif close >= middle:
        position = "Upper Half"
    elif close >= lower:
        position = "Lower Half"
    else:
        position = "Below Lower"
    return {
        "bb_upper": _value(row, "BB_Upper"),
        "bb_middle": _value(row, "BB_Middle"),
        "bb_lower": _value(row, "BB_Lower"),
        "bollinger_position": position,
    }


def _state_atr(df: pd.DataFrame, row: pd.Series) -> dict:
    atr, close = _raw(row, "ATR"), _raw(row, "Close")
    return {
        "atr": _value(row, "ATR"),
        "atr_pct": None if np.isnan(atr) else round(atr / close * 100, 2),
    }


def _state_supertrend(df: pd.DataFrame, row: pd.Series) -> dict:
    direction = _raw(row, "Supertrend_Direction")
    state = {1.0: "Bullish", -1.0: "Bearish"}.get(direction)
    return {"supertrend": _value(row, "Supertrend"), "supertrend_state": state}


def _state_ichimoku(df: pd.DataFrame, row: pd.Series) -> dict:
    close, top, bottom = (_raw(row, c) for c in ("Close", "Cloud_Top", "Cloud_Bottom"))
    if np.isnan(top) or np.isnan(bottom):
        state = None
    elif close > top:
        state = "Above Cloud"
    elif close < bottom:
        state = "Below Cloud"
    else:
        state = "In Cloud"
    return {
        "tenkan": _value(row, "Tenkan"),
        "kijun": _value(row, "Kijun"),
        "cloud_top": _value(row, "Cloud_Top"),
        "cloud_bottom": _value(row, "Cloud_Bottom"),
        "ichimoku_state": state,
    }


def _state_volume(df: pd.DataFrame, row: pd.Series) -> dict:
    volume, average = _raw(row, "Volume"), _raw(row, "Volume_MA")
    if np.isnan(average) or average == 0:
        return {"volume_ratio": None, "volume_regime": None}
    ratio = volume / average
    if ratio > HIGH_VOLUME_RATIO:
        regime = "High"
    elif ratio < LOW_VOLUME_RATIO:
        regime = "Low"
    else:
        regime = "Normal"
    return {"volume_ratio": round(ratio, 2), "volume_regime": regime}


_STATE_BUILDERS = {
    "SMA": _state_sma,
    "EMA": _state_ema,
    "KAMA": _state_kama,
    "RSI": _state_rsi,
    "MACD": _state_macd,
    "BOLLINGER": _state_bollinger,
    "ATR": _state_atr,
    "SUPERTREND": _state_supertrend,
    "ICHIMOKU": _state_ichimoku,
    "VOLUME": _state_volume,
}


def indicator_state(df: pd.DataFrame, indicators: Sequence[str]) -> dict:
    """Values and state labels of the last day of ``df`` (which already has the columns).

    An empty ``indicators`` list means every group. Values are rounded to two decimals;
    a value that cannot be computed yet is ``None``.
    """
    groups = list(indicators) or list(INDICATOR_GROUPS)
    unknown = [g for g in groups if g not in _STATE_BUILDERS]
    if unknown:
        raise ValueError(f"unknown indicator(s): {', '.join(unknown)}")
    if df.empty:
        state: dict = {"as_of": None, "close": None}
        row = pd.Series(dtype=float)
    else:
        row = df.iloc[-1]
        state = {"as_of": str(pd.Timestamp(df.index[-1]).date()), "close": _value(row, "Close")}
    for group in groups:
        state.update(_STATE_BUILDERS[group](df, row))
    return state
