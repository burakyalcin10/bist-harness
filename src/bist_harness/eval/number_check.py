"""Numeric-hallucination check.

The model must not calculate or invent numbers. This module finds every number in an
answer and reports the ones that do not appear in any tool output (or in an explicit
allow-list such as the numbers of the user's own question).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_ISO_DATE = re.compile(r"\b(\d{4})-\d{2}-\d{2}\b")
# A number starts at a non-word boundary (so E12, qwen3.5 or hex ids are skipped), may
# carry a leading minus (ASCII or Unicode), and must not run into a letter.
_NUMBER = re.compile(r"(?<![\w.,])[-−]?\d[\d.,]*(?!\w)")
_THOUSANDS_COMMA = re.compile(r"^\d{1,3}(,\d{3})+$")
_THOUSANDS_DOT = re.compile(r"^\d{1,3}(\.\d{3})+$")


def _interpretations(token: str) -> list[float]:
    """Parse one numeric token; the first value is the preferred reading.

    English (1,234.56) and Turkish (1.234,56) formats are both accepted. A token such
    as ``1,234`` is ambiguous, so the second reading is returned as an alternative.
    """
    text = token.rstrip(".,").replace("−", "-")
    sign = -1.0 if text.startswith("-") else 1.0
    body = text.lstrip("-")
    if not body:
        return []

    def parse(s: str) -> float:
        return sign * float(s)

    has_dot, has_comma = "." in body, "," in body
    if has_dot and has_comma:
        if body.rfind(",") > body.rfind("."):  # 1.234,56
            return [parse(body.replace(".", "").replace(",", "."))]
        return [parse(body.replace(",", ""))]  # 1,234.56
    if has_comma:
        decimal = parse(body.replace(",", ".")) if body.count(",") == 1 else None
        if _THOUSANDS_COMMA.match(body):
            values = [parse(body.replace(",", ""))]
            return values + ([decimal] if decimal is not None else [])
        return [decimal] if decimal is not None else []
    if has_dot:
        if body.count(".") > 1:
            return [parse(body.replace(".", ""))] if _THOUSANDS_DOT.match(body) else []
        values = [parse(body)]
        if _THOUSANDS_DOT.match(body):
            values.append(parse(body.replace(".", "")))
        return values
    return [parse(body)]


def _tokens(text: str) -> list[str]:
    return _NUMBER.findall(_ISO_DATE.sub(" ", text))


def extract_numbers(text: str) -> list[float]:
    """Return the numbers written in ``text``, in order.

    ISO dates, identifiers that mix letters and digits (E1, result ids, model tags) and
    ticker symbols are not numbers.
    """
    return [values[0] for values in map(_interpretations, _tokens(text)) if values]


def numbers_match(claimed: float, source: float) -> bool:
    """Decide whether a number in an answer is the same as a number from a tool.

    Decision K-008: equal after rounding to two decimals. Tools already return values
    rounded to two decimals, so a faithful answer copies them exactly; converting a
    percentage to a fraction, rounding to an integer or flipping the sign is a mismatch.
    """
    return round(float(claimed), 2) == round(float(source), 2)


def collect_numbers(value: object) -> list[float]:
    """Collect every number found anywhere inside a tool output."""
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, int | float):
        return [float(value)]
    if isinstance(value, str):
        years = [float(year) for year in _ISO_DATE.findall(value)]
        return extract_numbers(value) + years
    if isinstance(value, dict):
        return [n for item in value.values() for n in collect_numbers(item)]
    if isinstance(value, list | tuple):
        return [n for item in value for n in collect_numbers(item)]
    return []


def find_unsupported_numbers(
    answer: str, tool_outputs: list[dict], *, allowed: Iterable[float] = ()
) -> list[float]:
    """Return the numbers in ``answer`` that no tool output and no allowed value supports."""
    supported = collect_numbers(tool_outputs) + [float(a) for a in allowed]
    unsupported: list[float] = []
    for token in _tokens(answer):
        readings = _interpretations(token)
        if not readings:
            continue
        if any(numbers_match(r, s) for r in readings for s in supported):
            continue
        if readings[0] not in unsupported:
            unsupported.append(readings[0])
    return unsupported
