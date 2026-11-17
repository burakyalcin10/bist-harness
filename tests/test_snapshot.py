"""Versioned market-data snapshot: files, manifest, ACTIVE pointer and offline reads."""

import json

import pandas as pd
import pytest

from bist_harness.data import snapshot as snap
from bist_harness.errors import DataUnavailableError

from .synth import ohlcv


class Downloader:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = frames
        self.calls: list[str] = []

    def __call__(self, symbol, start, end):
        self.calls.append(symbol)
        return self.frames.get(symbol, pd.DataFrame()).copy()


def _frames():
    return {"ASELS.IS": ohlcv(50, 1), "XU100.IS": ohlcv(50, 2)}


def test_build_writes_one_parquet_per_symbol_a_manifest_and_the_active_pointer(tmp_path):
    dl = Downloader(_frames())
    manifest = snap.build_snapshot(
        ["asels", "XU100"], snapshot_id="s1", root=tmp_path, downloader=dl
    )
    assert dl.calls == ["ASELS.IS", "XU100.IS"]
    assert sorted(p.name for p in (tmp_path / "s1").iterdir()) == [
        "ASELS.parquet",
        "XU100.parquet",
        "manifest.json",
    ]
    assert (tmp_path / "ACTIVE").read_text(encoding="utf-8").strip() == "s1"
    assert snap.active_snapshot_id(tmp_path) == "s1"
    stored = json.loads((tmp_path / "s1" / "manifest.json").read_text(encoding="utf-8"))
    assert stored["snapshot_id"] == manifest.snapshot_id == "s1"
    assert [s["symbol"] for s in stored["series"]] == ["ASELS", "XU100"]
    first = manifest.series[0]
    assert (first.rows, first.first_date, first.last_date) == (50, "2020-01-02", "2020-03-11")
    assert len(first.sha256) == 64
    assert snap.load_manifest(root=tmp_path) == manifest


def test_load_history_reads_back_what_was_written(tmp_path):
    frames = _frames()
    snap.build_snapshot(["ASELS"], snapshot_id="s1", root=tmp_path, downloader=Downloader(frames))
    df = snap.load_history("asels.is", root=tmp_path)
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    pd.testing.assert_frame_equal(df, frames["ASELS.IS"], check_freq=False, check_names=False)


def test_symbol_without_data_is_listed_with_zero_rows_and_has_no_file(tmp_path):
    manifest = snap.build_snapshot(
        ["ASELS", "PGSUS"], snapshot_id="s1", root=tmp_path, downloader=Downloader(_frames())
    )
    empty = manifest.series[1]
    assert (empty.symbol, empty.rows, empty.sha256) == ("PGSUS", 0, "")
    assert not (tmp_path / "s1" / "PGSUS.parquet").exists()
    with pytest.raises(DataUnavailableError):
        snap.load_history("PGSUS", root=tmp_path)


def test_same_data_gives_the_same_hash_in_two_builds(tmp_path):
    a = snap.build_snapshot(
        ["ASELS"], snapshot_id="a", root=tmp_path, downloader=Downloader(_frames())
    )
    b = snap.build_snapshot(
        ["ASELS"], snapshot_id="b", root=tmp_path, downloader=Downloader(_frames())
    )
    assert a.series[0].sha256 == b.series[0].sha256
    changed = _frames()
    changed["ASELS.IS"].iloc[3, 3] += 0.01
    c = snap.build_snapshot(
        ["ASELS"], snapshot_id="c", root=tmp_path, downloader=Downloader(changed)
    )
    assert c.series[0].sha256 != a.series[0].sha256


def test_without_an_active_snapshot_the_error_names_the_build_command(tmp_path):
    with pytest.raises(DataUnavailableError, match="snapshot build"):
        snap.load_history("ASELS", root=tmp_path)
    with pytest.raises(DataUnavailableError, match="snapshot build"):
        snap.active_snapshot_id(tmp_path)


def test_an_older_snapshot_can_still_be_read_by_id(tmp_path):
    old, new = _frames(), _frames()
    new["ASELS.IS"] = ohlcv(60, 9)
    snap.build_snapshot(["ASELS"], snapshot_id="old", root=tmp_path, downloader=Downloader(old))
    snap.build_snapshot(["ASELS"], snapshot_id="new", root=tmp_path, downloader=Downloader(new))
    assert snap.active_snapshot_id(tmp_path) == "new"
    assert len(snap.load_history("ASELS", root=tmp_path)) == 60
    assert len(snap.load_history("ASELS", snapshot_id="old", root=tmp_path)) == 50


def test_a_failing_download_does_not_stop_the_build(tmp_path):
    def flaky(symbol, start, end):
        if symbol == "ASELS.IS":
            raise RuntimeError("network down")
        return ohlcv(50, 2)

    manifest = snap.build_snapshot(
        ["ASELS", "THYAO"], snapshot_id="s1", root=tmp_path, downloader=flaky
    )
    assert [s.rows for s in manifest.series] == [0, 50]


def test_default_snapshot_id_is_a_timestamp(tmp_path):
    manifest = snap.build_snapshot(["ASELS"], root=tmp_path, downloader=Downloader(_frames()))
    assert len(manifest.snapshot_id) == 13 and manifest.snapshot_id[8] == "-"
    assert manifest.source and manifest.start == "2020-01-01"


def _write_adjustments(tmp_path, rows: str):
    path = tmp_path / "adjustments.csv"
    path.write_text("ticker,effective_date,factor,reason\n" + rows, encoding="utf-8")
    return path


def test_documented_split_adjustment_is_applied_to_rows_before_its_date(tmp_path):
    frames = _frames()
    raw = frames["ASELS.IS"]
    cut = raw.index[20]
    path = _write_adjustments(tmp_path, f"ASELS,{cut.date()},11,test split\n")
    snap.build_snapshot(["ASELS"], snapshot_id="s1", root=tmp_path, downloader=Downloader(frames))

    adjusted = snap.load_history("ASELS", root=tmp_path, adjustments_path=path)
    before, after = adjusted.loc[: cut - pd.Timedelta(days=1)], adjusted.loc[cut:]
    assert len(before) == 20
    for column in ["Open", "High", "Low", "Close"]:
        assert before[column].to_numpy() == pytest.approx(raw[column].iloc[:20].to_numpy() / 11)
        assert after[column].to_numpy() == pytest.approx(raw[column].iloc[20:].to_numpy())
    assert before["Volume"].to_numpy() == pytest.approx(raw["Volume"].iloc[:20].to_numpy() * 11)

    untouched = snap.load_history("ASELS", root=tmp_path, adjustments_path=path, adjust=False)
    assert untouched["Close"].to_numpy() == pytest.approx(raw["Close"].to_numpy())


def test_adjustments_of_other_tickers_do_not_touch_a_series(tmp_path):
    frames = _frames()
    path = _write_adjustments(tmp_path, "THYAO,2020-02-03,2,other stock\n")
    snap.build_snapshot(["ASELS"], snapshot_id="s1", root=tmp_path, downloader=Downloader(frames))
    df = snap.load_history("ASELS", root=tmp_path, adjustments_path=path)
    assert df["Close"].to_numpy() == pytest.approx(frames["ASELS.IS"]["Close"].to_numpy())


def test_shipped_adjustments_remove_the_ccola_split_jump():
    table = snap.load_adjustments()
    row = table[table["ticker"] == "CCOLA"].iloc[0]
    assert (row["effective_date"], float(row["factor"])) == ("2024-08-01", 11.0)
