"""Human review CLI and the complete decision log (design spec section 10, card EC-048)."""

import json

import pytest

from bist_harness.harness import machine, review, session
from bist_harness.harness.validator import Explanation
from bist_harness.llm.client import ChatResult, ToolCall
from bist_harness.storage import db

PERIOD = {"start": "2025-01-02", "end": "2025-06-30"}
INTENT = {
    "scenario": "PRICE_SUMMARY",
    "ticker": "THYAO",
    "sector": None,
    "start": PERIOD["start"],
    "end": PERIOD["end"],
    "as_of": None,
    "language": "en",
}
VERSIONS = {"snapshot_id": "SNAP-1", "adjustments_id": "ADJ-1", "layers_id": "LAY-1"}


def reply(content="", calls=()):
    return ChatResult(
        content=content,
        tool_calls=tuple(calls),
        prompt_tokens=0,
        completion_tokens=0,
        total_duration_s=0.0,
        eval_tokens_per_s=None,
        raw={},
        malformed_tool_call=False,
    )


class Client:
    model = "fake-model"

    def __init__(self):
        indicators = {"ticker": "THYAO", "indicators": [], **PERIOD}
        self.script = [
            reply(json.dumps(INTENT)),
            reply("", [ToolCall("get_stock_history", {"ticker": "THYAO", **PERIOD})]),
            reply("", [ToolCall("calculate_indicators", indicators)]),
        ]

    def chat(self, messages, tools=None, **kwargs):
        return self.script.pop(0)


def tools(name, arguments):
    output = {"result_id": f"{name}-id", **VERSIONS}
    if name == "get_stock_history":
        output |= {
            "ticker": "THYAO",
            "period_return_pct": 12.5,
            "last_close": 300.0,
            "first_date": "2025-01-02",
            "last_date": "2025-06-30",
        }
    if name == "check_data_quality":
        output |= {"status": "PASS"}
    return output


def explain(analysis, client, evidence, gate):
    return Explanation(action="WATCH", text="THYAO returned 12.5% [E1].", eligible=["WATCH"])


@pytest.fixture(autouse=True)
def fixed_versions(monkeypatch, tmp_path):
    monkeypatch.setattr(session, "_versions", lambda: ("SNAP-1", "ADJ-1"))
    monkeypatch.setattr(session, "_store_path", lambda: tmp_path / "store.sqlite")


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "store.sqlite")
    yield connection
    connection.close()


@pytest.fixture
def completed(conn):
    return machine.run_analysis(
        "How did THYAO do?",
        Client(),
        call_tool=tools,
        today="2026-11-17",
        conn=conn,
        explain_fn=explain,
    )


def empty_fields(log):
    return [k for k, v in log.items() if v is None or v in ("", [], {})]


# --- the decision log ----------------------------------------------------------------
def test_every_field_of_section_28_is_filled_for_a_completed_analysis(completed, conn):
    log = review.decision_log(completed, conn)
    assert set(log) == set(db.DECISION_LOG_FIELDS)
    assert empty_fields(log) == []


def test_log_content_of_a_completed_analysis(completed, conn):
    log = review.decision_log(completed, conn)
    na = review.NOT_APPLICABLE
    assert log["stock"] == "THYAO"
    assert log["sector"] == na  # a stock question names no sector
    assert log["analysis_time"] == completed.created_at
    assert (log["data_period_start"], log["data_period_end"]) == (PERIOD["start"], PERIOD["end"])
    assert log["market_data_snapshot"] == "SNAP-1"
    assert log["data_versions_and_publication_times"]["layers_id"] == "LAY-1"
    assert "get_stock_history" in log["tools_called"][0]
    assert log["tool_arguments"]["1"] == {"ticker": "THYAO", **PERIOD}
    assert log["tool_outputs"]["1"]["period_return_pct"] == 12.5
    states = log["technical_sector_fundamental_macro_states"]
    assert states["CALCULATE_TECHNICALS"] == "RAN"
    assert states["LOAD_FUNDAMENTALS"] == "NOT_APPLICABLE"
    assert log["news_and_speech_source_metadata"] == na
    assert log["evidence_bundle"] and log["evidence_bundle"][0]["label"] == "E1"
    assert log["committed_evidence_set"] == [
        e["label"] for e in log["evidence_bundle"] if e["committed"]
    ]
    assert log["strategy_variant"] == na
    assert log["backtest_result"] == na
    assert log["gate_status"] == "PASS"
    assert log["agent_result"] == "WATCH"
    assert log["agent_explanation"] == "THYAO returned 12.5% [E1]."
    assert log["human_review_result"] == review.PENDING
    assert log["human_review_reason"] == review.PENDING


def test_a_refused_question_still_has_a_full_log(conn):
    client = Client()
    client.script = [reply(json.dumps({**INTENT, "scenario": "ADVICE_REQUEST"}))]
    refused = machine.run_analysis(
        "Should I buy THYAO?", client, call_tool=tools, today="2026-11-17", conn=conn
    )
    log = review.decision_log(refused, conn)
    assert empty_fields(log) == []
    assert log["agent_result"] == "REFUSED_ADVICE"
    assert log["tools_called"] == review.NOT_APPLICABLE


def test_backtest_strategy_and_result_are_logged(conn):
    analysis = session.new_analysis("q", model="m")
    analysis.intent = {**INTENT, "scenario": "BACKTEST"}
    session.record_call(
        analysis,
        state="RUN_BACKTEST",
        tool="run_backtest",
        arguments={"strategy": "A_TECHNICAL", "universe": ["THYAO"], **PERIOD},
        output={"result_id": "bt1", "trades": 7},
    )
    log = review.decision_log(analysis, conn)
    assert log["strategy_variant"] == "A_TECHNICAL"
    assert log["backtest_result"] == {"result_id": "bt1", "trades": 7}


# --- the review ----------------------------------------------------------------------
def test_review_writes_the_result_and_reason_to_the_store(completed, conn):
    review.record_review(completed.analysis_id, "MODIFY", "Period too short.", conn)
    row = conn.execute(
        "SELECT human_result, reason FROM decisions WHERE analysis_id = ?",
        (completed.analysis_id,),
    ).fetchone()
    assert row == ("MODIFY", "Period too short.")
    log = review.decision_log(completed, conn)
    assert (log["human_review_result"], log["human_review_reason"]) == (
        "MODIFY",
        "Period too short.",
    )


def test_the_latest_review_is_the_one_logged(completed, conn):
    review.record_review(completed.analysis_id, "REJECT", "first", conn)
    review.record_review(completed.analysis_id, "ACCEPT", "second", conn)
    log = review.decision_log(completed, conn)
    assert (log["human_review_result"], log["human_review_reason"]) == ("ACCEPT", "second")


def test_review_cli_accepts_and_stores(completed, capsys):
    code = review.main([completed.analysis_id, "ACCEPT", "Evidence is consistent."])
    assert code == 0
    assert "ACCEPT" in capsys.readouterr().out
    conn = db.connect(session._store_path())
    assert conn.execute("SELECT human_result, reason FROM decisions").fetchall() == [
        ("ACCEPT", "Evidence is consistent.")
    ]
    conn.close()


def test_review_cli_unknown_id_is_a_clear_error(completed, capsys):
    code = review.main(["AN-nope", "ACCEPT", "x"])
    assert code != 0
    assert "unknown analysis" in capsys.readouterr().err


def test_review_cli_without_a_store_is_a_clear_error(capsys):
    assert review.main(["AN-nope", "ACCEPT", "x"]) != 0
    assert "unknown analysis" in capsys.readouterr().err


def test_review_cli_bad_verdict_is_a_clear_error(completed, capsys):
    code = review.main([completed.analysis_id, "MAYBE", "x"])
    assert code != 0
    assert "ACCEPT, MODIFY or REJECT" in capsys.readouterr().err
    conn = db.connect(session._store_path())
    assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
    conn.close()


def test_review_cli_needs_a_reason(completed, capsys):
    assert review.main([completed.analysis_id, "ACCEPT", "  "]) != 0
    assert review.main([completed.analysis_id, "ACCEPT"]) != 0


def test_log_command_prints_the_log_as_json(completed, capsys):
    assert review.main(["log", completed.analysis_id]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert set(printed) == set(db.DECISION_LOG_FIELDS)
