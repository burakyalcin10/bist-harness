"""Scoring for the base-model bake-off: did the model pick the right tool and arguments?"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from bist_harness.llm.client import ToolCall
from bist_harness.universe import normalize_ticker

CASES_PATH = Path(__file__).with_name("cases.jsonl")


@dataclass(frozen=True)
class CaseScore:
    tool_ok: bool
    args_ok: bool
    no_tool_ok: bool | None  # None unless the case expects no tool call
    malformed: bool = False  # the reply attempted a tool call that could not be parsed


def load_cases(path: Path | None = None) -> list[dict]:
    lines = (path or CASES_PATH).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _canon(key: str, value: object) -> object:
    """Normalise a value so that harmless formatting differences do not count as errors."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, list | tuple):
        return frozenset(_canon(key, v) for v in value)
    if isinstance(value, str):
        text = value.strip()
        if key in ("ticker", "universe"):
            return normalize_ticker(text)
        try:
            return float(text)
        except ValueError:
            return text.upper()
    return value


def score_case(expected: dict, calls: Sequence[ToolCall], *, malformed: bool = False) -> CaseScore:
    """Score one case. Only the first tool call counts; extra arguments are tolerated.

    ``malformed`` marks a reply that tried to call a tool but could not be parsed. It
    never passes: on a no-tool case the model did attempt a call, and on a tool case
    there is no usable call.
    """
    if expected.get("expect") == "no_tool":
        passed = len(calls) == 0 and not malformed
        return CaseScore(tool_ok=False, args_ok=False, no_tool_ok=passed, malformed=malformed)
    if not calls:
        return CaseScore(False, False, None, malformed)
    call = calls[0]
    tool_ok = call.name == expected["tool"]
    args_ok = tool_ok and all(
        key in call.arguments and _canon(key, call.arguments[key]) == _canon(key, value)
        for key, value in expected.get("args", {}).items()
    )
    return CaseScore(tool_ok, args_ok, None, malformed)


def failed_case(expected: dict) -> CaseScore:
    """Score for a case whose request failed: a failure on every measure."""
    no_tool = False if expected.get("expect") == "no_tool" else None
    return CaseScore(tool_ok=False, args_ok=False, no_tool_ok=no_tool)


def _pct(hits: int, total: int) -> float | None:
    return round(100.0 * hits / total, 1) if total else None


def summarize(scores: Sequence[CaseScore]) -> dict:
    tool_cases = [s for s in scores if s.no_tool_ok is None]
    no_tool_cases = [s for s in scores if s.no_tool_ok is not None]
    return {
        "tool_ok_pct": _pct(sum(s.tool_ok for s in tool_cases), len(tool_cases)),
        "args_ok_pct": _pct(sum(s.args_ok for s in tool_cases), len(tool_cases)),
        "no_tool_ok_pct": _pct(sum(bool(s.no_tool_ok) for s in no_tool_cases), len(no_tool_cases)),
        "tool_cases": len(tool_cases),
        "no_tool_cases": len(no_tool_cases),
        "malformed_calls": sum(s.malformed for s in scores),
    }
