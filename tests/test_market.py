"""Market data loading: column flattening, empty results, and the on-disk snapshot cache."""

import numpy as np
import pandas as pd
import pytest

from bist_harness.data.market import load_stock_data
from bist_harness.errors import DataUnavailableError


def _frame(multi_index: bool = False) -> pd.DataFrame:
    index = pd.date_range("2024-01-02", periods=5, freq="B")
    data = {
        "Open": np.arange(5.0) + 10,
        "High": np.arange(5.0) + 11,
        "Low": np.arange(5.0) + 9,
        "Close": np.arange(5.0) + 10.5,
        "Volume": np.arange(5.0) * 1000 + 1,
    }
    df = pd.DataFrame(data, index=index)
    if multi_index:
        df.columns = pd.MultiIndex.from_product([df.columns, ["ASELS.IS"]])
    return df


class Downloader:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.calls = []

    def __call__(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        return self.frame.copy()


def test_yahoo_symbol_is_requested_and_columns_are_ohlcv(tmp_path):
    dl = Downloader(_frame())
    df = load_stock_data("asels", "2024-01-01", "2024-01-31", cache_dir=tmp_path, downloader=dl)
    assert dl.calls == [("ASELS.IS", "2024-01-01", "2024-01-31")]
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.is_monotonic_increasing
    assert len(df) == 5


def test_multi_index_columns_from_yfinance_are_flattened(tmp_path):
    df = load_stock_data(
        "ASELS", "2024-01-01", cache_dir=tmp_path, downloader=Downloader(_frame(multi_index=True))
    )
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_rows_with_missing_prices_are_dropped(tmp_path):
    frame = _frame()
    frame.iloc[2, frame.columns.get_loc("Close")] = np.nan
    df = load_stock_data("ASELS", "2024-01-01", cache_dir=tmp_path, downloader=Downloader(frame))
    assert len(df) == 4


def test_empty_download_raises_data_unavailable(tmp_path):
    with pytest.raises(DataUnavailableError, match="ASELS"):
        load_stock_data(
            "ASELS", "2024-01-01", cache_dir=tmp_path, downloader=Downloader(pd.DataFrame())
        )


def test_second_call_reads_the_snapshot_instead_of_the_network(tmp_path):
    dl = Downloader(_frame())
    first = load_stock_data("ASELS", "2024-01-01", "2024-01-31", cache_dir=tmp_path, downloader=dl)
    second = load_stock_data("ASELS", "2024-01-01", "2024-01-31", cache_dir=tmp_path, downloader=dl)
    assert len(dl.calls) == 1
    pd.testing.assert_frame_equal(first, second, check_freq=False)
    assert (tmp_path / "ASELS_2024-01-01_2024-01-31.parquet").is_file()


def test_refresh_forces_a_new_download(tmp_path):
    dl = Downloader(_frame())
    load_stock_data("ASELS", "2024-01-01", cache_dir=tmp_path, downloader=dl)
    load_stock_data("ASELS", "2024-01-01", cache_dir=tmp_path, downloader=dl, refresh=True)
    assert len(dl.calls) == 2
    assert (tmp_path / "ASELS_2024-01-01_latest.parquet").is_file()
