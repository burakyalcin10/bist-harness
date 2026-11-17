"""KAP disclosure metadata as timestamped context: tagging, storage, the news tool."""

import pandas as pd
import pytest

from bist_harness.data import kap
from bist_harness.errors import DataUnavailableError
from bist_harness.tools.news import TOPICS, news_events


@pytest.mark.parametrize(
    "subject,summary,topic",
    [
        ("Finansal Rapor", "", "earnings"),
        ("Faaliyet Raporu (Konsolide)", "Ara Dönem Faaliyet Raporu", "earnings"),
        (
            "Özel Durum Açıklaması (Genel)",
            "2025 3.Çeyrek Finansal Tabloların Açıklanması",
            "earnings",
        ),
        ("Geleceğe Dönük Değerlendirmeler", "", "earnings"),
        ("Kar Payı Dağıtım İşlemlerine İlişkin Bildirim", "", "dividend"),
        ("Kar Dağıtım Politikası", "", "dividend"),
        (
            "Sermaye Artırımı - Azaltımı İşlemlerine İlişkin Bildirim",
            "Bedelsiz",
            "capital_increase",
        ),
        ("Kayıtlı Sermaye Tavanı İşlemlerine İlişkin Bildirim", "", "capital_increase"),
        ("Payların Geri Alınmasına İlişkin Bildirim", "", "buyback"),
        ("Özel Durum Açıklaması (Genel)", "Yeni İş İlişkisi - Sözleşme İmzalanması", "contract"),
        ("Özel Durum Açıklaması (Genel)", "İhale sonucu hakkında", "contract"),
        ("Özel Durum Açıklaması (Genel)", "Yeni yatırım kararı ve kapasite artışı", "investment"),
        (
            "Pay Dışında Sermaye Piyasası Aracı İşlemlerine İlişkin Bildirim (Faiz İçeren)",
            "",
            "financing",
        ),
        ("İhraç Tavanına İlişkin Bildirim", "", "financing"),
        ("Özel Durum Açıklaması (Genel)", "Kredi sözleşmesi imzalanması", "financing"),
        ("Birleşme İşlemlerine İlişkin Bildirim", "", "merger_acquisition"),
        ("Finansal Duran Varlık Edinimi", "", "merger_acquisition"),
        (
            "Özel Durum Açıklaması (Genel)",
            "Rekabet Kurulu soruşturması hakkında",
            "regulation_legal",
        ),
        ("Özel Durum Açıklaması (Genel)", "Dava süreci ve idari para cezası", "regulation_legal"),
        ("Kredi Derecelendirmesi", "JCR-ER Kredi Derecelendirme Notu", "credit_rating"),
        ("Genel Kurul İşlemlerine İlişkin Bildirim", "", "management"),
        ("Yönetim Kurulu Komiteleri", "", "management"),
        ("Bağımsız Denetim Kuruluşunun Belirlenmesi", "", "management"),
        ("Özel Durum Açıklaması (Genel)", "Basında çıkan haberler hakkında", "other"),
        (None, None, "other"),
    ],
)
def test_topic_rules(subject, summary, topic):
    assert kap.tag_topic(subject, summary) == topic
    assert topic in TOPICS


def _item(published, subject, summary="", index=1, category="ODA"):
    return {
        "publishDate": published,
        "subject": subject,
        "summary": summary,
        "disclosureIndex": index,
        "disclosureCategory": category,
        "disclosureClass": "ODA",
    }


def test_disclosures_are_fetched_one_year_at_a_time_and_tagged():
    bodies = []

    def post_json(url, body):
        bodies.append(body)
        if body["fromDate"].startswith("2025"):
            return [
                _item("26.12.2025 18:18:20", "Kredi Derecelendirmesi", "Not", 7),
                _item("13.01.2025 09:17:01", "Kar Dağıtım Politikası", "", 3),
            ]
        return [_item("05.02.2026 20:00:00", "Özel Durum Açıklaması (Genel)", "Sözleşme", 9)]

    table = kap.fetch_disclosures("TUPRS", "oid-1", "2025-01-01", "2026-11-13", post_json=post_json)
    assert [(b["fromDate"], b["toDate"]) for b in bodies] == [
        ("2025-01-01", "2025-12-31"),
        ("2026-01-01", "2026-11-13"),
    ]
    assert bodies[0]["disclosureClass"] == "ODA" and bodies[0]["mkkMemberOidList"] == ["oid-1"]
    assert list(table.columns) == kap.COLUMNS
    assert table["published_at"].is_monotonic_increasing
    assert table["topic"].tolist() == ["dividend", "credit_rating", "contract"]
    assert table.iloc[0]["url"] == "https://www.kap.org.tr/tr/Bildirim/3"
    assert set(table["ticker"]) == {"TUPRS"}


def _get_json(url, params):
    return [{"mkkMemberOid": "oid-" + url.rsplit("/", 1)[-1]}]


def test_build_saves_after_every_stock_and_a_second_run_skips_finished_stocks(tmp_path):
    calls = []

    def post_json(url, body):
        oid = body["mkkMemberOidList"][0]
        calls.append(oid)
        if oid == "oid-THYAO" and calls.count(oid) <= 2:
            raise ConnectionError("server disconnected")
        return [_item("13.01.2025 09:17:01", "Kar Dağıtım Politikası", "", len(calls))]

    folder = tmp_path / "s1"
    common = {"start": "2025-01-01", "end": "2025-12-31", "get_json": _get_json, "pause": 0}
    left = kap.build_kap(
        folder, ["TUPRS", "THYAO"], post_json=post_json, sleep=lambda s: None, **common
    )
    assert left == []
    (tmp_path / "ACTIVE").write_text("s1\n", encoding="utf-8")
    table = kap.load_disclosures(root=tmp_path)
    assert sorted(table["ticker"]) == ["THYAO", "TUPRS"]
    done = len(calls)
    assert (
        kap.build_kap(
            folder, ["TUPRS", "THYAO"], post_json=post_json, sleep=lambda s: None, **common
        )
        == []
    )
    assert len(calls) == done  # nothing was requested again


def test_a_stock_that_keeps_failing_is_reported_and_can_be_retried_later(tmp_path):
    def refuse(url, body):
        raise ConnectionError("server disconnected")

    left = kap.build_kap(
        tmp_path / "s1",
        ["TUPRS"],
        start="2025-01-01",
        end="2025-12-31",
        get_json=_get_json,
        post_json=refuse,
        pause=0,
        sleep=lambda s: None,
    )
    assert left == ["TUPRS"]
    (tmp_path / "ACTIVE").write_text("s1\n", encoding="utf-8")
    assert kap.load_disclosures(root=tmp_path).empty


def test_a_stock_without_any_disclosure_counts_as_done(tmp_path):
    left = kap.build_kap(
        tmp_path / "s1",
        ["TUPRS"],
        start="2025-01-01",
        end="2025-12-31",
        get_json=_get_json,
        post_json=lambda url, body: [],
        pause=0,
        sleep=lambda s: None,
    )
    assert left == []


def test_loading_before_a_build_names_the_build_command(tmp_path):
    (tmp_path / "ACTIVE").write_text("s1\n", encoding="utf-8")
    with pytest.raises(DataUnavailableError, match="kap build"):
        kap.load_disclosures(root=tmp_path)


def _table() -> pd.DataFrame:
    rows = [
        ("TUPRS", "2025-03-01 10:00:00", "dividend", "Kar Payı", 1),
        ("TUPRS", "2025-03-10 19:30:00", "contract", "Sözleşme", 2),
        ("THYAO", "2025-03-10 09:00:00", "contract", "Sözleşme", 3),
        ("THYAO", "2025-04-02 12:00:00", "regulation_legal", "Dava", 4),
    ]
    return pd.DataFrame(
        [
            {
                "ticker": t,
                "published_at": pd.Timestamp(p),
                "category": "ODA",
                "subject": s,
                "summary": "",
                "disclosure_index": i,
                "url": f"https://www.kap.org.tr/tr/Bildirim/{i}",
                "topic": topic,
            }
            for t, p, topic, s, i in rows
        ],
        columns=kap.COLUMNS,
    )


def test_news_events_lists_the_period_newest_first_with_topic_counts():
    out = news_events(_table(), start="2025-03-01", end="2025-03-31")
    assert out["total"] == 3
    assert out["by_topic"] == {"contract": 2, "dividend": 1}
    assert [e["published_at"] for e in out["events"]] == [
        "2025-03-10T19:30:00",
        "2025-03-10T09:00:00",
        "2025-03-01T10:00:00",
    ]
    assert set(out["events"][0]) == {"published_at", "ticker", "topic", "subject", "url"}
    assert out["context_only"] is True and out["warnings"] == []


def test_news_events_includes_the_whole_end_day_and_nothing_after_it():
    assert news_events(_table(), start="2025-03-01", end="2025-03-10")["total"] == 3
    assert news_events(_table(), start="2025-03-01", end="2025-03-09")["total"] == 1
    assert news_events(_table(), start="2025-03-02", end="2025-04-01")["total"] == 2


def test_news_events_filters_by_stock_and_topic_and_caps_the_list():
    assert news_events(_table(), start="2025-01-01", end="2025-12-31", ticker="thyao")["total"] == 2
    out = news_events(_table(), start="2025-01-01", end="2025-12-31", topic="contract")
    assert out["total"] == 2 and {e["topic"] for e in out["events"]} == {"contract"}
    capped = news_events(_table(), start="2025-01-01", end="2025-12-31", limit=2)
    assert capped["total"] == 4 and len(capped["events"]) == 2
    assert capped["events"][0]["published_at"].startswith("2025-04-02")


def test_news_events_with_nothing_in_the_period_is_empty_and_an_unknown_topic_is_refused():
    out = news_events(_table(), start="2024-01-01", end="2024-12-31")
    assert out["total"] == 0 and out["events"] == [] and out["by_topic"] == {}
    with pytest.raises(ValueError):
        news_events(_table(), start="2025-01-01", end="2025-12-31", topic="gossip")


@pytest.fixture
def stored(monkeypatch):
    from bist_harness.mcp_server import server as srv

    monkeypatch.setattr(srv, "load_disclosures", lambda: _table())
    return srv


def test_news_tool_returns_events_with_versions(stored):
    out = stored.get_news_events("2025-03-01", "2025-03-31")
    expected = news_events(_table(), start="2025-03-01", end="2025-03-31")
    for key, value in expected.items():
        assert out[key] == value
    assert out["context_only"] is True and "KAP" in out["data_source"]
    assert out["snapshot_id"] and len(out["result_id"]) == 12


def test_news_tool_filters_by_stock_and_topic(stored):
    out = stored.get_news_events("2025-01-01", "2025-12-31", "thyao.is", "contract")
    assert (out["ticker"], out["topic"], out["total"]) == ("THYAO", "contract", 1)


@pytest.mark.parametrize(
    "args,code",
    [
        (("2025-03-31", "2025-03-01"), "INVALID_DATE_RANGE"),
        (("2025-03-01", "2999-01-01"), "FUTURE_DATE"),
        (("01.03.2025", "2025-03-31"), "INVALID_DATE"),
        (("2025-03-01", "2025-03-31", "GARAN"), "UNKNOWN_TICKER"),
        (("2025-03-01", "2025-03-31", None, "gossip"), "INVALID_ARGUMENT"),
    ],
)
def test_news_tool_bad_input(args, code, stored):
    out = stored.get_news_events(*args)
    assert set(out) == {"error"} and out["error"]["code"] == code


def test_news_tool_without_stored_disclosures_names_the_build_command(monkeypatch):
    from bist_harness.mcp_server import server as srv

    def missing():
        raise DataUnavailableError("no KAP disclosures. Run `... kap build` first.")

    monkeypatch.setattr(srv, "load_disclosures", missing)
    out = srv.get_news_events("2025-03-01", "2025-03-31")
    assert out["error"]["code"] == "DATA_UNAVAILABLE" and "kap build" in out["error"]["message"]
