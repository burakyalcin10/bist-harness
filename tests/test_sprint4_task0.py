"""Sprint 4, Task 0: corrections carried over from the Sprint 3 review."""

import pandas as pd
import pytest

from bist_harness.data import fundamentals as fd
from bist_harness.data import snapshot
from bist_harness.errors import DataUnavailableError
from bist_harness.features import table as ft

from .synth import ohlcv


def _snapshot_with_layers(tmp_path):
    snapshot.build_snapshot(
        ["XU100"], snapshot_id="s1", root=tmp_path, downloader=lambda s, a, b: ohlcv(30, 2)
    )
    folder = tmp_path / "s1"
    for layer, name in [
        ("macro", "cpi.parquet"),
        ("fundamentals", "statements.parquet"),
        ("kap", "disclosures.parquet"),
    ]:
        (folder / layer).mkdir()
        pd.DataFrame({"x": [1, 2]}).to_parquet(folder / layer / name)
    return folder


def test_layers_id_changes_when_a_layer_or_a_reference_table_changes(tmp_path):
    folder = _snapshot_with_layers(tmp_path)
    reference = tmp_path / "half_days.csv"
    reference.write_text("date,close,basis\n", encoding="utf-8")
    first = snapshot.layers_id("s1", tmp_path, references=(reference,))
    assert first == snapshot.layers_id("s1", tmp_path, references=(reference,))
    pd.DataFrame({"x": [1, 3]}).to_parquet(folder / "kap" / "disclosures.parquet")
    second = snapshot.layers_id("s1", tmp_path, references=(reference,))
    assert second != first
    reference.write_text("date,close,basis\n2025-10-28,12:30,eve\n", encoding="utf-8")
    assert snapshot.layers_id("s1", tmp_path, references=(reference,)) != second


def test_verify_checks_the_sealed_layer_files(tmp_path):
    folder = _snapshot_with_layers(tmp_path)
    snapshot.seal_layers("s1", tmp_path)
    assert snapshot.verify_snapshot("s1", tmp_path) == []
    pd.DataFrame({"x": [9]}).to_parquet(folder / "macro" / "cpi.parquet")
    (folder / "fundamentals" / "statements.parquet").unlink()
    pd.DataFrame({"x": [1]}).to_parquet(folder / "kap" / "extra.parquet")
    assert sorted(snapshot.verify_snapshot("s1", tmp_path)) == [
        "fundamentals/statements.parquet: file missing",
        "kap/extra.parquet: not sealed",
        "macro/cpi.parquet: content changed",
    ]


def test_every_tool_result_names_the_layers_it_was_computed_from(monkeypatch):
    from bist_harness.mcp_server import server

    monkeypatch.setattr(server, "current_layers_id", lambda: "abcd1234")
    assert server._versions()["layers_id"] == "abcd1234"


HALF_DAY_CALENDAR = pd.DatetimeIndex(["2025-10-27", "2025-10-28", "2025-10-30", "2025-10-31"])


@pytest.mark.parametrize(
    "published,expected",
    [
        ("2025-10-28 12:10:00", "2025-10-28"),  # before the 12:30 close of the half day
        ("2025-10-28 12:30:00", "2025-10-30"),  # at the close: the next session
        ("2025-10-28 14:00:00", "2025-10-30"),  # used to count on the 28th
        ("2025-10-27 17:59:00", "2025-10-27"),  # an ordinary day still closes at 18:00
    ],
)
def test_a_half_day_session_closes_at_half_past_twelve(published, expected):
    assert fd.known_from(pd.Timestamp(published), HALF_DAY_CALENDAR) == pd.Timestamp(expected)


def test_the_half_day_table_lists_the_legal_half_days():
    table = pd.read_csv(fd.HALF_DAYS_PATH, dtype=str)
    assert list(table.columns) == ["date", "close", "basis"]
    assert {"2023-06-27", "2024-10-28", "2026-03-19"} <= set(table["date"])
    assert set(table["close"]) == {"12:30"}


def test_every_half_day_is_a_trading_day_followed_by_a_closure():
    try:
        calendar = snapshot.load_history("XU100").index
    except DataUnavailableError:
        pytest.skip("no snapshot")
    table = pd.read_csv(fd.HALF_DAYS_PATH, dtype=str)
    for day in pd.to_datetime(table["date"]):
        if day > calendar[-1]:
            continue
        assert day in calendar, day
        holiday = day + pd.Timedelta(days=1)  # the holiday itself may fall on a weekend
        assert holiday.day_of_week >= 5 or holiday not in calendar, day


def test_exchange_rate_is_used_one_day_late():
    # Yahoo's daily FX close comes hours after the BIST close, so on day t only the
    # rate of day t-1 is known.
    days = pd.bdate_range("2024-01-01", periods=30)
    fx = pd.DataFrame({"USDTRY": [30.0] * 29 + [60.0]}, index=days)
    table = pd.DataFrame(index=days)
    ft._macro(table, {"fx": fx})
    assert table.loc[days[-1], "usdtry_change_20d_pct"] == 0.0
    assert pd.isna(table.loc[days[20], "usdtry_change_20d_pct"])  # 20 days of history end t-1
