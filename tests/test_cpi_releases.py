"""CPI release days come from a recorded table, not from a weekday rule (Sprint 4, Task 0)."""

import pandas as pd
import pytest

from bist_harness.data import macro

# BIST was closed 2 to 4 May 2022 (Ramadan holiday) and on the weekend of 3 February 2024.
CALENDAR = pd.DatetimeIndex(
    ["2022-04-29", "2022-05-05", "2022-05-06", "2024-02-02", "2024-02-05", "2025-10-03"]
)


@pytest.mark.parametrize(
    "period,released",
    [
        ("2022-04", "2022-05-05"),  # the 3rd was a holiday; the weekday rule said 3 May
        ("2024-01", "2024-02-05"),  # the 3rd was a Saturday
        ("2025-09", "2025-10-03"),  # an ordinary month
    ],
)
def test_release_day_is_the_first_trading_day_on_or_after_the_third(period, released):
    table = macro.cpi_release_dates([pd.Period(period, "M")], CALENDAR)
    assert table.loc[0, "period"] == period
    assert table.loc[0, "released"] == released
    assert "trading day" in table.loc[0, "basis"]


def _snapshot_with_cpi(tmp_path):
    folder = tmp_path / "s1" / "macro"
    folder.mkdir(parents=True)
    cpi = pd.DataFrame(
        {
            "period": pd.to_datetime(["2022-04-30", "2022-05-31"]),
            "annual_pct": [69.97, 73.5],
            "monthly_pct": [7.25, 2.98],
            "published": pd.to_datetime(["2022-05-03", "2022-06-03"]),  # weekday rule
        }
    )
    cpi.to_parquet(folder / "cpi.parquet")
    (tmp_path / "ACTIVE").write_text("s1\n", encoding="utf-8")


def test_loading_cpi_takes_release_days_from_the_table(tmp_path):
    _snapshot_with_cpi(tmp_path)
    releases = tmp_path / "releases.csv"
    releases.write_text(
        "period,released,basis\n2022-04,2022-05-05,first BIST trading day on or after the 3rd\n",
        encoding="utf-8",
    )
    cpi = macro.load_macro("cpi", root=tmp_path, cpi_releases=releases)
    assert cpi["published"].tolist() == [pd.Timestamp("2022-05-05"), pd.Timestamp("2022-06-03")]


def test_the_recorded_table_covers_the_study_months_and_knows_the_may_2022_holiday():
    table = pd.read_csv(macro.CPI_RELEASES_PATH, dtype=str)
    assert list(table.columns) == ["period", "released", "basis"]
    months = set(table["period"])
    assert {"2019-12", "2022-04", "2025-01", "2026-10"} <= months
    assert table.set_index("period").loc["2022-04", "released"] == "2022-05-05"
    for period, released in zip(table["period"], table["released"], strict=True):
        third = (pd.Period(period, "M") + 1).to_timestamp() + pd.Timedelta(days=2)
        assert pd.Timestamp(released) >= third
