"""The fine-tuning teacher and the training record format (Sprint 5, Task 1).

The teacher answers every model turn of the real harness with the correct reply; the
harness runs the real MCP tool functions on the synthetic snapshot of
``tests/golden_snapshot.py``, never the real data folder. Question wordings are this
file's own (ruling R5: no frozen-set text); ``test_question_wordings_are_not_frozen``
checks them with ``questions.overlaps``.
"""

from __future__ import annotations

import json
import re

import pytest

from bist_harness.data import macro as macro_data
from bist_harness.data import snapshot as snapshot_module
from bist_harness.eval import questions as frozen
from bist_harness.finetune.record import TURN_KINDS, TrainingRecord, read_jsonl, write_jsonl
from bist_harness.finetune.teacher import (
    CapturingClient,
    Gold,
    TeacherClient,
    TeacherError,
    choose_action,
)
from bist_harness.harness import machine, session
from bist_harness.harness.intent import INTENT_SCHEMA, INTENT_SYSTEM_PROMPT
from bist_harness.harness.routes import ALLOWED_TOOLS, ROUTES
from bist_harness.harness.validator import (
    DISCLAIMER,
    generate_explanation,
    period_note,
    validate_explanation,
)
from bist_harness.mcp_server import server as srv
from bist_harness.tools.schemas import to_ollama_tools

from .golden_snapshot import build_golden_snapshot

TODAY = "2024-12-31"  # training questions stay before the pre-registered test period


@pytest.fixture(autouse=True)
def golden_data(monkeypatch, tmp_path):
    """The seeded snapshot behind every tool; no price corrections; a private store."""
    root = tmp_path / "data"
    build_golden_snapshot(root / "snapshots")
    monkeypatch.setenv("BIST_DATA_DIR", str(root))
    no_adjustments = tmp_path / "adjustments.csv"
    no_adjustments.write_text("ticker,effective_date,factor,reason\n", encoding="utf-8")
    monkeypatch.setattr(snapshot_module, "ADJUSTMENTS_PATH", no_adjustments)
    monkeypatch.setattr(
        srv, "load_macro", lambda name: macro_data.load_macro(name, cpi_releases=None)
    )
    monkeypatch.setattr(session, "_store_path", lambda: tmp_path / "store.sqlite")
    session._LIVE.clear()
    yield
    session._LIVE.clear()


def real_tools(name: str, arguments: dict) -> dict:
    return getattr(srv, name)(**arguments)


def gold(scenario, ticker, start, end, language, *, sector=None, action=None) -> Gold:
    intent = {
        "scenario": scenario,
        "ticker": ticker,
        "sector": sector,
        "start": start,
        "end": end,
        "as_of": None,
        "language": language,
    }
    return Gold(intent=intent, action=action)


# One question per required scenario, both languages represented.
CASES = {
    "SECTOR_LAGGARD": (
        "AKBNK 2024-01-02 ile 2024-06-28 arasında banka hisselerinin gerisinde mi kaldı?",
        gold("SECTOR_LAGGARD", "AKBNK", "2024-01-02", "2024-06-28", "tr", sector="Banking"),
    ),
    "CALENDAR_PATTERN": (
        "Was there a day-of-week effect in ASELS returns between 2023-03-01 and 2024-10-31?",
        gold("CALENDAR_PATTERN", "ASELS", "2023-03-01", "2024-10-31", "en"),
    ),
    "TECHNICAL_REVERSAL": (
        "THYAO alt bandı test ettikten sonra 2024-01-02 ile 2024-09-30 arasında nasıl hareket etti?",
        gold("TECHNICAL_REVERSAL", "THYAO", "2024-01-02", "2024-09-30", "tr"),
    ),
    "FUNDAMENTAL_REACTION": (
        "After its quarterly reports between 2023-06-01 and 2024-12-31, how did TUPRS shares respond?",
        gold("FUNDAMENTAL_REACTION", "TUPRS", "2023-06-01", "2024-12-31", "en"),
    ),
}
UNDATED = (
    "How did THYAO move after it touched its lower band?",
    gold("TECHNICAL_REVERSAL", "THYAO", None, None, "en"),
)
SECTOR_ONLY = (
    "2024-01-02 ile 2024-06-28 arasında bankacılık sektöründe geride kalan hisseler hangileri?",
    gold("SECTOR_LAGGARD", None, "2024-01-02", "2024-06-28", "tr", sector="Banking"),
)
ADVICE = (
    "Bu hafta THYAO hissesini almalı mıyım, ne dersin?",
    gold("ADVICE_REQUEST", "THYAO", None, None, "tr"),
)


def run(question: str, teacher_gold: Gold, *, wrap=None, explain_fn=generate_explanation):
    teacher = TeacherClient(teacher_gold)
    client = wrap(teacher) if wrap else teacher
    analysis = machine.run_analysis(
        question, client, call_tool=real_tools, today=TODAY, explain_fn=explain_fn
    )
    return teacher, analysis


def model_states(scenario: str) -> list[str]:
    """The states of the route where the model proposes tool calls."""
    return [s for s in ROUTES[scenario] if ALLOWED_TOOLS[s] and s not in machine.HARNESS_STATES]


def capture_explanation(seen: dict):
    """The default explain step, keeping what the harness validated the reply against."""

    def explain(analysis, client, evidence, gate):
        result = generate_explanation(analysis, client, evidence, gate)
        seen.update(evidence=list(evidence), result=result)
        return result

    return explain


def test_question_wordings_are_not_frozen():
    texts = [q for q, _ in (*CASES.values(), UNDATED, SECTOR_ONLY, ADVICE)]
    assert frozen.overlaps(texts) == []


# --- the three turn kinds ----------------------------------------------------------------
@pytest.mark.parametrize("scenario", list(CASES))
def test_teacher_reply_matches_turn_kind(scenario):
    question, teacher_gold = CASES[scenario]
    teacher, analysis = run(question, teacher_gold)

    states = model_states(scenario)
    assert [r.turn for r in teacher.turns] == [
        "intent",
        *["tool_call"] * len(states),
        "explanation",
    ]
    assert [r.state for r in teacher.turns] == [None, *states, None]
    assert all(r.turn in TURN_KINDS for r in teacher.turns)
    assert {(r.scenario, r.language) for r in teacher.turns} == {
        (scenario, teacher_gold.intent["language"])
    }

    first = teacher.turns[0]
    assert first.messages[0] == {"role": "system", "content": INTENT_SYSTEM_PROMPT}
    reply = json.loads(first.target["content"])
    assert reply == teacher_gold.intent
    assert set(reply) == set(INTENT_SCHEMA["required"])
    assert first.tools == []

    for record in teacher.turns[1:-1]:
        assert record.messages[0]["content"].startswith(machine.TOOL_STATE_PROMPT)
        assert "content" not in record.target
        assert record.target["role"] == "assistant" and record.target["tool_calls"]
        assert record.tools == to_ollama_tools(ALLOWED_TOOLS[record.state])
        assert record.meta == {"state": record.state}
    # every teacher reply was accepted at the first attempt, with no fallback; no tool
    # failed (a backtest the tool rejects would be re-run) and nothing was topped up
    assert machine.wrong_tool_calls(analysis) == 0
    assert machine.harness_interventions(analysis) == 0
    assert [c.tool for c in analysis.tool_calls if "error" in c.output] == []
    for state in states:
        detail = next(r.detail for r in analysis.trail if r.state == state)
        assert (detail["attempts"], detail["rejected"], detail["fallback"]) == (1, 0, False)

    last = teacher.turns[-1]
    explanation = json.loads(last.target["content"])
    assert analysis.outcome == explanation["action"] == last.meta["action"]
    assert set(last.meta) == {"action", "eligible"}
    assert first.meta == {}
    assert analysis.answer == explanation["explanation"]
    assert last.tools == []


def test_teacher_messages_are_what_the_harness_sent():
    question, teacher_gold = CASES["FUNDAMENTAL_REACTION"]
    captured: list[CapturingClient] = []

    def wrap(teacher):
        captured.append(CapturingClient(teacher))
        return captured[0]

    teacher, _ = run(question, teacher_gold, wrap=wrap)
    requests = captured[0].requests
    assert len(requests) == len(teacher.turns)
    for request, record in zip(requests, teacher.turns, strict=True):
        # compared as text: a dict with the same items in another key order must fail
        assert json.dumps(record.messages) == json.dumps(request["messages"])
        assert json.dumps(record.tools) == json.dumps(request["tools"] or [])


# --- the explanation target ----------------------------------------------------------------
_CITED_LINE = re.compile(r" \[E\d+\]$")


@pytest.mark.parametrize("case", ["dated", "undated"])
def test_teacher_explanation_passes_validator(case):
    question, teacher_gold = UNDATED if case == "undated" else CASES["TECHNICAL_REVERSAL"]
    seen: dict = {}
    teacher, analysis = run(question, teacher_gold, explain_fn=capture_explanation(seen))

    target = json.loads(teacher.turns[-1].target["content"])
    result = seen["result"]
    intent = analysis.intent
    problems = validate_explanation(
        target["explanation"],
        action=target["action"],
        eligible=result.eligible,
        evidence=seen["evidence"],
        question=question,
        language=intent["language"],
        defaulted_period=intent["defaulted_period"],
        defaulted_bound=intent["defaulted_bound"],
    )
    assert problems == []
    # the harness took the first reply; with no gold action the preferred eligible label
    assert (result.attempts, result.fallback) == (1, False)
    assert result.eligible == ["HOLD", "WATCH", "INVESTIGATE"]
    assert target["action"] == "WATCH" == teacher.turns[-1].meta["action"]
    assert teacher.turns[-1].meta["eligible"] == result.eligible

    lines = target["explanation"].split("\n")
    committed = [e for e in seen["evidence"] if e.committed]
    fixed = [DISCLAIMER[intent["language"]]]
    if intent["defaulted_period"]:
        fixed.insert(0, period_note(intent["language"], intent["defaulted_bound"]))
    assert lines == [f"{e.sentence} [{e.label}]" for e in committed] + fixed
    assert all(_CITED_LINE.search(line) for line in lines[: len(committed)])
    assert (case == "undated") == intent["defaulted_period"]


def test_teacher_copies_sign():
    question, teacher_gold = CASES["TECHNICAL_REVERSAL"]
    seen: dict = {}
    teacher, _ = run(question, teacher_gold, explain_fn=capture_explanation(seen))
    drawdown = next(e for e in seen["evidence"] if e.committed and e.field == "max_drawdown_pct")
    assert drawdown.value < 0
    shown = re.search(r"%-\d+(?:,\d+)?", drawdown.sentence)[0]  # Turkish: "%-16,88"
    text = json.loads(teacher.turns[-1].target["content"])["explanation"]
    assert shown in text
    assert f"[{drawdown.label}]" in text


# --- guarded questions ----------------------------------------------------------------------
def test_advice_question_yields_only_intent_turn():
    question, teacher_gold = ADVICE
    teacher, analysis = run(question, teacher_gold)
    assert [r.turn for r in teacher.turns] == ["intent"]
    assert teacher.turns[0].scenario == "ADVICE_REQUEST"
    assert json.loads(teacher.turns[0].target["content"])["scenario"] == "ADVICE_REQUEST"
    assert analysis.outcome == machine.REFUSED_ADVICE
    assert analysis.tool_calls == []


# --- the teacher never writes a target it cannot stand behind ------------------------------
def test_unrecognised_turn_raises_value_error():
    teacher = TeacherClient(CASES["CALENDAR_PATTERN"][1])
    with pytest.raises(ValueError):
        teacher.chat(
            [{"role": "system", "content": "Summarise."}, {"role": "user", "content": "x"}]
        )
    assert teacher.turns == []


def test_a_rejected_target_raises_teacher_error():
    question, teacher_gold = CASES["CALENDAR_PATTERN"]
    teacher = TeacherClient(teacher_gold)
    retry = [
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": question},
        {"role": "assistant", "content": "{}"},
        {"role": "user", "content": "That was not valid. Answer again with only the JSON object."},
    ]
    with pytest.raises(TeacherError):
        teacher.chat(retry, response_format=INTENT_SCHEMA)


def test_an_ungrounded_gold_intent_raises_teacher_error():
    question, teacher_gold = CASES["CALENDAR_PATTERN"]
    wrong = Gold(intent={**teacher_gold.intent, "start": "2022-01-03"}, action=None)
    with pytest.raises(TeacherError, match="start"):
        run(question, wrong)


def test_a_gold_action_that_is_not_eligible_raises_teacher_error():
    question, teacher_gold = CASES["TECHNICAL_REVERSAL"]
    wrong = Gold(intent=teacher_gold.intent, action="POTENTIAL_CATCH_UP_CANDIDATE")
    with pytest.raises(TeacherError, match="POTENTIAL_CATCH_UP_CANDIDATE"):
        run(question, wrong)


def test_an_eligible_gold_action_wins():
    question, teacher_gold = CASES["TECHNICAL_REVERSAL"]
    teacher, analysis = run(question, Gold(intent=teacher_gold.intent, action="INVESTIGATE"))
    assert json.loads(teacher.turns[-1].target["content"])["action"] == "INVESTIGATE"
    assert analysis.outcome == "INVESTIGATE"


@pytest.mark.parametrize(
    ("eligible", "chosen"),
    [
        (["HOLD", "WATCH", "INVESTIGATE"], "WATCH"),
        (
            ["HOLD", "WATCH", "INVESTIGATE", "TECHNICAL_REVERSAL_CANDIDATE"],
            "TECHNICAL_REVERSAL_CANDIDATE",
        ),
        (["HOLD", "INVESTIGATE", "REJECT_SIGNAL"], "REJECT_SIGNAL"),
        (["REJECT_SIGNAL"], "REJECT_SIGNAL"),
        (["HOLD", "INVESTIGATE"], "HOLD"),
        (["INVESTIGATE"], "INVESTIGATE"),
    ],
)
def test_default_label_preference(eligible, chosen):
    assert choose_action(eligible, None) == chosen


def test_explicit_action_and_never_analysis_unsafe():
    assert choose_action(["HOLD", "WATCH", "INVESTIGATE"], "HOLD") == "HOLD"
    with pytest.raises(TeacherError, match="WATCH"):
        choose_action(["HOLD", "INVESTIGATE"], "WATCH")
    with pytest.raises(TeacherError):
        choose_action(["ANALYSIS_UNSAFE"], None)


# --- a state without a canonical call -------------------------------------------------------
def test_a_state_without_a_canonical_call_writes_no_record():
    question, teacher_gold = SECTOR_ONLY
    teacher, analysis = run(question, teacher_gold)
    states = [r.state for r in teacher.turns if r.turn == "tool_call"]
    assert "CALCULATE_TECHNICALS" not in states  # needs a stock; the question names none
    assert [r.turn for r in teacher.turns] == [
        "intent",
        *["tool_call"] * len(states),
        "explanation",
    ]
    assert states == [s for s in model_states("SECTOR_LAGGARD") if s != "CALCULATE_TECHNICALS"]
    detail = next(r.detail for r in analysis.trail if r.state == "CALCULATE_TECHNICALS")
    assert detail["fallback"] is True  # the harness's own fallback, not the teacher's record
    assert analysis.outcome == json.loads(teacher.turns[-1].target["content"])["action"]


def test_gold_intent_must_fit_the_schema():
    with pytest.raises(ValueError):
        Gold(intent={"scenario": "PRICE_SUMMARY", "ticker": "THYAO"}, action=None)
    with pytest.raises(ValueError):
        Gold(intent={**ADVICE[1].intent, "language": "de"}, action=None)
    with pytest.raises(ValueError):
        Gold(intent=ADVICE[1].intent, action="BUY")


# --- the record file -------------------------------------------------------------------------
def test_records_round_trip_with_a_stable_hash(tmp_path):
    question, teacher_gold = CASES["CALENDAR_PATTERN"]
    teacher = TeacherClient(teacher_gold, question_id="gen-001", family="calendar-dated")
    machine.run_analysis(question, teacher, call_tool=real_tools, today=TODAY)
    records = teacher.turns
    assert [r.record_id for r in records] == [f"gen-001-{i:02d}" for i in range(len(records))]
    assert {(r.question_id, r.family) for r in records} == {("gen-001", "calendar-dated")}

    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    digest = write_jsonl(records, first)
    assert write_jsonl(records, second) == digest
    assert len(digest) == 64
    raw = first.read_bytes()
    assert b"\r\n" not in raw and raw.count(b"\n") == len(records)
    assert read_jsonl(first) == records
    assert all(isinstance(r, TrainingRecord) for r in read_jsonl(first))


def test_records_keep_the_key_order_the_harness_sent(tmp_path):
    tool = {"type": "function", "function": {"name": "zeta", "parameters": {"z": 1, "a": 2}}}
    record = TrainingRecord(
        record_id="q-00",
        question_id="q",
        family="f",
        language="en",
        scenario="PRICE_SUMMARY",
        turn="tool_call",
        state="LOAD_MARKET_DATA",
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        tools=[tool],
        target={
            "role": "assistant",
            "tool_calls": [
                {
                    "function": {
                        "name": "zeta",
                        "arguments": {"ticker": "X", "end": "e", "start": "s"},
                    }
                }
            ],
        },
        meta={"today": "t", "action": None},
    )
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_jsonl([record], first)
    write_jsonl([record], second)
    assert first.read_bytes() == second.read_bytes()
    (back,) = read_jsonl(first)
    assert list(back.tools[0]) == ["type", "function"]
    assert list(back.tools[0]["function"]["parameters"]) == ["z", "a"]
    arguments = back.target["tool_calls"][0]["function"]["arguments"]
    assert list(arguments) == ["ticker", "end", "start"]
    assert list(back.messages[0]) == ["role", "content"]
    assert list(back.meta) == ["today", "action"]
