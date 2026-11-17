"""The reversal event family and direction are grounded in the question (I3).

A ``detect_reversal_events`` call whose ``event_type`` or ``direction`` contradicts what the
question names is rejected as INTENT_MISMATCH, so the model can retry; the canonical
fallback uses the grounded values. A question that names no event family allows any type.
"""

from __future__ import annotations

import pytest

from bist_harness.eval.metrics import wrong_calls
from bist_harness.eval.questions import load_questions
from bist_harness.harness import machine
from bist_harness.harness.intent import reversal_grounding
from bist_harness.tools.schemas import REVERSAL_EVENT_TYPES

from .test_machine import FakeTools, ScriptedClient, call, intent

STATE = "RUN_PATTERN_AND_REVERSAL_ANALYSIS"
TODAY = "2026-11-17"
PERIOD = {"start": "2025-01-02", "end": "2025-06-30"}


def question(qid: str) -> str:
    return next(q["question"] for q in load_questions() if q["id"] == qid)


def reversal_intent(ticker: str) -> machine.Intent:
    return machine.Intent("TECHNICAL_REVERSAL", ticker, None, **PERIOD, as_of=None, language="tr")


def check(qid: str, ticker: str, **arguments):
    return machine.check_call(
        STATE,
        "detect_reversal_events",
        {"ticker": ticker, **PERIOD, **arguments},
        reversal_intent(ticker),
        analysis_id="AN-1",
        question=question(qid),
    )


# TR-01: the lower Bollinger band, then a recovery (Turkish); TR-11: the same in English.
@pytest.mark.parametrize("qid", ["TR-01", "TR-11"])
def test_the_lower_band_question_grounds_the_lower_touch_and_bullish(qid):
    assert reversal_grounding(question(qid)) == (("BOLLINGER_LOWER_TOUCH",), "BULLISH")


@pytest.mark.parametrize(("qid", "ticker"), [("TR-01", "THYAO"), ("TR-11", "MGROS")])
def test_an_upper_band_call_on_a_lower_band_question_is_rejected(qid, ticker):
    problem = check(qid, ticker, event_type="BOLLINGER_UPPER_TOUCH", direction="BEARISH")
    assert problem is not None and problem[0] == "INTENT_MISMATCH"
    assert "BOLLINGER_LOWER_TOUCH" in problem[1]
    assert check(qid, ticker, event_type="BOLLINGER_LOWER_TOUCH") is None


@pytest.mark.parametrize(
    ("text", "types", "direction"),
    [
        ("Did it rebound after touching the upper band?", ("BOLLINGER_UPPER_TOUCH",), "BEARISH"),
        ("Üst banda değdikten sonra ne oldu?", ("BOLLINGER_UPPER_TOUCH",), "BEARISH"),
        ("Orta bant testleri işe yaradı mı?", ("BOLLINGER_MIDDLE_TEST",), None),
        ("RSI aşırı satım dönüşleri", ("RSI_LOCAL_TROUGH",), "BULLISH"),
        ("RSI 30'un altına indiğinde", ("RSI_LOCAL_TROUGH",), None),
        ("oversold rebounds", ("RSI_LOCAL_TROUGH", "BOLLINGER_LOWER_TOUCH"), "BULLISH"),
        ("overbought reversals", ("RSI_LOCAL_PEAK", "BOLLINGER_UPPER_TOUCH"), "BEARISH"),
        ("destek seviyesine yaklaştığında", ("SUPPORT_RESISTANCE_TOUCH",), "BULLISH"),
        ("touches of resistance", ("SUPPORT_RESISTANCE_TOUCH",), "BEARISH"),
        ("Supertrend dönüşleri tepe sonrası", ("SUPERTREND_FLIP",), "BEARISH"),
        ("dip dönüşü sinyalleri", None, "BULLISH"),
        ("reversal statistics", None, None),
    ],
)
def test_grounding_table(text, types, direction):
    assert reversal_grounding(text) == (types, direction)


def test_a_question_that_names_no_event_family_allows_any_event_type():
    for event_type in REVERSAL_EVENT_TYPES:
        for direction in ("BULLISH", "BEARISH"):
            assert check("TR-19", "PETKM", event_type=event_type, direction=direction) is None


def test_a_two_sided_family_checks_the_direction():
    problem = machine.check_call(
        STATE,
        "detect_reversal_events",
        {"ticker": "THYAO", **PERIOD, "event_type": "SUPERTREND_FLIP"},  # default BULLISH
        reversal_intent("THYAO"),
        analysis_id="AN-1",
        question="THYAO Supertrend tepe dönüşleri",
    )
    assert problem is not None and "direction must be BEARISH" in problem[1]


@pytest.mark.parametrize("qid", ["TR-01", "TR-11", "TR-05", "TR-19"])
def test_the_canonical_call_uses_the_grounded_values_and_passes_the_check(qid):
    intent_ = reversal_intent("THYAO")
    calls = machine.canonical_calls(STATE, intent_, question=question(qid))
    types, direction = reversal_grounding(question(qid))
    for name, arguments in calls:
        assert (
            machine.check_call(
                STATE, name, arguments, intent_, analysis_id="AN-1", question=question(qid)
            )
            is None
        )
        if types:
            assert arguments["event_type"] == types[0]
    if qid in ("TR-01", "TR-11", "TR-19"):  # TR-19 names no family: the default event
        assert calls[0][1]["event_type"] == machine.REVERSAL_EVENT == "BOLLINGER_LOWER_TOUCH"


def test_without_a_question_the_canonical_event_is_unchanged():
    calls = machine.canonical_calls(STATE, reversal_intent("THYAO"))
    assert calls == [
        (
            "detect_reversal_events",
            {"ticker": "THYAO", **PERIOD, "event_type": "BOLLINGER_LOWER_TOUCH", "forward_days": 5},
        )
    ]


def test_a_bearish_question_without_a_family_gets_a_bearish_canonical_event():
    calls = machine.canonical_calls(STATE, reversal_intent("THYAO"), question="tepe dönüşleri")
    assert calls[0][1]["event_type"] == "BOLLINGER_UPPER_TOUCH"


def test_in_a_run_the_contradicting_call_is_a_counted_wrong_call_and_the_fallback_is_grounded():
    text = question("TR-01")
    upper = call(
        "detect_reversal_events",
        ticker="THYAO",
        **PERIOD,
        event_type="BOLLINGER_UPPER_TOUCH",
        direction="BEARISH",
    )
    client = ScriptedClient(
        intent(scenario="TECHNICAL_REVERSAL", ticker="THYAO", language="tr"),
        "text",  # LOAD_MARKET_DATA: text twice, the harness falls back
        "text",
        "text",  # CALCULATE_TECHNICALS
        "text",
        [upper],  # RUN_PATTERN_AND_REVERSAL_ANALYSIS: rejected twice
        [upper],
        "text",  # RUN_BACKTEST
        "text",
    )
    analysis = machine.run_analysis(
        text, client, call_tool=FakeTools(), today=TODAY, explain_fn=lambda *a: None
    )
    reversal = [c for c in analysis.tool_calls if c.tool == "detect_reversal_events"]
    assert [(c.allowed, c.source) for c in reversal] == [
        (False, "model"),
        (False, "model"),
        (True, "harness"),
    ]
    assert reversal[0].output["error"]["code"] == "INTENT_MISMATCH"
    assert reversal[-1].arguments["event_type"] == "BOLLINGER_LOWER_TOUCH"
    record = {"tool_calls": [{"source": c.source, "allowed": c.allowed} for c in reversal]}
    assert wrong_calls(record) == (2, 2)
