"""Intent parsing for the harness START state.

The model turns a question into a schema-constrained JSON intent. Code then checks it
(universe, dates) and runs an independent keyword guard for investment advice and price
predictions: if either layer fires, no analysis starts.
"""

from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Protocol

from bist_harness.data import peers
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
    # Fields the model filled that the question does not name, as
    # {field: [model value, value kept]} (see ``ground_intent``), plus "sector_unworded"
    # when a sector was kept only as the group of a named stock. An audit record for the
    # evaluation (how often the model invents a field); left out of comparisons.
    grounded: dict[str, list[str | None]] = field(default_factory=dict, compare=False)


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
# Price-move vocabulary shared with the output validator (harness.validator), so the
# question guard and the explanation check do not drift apart.
MOVE_AORIST_TR = ("yukselir", "duser", "artar", "azalir")  # "yükselir", "düşer", ...
MOVE_FUTURE_TR = ("yukselecek", "dusecek", "artacak")
MOVE_VERBS_EN = (
    "go up",
    "go down",
    "rise",
    "fall",
    "drop",
    "increase",
    "decrease",
    "reach",
    "hit",
    "climb",
)

PREDICTION_PHRASES = (
    # Turkish
    *(f"{verb} mi" for verb in MOVE_AORIST_TR),
    *(f"{verb} mi" for verb in MOVE_FUTURE_TR),
    "yukseli beklen",
    "dusus beklen",
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
        rf"({'|'.join(MOVE_VERBS_EN)}) "
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
    return replace(intent, start=start, end=end, defaulted_period=True)


# --- grounding: the intent keeps only what the question names ----------------------------
# A small model fills fields the question does not hold: another stock, an invented
# sector, dates around its own idea of "now". The system prompt asks it not to; code
# enforces it here, before the default period and ``check_intent``.

# Upper-case ticker-like tokens of the raw question ("PGSUS'un" gives PGSUS).
_UPPER_TOKEN = re.compile(r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü])[A-ZÇĞİÖŞÜ]{4,6}(?![A-Za-z0-9çğıöşü])")
_UPPER_FOLD = str.maketrans("ÇĞİÖŞÜ", "CGIOSU")
# Code-like words of the raw question in any case ("thyao", "thyao'nun" gives thyao).
_ANY_TOKEN = re.compile(
    r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü])[A-Za-zÇĞİÖŞÜçğıöşü]{4,6}(?![A-Za-z0-9çğıöşü])"
)
# Stock codes that are also ordinary words ("mavi" is blue, "deva" a cure): they name the
# stock only when written upper-case.
_WORD_CODES = frozenset({"ALKIM", "DEVA", "GEDIK", "INFO", "MAVI", "ULKER"})

# Word starts (folded) by which a question names a peer group, Turkish and English. The
# group's own name parts count as well (see ``_sector_grounding``).
SECTOR_WORDS: dict[str, tuple[str, ...]] = {
    "Banking": ("bank", "lender"),
    "Defense / Vehicles": ("savunma", "defense", "defence"),
    "Energy / Petrochemicals": ("enerji", "energy", "petrokimya", "petrochem", "rafineri", "refin"),
    "Holding": ("holding",),
    "Food & Beverage": ("gida", "icecek", "food", "beverage", "drink"),
    "Retail": ("perakende", "retail"),
    "Airlines / Transport": ("havayol", "havacilik", "ulasim", "airline", "aviation", "transport"),
    "Steel": ("celik", "steel"),
    "Telecom": ("telekom", "telecom"),
    "Chemicals / Fertilizer": ("kimya", "gubre", "chemical", "fertili"),
    "Mining": ("maden", "mining", "gold"),
    "Automotive": ("otomotiv", "otomobil", "automotive", "automaker", "carmaker"),
    "Construction": ("insaat", "construction"),
    "Healthcare / Pharma": ("saglik", "ilac", "hastane", "health", "pharma", "hospital"),
    "Real Estate": ("gayrimenkul", "emlak", "real estate", "reit", "property"),
    "Insurance": ("sigorta", "insur"),
    "Electric Utilities": ("elektrik", "electric", "utilit"),
    "Cement": ("cimento", "cement"),
    "Brokerage": ("araci kurum", "brokerage", "broker"),
    "Durables": ("dayanikli", "beyaz esya", "durable", "appliance"),
}

# Month names, folded: Turkish, English and English short forms (fixed, not the locale's).
_MONTH_NAMES = (
    ("ocak", "january", "jan"),
    ("subat", "february", "feb"),
    ("mart", "march", "mar"),
    ("nisan", "april", "apr"),
    ("mayis", "may"),
    ("haziran", "june", "jun"),
    ("temmuz", "july", "jul"),
    ("agustos", "august", "aug"),
    ("eylul", "september", "sept", "sep"),
    ("ekim", "october", "oct"),
    ("kasim", "november", "nov"),
    ("aralik", "december", "dec"),
)
_MONTHS = {name: number for number, names in enumerate(_MONTH_NAMES, 1) for name in names}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
# Numeric dates on the raw question: 2025-03-31 (2025/03/31) and 31.03.2025 (31/03/2025).
_YMD = re.compile(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
_DMY = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)")
# Written dates on the folded question: "15 ağustos 2025", "june 30, 2025", "mart 2025".
_DAY_MONTH_YEAR = re.compile(rf"\b(\d{{1,2}}) ({_MONTH}) (\d{{4}})\b")
_MONTH_DAY_YEAR = re.compile(rf"\b({_MONTH}) (\d{{1,2}}) (\d{{4}})\b")
_MONTH_YEAR = re.compile(rf"\b({_MONTH}) (\d{{4}})\b")
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
# A range whose bounds share one year writes it once, at the end; a dash folds to a space.
# The first bound takes the year of the second: "3 mart ile 15 mayis 2025", "between march
# 3 and may 15 2025", "ocak mart 2025" (Ocak-Mart 2025), "30 eylul 31 aralik 2024".
_DAY_OR_MONTH = rf"(?:\d{{1,2}} (?:{_MONTH})|(?:{_MONTH})(?: \d{{1,2}})?)"
_SHARED_YEAR = re.compile(
    rf"\b({_DAY_OR_MONTH})(?= (?:(?:ile|ve|and|to) )?{_DAY_OR_MONTH} (\d{{4}})\b)"
)
# A bare first day takes the month and year as well: "1 15 mart 2025" (1-15 Mart 2025),
# "march 1 15 2025" (March 1-15, 2025).
_SHARED_MONTH_DM = re.compile(rf"\b(\d{{1,2}})(?= \d{{1,2}} ({_MONTH}) (\d{{4}})\b)")
_SHARED_MONTH_MD = re.compile(rf"\b({_MONTH}) (\d{{1,2}})(?= \d{{1,2}} (\d{{4}})\b)")
# A year the question names alone ("2023 yılı", "during 2024", "first half of 2025")
# grounds the bounds of its quarters and halves.
_YEAR_BOUNDS = ("01-01", "03-31", "04-01", "06-30", "07-01", "09-30", "10-01", "12-31")


def _iso(year: str, month: str | int, day: str | int) -> str:
    """ISO text of the parts, not checked: a malformed date stays for ``check_intent``."""
    return f"{year}-{int(month):02d}-{int(day):02d}"


def named_dates(question: str) -> set[str]:
    """The ISO dates a question names, in ISO, numeric or written Turkish/English form."""
    found: set[str] = set()

    def ymd(match: re.Match) -> str:
        found.update({match[0], _iso(match[1], match[2], match[3])})
        return " "

    def dmy(match: re.Match) -> str:
        found.add(_iso(match[3], match[2], match[1]))
        return " "

    text = _DMY.sub(dmy, _YMD.sub(ymd, question))
    folded = fold_text(text)
    folded = _SHARED_YEAR.sub(r"\1 \2", folded)
    folded = _SHARED_MONTH_DM.sub(r"\1 \2 \3", folded)
    folded = _SHARED_MONTH_MD.sub(r"\1 \2 \3 \1", folded)

    def day_month_year(match: re.Match) -> str:
        found.add(_iso(match[3], _MONTHS[match[2]], match[1]))
        return " "

    def month_day_year(match: re.Match) -> str:
        found.add(_iso(match[3], _MONTHS[match[1]], match[2]))
        return " "

    def month_year(match: re.Match) -> str:
        year, month = int(match[2]), _MONTHS[match[1]]
        last = calendar.monthrange(year, month)[1]
        found.update({_iso(match[2], month, 1), _iso(match[2], month, last)})
        return " "

    folded = _DAY_MONTH_YEAR.sub(day_month_year, folded)
    folded = _MONTH_DAY_YEAR.sub(month_day_year, folded)
    folded = _MONTH_YEAR.sub(month_year, folded)
    for year in _YEAR.findall(folded):
        found.update(f"{year}-{bound}" for bound in _YEAR_BOUNDS)
    return found


def _company_names() -> dict[str, tuple[str, ...]]:
    # Imported here: the validator imports this module.
    from bist_harness.harness.validator import COMPANY_NAMES

    return COMPANY_NAMES


def _names_company(folded: str, ticker: str) -> bool:
    names = _company_names().get(ticker, ())
    return any(f" {fold_text(name).strip()} " in folded for name in names)


def _upper_tokens(question: str) -> list[str]:
    return [m[0].translate(_UPPER_FOLD) for m in _UPPER_TOKEN.finditer(question)]


def _written_codes(question: str) -> set[str]:
    """The stock codes a question writes, in any case, with or without a suffix after an
    apostrophe ("THYAO", "THYAO'nun", "thyao", "thyao'nun"). A code that is also an
    ordinary word counts upper-case only ("Mavi bir gökyüzü" does not name MAVI)."""
    codes = set(_upper_tokens(question))
    for match in _ANY_TOKEN.finditer(question):
        code = fold_text(match[0]).strip().upper()
        if code not in _WORD_CODES:
            codes.add(code)
    return codes


def _names_ticker(codes: set[str], folded: str, ticker: str) -> bool:
    """The question names the stock: it writes its code (``_written_codes``) or one of its
    company names (any case). One rule, to keep the model's ticker and to replace it."""
    return ticker.translate(_UPPER_FOLD) in codes or _names_company(folded, ticker)


def _known_tickers() -> set[str]:
    return set(peers.all_symbols()) | set(load_universe()["ticker"]) | set(_company_names())


def _known_named(codes: set[str], folded: str) -> list[str]:
    """The universe and peer-group stocks the question names, by code or company name."""
    return [t for t in sorted(_known_tickers()) if _names_ticker(codes, folded, t)]


def _named_ticker(codes: set[str], folded: str) -> str | None:
    """The one known stock the question names, when it names exactly one; else None.

    Only stocks the project knows count: an unknown upper-case word ("OPEC", "XBANK",
    "AAPL") is never taken for a ticker.
    """
    named = _known_named(codes, folded)
    return named[0] if len(named) == 1 else None


def _group_of(ticker: str) -> str | None:
    try:
        return peers.peer_group_of(ticker).name
    except KeyError:
        return None


def _sector_stems(name: str) -> set[str]:
    """Folded parts of a sector name, a plural "s" dropped ("Airlines" gives "airline")."""
    stems = set()
    for part in re.split(r"[/&]", name):
        stem = fold_text(part).strip()
        if len(stem) > 4 and stem.endswith("s"):
            stem = stem[:-1]
        if len(stem) >= 4:
            stems.add(stem)
    return stems


def _sector_grounding(codes: set[str], folded: str, sector: str) -> str | None:
    """How the question grounds the sector, which must resolve to a peer group:
    "worded" when it words it (a word of the sector or of its group, or one of the group's
    Turkish/English words), "stock" when it only names a stock of that group ("TCELL ile
    TTKOM" means Telecom), None otherwise."""
    group = peers.sector_group(sector)
    if group is None:
        return None
    words = _sector_stems(sector) | _sector_stems(group) | set(SECTOR_WORDS.get(group, ()))
    if any(f" {word}" in folded for word in words):
        return "worded"
    if any(_group_of(t) == group for t in _known_named(codes, folded)):
        return "stock"
    return None


def ground_intent(intent: Intent, question: str) -> Intent:
    """Keep only the ticker, sector and dates the question names.

    - ticker: kept when the question names it (code or company name); otherwise the one
      known stock the question names, else None.
    - sector: kept when it resolves to a peer group and the question words it or names a
      stock of that group; else None.
    - start, end, as_of: kept when the question names that date; else None, so the default
      period is built from today.

    Every changed field is recorded in ``Intent.grounded`` as [model value, kept value]. A
    sector kept only through a named stock's group is recorded as "sector_unworded"
    [model value, model value]: kept, but not worded in the question.
    """
    folded = fold_text(question)
    codes = _written_codes(question)
    values: dict[str, str | None] = {}
    noted: dict[str, list[str | None]] = {}
    if intent.ticker is not None and not _names_ticker(codes, folded, intent.ticker):
        values["ticker"] = _named_ticker(codes, folded)
    if intent.sector is not None:
        how = _sector_grounding(codes, folded, intent.sector)
        if how is None:
            values["sector"] = None
        elif how == "stock":
            noted["sector_unworded"] = [intent.sector, intent.sector]
    dates = named_dates(question)
    for key in ("start", "end", "as_of"):
        value = getattr(intent, key)
        if value is not None and value not in dates:
            values[key] = None
    changed = {key: [getattr(intent, key), value] for key, value in values.items()} | noted
    if not changed:
        return intent
    return replace(intent, **values, grounded=changed)


# --- grounding of the reversal event family and direction -------------------------------
# Built from the event types ``detect_reversal_events`` supports (``REVERSAL_EVENT_TYPES``);
# MACD has no event type there, so a MACD question grounds nothing. Patterns run on the
# folded question (``fold_text``: lower-case, no Turkish diacritics, single spaces).
_LOWER_BAND = re.compile(r" (?:alt ban[dt]|lower (?:bollinger )?band)")
_UPPER_BAND = re.compile(r" (?:ust ban[dt]|upper (?:bollinger )?band)")
_MIDDLE_BAND = re.compile(r" (?:orta ban[dt]|middle (?:bollinger )?band)")
_OVERSOLD = re.compile(r" (?:asiri satim|oversold)")
_OVERBOUGHT = re.compile(r" (?:asiri alim|overbought)")
_SUPPORT = re.compile(r" (?:destek|support)")
_RESISTANCE = re.compile(r" (?:direnc|resistance)")
_BULLISH_WORDS = (
    _LOWER_BAND,
    _OVERSOLD,
    _SUPPORT,
    re.compile(r" (?:dip|dipten|dibe|dibinden|bottom|bottoms|bullish) "),
)
_BEARISH_WORDS = (
    _UPPER_BAND,
    _OVERBOUGHT,
    _RESISTANCE,
    re.compile(r" (?:tepe|tepeden|tepeye|top|tops|peak|peaks|bearish) "),
)
_FAMILY_WORDS = (
    (re.compile(r" supertrend"), ("SUPERTREND_FLIP",)),
    (re.compile(r" kama "), ("KAMA_TURN",)),
    (re.compile(r" (?:ichimoku|bulut|cloud)"), ("ICHIMOKU_BREAKOUT",)),
)


def reversal_grounding(question: str) -> tuple[tuple[str, ...] | None, str | None]:
    """The reversal event types and the direction the question names.

    Returns ``(event types, direction)``: the event types (in order of preference; the
    first is the canonical one) or ``None`` when the question names no event family, and
    ``"BULLISH"``, ``"BEARISH"`` or ``None`` (none or both named). A direction no named
    type can have (a one-sided family of the other side) is dropped, so the canonical call
    always fits. "alt bant" / "lower band" gives the lower-band touch and BULLISH.
    """
    from bist_harness.tools.events import SINGLE_DIRECTION

    folded = fold_text(question)
    bullish = any(p.search(folded) for p in _BULLISH_WORDS)
    bearish = any(p.search(folded) for p in _BEARISH_WORDS)
    direction = None if bullish == bearish else "BULLISH" if bullish else "BEARISH"
    types: list[str] = []
    bands = [
        (_LOWER_BAND, "BOLLINGER_LOWER_TOUCH"),
        (_MIDDLE_BAND, "BOLLINGER_MIDDLE_TEST"),
        (_UPPER_BAND, "BOLLINGER_UPPER_TOUCH"),
    ]
    types += [name for pattern, name in bands if pattern.search(folded)]
    if not types and " bollinger" in folded:
        types += [name for _, name in bands]
    if " rsi " in folded:
        if " 30 " in folded or _OVERSOLD.search(folded):
            types.append("RSI_LOCAL_TROUGH")
        elif " 70 " in folded or _OVERBOUGHT.search(folded):
            types.append("RSI_LOCAL_PEAK")
        else:
            types += ["RSI_LOCAL_TROUGH", "RSI_LOCAL_PEAK"]
    else:
        if _OVERSOLD.search(folded):
            types += ["RSI_LOCAL_TROUGH", "BOLLINGER_LOWER_TOUCH"]
        if _OVERBOUGHT.search(folded):
            types += ["RSI_LOCAL_PEAK", "BOLLINGER_UPPER_TOUCH"]
    types += [name for pattern, names in _FAMILY_WORDS if pattern.search(folded) for name in names]
    if _SUPPORT.search(folded) or _RESISTANCE.search(folded):
        types.append("SUPPORT_RESISTANCE_TOUCH")
    types = list(dict.fromkeys(types))
    if direction and types:
        fitting = [t for t in types if SINGLE_DIRECTION.get(t, direction) == direction]
        if fitting:
            types = fitting
        else:
            direction = None
    return (tuple(types) or None), direction


def _guess_language(question: str) -> str:
    return "tr" if re.search(r"[ıİşŞğĞüÜöÖçÇ]", question) or " mi " in fold_text(question) else "en"


def parse_intent(question: str, client: ChatClient, *, today: str, guard: bool = True) -> Intent:
    """Ask the model for a JSON intent, then ground it in the question and apply the
    code-side guard and defaults.

    A malformed answer is re-requested once; a second failure yields ``OUT_OF_SCOPE``.
    The model's fields are kept only where the question names them (``ground_intent``).
    The keyword guard runs regardless of the model's label. ``guard=False`` leaves the
    guard and the grounding out: the raw model intent of evaluation experiment A, which
    has no harness at all.
    """
    found = keyword_guard(question) if guard else None
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
    if intent is not None and guard:
        intent = ground_intent(intent, question)
    if intent is None:
        intent = Intent(
            scenario=found or "OUT_OF_SCOPE",
            ticker=None,
            sector=None,
            start=None,
            end=None,
            as_of=None,
            language=_guess_language(question),
        )
    if found is not None and intent.scenario not in ("ADVICE_REQUEST", "PREDICTION_REQUEST"):
        intent = Intent(
            scenario=found,
            ticker=intent.ticker,
            sector=None,
            start=None,
            end=None,
            as_of=None,
            language=intent.language,
            grounded=intent.grounded,
        )
    return _apply_default_period(intent, today)


# --- code-side checks ------------------------------------------------------------------
def _sector_known(sector: str) -> bool:
    """A sector name the state machine can resolve: a universe sector label, a peer-group
    name or one part of either (``peers.sector_group``, shared with the machine)."""
    return peers.sector_group(sector) is not None


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
    # A sector question needs a group: its stock's or a sector the question names.
    if intent.scenario == "SECTOR_LAGGARD" and intent.ticker is None and intent.sector is None:
        return "UNKNOWN_SECTOR"
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
