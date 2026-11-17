import json
from types import SimpleNamespace

import pytest

from bist_harness.harness.intent import (
    INTENT_SCHEMA,
    SCENARIOS,
    Intent,
    check_intent,
    keyword_guard,
    parse_intent,
)

TODAY = "2026-11-17"
ADV = "ADVICE_REQUEST"
PRED = "PREDICTION_REQUEST"

# (question, expected guard result): 40 questions, Turkish and English, both outcomes.
GUARD_TABLE = [
    # advice, Turkish (with and without Turkish letters)
    ("THYAO'yu alayım mı?", ADV),
    ("THYAO'yu alayim mi?", ADV),
    ("AKBNK hissesini satmalı mıyım?", ADV),
    ("akbnk satmali miyim", ADV),
    ("Bu hisseyi elimde tutmalı mıyım?", ADV),
    ("Bana yatırım tavsiyesi verir misin?", ADV),
    ("EREGL şu fiyattan alınır mı?", ADV),
    ("BIMAS al mı sat mı?", ADV),
    # advice, English
    ("Should I buy THYAO now?", ADV),
    ("should i sell my AKBNK shares", ADV),
    ("Is TUPRS a good investment?", ADV),
    ("Give me investment advice on ASELS.", ADV),
    ("Buy or sell KCHOL?", ADV),
    # prediction, Turkish
    ("THYAO yükselir mi?", PRED),
    ("thyao yukselir mi", PRED),
    ("ASELS için hedef fiyat nedir?", PRED),
    ("TUPRS yarın düşecek mi?", PRED),
    ("SASA ne kadar olur?", PRED),
    # prediction, English
    ("Will it rise tomorrow? THYAO", PRED),
    ("What is the price target for AKBNK?", PRED),
    # not guarded, Turkish (near misses included)
    ("TUPRS'un satışları arttı mı?", None),
    ("THYAO son 3 ayda sektörüne göre geride mi kaldı?", None),
    ("ASELS'te pazartesi etkisi var mı?", None),
    ("AKBNK'nin bilançosundan sonra fiyat nasıl tepki verdi?", None),
    ("Enflasyon verisi açıklandığında BIST 100 nasıl hareket etti?", None),
    ("EREGL için aşırı satım sonrası toparlanma olaylarını göster.", None),
    ("KCHOL hisse alım satım hacmi son ayda nasıl değişti?", None),
    ("Dün TUPRS'a dair hangi haberler çıktı?", None),
    ("MGROS yükselişe geçtiğinde hacim arttı mı?", None),
    ("Bu stratejinin geçmiş performansını test et.", None),
    # not guarded, English
    ("How did THYAO perform over the last 90 days?", None),
    ("Is there a weekday effect in ASELS returns?", None),
    ("Did AKBNK lag its banking peers this quarter?", None),
    ("Show the macro context for the last year.", None),
    ("Backtest the oversold reversal rule on EREGL.", None),
    ("What news was published about TUPRS last week?", None),
    ("Which stocks sold off after the last CPI release?", None),
    ("Summarize the price history of BIMAS.", None),
    ("Did the stock buy back shares in 2026?", None),
    ("What is the weather like in Istanbul?", None),
]


def test_guard_table_has_forty_questions_in_both_languages():
    assert len(GUARD_TABLE) == 40
    guarded = [q for q, expected in GUARD_TABLE if expected]
    assert 15 <= len(guarded) <= 25


@pytest.mark.parametrize(("question", "expected"), GUARD_TABLE)
def test_keyword_guard(question, expected):
    assert keyword_guard(question) == expected


def test_guard_is_accent_insensitive():
    assert keyword_guard("ALAYIM MI") == keyword_guard("alayim mi") == ADV


class FakeClient:
    """Scripted stand-in for OllamaClient: returns the queued contents in order."""

    def __init__(self, *contents):
        self.contents = list(contents)
        self.calls = []

    def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools, **kwargs})
        return SimpleNamespace(content=self.contents.pop(0))


def payload(**over):
    base = {
        "scenario": "PRICE_SUMMARY",
        "ticker": "THYAO",
        "sector": None,
        "start": None,
        "end": None,
        "as_of": None,
        "language": "tr",
    }
    base.update(over)
    return json.dumps(base)


def test_schema_covers_every_scenario():
    assert INTENT_SCHEMA["properties"]["scenario"]["enum"] == list(SCENARIOS)


def test_parse_intent_uses_schema_and_normalizes_ticker():
    client = FakeClient(payload(ticker="thyao.is", start="2026-01-01", end="2026-03-31"))
    intent = parse_intent("THYAO nasıl gitti?", client, today=TODAY)
    assert intent == Intent("PRICE_SUMMARY", "THYAO", None, "2026-01-01", "2026-03-31", None, "tr")
    assert client.calls[0]["response_format"] == INTENT_SCHEMA
    assert not intent.defaulted_period


def test_missing_dates_get_a_default_period_and_are_marked():
    client = FakeClient(payload(scenario="PRICE_SUMMARY"))
    intent = parse_intent("THYAO nasıl gitti?", client, today=TODAY)
    assert (intent.start, intent.end) == ("2026-08-19", TODAY)
    assert intent.defaulted_period


def test_malformed_json_is_requested_once_more():
    client = FakeClient("not json {", payload())
    intent = parse_intent("THYAO nasıl gitti?", client, today=TODAY)
    assert intent.scenario == "PRICE_SUMMARY"
    assert len(client.calls) == 2


def test_two_malformed_answers_give_out_of_scope():
    client = FakeClient("nope", '{"scenario": "MADE_UP"}')
    intent = parse_intent("hava nasıl?", client, today=TODAY)
    assert intent.scenario == "OUT_OF_SCOPE"
    assert len(client.calls) == 2
    assert check_intent(intent, today=TODAY) is None


def test_keyword_guard_overrides_a_model_that_says_analyze():
    client = FakeClient(payload(scenario="TECHNICAL_REVERSAL"))
    intent = parse_intent("THYAO'yu alayım mı?", client, today=TODAY)
    assert intent.scenario == ADV
    assert intent.start is None and not intent.defaulted_period


def test_model_advice_label_stands_without_keywords():
    client = FakeClient(payload(scenario=ADV))
    assert parse_intent("Bu hisse bana uyar mı?", client, today=TODAY).scenario == ADV


def test_guard_still_fires_when_the_model_output_is_unusable():
    client = FakeClient("x", "y")
    assert parse_intent("Should I buy THYAO?", client, today=TODAY).scenario == ADV


def make(**over):
    base = dict(
        scenario="PRICE_SUMMARY",
        ticker="THYAO",
        sector=None,
        start="2026-01-01",
        end="2026-03-31",
        as_of=None,
        language="en",
    )
    base.update(over)
    return Intent(**base)


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({}, None),
        ({"ticker": "ZZZZZ"}, "UNKNOWN_TICKER"),
        ({"ticker": None}, "MISSING_TICKER"),
        ({"scenario": "SECTOR_LAGGARD", "ticker": None, "sector": "Banking"}, None),
        ({"sector": "Astrology"}, "UNKNOWN_SECTOR"),
        ({"end": "2026-12-01"}, "FUTURE_DATE"),
        ({"as_of": "2027-01-01"}, "FUTURE_DATE"),
        ({"start": "2026-05-01", "end": "2026-01-01"}, "INVALID_DATE_RANGE"),
        ({"start": "2026-02-30"}, "INVALID_DATE"),
        ({"scenario": ADV, "ticker": "ZZZZZ"}, None),
    ],
)
def test_check_intent(over, expected):
    assert check_intent(make(**over), today=TODAY) == expected
