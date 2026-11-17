"""KAP financial-report pages: the listing and the resumable download (K-055)."""

import gzip

import pandas as pd
import pytest

from bist_harness.data import kap_reports as kr
from bist_harness.errors import DataUnavailableError


def _disclosure(published, year, period, index, subject="Finansal Rapor"):
    return {
        "publishDate": published,
        "subject": subject,
        "year": year,
        "period": period,
        "disclosureIndex": index,
        "disclosureCategory": "FR",
        "summary": None,
    }


def _members(url, params):
    ticker = url.rstrip("/").rsplit("/", 1)[-1]
    return [] if ticker == "NOPE" else [{"mkkMemberOid": f"oid-{ticker}"}]


def _reports(url, body):
    oid, year = body["mkkMemberOidList"][0], body["fromDate"][:4]
    if oid == "oid-TUPRS" and year == "2025":
        return [_disclosure("17.02.2025 18:26:35", 2024, 4, 1393446)]
    if oid == "oid-AKBNK" and year == "2025":
        return [
            _disclosure("30.01.2025 18:15:07", 2024, 4, 1386664),
            _disclosure("30.01.2025 18:15:20", 2024, 4, 1386666),
        ]
    return []


def test_the_report_list_has_one_row_per_disclosure_with_its_index(tmp_path):
    waits = []
    table = kr.list_reports(
        ["TUPRS", "AKBNK"],
        "2024-01-01",
        "2025-12-31",
        cache_file=tmp_path / "list.json",
        get_json=_members,
        post_json=_reports,
        sleep=waits.append,
        pause=15,
    )
    assert list(table.columns) == kr.LIST_COLUMNS
    assert table["disclosure_index"].tolist() == [1393446, 1386664, 1386666]
    assert table["ticker"].tolist() == ["TUPRS", "AKBNK", "AKBNK"]
    assert table["published_at"].iloc[0] == pd.Timestamp("2025-02-17 18:26:35")
    assert waits and set(waits) == {15}


def test_a_stock_without_a_kap_member_id_stops_the_listing(tmp_path):
    with pytest.raises(DataUnavailableError, match="NOPE"):
        kr.list_reports(
            ["TUPRS", "NOPE"],
            "2025-01-01",
            "2025-12-31",
            cache_file=tmp_path / "list.json",
            get_json=_members,
            post_json=_reports,
            sleep=lambda s: None,
        )


def test_an_interrupted_listing_resumes_from_its_cache(tmp_path):
    cache = tmp_path / "list.json"

    def broken_for_akbnk(url, body):
        if body["mkkMemberOidList"] == ["oid-AKBNK"]:
            raise ConnectionError("dropped")
        return _reports(url, body)

    with pytest.raises(ConnectionError):
        kr.list_reports(
            ["TUPRS", "AKBNK"],
            "2025-01-01",
            "2025-12-31",
            cache_file=cache,
            get_json=_members,
            post_json=broken_for_akbnk,
            sleep=lambda s: None,
        )
    asked = []

    def counting(url, body):
        asked.append(body["mkkMemberOidList"][0])
        return _reports(url, body)

    table = kr.list_reports(
        ["TUPRS", "AKBNK"],
        "2025-01-01",
        "2025-12-31",
        cache_file=cache,
        get_json=_members,
        post_json=counting,
        sleep=lambda s: None,
    )
    assert asked == ["oid-AKBNK"]
    assert table["disclosure_index"].tolist() == [1393446, 1386664, 1386666]


def test_pages_are_saved_compressed_and_read_back(tmp_path):
    waits = []
    html = '<td>Hasılat</td><div title="810385588">810.385.588</div>'
    failed = kr.download_pages(
        [11, 12],
        tmp_path,
        get_page=lambda index: html.encode("utf-8"),
        sleep=waits.append,
        pause=15,
    )
    assert failed == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["11.html.gz", "12.html.gz"]
    assert gzip.decompress((tmp_path / "11.html.gz").read_bytes()).decode("utf-8") == html
    assert kr.read_page(tmp_path, 12) == html
    assert waits == [15, 15]


def test_saved_pages_are_not_downloaded_again(tmp_path):
    kr.download_pages([11], tmp_path, get_page=lambda i: b"x", sleep=lambda s: None)
    asked = []
    kr.download_pages(
        [11, 12], tmp_path, get_page=lambda i: asked.append(i) or b"y", sleep=lambda s: None
    )
    assert asked == [12]


def test_a_failing_page_is_retried_with_growing_waits_then_reported(tmp_path):
    calls = {11: 0, 12: 0}

    def flaky(index):
        calls[index] += 1
        if index == 11 and calls[11] < 3:
            raise ConnectionError("dropped")
        if index == 12:
            raise ConnectionError("always")
        return b"ok"

    waits = []
    failed = kr.download_pages([11, 12], tmp_path, get_page=flaky, sleep=waits.append, pause=10)
    assert failed == [12]
    assert (tmp_path / "11.html.gz").is_file() and not (tmp_path / "12.html.gz").exists()
    assert calls == {11: 3, 12: 3}
    assert waits[:3] == [20, 30, 10]  # two growing waits, then the pause after success


def test_reading_a_page_that_was_not_downloaded_names_the_download_command(tmp_path):
    with pytest.raises(DataUnavailableError, match="kap_reports download"):
        kr.read_page(tmp_path, 99)
