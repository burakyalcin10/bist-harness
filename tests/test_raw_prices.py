"""Unadjusted closes for market values (Sprint 4, Task 0)."""

import pandas as pd

from bist_harness.data import raw_prices as rp
from bist_harness.data import snapshot

DAYS = pd.bdate_range("2025-01-06", periods=4)


def _yahoo():
    # traded at 20, 20, then a 2-for-1 bonus issue, 10, 10; Yahoo divides the earlier
    # closes by 2 even with auto_adjust=False and records the split on its day
    return pd.DataFrame(
        {"Close": [10.0, 10.0, 10.0, 10.0], "Stock Splits": [0, 0, 2.0, 0]}, index=DAYS
    )


def test_raw_close_undoes_the_split_adjustment():
    raw = rp.raw_close(_yahoo())
    assert raw.tolist() == [20.0, 20.0, 10.0, 10.0]


def test_build_writes_a_layer_that_loads_back_and_is_hashed(tmp_path):
    (tmp_path / "ACTIVE").write_text("s1\n", encoding="utf-8")
    (tmp_path / "s1").mkdir()
    counts = rp.build_raw_prices(
        tmp_path / "s1", ["TUPRS"], downloader=lambda symbol, start, end: _yahoo()
    )
    assert counts == {"TUPRS": 4}
    loaded = rp.load_raw("TUPRS", root=tmp_path)
    assert list(loaded.columns) == ["close", "splits", "raw_close"]
    assert loaded["raw_close"].iloc[0] == 20.0
    assert "prices_raw/TUPRS.parquet" in snapshot.layer_hashes("s1", tmp_path)


def test_a_stock_without_the_layer_has_no_raw_prices(tmp_path):
    (tmp_path / "ACTIVE").write_text("s1\n", encoding="utf-8")
    (tmp_path / "s1").mkdir()
    assert rp.load_raw("TUPRS", root=tmp_path) is None
