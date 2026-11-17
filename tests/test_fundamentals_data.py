"""Quarterly statements and their KAP publication times: parsing, timing rule, storage."""

import pandas as pd
import pytest

from bist_harness.data import fundamentals as fd
from bist_harness.errors import DataUnavailableError

P = fd.Period


def test_period_arithmetic_and_end_dates():
    q3 = P(2025, 3)
    assert q3.end_date == pd.Timestamp("2025-09-30") and P(2024, 4).end_date == pd.Timestamp(
        "2024-12-31"
    )
    assert q3.previous() == P(2025, 2) and P(2025, 1).previous() == P(2024, 4)
    assert q3.year_earlier() == P(2024, 3) and q3.month == 9
    assert fd.periods_between(P(2024, 3), P(2025, 2)) == [
        P(2024, 3),
        P(2024, 4),
        P(2025, 1),
        P(2025, 2),
    ]
    assert P(2024, 4) < P(2025, 1) and str(q3) == "2025Q3"
    with pytest.raises(ValueError):
        P(2025, 5)


def test_financial_group_follows_the_sector():
    assert fd.financial_group("AKBNK") == "bank"
    assert fd.financial_group("TURSG") == "insurance"
    assert fd.financial_group("tuprs.is") == "industrial"
    assert fd.financial_group("ISMEN") == "industrial"


def _statement_reply(v1, v2):
    return {
        "value": [
            {"itemCode": "3C", "itemDescTr": "Satış Gelirleri", "itemDescEng": "Net Sales", "value1": v1, "value2": v2, "value3": None, "value4": None},
            {"itemCode": "3L", "itemDescTr": "DÖNEM KARI", "itemDescEng": None, "value1": "50", "value2": "-20", "value3": None, "value4": None},
            {"itemCode": "9X", "itemDescTr": "Boş", "itemDescEng": "Empty", "value1": None, "value2": "", "value3": None, "value4": None},
        ]
    }  # fmt: skip


def test_statements_are_read_into_long_rows_four_periods_a_request():
    calls = []

    def get_json(url, params):
        calls.append(params)
        return _statement_reply("1000", "600")

    periods = fd.periods_between(P(2024, 1), P(2025, 2))  # six periods: two requests
    table = fd.fetch_statements("tuprs", periods, get_json=get_json)
    assert len(calls) == 2
    assert calls[0]["companyCode"] == "TUPRS" and calls[0]["financialGroup"] == "XI_29"
    assert (calls[0]["year1"], calls[0]["period1"], calls[0]["year4"], calls[0]["period4"]) == (
        2024,
        3,
        2024,
        12,
    )
    assert list(table.columns) == ["ticker", "year", "quarter", "item_code", "item_name", "value"]
    first = table[(table["year"] == 2024) & (table["quarter"] == 1)]
    assert first.set_index("item_code")["value"].to_dict() == {"3C": 1000.0, "3L": 50.0}
    second = table[(table["year"] == 2024) & (table["quarter"] == 2)]
    assert second.set_index("item_code")["value"].to_dict() == {"3C": 600.0, "3L": -20.0}
    assert set(table["item_name"]) == {"Net Sales", "DÖNEM KARI"}  # Turkish name as fallback
    assert "9X" not in set(table["item_code"])


def test_bank_statements_are_requested_from_the_bank_layout():
    seen = {}

    def get_json(url, params):
        seen.update(params)
        return {"value": []}

    table = fd.fetch_statements("AKBNK", [P(2025, 1)], get_json=get_json)
    assert seen["financialGroup"] == "UFRS_K" and table.empty


def _disclosure(published, subject, year, period, index, category="FR"):
    return {
        "publishDate": published,
        "subject": subject,
        "year": year,
        "period": period,
        "disclosureIndex": index,
        "disclosureCategory": category,
        "summary": None,
    }


def test_only_financial_reports_are_kept_with_parsed_timestamps():
    def post_json(url, body):
        assert body["mkkMemberOidList"] == ["oid-1"] and body["disclosureClass"] == "FR"
        if body["fromDate"].startswith("2025"):
            return [
                _disclosure(
                    "31.10.2025 18:19:54", "Faaliyet Raporu (Konsolide)", 2025, 3, 1, "ODA"
                ),
                _disclosure("31.10.2025 18:19:22", "Finansal Rapor", 2025, 3, 2),
                _disclosure("29.07.2025 09:33:39", "Finansal Rapor", 2025, 2, 3),
            ]
        return [_disclosure("17.02.2024 18:26:35", "Finansal Rapor", 2023, 4, 4)]

    table = fd.fetch_report_disclosures("oid-1", "2024-01-01", "2025-12-31", post_json=post_json)
    assert list(table.columns) == ["published_at", "year", "quarter", "subject", "disclosure_index"]
    assert table["published_at"].tolist() == [
        pd.Timestamp("2024-02-17 18:26:35"),
        pd.Timestamp("2025-07-29 09:33:39"),
        pd.Timestamp("2025-10-31 18:19:22"),
    ]
    assert table[["year", "quarter"]].to_numpy().tolist() == [[2023, 4], [2025, 2], [2025, 3]]


CALENDAR = pd.DatetimeIndex(
    ["2025-10-30", "2025-10-31", "2025-11-03", "2025-11-04", "2025-11-05"]
)  # the 1st and 2nd are a weekend


@pytest.mark.parametrize(
    "published,expected",
    [
        ("2025-10-31 17:59:59", "2025-10-31"),  # before the close: known at that day's close
        ("2025-10-31 18:00:00", "2025-11-03"),  # at or after the close: the next trading day
        ("2025-10-31 18:19:22", "2025-11-03"),
        ("2025-11-01 11:00:00", "2025-11-03"),  # a Saturday
        ("2025-11-03 02:55:12", "2025-11-03"),  # in the night before a trading day
        ("2025-10-29 10:00:00", "2025-10-30"),  # a day missing from the calendar (holiday)
    ],
)
def test_known_from_is_the_first_close_after_the_publication(published, expected):
    assert fd.known_from(pd.Timestamp(published), CALENDAR) == pd.Timestamp(expected)


def test_known_from_is_undefined_beyond_the_calendar():
    assert pd.isna(fd.known_from(pd.Timestamp("2025-11-05 19:00:00"), CALENDAR))
    assert pd.isna(fd.known_from(pd.NaT, CALENDAR))


def test_disclosure_calendar_keeps_the_first_publication_and_counts_corrections():
    reports = pd.DataFrame(
        {
            "published_at": pd.to_datetime(
                ["2025-10-31 18:19:22", "2025-11-04 10:00:00", "2025-07-29 09:33:39"]
            ),
            "year": [2025, 2025, 2025],
            "quarter": [3, 3, 2],
            "subject": ["Finansal Rapor"] * 3,
            "disclosure_index": [2, 9, 3],
        }
    )
    table = fd.disclosure_calendar(
        "TUPRS", reports, CALENDAR.union(pd.DatetimeIndex(["2025-07-29"]))
    )
    assert list(table.columns) == [
        "ticker",
        "year",
        "quarter",
        "published_at",
        "known_from",
        "revisions",
    ]
    q3 = table[table["quarter"] == 3].iloc[0]
    assert q3["published_at"] == pd.Timestamp("2025-10-31 18:19:22")
    assert q3["known_from"] == pd.Timestamp("2025-11-03") and q3["revisions"] == 1
    q2 = table[table["quarter"] == 2].iloc[0]
    assert q2["known_from"] == pd.Timestamp("2025-07-29") and q2["revisions"] == 0


def test_build_stores_statements_and_calendar_and_reports_coverage(tmp_path):
    def get_json(url, params):
        if "member/filter" in url:
            return [{"mkkMemberOid": "oid-" + url.rsplit("/", 1)[-1]}]
        if params["companyCode"] == "THYAO":
            return {"value": []}
        return _statement_reply("1000", "600")

    def post_json(url, body):
        if body["mkkMemberOidList"] == ["oid-TUPRS"] and body["fromDate"].startswith("2025"):
            return [_disclosure("31.10.2025 18:19:22", "Finansal Rapor", 2025, 1, 2)]
        return []

    coverage = fd.build_fundamentals(
        tmp_path / "s1",
        ["TUPRS", "THYAO"],
        first=P(2025, 1),
        last=P(2025, 2),
        calendar=CALENDAR,
        get_json=get_json,
        post_json=post_json,
        pause=0,
    )
    assert coverage.set_index("ticker").to_dict("index") == {
        "TUPRS": {"statements": 2, "published": 1},
        "THYAO": {"statements": 0, "published": 0},
    }
    (tmp_path / "ACTIVE").write_text("s1\n", encoding="utf-8")
    statements = fd.load_statements("tuprs", root=tmp_path)
    assert len(statements) == 4 and set(statements["quarter"]) == {1, 2}
    assert fd.load_statements("THYAO", root=tmp_path).empty
    calendar = fd.load_disclosure_calendar(root=tmp_path)
    assert calendar[["ticker", "year", "quarter"]].to_numpy().tolist() == [["TUPRS", 2025, 1]]
    assert calendar.iloc[0]["known_from"] == pd.Timestamp("2025-11-03")


def test_loading_before_a_build_names_the_build_command(tmp_path):
    (tmp_path / "ACTIVE").write_text("s1\n", encoding="utf-8")
    with pytest.raises(DataUnavailableError, match="fundamentals build"):
        fd.load_statements("TUPRS", root=tmp_path)
    with pytest.raises(DataUnavailableError, match="fundamentals build"):
        fd.load_disclosure_calendar(root=tmp_path)


def test_missing_publication_times_are_fetched_again_with_retries(tmp_path):
    def get_json(url, params):
        if "member/filter" in url:
            return [{"mkkMemberOid": "oid-" + url.rsplit("/", 1)[-1]}]
        return _statement_reply("1000", "600")

    attempts = {"oid-TUPRS": 0, "oid-THYAO": 0}

    def flaky(url, body):
        oid = body["mkkMemberOidList"][0]
        attempts[oid] += 1
        if oid == "oid-THYAO" and attempts[oid] <= 2:
            raise ConnectionError("server disconnected")
        if body["fromDate"].startswith("2025"):
            return [_disclosure("31.10.2025 18:19:22", "Finansal Rapor", 2025, 1, 2)]
        return []

    def refuse(url, body):
        raise ConnectionError("server disconnected")

    common = {"first": P(2025, 1), "last": P(2025, 2), "calendar": CALENDAR, "pause": 0}
    fd.build_fundamentals(
        tmp_path / "s1", ["TUPRS", "THYAO"], get_json=get_json, post_json=refuse, **common
    )
    (tmp_path / "ACTIVE").write_text("s1\n", encoding="utf-8")
    assert fd.load_disclosure_calendar(root=tmp_path).empty

    waits = []
    left = fd.update_publication_times(
        tmp_path / "s1", get_json=get_json, post_json=flaky, sleep=waits.append, **common
    )
    assert left == []
    calendar = fd.load_disclosure_calendar(root=tmp_path)
    assert sorted(calendar["ticker"]) == ["THYAO", "TUPRS"]
    assert attempts["oid-THYAO"] >= 3 and len(waits) >= 2

    # Stocks that already have their times are not requested again.
    before = dict(attempts)
    assert (
        fd.update_publication_times(
            tmp_path / "s1", get_json=get_json, post_json=flaky, sleep=waits.append, **common
        )
        == []
    )
    assert attempts == before


def test_a_stock_that_keeps_failing_is_returned_as_still_missing(tmp_path):
    def get_json(url, params):
        if "member/filter" in url:
            return [{"mkkMemberOid": "oid"}]
        return _statement_reply("1000", "600")

    def refuse(url, body):
        raise ConnectionError("server disconnected")

    common = {"first": P(2025, 1), "last": P(2025, 2), "calendar": CALENDAR, "pause": 0}
    fd.build_fundamentals(tmp_path / "s1", ["TUPRS"], get_json=get_json, post_json=refuse, **common)
    left = fd.update_publication_times(
        tmp_path / "s1", get_json=get_json, post_json=refuse, sleep=lambda s: None, **common
    )
    assert left == ["TUPRS"]
