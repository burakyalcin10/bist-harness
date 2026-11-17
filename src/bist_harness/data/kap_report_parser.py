"""Statement figures from a KAP financial-report page (K-055).

A KAP financial-report page renders the XBRL filing as HTML tables, one per statement
(balance sheet ``2xxxxx``, profit or loss ``3xxxxx``, other comprehensive income
``4xxxxx``, cash flows ``5xxxxx``, changes in equity ``6xxxxx``). Each row names its
taxonomy concept (``ifrs-full_Revenue``) and each value cell holds the raw number in a
``title`` attribute. The column headers carry the period ("Current Period 01.01.2024 -
30.09.2024" or a balance-sheet date), and a small table before each statement gives the
presentation unit and whether the report is consolidated. Bank balance sheets split each
period into Turkish-lira, foreign-currency and total columns.

Columns are identified by their dates, never by their position, because the number and
order of columns differ between reports (three-month columns, a third restated year).
The page also carries the same HTML a second time, escaped inside a script string; a
statement table is read once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_TABLE = re.compile(
    r'<table class="(financial-header-table|financial-table tbl_(\w+?_role_(\d+)))"'
)
_CELL = re.compile(r"<td([^>]*)>(.*?)</td>", re.S)
_EN = re.compile(r'content-en"[^>]*>(.*?)</div>', re.S)
_DATE = re.compile(r"(\d\d)\.(\d\d)\.(\d{4})")
_FIELD = re.compile(r'taxonomy-field-name"[^>]*>([^|<]*)\|')
_VALUE = re.compile(r'taxonomy-context-value col-order-class-(\d+)"[^>]*>(.*?)</td>', re.S)
_TITLE = re.compile(r'title="(-?[\d.]+)"')
_UNIT = re.compile(r"Sunum Para Birimi</td>\s*<td>([^<]*)</td>")
_NATURE = re.compile(r"Finansal Tablo Nitel[^<]*</td>\s*<td>([^<]*)</td>")
PARTS = ("TC", "FC", "Total")


@dataclass(frozen=True)
class Column:
    """One value column: a period (``start`` to ``end``) or a balance date (``start`` None)."""

    label: str
    start: date | None
    end: date
    part: str | None = None  # "TC", "FC" or "Total" in bank balance sheets


@dataclass(frozen=True)
class Fact:
    statement: str  # e.g. "general_role_310000"
    concept: str
    column: Column
    value: float  # in TRY


@dataclass(frozen=True)
class Report:
    unit: float
    consolidated: bool | None
    facts: tuple[Fact, ...]

    def value(self, concept: str, *, end: date, start: date | None = None) -> float | None:
        """The figure of a concept for a period (or, without ``start``, a balance date)."""
        for fact in self.facts:
            column = fact.column
            if (
                fact.concept == concept
                and column.end == end
                and column.start == start
                and column.part in (None, "Total")
            ):
                return fact.value
        return None


def _unescape(raw: str) -> str:
    return (
        raw.replace("\\u003c", "<")
        .replace("\\u003e", ">")
        .replace('\\"', '"')
        .replace("\\u0026", "&")
        .replace("\\r", "\r")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
    )


def _unit(text: str) -> float:
    digits = re.sub(r"[^\d]", "", text)
    return float(digits) if digits else 1.0


def _nature(text: str) -> bool | None:
    text = text.strip()
    if text.startswith("Konsolide Olmayan"):
        return False
    if text.startswith("Konsolide"):
        return True
    return None


def _en_text(body: str) -> str | None:
    match = _EN.search(body)
    return match.group(1).strip() if match else None


def _columns(header: str) -> list[Column]:
    periods: list[tuple[str, date | None, date, int]] = []
    parts: list[str] = []
    for attrs, body in _CELL.findall(header):
        text = _en_text(body)
        if text is None:
            continue
        found = [date(int(y), int(m), int(d)) for d, m, y in _DATE.findall(text)]
        if found:
            span = re.search(r'colspan="(\d+)"', attrs, re.I)
            label = re.split(r"<br\s*/?>", text)[0].strip()
            start, end = (found[0], found[-1]) if len(found) > 1 else (None, found[0])
            periods.append((label, start, end, int(span.group(1)) if span else 1))
        elif re.sub(r"<[^>]+>", "", text).strip() in PARTS:
            parts.append(re.sub(r"<[^>]+>", "", text).strip())
    columns: list[Column] = []
    width = sum(span for *_, span in periods)
    for label, start, end, span in periods:
        for _ in range(span):
            part = parts[len(columns)] if len(parts) == width and span > 1 else None
            columns.append(Column(label, start, end, part))
    return columns


def _number(cell: str) -> float | None:
    match = _TITLE.search(cell)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_report(raw: str) -> Report:
    """Every figure of the statements on a page, scaled to TRY."""
    text = _unescape(raw)
    marks = list(_TABLE.finditer(text))
    unit, consolidated = 1.0, None
    first_unit: float | None = None
    first_nature: bool | None = None
    seen: set[str] = set()
    facts: list[Fact] = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        block = text[mark.start() : end]
        if mark.group(1) == "financial-header-table":
            unit_match, nature_match = _UNIT.search(block), _NATURE.search(block)
            unit = _unit(unit_match.group(1)) if unit_match else 1.0
            consolidated = _nature(nature_match.group(1)) if nature_match else None
            if first_unit is None:
                first_unit, first_nature = unit, consolidated
            continue
        statement, role = mark.group(2), mark.group(3)
        if statement in seen:
            continue
        seen.add(statement)
        if role.startswith("6"):  # changes in equity: a matrix, not needed
            continue
        split = block.find('<td class="taxonomy-field-name-cell"')
        if split < 0:
            continue
        columns = _columns(block[:split])
        cells = _VALUE.findall(block)
        if not columns or not cells:
            continue
        base = min(int(order) for order, _ in cells)
        concepts: set[str] = set()
        for chunk in block[split:].split('<td class="taxonomy-field-name-cell"')[1:]:
            name = _FIELD.search(chunk)
            if not name or name.group(1) in concepts:
                continue
            concepts.add(name.group(1))
            for order, cell in _VALUE.findall(chunk):
                position = int(order) - base
                value = _number(cell)
                if value is None or not 0 <= position < len(columns):
                    continue
                facts.append(Fact(statement, name.group(1), columns[position], value * unit))
    if not seen:
        raise ValueError("The page has no financial statement table.")
    return Report(
        unit=first_unit if first_unit is not None else 1.0,
        consolidated=first_nature,
        facts=tuple(facts),
    )
