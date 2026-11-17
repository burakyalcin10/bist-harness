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
    # round 2: recommendation, price-level and hyphen cases
    ("Which stock would you recommend?", ADV),
    ("Hangi hisseyi önerirsin?", ADV),
    ("Bana bir hisse önerir misin?", ADV),
    ("Which stock should I pick?", ADV),
    ("Can you recommend a stock to hold?", ADV),
    ("Hangi hisseyi almalıyım?", ADV),
    ("What will THYAO price be next month?", PRED),
    ("What will the price of AKBNK be in June?", PRED),
    ("THYAO fiyatı ne olur?", PRED),
    ("ASELS fiyatı kaç olur sence?", PRED),
    ("Is THYAO a buy-and-hold candidate in the backtest?", None),
    ("What will the backtest window be?", None),
    ("Which stock lagged its sector peers?", None),
    ("Hangi hisse sektörünün gerisinde kaldı?", None),
    ("Fiyat verisi ne zaman güncellendi?", None),
    ("Do you recommend a backtest window?", None),
    # gap rows (round 1): wordings that are NOT in the phrase list
    ("THYAO alsam mı?", ADV),
    ("AKBNK'yı satsam mı acaba?", ADV),
    ("Can I buy THYAO?", ADV),
    ("Can I sell my ASELS position?", ADV),
    ("Is THYAO a buy?", ADV),
    ("Would you buy TUPRS today?", ADV),
    ("Is it a good time to buy EREGL?", ADV),
    ("Is THYAO going to go up?", PRED),
    ("Will THYAO go up next week?", PRED),
    ("Will it reach 300 TL?", PRED),
    ("BIMAS'ı portföyüme eklesem mi?", ADV),
    # near misses sharing words with the guarded phrases
    ("Will the stock data include dividends?", None),
    ("Will the price series be adjusted?", None),
    ("Where will the report be saved?", None),
    ("Do you recommend a backtest window?", None),
    ("Can I see the price history of THYAO?", None),
    ("Can I run a backtest on AKBNK?", None),
    ("Is THYAO a bank or an airline?", None),
    ("Will the backtest go up to 2026?", None),
]


def test_guard_table_has_at_least_forty_questions_in_both_languages():
    assert len(GUARD_TABLE) >= 40
    guarded = [q for q, expected in GUARD_TABLE if expected]
    assert len(guarded) >= 20


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
    question = "THYAO 2026-01-01 ile 2026-03-31 arasında nasıl gitti?"  # Task 10: dates named
    intent = parse_intent(question, client, today=TODAY)
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
        ({"end": TODAY, "start": "2026-11-01"}, None),
        ({"end": "2026-13-01"}, "INVALID_DATE"),
        ({"as_of": "yesterday"}, "INVALID_DATE"),
        ({"start": "2026-11-18", "end": "2026-12-01"}, "FUTURE_DATE"),
        ({"start": "2026-11-18", "end": None}, "FUTURE_DATE"),
        ({"scenario": ADV, "ticker": "ZZZZZ"}, None),
    ],
)
def test_check_intent(over, expected):
    assert check_intent(make(**over), today=TODAY) == expected


# --- fix round 1 (Task 9): the intent check accepts the machine's sector names ------------
@pytest.mark.parametrize(
    "sector",
    ["Telecom", "telecom", "Airlines / Transport", "Airlines", "Telecommunications", "Steel"],
)
def test_check_intent_accepts_peer_group_names_as_the_machine_does(sector):
    intent = make(scenario="SECTOR_LAGGARD", ticker=None, sector=sector)
    assert check_intent(intent, today=TODAY) is None


@pytest.mark.parametrize("sector", ["Spaceflight", "Tele", "Airlines / Banking", ""])
def test_check_intent_still_rejects_an_unknown_sector(sector):
    intent = make(scenario="SECTOR_LAGGARD", ticker=None, sector=sector or " ")
    assert check_intent(intent, today=TODAY) == "UNKNOWN_SECTOR"


def test_the_intent_check_and_the_machine_share_one_sector_resolver():
    from bist_harness.data import peers
    from bist_harness.harness import machine

    names = ["Telecom", "Retail Trade", "Healthcare", "Petroleum", "Astrology", "Tele"]
    for name in names:
        accepted = check_intent(make(ticker=None, sector=name), today=TODAY) is None
        assert accepted == (peers.sector_group(name) is not None), name
        assert machine._sector_group(name) == peers.sector_group(name), name


# --- Task 10: the model's intent is grounded in the question --------------------------------
# Live run, experiment E (qwen3.5:2b): the model filled fields the question does not hold
# (another ticker, an invented sector, dates around its own idea of "now"). Code keeps a
# field only when the question names it; the default period is then built from `today`.
def live_question(qid):
    """The question text of the frozen set, read by id (the set must stay unseen: no copy
    of its text may sit in a test file)."""
    from bist_harness.eval import questions as qs

    return {q["id"]: q for q in qs.load_questions()}[qid]["question"]


def ask(question, **over):
    client = FakeClient(payload(**over))
    intent = parse_intent(question, client, today=TODAY)
    return intent, check_intent(intent, today=TODAY)


def test_live_sl01_takes_the_named_stock_and_drops_the_invented_fields():
    intent, problem = ask(
        live_question("SL-01"),
        scenario="SECTOR_LAGGARD",
        ticker="THYAO",
        sector="HAVAYO",
        start="2024-06-22",
        end="2024-12-19",
        as_of="2024-12-19",
    )
    assert problem is None
    assert (intent.ticker, intent.sector, intent.as_of) == ("PGSUS", None, None)
    assert (intent.start, intent.end) == ("2026-05-21", TODAY)  # 180 days before today
    assert intent.defaulted_period
    assert intent.grounded == {
        "ticker": ["THYAO", "PGSUS"],
        "sector": ["HAVAYO", None],
        "start": ["2024-06-22", None],
        "end": ["2024-12-19", None],
        "as_of": ["2024-12-19", None],
    }


def test_live_cp01_takes_asels_and_defaults_the_period_from_today():
    intent, problem = ask(
        live_question("CP-01"),
        scenario="CALENDAR_PATTERN",
        ticker="THYAO",
        sector="TELECOMS",
        start="2023-10-05",
        end="2023-10-12",
    )
    assert problem is None
    assert (intent.ticker, intent.sector) == ("ASELS", None)
    assert (intent.start, intent.end) == ("2024-11-17", TODAY)  # 730 days before today
    assert intent.defaulted_period
    assert intent.grounded["ticker"] == ["THYAO", "ASELS"]
    assert intent.grounded["start"] == ["2023-10-05", None]


@pytest.mark.parametrize(
    ("qid", "scenario", "ticker", "sector", "as_of", "days"),
    [
        ("TR-01", "TECHNICAL_REVERSAL", "THYAO", "BIST 100", "2023-10-27", 365),
        ("FR-01", "FUNDAMENTAL_REACTION", "BIMAS", "TELECOMS", "2024-01-15", 730),
    ],
)
def test_live_tr01_and_fr01_drop_the_invented_sector_and_as_of(
    qid, scenario, ticker, sector, as_of, days
):
    from datetime import date, timedelta

    intent, problem = ask(
        live_question(qid), scenario=scenario, ticker=ticker, sector=sector, as_of=as_of
    )
    assert problem is None  # no UNKNOWN_SECTOR any more
    assert (intent.ticker, intent.sector, intent.as_of) == (ticker, None, None)
    start = (date.fromisoformat(TODAY) - timedelta(days=days)).isoformat()
    assert (intent.start, intent.end) == (start, TODAY)
    assert intent.grounded == {"sector": [sector, None], "as_of": [as_of, None]}


@pytest.mark.parametrize(
    ("question", "dates"),
    [
        ("THYAO'nun 2025-04-30 tarihli kapanışı neydi?", {"as_of": "2025-04-30"}),
        ("THYAO 12 Şubat 2025 itibarıyla ne durumdaydı?", {"as_of": "2025-02-12"}),
        ("Where did THYAO stand on April 7, 2025?", {"as_of": "2025-04-07"}),
        ("Where did THYAO stand on 7 April 2025?", {"as_of": "2025-04-07"}),
        ("THYAO 07.04.2025 tarihinde ne durumdaydı?", {"as_of": "2025-04-07"}),
        (
            "THYAO 2024-02-01 ile 2024-05-31 arasında nasıl hareket etti?",
            {"start": "2024-02-01", "end": "2024-05-31"},
        ),
        (
            "How did THYAO trade between May 2, 2024 and 14 October 2024?",
            {"start": "2024-05-02", "end": "2024-10-14"},
        ),
        (
            "THYAO 2022 yılında nasıl bir seyir izledi?",
            {"start": "2022-01-01", "end": "2022-12-31"},
        ),
        (
            "How did THYAO trade in the first half of 2022?",
            {"start": "2022-01-01", "end": "2022-06-30"},
        ),
    ],
)
def test_a_date_the_question_names_is_kept(question, dates):
    intent, problem = ask(question, **dates)
    assert problem is None
    for key, value in dates.items():
        assert getattr(intent, key) == value, key
    assert intent.grounded == {}


def test_a_named_date_is_kept_and_an_invented_one_dropped():
    intent, _ = ask(
        "THYAO 2024-02-01 tarihinden bu yana nasıl gitti?", start="2024-02-01", end="2024-09-30"
    )
    assert (intent.start, intent.end) == ("2024-02-01", TODAY)
    assert intent.grounded == {"end": ["2024-09-30", None]}


def test_a_malformed_date_in_the_question_still_reaches_the_check():
    intent, problem = ask("THYAO 2025-02-30 günü ne yaptı?", as_of="2025-02-30")
    assert intent.as_of == "2025-02-30"
    assert problem == "INVALID_DATE"


@pytest.mark.parametrize(
    ("question", "model_ticker", "ticker"),
    [
        ("GARAN hissesi son çeyrekte nasıl gitti?", "GARAN", "GARAN"),  # a reference stock
        ("GARAN hissesi son çeyrekte nasıl gitti?", "AKBNK", "GARAN"),
        ("Summarize the daily moves of AAPL this year.", "AAPL", "AAPL"),
        ("Summarize the daily moves of AAPL this year.", "THYAO", "AAPL"),
        ("AKBMK son dönemde nasıl seyretti?", "AKBNK", "AKBMK"),  # misspelled
    ],
)
def test_an_out_of_universe_ticker_in_the_question_still_gives_unknown_ticker(
    question, model_ticker, ticker
):
    intent, problem = ask(question, ticker=model_ticker)
    assert intent.ticker == ticker
    assert problem == "UNKNOWN_TICKER"


def test_a_ticker_named_by_its_company_name_is_kept():
    intent, problem = ask("Pegasus son üç ayda nasıl gitti?", ticker="PGSUS")
    assert (intent.ticker, problem) == ("PGSUS", None)
    assert "ticker" not in intent.grounded


@pytest.mark.parametrize(
    ("model_ticker", "ticker"),
    [("EREGL", "EREGL"), ("KRDMD", "KRDMD"), ("THYAO", None)],
)
def test_a_question_naming_two_stocks_keeps_the_models_choice_of_them(model_ticker, ticker):
    question = "Compare how EREGL and KRDMD moved over the last month."
    intent, _ = ask(question, scenario="SECTOR_LAGGARD", ticker=model_ticker)
    assert intent.ticker == ticker
    assert ("ticker" in intent.grounded) == (ticker is None)


def test_a_sector_question_without_a_ticker_keeps_a_named_resolvable_sector():
    intent, problem = ask(
        "Bankacılık sektöründe en zayıf kalan hangisi?",
        scenario="SECTOR_LAGGARD",
        ticker=None,
        sector="Banking",
    )
    assert (intent.sector, problem) == ("Banking", None)
    assert intent.grounded == {}


@pytest.mark.parametrize("sector", ["Steel", "Bankacılık"])
def test_a_sector_question_without_ticker_or_named_sector_is_unknown_sector(sector):
    intent, problem = ask(
        "Hangi hisse sektörünün gerisinde kaldı?",
        scenario="SECTOR_LAGGARD",
        ticker=None,
        sector=sector,
    )
    assert intent.sector is None
    assert problem == "UNKNOWN_SECTOR"


@pytest.mark.parametrize(("sector", "kept"), [("Telecom", "Telecom"), ("Banking", None)])
def test_a_sector_is_grounded_by_the_stocks_the_question_names(sector, kept):
    intent, _ = ask(
        "Between TCELL and TTKOM, which one lags its group?",
        scenario="SECTOR_LAGGARD",
        ticker=None,
        sector=sector,
    )
    assert intent.sector == kept


def test_a_named_sector_is_kept_alongside_a_ticker():
    intent, problem = ask(
        "Did TUPRS trail its energy peers last quarter?",
        scenario="SECTOR_LAGGARD",
        ticker="TUPRS",
        sector="Energy / Petrochemicals",
    )
    assert (intent.ticker, intent.sector, problem) == ("TUPRS", "Energy / Petrochemicals", None)


def test_the_guard_path_keeps_its_shape_after_grounding():
    intent, problem = ask("THYAO'yu alayım mı?", scenario="TECHNICAL_REVERSAL", as_of="2024-01-02")
    assert intent.scenario == ADV
    assert (intent.ticker, intent.start, intent.as_of) == ("THYAO", None, None)
    assert not intent.defaulted_period and problem is None


def test_experiment_a_without_the_harness_keeps_the_raw_intent():
    client = FakeClient(payload(ticker="AKBNK", sector="TELECOMS", as_of="2024-01-15"))
    intent = parse_intent("THYAO nasıl gitti?", client, today=TODAY, guard=False)
    assert (intent.ticker, intent.sector, intent.as_of) == ("AKBNK", "TELECOMS", "2024-01-15")
    assert intent.grounded == {}


def test_a_sector_laggard_intent_with_neither_ticker_nor_sector_is_unknown_sector():
    intent = make(scenario="SECTOR_LAGGARD", ticker=None, sector=None)
    assert check_intent(intent, today=TODAY) == "UNKNOWN_SECTOR"
