"""Sprint 4, Task 0: corrections carried over from the Sprint 3 review."""

import pandas as pd

from bist_harness.features import table as ft


def test_exchange_rate_is_used_one_day_late():
    # Yahoo's daily FX close comes hours after the BIST close, so on day t only the
    # rate of day t-1 is known.
    days = pd.bdate_range("2024-01-01", periods=30)
    fx = pd.DataFrame({"USDTRY": [30.0] * 29 + [60.0]}, index=days)
    table = pd.DataFrame(index=days)
    ft._macro(table, {"fx": fx})
    assert table.loc[days[-1], "usdtry_change_20d_pct"] == 0.0
    assert pd.isna(table.loc[days[20], "usdtry_change_20d_pct"])  # 20 days of history end t-1
