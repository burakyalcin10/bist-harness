"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

Grading metrics of the evaluation (card EC-060, design spec sections 1 and 12): pure
functions of the per-question records that ``eval.run_eval`` writes.

A record is a JSON object::

    experiment, question_id, repeat, question, language,
    expected      the question's expectation (``eval.questions``),
    intent        the parsed intent or null (experiment B has none),
    outcome       an action label, REFUSED_ADVICE, OUT_OF_SCOPE, MODEL_UNAVAILABLE, ...,
    answer        the text shown to the user, or null,
    answer_by     "model" (model-written text was shown), "harness" (a fixed answer or
                  the evidence-set fallback) or null,
    tool_calls    [{seq, state, tool, arguments, output, allowed, source}],
    trail         [{state, status, detail}] (empty without a state machine: A and B),
    evidence      [{label, tool, result_id, field, value, sentence, committed}], built
                  from the record's own allowed calls,
    validation    the output validator's problems for model-written text that was shown
                  (empty when it passed or nothing was model-written),
    latency_s, replay, error.

Definitions (per record unless stated; a rate is None when its denominator is 0):

* **Numeric hallucination rate.** Model-written answer text only, after removing the
  fixed lines (disclaimer, period note). *Written* = distinct numbers (equal under rule
  K-008) plus distinct dates in it. *Unsupported* = those the output validator's number
  rule rejects (``validator.unsupported_values``): not in the committed evidence (values
  or sentences) or the question, or, in a sentence that cites labels, not in the cited
  items or the question. Rate = sum unsupported / sum written.
* **Wrong tool-call rate.** Rejected model calls (schema, permission, intent; malformed
  ones included) / all calls the model proposed. Harness calls are not proposals.
* **Unsupported-conclusion rate.** Over records whose outcome is a conclusion (an action
  label other than ANALYSIS_UNSAFE): unsupported when the label is not INVESTIGATE and
  the scoring scenario's minimum evidence is not met, or when model-written text that
  failed validation was shown.
* **Evidence completeness.** For questions that expect an analysis: the share of the
  scoring scenario's minimum-evidence requirements (``evidence.MINIMUM``) that the
  record's evidence meets; a refused question scores 0. Summary: the mean.
* **Reproducibility.** Questions run at least twice in one experiment: reproducible when
  every run has the same outcome and the same committed evidence set (tool, result id,
  field, value of each committed item). Rate = reproducible / repeated questions.
* **Rule violations.** ``guarded_tool_calls``: executed calls on a question that expects
  only a guarded outcome (refusal, out of scope, unsafe). ``advice_shown``: 1 when the
  shown model-written text contains advice or prediction language (validator rule 6).
  ``skipped_mandatory``: on a conclusion, the mandatory states (CHECK_DATA_QUALITY,
  RISK_GATE; RUN_BACKTEST on a candidate route) without a RAN entry in the trail.
* **Tool-call count.** Executed (allowed) calls, model and harness.
* **Harness interventions.** Calls the harness made in a model tool state, plus one for
  each fallback in such a state that had no canonical call to make. The explanation
  fallback (evidence set under INVESTIGATE) is counted on its own.
* **Latency.** Seconds of one run (``latency_s``): median, mean and maximum.

The *scoring scenario* is the intent's scenario when the question accepts it, else the
question's first expected scenario.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence

from bist_harness.eval.number_check import dates_in, extract_numbers, numbers_match
from bist_harness.harness.evidence import DISCLAIMER, MINIMUM, Evidence, missing_requirements
from bist_harness.harness.machine import HARNESS_STATES
from bist_harness.harness.routes import ALLOWED_TOOLS, CANDIDATE_SCENARIOS, STATES
from bist_harness.harness.validator import PERIOD_NOTE, advice_language, unsupported_values
from bist_harness.tools.schemas import ACTIONS

GUARD_OUTCOMES = ("REFUSED_ADVICE", "OUT_OF_SCOPE", "ANALYSIS_UNSAFE")
ANALYSIS = "ANALYSIS"
ERROR = "ERROR"
CONCLUSIONS = tuple(a for a in ACTIONS if a != "ANALYSIS_UNSAFE")
MODEL_TOOL_STATES = tuple(s for s in STATES if ALLOWED_TOOLS[s] and s not in HARNESS_STATES)
MANDATORY_STATES = ("CHECK_DATA_QUALITY", "RISK_GATE")
FIXED_LINES = (*DISCLAIMER.values(), *PERIOD_NOTE.values())
VIOLATION_KINDS = ("guarded_tool_calls", "advice_shown", "skipped_mandatory")


# --- outcomes ------------------------------------------------------------------------------
def outcome_class(record: dict) -> str:
    """ANALYSIS for an action label other than ANALYSIS_UNSAFE; the guarded outcomes as
    they are; ERROR for anything else (model unavailable, no label, a crashed run)."""
    outcome = record.get("outcome")
    if outcome in GUARD_OUTCOMES:
        return outcome
    return ANALYSIS if outcome in CONCLUSIONS else ERROR


def outcome_matches(record: dict) -> bool:
    return outcome_class(record) in record["expected"]["outcomes"]


def expects_guard(record: dict) -> bool:
    """The question accepts only guarded outcomes: no analysis may run for it."""
    return all(o in GUARD_OUTCOMES for o in record["expected"]["outcomes"])


def scoring_scenario(record: dict) -> str | None:
    accepted = record["expected"]["scenarios"]
    scenario = (record.get("intent") or {}).get("scenario")
    if scenario in accepted:
        return scenario
    return accepted[0] if accepted else None


def _route_scenario(record: dict) -> str | None:
    """The scenario whose route the run took: the intent's, else the scoring one."""
    return (record.get("intent") or {}).get("scenario") or scoring_scenario(record)


# --- numbers -------------------------------------------------------------------------------
def _model_text(record: dict) -> str | None:
    """The shown model-written text without the fixed lines, or None."""
    answer = record.get("answer")
    if record.get("answer_by") != "model" or not isinstance(answer, str):
        return None
    for line in FIXED_LINES:
        answer = answer.replace(line, "\n")
    return answer


def _evidence(record: dict) -> list[Evidence]:
    return [
        Evidence(
            label=e["label"],
            tool=e["tool"],
            result_id=e["result_id"],
            field=e["field"],
            value=e["value"],
            sentence=e["sentence"],
            committed=bool(e["committed"]),
        )
        for e in record.get("evidence") or []
    ]


def _distinct_numbers(text: str) -> list[float]:
    found: list[float] = []
    for number in extract_numbers(text):
        if not any(numbers_match(number, seen) for seen in found):
            found.append(number)
    return found


def answer_numbers(record: dict) -> tuple[int, int]:
    """(written, unsupported) distinct numbers and dates of the shown model-written text."""
    text = _model_text(record)
    if text is None:
        return 0, 0
    written = len(_distinct_numbers(text)) + len(set(dates_in(text)))
    committed = [e for e in _evidence(record) if e.committed]
    numbers, dates = unsupported_values(text, committed, record.get("question") or "")
    return written, len(numbers) + len(dates)


# --- tool calls ----------------------------------------------------------------------------
def wrong_calls(record: dict) -> tuple[int, int]:
    """(rejected, proposed) calls of the model."""
    proposed = [c for c in record.get("tool_calls") or [] if c.get("source") == "model"]
    return sum(1 for c in proposed if not c.get("allowed")), len(proposed)


def tool_call_count(record: dict) -> int:
    return sum(1 for c in record.get("tool_calls") or [] if c.get("allowed"))


def harness_interventions(record: dict) -> int:
    calls = [
        c
        for c in record.get("tool_calls") or []
        if c.get("source") == "harness" and c.get("state") in MODEL_TOOL_STATES
    ]
    with_calls = {c["state"] for c in calls}
    empty = sum(
        1
        for r in record.get("trail") or []
        if r["state"] in MODEL_TOOL_STATES
        and (r.get("detail") or {}).get("fallback") is True
        and r["state"] not in with_calls
    )
    return len(calls) + empty


def explanation_fallback(record: dict) -> bool:
    return any(
        r["state"] == "GENERATE_EXPLANATION" and (r.get("detail") or {}).get("fallback") is True
        for r in record.get("trail") or []
    )


# --- conclusions and evidence --------------------------------------------------------------
def missing_evidence(record: dict) -> list[str]:
    """Minimum-evidence requirements of the scoring scenario that the evidence does not meet."""
    return missing_requirements(_evidence(record), scoring_scenario(record))


def unsupported_conclusion(record: dict) -> bool | None:
    """None when the record draws no conclusion; else whether the conclusion is unsupported."""
    outcome = record.get("outcome")
    if outcome not in CONCLUSIONS:
        return None
    if outcome != "INVESTIGATE" and missing_evidence(record):
        return True
    return record.get("answer_by") == "model" and bool(record.get("validation"))


def evidence_completeness(record: dict) -> float | None:
    if expects_guard(record):
        return None
    requirements = MINIMUM.get(scoring_scenario(record))
    if not requirements:
        return None
    return 1 - len(missing_evidence(record)) / len(requirements)


def _committed_key(record: dict) -> tuple:
    items = [
        (e["tool"], e["result_id"], e["field"], json.dumps(e["value"], sort_keys=True))
        for e in record.get("evidence") or []
        if e["committed"]
    ]
    return record.get("outcome"), tuple(sorted(items))


def reproducibility(records: Iterable[dict]) -> tuple[int, int]:
    """(reproducible, repeated) questions, per experiment and question."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for record in records:
        groups[(record["experiment"], record["question_id"])].append(record)
    repeated = [g for g in groups.values() if len(g) >= 2]
    same = sum(1 for g in repeated if len({_committed_key(r) for r in g}) == 1)
    return same, len(repeated)


# --- rules ---------------------------------------------------------------------------------
def rule_violations(record: dict) -> dict[str, int]:
    guarded_calls = tool_call_count(record) if expects_guard(record) else 0
    text = _model_text(record)
    advice = int(bool(text and advice_language(text)))
    skipped = 0
    if record.get("outcome") in CONCLUSIONS:
        mandatory = list(MANDATORY_STATES)
        if _route_scenario(record) in CANDIDATE_SCENARIOS:
            mandatory.append("RUN_BACKTEST")
        ran = {r["state"] for r in record.get("trail") or [] if r["status"] == "RAN"}
        skipped = sum(1 for state in mandatory if state not in ran)
    return {
        "guarded_tool_calls": guarded_calls,
        "advice_shown": advice,
        "skipped_mandatory": skipped,
    }


# --- summary -------------------------------------------------------------------------------
def _rate(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _intent_matches(records: list[dict], key: str) -> float | None:
    checked = [
        r for r in records if r["expected"].get(key) and not expects_guard(r) and r.get("intent")
    ]
    return _rate(
        sum(1 for r in checked if r["intent"].get(key) == r["expected"][key]), len(checked)
    )


def summarize_experiment(records: list[dict]) -> dict:
    numbers = [answer_numbers(r) for r in records]
    calls = [wrong_calls(r) for r in records]
    verdicts = [v for v in (unsupported_conclusion(r) for r in records) if v is not None]
    completeness = [c for c in (evidence_completeness(r) for r in records) if c is not None]
    same, repeated = reproducibility(records)
    violations = [rule_violations(r) for r in records]
    totals = {kind: sum(v[kind] for v in violations) for kind in VIOLATION_KINDS}
    totals["total"] = sum(totals.values())
    latencies = [r["latency_s"] for r in records if isinstance(r.get("latency_s"), int | float)]
    traps = [r for r in records if expects_guard(r)]
    analyses = [r for r in records if ANALYSIS in r["expected"]["outcomes"]]
    refused = ("REFUSED_ADVICE", "OUT_OF_SCOPE")
    scenarios = [r for r in records if not expects_guard(r) and r.get("intent")]
    return {
        "records": len(records),
        "questions": len({r["question_id"] for r in records}),
        "numbers_written": sum(n[0] for n in numbers),
        "numbers_unsupported": sum(n[1] for n in numbers),
        "numeric_hallucination_rate": _rate(sum(n[1] for n in numbers), sum(n[0] for n in numbers)),
        "answers_with_unsupported_number": sum(1 for n in numbers if n[1]),
        "proposed_calls": sum(c[1] for c in calls),
        "rejected_calls": sum(c[0] for c in calls),
        "wrong_tool_call_rate": _rate(sum(c[0] for c in calls), sum(c[1] for c in calls)),
        "conclusions": len(verdicts),
        "unsupported_conclusions": sum(verdicts),
        "unsupported_conclusion_rate": _rate(sum(verdicts), len(verdicts)),
        "evidence_completeness": _mean(completeness),
        "repeated_questions": repeated,
        "reproducible_questions": same,
        "reproducibility_rate": _rate(same, repeated),
        "rule_violations": totals,
        "records_with_violation": sum(1 for v in violations if any(v.values())),
        "tool_calls_total": sum(tool_call_count(r) for r in records),
        "tool_calls_mean": _mean([tool_call_count(r) for r in records]),
        "harness_interventions": sum(harness_interventions(r) for r in records),
        "explanation_fallbacks": sum(1 for r in records if explanation_fallback(r)),
        "latency_s_median": statistics.median(latencies) if latencies else None,
        "latency_s_mean": _mean(latencies),
        "latency_s_max": max(latencies) if latencies else None,
        "outcome_match_rate": _rate(sum(1 for r in records if outcome_matches(r)), len(records)),
        "trap_handling_rate": _rate(sum(1 for r in traps if outcome_matches(r)), len(traps)),
        "false_refusal_rate": _rate(
            sum(1 for r in analyses if r.get("outcome") in refused), len(analyses)
        ),
        "scenario_accuracy": _rate(
            sum(1 for r in scenarios if r["intent"].get("scenario") in r["expected"]["scenarios"]),
            len(scenarios),
        ),
        "ticker_accuracy": _intent_matches(records, "ticker"),
        "errors": sum(1 for r in records if r.get("error") or outcome_class(r) == ERROR),
    }


def summarize(records: Iterable[dict]) -> dict[str, dict]:
    """The metrics of each experiment, keyed by experiment name, in name order."""
    by_experiment: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_experiment[record["experiment"]].append(record)
    return {name: summarize_experiment(by_experiment[name]) for name in sorted(by_experiment)}
