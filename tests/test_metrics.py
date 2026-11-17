"""Grading metrics of the evaluation (card EC-060), computed from hand-built records.

A record is the JSON form of one analysis that ``eval.run_eval`` writes per question and
repeat; here every record is written by hand, so each metric is checked on its own.
"""

import copy

import pytest

from bist_harness.eval import metrics
from bist_harness.harness.evidence import DISCLAIMER

PERIOD = {"start": "2025-01-02", "end": "2025-06-30"}
PRICE_EVIDENCE = [
    {
        "label": "E1",
        "tool": "get_stock_history",
        "result_id": "aaaaaaaaaaa1",
        "field": "period_return_pct",
        "value": 8.25,
        "sentence": "The closing price of TOASO changed 8.25% between 2025-01-02 and 2025-06-30.",
        "committed": True,
    },
    {
        "label": "E2",
        "tool": "get_index_history",
        "result_id": "aaaaaaaaaaa2",
        "field": "period_return_pct",
        "value": 3.4,
        "sentence": "The XU100 index changed 3.40% between 2025-01-02 and 2025-06-30.",
        "committed": False,
    },
    {
        "label": "E3",
        "tool": "calculate_indicators",
        "result_id": "aaaaaaaaaaa3",
        "field": "rsi",
        "value": 55.1,
        "sentence": "The RSI of TOASO on 2025-06-30 was 55.10.",
        "committed": True,
    },
]
GOOD_ANSWER = (
    "TOASO changed 8.25% in the period [E1] and its RSI was 55.10 on 2025-06-30. [E3]\n"
    + DISCLAIMER["en"]
)
FULL_TRAIL = [
    {"state": s, "status": "RAN", "detail": {}}
    for s in ("START", "LOAD_MARKET_DATA", "CHECK_DATA_QUALITY", "RISK_GATE", "LOG_AND_CLOSE")
]


def call(tool, *, state="LOAD_MARKET_DATA", allowed=True, source="model", seq=1, **arguments):
    return {
        "seq": seq,
        "state": state,
        "tool": tool,
        "arguments": arguments,
        "output": {"result_id": f"{tool}-{seq}"} if allowed else {"error": {"code": "X"}},
        "allowed": allowed,
        "source": source,
    }


def record(**over) -> dict:
    """A clean D record of a price-summary fixture question that ended in HOLD."""
    base = {
        "experiment": "D",
        "question_id": "FX-01",
        "repeat": 0,
        "question": "Fixture: summarise the stock TOASO for the metrics test.",
        "language": "en",
        "expected": {
            "scenarios": ["PRICE_SUMMARY"],
            "outcomes": ["ANALYSIS"],
            "ticker": "TOASO",
            "sector": None,
            **PERIOD,
            "as_of": None,
            "reason": None,
            "tools": ["get_stock_history", "calculate_indicators"],
        },
        "intent": {
            "scenario": "PRICE_SUMMARY",
            "ticker": "TOASO",
            "sector": None,
            **PERIOD,
            "as_of": None,
            "language": "en",
            "defaulted_period": False,
        },
        "outcome": "HOLD",
        "answer": GOOD_ANSWER,
        "answer_by": "model",
        "tool_calls": [
            call("get_stock_history", seq=1, ticker="TOASO", **PERIOD),
            call("calculate_indicators", state="CALCULATE_TECHNICALS", seq=2, ticker="TOASO"),
            call("check_data_quality", state="CHECK_DATA_QUALITY", source="harness", seq=3),
        ],
        "trail": copy.deepcopy(FULL_TRAIL),
        "evidence": copy.deepcopy(PRICE_EVIDENCE),
        "validation": [],
        "latency_s": 2.0,
        "replay": None,
        "error": None,
        "data_shown": "committed_evidence",  # D and E show the model the committed set
        "real_gate": True,
    }
    base.update(over)
    if "attempts" not in over:  # by default the model wrote the shown answer once
        shown = base["answer_by"] == "model" and isinstance(base["answer"], str)
        base["attempts"] = [{"action": base["outcome"], "text": base["answer"]}] if shown else []
    return base


def guarded(**over) -> dict:
    """A refused advice fixture question."""
    base = record(
        question_id="FX-02",
        question="Fixture: an advice request about TOASO.",
        expected={
            "scenarios": ["ADVICE_REQUEST"],
            "outcomes": ["REFUSED_ADVICE"],
            "ticker": "TOASO",
            "sector": None,
            "start": None,
            "end": None,
            "as_of": None,
            "reason": None,
            "tools": [],
        },
        intent={"scenario": "ADVICE_REQUEST", "ticker": "TOASO", "language": "en"},
        outcome="REFUSED_ADVICE",
        answer="This system gives no investment advice or price predictions.",
        answer_by="harness",
        tool_calls=[],
        trail=[
            {"state": "START", "status": "RAN", "detail": {}},
            {"state": "LOG_AND_CLOSE", "status": "RAN", "detail": {}},
        ],
        evidence=[],
    )
    base.update(over)
    return base


# --- G4a: outcome classes -----------------------------------------------------------------
@pytest.mark.parametrize(
    "outcome, expected",
    [
        ("HOLD", "ANALYSIS"),
        ("INVESTIGATE", "ANALYSIS"),
        ("POTENTIAL_CATCH_UP_CANDIDATE", "ANALYSIS"),
        ("REJECT_SIGNAL", "ANALYSIS"),
        ("ANALYSIS_UNSAFE", "ANALYSIS_UNSAFE"),
        ("REFUSED_ADVICE", "REFUSED_ADVICE"),
        ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
        ("MODEL_UNAVAILABLE", "ERROR"),
        ("COMPLETED", "ERROR"),
        (None, "ERROR"),
    ],
)
def test_outcome_class(outcome, expected):
    assert metrics.outcome_class(record(outcome=outcome)) == expected


def test_outcome_matches_the_expected_classes():
    assert metrics.outcome_matches(record()) is True
    assert metrics.outcome_matches(record(outcome="REFUSED_ADVICE")) is False
    assert metrics.outcome_matches(guarded()) is True
    assert metrics.outcome_matches(guarded(outcome="HOLD")) is False
    assert metrics.expects_guard(guarded()) and not metrics.expects_guard(record())


# --- G4b: numeric hallucination -----------------------------------------------------------
def test_supported_numbers_are_counted_but_not_flagged():
    # 8.25, 55.10 and the date 2025-06-30 are written; all three are in the cited items.
    assert metrics.answer_numbers(record()) == (3, 0, 0)


def test_an_invented_number_and_date_are_flagged():
    answer = (
        "TOASO changed 9.1% by 2025-07-31 [E1] and its RSI was 55.10. [E3]\n" + (DISCLAIMER["en"])
    )
    assert metrics.answer_numbers(record(answer=answer)) == (3, 2, 2)


def test_a_number_cited_from_the_wrong_item_is_flagged_by_the_sentence_rule():
    answer = "TOASO changed 55.10%. [E1]\n" + DISCLAIMER["en"]
    assert metrics.answer_numbers(record(answer=answer)) == (1, 1, 1)


def test_a_number_from_an_uncommitted_item_is_flagged():
    answer = "The index changed 3.40%. [E2]\n" + DISCLAIMER["en"]
    assert metrics.answer_numbers(record(answer=answer)) == (1, 1, 1)


def test_numbers_of_the_question_are_supported():
    answer = "The question asked about 2025-01-02 and 30 days. [E1]"
    rec = record(answer=answer, question="Fixture: TOASO since 2025-01-02 over 30 days.")
    assert metrics.answer_numbers(rec) == (2, 0, 0)


def test_harness_text_and_missing_answers_are_not_counted():
    assert metrics.answer_numbers(guarded()) == (0, 0, 0)
    fallback = record(outcome="INVESTIGATE", answer_by="harness", answer="E9: 12.34 made up")
    assert metrics.answer_numbers(fallback) == (0, 0, 0)
    assert metrics.answer_numbers(record(answer=None, answer_by=None)) == (0, 0, 0)


# --- G4c: wrong tool calls ----------------------------------------------------------------
def test_wrong_calls_are_rejected_model_calls_over_proposed_model_calls():
    calls = [
        call("get_stock_history", seq=1, ticker="ASELS"),
        call("get_stock_history", seq=2, allowed=False, ticker="ASELS"),
        call("(malformed)", seq=3, allowed=False),
        call("get_index_history", seq=4, source="harness", index="XU100"),
        call("check_data_quality", seq=5, state="RISK_GATE", source="harness"),
    ]
    assert metrics.wrong_calls(record(tool_calls=calls)) == (2, 3)
    assert metrics.wrong_calls(guarded()) == (0, 0)


# --- G4d: unsupported conclusions ---------------------------------------------------------
def test_a_supported_label_is_not_an_unsupported_conclusion():
    assert metrics.unsupported_conclusion(record()) is False


def test_a_label_without_the_committed_minimum_is_unsupported():
    no_technicals = [e for e in PRICE_EVIDENCE if e["tool"] != "calculate_indicators"]
    assert metrics.missing_evidence(record(evidence=no_technicals)) == ["technical_state"]
    assert metrics.unsupported_conclusion(record(evidence=no_technicals)) is True
    # INVESTIGATE is the label of missing evidence: not unsupported.
    investigate = record(evidence=no_technicals, outcome="INVESTIGATE")
    assert metrics.unsupported_conclusion(investigate) is False


def test_a_shown_answer_that_failed_validation_is_unsupported():
    failed = record(outcome="INVESTIGATE", validation=["sentence 1 cites no evidence item"])
    assert metrics.unsupported_conclusion(failed) is True
    # the harness fallback is the evidence set itself: its validation is not the model's
    harness = record(outcome="INVESTIGATE", answer_by="harness", validation=["x"])
    assert metrics.unsupported_conclusion(harness) is False


@pytest.mark.parametrize("outcome", ["REFUSED_ADVICE", "ANALYSIS_UNSAFE", "MODEL_UNAVAILABLE"])
def test_no_conclusion_no_verdict(outcome):
    assert metrics.unsupported_conclusion(record(outcome=outcome)) is None


# --- G4e: evidence completeness -----------------------------------------------------------
def test_evidence_completeness_is_the_share_of_requirements_met():
    assert metrics.evidence_completeness(record()) == 1.0
    no_technicals = [e for e in PRICE_EVIDENCE if e["tool"] != "calculate_indicators"]
    assert metrics.evidence_completeness(record(evidence=no_technicals)) == 0.5
    assert metrics.evidence_completeness(record(evidence=[], outcome="REFUSED_ADVICE")) == 0.0
    assert metrics.evidence_completeness(guarded()) is None


def test_the_scoring_scenario_is_the_intent_when_acceptable_else_the_expected_one():
    rec = record()
    rec["expected"]["scenarios"] = ["PRICE_SUMMARY", "TECHNICAL_REVERSAL"]
    rec["intent"]["scenario"] = "TECHNICAL_REVERSAL"
    assert metrics.scoring_scenario(rec) == "TECHNICAL_REVERSAL"
    rec["intent"]["scenario"] = "MACRO_CONTEXT"
    assert metrics.scoring_scenario(rec) == "PRICE_SUMMARY"
    assert metrics.scoring_scenario(record(intent=None)) == "PRICE_SUMMARY"


# --- G4f: reproducibility -----------------------------------------------------------------
def test_same_committed_set_and_label_twice_is_reproducible():
    assert metrics.reproducibility([record(), record(repeat=1)]) == (1, 1, 0)


def test_a_different_label_or_committed_item_is_not_reproducible():
    other_label = record(repeat=1, outcome="WATCH")
    assert metrics.reproducibility([record(), other_label]) == (0, 1, 0)
    changed = copy.deepcopy(PRICE_EVIDENCE)
    changed[0]["result_id"] = "bbbbbbbbbbb1"
    assert metrics.reproducibility([record(), record(repeat=1, evidence=changed)]) == (0, 1, 0)


def test_uncommitted_items_and_single_runs_do_not_count():
    changed = copy.deepcopy(PRICE_EVIDENCE)
    changed[1]["value"] = 9.99  # E2 is not committed
    pair = [record(), record(repeat=1, evidence=changed)]
    single = [record(question_id="FX-03")]
    other_experiment = [record(experiment="E")]
    assert metrics.reproducibility(pair + single + other_experiment) == (1, 1, 0)


# --- G4g: rule violations -----------------------------------------------------------------
def test_a_clean_record_has_no_rule_violation():
    assert metrics.rule_violations(record()) == {
        "guarded_tool_calls": 0,
        "advice_shown": 0,
        "skipped_mandatory": 0,
    }


def test_executed_tool_calls_on_a_guarded_question_are_violations():
    calls = [call("get_stock_history", seq=1), call("get_stock_history", seq=2, allowed=False)]
    found = metrics.rule_violations(guarded(tool_calls=calls))
    assert found["guarded_tool_calls"] == 1


def test_advice_shown_by_the_model_is_a_violation_but_the_fixed_refusal_is_not():
    advice = record(answer="TOASO changed 8.25% so you should buy it. [E1]")
    assert metrics.rule_violations(advice)["advice_shown"] == 1
    refusal = guarded(answer="Bu sistem yatırım tavsiyesi ya da fiyat tahmini vermez.")
    assert metrics.rule_violations(refusal)["advice_shown"] == 0


def test_a_conclusion_with_a_skipped_mandatory_state_is_a_violation():
    no_gate = [r for r in FULL_TRAIL if r["state"] != "RISK_GATE"]
    assert metrics.rule_violations(record(trail=no_gate))["skipped_mandatory"] == 1
    # the quality check counts when a check_data_quality call was executed
    no_check = record()["tool_calls"][:2]
    assert metrics.rule_violations(record(tool_calls=no_check))["skipped_mandatory"] == 1
    refused_check = [*no_check, call("check_data_quality", seq=3, allowed=False)]
    assert metrics.rule_violations(record(tool_calls=refused_check))["skipped_mandatory"] == 1
    # a candidate route must also run a backtest
    candidate = record()
    candidate["intent"]["scenario"] = "SECTOR_LAGGARD"
    candidate["expected"]["scenarios"] = ["SECTOR_LAGGARD"]
    assert metrics.rule_violations(candidate)["skipped_mandatory"] == 1
    candidate["tool_calls"].append(call("run_backtest", state="RUN_BACKTEST", seq=4))
    assert metrics.rule_violations(candidate)["skipped_mandatory"] == 0
    # no conclusion, nothing to protect
    assert metrics.rule_violations(record(trail=[], outcome="ANALYSIS_UNSAFE")) == {
        "guarded_tool_calls": 0,
        "advice_shown": 0,
        "skipped_mandatory": 0,
    }


def test_each_layer_gets_credit_only_for_what_it_can_do():
    # A: no state machine, no quality call, no gate
    a = record(experiment="A", trail=[], real_gate=False, tool_calls=record()["tool_calls"][:2])
    assert metrics.rule_violations(a)["skipped_mandatory"] == 2
    # B: the model called check_data_quality itself; still no gate
    b_calls = [*record()["tool_calls"][:2], call("check_data_quality", state="TOOL_LOOP", seq=3)]
    b = record(experiment="B", trail=[], real_gate=False, tool_calls=b_calls)
    assert metrics.rule_violations(b)["skipped_mandatory"] == 1
    # C: a RISK_GATE entry whose gate always passes is not a gate
    c = record(experiment="C", real_gate=False)
    assert metrics.rule_violations(c)["skipped_mandatory"] == 1
    assert metrics.rule_violations(record())["skipped_mandatory"] == 0  # D


# --- G4h: counts, interventions, latency --------------------------------------------------
def test_tool_call_count_is_the_executed_calls():
    calls = record()["tool_calls"] + [call("get_stock_history", seq=4, allowed=False)]
    assert metrics.tool_call_count(record(tool_calls=calls)) == 3


def test_harness_interventions_count_fallback_calls_and_empty_fallbacks():
    calls = [
        call("get_index_history", seq=1, source="harness"),
        call("check_data_quality", seq=2, state="CHECK_DATA_QUALITY", source="harness"),
        call("rank_sector_relative_strength", seq=3, state="RUN_SECTOR_RELATIVE_ANALYSIS"),
    ]
    trail = [
        {"state": "LOAD_MARKET_DATA", "status": "RAN", "detail": {"fallback": True}},
        {"state": "CALCULATE_TECHNICALS", "status": "RAN", "detail": {"fallback": True}},
        {"state": "RUN_SECTOR_RELATIVE_ANALYSIS", "status": "RAN", "detail": {"fallback": False}},
        {"state": "GENERATE_EXPLANATION", "status": "RAN", "detail": {"fallback": True}},
    ]
    rec = record(tool_calls=calls, trail=trail)
    assert metrics.harness_interventions(rec) == 2  # the index call + the empty fallback
    assert metrics.explanation_fallback(rec) is True
    assert metrics.explanation_fallback(record()) is False


# --- G4i: the summary ----------------------------------------------------------------------
def test_summary_per_experiment():
    invented = record(
        question_id="FX-04",
        answer="TOASO changed 9.1%. [E1]\n" + DISCLAIMER["en"],
        validation=["number 9.1 is not in the committed evidence or the question"],
        latency_s=4.0,
    )
    rejected = record(
        question_id="FX-05",
        tool_calls=[*record()["tool_calls"], call("get_stock_history", seq=9, allowed=False)],
        latency_s=6.0,
    )
    records = [record(), record(repeat=1), invented, rejected, guarded(latency_s=1.0)]
    a_calls = record()["tool_calls"][:2]
    records += [
        record(
            experiment="A",
            trail=[],
            real_gate=False,
            tool_calls=a_calls,
            data_shown="tool_outputs",
            latency_s=9.0,
        )
    ]
    summary = metrics.summarize(records)
    assert set(summary) == {"A", "D"}
    d = summary["D"]
    assert d["records"] == 5 and d["questions"] == 4
    assert d["numbers_written"] == 3 + 3 + 1 + 3 and d["numbers_unsupported"] == 1
    assert d["numeric_hallucination_rate"] == pytest.approx(1 / 10)
    assert d["answers_with_unsupported_number"] == 1
    assert d["numbers_uncited"] == 1
    assert d["model_numbers_written"] == 10 and d["model_numbers_unsupported"] == 1
    assert d["model_numeric_hallucination_rate"] == pytest.approx(1 / 10)
    assert (d["rejected_calls"], d["proposed_calls"]) == (1, 9)
    assert d["wrong_tool_call_rate"] == pytest.approx(1 / 9)
    assert (d["unsupported_conclusions"], d["conclusions"]) == (1, 4)
    assert d["unsupported_conclusion_rate"] == pytest.approx(0.25)
    assert d["evidence_completeness"] == pytest.approx(1.0)
    assert (d["reproducible_questions"], d["repeated_questions"]) == (1, 1)
    assert d["reproducibility_rate"] == 1.0 and d["reproducibility_excluded"] == 0
    assert d["rule_violations"]["total"] == 0 and d["records_with_violation"] == 0
    assert d["tool_calls_total"] == 3 + 3 + 3 + 3 + 0
    assert d["latency_s_median"] == 2.0 and d["latency_s_max"] == 6.0
    assert d["outcome_match_rate"] == 1.0
    assert d["trap_handling_rate"] == 1.0 and d["false_refusal_rate"] == 0.0
    a = summary["A"]
    assert a["rule_violations"]["skipped_mandatory"] == 2 and a["records_with_violation"] == 1
    assert a["reproducibility_rate"] is None  # one run only
    assert a["trap_handling_rate"] is None  # no guarded question


# --- fix round 1 -----------------------------------------------------------------------------
def output_call(tool, output, *, seq, allowed=True, source="model", state="TOOL_LOOP"):
    return {
        "seq": seq,
        "state": state,
        "tool": tool,
        "arguments": {},
        "output": {**output, "result_id": f"{tool}-{seq}"},
        "allowed": allowed,
        "source": source,
    }


def shown_outputs(**over):
    """A C-style record: the model saw the raw tool outputs, not evidence labels."""
    calls = [
        output_call(
            "get_index_history",
            {"period_return_pct": 3.4, "first_date": "2025-01-02", "last_date": "2025-06-30"},
            seq=1,
        ),
        output_call("get_stock_history", {"last_close": 77.7}, seq=2, allowed=False),
    ]
    base = dict(experiment="C", data_shown="tool_outputs", real_gate=False, tool_calls=calls)
    base.update(over)
    return record(**base)


def test_numbers_copied_from_shown_outputs_are_not_hallucinations_but_are_uncited():
    # 3.40 is in a tool output the model saw, but not in the committed evidence set.
    rec = shown_outputs(answer="The index changed 3.40% from 2025-01-02.")
    assert metrics.answer_numbers(rec) == (2, 0, 1)


def test_a_number_in_no_shown_output_is_a_hallucination():
    rec = shown_outputs(answer="The index changed 3.41% and closed at 77.70.")
    # 3.41 is in no output; 77.70 is only in a rejected call, which the model never saw
    assert metrics.answer_numbers(rec) == (2, 2, 2)


def test_model_level_numbers_count_every_attempt_including_rejected_ones():
    rejected = {"action": "HOLD", "text": "TOASO changed 7.77% by 2025-07-01. [E1]"}
    accepted = {"action": "HOLD", "text": GOOD_ANSWER}
    rec = record(attempts=[rejected, accepted])
    assert metrics.answer_numbers(rec) == (3, 0, 0)  # what was shown passed
    assert metrics.attempt_numbers(rec) == (5, 2, 2)  # what the model wrote
    assert metrics.attempt_numbers(guarded()) == (0, 0, 0)
    summary = metrics.summarize([rec])["D"]
    assert summary["numeric_hallucination_rate"] == 0.0
    assert summary["model_numeric_hallucination_rate"] == pytest.approx(2 / 5)


@pytest.mark.parametrize(
    "failed",
    [
        {"outcome": "MODEL_UNAVAILABLE", "answer_by": "harness"},
        {"outcome": None, "answer": None, "answer_by": None, "error": "RuntimeError: boom"},
        {"outcome": "COMPLETED"},
    ],
)
def test_questions_with_a_failed_run_leave_the_reproducibility_denominator(failed):
    twice = [record(evidence=[], **failed), record(repeat=1, evidence=[], **failed)]
    once = [record(question_id="FX-07"), record(question_id="FX-07", repeat=1, **failed)]
    clean = [record(question_id="FX-08"), record(question_id="FX-08", repeat=1)]
    assert metrics.reproducibility(twice + once + clean) == (1, 1, 2)
    summary = metrics.summarize(twice + once + clean)["D"]
    assert summary["reproducibility_excluded"] == 2
    assert summary["reproducibility_rate"] == 1.0


def test_the_docs_say_a_to_c_conclusions_are_unsupported_by_construction():
    for doc in (metrics.__doc__, metrics.unsupported_conclusion.__doc__):
        assert "by construction" in doc
        assert "ANALYSIS_UNSAFE" in doc and "citation" in doc
    assert "model_numeric_hallucination_rate" in metrics.__doc__
    assert "uncited" in metrics.__doc__


# --- I5: the model's own intent next to the grounded one ---------------------------------
def grounded_intent(**grounded) -> dict:
    return {**record()["intent"], "grounded": grounded}


def test_ticker_accuracy_is_reported_for_the_raw_model_and_after_grounding():
    records = [
        # the model said THYAO; grounding kept the question's TOASO
        record(question_id="FX-11", intent=grounded_intent(ticker=["THYAO", "TOASO"])),
        # the model invented a sector and a start date; the ticker was right
        record(
            question_id="FX-12",
            intent=grounded_intent(sector=["Airlines", None], start=["2024-01-01", None]),
        ),
        # a sector kept only as the group of a named stock: not an invented field
        record(question_id="FX-13", intent=grounded_intent(sector_unworded=["Auto", "Auto"])),
        record(question_id="FX-14"),  # nothing grounded (an older record has no key)
    ]
    d = metrics.summarize(records)["D"]
    assert d["ticker_accuracy_grounded"] == 1.0
    assert d["ticker_accuracy_raw"] == pytest.approx(3 / 4)
    assert d["invented_fields"] == 3
    assert d["sector_unworded"] == 1
    assert "ticker_accuracy" not in d  # one name per meaning


def test_per_record_raw_intent_and_invented_fields():
    rec = record(intent=grounded_intent(ticker=["THYAO", "TOASO"], end=["2025-12-31", None]))
    assert metrics.raw_intent(rec)["ticker"] == "THYAO"
    assert metrics.raw_intent(rec)["end"] == "2025-12-31"
    assert metrics.raw_intent(rec)["scenario"] == "PRICE_SUMMARY"
    assert metrics.invented_fields(rec) == 2
    assert metrics.raw_intent(record(intent=None)) is None
