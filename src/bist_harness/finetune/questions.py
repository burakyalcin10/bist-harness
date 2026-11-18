"""Templated question generator and the frozen-set overlap filter (Sprint 5, Task 2).

Fine-tuning questions are built from templates, not written one by one. A ``Family`` is
one kind of question (a scenario in one reference mode, or one negative kind) with
Turkish and English paraphrases, formal and colloquial; ``generate`` fills them with a
stock, a company name or a lower-case code, and a period, and returns each question with
its ``Gold`` (the correct intent, see ``finetune.teacher``) and its ``today``.

Rules the generator keeps:

* The gold intent holds only what the question text names (``ground_intent`` leaves it
  unchanged): the ticker by code or company name, dates only when written, no sector.
* Every date and every ``today`` is before 2025-01-01 (the pre-registered test period);
  a period ends on or before its ``today`` (the future-date family is the one exception,
  and its dates are still before 2025).
* Only ``random.Random(seed)`` is used: the same seed gives the same list.

``drop_overlaps`` removes a question that copies the frozen evaluation set (text
similarity, ``eval.questions.overlaps``) or carries the same (stock, start, end) triple as
a frozen question's expected intent.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from bist_harness.data import peers
from bist_harness.eval import questions as frozen
from bist_harness.finetune.teacher import DEFAULT_PREFERENCE, Gold
from bist_harness.harness.intent import _WORD_CODES, Intent, ground_intent
from bist_harness.harness.validator import COMPANY_NAMES
from bist_harness.universe import load_universe

__all__ = [
    "FAMILIES",
    "Family",
    "GenQuestion",
    "REACHABLE_BY_DEFAULT",
    "drop_overlaps",
    "generate",
]

LANGS = ("tr", "en")
TODAY_RANGE = ("2019-06-01", "2024-12-31")
CUTOFF = "2025-01-01"  # the pre-registered test period starts here
DATA_START = date(2018, 1, 1)
# Labels the teacher reaches without an explicit gold action (HOLD never: WATCH wins).
REACHABLE_BY_DEFAULT = frozenset(DEFAULT_PREFERENCE) - {"HOLD"}
FOREIGN_CODES = ("AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "NFLX", "INTC", "ORCL")

_TR_PLAIN = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC")
_MONTHS_TR = "Ocak Şubat Mart Nisan Mayıs Haziran Temmuz Ağustos Eylül Ekim Kasım Aralık".split()
_MONTHS_EN = (
    "January February March April May June July August September October November December"
).split()


@dataclass(frozen=True)
class GenQuestion:
    question_id: str
    family: str
    language: str
    text: str
    gold: Gold
    today: str  # the run's reference date, passed to ``run_analysis``
    # the paraphrase the text was written from (one of the family's templates for its
    # language, unformatted); the build holds some paraphrases out of training by it
    template: str


@dataclass(frozen=True)
class Family:
    """One question kind: paraphrases per language and how a question is built from them."""

    name: str
    description: str
    templates: dict[str, tuple[str, ...]]
    # (text, gold, today, template)
    make: Callable[[Family, random.Random, str, tuple[str, str]], tuple[str, Gold, str, str]]
    scenario: str = ""
    mode: str = "code"  # how a stock is written: code | company | lower | any
    dated: bool | None = None  # True always, False never, None by chance
    action: str | None = None  # explicit gold action; None leaves it to the teacher
    extra: dict = field(default_factory=dict, compare=False)


# --- parameters ------------------------------------------------------------------------
def _universe() -> list[str]:
    return sorted(load_universe()["ticker"])


def _outside() -> list[str]:
    inside = set(_universe())
    reference = sorted(
        t for t in peers.all_symbols() if t not in inside and t.isalpha() and 4 <= len(t) <= 6
    )
    return [*FOREIGN_CODES, *reference]


def _iso(d: date) -> str:
    return d.isoformat()


def _random_day(rng: random.Random, lo: str, hi: str) -> date:
    a, b = date.fromisoformat(lo), date.fromisoformat(hi)
    return a + timedelta(days=rng.randint(0, (b - a).days))


def _stock(rng: random.Random, mode: str) -> tuple[str, str]:
    """``(ticker, how the question writes it)``."""
    if mode == "any":
        mode = rng.choice(("code", "code", "company", "lower"))
    tickers = _universe()
    if mode == "company":
        ticker = rng.choice([t for t in tickers if t in COMPANY_NAMES])
        return ticker, rng.choice(COMPANY_NAMES[ticker])
    if mode == "lower":
        ticker = rng.choice([t for t in tickers if t not in _WORD_CODES])
        return ticker, ticker.lower()
    ticker = rng.choice(tickers)
    return ticker, ticker


def _period_words(rng: random.Random, lang: str, start: str, end: str) -> str:
    """The period as the question writes it; Turkish leads the sentence, English trails."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    if lang == "tr":
        if rng.random() < 0.5:
            a, b = start, end
        else:
            a = f"{s.day} {_MONTHS_TR[s.month - 1]} {s.year}"
            b = f"{e.day} {_MONTHS_TR[e.month - 1]} {e.year}"
        return rng.choice(
            (f"{a} ile {b} arasında ", f"{a} - {b} döneminde ", f"{a} ile {b} arasındaki dönemde ")
        )
    if rng.random() < 0.5:
        a, b = start, end
    elif rng.random() < 0.5:
        a = f"{_MONTHS_EN[s.month - 1]} {s.day}, {s.year}"
        b = f"{_MONTHS_EN[e.month - 1]} {e.day}, {e.year}"
    else:
        a = f"{s.day} {_MONTHS_EN[s.month - 1]} {s.year}"
        b = f"{e.day} {_MONTHS_EN[e.month - 1]} {e.year}"
    return rng.choice((f" between {a} and {b}", f" from {a} to {b}", f" during {a} to {b}"))


def _period(rng: random.Random, today: str) -> tuple[str, str]:
    """A period that ends on or before ``today``."""
    end = date.fromisoformat(today) - timedelta(days=rng.randint(0, 45))
    start = max(end - timedelta(days=rng.randint(60, 540)), DATA_START)
    return _iso(start), _iso(end)


def _intent(scenario: str, lang: str, **fields: str | None) -> dict:
    base = {"ticker": None, "sector": None, "start": None, "end": None, "as_of": None}
    return {"scenario": scenario, "language": lang, **base, **fields}


def _plain(text: str, lang: str, rng: random.Random) -> str:
    """Some Turkish questions are typed without diacritics, as people type on a phone."""
    return text.translate(_TR_PLAIN) if lang == "tr" and rng.random() < 0.2 else text


def _maybe_period(
    fam: Family, rng: random.Random, lang: str, today: str, chance: float = 0.5
) -> tuple[str | None, str | None, str]:
    dated = fam.dated if fam.dated is not None else rng.random() < chance
    if not dated:
        return None, None, ""
    start, end = _period(rng, today)
    return start, end, _period_words(rng, lang, start, end)


# --- builders --------------------------------------------------------------------------
def _scenario_question(fam, rng, lang, today_range):
    today = _iso(_random_day(rng, *today_range))
    ticker, ref = _stock(rng, fam.mode)
    start, end, when = _maybe_period(fam, rng, lang, today)
    template = rng.choice(fam.templates[lang])
    text = template.format(ref=ref, when=when)
    gold = Gold(_intent(fam.scenario, lang, ticker=ticker, start=start, end=end), fam.action)
    return _plain(text, lang, rng), gold, today, template


def _macro_question(fam, rng, lang, today_range):
    today = _iso(_random_day(rng, *today_range))
    start, end, when = _maybe_period(fam, rng, lang, today)
    template = rng.choice(fam.templates[lang])
    text = template.format(when=when)
    gold = Gold(_intent(fam.scenario, lang, start=start, end=end), fam.action)
    return _plain(text, lang, rng), gold, today, template


def _guarded_question(fam, rng, lang, today_range):
    """Advice and prediction: a stock and no dates."""
    today = _iso(_random_day(rng, *today_range))
    ticker, ref = _stock(rng, "any")
    template = rng.choice(fam.templates[lang])
    text = template.format(ref=ref)
    gold = Gold(_intent(fam.scenario, lang, ticker=ticker))
    return _plain(text, lang, rng), gold, today, template


def _outside_question(fam, rng, lang, today_range):
    today = _iso(_random_day(rng, *today_range))
    ticker = rng.choice(_outside())
    ref = ticker.lower() if rng.random() < 0.2 else ticker
    start, end, when = _maybe_period(fam, rng, lang, today, chance=0.4)
    template = rng.choice(fam.templates[lang])
    text = template.format(ref=ref, when=when)
    gold = Gold(_intent("PRICE_SUMMARY", lang, ticker=ticker, start=start, end=end))
    return _plain(text, lang, rng), gold, today, template


def _future_question(fam, rng, lang, today_range):
    lo, hi = date.fromisoformat(today_range[0]), date.fromisoformat(today_range[1])
    today = _iso(_random_day(rng, today_range[0], _iso(lo + (hi - lo) / 2)))
    ticker, ref = _stock(rng, "any")
    start_d = date.fromisoformat(today) + timedelta(days=rng.randint(60, 300))
    end_d = min(start_d + timedelta(days=rng.randint(30, 150)), hi)
    start, end = _iso(start_d), _iso(end_d)
    when = _period_words(rng, lang, start, end)
    template = rng.choice(fam.templates[lang])
    text = template.format(ref=ref, when=when)
    gold = Gold(_intent("PRICE_SUMMARY", lang, ticker=ticker, start=start, end=end))
    return _plain(text, lang, rng), gold, today, template


def _no_tool_question(fam, rng, lang, today_range):
    today = _iso(_random_day(rng, *today_range))
    template = rng.choice(fam.templates[lang])
    text = template.format(topic=rng.choice(fam.extra["topics"][lang]))
    return _plain(text, lang, rng), Gold(_intent("OUT_OF_SCOPE", lang)), today, template


def _missing_question(fam, rng, lang, today_range):
    today = _iso(_random_day(rng, *today_range))
    scenario = rng.choice(tuple(MISSING))
    start, end, when = _maybe_period(fam, rng, lang, today, chance=0.4)
    template = rng.choice(MISSING[scenario][lang])
    text = template.format(when=when)
    gold = Gold(_intent(scenario, lang, start=start, end=end))
    return _plain(text, lang, rng), gold, today, template


# --- paraphrases (TR: the period leads the sentence; EN: it trails) ----------------------
SECTOR = {
    "tr": (
        "{when}{ref} sektör ortalamasının gerisinde kaldı mı?",
        "{when}{ref} hissesi sektör arkadaşlarına göre nasıl performans gösterdi?",
        "{when}{ref} sektöründe geride mi kaldı?",
        "{when}{ref} hissesini sektörüyle karşılaştır.",
        "{when}{ref} sektorune gore nasil, geride kalmis mi?",
        "{when}{ref} sektorunun gerisinde mi, bi bakar misin?",
    ),
    "en": (
        "Has {ref} lagged its sector peers{when}?",
        "How did {ref} perform relative to its peer group{when}?",
        "Compare {ref} with its sector peers{when}.",
        "Was {ref} a laggard in its sector{when}?",
        "is {ref} behind the rest of its sector{when}?",
        "{ref} vs its sector{when}, is it trailing?",
    ),
}
CALENDAR = {
    "tr": (
        "{when}{ref} hissesinde haftanın günü etkisi var mı?",
        "{when}{ref} için en iyi getiri hangi gün?",
        "{when}{ref} hissesinde takvim etkisi var mı, mesela pazartesi zayıf mı?",
        "{when}{ref} icin hangi gun daha iyi getiri veriyor?",
        "{when}{ref} hissesinde aylık mevsimsellik var mı?",
        "{when}{ref} bazi gunler hep dusuyor mu?",
    ),
    "en": (
        "Does {ref} show a weekday effect{when}?",
        "Which weekday has been best for {ref}{when}?",
        "Is there a day-of-the-week pattern in {ref} returns{when}?",
        "any calendar effect in {ref}{when}, like Mondays being weak?",
        "Check {ref} for month-of-year seasonality{when}.",
        "do some weekdays work better for {ref}{when}?",
    ),
}
REVERSAL = {
    "tr": (
        "{when}{ref} aşırı satım bölgesine indikten sonra nasıl toparlandı?",
        "{when}{ref} alt banda değdiğinde ne oldu?",
        "{when}{ref} hissesinde dönüş sinyalleri işe yaradı mı?",
        "{when}{ref} dipten donuyor mu, RSI asiri satim olaylarina bak.",
        "{when}{ref} hissesi destekten döndü mü?",
        "{when}{ref} icin teknik donus sinyallerini incele.",
    ),
    "en": (
        "How did {ref} behave after oversold readings{when}?",
        "After {ref} touched its lower Bollinger band{when}, what happened next?",
        "Has {ref} bounced back after falling to support{when}?",
        "Do reversal signals on {ref} work{when}?",
        "Look at {ref} RSI oversold events{when}, did the price recover?",
        "did {ref} turn around from the bottom{when}?",
    ),
}
FUNDAMENTAL = {
    "tr": (
        "{when}{ref} bilançolarına nasıl tepki verdi?",
        "{when}{ref} hissesi bilanço açıklamalarından sonra nasıl hareket etti?",
        "{when}{ref} net kâr artışı fiyata yansıdı mı?",
        "{when}{ref} bilanco sonrasi ne yapti?",
        "{when}{ref} için bilanço ve fiyat tepkisini incele.",
        "{when}{ref} hissesinde finansal sonuçlara tepki var mı?",
    ),
    "en": (
        "How did {ref} react to its financial results{when}?",
        "Did the {ref} stock move after earnings announcements{when}?",
        "Is there a link between {ref} profit growth and its price{when}?",
        "{ref} price reaction to quarterly earnings{when}?",
        "what happened to {ref} shares after it published results{when}?",
        "Check how {ref} responded to its balance sheet news{when}.",
    ),
}
BACKTEST = {
    "tr": (
        "{when}{ref} için basit bir strateji backtest et.",
        "{when}{ref} üzerinde hareketli ortalama stratejisi nasıl çalışırdı?",
        "{when}{ref} icin geriye donuk test yap, al-tut'tan iyi mi?",
        "{when}{ref} hissesinde momentum stratejisini test et.",
        "{when}{ref} için backtest sonucu ne?",
        "{when}{ref} icin RSI stratejisini geriye donuk dene.",
    ),
    "en": (
        "Backtest a simple strategy on {ref}{when}.",
        "How would a moving average crossover strategy have done on {ref}{when}?",
        "Test a momentum strategy for {ref}{when} against buy and hold.",
        "Run a backtest of {ref}{when}, is the strategy better than holding?",
        "Did trading {ref} on RSI signals beat the market{when}?",
        "backtest {ref} trading rules{when}",
    ),
}
PRICE = {
    "tr": (
        "{when}{ref} nasıl hareket etti?",
        "{when}{ref} hissesinin fiyat özetini ver.",
        "{when}{ref} getirisi ne oldu?",
        "{when}{ref} nasil gitti, bi ozet gecer misin?",
        "{when}{ref} hissesi ne kadar kazandırdı?",
        "{when}{ref} fiyatı nasıl değişti?",
    ),
    "en": (
        "How did {ref} move{when}?",
        "Give me a price summary of {ref}{when}.",
        "What was the price performance of {ref}{when}?",
        "how's {ref} been doing{when}?",
        "Summarise the price action of {ref}{when}.",
        "What was the return on {ref}{when}?",
    ),
}
MACRO = {
    "tr": (
        "{when}Türkiye'de makro ortam nasıldı?",
        "{when}enflasyon ve faiz nasıldı?",
        "{when}BIST için makro bağlamı özetle.",
        "{when}dolar ve enflasyon ne durumdaydi?",
        "{when}ekonomide neler oldu, faiz, TÜFE, kur?",
        "{when}makro tablo nasıl, kısaca anlat.",
    ),
    "en": (
        "What was the macro backdrop for Turkish markets{when}?",
        "How did inflation and interest rates look{when}?",
        "Give me the macro context for BIST{when}.",
        "What was going on with the lira and inflation{when}?",
        "how was the economy doing{when}, rates, CPI, FX?",
        "Summarise macro conditions in Turkey{when}.",
    ),
}
NEWS = {
    "tr": (
        "{when}{ref} hakkında hangi haberler çıktı?",
        "{when}{ref} için KAP duyuruları neler?",
        "{when}{ref} ile ilgili önemli gelişmeler neler?",
        "{when}{ref} hakkinda ne haberler var?",
        "{when}{ref} şirketi ne açıkladı?",
        "{when}{ref} hissesinin haber akışını özetle.",
    ),
    "en": (
        "What news came out about {ref}{when}?",
        "Any KAP disclosures for {ref}{when}?",
        "What were the main headlines on {ref}{when}?",
        "Summarise the company announcements of {ref}{when}.",
        "anything important in the news for {ref}{when}?",
        "What did {ref} announce{when}?",
    ),
}
ADVICE = {
    "tr": (
        "{ref} alayım mı?",
        "{ref} hissesini almalı mıyım?",
        "{ref} alinir mi sence?",
        "{ref} satsam mı?",
        "{ref} hissesi iyi bir yatırım mı?",
        "{ref} icin yatirim tavsiyesi verir misin?",
    ),
    "en": (
        "Should I buy {ref}?",
        "Is {ref} a good investment right now?",
        "should i hold {ref} or sell it",
        "Would you sell {ref} here?",
        "Can I buy {ref} today?",
        "Give me investment advice on {ref}.",
    ),
}
PREDICTION = {
    "tr": (
        "{ref} yarın yükselir mi?",
        "{ref} hissesinin hedef fiyatı ne?",
        "{ref} fiyat tahmini yapar mısın?",
        "{ref} haftaya düşer mi?",
        "{ref} kac tl olur sence?",
        "{ref} hissesi nereye gidecek?",
    ),
    "en": (
        "Give me a price forecast for {ref}.",
        "What is the price target for {ref}?",
        "Predict the price of {ref} for next month.",
        "is {ref} going to go up tomorrow?",
        "Where is {ref} heading, any price prediction?",
        "{ref} price target for next year?",
    ),
}
GREETING = {
    "tr": (
        "Merhaba{topic}",
        "Selam, nasılsın{topic}",
        "Günaydın{topic}",
        "iyi aksamlar{topic}",
        "Selam{topic}",
        "Merhaba, kimsin sen{topic}",
    ),
    "en": (
        "Hello{topic}",
        "Hi there, how are you{topic}",
        "Good morning{topic}",
        "hey{topic}",
        "Good evening, who are you{topic}",
        "Hi{topic}",
    ),
}
GREETING_TAILS = ("!", ".", "?", " :)", "!!")
OFF_TOPIC = {
    "tr": (
        "{topic}",
        "Bana {topic} anlat.",
        "{topic} hakkında bilgi verir misin?",
        "bi sey sorabilir miyim, {topic}?",
        "Lütfen {topic} konusunda yardım et.",
        "{topic} nedir, kısaca açıkla.",
    ),
    "en": (
        "{topic}",
        "Tell me about {topic}.",
        "Can you give me information on {topic}?",
        "quick question, {topic}?",
        "Please help me with {topic}.",
        "What is {topic}, explain briefly.",
    ),
}
OFF_TOPICS = {
    "tr": (
        "İstanbul'da hava durumu",
        "pilav nasıl yapılır",
        "en iyi film önerileri",
        "Fransa'nın başkenti",
        "bir fıkra",
        "İngilizce öğrenme yolları",
        "futbol maçı sonuçları",
        "bir şiir yazma",
        "kediler neden mırlar",
        "tatil için güzel yerler",
    ),
    "en": (
        "the weather in Istanbul",
        "how to cook rice",
        "good movie recommendations",
        "the capital of France",
        "a joke",
        "ways to learn Spanish",
        "football match scores",
        "writing a poem",
        "why cats purr",
        "nice places for a holiday",
    ),
}
# Missing information: a question that names no stock, by the scenario it asks about.
MISSING = {
    "SECTOR_LAGGARD": {
        "tr": (
            "{when}hisse sektörünün gerisinde mi kaldı?",
            "{when}sektorune gore geride kaldi mi?",
        ),
        "en": ("Did the stock lag its sector{when}?", "is it behind its peers{when}?"),
    },
    "CALENDAR_PATTERN": {
        "tr": ("{when}haftanın günü etkisi var mı?", "{when}hangi gun daha iyi getiri veriyor?"),
        "en": ("Is there a weekday effect{when}?", "which weekday is best{when}?"),
    },
    "TECHNICAL_REVERSAL": {
        "tr": (
            "{when}aşırı satımdan dönüş sinyalleri işe yaradı mı?",
            "{when}dipten donus var mi?",
        ),
        "en": ("Did oversold reversal signals work{when}?", "any bounce from the bottom{when}?"),
    },
    "FUNDAMENTAL_REACTION": {
        "tr": ("{when}bilanço sonrası fiyat nasıl tepki verdi?", "{when}bilanco sonrasi ne oldu?"),
        "en": ("How did the price react to earnings{when}?", "what happened after results{when}?"),
    },
    "PRICE_SUMMARY": {
        "tr": ("{when}fiyat nasıl hareket etti?", "{when}nasil gitti bu hisse?"),
        "en": ("How did the price move{when}?", "how did it do{when}?"),
    },
}
MISSING_TEMPLATES = {lang: tuple(t for by in MISSING.values() for t in by[lang]) for lang in LANGS}


def _scenario(name: str, scenario: str, mode: str, templates: dict, dated, doc: str) -> Family:
    return Family(
        name, doc, templates, _scenario_question, scenario=scenario, mode=mode, dated=dated
    )


def _build() -> dict[str, Family]:
    topics = (
        ("sector_laggard", "SECTOR_LAGGARD", SECTOR, "stock lags its sector peers"),
        ("calendar_pattern", "CALENDAR_PATTERN", CALENDAR, "weekday or calendar effects"),
        ("technical_reversal", "TECHNICAL_REVERSAL", REVERSAL, "reversal events"),
        ("fundamental_reaction", "FUNDAMENTAL_REACTION", FUNDAMENTAL, "reaction to results"),
    )
    modes = (
        ("dated", "code", True, "period written in the question"),
        ("undated", "code", False, "no dates: the default period"),
        ("company", "company", None, "stock named by company name"),
        ("lowercase", "lower", None, "stock written as a lower-case code"),
    )
    fams: dict[str, Family] = {}
    for topic, scenario, templates, doc in topics:
        for suffix, mode, dated, mode_doc in modes:
            name = f"{topic}_{suffix}"
            fams[name] = _scenario(name, scenario, mode, templates, dated, f"{doc}; {mode_doc}")
    extra = (
        _scenario("backtest", "BACKTEST", "any", BACKTEST, None, "strategy backtest"),
        _scenario("price_summary", "PRICE_SUMMARY", "any", PRICE, None, "price summary"),
        Family("macro_context", "macro context", MACRO, _macro_question, scenario="MACRO_CONTEXT"),
        _scenario("news_context", "NEWS_CONTEXT", "any", NEWS, None, "company news"),
        Family(
            "price_summary_hold",
            "price summary, gold label HOLD",
            PRICE,
            _scenario_question,
            scenario="PRICE_SUMMARY",
            mode="any",
            action="HOLD",
        ),
        Family(
            "macro_context_hold",
            "macro context, gold label HOLD",
            MACRO,
            _macro_question,
            scenario="MACRO_CONTEXT",
            action="HOLD",
        ),
        Family(
            "advice_request",
            "asks whether to buy or sell",
            ADVICE,
            _guarded_question,
            scenario="ADVICE_REQUEST",
        ),
        Family(
            "prediction_request",
            "asks for a future price",
            PREDICTION,
            _guarded_question,
            scenario="PREDICTION_REQUEST",
        ),
        Family("out_of_universe", "stock outside the study universe", PRICE, _outside_question),
        Family("future_date", "period after today", PRICE, _future_question),
        Family(
            "no_tool_greeting",
            "greeting, no tool needed",
            GREETING,
            _no_tool_question,
            extra={"topics": {"tr": GREETING_TAILS, "en": GREETING_TAILS}},
        ),
        Family(
            "no_tool_off_topic",
            "out of scope, no tool needed",
            OFF_TOPIC,
            _no_tool_question,
            extra={"topics": OFF_TOPICS},
        ),
        Family("missing_information", "no stock named", MISSING_TEMPLATES, _missing_question),
    )
    fams.update((f.name, f) for f in extra)
    return fams


FAMILIES: dict[str, Family] = _build()


# --- generation and the overlap filter -------------------------------------------------
def generate(
    n_per_family: int,
    *,
    seed: int = 42,
    today_range: tuple[str, str] = TODAY_RANGE,
) -> list[GenQuestion]:
    """``n_per_family`` questions of every family, Turkish and English alternating.

    A question whose gold intent grounding would change is drawn again. A family's text
    repeats only when its paraphrases and parameters run out (the greeting family); the
    question ids stay unique.
    """
    if max(today_range) >= CUTOFF:
        raise ValueError("every date and today must be before 2025-01-01")
    rng = random.Random(seed)
    out: list[GenQuestion] = []
    for name, family in FAMILIES.items():
        seen: set[str] = set()
        for index in range(n_per_family):
            lang = LANGS[index % 2]
            for _ in range(50):
                text, gold, today, template = family.make(family, rng, lang, today_range)
                if not _grounded(gold, text):
                    continue  # e.g. an English company word tips the detected language
                if text not in seen:
                    break
            else:
                if not _grounded(gold, text):
                    raise ValueError(f"family {name} cannot ground its intent in {text!r}")
            seen.add(text)
            qid = f"{name}-{index:04d}"
            out.append(GenQuestion(qid, name, lang, text, gold, today, template))
    return out


def _grounded(gold: Gold, text: str) -> bool:
    """``ground_intent`` keeps the gold intent as it is (the question names all of it)."""
    intent = Intent(**gold.intent)
    return ground_intent(intent, text) == intent


def drop_overlaps(qs: list[GenQuestion]) -> tuple[list[GenQuestion], list[dict]]:
    """``(kept, dropped)``: drop what copies the frozen set or shares an expected triple.

    A dropped entry is ``{"question_id", "text", "reason", "frozen_id", "ratio"}`` with
    ``reason`` ``"text_overlap"`` (``eval.questions.overlaps``) or ``"expected_triple"``
    (the gold's non-null ticker, start and end equal a frozen question's expected ones).
    """
    pool = frozen.load_questions()
    triples = {
        (e["ticker"], e["start"], e["end"]): q["id"]
        for q in pool
        for e in (q["expected"],)
        if None not in (e["ticker"], e["start"], e["end"])
    }
    similar: dict[str, tuple[str, float]] = {}
    for text, qid, ratio in frozen.overlaps({q.text for q in qs}, questions=pool):
        if text not in similar or ratio > similar[text][1]:
            similar[text] = (qid, ratio)
    kept: list[GenQuestion] = []
    dropped: list[dict] = []
    for q in qs:
        i = q.gold.intent
        triple = (i["ticker"], i["start"], i["end"])
        if q.text in similar:
            qid, ratio = similar[q.text]
            reason = "text_overlap"
        elif None not in triple and triple in triples:
            qid, ratio, reason = triples[triple], None, "expected_triple"
        else:
            kept.append(q)
            continue
        dropped.append(
            {
                "question_id": q.question_id,
                "text": q.text,
                "reason": reason,
                "frozen_id": qid,
                "ratio": ratio,
            }
        )
    return kept, dropped
