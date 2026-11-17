"""Intent parsing for the harness START state.

The model turns a question into a schema-constrained JSON intent. Code then checks it
(universe, dates) and runs an independent keyword guard for investment advice and price
predictions: if either layer fires, no analysis starts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from bist_harness.universe import is_in_universe, load_universe, normalize_ticker

SCENARIOS = (
    "SECTOR_LAGGARD",
    "CALENDAR_PATTERN",
    "TECHNICAL_REVERSAL",
    "FUNDAMENTAL_REACTION",
    "PRICE_SUMMARY",
    "MACRO_CONTEXT",
    "NEWS_CONTEXT",
    "BACKTEST",
    "ADVICE_REQUEST",
    "PREDICTION_REQUEST",
    "OUT_OF_SCOPE",
)
GUARDED_SCENARIOS = ("ADVICE_REQUEST", "PREDICTION_REQUEST", "OUT_OF_SCOPE")
LANGUAGES = ("tr", "en")

# Default analysis window (calendar days before `end`) when the question gives no dates.
DEFAULT_PERIOD_DAYS = {
    "SECTOR_LAGGARD": 180,
    "CALENDAR_PATTERN": 730,
    "TECHNICAL_REVERSAL": 365,
    "FUNDAMENTAL_REACTION": 730,
    "PRICE_SUMMARY": 90,
    "MACRO_CONTEXT": 365,
    "NEWS_CONTEXT": 90,
    "BACKTEST": 730,
}

# Scenarios that need one named stock (the rest work on a sector, the index or a market view).
_NEEDS_TICKER = ("CALENDAR_PATTERN", "TECHNICAL_REVERSAL", "FUNDAMENTAL_REACTION", "PRICE_SUMMARY")

_NULLABLE_STR = {"type": ["string", "null"]}
INTENT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "scenario": {"type": "string", "enum": list(SCENARIOS)},
        "ticker": _NULLABLE_STR,
        "sector": _NULLABLE_STR,
        "start": _NULLABLE_STR,
        "end": _NULLABLE_STR,
        "as_of": _NULLABLE_STR,
        "language": {"type": "string", "enum": list(LANGUAGES)},
    },
    "required": ["scenario", "ticker", "sector", "start", "end", "as_of", "language"],
}

_SYSTEM_PROMPT = (
    "You turn one question about the BIST 100 stock universe into a JSON intent. "
    "Scenarios: SECTOR_LAGGARD (stock lags its sector peers), CALENDAR_PATTERN (weekday or "
    "calendar effects), TECHNICAL_REVERSAL (oversold/reversal events), FUNDAMENTAL_REACTION "
    "(price reaction to financial results), PRICE_SUMMARY (how a stock moved), MACRO_CONTEXT, "
    "NEWS_CONTEXT, BACKTEST (test a strategy), ADVICE_REQUEST (asks whether to buy, sell or "
    "hold), PREDICTION_REQUEST (asks for a future price or direction), OUT_OF_SCOPE (anything "
    "else). Use ISO dates (YYYY-MM-DD) only when the question states them, otherwise null. "
    "Tickers are upper-case BIST codes such as THYAO. language is tr or en. Answer with JSON only."
)


@dataclass(frozen=True)
class Intent:
    scenario: str
    ticker: str | None
    sector: str | None
    start: str | None
    end: str | None
    as_of: str | None
    language: str  # "tr" | "en"
    defaulted_period: bool = False  # True when start/end came from the scenario default


class ChatClient(Protocol):
    """The slice of ``OllamaClient`` that intent parsing needs."""

    def chat(self, messages: list[dict], tools: list[dict] | None = None, **kwargs): ...


# --- advice / prediction keyword guard -------------------------------------------------
# Phrases are written accent-free and lower-case; the question is folded the same way, so
# "alayım mı", "alayim mi" and "ALAYIM MI" all match. Matching is on whole words.
ADVICE_PHRASES = (
    # Turkish
    "alayim mi",
    "almali miyim",
    "almam mi",
    "alinir mi",
    "alinmali mi",
    "satayim mi",
    "satmali miyim",
    "satmam mi",
    "satilir mi",
    "satilmali mi",
    "alsam mi",
    "satsam mi",
    "eklesem mi",
    "almaliyim",
    "satmaliyim",
    "tutmaliyim",
    "tutayim mi",
    "tutmali miyim",
    "elimde tutmali",
    "pozisyon acayim",
    "yatirim tavsiyesi",
    "yatirim tavsiye",
    "tavsiye eder misin",
    "tavsiye verir misin",
    "ne yapmaliyim",
    "portfoyume eklemeli",
    "al mi sat mi",
    "alim firsati mi",
    "iyi bir yatirim mi",
    # English
    "should i buy",
    "should i sell",
    "should i hold",
    "should i invest",
    "shall i buy",
    "shall i sell",
    "buy or sell",
    "sell or hold",
    "worth buying",
    "good buy",
    "good investment",
    "investment advice",
    "financial advice",
    "can i buy",
    "can i sell",
    "would you buy",
    "would you sell",
    "wise to buy",
    "wise to sell",
    "good time to buy",
    "good time to sell",
    "recommend buying",
    "recommend selling",
    "add to my portfolio",
    "open a position",
)
PREDICTION_PHRASES = (
    # Turkish
    "yukselir mi",
    "yukselecek mi",
    "yukseli beklen",
    "duser mi",
    "dusecek mi",
    "dusus beklen",
    "artar mi",
    "artacak mi",
    "azalir mi",
    "hedef fiyat",
    "fiyat tahmini",
    "fiyat hedefi",
    "fiyati ne olur",
    "fiyati kac olur",
    "fiyati ne olacak",
    "fiyati kac olacak",
    "ne kadar olur",
    "ne kadar olacak",
    "kac tl olur",
    "kac tl olacak",
    "tavan yapar mi",
    "tavan olur mu",
    "yarin ne olur",
    "gelecek hafta ne olur",
    "gelecek ay ne olur",
    "gelecekte ne olur",
    "nereye gider",
    "nereye gidecek",
    "tahmin et",
    # English
    "will it rise",
    "will it fall",
    "will it go up",
    "will it go down",
    "will it drop",
    "will it increase",
    "will it reach",
    "price target",
    "price prediction",
    "predict the price",
    "forecast the price",
    "price forecast",
    "going to go up",
    "going to go down",
    "going to rise",
    "going to fall",
    "going up tomorrow",
    "next week price",
    "next month price",
)

# Patterns for wordings a fixed phrase cannot cover; they run on the folded text.
ADVICE_PATTERNS = (
    re.compile(r" (is|are) [a-z]{3,5} an? (buy|sell|hold) "),
    # "recommend a stock", "which stock would you recommend / should I pick"
    re.compile(r" recommend(ing)? (me )?(an? |any |some |the )?(stock|share|hisse)"),
    re.compile(r" (which|what) (stock|share)s? (would|should|do|can) (you|i) "),
    # "hisse onerir misin", "hangi hisseyi onerirsin", "hisse tavsiye eder misin"
    re.compile(r" hisse\w* (onerir|oneri|tavsiye)"),
)
PREDICTION_PATTERNS = (
    # "what will THYAO price be", "what will the price of AKBNK be"
    re.compile(r" what will (the )?(price of )?[a-z]{4,5} (price )?be "),
    re.compile(
        r" will (it|they|the stock|the price|the share|[a-z]{4,5}) "
        r"(go up|go down|rise|fall|drop|increase|decrease|reach|hit|climb) "
    ),
)

_FOLD = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iissgguuoocc")


def fold_text(text: str) -> str:
    """Lower-case, drop Turkish diacritics and collapse punctuation to single spaces."""
    t = text.translate(_FOLD).lower()
    t = re.sub(r"(?<=[a-z])-and-(?=[a-z])", "and", t)  # "buy-and-hold" stays one token
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return f" {t.strip()} "


def keyword_guard(question: str) -> str | None:
    """Return ``ADVICE_REQUEST`` or ``PREDICTION_REQUEST`` when a guarded phrase appears."""
    folded = fold_text(question)
    if any(f" {p} " in folded for p in ADVICE_PHRASES) or any(
        r.search(folded) for r in ADVICE_PATTERNS
    ):
        return "ADVICE_REQUEST"
    if any(f" {p} " in folded for p in PREDICTION_PHRASES) or any(
        r.search(folded) for r in PREDICTION_PATTERNS
    ):
        return "PREDICTION_REQUEST"
    return None


# --- parsing ---------------------------------------------------------------------------
def _valid_date(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _intent_from_payload(raw: str) -> Intent | None:
    """Validate the model's JSON; None when it does not fit the schema."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("scenario") not in SCENARIOS or data.get("language") not in LANGUAGES:
        return None
    fields: dict[str, str | None] = {}
    for key in ("ticker", "sector", "start", "end", "as_of"):
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            return None
        fields[key] = (value.strip() or None) if isinstance(value, str) else None
    if fields["ticker"] is not None:
        fields["ticker"] = normalize_ticker(fields["ticker"])
    return Intent(scenario=data["scenario"], language=data["language"], **fields)


def _apply_default_period(intent: Intent, today: str) -> Intent:
    days = DEFAULT_PERIOD_DAYS.get(intent.scenario)
    if days is None or (intent.start and intent.end):
        return intent
    # A malformed given date is left for check_intent to report.
    if (intent.start and not _valid_date(intent.start)) or (
        intent.end and not _valid_date(intent.end)
    ):
        return intent
    end = intent.end or (intent.as_of if intent.as_of and _valid_date(intent.as_of) else today)
    if intent.start:
        start = intent.start
    else:
        start = (date.fromisoformat(end) - timedelta(days=days)).isoformat()
    return Intent(
        scenario=intent.scenario,
        ticker=intent.ticker,
        sector=intent.sector,
        start=start,
        end=end,
        as_of=intent.as_of,
        language=intent.language,
        defaulted_period=True,
    )


def _guess_language(question: str) -> str:
    return "tr" if re.search(r"[ıİşŞğĞüÜöÖçÇ]", question) or " mi " in fold_text(question) else "en"


def parse_intent(question: str, client: ChatClient, *, today: str) -> Intent:
    """Ask the model for a JSON intent, then apply the code-side guard and defaults.

    A malformed answer is re-requested once; a second failure yields ``OUT_OF_SCOPE``.
    The keyword guard runs regardless of the model's label.
    """
    guard = keyword_guard(question)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    intent: Intent | None = None
    for attempt in range(2):
        result = client.chat(messages, response_format=INTENT_SCHEMA)
        intent = _intent_from_payload(result.content)
        if intent is not None:
            break
        if attempt == 0:
            messages = [
                *messages,
                {"role": "assistant", "content": result.content},
                {
                    "role": "user",
                    "content": "That was not valid. Answer again with only the JSON object.",
                },
            ]
    if intent is None:
        intent = Intent(
            scenario=guard or "OUT_OF_SCOPE",
            ticker=None,
            sector=None,
            start=None,
            end=None,
            as_of=None,
            language=_guess_language(question),
        )
    if guard is not None and intent.scenario not in ("ADVICE_REQUEST", "PREDICTION_REQUEST"):
        intent = Intent(
            scenario=guard,
            ticker=intent.ticker,
            sector=None,
            start=None,
            end=None,
            as_of=None,
            language=intent.language,
        )
    return _apply_default_period(intent, today)


# --- code-side checks ------------------------------------------------------------------
def _sector_known(sector: str) -> bool:
    wanted = sector.strip().casefold()
    for full in load_universe()["sector"].unique():
        parts = [full, *(p.strip() for p in full.split("/"))]
        if wanted in (p.casefold() for p in parts):
            return True
    return False


def check_intent(intent: Intent, *, today: str) -> str | None:
    """Return an error code for an unusable intent, or None when analysis may start.

    Guarded scenarios (advice, prediction, out of scope) are not errors here; the state
    machine answers them without starting an analysis.
    """
    if intent.scenario in GUARDED_SCENARIOS:
        return None
    if intent.ticker is not None and not is_in_universe(intent.ticker):
        return "UNKNOWN_TICKER"
    if intent.ticker is None and intent.scenario in _NEEDS_TICKER and intent.sector is None:
        return "MISSING_TICKER"
    if intent.sector is not None and not _sector_known(intent.sector):
        return "UNKNOWN_SECTOR"
    given = [d for d in (intent.start, intent.end, intent.as_of) if d is not None]
    if any(not _valid_date(d) for d in given):
        return "INVALID_DATE"
    if any(d > today for d in given):
        return "FUTURE_DATE"
    if intent.start and intent.end and intent.start > intent.end:
        return "INVALID_DATE_RANGE"
    return None
