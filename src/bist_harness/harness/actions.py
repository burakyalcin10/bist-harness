"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

Which of the eight action labels the model may choose: a pure function of the analysis, the
final evidence and the gate (design spec sections 7 and 9). The model picks among these;
it never widens the set.

Table (checked in this order):

* gate HARD_BLOCK / ANALYSIS_UNSAFE: only ``ANALYSIS_UNSAFE``;
* a calendar pattern flagged ``NOT_SIGNIFICANT``: only ``REJECT_SIGNAL``;
* evidence missing or not committed: only ``INVESTIGATE``;
* otherwise ``HOLD``, ``WATCH`` and ``INVESTIGATE``, plus the scenario's candidate label
  when a backtest ran and it carries neither ``UNDERPERFORMS_BUY_AND_HOLD`` nor
  ``FEW_TRADES``.

``ANALYSIS_UNSAFE`` and ``REJECT_SIGNAL`` are never offered outside their own rows. The
result follows the order of ``ACTIONS``.
"""

from __future__ import annotations

from collections.abc import Sequence

from bist_harness.harness.evidence import committed_set, missing_requirements
from bist_harness.tools.schemas import ACTIONS

BLOCKING_STATUSES = ("HARD_BLOCK", "ANALYSIS_UNSAFE")
CANDIDATE_LABEL = {
    "SECTOR_LAGGARD": "POTENTIAL_CATCH_UP_CANDIDATE",
    "TECHNICAL_REVERSAL": "TECHNICAL_REVERSAL_CANDIDATE",
    "FUNDAMENTAL_REACTION": "FUNDAMENTAL_IMPROVEMENT_CANDIDATE",
}
CAPPING_FLAGS = ("UNDERPERFORMS_BUY_AND_HOLD", "FEW_TRADES")
BASE_LABELS = ("HOLD", "WATCH", "INVESTIGATE")


def _in_order(labels: set[str]) -> tuple[str, ...]:
    return tuple(label for label in ACTIONS if label in labels)


def _calls(analysis, tool: str) -> list[dict]:
    """Outputs of the allowed, error-free calls of a tool."""
    return [
        c.output
        for c in analysis.tool_calls
        if c.tool == tool and c.allowed and isinstance(c.output, dict) and "error" not in c.output
    ]


def _complete(evidence: Sequence, scenario: str) -> bool:
    """No requirement is missing and the whole committed set is flagged committed."""
    if missing_requirements(evidence, scenario):
        return False
    committed = {item.label for item in evidence if item.committed}
    return all(item.label in committed for item in committed_set(evidence, scenario))


def eligible_actions(analysis, evidence: Sequence, gate) -> tuple[str, ...]:
    if gate.status in BLOCKING_STATUSES:
        return ("ANALYSIS_UNSAFE",)
    scenario = (analysis.intent or {}).get("scenario")
    if scenario == "CALENDAR_PATTERN" and any(
        "NOT_SIGNIFICANT" in (out.get("interpretation_flags") or [])
        for out in _calls(analysis, "test_weekday_pattern")
    ):
        return ("REJECT_SIGNAL",)
    if not _complete(evidence, scenario):
        return ("INVESTIGATE",)
    labels = set(BASE_LABELS)
    candidate = CANDIDATE_LABEL.get(scenario)
    backtests = _calls(analysis, "run_backtest")
    capped = any(flag in CAPPING_FLAGS for out in backtests for flag in out.get("flags") or [])
    if candidate and backtests and not capped:
        labels.add(candidate)
    return _in_order(labels)
