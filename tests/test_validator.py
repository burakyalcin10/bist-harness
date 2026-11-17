"""Output validator and finite action space at GENERATE_EXPLANATION (card EC-045).

Every rule has a passing and a failing example in Turkish and English. The model is a
scripted fake client; no real model, network or cloud SDK is involved.
"""

import json
from types import SimpleNamespace

import pytest

from bist_harness.errors import LLMUnavailableError
from bist_harness.harness import machine, session
from bist_harness.harness.evidence import DISCLAIMER as EVIDENCE_DISCLAIMER
from bist_harness.harness.evidence import TEMPLATES, WORDS, Evidence
from bist_harness.harness.validator import (
    DISCLAIMER,
    PERIOD_NOTE,
    generate_explanation,
    validate_explanation,
)
from bist_harness.llm.client import ChatResult, ToolCall
from bist_harness.storage import db

LANGS = ("tr", "en")
TODAY = "2026-11-17"
ELIGIBLE = ("HOLD", "WATCH", "INVESTIGATE")
GATE_PASS = SimpleNamespace(status="PASS", hard_blocks=(), warnings=())
QUESTION = {"en": "How did THYAO do?", "tr": "THYAO nasıl gitti?"}


def item(label, tool, field, value, sentence, committed=True):
    return Evidence(label, tool, f"{tool}-1", field, value, sentence, committed)


EVIDENCE = {
    "en": [
        item(
            "E1",
            "get_stock_history",
            "period_return_pct",
            12.35,
            "The closing price of THYAO changed 12.35% between 2025-01-02 and 2025-06-30.",
        ),
        item(
            "E2",
            "get_stock_history",
            "last_close",
            312.5,
            "The last close of THYAO in the period was 312.50 (2025-06-30).",
        ),
        item(
            "E3",
            "get_index_history",
            "period_return_pct",
            4.1,
            "The XU100 index changed 4.10% between 2025-01-02 and 2025-06-30.",
            committed=False,
        ),
        item(
            "E4", "calculate_indicators", "rsi", 41.27, "The RSI of THYAO on 2025-06-30 was 41.27."
        ),
    ],
    "tr": [
        item(
            "E1",
            "get_stock_history",
            "period_return_pct",
            12.35,
            "THYAO kapanış fiyatı 2025-01-02 ile 2025-06-30 arasında %12,35 değişti.",
        ),
        item(
            "E2",
            "get_stock_history",
            "last_close",
            312.5,
            "THYAO için dönem sonu kapanışı 312,50 (2025-06-30).",
        ),
        item(
            "E3",
            "get_index_history",
            "period_return_pct",
            4.1,
            "XU100 endeksi 2025-01-02 ile 2025-06-30 arasında %4,10 değişti.",
            committed=False,
        ),
        item(
            "E4",
            "calculate_indicators",
            "rsi",
            41.27,
            "THYAO için 2025-06-30 tarihinde RSI değeri 41,27.",
        ),
    ],
}

BODY = {
    "en": (
        "THYAO's closing price changed 12.35% between 2025-01-02 and 2025-06-30 [E1]. "
        "On 2025-06-30 its RSI was 41.27 [E4]."
    ),
    "tr": (
        "THYAO kapanış fiyatı 2025-01-02 ile 2025-06-30 arasında %12,35 değişti [E1]. "
        "2025-06-30 tarihinde RSI değeri 41,27 oldu [E4]."
    ),
}
GOOD = {lang: f"{BODY[lang]}\n{DISCLAIMER[lang]}" for lang in LANGS}


def with_sentence(lang: str, sentence: str) -> str:
    """The good explanation with one more sentence before the disclaimer line."""
    return f"{BODY[lang]} {sentence}\n{DISCLAIMER[lang]}"


def check(text, lang, *, action="WATCH", eligible=ELIGIBLE, question=None, defaulted=False):
    return validate_explanation(
        text,
        action=action,
        eligible=eligible,
        evidence=EVIDENCE[lang],
        question=QUESTION[lang] if question is None else question,
        language=lang,
        defaulted_period=defaulted,
    )


def number_problem(value: str) -> str:
    return f"number {value} is not in the committed evidence or the question"


def date_problem(value: str) -> str:
    return f"date {value} is not in the committed evidence or the question"


def uncited(sentence: str, index: int = 1) -> str:
    return f"sentence {index} cites no evidence item: {sentence!r}"


def advice(phrase: str) -> str:
    return f"advice or prediction language: {phrase!r}"


def company(name: str) -> str:
    return f"company or ticker not in the evidence: {name}"


# --- constants ---------------------------------------------------------------------------
def test_the_disclaimer_lines_are_fixed_in_both_languages():
    assert DISCLAIMER["en"] == "Historical evidence only; no guarantee of future return."
    assert DISCLAIMER["tr"] == (
        "Yalnızca geçmiş veriye dayalı kanıt; gelecekteki getiri için garanti yoktur."
    )
    assert DISCLAIMER is EVIDENCE_DISCLAIMER  # one definition, shared with the evidence


@pytest.mark.parametrize("lang", LANGS)
def test_a_faithful_explanation_passes(lang):
    assert check(GOOD[lang], lang) == []


# --- V1: the action is in the eligible set ------------------------------------------------
@pytest.mark.parametrize("lang", LANGS)
def test_an_eligible_action_passes(lang):
    for action in ELIGIBLE:
        assert check(GOOD[lang], lang, action=action) == []


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("action", ["POTENTIAL_CATCH_UP_CANDIDATE", "BUY", "watch"])
def test_an_action_outside_the_eligible_set_fails(lang, action):
    assert check(GOOD[lang], lang, action=action) == [
        f"action {action!r} is not one of the eligible actions: HOLD, WATCH, INVESTIGATE"
    ]


@pytest.mark.parametrize("lang", LANGS)
def test_only_investigate_when_that_is_all_that_is_eligible(lang):
    assert check(GOOD[lang], lang, action="INVESTIGATE", eligible=("INVESTIGATE",)) == []
    assert check(GOOD[lang], lang, action="HOLD", eligible=("INVESTIGATE",)) == [
        "action 'HOLD' is not one of the eligible actions: INVESTIGATE"
    ]


# --- V2: every number and date comes from the committed evidence or the question ---------
NUMBER_CASES = [
    # (language, text in the good explanation, replacement, expected problem)
    ("en", "12.35%", "13%", number_problem("13")),
    ("tr", "%12,35", "%13", number_problem("13")),
    ("en", "12.35%", "12.4%", number_problem("12.4")),  # K-008: no rounding
    ("tr", "%12,35", "%12,4", number_problem("12.4")),
    ("en", "12.35%", "0.1235", number_problem("0.1235")),  # K-008: no %/fraction conversion
    ("tr", "%12,35", "0,1235", number_problem("0.1235")),
    ("en", "12.35%", "-12.35%", number_problem("-12.35")),  # K-008: no sign flip
    ("tr", "%12,35", "%-12,35", number_problem("-12.35")),
    ("en", "On 2025-06-30", "On 2025-07-15", date_problem("2025-07-15")),
    ("tr", "2025-06-30 tarihinde", "15 Temmuz 2025 tarihinde", date_problem("2025-07-15")),
]


@pytest.mark.parametrize(("lang", "old", "new", "problem"), NUMBER_CASES)
def test_an_invented_number_or_date_fails(lang, old, new, problem):
    text = GOOD[lang].replace(old, new, 1)
    assert text != GOOD[lang]
    assert check(text, lang) == [problem]


UNCOMMITTED = {
    "en": "The XU100 index changed 4.10% [E1].",
    "tr": "XU100 endeksi %4,10 değişti [E1].",
}


@pytest.mark.parametrize("lang", LANGS)
def test_a_number_of_an_uncommitted_item_is_not_supported(lang):
    assert check(with_sentence(lang, UNCOMMITTED[lang]), lang) == [number_problem("4.1")]


ASKED = {
    "en": (
        "How did THYAO do over 90 days from 2025-03-03?",
        "The question asks about 90 days from 2025-03-03 [E1].",
    ),
    "tr": (
        "THYAO 2025-03-03'ten itibaren 90 günde nasıl gitti?",
        "Soru 2025-03-03'ten itibaren 90 günü soruyor [E1].",
    ),
}


@pytest.mark.parametrize("lang", LANGS)
def test_numbers_and_dates_of_the_question_are_exempt(lang):
    question, sentence = ASKED[lang]
    text = with_sentence(lang, sentence)
    assert check(text, lang, question=question) == []
    assert check(text, lang) == [number_problem("90"), date_problem("2025-03-03")]


# --- V3: every sentence cites a committed evidence item -----------------------------------
@pytest.mark.parametrize("lang", LANGS)
def test_a_sentence_without_a_citation_fails(lang):
    text = GOOD[lang].replace(" [E1]", "", 1)
    first = text.split("\n")[0].split(". ")[0] + "."
    assert check(text, lang) == [uncited(first)]


@pytest.mark.parametrize("lang", LANGS)
def test_a_citation_of_an_item_that_does_not_exist_fails(lang):
    # Fix round 1: the sentence's number and date are then supported by nothing it cites.
    assert check(GOOD[lang].replace("[E4]", "[E9]"), lang) == [
        "E9 is not an evidence item",
        miscited(2, "number", "41.27", "E9"),
        miscited(2, "date", "2025-06-30", "E9"),
    ]


@pytest.mark.parametrize("lang", LANGS)
def test_a_citation_of_an_uncommitted_item_fails(lang):
    # Only committed items support a number, even when the uncommitted one holds the date.
    assert check(GOOD[lang].replace("[E4]", "[E3]"), lang) == [
        "E3 is not in the committed evidence set",
        miscited(2, "number", "41.27", "E3"),
        miscited(2, "date", "2025-06-30", "E3"),
    ]


# --- Fix round 1, finding 2: numbers are checked against the items the sentence cites ----
def miscited(index: int, kind: str, value: str, labels: str) -> str:
    return (
        f"sentence {index}: {kind} {value} is not in the items it cites ({labels}) or the question"
    )


MISCITED_CASES = [
    # a correct number cited to the wrong item (12.35 is E1's, the sentence cites E4)
    ("en", "41.27 [E4]", "12.35 [E4]", miscited(2, "number", "12.35", "E4")),
    ("tr", "41,27 oldu [E4]", "12,35 oldu [E4]", miscited(2, "number", "12.35", "E4")),
    # a number of an item that another sentence cites (41.27 is E4's, cited in sentence 2)
    ("en", "changed 12.35%", "changed 41.27%", miscited(1, "number", "41.27", "E1")),
    ("tr", "%12,35 değişti", "%41,27 değişti", miscited(1, "number", "41.27", "E1")),
    # a date of another item (2025-01-02 is only in E1's sentence)
    ("en", "On 2025-06-30", "On 2025-01-02", miscited(2, "date", "2025-01-02", "E4")),
    ("tr", "2025-06-30 tarihinde", "2025-01-02 tarihinde", miscited(2, "date", "2025-01-02", "E4")),
]


@pytest.mark.parametrize(("lang", "old", "new", "problem"), MISCITED_CASES)
def test_a_number_or_date_must_come_from_the_items_its_sentence_cites(lang, old, new, problem):
    text = GOOD[lang].replace(old, new, 1)
    assert text != GOOD[lang]
    assert check(text, lang) == [problem]


TWO_ITEMS = {
    "en": "THYAO changed 12.35% and closed at 312.50 on 2025-06-30 [E1, E2].",
    "tr": "THYAO %12,35 değişti ve 2025-06-30 tarihinde 312,50 seviyesinden kapandı [E1][E2].",
}


@pytest.mark.parametrize("lang", LANGS)
def test_a_sentence_citing_two_items_may_use_the_numbers_of_both(lang):
    assert check(f"{TWO_ITEMS[lang]}\n{DISCLAIMER[lang]}", lang) == []
    only_one = TWO_ITEMS[lang].replace("[E1, E2]", "[E1]").replace("[E1][E2]", "[E1]")
    assert check(f"{only_one}\n{DISCLAIMER[lang]}", lang) == [miscited(1, "number", "312.5", "E1")]


CITATION_FORMS = {
    "en": [
        # the label after the full stop, and several labels in one bracket
        "THYAO's closing price changed 12.35% between 2025-01-02 and 2025-06-30. [E1] "
        "On 2025-06-30 its RSI was 41.27. [E4]",
        "THYAO changed 12.35% and its RSI was 41.27 (E1, E4).",
        "- THYAO changed 12.35% [E1]\n- Its RSI was 41.27 [E4]",
    ],
    "tr": [
        "THYAO kapanış fiyatı %12,35 değişti. [E1] RSI değeri 41,27 oldu. [E4]",
        "THYAO %12,35 değişti ve RSI değeri 41,27 oldu (E1, E4).",
        "- THYAO %12,35 değişti [E1]\n- RSI değeri 41,27 [E4]",
    ],
}


@pytest.mark.parametrize("lang", LANGS)
def test_common_citation_forms_pass(lang):
    for body in CITATION_FORMS[lang]:
        assert check(f"{body}\n{DISCLAIMER[lang]}", lang) == [], body


# --- V4: no investment-advice or prediction language -------------------------------------
ADVICE_CASES = [
    ("en", "You should buy THYAO [E1].", "should buy"),
    ("en", "THYAO will rise [E1].", "will rise"),
    ("en", "The return is guaranteed [E1].", "guaranteed"),
    ("en", "THYAO is a STRONG BUY [E1].", "strong buy"),
    ("tr", "THYAO için al tavsiyesi veriyoruz [E1].", "al tavsiyesi"),
    ("tr", "THYAO KESİN YÜKSELİR [E1].", "kesin yukselir"),
    ("tr", "THYAO kesin yukselir [E1].", "kesin yukselir"),  # accent-insensitive
    ("tr", "Getiri garantilidir [E1].", "garantilidir"),
    ("tr", "THYAO hissesini tutmalısınız [E1].", "tutmalisiniz"),
]


@pytest.mark.parametrize(("lang", "sentence", "phrase"), ADVICE_CASES)
def test_advice_or_prediction_language_fails(lang, sentence, phrase):
    assert check(with_sentence(lang, sentence), lang) == [advice(phrase)]


NOT_ADVICE = {
    "en": [
        "This is not investment advice [E1].",
        "There is no guarantee of a return [E1].",
        "The strategy is compared with a buy-and-hold benchmark [E1].",
        "The eligible labels are HOLD, WATCH and INVESTIGATE [E1].",
        "HOLD: the evidence does not single out a direction [E1].",
        "The price rose in the period [E1].",
    ],
    "tr": [
        "Bu bir yatırım tavsiyesi değildir [E1].",
        "Strateji al-tut kıyasıyla karşılaştırıldı [E1].",
        "Fiyat dönem içinde yükseldi [E1].",
        "Fiyat artarak dönemi tamamladı [E1].",
        "RSI aşırı satım bölgesinde değildi [E1].",
        # Fix round 2: ordinary passives with "alınmalı" / "tutulmalı" are not advice.
        "Bu durum dikkate alınmalıdır [E1].",
        "Riskler dikkate alınmalıdır [E1].",
        "Bu fark hesaba katılmalıdır [E1].",
        "Bu sonuç göz önüne alınmalıdır [E1].",
        "Bu konu ayrıca ele alınmalıdır [E1].",
        "Bu sınır akılda tutulmalıdır [E1].",
        "Bu fark göz önünde tutulmalıdır [E1].",
    ],
}


@pytest.mark.parametrize("lang", LANGS)
def test_the_disclaimer_itself_is_not_advice(lang):
    # The Turkish disclaimer contains "garanti"; the disclaimer line is not advice.
    assert check(GOOD[lang], lang) == []


@pytest.mark.parametrize(
    ("lang", "sentence"), [(lang, s) for lang in LANGS for s in NOT_ADVICE[lang]]
)
def test_descriptive_sentences_are_not_advice(lang, sentence):
    assert check(with_sentence(lang, sentence), lang) == []


# --- Fix round 1, finding 1: suffixed stems and hedged forms ------------------------------
ADVICE_BYPASSES = {
    "tr": [
        "Hisse alınmalıdır",
        "Hisse satılmalıdır",
        "Hisse elde tutulmalıdır",
        "Hisse satın alınmalıdır",
        "Fiyat artacaktır",
        "Fiyat azalacaktır",
        "Bu bir yatırım tavsiyesidir",
        "Yatırımcı almalı",
        "Bu hisseyi öneriyoruz",
        "Bu hisseyi öneririz",
        "Hisse almaya değer",
        "Bu bir al sinyalidir",
        "Satın alın",
        "Hisse alın",
        "Fiyat yükselir",
        "Fiyat yükselebilir",
        "Fiyatın yükselmesi bekleniyor",
        "Fiyatın yükselmesi muhtemel",
        "Yükselmeye devam edecek",
        "Hisseyi alabilirsiniz",
    ],
    "en": [
        "Sell",
        "Buy",
        "Buy THYAO now",
        "It is a buy",
        "I would buy",
        "We suggest selling",
        "I suggest buying",
        "Consider buying",
        "You should consider buying",
        "Investors may want to buy",
        "A guarantee of return",
        "THYAO will probably rise",
        "THYAO will likely rise",
        "THYAO is expected to rise",
        "It should rise",
        "THYAO will outperform",
        "THYAO will continue to fall",
        "The price may fall",
    ],
}
BYPASS_CASES = [(lang, s) for lang in LANGS for s in ADVICE_BYPASSES[lang]]


@pytest.mark.parametrize(("lang", "sentence"), BYPASS_CASES)
def test_suffixed_and_hedged_advice_or_prediction_fails(lang, sentence):
    problems = check(with_sentence(lang, f"{sentence} [E1]."), lang)
    assert len(problems) == 1 and problems[0].startswith("advice or prediction language: "), (
        problems
    )


def _template_texts(lang: str) -> list[str]:
    texts = [templates[lang] for templates in TEMPLATES.values()]
    texts += [f"The state was {word} [E1]." for word in WORDS[lang].values()]
    return texts


@pytest.mark.parametrize("lang", LANGS)
def test_no_evidence_template_or_word_reads_as_advice(lang):
    for text in _template_texts(lang):
        problems = check(f"{text} [E1]\n{DISCLAIMER[lang]}", lang)
        assert not [p for p in problems if p.startswith("advice")], (text, problems)


# --- V5: the mandatory disclaimer line ------------------------------------------------------
@pytest.mark.parametrize("lang", LANGS)
def test_a_missing_disclaimer_fails(lang):
    assert check(BODY[lang], lang) == [f"the disclaimer line is missing: {DISCLAIMER[lang]!r}"]


def test_the_disclaimer_must_be_in_the_answer_language():
    tr_with_en = f"{BODY['tr']}\n{DISCLAIMER['en']}"
    assert check(tr_with_en, "tr") == [
        f"the disclaimer line is missing: {DISCLAIMER['tr']!r}",
        uncited(DISCLAIMER["en"], 3),
    ]
    en_with_tr = f"{BODY['en']}\n{DISCLAIMER['tr']}"
    assert check(en_with_tr, "en") == [
        f"the disclaimer line is missing: {DISCLAIMER['en']!r}",
        uncited(DISCLAIMER["tr"], 3),
        advice("garanti"),
    ]


# --- V6: no company or ticker outside the evidence set ----------------------------------
SAME_COMPANY = {
    "en": "Turkish Airlines is the company behind THYAO [E1].",
    "tr": "Türk Hava Yolları, THYAO kodlu şirkettir [E1].",
}
OTHER_COMPANY = [
    ("en", "ASELS changed less [E1].", "ASELS"),
    ("en", "Aselsan moved less [E1].", "Aselsan (ASELS)"),
    ("tr", "ASELS daha az değişti [E1].", "ASELS"),
    ("tr", "Pegasus'un fiyatı da değişti [E1].", "Pegasus (PGSUS)"),
    ("tr", "GARAN da yükseldi [E1].", "GARAN"),  # a peer of the study, not in the evidence
]


@pytest.mark.parametrize("lang", LANGS)
def test_the_company_of_the_evidence_and_the_index_pass(lang):
    assert check(with_sentence(lang, SAME_COMPANY[lang]), lang) == []
    index = {"en": "The XU100 index is the benchmark [E1].", "tr": "Kıyas endeksi XU100 [E1]."}
    assert check(with_sentence(lang, index[lang]), lang) == []


@pytest.mark.parametrize(("lang", "sentence", "name"), OTHER_COMPANY)
def test_a_company_or_ticker_outside_the_evidence_fails(lang, sentence, name):
    assert check(with_sentence(lang, sentence), lang) == [company(name)]


# --- V7: a defaulted period is said ------------------------------------------------------
@pytest.mark.parametrize("lang", LANGS)
def test_a_defaulted_period_must_be_said(lang):
    noted = f"{BODY[lang]}\n{PERIOD_NOTE[lang]}\n{DISCLAIMER[lang]}"
    assert check(noted, lang, defaulted=True) == []
    assert check(GOOD[lang], lang, defaulted=True) == [
        f"the default-period note is missing: {PERIOD_NOTE[lang]!r}"
    ]
    assert check(noted, lang, defaulted=False) == [
        "the default-period note is present but the question gave a period"
    ]


# --- determinism ---------------------------------------------------------------------------
def test_problems_come_in_a_fixed_order():
    text = "THYAO changed 13% between 2025-01-02 and 2025-06-30. You should buy ASELS [E9]."
    expected = [
        "action 'BUY' is not one of the eligible actions: HOLD, WATCH, INVESTIGATE",
        f"the disclaimer line is missing: {DISCLAIMER['en']!r}",
        uncited("THYAO changed 13% between 2025-01-02 and 2025-06-30."),
        "E9 is not an evidence item",
        number_problem("13"),
        advice("should buy"),
        company("ASELS"),
    ]
    assert check(text, "en", action="BUY") == expected
    assert check(text, "en", action="BUY") == expected


# --- generate_explanation: schema, one re-ask, then the evidence set and INVESTIGATE ------
def reply(content: str = "", calls=()) -> ChatResult:
    return ChatResult(
        content=content,
        tool_calls=tuple(calls),
        prompt_tokens=0,
        completion_tokens=0,
        total_duration_s=0.0,
        eval_tokens_per_s=None,
        raw={},
    )


class FakeClient:
    """Scripted stand-in for OllamaClient: a string is a text reply, a list is tool calls,
    an exception is raised."""

    model = "fake-model"

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[dict] = []

    def chat(self, messages, tools=None, **kwargs):
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tools, **kwargs})
        if not self.script:
            raise AssertionError("the model was asked more often than scripted")
        item_ = self.script.pop(0)
        if isinstance(item_, BaseException):
            raise item_
        if isinstance(item_, list):
            return reply("", item_)
        return reply(item_)


def answer(action: str, text: str) -> str:
    return json.dumps({"action": action, "explanation": text}, ensure_ascii=False)


def analysis_for(lang: str, *, defaulted: bool = False) -> session.Analysis:
    return session.Analysis(
        analysis_id="AN-test00000001",
        question=QUESTION[lang],
        created_at="2026-11-17T00:00:00+00:00",
        model="fake-model",
        snapshot_id="snap",
        adjustments_id="adj",
        intent={
            "scenario": "PRICE_SUMMARY",
            "ticker": "THYAO",
            "language": lang,
            "defaulted_period": defaulted,
        },
    )


def prompt_of(request: dict) -> str:
    return "\n".join(m["content"] for m in request["messages"])


def fallback_text(lang: str, *, defaulted: bool = False) -> str:
    lines = ["INVESTIGATE"]
    lines += [f"{e.label}: {e.sentence}" for e in EVIDENCE[lang] if e.committed]
    if defaulted:
        lines.append(PERIOD_NOTE[lang])
    lines.append(DISCLAIMER[lang])
    return "\n".join(lines)


@pytest.mark.parametrize("lang", LANGS)
def test_a_valid_first_reply_is_accepted(lang):
    client = FakeClient(answer("WATCH", GOOD[lang]))
    result = generate_explanation(analysis_for(lang), client, EVIDENCE[lang], GATE_PASS)
    assert (result.action, result.text) == ("WATCH", GOOD[lang])
    assert result.eligible == list(ELIGIBLE)
    assert (result.attempts, result.fallback, result.problems) == (1, False, [])
    assert len(client.requests) == 1


@pytest.mark.parametrize("lang", LANGS)
def test_the_reply_is_constrained_to_the_eligible_labels(lang):
    client = FakeClient(answer("WATCH", GOOD[lang]))
    generate_explanation(analysis_for(lang), client, EVIDENCE[lang], GATE_PASS)
    request = client.requests[0]
    assert request["tools"] is None  # GENERATE_EXPLANATION has no tools
    assert (request["temperature"], request["seed"]) == (0.0, 42)
    schema = request["response_format"]
    assert schema["type"] == "object"
    assert schema["required"] == ["action", "explanation"]
    assert schema["properties"]["action"] == {"type": "string", "enum": list(ELIGIBLE)}
    assert schema["properties"]["explanation"] == {"type": "string"}


@pytest.mark.parametrize("lang", LANGS)
def test_the_prompt_shows_only_the_committed_evidence(lang):
    client = FakeClient(answer("WATCH", GOOD[lang]))
    generate_explanation(analysis_for(lang), client, EVIDENCE[lang], GATE_PASS)
    prompt = prompt_of(client.requests[0])
    for evidence in EVIDENCE[lang]:
        line = f"{evidence.label}: {evidence.sentence}"
        assert (line in prompt) is evidence.committed
    assert QUESTION[lang] in prompt and DISCLAIMER[lang] in prompt
    assert "HOLD, WATCH, INVESTIGATE" in prompt
    assert {"tr": "Turkish", "en": "English"}[lang] in prompt
    assert PERIOD_NOTE[lang] not in prompt


@pytest.mark.parametrize("lang", LANGS)
def test_a_defaulted_period_is_asked_for_and_checked(lang):
    noted = f"{BODY[lang]}\n{PERIOD_NOTE[lang]}\n{DISCLAIMER[lang]}"
    client = FakeClient(answer("WATCH", GOOD[lang]), answer("WATCH", noted))
    result = generate_explanation(
        analysis_for(lang, defaulted=True), client, EVIDENCE[lang], GATE_PASS
    )
    assert PERIOD_NOTE[lang] in prompt_of(client.requests[0])
    assert result.problems == [[f"the default-period note is missing: {PERIOD_NOTE[lang]!r}"]]
    assert (result.action, result.text, result.attempts) == ("WATCH", noted, 2)


@pytest.mark.parametrize("lang", LANGS)
def test_a_rejected_reply_is_asked_again_once_with_the_problems(lang):
    bad = answer("BUY", GOOD[lang])
    client = FakeClient(bad, answer("HOLD", GOOD[lang]))
    result = generate_explanation(analysis_for(lang), client, EVIDENCE[lang], GATE_PASS)
    problem = "action 'BUY' is not one of the eligible actions: HOLD, WATCH, INVESTIGATE"
    assert (result.action, result.text, result.attempts, result.fallback) == (
        "HOLD",
        GOOD[lang],
        2,
        False,
    )
    assert result.problems == [[problem]]
    second = client.requests[1]["messages"]
    assert second[-2] == {"role": "assistant", "content": bad}
    assert second[-1]["role"] == "user" and problem in second[-1]["content"]


@pytest.mark.parametrize("lang", LANGS)
def test_a_second_failure_shows_only_the_evidence_set_and_investigate(lang):
    client = FakeClient(answer("BUY", GOOD[lang]), answer("WATCH", BODY[lang]))
    result = generate_explanation(analysis_for(lang), client, EVIDENCE[lang], GATE_PASS)
    assert (result.action, result.attempts, result.fallback) == ("INVESTIGATE", 2, True)
    assert result.text == fallback_text(lang)
    assert result.problems == [
        ["action 'BUY' is not one of the eligible actions: HOLD, WATCH, INVESTIGATE"],
        [f"the disclaimer line is missing: {DISCLAIMER[lang]!r}"],
    ]
    assert len(client.requests) == 2  # asked again once, never a third time


@pytest.mark.parametrize(
    "content", ["not json", "[1, 2]", '{"action": "WATCH"}', '{"action": 1, "explanation": "x"}']
)
def test_a_reply_that_is_not_the_json_object_is_a_failed_attempt(content):
    client = FakeClient(content, content)
    result = generate_explanation(analysis_for("en"), client, EVIDENCE["en"], GATE_PASS)
    assert result.fallback and result.action == "INVESTIGATE"
    assert (
        result.problems
        == [["the reply is not a JSON object with a string action and explanation"]] * 2
    )


def test_without_committed_evidence_the_model_is_not_asked():
    evidence = [e for e in EVIDENCE["en"] if not e.committed]
    client = FakeClient()
    result = generate_explanation(analysis_for("en"), client, evidence, GATE_PASS)
    assert client.requests == []
    assert (result.action, result.attempts, result.fallback) == ("INVESTIGATE", 0, True)
    assert result.eligible == ["INVESTIGATE"]
    assert result.text == f"INVESTIGATE\n{DISCLAIMER['en']}"


def test_incomplete_evidence_offers_only_investigate():
    evidence = [e for e in EVIDENCE["en"] if e.label != "E4"]  # no technical-state item
    client = FakeClient(
        answer("INVESTIGATE", BODY["en"].split(" On ")[0] + f"\n{DISCLAIMER['en']}")
    )
    result = generate_explanation(analysis_for("en"), client, evidence, GATE_PASS)
    assert client.requests[0]["response_format"]["properties"]["action"]["enum"] == ["INVESTIGATE"]
    assert (result.action, result.eligible, result.fallback) == (
        "INVESTIGATE",
        ["INVESTIGATE"],
        False,
    )


def test_a_model_error_is_not_swallowed():
    client = FakeClient(LLMUnavailableError("down"))
    with pytest.raises(LLMUnavailableError):
        generate_explanation(analysis_for("en"), client, EVIDENCE["en"], GATE_PASS)


# --- the machine: the outcome is the chosen action label -----------------------------------
PERIOD = {"start": "2025-01-02", "end": "2025-06-30"}
# The machine keeps only the dates a question names (Task 10): the run questions name them.
RUN_QUESTION = {
    "en": "How did THYAO do from 2025-01-02 to 2025-06-30?",
    "tr": "THYAO 2025-01-02 ile 2025-06-30 arasında nasıl gitti?",
}


class FakeTools:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, dict(arguments)))
        output = {"result_id": f"{name}-{len(self.calls)}"}
        if name == "check_data_quality":
            output["status"] = "PASS"
        return output


@pytest.fixture(autouse=True)
def private_store(monkeypatch, tmp_path):
    """No test may read or create the real store in the data directory."""
    path = tmp_path / "default-store.sqlite"
    monkeypatch.setattr(session, "_store_path", lambda: path)
    return path


def run_script(lang: str, *explanations):
    intent = {
        "scenario": "PRICE_SUMMARY",
        "ticker": "THYAO",
        "sector": None,
        "as_of": None,
        "language": lang,
        **PERIOD,
    }
    return (
        json.dumps(intent),
        [
            ToolCall("get_stock_history", {"ticker": "THYAO", **PERIOD}),
            ToolCall("get_index_history", {"index": "XU100", **PERIOD}),
        ],
        [ToolCall("calculate_indicators", {"ticker": "THYAO", "indicators": [], **PERIOD})],
        *explanations,
    )


def run(lang: str, client, **kwargs):
    return machine.run_analysis(
        RUN_QUESTION[lang],
        client,
        call_tool=FakeTools(),
        today=TODAY,
        evidence_fn=lambda analysis, language: EVIDENCE[language],
        gate_fn=lambda analysis, evidence: GATE_PASS,
        **kwargs,
    )


def explanation_record(analysis):
    return next(r for r in analysis.trail if r.state == "GENERATE_EXPLANATION")


@pytest.mark.parametrize("lang", LANGS)
def test_the_run_ends_with_the_chosen_label_and_the_checked_explanation(lang):
    client = FakeClient(*run_script(lang, answer("WATCH", GOOD[lang])))
    analysis = run(lang, client)
    assert analysis.outcome == "WATCH"
    assert analysis.answer == GOOD[lang]
    record = explanation_record(analysis)
    assert record.status == "RAN"
    assert record.detail == {
        "action": "WATCH",
        "eligible": list(ELIGIBLE),
        "attempts": 1,
        "fallback": False,
        "problems": [],
    }
    assert len(client.requests) == 4
    assert client.requests[-1]["tools"] is None and "response_format" in client.requests[-1]


@pytest.mark.parametrize("lang", LANGS)
def test_two_rejected_explanations_end_in_investigate_with_the_evidence(lang, tmp_path):
    conn = db.connect(tmp_path / "validator.sqlite")
    try:
        client = FakeClient(*run_script(lang, answer("BUY", GOOD[lang]), answer("BUY", GOOD[lang])))
        analysis = run(lang, client, conn=conn)
        assert analysis.outcome == "INVESTIGATE"
        assert analysis.answer == fallback_text(lang)
        record = explanation_record(analysis)
        assert record.detail["fallback"] is True and record.detail["attempts"] == 2
        loaded = session.load(analysis.analysis_id, conn)
        assert (loaded.outcome, loaded.answer) == ("INVESTIGATE", fallback_text(lang))
        assert loaded.trail == analysis.trail
    finally:
        conn.close()


def test_with_the_default_hooks_and_no_evidence_the_run_ends_investigate():
    client = FakeClient(*run_script("en"))
    analysis = machine.run_analysis(RUN_QUESTION["en"], client, call_tool=FakeTools(), today=TODAY)
    assert analysis.outcome == "INVESTIGATE"
    assert analysis.answer == f"INVESTIGATE\n{DISCLAIMER['en']}"
    assert len(client.requests) == 3  # no committed evidence: no explanation turn
    assert explanation_record(analysis).detail["fallback"] is True


def test_a_model_error_in_the_explanation_still_ends_model_unavailable():
    client = FakeClient(*run_script("en", LLMUnavailableError("down")))
    analysis = run("en", client)
    assert analysis.outcome == "MODEL_UNAVAILABLE"
    assert analysis.answer == machine.MODEL_UNAVAILABLE_ANSWERS["en"]
    assert explanation_record(analysis).status == "FAILED"


# --- public helpers for the evaluation (Task 9) -------------------------------------------
def test_advice_language_lists_the_phrases_the_validator_rejects():
    from bist_harness.harness.validator import advice_language

    assert advice_language("You should buy THYAO now. [E1]") == ["should buy"]
    assert advice_language("Bu hisse kesin yükselir. [E1]") == ["kesin yukselir"]
    assert advice_language("The RSI of THYAO on 2025-06-30 was 41.27. [E4]") == []


def test_unsupported_values_follow_the_whole_set_and_the_sentence_rule():
    from bist_harness.harness.validator import unsupported_values

    committed = [e for e in EVIDENCE["en"] if e.committed]
    question = QUESTION["en"]
    clean = "THYAO changed 12.35% [E1] and its RSI was 41.27 on 2025-06-30. [E4]"
    assert unsupported_values(clean, committed, question) == ([], [])
    invented = "THYAO changed 12.4% by 2025-07-15. [E1]"
    assert unsupported_values(invented, committed, question) == ([12.4], ["2025-07-15"])
    # 41.27 is in the committed set, but this sentence cites only E1: rule 5, per sentence.
    wrong_cite = "The RSI was 41.27. [E1] The RSI was 41.27 again. [E1]"
    assert unsupported_values(wrong_cite, committed, question) == ([41.27], [])
    # 4.10 is only in E3, which is not committed.
    assert unsupported_values("The index moved 4.10%. [E3]", committed, question) == ([4.1], [])


# --- fix round 1: the system's own fixed answers are not advice ---------------------------
def _fixed_answers():
    reasons = (  # every code check_intent can return
        "UNKNOWN_TICKER",
        "MISSING_TICKER",
        "UNKNOWN_SECTOR",
        "INVALID_DATE",
        "FUTURE_DATE",
        "INVALID_DATE_RANGE",
    )
    found = []
    for table in (
        machine.REFUSAL_ANSWERS,
        machine.OUT_OF_SCOPE_ANSWERS,
        machine.MODEL_UNAVAILABLE_ANSWERS,
    ):
        found += [(lang, text) for lang, text in table.items()]
    for lang, text in machine.UNSAFE_ANSWERS.items():
        found += [(lang, text.format(reason=reason)) for reason in reasons]
    return found


@pytest.mark.parametrize("lang, text", _fixed_answers())
def test_every_fixed_system_answer_passes_the_advice_check(lang, text):
    from bist_harness.harness.validator import advice_language

    assert advice_language(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "Bu sistem yatırım tavsiyesi ya da fiyat tahmini vermez. [E1]",
        "Bu cevap yatırım tavsiyesi veya kesin bir yorum içermez. [E1]",
        "Bu metin yatırım tavsiyesi değildir. [E1]",
        "Bu bilgiler yatırım tavsiyesi niteliği taşımaz. [E1]",
        "Bu analiz yatırım tavsiyesi niteliğinde değildir. [E1]",
        "Bu metin yatırım tavsiyesi niteliğinde değil. [E1]",
        "Bu sonuçların yatırım tavsiyesi niteliği yoktur. [E1]",
        "Bu bilgiler yatırım tavsiyesi veya öneri niteliği taşımaz. [E1]",
    ],
)
def test_a_negated_investment_advice_phrase_is_not_advice(text):
    from bist_harness.harness.validator import advice_language

    assert advice_language(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "Bu bir yatırım tavsiyesidir ve THYAO için geçerlidir. [E1]",
        "Bu yatırım tavsiyesi ya da yorum olarak okunabilir. [E1]",
        "Bu bir yatırım tavsiyesi niteliğindedir [E1].",
        "Bu bir yatırım tavsiyesi niteliğindedir ve THYAO için geçerlidir. [E1]",
        "Bu yatırım tavsiyesi veya öneri niteliğindedir. [E1]",
        "Bu yatırım tavsiyesi niteliği taşır. [E1]",
        "Bu bir yatırım tavsiyesi niteliğinde bir değerlendirmedir. [E1]",
    ],
)
def test_an_investment_advice_claim_is_still_advice(text):
    from bist_harness.harness.validator import advice_language

    assert advice_language(text) != []


# --- M2: a note that fits a half-given period -----------------------------------------------
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("bound", ["start", "end"])
def test_a_half_given_period_needs_its_own_note(lang, bound):
    from bist_harness.harness.validator import period_note

    note = period_note(lang, bound)
    assert note != PERIOD_NOTE[lang]
    noted = f"{BODY[lang]}\n{note}\n{DISCLAIMER[lang]}"
    full = f"{BODY[lang]}\n{PERIOD_NOTE[lang]}\n{DISCLAIMER[lang]}"

    def check_bound(text):
        return validate_explanation(
            text,
            action="WATCH",
            eligible=ELIGIBLE,
            evidence=EVIDENCE[lang],
            question=QUESTION[lang],
            language=lang,
            defaulted_period=True,
            defaulted_bound=bound,
        )

    assert check_bound(noted) == []
    assert f"the default-period note is missing: {note!r}" in check_bound(full)
    assert check(noted, lang, defaulted=False) == [
        "the default-period note is present but the question gave a period"
    ]


@pytest.mark.parametrize("lang", LANGS)
def test_a_half_given_period_is_asked_for_and_falls_back_with_its_note(lang):
    from bist_harness.harness.validator import period_note

    analysis = analysis_for(lang, defaulted=True)
    analysis.intent["defaulted_bound"] = "end"
    note = period_note(lang, "end")
    noted = f"{BODY[lang]}\n{note}\n{DISCLAIMER[lang]}"
    client = FakeClient(answer("WATCH", noted))
    result = generate_explanation(analysis, client, EVIDENCE[lang], GATE_PASS)
    assert note in prompt_of(client.requests[0])
    assert PERIOD_NOTE[lang] not in prompt_of(client.requests[0])
    assert (result.action, result.text, result.fallback) == ("WATCH", noted, False)
    bad = FakeClient(answer("WATCH", GOOD[lang]), answer("WATCH", GOOD[lang]))
    fallback = generate_explanation(analysis, bad, EVIDENCE[lang], GATE_PASS)
    assert fallback.fallback and note in fallback.text and PERIOD_NOTE[lang] not in fallback.text
