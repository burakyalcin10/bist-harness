"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

The quality gate (design spec section 8): hard blocks and soft warnings, read from the
analysis alone. The decision is code; the model cannot change it.

Hard blocks: a symbol outside the study universe, a ``hard`` quality finding (or a quality
check with no status), a trade whose information date is after its signal date, a statement
known only after the ``as_of`` date, and empty data. Everything else that a tool warns
about is a soft warning.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from bist_harness.universe import is_in_universe, normalize_ticker

PASS = "PASS"
PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
HARD_BLOCK = "HARD_BLOCK"

SASA_VOLUME_WARNING = (
    "SASA has 155 days without volume data (Sprint 2 data check); volume-based features "
    "for SASA are unreliable."
)
_WARNING_FIELDS = ("sample_warning", "coverage_warning")
_WARNING_LISTS = ("warnings", "flags", "interpretation_flags")
_VOLUME_TOOLS = ("find_support_resistance", "detect_reversal_events")
_HISTORY_TOOLS = ("get_stock_history", "get_index_history")


@dataclass(frozen=True)
class GateResult:
    status: str  # PASS, PASS_WITH_WARNINGS or HARD_BLOCK
    hard_blocks: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _usable(analysis) -> list:
    """Allowed calls that returned an output without an error, in call order."""
    return [
        c
        for c in analysis.tool_calls
        if c.allowed and isinstance(c.output, dict) and "error" not in c.output
    ]


def _tickers_of(analysis, calls: Sequence) -> list[str]:
    """Every stock symbol the analysis worked with, in order, each once."""
    found: list[str] = []
    intent_ticker = (analysis.intent or {}).get("ticker")
    names = [intent_ticker] if isinstance(intent_ticker, str) else []
    for call in calls:
        arguments = call.arguments if isinstance(call.arguments, dict) else {}
        if isinstance(arguments.get("ticker"), str):
            names.append(arguments["ticker"])
        if isinstance(arguments.get("universe"), list):
            names.extend(t for t in arguments["universe"] if isinstance(t, str))
    for name in names:
        if name.strip() and name not in found:
            found.append(name)
    return found


def _quality_status(analysis) -> str | None:
    checks = [c for c in analysis.tool_calls if c.allowed and c.tool == "check_data_quality"]
    output = checks[-1].output if checks and isinstance(checks[-1].output, dict) else {}
    status = output.get("status")
    return status if isinstance(status, str) else None


def _quality_blocks(analysis) -> list[str]:
    checks = [c for c in analysis.tool_calls if c.allowed and c.tool == "check_data_quality"]
    if not checks:
        return ["no quality check was run"]
    output = checks[-1].output if isinstance(checks[-1].output, dict) else {}
    status = output.get("status")
    if not isinstance(status, str):
        error = output.get("error")
        code = error.get("code", "NO_STATUS") if isinstance(error, dict) else "NO_STATUS"
        return [f"the quality check gave no status: {code}"]
    blocks = []
    if status == HARD_BLOCK:
        blocks.append("the quality check reported HARD_BLOCK")
    for finding in output.get("findings") or []:
        if isinstance(finding, dict) and finding.get("severity") == "hard":
            blocks.append(f"quality finding {finding.get('code')}: {finding.get('message')}")
    for row in output.get("checked") or []:
        if isinstance(row, dict) and row.get("rows") == 0:
            blocks.append(f"empty data for {row.get('ticker')} to {row.get('as_of')}")
    return blocks


def _lookahead_blocks(calls: Sequence) -> list[str]:
    blocks = []
    for call in calls:
        output = call.output
        for key in ("trade_sample", "trades"):
            trades = output.get(key)
            for trade in trades if isinstance(trades, list) else []:
                if not isinstance(trade, dict):
                    continue
                info, signal = trade.get("info_date"), trade.get("signal_date")
                if isinstance(info, str) and isinstance(signal, str) and info > signal:
                    blocks.append(
                        f"{call.tool}: a trade used information of {info} for a signal on {signal}"
                    )
        as_of = output.get("as_of")
        if not isinstance(as_of, str):
            continue
        rows = [output] + [r for r in output.get("quarters") or [] if isinstance(r, dict)]
        for row in rows:
            known = row.get("known_from")
            if isinstance(known, str) and known > as_of:
                blocks.append(f"{call.tool}: a statement known from {known} is used as of {as_of}")
    return blocks


def _empty_data_blocks(calls: Sequence) -> list[str]:
    return [
        f"{call.tool}: no price rows were returned"
        for call in calls
        if call.tool in _HISTORY_TOOLS and call.output.get("rows") == 0
    ]


def _uses_volume(call) -> bool:
    if call.tool in _VOLUME_TOOLS:
        return True
    if call.tool != "calculate_indicators":
        return False
    groups = call.arguments.get("indicators") if isinstance(call.arguments, dict) else None
    return not groups or "VOLUME" in groups


def _warnings(analysis, calls: Sequence) -> list[str]:
    found: list[str] = []

    def add(text: Any) -> None:
        if isinstance(text, str) and text and text not in found:
            found.append(text)

    quality = [c for c in analysis.tool_calls if c.allowed and c.tool == "check_data_quality"]
    if quality and isinstance(quality[-1].output, dict):
        for finding in quality[-1].output.get("findings") or []:
            if isinstance(finding, dict) and finding.get("severity") != "hard":
                code, message = finding.get("code"), finding.get("message")
                add(message if code == "TOOL_WARNING" else f"{code}: {message}")
    for call in calls:
        if call.tool == "check_data_quality":
            continue
        for name in _WARNING_FIELDS:
            add(call.output.get(name))
        for name in _WARNING_LISTS:
            value = call.output.get(name)
            for text in value if isinstance(value, list) else []:
                add(text)
    names = {normalize_ticker(t) for t in _tickers_of(analysis, calls)}
    if "SASA" in names and any(_uses_volume(c) for c in calls):
        add(SASA_VOLUME_WARNING)
    return found


def quality_gate(analysis, evidence: Sequence = ()) -> GateResult:
    """Decide from the analysis alone; ``evidence`` is accepted for the gate hook's shape."""
    calls = _usable(analysis)
    blocks: list[str] = []
    for name in _tickers_of(analysis, calls):
        if not is_in_universe(name):
            blocks.append(f"{name} is not in the study universe")
    blocks += _quality_blocks(analysis)
    blocks += _lookahead_blocks(calls)
    blocks += _empty_data_blocks(calls)
    warnings = tuple(_warnings(analysis, calls))
    if blocks:
        return GateResult(HARD_BLOCK, tuple(blocks), warnings)
    warned = bool(warnings) or _quality_status(analysis) == PASS_WITH_WARNINGS
    return GateResult(PASS_WITH_WARNINGS if warned else PASS, (), warnings)
