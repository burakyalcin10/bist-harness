"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

The output validator and the finite action space of GENERATE_EXPLANATION (design spec
section 9, card EC-045). The model's explanation is checked in code before anyone sees it.

The model answers with schema-constrained JSON ``{"action": ..., "explanation": ...}``;
the schema already limits ``action`` to the eligible labels (``harness.actions``), and the
validator checks it again together with the text:

1. the action is one of the eligible labels;
2. the mandatory disclaimer line is there, in the answer's language;
3. when the period was defaulted, the fixed period note is there (and only then);
4. every sentence cites at least one evidence label, and every cited label exists and is
   committed;
5. every number and date is in the committed evidence (its values or its sentences) or in
   the question (rules K-008 and K-015 through ``eval.number_check``), and, sentence by
   sentence, in the items that sentence cites or in the question;
6. no investment-advice or prediction language (accent-insensitive);
7. no company name or ticker that the committed evidence does not mention.

``validate_explanation`` returns the problems in that order (empty = pass). A rejected
explanation is asked for again once, with the problems; on a second failure the answer is
only the committed evidence set under the label ``INVESTIGATE``.

Known limits: ticker detection knows the study universe and its peer groups (other
upper-case words such as RSI or MACD are not tickers); company names are matched from the
fixed list ``COMPANY_NAMES``. The disclaimer and the period note are fixed lines; they need
no citation and are not searched for advice words ("garanti" is part of the Turkish line).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from bist_harness.data import peers
from bist_harness.eval.number_check import (
    collect_numbers,
    extract_numbers,
    find_unsupported_dates,
    find_unsupported_numbers,
    numbers_match,
    question_numbers,
)
from bist_harness.harness import session
from bist_harness.harness.actions import eligible_actions
from bist_harness.harness.evidence import DISCLAIMER, LANGUAGES, Evidence
from bist_harness.harness.intent import (
    MOVE_AORIST_TR,
    MOVE_FUTURE_TR,
    MOVE_VERBS_EN,
    fold_text,
)

__all__ = [
    "DISCLAIMER",
    "FALLBACK_ACTION",
    "PERIOD_NOTE",
    "Explanation",
    "explanation_schema",
    "generate_explanation",
    "validate_explanation",
]

# DISCLAIMER (one definition, in harness.evidence):
#   en "Historical evidence only; no guarantee of future return."
#   tr "Yalnızca geçmiş veriye dayalı kanıt; gelecekteki getiri için garanti yoktur."
PERIOD_NOTE = {
    "tr": "Soruda dönem belirtilmediği için varsayılan analiz dönemi kullanıldı.",
    "en": "The question gave no period, so the default analysis period was used.",
}
FALLBACK_ACTION = "INVESTIGATE"
LANGUAGE_NAMES = {"tr": "Turkish", "en": "English"}
NOT_JSON = "the reply is not a JSON object with a string action and explanation"

# --- advice and prediction language ----------------------------------------------------
# Written folded (lower-case, no Turkish diacritics, punctuation as spaces); matched on
# whole words of the folded explanation. "yatirim tavsiyesi" alone is not here: "this is
# not investment advice" is not advice.
ADVICE_PHRASES = (
    # English
    "should buy",
    "should sell",
    "should hold",
    "should invest",
    "buy now",
    "sell now",
    "strong buy",
    "strong sell",
    "buy recommendation",
    "sell recommendation",
    "hold recommendation",
    "i recommend",
    "we recommend",
    "recommend buying",
    "recommend selling",
    "risk free",
    "will rise",
    "will fall",
    "will go up",
    "will go down",
    "will increase",
    "will decrease",
    "will drop",
    "will climb",
    "will recover",
    "is going to rise",
    "is going to fall",
    "sure to rise",
    "certain to rise",
    "price target",
    "target price",
    "time to buy",
    "time to sell",
    "worth buying",
    "must buy",
    # Turkish
    "al tavsiyesi",
    "sat tavsiyesi",
    "tut tavsiyesi",
    "alim tavsiyesi",
    "satis tavsiyesi",
    "tavsiye ederim",
    "tavsiye ediyorum",
    "tavsiye ederiz",
    "oneririm",
    "oneriyorum",
    "almalisiniz",
    "satmalisiniz",
    "tutmalisiniz",
    "almalisin",
    "satmalisin",
    "tutmalisin",
    "alinmali",
    "satilmali",
    "alim firsati",
    "kesin yukselir",
    "kesin duser",
    "kesinlikle yukselir",
    "kesinlikle duser",
    "kesin kazanc",
    "kesin getiri",
    "hedef fiyat",
    "risksiz",
)
# Suffix-tolerant patterns next to the phrases (fix round 1): Turkish stems take suffixes
# ("alınmalıdır", "artacaktır") and English advice comes hedged ("will likely rise"). The
# price-move vocabulary is shared with the question guard in ``harness.intent``.
_MOVES_EN = "|".join(
    (
        *MOVE_VERBS_EN,
        "recover",
        "rebound",
        "outperform",
        "underperform",
        "rally",
        "decline",
        "gain",
        "lose",
        "surge",
        "soar",
        "plunge",
        "crash",
        "grow",
        "double",
        "beat",
    )
)
# Future stems without their last letter, which is k or ğ (g when folded): "artaca[kg]".
_FUTURE_TR = "|".join(
    verb[:-1] for verb in (*MOVE_FUTURE_TR, "azalacak", "gerileyecek", "toparlanacak")
)
# Words that turn "alınmalı" / "tutulmalı" into an ordinary passive ("should be taken into
# account / kept in mind"); each is checked as the word right before the token.
IDIOM_WORDS_TR = ("dikkate", "onune", "onunde", "hesaba", "ele", "isleme", "altina", "akilda")
_NOT_AFTER_IDIOM = "".join(f"(?<! {word} )" for word in IDIOM_WORDS_TR)
ADVICE_PATTERNS = (
    # Turkish: "almalı", "alınmalıdır", "satılmalı", "tutulmalı", "tutmalısınız"; not the
    # idioms "dikkate / göz önüne / ele alınmalı", "akılda / göz önünde tutulmalı".
    _NOT_AFTER_IDIOM + r"(?:al(?:in)?|sat(?:il)?|tut(?:ul)?)mali[a-z]*",
    r"(?:al|sat|tut)abilirsiniz",
    r"(?:almaya|satmaya|tutmaya) deger[a-z]*",
    r"(?:al|sat|tut) (?:sinyal|tavsiye|firsat|onerisi)[a-z]*",  # "al sinyalidir"
    r"satin alin(?:iz)?|alin(?:iz)?|tutun(?:uz)?|satiniz|satin(?! al)",  # imperatives
    r"oner(?:iyor|ir|il(?:ir|mektedir))[a-z]*",  # "öneriyoruz", "öneririz", "önerilir"
    r"tavsiye ed[a-z]*",
    # "yatırım tavsiyesidir", but not "yatırım tavsiyesi değildir / vermez"
    r"yatirim tavsiye[a-z]*(?= )(?! (?:degil|niteligi|icermez|vermez|sunmaz|yoktur))",
    # "garanti", "garantilidir", but not the bank (Garanti BBVA, Garanti Bankası)
    r"garanti[a-z]*(?= )(?! bbva | bankasi )",
    r"(?:" + "|".join((*MOVE_AORIST_TR, "geriler")) + r")(?:dir|ler|lar)?",  # "yükselir"
    r"(?:" + _FUTURE_TR + r")[gk][a-z]*",  # "artacaktır", "yükseleceği"
    r"(?:yukselebil|dusebil|artabil|azalabil|gerileyebil)[a-z]*",  # "yükselebilir"
    r"(?:yukselme|dusme|artma|azalma|gerileme)(?:si|leri) "
    r"(?:bekleni[a-z]*|beklenir|muhtemel[a-z]*|olasi[a-z]*)",
    r"devam edece[gk][a-z]*",  # "yükselmeye devam edecek"
    # English
    r"will (?:(?:probably|likely|surely|definitely|certainly|most|still|not|continue to|"
    rf"keep) )*(?:{_MOVES_EN})",
    rf"(?:is|are) going to (?:{_MOVES_EN})",
    r"(?:expected|likely|set|poised|bound|sure|certain|projected|forecast|predicted|"
    rf"anticipated) to (?:{_MOVES_EN})",
    rf"(?:should|could|may|might|must|would) (?:(?:continue to|keep) )?(?:{_MOVES_EN})",
    r"(?:i|we|you) (?:would|could|might|must|can) (?:also )?(?:consider )?"
    r"(?:buy|sell|hold|invest|add|accumulat)[a-z]*",
    r"(?:suggest|advise|recommend|urge)[a-z]* (?:that )?(?:you )?(?:to )?"
    r"(?:buy|sell|hold|invest|accumulat|reduc)[a-z]*",
    r"consider (?:buying|selling|holding|adding|investing|accumulating)",
    r"(?:may|might|would) (?:want|wish|like) to (?:buy|sell|hold|invest|add)",
    r"(?:is|are|looks|seems)(?: like)? an? (?:buy|sell|hold)(?= )(?! (?:label|action))",
    # "guaranteed", "a guarantee of return", but not "no guarantee", "not guaranteed"
    r"(?<! no )(?<! not )(?<! any )(?<! t )(?<! cannot )(?<! without )guarantee[a-z]*",
)
_ADVICE = re.compile(
    "|".join(
        [f"(?<= )(?:{re.escape(p)})(?= )" for p in ADVICE_PHRASES]
        + [f"(?<= )(?:{p})(?= )" for p in ADVICE_PATTERNS]
    )
)
# A bare imperative at the start of a sentence: "Buy.", "Sell THYAO", "Hold it". "HOLD"
# in capitals is the action label and is left alone.
_IMPERATIVE = re.compile(
    r"^ (?:buy|sell)(?= )(?! and hold )"
    r"|^ hold (?:$|(?:it|now|on|onto|them|the|this|these|your|shares|positions?)(?= ))"
)

# --- companies -----------------------------------------------------------------------------
# Common names of the study universe and its main peers. A name counts as mentioned when
# its folded form appears as whole words; the first name is the one reported.
COMPANY_NAMES: dict[str, tuple[str, ...]] = {
    "ASELS": ("Aselsan",),
    "TUPRS": ("Tüpraş",),
    "BIMAS": ("BİM Birleşik Mağazalar", "BİM"),
    "THYAO": ("Türk Hava Yolları", "Turkish Airlines"),
    "AKBNK": ("Akbank",),
    "KCHOL": ("Koç Holding",),
    "EREGL": ("Ereğli Demir", "Erdemir"),
    "TCELL": ("Turkcell",),
    "CCOLA": ("Coca-Cola İçecek", "Coca-Cola"),
    "MGROS": ("Migros",),
    "SASA": ("SASA Polyester",),
    "TRALT": ("Koza Altın",),
    "FROTO": ("Ford Otosan", "Ford Otomotiv"),
    "ENKAI": ("Enka İnşaat", "Enka"),
    "PGSUS": ("Pegasus",),
    "MPARK": ("MLP Sağlık", "Medical Park"),
    "EKGYO": ("Emlak Konut",),
    "GUBRF": ("Gübre Fabrikaları", "Gübretaş"),
    "TURSG": ("Türkiye Sigorta",),
    "ENJSA": ("Enerjisa",),
    "TTKOM": ("Türk Telekom",),
    "OYAKC": ("Oyak Çimento",),
    "AKSEN": ("Aksa Enerji",),
    "ISMEN": ("İş Yatırım",),
    "ARCLK": ("Arçelik",),
    "ECILC": ("Eczacıbaşı İlaç", "Eczacıbaşı"),
    "MAVI": ("Mavi Giyim",),
    "PETKM": ("Petkim",),
    "TOASO": ("Tofaş",),
    "KRDMD": ("Kardemir",),
    "GARAN": ("Garanti BBVA", "Garanti Bankası"),
    "ISCTR": ("İş Bankası", "Isbank"),
    "YKBNK": ("Yapı Kredi",),
    "HALKB": ("Halkbank",),
    "VAKBN": ("Vakıfbank",),
    "SAHOL": ("Sabancı Holding",),
    "ULKER": ("Ülker",),
    "SOKM": ("Şok Marketler",),
    "TAVHL": ("TAV Havalimanları",),
    "AEFES": ("Anadolu Efes",),
    "VESTL": ("Vestel",),
    "TKFEN": ("Tekfen",),
    "AYGAZ": ("Aygaz",),
    "DOHOL": ("Doğan Holding",),
}
_TICKER_TOKEN = re.compile(r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü])[A-ZÇĞİÖŞÜ]{4,6}(?![A-Za-z0-9çğıöşü])")
_TICKER_FOLD = str.maketrans("ÇĞİÖŞÜ", "CGIOSU")

# --- citations and sentences -----------------------------------------------------------
_LABEL = re.compile(r"\bE(\d+)\b")
# A sentence ends at . ! ? followed by space, unless a citation follows ("... rose. [E1]")
# or the full stop closes an abbreviation such as "A.Ş." or "e.g.".
_SENTENCE_END = re.compile(r"(?<=[.!?])(?<!\.[^\W\d]\.)\s+(?!\s)(?![\[(]?E\d)")
# "... rose. [E1] The RSI ..." : a citation bracket followed by a new capitalised sentence.
_AFTER_CITATION = re.compile(r"(?<=\])\s+(?=[A-ZÇĞİÖŞÜ])")


@dataclass(frozen=True)
class Explanation:
    """The outcome of GENERATE_EXPLANATION: the label and the text shown to the user."""

    action: str
    text: str
    eligible: list[str] = field(default_factory=list)
    attempts: int = 0  # model turns used (0 when the model was not asked)
    fallback: bool = False  # True when the answer is the evidence set under INVESTIGATE
    problems: list[list[str]] = field(default_factory=list)  # one list per rejected reply


# --- the checks ------------------------------------------------------------------------------
def _fmt(number: float) -> str:
    return f"{number:f}".rstrip("0").rstrip(".")


def _strip_line(text: str, line: str) -> tuple[str, bool]:
    """Remove every occurrence of a fixed line; say whether it was there."""
    found = line in text
    return text.replace(line, "\n"), found


def _sentences(text: str) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        for part in _SENTENCE_END.split(line):
            for sentence in _AFTER_CITATION.split(part):
                sentence = sentence.strip()
                if any(ch.isalnum() for ch in sentence):
                    found.append(sentence)
    return found


def _citation_problems(text: str, evidence: Sequence[Evidence]) -> list[str]:
    labels = {e.label for e in evidence}
    committed = {e.label for e in evidence if e.committed}
    problems = [
        f"sentence {i} cites no evidence item: {sentence!r}"
        for i, sentence in enumerate(_sentences(text), 1)
        if not _LABEL.search(sentence)
    ]
    seen: set[str] = set()
    for match in _LABEL.finditer(text):
        label = match[0]
        if label in seen:
            continue
        seen.add(label)
        if label not in labels:
            problems.append(f"{label} is not an evidence item")
        elif label not in committed:
            problems.append(f"{label} is not in the committed evidence set")
    return problems


def _unsupported(
    text: str, items: Sequence[Evidence], question: str
) -> tuple[list[float], list[str]]:
    """Numbers and dates of ``text`` that neither the items (values or sentences) nor the
    question support."""
    values = [e.value for e in items]
    sentences = [e.sentence for e in items]
    allowed = [n for s in sentences for n in extract_numbers(s)] + question_numbers(question)
    numbers = find_unsupported_numbers(text, [{"values": collect_numbers(values)}], allowed=allowed)
    source = [{"values": [v for v in values if isinstance(v, str)], "sentences": sentences}]
    return numbers, find_unsupported_dates(text, source, question)


def _number_problems(text: str, committed: Sequence[Evidence], question: str) -> list[str]:
    """First against the whole committed set; then each number or date the set does support
    against the items its own sentence cites (spec section 13: the number and the field it
    comes from belong to the same sentence)."""
    numbers, dates = _unsupported(text, committed, question)
    problems = [
        f"number {_fmt(n)} is not in the committed evidence or the question" for n in numbers
    ]
    problems += [f"date {d} is not in the committed evidence or the question" for d in dates]
    by_label = {e.label: e for e in committed}
    for i, sentence in enumerate(_sentences(text), 1):
        cited = list(dict.fromkeys(m[0] for m in _LABEL.finditer(sentence)))
        if not cited:
            continue  # already reported as a sentence without a citation
        items = [by_label[label] for label in cited if label in by_label]
        own_numbers, own_dates = _unsupported(sentence, items, question)
        names = ", ".join(cited)
        problems += [
            f"sentence {i}: number {_fmt(n)} is not in the items it cites ({names}) or the question"
            for n in own_numbers
            if not any(numbers_match(n, m) for m in numbers)
        ]
        problems += [
            f"sentence {i}: date {d} is not in the items it cites ({names}) or the question"
            for d in own_dates
            if d not in dates
        ]
    return problems


def _advice_problems(text: str) -> list[str]:
    found: list[str] = []
    for match in _ADVICE.finditer(fold_text(text)):
        if match[0] not in found:
            found.append(match[0])
    for sentence in _sentences(text):
        if sentence.lstrip("-* ").startswith("HOLD"):
            continue  # the action label, not an imperative
        match = _IMPERATIVE.search(fold_text(_LABEL.sub(" ", sentence)))
        if match and match[0].strip() not in found:
            found.append(match[0].strip())
    return [f"advice or prediction language: {phrase!r}" for phrase in found]


def _known_tickers() -> set[str]:
    return set(peers.all_symbols()) | set(COMPANY_NAMES)


def _tickers_in(text: str) -> list[str]:
    known = _known_tickers()
    found: list[str] = []
    for match in _TICKER_TOKEN.finditer(text):
        ticker = match[0].translate(_TICKER_FOLD)
        if ticker in known and ticker not in found:
            found.append(ticker)
    return found


def _names_in(folded: str) -> list[tuple[int, str, str]]:
    """(position, ticker, reported name) of each company name in a folded text."""
    found = []
    for ticker, names in COMPANY_NAMES.items():
        for name in names:
            position = folded.find(fold_text(name))
            if position >= 0:
                found.append((position, ticker, names[0]))
                break
    return sorted(found)


def _company_problems(text: str, committed: Sequence[Evidence]) -> list[str]:
    source = " ".join(
        [e.sentence for e in committed]
        + [e.field for e in committed]
        + [e.value for e in committed if isinstance(e.value, str)]
    )
    allowed = set(_tickers_in(source)) | {t for _, t, _ in _names_in(fold_text(source))}
    found: list[tuple[int, str]] = []
    for match in _TICKER_TOKEN.finditer(text):
        ticker = match[0].translate(_TICKER_FOLD)
        if ticker in _known_tickers() and ticker not in allowed:
            found.append((match.start(), ticker))
    folded = fold_text(text)
    # Positions in the folded text are close to the original ones (one leading space).
    found += [(p, f"{name} ({t})") for p, t, name in _names_in(folded) if t not in allowed]
    reported: list[str] = []
    for _, name in sorted(found):
        if name not in reported:
            reported.append(name)
    return [f"company or ticker not in the evidence: {name}" for name in reported]


def validate_explanation(
    text: str,
    *,
    action: str,
    eligible: Sequence[str],
    evidence: Sequence[Evidence],
    question: str,
    language: str,
    defaulted_period: bool = False,
) -> list[str]:
    """Return the problems of an explanation, in a fixed order; an empty list means it passes.

    ``evidence`` is the final evidence of the analysis (all items); only the committed
    ones support a number, a date, a citation or a company. ``defaulted_period`` is
    ``Intent.defaulted_period``: the fixed period note must then be in the text.
    """
    language = language if language in LANGUAGES else "en"
    problems: list[str] = []
    if action not in eligible:
        problems.append(
            f"action {action!r} is not one of the eligible actions: {', '.join(eligible)}"
        )
    body, has_disclaimer = _strip_line(text, DISCLAIMER[language])
    if not has_disclaimer:
        problems.append(f"the disclaimer line is missing: {DISCLAIMER[language]!r}")
    body, has_note = _strip_line(body, PERIOD_NOTE[language])
    if defaulted_period and not has_note:
        problems.append(f"the default-period note is missing: {PERIOD_NOTE[language]!r}")
    if has_note and not defaulted_period:
        problems.append("the default-period note is present but the question gave a period")
    committed = [e for e in evidence if e.committed]
    problems += _citation_problems(body, evidence)
    problems += _number_problems(body, committed, question)
    problems += _advice_problems(body)
    problems += _company_problems(body, committed)
    return problems


# --- the model turn --------------------------------------------------------------------------
def explanation_schema(eligible: Sequence[str]) -> dict:
    """JSON schema of the reply; ``action`` is limited to the eligible labels."""
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(eligible)},
            "explanation": {"type": "string"},
        },
        "required": ["action", "explanation"],
    }


def _system_prompt(eligible: Sequence[str], language: str, defaulted_period: bool) -> str:
    lines = [
        "You write the explanation step of an educational BIST 100 analysis harness. "
        "You cannot call tools; you only explain the evidence listed by the user message.",
        'Answer with one JSON object: {"action": <label>, "explanation": <text>}.',
        "Rules:",
        f"1. action is exactly one of: {', '.join(eligible)}.",
        f"2. Write the explanation in {LANGUAGE_NAMES[language]}; labels and tool names stay "
        "in English.",
        "3. Use only the evidence items listed. End every sentence with the labels of the "
        "items it uses, for example [E1] or [E1, E2].",
        "4. Copy numbers and dates exactly as the evidence writes them. Write no other "
        "number or date: no rounding, no percentage-to-fraction conversion, no sums.",
        "5. Give no investment advice and no prediction: never tell anyone to buy, sell or "
        "hold, never promise or guarantee a return, never say a price will rise or fall.",
        "6. Name no company or ticker that the evidence does not name.",
    ]
    if defaulted_period:
        lines.append(f"7. Include this line exactly: {PERIOD_NOTE[language]}")
    lines.append(f"{len(lines) - 2}. End with this line exactly: {DISCLAIMER[language]}")
    return "\n".join(lines)


def _user_prompt(question: str, committed: Sequence[Evidence]) -> str:
    items = "\n".join(f"{e.label}: {e.sentence}" for e in committed)
    return f"Question: {question}\n\nEvidence:\n{items}"


def _parse(content: str) -> tuple[str, str] | None:
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    action, text = data.get("action"), data.get("explanation")
    if not isinstance(action, str) or not isinstance(text, str):
        return None
    return action, text


def fallback_answer(committed: Sequence[Evidence], language: str, defaulted_period: bool) -> str:
    """What is shown after a second rejection: the label, the evidence set, the fixed lines."""
    lines = [FALLBACK_ACTION, *(f"{e.label}: {e.sentence}" for e in committed)]
    if defaulted_period:
        lines.append(PERIOD_NOTE[language])
    lines.append(DISCLAIMER[language])
    return "\n".join(lines)


def generate_explanation(analysis, client, evidence, gate) -> Explanation:
    """GENERATE_EXPLANATION: the model picks a label from the eligible set and explains it.

    ``evidence`` is the final evidence built at RISK_GATE. The reply is checked; a rejected
    reply is asked for once more with its problems; a second rejection (or no committed
    evidence at all) yields the committed evidence set under ``INVESTIGATE``. A model
    server error is not caught here; the state machine records it as MODEL_UNAVAILABLE.
    """
    intent = analysis.intent or {}
    language = intent.get("language") if intent.get("language") in LANGUAGES else "en"
    defaulted = bool(intent.get("defaulted_period"))
    evidence = list(evidence or ())
    committed = [e for e in evidence if e.committed]
    eligible = list(eligible_actions(analysis, evidence, gate))
    fallback = Explanation(
        action=FALLBACK_ACTION,
        text=fallback_answer(committed, language, defaulted),
        eligible=eligible,
        fallback=True,
    )
    if not committed:  # nothing could be cited: no model turn
        return fallback

    messages = [
        {"role": "system", "content": _system_prompt(eligible, language, defaulted)},
        {"role": "user", "content": _user_prompt(analysis.question, committed)},
    ]
    problems: list[list[str]] = []
    for attempt in (1, 2):
        result = client.chat(
            messages,
            response_format=explanation_schema(eligible),
            temperature=session.TEMPERATURE,
            seed=session.SEED,
        )
        parsed = _parse(result.content)
        if parsed is None:
            found = [NOT_JSON]
        else:
            action, text = parsed
            found = validate_explanation(
                text,
                action=action,
                eligible=eligible,
                evidence=evidence,
                question=analysis.question,
                language=language,
                defaulted_period=defaulted,
            )
            if not found:
                return Explanation(action, text, eligible, attempt, False, problems)
        problems.append(found)
        messages = [
            *messages,
            {"role": "assistant", "content": result.content},
            {
                "role": "user",
                "content": "Rejected: " + "; ".join(found) + ". Answer again with the JSON "
                "object and fix every problem.",
            },
        ]
    return Explanation(fallback.action, fallback.text, eligible, len(problems), True, problems)
