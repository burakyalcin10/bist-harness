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
   the question (rules K-008 and K-015 through ``eval.number_check``);
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
    question_numbers,
)
from bist_harness.harness import session
from bist_harness.harness.actions import eligible_actions
from bist_harness.harness.evidence import DISCLAIMER, LANGUAGES, Evidence
from bist_harness.harness.intent import fold_text

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
    "guaranteed",
    "guarantees",
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
    "yukselecek",
    "yukselecektir",
    "dusecek",
    "dusecektir",
    "artacak",
    "azalacak",
    "hedef fiyat",
    "risksiz",
)
# "garanti", "garantili", "garantilidir" ... but not the bank (Garanti BBVA, Garanti Bankasi).
_GUARANTEE_TR = re.compile(r"(?<= )garanti[a-z]*(?= )(?! bbva | bankasi )")
_ADVICE = re.compile(
    "(?<= )(?:" + "|".join(re.escape(p) for p in ADVICE_PHRASES) + ")(?= )|" + _GUARANTEE_TR.pattern
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


def _number_problems(text: str, committed: Sequence[Evidence], question: str) -> list[str]:
    values = [e.value for e in committed]
    sentences = [e.sentence for e in committed]
    allowed = [n for s in sentences for n in extract_numbers(s)] + question_numbers(question)
    problems = [
        f"number {_fmt(n)} is not in the committed evidence or the question"
        for n in find_unsupported_numbers(
            text, [{"values": collect_numbers(values)}], allowed=allowed
        )
    ]
    source = [{"values": [v for v in values if isinstance(v, str)], "sentences": sentences}]
    problems += [
        f"date {d} is not in the committed evidence or the question"
        for d in find_unsupported_dates(text, source, question)
    ]
    return problems


def _advice_problems(text: str) -> list[str]:
    found: list[str] = []
    for match in _ADVICE.finditer(fold_text(text)):
        if match[0] not in found:
            found.append(match[0])
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
