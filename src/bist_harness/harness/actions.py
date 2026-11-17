"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

Which of the eight action labels the model may choose: a pure function of the analysis, the
final evidence and the gate (design spec sections 7 and 9). The model picks among these;
it never widens the set.

Table (checked in this order):

* gate HARD_BLOCK / ANALYSIS_UNSAFE: only ``ANALYSIS_UNSAFE``;
* a calendar pattern flagged ``NOT_SIGNIFICANT``: only ``REJECT_SIGNAL``;
* evidence missing or not committed: only ``INVESTIGATE``;
* otherwise ``HOLD``, ``WATCH`` and ``INVESTIGATE``, plus the scenario's candidate label
  when a backtest ran, it carries neither ``UNDERPERFORMS_BUY_AND_HOLD`` nor
  ``FEW_TRADES``, and the committed evidence points the candidate's way
  (``_points_its_way``):

  - ``POTENTIAL_CATCH_UP_CANDIDATE``: the stock lags its sector. Every committed lag score
    of the analysis's stock is below 0 (for a question without a stock: at least one
    committed lag score is); the lag score is the stock's return minus the sector median
    (``tools.sector``), so a negative score means lagging. A return without a lag score is
    not lag evidence.
  - ``FUNDAMENTAL_IMPROVEMENT_CANDIDATE``: every committed ``fundamental_trend`` is
    ``Improving``; without a trend, every committed inflation-adjusted net profit change
    is above 0.
  - ``TECHNICAL_REVERSAL_CANDIDATE``: every committed success rate is above
    ``REVERSAL_SUCCESS_MIN_PCT`` (a majority of the events succeeded; success already
    follows the event's direction), and every committed average or median forward return
    has the sign of the event's direction (BULLISH above 0, BEARISH below 0).

``ANALYSIS_UNSAFE`` and ``REJECT_SIGNAL`` are never offered outside their own rows. The
result follows the order of ``ACTIONS``.
"""

from __future__ import annotations

import re
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
REVERSAL_SUCCESS_MIN_PCT = 50.0  # more successful events than failed ones
_LAG_FIELD = re.compile(r"^members\[(.+?)\]\.lag_score_pct$")


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


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _values(committed: Sequence, tool: str, field: str) -> list:
    return [item.value for item in committed if item.tool == tool and item.field == field]


def _catch_up(analysis, committed: Sequence) -> bool:
    ticker = (analysis.intent or {}).get("ticker")
    lags = []
    for item in committed:
        match = (
            _LAG_FIELD.match(item.field) if item.tool == "rank_sector_relative_strength" else None
        )
        if match and (ticker is None or match.group(1) == ticker):
            lags.append(_number(item.value))
    if not lags or None in lags:
        return False
    return all(lag < 0 for lag in lags) if ticker else any(lag < 0 for lag in lags)


def _improvement(committed: Sequence) -> bool:
    trends = _values(committed, "calculate_fundamental_change", "fundamental_trend")
    if trends:
        return all(trend == "Improving" for trend in trends)
    growth = [
        _number(v)
        for v in _values(committed, "calculate_fundamental_change", "net_profit_real_yoy_pct")
    ]
    return bool(growth) and all(g is not None and g > 0 for g in growth)


def _reversal(analysis, committed: Sequence) -> bool:
    directions = {
        out.get("result_id"): out.get("direction")
        for out in _calls(analysis, "detect_reversal_events")
    }
    items = [item for item in committed if item.tool == "detect_reversal_events"]
    rates = [_number(i.value) for i in items if i.field == "success_rate_pct"]
    if not rates or any(r is None or r <= REVERSAL_SUCCESS_MIN_PCT for r in rates):
        return False
    for item in items:
        if item.field in ("average_forward_return_pct", "median_forward_return_pct"):
            value = _number(item.value)
            sign = -1 if directions.get(item.result_id) == "BEARISH" else 1
            if value is None or value * sign <= 0:
                return False
    return True


def _points_its_way(analysis, evidence: Sequence, scenario: str) -> bool:
    """Does the committed evidence point the way of the scenario's candidate label?"""
    committed = [item for item in evidence if item.committed]
    if scenario == "SECTOR_LAGGARD":
        return _catch_up(analysis, committed)
    if scenario == "FUNDAMENTAL_REACTION":
        return _improvement(committed)
    if scenario == "TECHNICAL_REVERSAL":
        return _reversal(analysis, committed)
    return True


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
    if candidate and backtests and not capped and _points_its_way(analysis, evidence, scenario):
        labels.add(candidate)
    return _in_order(labels)
