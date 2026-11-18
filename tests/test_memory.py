"""Episodic memory of past analyses and human decisions (card EC-047).

The model never sees a memory item: it is shown to the user (answer, review screen,
decision log) and never enters a prompt or the committed evidence set.
"""

from __future__ import annotations

import dataclasses
import inspect
import json

import pytest

from bist_harness.eval import metrics
from bist_harness.harness import machine, memory, replay, review, session
from bist_harness.harness.actions import eligible_actions
from bist_harness.harness.validator import Explanation, generate_explanation
from bist_harness.storage import db

from .test_machine import ScriptedClient, call, intent
from .test_machine_integration import (  # noqa: F401  (golden_data is an autouse fixture)
    TODAY,
    golden_data,
    real_tools,
)

FIRST = {"start": "2025-01-02", "end": "2025-06-30"}
SECOND = {"start": "2025-01-02", "end": "2025-09-30"}
LONG_AGO = "2000-01-01T00:00:00+00:00"
FAR_FUTURE = "2999-01-01T00:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "memory.sqlite")
    yield connection
    connection.close()


def explain(analysis, client, evidence, gate):
    return Explanation(action="WATCH", text="ASELS moved [E1].", eligible=["WATCH"])


def question_for(period, language="en"):
    if language == "tr":
        return f"ASELS hissesi {period['start']} ile {period['end']} arasında nasıl işlem gördü?"
    return f"How did ASELS trade from {period['start']} to {period['end']}?"


def analyse(period, conn, *, memory_on, explain_fn=explain, language="en"):
    client = ScriptedClient(
        intent(ticker="ASELS", language=language, **period),
        [call("get_stock_history", ticker="ASELS", **period)],
        [call("calculate_indicators", ticker="ASELS", **period, indicators=[])],
    )
    analysis = machine.run_analysis(
        question_for(period, language),
        client,
        call_tool=real_tools,
        today=TODAY,
        conn=conn,
        explain_fn=explain_fn,
        memory=memory_on,
    )
    return analysis, client


def decide(conn, analysis, verdict="ACCEPT", reviewed_at=LONG_AGO):
    review.record_review(analysis.analysis_id, verdict, "checked the evidence", conn)
    with conn:
        conn.execute(
            "UPDATE decisions SET reviewed_at = ? WHERE analysis_id = ?",
            (reviewed_at, analysis.analysis_id),
        )


def test_second_analysis_shows_previous_and_human_decision(conn):
    first, _ = analyse(FIRST, conn, memory_on=True)
    assert memory.items_of(first, language="en") == []  # nothing came before it
    decide(conn, first, "ACCEPT")
    second, _ = analyse(SECOND, conn, memory_on=True)
    items = memory.items_of(second, language="en")
    assert len(items) == 1
    assert items[0].tool == "memory" and items[0].committed is False
    assert "2025-06-30" in items[0].sentence and "ACCEPT" in items[0].sentence
    assert first.outcome in items[0].sentence
    # shown in the answer and on the review screen / decision log, in the question's language
    assert "Earlier analyses:" in second.answer and "ACCEPT" in second.answer
    log = review.decision_log(second, conn)
    assert any(e["tool"] == "memory" and not e["committed"] for e in log["evidence_bundle"])
    assert not any(e["tool"] == "memory" for e in log["evidence_bundle"] if e["committed"])
    turkish, _ = analyse(SECOND, conn, memory_on=True, language="tr")
    assert "Önceki analizler:" in turkish.answer and "insan kararı" in turkish.answer


def test_memory_never_recalls_later_episodes(conn):
    later, _ = analyse(SECOND, conn, memory_on=True)  # as_of 2025-09-30, analysed first
    earlier, _ = analyse(FIRST, conn, memory_on=True)  # as_of 2025-06-30
    assert memory.items_of(earlier, language="en") == []
    assert "Earlier analyses:" not in earlier.answer
    assert memory.recall(conn, ticker="ASELS", as_of="2025-06-30") == []
    only = memory.recall(conn, ticker="ASELS", as_of="2025-09-30")  # strictly before
    assert [e.as_of for e in only] == ["2025-06-30"]
    found = memory.recall(conn, ticker="ASELS", as_of="2025-10-01")
    assert [e.as_of for e in found] == ["2025-09-30", "2025-06-30"]
    # an episode created after the asking time is not known yet
    assert memory.recall(conn, ticker="ASELS", as_of="2025-10-01", known_at=LONG_AGO) == []
    # a review made after the new analysis: the episode appears, the decision does not
    decide(conn, earlier, "REJECT", reviewed_at=FAR_FUTURE)
    third, _ = analyse({"start": "2025-01-02", "end": "2025-12-01"}, conn, memory_on=True)
    items = {e.analysis_id: e for e in memory.recall_for(conn, third)}
    assert items[earlier.analysis_id].human_result is None
    assert "REJECT" not in third.answer
    # shown: the episode's line is in the answer, with the "none yet" wording
    line = next(
        e for e in memory.items_of(third, language="en") if e.result_id == earlier.analysis_id
    )
    assert line.sentence in third.answer and "human decision: none yet" in line.sentence
    # stored: the trail keeps the episode with its decision withheld
    stored = {
        e["analysis_id"]: e for e in memory.episodes_of(session.load(third.analysis_id, conn))
    }
    assert stored[earlier.analysis_id]["human_result"] is None
    assert stored[earlier.analysis_id]["reviewed_at"] is None


def test_memory_off_gives_same_committed_set(conn):
    first, _ = analyse(FIRST, conn, memory_on=False)
    decide(conn, first)
    seen = {}

    def capture(key):
        def fn(analysis, client, evidence, gate):
            seen[key] = (
                [dataclasses.astuple(e) for e in evidence],
                list(eligible_actions(analysis, evidence, gate)),
                gate.status,
            )
            return explain(analysis, client, evidence, gate)

        return fn

    off, _ = analyse(SECOND, conn, memory_on=False, explain_fn=capture("off"))
    on, _ = analyse(SECOND, conn, memory_on=True, explain_fn=capture("on"))
    assert memory.items_of(off, language="en") == []
    assert len(memory.items_of(on, language="en")) == 1
    assert seen["on"][1:] == seen["off"][1:]  # eligible actions and gate
    assert seen["on"][0] == seen["off"][0]  # the evidence handed on: same, committed set too
    assert all(e[1] != "memory" for e in seen["on"][0])


def test_memory_changes_no_model_prompt(conn):
    first, _ = analyse(FIRST, conn, memory_on=False)
    decide(conn, first)

    def run(memory_on):
        client = ScriptedClient(
            intent(ticker="ASELS", **SECOND),
            [call("get_stock_history", ticker="ASELS", **SECOND)],
            [call("calculate_indicators", ticker="ASELS", **SECOND, indicators=[])],
            "not json",
            "not json",
        )
        analysis = machine.run_analysis(
            question_for(SECOND),
            client,
            call_tool=real_tools,
            today=TODAY,
            conn=conn,
            explain_fn=generate_explanation,
            memory=memory_on,
        )
        return analysis, client

    off, client_off = run(False)
    on, client_on = run(True)
    assert len(memory.items_of(on, language="en")) == 1
    messages_on = [r["messages"] for r in client_on.requests]
    assert messages_on == [r["messages"] for r in client_off.requests]
    assert len(messages_on) == 5  # intent, two tool states, two explanation attempts
    assert "Earlier analyses" not in json.dumps(messages_on)
    assert "Earlier analyses:" in on.answer and "Earlier analyses:" not in off.answer


def test_replay_with_memory_matches(conn):
    first, _ = analyse(FIRST, conn, memory_on=True)
    decide(conn, first, "MODIFY")
    second, _ = analyse(SECOND, conn, memory_on=True)
    analyse({"start": "2025-01-02", "end": "2025-07-31"}, conn, memory_on=True)  # created later
    stored = session.load(second.analysis_id, conn)
    again = memory.recall_for(conn, stored)  # as it was: original created_at and as_of
    assert [dataclasses.asdict(e) for e in again] == memory.episodes_of(stored)
    assert len(again) == 1 and again[0].human_result == "MODIFY"
    assert memory.memory_items(again, language="en") == memory.items_of(stored, language="en")
    assert stored.answer == second.answer
    result = replay.replay(
        stored,
        call_tool=real_tools,
        verify=lambda snapshot_id: [],
        current_snapshot_id=lambda: stored.snapshot_id,
    )
    assert result.status == replay.MATCH


def test_memory_section_is_not_model_text():
    done = memory.Episode(
        "A-1", "2025-06-30", "PRICE_SUMMARY", "WATCH", "WATCH", "ACCEPT", "ok", "x"
    )
    pending = dataclasses.replace(done, human_result=None, reason=None, reviewed_at=None)
    for language, episode, body in (("en", done, "ASELS moved [E1]."), ("tr", pending, "Metin.")):
        section = memory.answer_section(
            memory.memory_items([episode], language=language), language=language
        )
        trail = [{"state": "BUILD_EVIDENCE", "detail": {"memory": [dataclasses.asdict(episode)]}}]
        record = {"answer": body + chr(10) * 2 + section, "answer_by": "model", "trail": trail}
        record["language"] = language
        text = metrics._model_text(record)
        assert "2025" not in text and "ACCEPT" not in text and body in text


def test_default_run_analysis_has_memory_off(conn):
    assert inspect.signature(machine.run_analysis).parameters["memory"].default is False
    first, _ = analyse(FIRST, conn, memory_on=False)
    decide(conn, first)  # a store that holds an earlier analysis of the same stock
    client = ScriptedClient(
        intent(ticker="ASELS", **SECOND),
        [call("get_stock_history", ticker="ASELS", **SECOND)],
        [call("calculate_indicators", ticker="ASELS", **SECOND, indicators=[])],
    )
    second = machine.run_analysis(  # no memory argument
        question_for(SECOND),
        client,
        call_tool=real_tools,
        today=TODAY,
        conn=conn,
        explain_fn=explain,
    )
    assert memory.items_of(second, language="en") == []
    assert memory.episodes_of(session.load(second.analysis_id, conn)) == []
    assert "Earlier analyses:" not in second.answer


def test_only_experiment_e_runs_with_memory(monkeypatch, conn):
    from bist_harness.eval import run_eval

    seen = {}

    def fake(text, client, **kwargs):
        seen[len(seen)] = (kwargs["memory"], kwargs["conn"])
        raise RuntimeError("stop")

    monkeypatch.setattr(run_eval.machine, "run_analysis", fake)
    for experiment in ("D", "E"):
        with pytest.raises(RuntimeError):
            run_eval.run_one(
                experiment,
                {"question": "q"},
                1,
                ScriptedClient(),
                call_tool=real_tools,
                today=TODAY,
                memory=conn,
            )
    assert seen == {0: (False, None), 1: (True, conn)}
