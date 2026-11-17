"""Numeric-hallucination check.

The model must not calculate or invent numbers. This module finds every number and
date in an answer and reports the ones that do not come from a tool output (or from an
explicit allow-list such as the numbers of the user's own question).

Design rule: a missed invented number is worse than a false alarm. So

* a number counts wherever it stands (``TL62.5``, ``7x``, ``rate,97.3%``); only a few
  known identifier shapes are skipped,
* only *numeric fields* of a tool output support a number; digits inside its strings
  (definitions, error messages, dates) do not,
* dates are compared as whole dates against the dates of the tool outputs and the
  question.

Known limit: numbers written as words ("sixty", "altmış") are not detected.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
# Identifier shapes that are not quantities: index names, evidence ids, result ids.
_INDEX_NAME = re.compile(r"\bBIST\s?\d+\b|\bXU\d+\b", re.IGNORECASE)
_EVIDENCE_ID = re.compile(r"\bE\d+\b")
_RESULT_ID = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{12}\b")
_FRACTIONS = {"½": "0.5", "¼": "0.25", "¾": "0.75", "⅓": "0.33", "⅔": "0.67"}
_MINUS = "-−–‑"  # hyphen-minus, minus sign, en dash, non-breaking hyphen

_NUMBER = re.compile(
    rf"""
    (?P<sign>[{_MINUS}])?
    (?P<body>
        [1-9]\d{{0,2}}(?:,\d{{3}})+(?:\.\d+)?     # 1,234,567.89  (English grouping)
      | [1-9]\d{{0,2}}(?:\.\d{{3}})+(?:,\d+)?     # 1.234.567,89  (Turkish grouping)
      | \d+(?:[.,]\d+)?                           # 62.5 / 62,5 / 24
    )
    (?P<exp>[eE][+-]?\d+)?
    """,
    re.VERBOSE,
)
_EN_GROUPED = re.compile(r"^[1-9]\d{0,2}(,\d{3})+(\.\d+)?$")
_TR_GROUPED = re.compile(r"^[1-9]\d{0,2}(\.\d{3})+(,\d+)?$")


def _strip_non_quantities(text: str) -> str:
    for pattern in (_ISO_DATE, _DMY_DATE, _INDEX_NAME, _EVIDENCE_ID, _RESULT_ID):
        text = pattern.sub(" ", text)
    for char, value in _FRACTIONS.items():
        text = text.replace(char, f" {value} ")
    return text


def _to_float(body: str, exponent: str | None) -> float:
    if _EN_GROUPED.match(body):
        normal = body.replace(",", "")
    elif _TR_GROUPED.match(body):
        normal = body.replace(".", "").replace(",", ".")
    else:
        normal = body.replace(",", ".")
    return float(normal + (exponent or ""))


def extract_numbers(text: str) -> list[float]:
    """Return the numbers written in ``text``, in order.

    English (1,234.56) and Turkish (1.234,56) formats are both read; a three-digit group
    is always a thousands group, because tools never return three decimals. A leading
    minus counts only when it does not follow a letter or digit, so ``5-10`` and
    ``2020–2024`` are ranges. Dates, index names (BIST 100, XU100), evidence ids (E1)
    and result ids are not numbers.
    """
    cleaned = _strip_non_quantities(text)
    numbers: list[float] = []
    for match in _NUMBER.finditer(cleaned):
        value = _to_float(match["body"], match["exp"])
        if match["sign"]:
            before = cleaned[match.start() - 1] if match.start() else " "
            if not before.isalnum():
                value = -value
        numbers.append(value)
    return numbers


def numbers_match(claimed: float, source: float) -> bool:
    """Decide whether a number in an answer is the same as a number from a tool.

    Decision K-008: equal after rounding to two decimals. Tools already return values
    rounded to two decimals, so a faithful answer copies them exactly; converting a
    percentage to a fraction, rounding to an integer or flipping the sign is a mismatch.
    """
    return round(float(claimed), 2) == round(float(source), 2)


def collect_numbers(value: object) -> list[float]:
    """Collect the numeric fields of a tool output. Digits inside strings do not count."""
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, int | float):
        return [float(value)]
    if isinstance(value, dict):
        return [n for item in value.values() for n in collect_numbers(item)]
    if isinstance(value, list | tuple):
        return [n for item in value for n in collect_numbers(item)]
    return []


def question_numbers(question: str) -> list[float]:
    """Numbers the user wrote: quantities in the question plus the years of its dates."""
    years = [float(m[1]) for m in _ISO_DATE.finditer(question)]
    years += [float(m[3]) for m in _DMY_DATE.finditer(question)]
    return extract_numbers(question) + years


def find_unsupported_numbers(
    answer: str, tool_outputs: list[dict], *, allowed: Iterable[float] = ()
) -> list[float]:
    """Return the numbers in ``answer`` that no tool output and no allowed value supports."""
    supported = collect_numbers(tool_outputs) + [float(a) for a in allowed]
    unsupported: list[float] = []
    for number in extract_numbers(answer):
        if any(numbers_match(number, s) for s in supported):
            continue
        if number not in unsupported:
            unsupported.append(number)
    return unsupported


def _dates(text: str) -> list[str]:
    """Dates written in ``text`` as ISO strings, in order (ISO and dd.mm.yyyy forms)."""
    found = [(m.start(), m[0]) for m in _ISO_DATE.finditer(text)]
    found += [
        (m.start(), f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}") for m in _DMY_DATE.finditer(text)
    ]
    return [value for _, value in sorted(found)]


def find_unsupported_dates(answer: str, tool_outputs: list[dict], question: str = "") -> list[str]:
    """Return the dates in ``answer`` that appear neither in a tool output nor in the question."""
    known = set(_dates(json.dumps(tool_outputs, ensure_ascii=False, default=str)))
    known.update(_dates(question))
    unsupported: list[str] = []
    for value in _dates(answer):
        if value not in known and value not in unsupported:
            unsupported.append(value)
    return unsupported
