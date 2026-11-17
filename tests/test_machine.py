"""The stateful harness: state loop, tool permissions, intent checks and the fallback.

The model is a scripted fake client and the tools are a fake ``call_tool``; no real
model, network or data download is involved.
"""

import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from bist_harness.errors import LLMUnavailableError
from bist_harness.harness import machine, session
from bist_harness.harness.routes import ALLOWED_TOOLS, GUARDED_ROUTE, ROUTES, STATES
from bist_harness.llm.client import ChatResult, ToolCall
from bist_harness.storage import db

TODAY = "2026-11-17"
MALFORMED = object()  # a reply that tries to call a tool but cannot be parsed


def reply(content: str = "", calls=(), *, malformed: bool = False) -> ChatResult:
    return ChatResult(
        content=content,
        tool_calls=tuple(calls),
        prompt_tokens=0,
        completion_tokens=0,
        total_duration_s=0.0,
        eval_tokens_per_s=None,
        raw={},
        malformed_tool_call=malformed,
    )


class ScriptedClient:
    """Stand-in for OllamaClient: answers with the scripted replies, in order.

    A script item is a string (a text answer, e.g. the intent JSON), a list of
    ``ToolCall`` (a tool-call answer) or ``MALFORMED``.
    """

    model = "fake-model"

    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[dict] = []

    def chat(self, messages, tools=None, **kwargs):
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tools, **kwargs})
        if not self.script:
            raise AssertionError("the model was asked more often than scripted")
        item = self.script.pop(0)
        if item is MALFORMED:
            return reply('<tool_call>{"name": "get_stock_history", "arguments": {', malformed=True)
        if isinstance(item, str):
            return reply(item)
        return reply("", item)

    def tool_turns(self) -> list[dict]:
        return [r for r in self.requests if r["tools"]]


class FakeTools:
    """Stand-in for the MCP tools: records every call and answers with a result id."""

    def __init__(self, quality: str = "PASS"):
        self.quality = quality
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, dict(arguments)))
        output = {"result_id": f"{name}-{len(self.calls)}"}
        if name == "check_data_quality":
            output["status"] = self.quality
        return output


def intent(**over) -> str:
    base = {
        "scenario": "PRICE_SUMMARY",
        "ticker": "THYAO",
        "sector": None,
        "start": "2025-01-02",
        "end": "2025-06-30",
        "as_of": None,
        "language": "en",
    }
    base.update(over)
    return json.dumps(base)


def call(name: str, **arguments) -> ToolCall:
    return ToolCall(name, arguments)


def visited(analysis) -> list[str]:
    return [r.state for r in analysis.trail if r.status != "NOT_APPLICABLE"]


def record_of(analysis, state):
    return next(r for r in analysis.trail if r.state == state)


@pytest.fixture(autouse=True)
def private_store(monkeypatch, tmp_path):
    """No test may read or create the real store in the data directory."""
    path = tmp_path / "default-store.sqlite"
    monkeypatch.setattr(session, "_store_path", lambda: path)
    return path


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "machine.sqlite")
    yield connection
    connection.close()


# --- G1: the run record --------------------------------------------------------------
def test_a_new_analysis_records_temperature_zero_and_seed_42():
    analysis = session.new_analysis("q", model="qwen3")
    assert (analysis.temperature, analysis.seed) == (0.0, 42)
    assert analysis.outcome is None and analysis.answer is None
    assert analysis.gate_status is None and analysis.trail == []


def test_outcome_trail_and_run_settings_survive_save_and_load(conn):
    analysis = session.new_analysis("q", model="qwen3")
    analysis.outcome = "REFUSED_ADVICE"
    analysis.answer = "Eğitim amaçlıdır."
    analysis.gate_status = "PASS"
    analysis.trail.append(session.StateRecord("START", "RAN", {"scenario": "ADVICE_REQUEST"}))
    analysis.trail.append(session.StateRecord("SELECT_UNIVERSE", "NOT_APPLICABLE"))
    session.save(analysis, conn)
    loaded = session.load(analysis.analysis_id, conn)
    assert loaded.temperature == 0.0 and loaded.seed == 42
    assert (loaded.outcome, loaded.answer, loaded.gate_status) == (
        "REFUSED_ADVICE",
        "Eğitim amaçlıdır.",
        "PASS",
    )
    assert loaded.trail == analysis.trail
    row = conn.execute(
        "SELECT outcome, gate_status, run_json FROM analyses WHERE analysis_id = ?",
        (analysis.analysis_id,),
    ).fetchone()
    assert row[0] == "REFUSED_ADVICE" and row[1] == "PASS"
    assert json.loads(row[2])["seed"] == 42


def test_a_version_2_store_gains_the_run_columns(tmp_path):
    path = tmp_path / "old.sqlite"
    raw = sqlite3.connect(path)
    raw.execute(
        "CREATE TABLE analyses (analysis_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
        "question TEXT NOT NULL, intent_json TEXT, ticker TEXT, sector TEXT, as_of TEXT, "
        "period_start TEXT, period_end TEXT, snapshot_id TEXT, data_versions_json TEXT, "
        "model TEXT, state TEXT, states_json TEXT, sources_json TEXT, strategy_variant TEXT, "
        "backtest_json TEXT, gate_status TEXT, action TEXT, explanation TEXT)"
    )
    raw.execute(
        "INSERT INTO analyses (analysis_id, created_at, question, data_versions_json, model, "
        "snapshot_id, state) VALUES ('AN-old', 't', 'q', '{\"adjustments_id\": \"a\"}', 'm', "
        "'s', 'LOG_AND_CLOSE')"
    )
    raw.execute("PRAGMA user_version = 2")
    raw.commit()
    raw.close()
    conn = db.connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(analyses)")}
    assert {"outcome", "run_json"} <= columns
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 3
    old = session.load("AN-old", conn)  # written before the run columns existed
    assert (old.temperature, old.seed, old.outcome, old.trail) == (0.0, 42, None, [])
    conn.close()


# --- G2: advice and prediction questions are refused without a tool call -------------
@pytest.mark.parametrize(
    ("question", "label", "language"),
    [
        ("Should I buy THYAO now?", "ADVICE_REQUEST", "en"),
        ("Bu hisseyi portföyüme mi koysam, THYAO?", "ADVICE_REQUEST", "tr"),
        ("THYAO alayım mı?", "PRICE_SUMMARY", "tr"),  # the keyword guard overrules the model
        ("THYAO yarın yükselir mi?", "PREDICTION_REQUEST", "tr"),
        ("What will THYAO price be next month?", "PRICE_SUMMARY", "en"),
    ],
)
def test_advice_or_prediction_makes_no_tool_call(question, label, language):
    client = ScriptedClient(intent(scenario=label, language=language))
    tools = FakeTools()
    analysis = machine.run_analysis(question, client, call_tool=tools, today=TODAY)
    assert tools.calls == [] and analysis.tool_calls == []
    assert len(client.requests) == 1  # the intent turn only, no tool turn
    assert analysis.outcome == "REFUSED_ADVICE"
    assert analysis.answer == machine.REFUSAL_ANSWERS[language]
    assert visited(analysis) == list(GUARDED_ROUTE)
    assert analysis.state == "LOG_AND_CLOSE"


def test_refusal_answers_are_educational_in_both_languages():
    assert "eğitim" in machine.REFUSAL_ANSWERS["tr"].casefold()
    assert "educational" in machine.REFUSAL_ANSWERS["en"].casefold()
    for text in machine.REFUSAL_ANSWERS.values():
        assert "ANALYSIS_UNSAFE" not in text


def test_out_of_scope_question_is_answered_without_tools():
    client = ScriptedClient(intent(scenario="OUT_OF_SCOPE", ticker=None, start=None, end=None))
    tools = FakeTools()
    analysis = machine.run_analysis("Write me a poem", client, call_tool=tools, today=TODAY)
    assert tools.calls == [] and analysis.outcome == "OUT_OF_SCOPE"
    assert analysis.answer == machine.OUT_OF_SCOPE_ANSWERS["en"]
    assert visited(analysis) == list(GUARDED_ROUTE)


def test_a_refused_question_is_saved(conn):
    client = ScriptedClient(intent(scenario="ADVICE_REQUEST", language="tr"))
    analysis = machine.run_analysis(
        "THYAO alayım mı?", client, call_tool=FakeTools(), today=TODAY, conn=conn
    )
    loaded = session.load(analysis.analysis_id, conn)
    assert loaded.outcome == "REFUSED_ADVICE" and loaded.tool_calls == []
    assert loaded.answer == machine.REFUSAL_ANSWERS["tr"]


# --- G3: an unusable intent ends as ANALYSIS_UNSAFE -----------------------------------
@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"ticker": "XYZAB"}, "UNKNOWN_TICKER"),  # not one of the 30 stocks
        ({"start": "2026-12-01", "end": "2027-01-15"}, "FUTURE_DATE"),
        ({"start": "2025-06-30", "end": "2025-01-02"}, "INVALID_DATE_RANGE"),
    ],
)
def test_unusable_intent_is_analysis_unsafe_and_recorded(over, reason, conn):
    client = ScriptedClient(intent(language="tr", **over))
    tools = FakeTools()
    analysis = machine.run_analysis(
        "Hisse nasıl gitti?", client, call_tool=tools, today=TODAY, conn=conn
    )
    assert tools.calls == [] and len(client.requests) == 1
    assert analysis.outcome == "ANALYSIS_UNSAFE"
    assert record_of(analysis, "START").detail["reason"] == reason
    assert analysis.answer == machine.UNSAFE_ANSWERS["tr"].format(reason=reason)
    assert visited(analysis) == list(GUARDED_ROUTE)
    loaded = session.load(analysis.analysis_id, conn)
    assert loaded.outcome == "ANALYSIS_UNSAFE"
    assert record_of(loaded, "START").detail["reason"] == reason


# --- G4: the right path, start to end ------------------------------------------------
PERIOD = {"start": "2025-01-02", "end": "2025-06-30"}


def price_summary_script():
    return (
        intent(),
        [
            call("get_stock_history", ticker="THYAO", **PERIOD),
            call("get_index_history", index="XU100", **PERIOD),
        ],
        [call("calculate_indicators", ticker="THYAO", indicators=[], **PERIOD)],
    )


def test_right_path_runs_the_route_and_records_every_call():
    client = ScriptedClient(*price_summary_script())
    tools = FakeTools()
    analysis = machine.run_analysis("How did THYAO do?", client, call_tool=tools, today=TODAY)
    aid = analysis.analysis_id
    assert [(c.seq, c.state, c.tool, c.source, c.allowed) for c in analysis.tool_calls] == [
        (1, "LOAD_MARKET_DATA", "get_stock_history", "model", True),
        (2, "LOAD_MARKET_DATA", "get_index_history", "model", True),
        (3, "CHECK_DATA_QUALITY", "check_data_quality", "harness", True),
        (4, "CALCULATE_TECHNICALS", "calculate_indicators", "model", True),
        (5, "BUILD_EVIDENCE", "build_evidence_bundle", "harness", True),
        (6, "RISK_GATE", "check_data_quality", "harness", True),
    ]
    assert tools.calls[2] == ("check_data_quality", {"analysis_id": aid})
    assert tools.calls[4] == ("build_evidence_bundle", {"analysis_id": aid})
    assert [c.result_id for c in analysis.tool_calls] == [
        f"{n}-{i}" for i, (n, _) in enumerate(tools.calls, 1)
    ]
    assert analysis.outcome == "INVESTIGATE" and analysis.gate_status == "PASS"
    assert analysis.state == "LOG_AND_CLOSE"
    assert machine.wrong_tool_calls(analysis) == 0
    assert machine.harness_interventions(analysis) == 0


def test_each_model_turn_offers_only_the_tools_of_its_state():
    client = ScriptedClient(*price_summary_script())
    machine.run_analysis("How did THYAO do?", client, call_tool=FakeTools(), today=TODAY)
    turns = client.tool_turns()
    # Harness-run states (CHECK_DATA_QUALITY, BUILD_EVIDENCE, RISK_GATE) have no model turn.
    assert len(client.requests) == 1 + len(turns) == 3
    for turn, state in zip(turns, ("LOAD_MARKET_DATA", "CALCULATE_TECHNICALS"), strict=True):
        offered = [t["function"]["name"] for t in turn["tools"]]
        assert offered == list(ALLOWED_TOOLS[state])
        assert (turn["temperature"], turn["seed"]) == (0.0, 42)
        prompt = " ".join(m["content"] for m in turn["messages"])
        assert state in prompt and "THYAO" in prompt and "2025-01-02" in prompt
        assert "How did THYAO do?" in prompt


def test_analysis_records_ids_versions_model_and_settings():
    client = ScriptedClient(*price_summary_script())
    analysis = machine.run_analysis("How did THYAO do?", client, call_tool=FakeTools(), today=TODAY)
    assert analysis.analysis_id.startswith("AN-")
    assert analysis.snapshot_id == "test-snapshot" and analysis.adjustments_id
    assert analysis.model == "fake-model"
    assert (analysis.temperature, analysis.seed) == (0.0, 42)
    assert analysis.intent["ticker"] == "THYAO" and analysis.intent["start"] == "2025-01-02"


def test_every_state_is_recorded_in_order():
    client = ScriptedClient(*price_summary_script())
    analysis = machine.run_analysis("How did THYAO do?", client, call_tool=FakeTools(), today=TODAY)
    assert [r.state for r in analysis.trail] == list(STATES)
    route = ROUTES["PRICE_SUMMARY"]
    for record in analysis.trail:
        assert record.status == ("RAN" if record.state in route else "NOT_APPLICABLE")
    assert visited(analysis) == list(route)
    market = record_of(analysis, "LOAD_MARKET_DATA").detail
    assert market == {"attempts": 1, "rejected": 0, "text_replies": 0, "fallback": False}
    # Task 7: the fake tools give no evidence, so the model is not asked and the answer is
    # the (empty) committed evidence set under INVESTIGATE.
    assert record_of(analysis, "GENERATE_EXPLANATION").detail == {
        "action": "INVESTIGATE",
        "eligible": ["INVESTIGATE"],
        "attempts": 0,
        "fallback": True,
        "problems": [],
    }


class StoreWatchingTools(FakeTools):
    """Notes how many calls the store holds each time a tool is called."""

    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.stored: list[int] = []

    def __call__(self, name, arguments):
        self.stored.append(self.conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0])
        return super().__call__(name, arguments)


def test_with_a_store_every_recorded_call_is_saved_at_once(conn):
    client = ScriptedClient(*price_summary_script())
    tools = StoreWatchingTools(conn)
    analysis = machine.run_analysis(
        "How did THYAO do?", client, call_tool=tools, today=TODAY, conn=conn
    )
    assert tools.stored == [0, 1, 2, 3, 4, 5]  # call n sees the n-1 calls before it
    loaded = session.load(analysis.analysis_id, conn)
    assert loaded.tool_calls == analysis.tool_calls
    assert loaded.trail == analysis.trail
    assert (loaded.outcome, loaded.gate_status) == ("INVESTIGATE", "PASS")


# --- G5: proposed calls are checked: schema, permission, intent ----------------------
def run_with_market_replies(*market_replies, max_attempts=2):
    """PRICE_SUMMARY for THYAO; the LOAD_MARKET_DATA turn gets ``market_replies``."""
    client = ScriptedClient(
        intent(),
        *market_replies,
        [call("calculate_indicators", ticker="THYAO", indicators=[], **PERIOD)],
    )
    tools = FakeTools()
    analysis = machine.run_analysis(
        "How did THYAO do?", client, call_tool=tools, today=TODAY, max_attempts=max_attempts
    )
    return analysis, client, tools


GOOD_MARKET_CALL = [call("get_stock_history", ticker="THYAO", **PERIOD)]


@pytest.mark.parametrize(
    "proposal",
    [
        call("run_backtest", strategy="A_TECHNICAL", universe=["THYAO"], **PERIOD),
        call("check_data_quality", analysis_id="AN-x"),  # a harness-only tool
    ],
)
def test_a_tool_outside_the_state_is_rejected_recorded_and_counted(proposal):
    analysis, client, tools = run_with_market_replies([proposal], GOOD_MARKET_CALL)
    first = analysis.tool_calls[0]
    assert (first.state, first.tool, first.allowed, first.source) == (
        "LOAD_MARKET_DATA",
        proposal.name,
        False,
        "model",
    )
    assert first.output["error"]["code"] == "TOOL_NOT_ALLOWED"
    assert (proposal.name, proposal.arguments) not in tools.calls  # never executed
    assert machine.wrong_tool_calls(analysis) == 1
    assert machine.harness_interventions(analysis) == 0
    feedback = client.tool_turns()[1]["messages"][-1]["content"]
    assert proposal.name in feedback and "not allowed" in feedback
    assert "get_stock_history" in feedback  # the model is told what it may call
    detail = record_of(analysis, "LOAD_MARKET_DATA").detail
    assert detail == {"attempts": 2, "rejected": 1, "text_replies": 0, "fallback": False}
    # The analysis goes on with the valid call.
    assert analysis.tool_calls[1].tool == "get_stock_history" and analysis.tool_calls[1].allowed
    assert analysis.outcome == "INVESTIGATE"


@pytest.mark.parametrize(
    "proposal",
    [
        call("get_stock_history", ticker="THYAO", start="2025-01-02"),  # end missing
        call("get_price", ticker="THYAO", **PERIOD),  # no such tool
        call("get_stock_history", ticker="THYAO", period="6mo", **PERIOD),
    ],
)
def test_a_call_that_breaks_the_schema_is_rejected(proposal):
    analysis, client, tools = run_with_market_replies([proposal], GOOD_MARKET_CALL)
    first = analysis.tool_calls[0]
    assert (first.tool, first.allowed) == (proposal.name, False)
    assert first.output["error"]["code"] == "INVALID_CALL"
    assert len(tools.calls) == len(analysis.tool_calls) - 1
    assert machine.wrong_tool_calls(analysis) == 1


@pytest.mark.parametrize(
    ("proposal", "hint"),
    [
        (call("get_stock_history", ticker="ASELS", **PERIOD), "ticker must be THYAO"),
        (
            call("get_stock_history", ticker="THYAO", start="2024-01-02", end="2025-06-30"),
            "start must be 2025-01-02",
        ),
        (
            call("get_stock_history", ticker="THYAO", start="2025-01-02", end="2025-12-31"),
            "end must be 2025-06-30",
        ),
    ],
)
def test_a_call_for_another_stock_or_period_is_rejected(proposal, hint):
    analysis, client, tools = run_with_market_replies([proposal], GOOD_MARKET_CALL)
    first = analysis.tool_calls[0]
    assert (first.tool, first.arguments, first.allowed) == (
        proposal.name,
        proposal.arguments,
        False,
    )
    assert first.output["error"]["code"] == "INTENT_MISMATCH"
    assert all(args != proposal.arguments for _, args in tools.calls)
    assert machine.wrong_tool_calls(analysis) == 1
    feedback = client.tool_turns()[1]["messages"][-1]["content"]
    assert hint in feedback  # the model is told the value the question asks for


def test_valid_and_invalid_calls_in_one_reply_are_judged_one_by_one():
    analysis, client, tools = run_with_market_replies(
        [
            call("get_stock_history", ticker="ASELS", **PERIOD),
            call("get_stock_history", ticker="thyao", **PERIOD),  # case is not a mismatch
        ]
    )
    market = [c for c in analysis.tool_calls if c.state == "LOAD_MARKET_DATA"]
    assert [(c.arguments["ticker"], c.allowed) for c in market] == [
        ("ASELS", False),
        ("thyao", True),
    ]
    assert record_of(analysis, "LOAD_MARKET_DATA").detail["attempts"] == 1


SECTOR_INTENT = machine.Intent(
    "SECTOR_LAGGARD", "THYAO", None, "2025-01-02", "2025-06-30", None, "en"
)
BANKING_INTENT = machine.Intent(
    "SECTOR_LAGGARD", None, "Banking", "2025-01-02", "2025-06-30", None, "en"
)


@pytest.mark.parametrize(
    ("intent_", "state", "name", "arguments", "expected"),
    [
        (
            SECTOR_INTENT,
            "LOAD_MARKET_DATA",
            "get_index_history",
            {"index": "XU100", **PERIOD},
            None,
        ),
        (
            SECTOR_INTENT,
            "RUN_SECTOR_RELATIVE_ANALYSIS",
            "rank_sector_relative_strength",
            {"sector": "Airlines / Transport", "horizon_days": 20, "as_of": "2025-06-30"},
            None,
        ),
        (
            SECTOR_INTENT,
            "RUN_SECTOR_RELATIVE_ANALYSIS",
            "rank_sector_relative_strength",
            {"sector": "Transportation / Airlines", "horizon_days": 60, "as_of": "2025-06-30"},
            None,
        ),
        (
            SECTOR_INTENT,
            "RUN_SECTOR_RELATIVE_ANALYSIS",
            "rank_sector_relative_strength",
            {"sector": "Banking", "horizon_days": 20, "as_of": "2025-06-30"},
            "INTENT_MISMATCH",
        ),
        (
            SECTOR_INTENT,
            "RUN_SECTOR_RELATIVE_ANALYSIS",
            "rank_sector_relative_strength",
            {"sector": "Airlines / Transport", "horizon_days": 20, "as_of": "2025-03-31"},
            "INTENT_MISMATCH",
        ),
        (
            SECTOR_INTENT,
            "RUN_SECTOR_RELATIVE_ANALYSIS",
            "rank_sector_relative_strength",
            {"sector": "Airlines / Transport", "horizon_days": 7, "as_of": "2025-06-30"},
            "INVALID_CALL",
        ),
        (
            SECTOR_INTENT,
            "RUN_BACKTEST",
            "run_backtest",
            {"strategy": "B_TECH_SECTOR", "universe": ["THYAO"], **PERIOD},
            None,
        ),
        (
            SECTOR_INTENT,
            "RUN_BACKTEST",
            "run_backtest",
            {"strategy": "B_TECH_SECTOR", "universe": [], **PERIOD},
            None,
        ),
        (
            SECTOR_INTENT,
            "RUN_BACKTEST",
            "run_backtest",
            {"strategy": "B_TECH_SECTOR", "universe": ["THYAO", "ASELS"], **PERIOD},
            "INTENT_MISMATCH",
        ),
        (
            SECTOR_INTENT,
            "RUN_SECTOR_RELATIVE_ANALYSIS",
            "calculate_indicators",
            {"ticker": "THYAO", "indicators": [], **PERIOD},
            "TOOL_NOT_ALLOWED",
        ),
        (
            BANKING_INTENT,
            "CALCULATE_TECHNICALS",
            "calculate_indicators",
            {"ticker": "AKBNK", "indicators": ["RSI"], **PERIOD},
            None,
        ),
        (
            BANKING_INTENT,
            "CALCULATE_TECHNICALS",
            "calculate_indicators",
            {"ticker": "ASELS", "indicators": ["RSI"], **PERIOD},
            "INTENT_MISMATCH",
        ),
        (
            BANKING_INTENT,
            "RUN_SECTOR_RELATIVE_ANALYSIS",
            "rank_sector_relative_strength",
            {"sector": "banking", "horizon_days": 20, "as_of": "2025-06-30"},
            None,
        ),
    ],
)
def test_call_check_rules(intent_, state, name, arguments, expected):
    problem = machine.check_call(state, name, arguments, intent_, analysis_id="AN-1")
    assert (problem[0] if problem else None) == expected
    if problem:
        assert problem[1]  # a short message for the model


# --- G6: a text answer is asked again, then the harness makes the call ---------------
CANONICAL_MARKET = [
    ("get_stock_history", {"ticker": "THYAO", **PERIOD}),
    ("get_index_history", {"index": "XU100", **PERIOD}),
]


def market_calls(analysis):
    return [c for c in analysis.tool_calls if c.state == "LOAD_MARKET_DATA"]


def test_text_twice_then_the_harness_makes_the_canonical_call():
    analysis, client, tools = run_with_market_replies(
        "THYAO rose 12% in this period.", "I think it went up."
    )
    market_turns = [t for t in client.tool_turns() if "LOAD_MARKET_DATA" in str(t["messages"])]
    assert len(market_turns) == 2  # asked once more, then no further model turn
    again = market_turns[1]["messages"][-1]
    assert again["role"] == "user" and "text answer is not accepted" in again["content"]
    assert "get_stock_history" in again["content"]
    assert [(c.tool, c.arguments, c.source, c.allowed) for c in market_calls(analysis)] == [
        (name, args, "harness", True) for name, args in CANONICAL_MARKET
    ]
    assert tools.calls[:2] == CANONICAL_MARKET
    detail = record_of(analysis, "LOAD_MARKET_DATA").detail
    assert detail == {"attempts": 2, "rejected": 0, "text_replies": 2, "fallback": True}
    assert machine.harness_interventions(analysis) == 2
    assert machine.wrong_tool_calls(analysis) == 0
    assert analysis.outcome == "INVESTIGATE"  # the analysis goes on


@pytest.mark.parametrize("max_attempts", [1, 3])
def test_max_attempts_bounds_the_model_turns(max_attempts):
    texts = ["no call"] * max_attempts
    analysis, client, tools = run_with_market_replies(*texts, max_attempts=max_attempts)
    detail = record_of(analysis, "LOAD_MARKET_DATA").detail
    assert detail["attempts"] == detail["text_replies"] == max_attempts
    assert detail["fallback"] is True
    assert [c.source for c in market_calls(analysis)] == ["harness", "harness"]


def test_rejected_calls_on_every_attempt_also_end_in_the_fallback():
    wrong = [call("get_stock_history", ticker="ASELS", **PERIOD)]
    analysis, client, tools = run_with_market_replies(wrong, wrong)
    assert [(c.arguments.get("ticker"), c.allowed, c.source) for c in market_calls(analysis)] == [
        ("ASELS", False, "model"),
        ("ASELS", False, "model"),
        ("THYAO", True, "harness"),
        (None, True, "harness"),
    ]
    assert machine.wrong_tool_calls(analysis) == 2
    assert machine.harness_interventions(analysis) == 2


def test_a_malformed_call_is_recorded_as_a_wrong_call_and_asked_again():
    analysis, client, tools = run_with_market_replies(MALFORMED, GOOD_MARKET_CALL)
    first = analysis.tool_calls[0]
    assert (first.tool, first.allowed, first.source) == ("(malformed)", False, "model")
    assert first.output["error"]["code"] == "MALFORMED_CALL"
    assert machine.wrong_tool_calls(analysis) == 1
    feedback = client.tool_turns()[1]["messages"][-1]["content"]
    assert "could not be parsed" in feedback
    assert analysis.tool_calls[1].tool == "get_stock_history"
    assert record_of(analysis, "LOAD_MARKET_DATA").detail["fallback"] is False


def make_intent(scenario, **over):
    base = {
        "scenario": scenario,
        "ticker": "THYAO",
        "sector": None,
        "start": "2025-01-02",
        "end": "2025-06-30",
        "as_of": None,
        "language": "en",
    }
    base.update(over)
    return machine.Intent(**base)


ANALYSIS_SCENARIOS = [s for s, route in ROUTES.items() if route != GUARDED_ROUTE]


@pytest.mark.parametrize("scenario", ANALYSIS_SCENARIOS)
@pytest.mark.parametrize("over", [{}, {"ticker": None, "sector": "Banking"}])
def test_canonical_calls_always_pass_the_call_check(scenario, over):
    intent_ = make_intent(scenario, **over)
    for state in ROUTES[scenario]:
        if not ALLOWED_TOOLS[state] or state in machine.HARNESS_STATES:
            continue
        for name, arguments in machine.canonical_calls(state, intent_):
            assert machine.check_call(state, name, arguments, intent_, analysis_id="AN-1") is None


def test_canonical_calls_follow_the_intent():
    sector = make_intent("SECTOR_LAGGARD")
    assert machine.canonical_calls("RUN_SECTOR_RELATIVE_ANALYSIS", sector) == [
        (
            "rank_sector_relative_strength",
            {"sector": "Airlines / Transport", "horizon_days": 20, "as_of": "2025-06-30"},
        )
    ]
    assert machine.canonical_calls("RUN_BACKTEST", sector) == [
        ("run_backtest", {"strategy": "B_TECH_SECTOR", "universe": ["THYAO"], **PERIOD})
    ]
    calendar = make_intent("CALENDAR_PATTERN")
    assert machine.canonical_calls("RUN_PATTERN_AND_REVERSAL_ANALYSIS", calendar) == [
        ("test_weekday_pattern", {"ticker": "THYAO", "pattern": "WEEKDAY_MEANS", **PERIOD})
    ]
    reversal = make_intent("TECHNICAL_REVERSAL", as_of="2025-05-30")
    assert machine.canonical_calls("LOAD_FUNDAMENTALS", reversal) == [
        ("get_fundamental_metrics", {"ticker": "THYAO", "as_of": "2025-05-30"}),
        ("calculate_fundamental_change", {"ticker": "THYAO", "as_of": "2025-05-30"}),
    ]
    banking = make_intent("SECTOR_LAGGARD", ticker=None, sector="Banking")
    assert machine.canonical_calls("LOAD_MARKET_DATA", banking) == [
        ("get_index_history", {"index": "XU100", **PERIOD})
    ]


# --- G7: the states run in the order of the route ------------------------------------
class TextOnlyClient(ScriptedClient):
    """Gives the intent, then answers every tool turn with text (the worst model)."""

    def __init__(self, intent_json):
        super().__init__(intent_json)

    def chat(self, messages, tools=None, **kwargs):
        if tools and not self.script:
            self.requests.append(
                {"messages": [dict(m) for m in messages], "tools": tools, **kwargs}
            )
            return reply("The stock looks fine.")
        return super().chat(messages, tools, **kwargs)


def state_of_turn(turn) -> str:
    return next(s for s in STATES if f"Current state: {s}." in turn["messages"][0]["content"])


@pytest.mark.parametrize("scenario", ANALYSIS_SCENARIOS)
@pytest.mark.parametrize("over", [{}, {"ticker": None, "sector": "Banking"}])
def test_state_order_is_the_route(scenario, over):
    client = TextOnlyClient(intent(scenario=scenario, **over))
    tools = FakeTools()
    analysis = machine.run_analysis("q", client, call_tool=tools, today=TODAY)
    route = ROUTES[scenario]
    assert [r.state for r in analysis.trail] == list(STATES)  # every state has a record
    assert visited(analysis) == list(route)
    assert all(r.status == "RAN" for r in analysis.trail if r.state in route)
    # Tool calls happen in route order and only in route states.
    positions = [route.index(c.state) for c in analysis.tool_calls]
    assert positions == sorted(positions)
    # Model turns: only the tool states of the route, each asked max_attempts (2) times.
    model_states = [s for s in route if ALLOWED_TOOLS[s] and s not in machine.HARNESS_STATES]
    assert [state_of_turn(t) for t in client.tool_turns()] == [
        s for s in model_states for _ in range(2)
    ]
    for turn in client.tool_turns():
        offered = [t["function"]["name"] for t in turn["tools"]]
        assert offered == list(ALLOWED_TOOLS[state_of_turn(turn)])
    # The mandatory quality checks always ran, by the harness.
    harness = [(c.state, c.tool, c.source) for c in analysis.tool_calls]
    assert ("CHECK_DATA_QUALITY", "check_data_quality", "harness") in harness
    assert ("RISK_GATE", "check_data_quality", "harness") in harness


def test_candidate_route_previews_the_variants_before_the_backtest():
    client = TextOnlyClient(intent(scenario="SECTOR_LAGGARD"))
    analysis = machine.run_analysis("q", client, call_tool=FakeTools(), today=TODAY)
    assert record_of(analysis, "PREVIEW_STRATEGIES").detail == {
        "variants": [
            "A_TECHNICAL",
            "B_TECH_SECTOR",
            "C_TECH_SECTOR_FUND",
            "D_FULL_STRUCTURED",
            "E_FULL_CONTEXTUAL",
        ]
    }
    backtest_turn = next(t for t in client.tool_turns() if state_of_turn(t) == "RUN_BACKTEST")
    assert "B_TECH_SECTOR" in backtest_turn["messages"][0]["content"]
    backtests = [c for c in analysis.tool_calls if c.tool == "run_backtest"]
    assert [(c.state, c.source) for c in backtests] == [("RUN_BACKTEST", "harness")]


# --- G8: the gate decides; HARD_BLOCK skips the explanation --------------------------
class Spy:
    def __init__(self, result=None):
        self.result = result
        self.calls: list[tuple] = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def test_hard_block_skips_the_explanation_and_ends_unsafe(conn):
    client = ScriptedClient(*price_summary_script())
    explain = Spy()
    analysis = machine.run_analysis(
        "How did THYAO do?",
        client,
        call_tool=FakeTools(quality="HARD_BLOCK"),
        today=TODAY,
        conn=conn,
        explain_fn=explain,
    )
    assert explain.calls == []
    assert record_of(analysis, "GENERATE_EXPLANATION").status == "SKIPPED"
    assert record_of(analysis, "GENERATE_EXPLANATION").detail == {"reason": "HARD_BLOCK"}
    assert (analysis.outcome, analysis.gate_status) == ("ANALYSIS_UNSAFE", "HARD_BLOCK")
    assert record_of(analysis, "HUMAN_REVIEW").status == "RAN"
    assert record_of(analysis, "LOG_AND_CLOSE").detail == {"outcome": "ANALYSIS_UNSAFE"}
    assert len(client.requests) == 3  # no explanation turn
    loaded = session.load(analysis.analysis_id, conn)
    assert (loaded.outcome, loaded.gate_status) == ("ANALYSIS_UNSAFE", "HARD_BLOCK")


def test_warnings_do_not_block_the_explanation():
    explain = Spy()
    analysis = machine.run_analysis(
        "How did THYAO do?",
        ScriptedClient(*price_summary_script()),
        call_tool=FakeTools(quality="PASS_WITH_WARNINGS"),
        today=TODAY,
        explain_fn=explain,
    )
    assert len(explain.calls) == 1
    assert analysis.gate_status == "PASS_WITH_WARNINGS" and analysis.outcome == "COMPLETED"


def test_hooks_receive_the_analysis_evidence_and_gate():
    client = ScriptedClient(*price_summary_script())
    evidence = ("E1", "E2")
    gate_result = SimpleNamespace(status="PASS", hard_blocks=())
    evidence_fn = Spy(evidence)
    gate_fn = Spy(gate_result)
    explain_fn = Spy(SimpleNamespace(action="WATCH"))
    analysis = machine.run_analysis(
        "How did THYAO do?",
        client,
        call_tool=FakeTools(),
        today=TODAY,
        evidence_fn=evidence_fn,
        gate_fn=gate_fn,
        explain_fn=explain_fn,
    )
    # BUILD_EVIDENCE, then the rebuild at RISK_GATE (Task 6): one call each.
    assert evidence_fn.calls == [((analysis,), {"language": "en"})] * 2
    assert gate_fn.calls == [((analysis, evidence), {})]
    assert explain_fn.calls == [((analysis, client, evidence, gate_result), {})]
    assert analysis.outcome == "WATCH"
    assert record_of(analysis, "GENERATE_EXPLANATION").detail == {"action": "WATCH"}


def test_hooks_run_after_the_call_of_their_state():
    seen = {}

    def evidence_fn(analysis, *, language):
        seen.setdefault("evidence", [c.tool for c in analysis.tool_calls][-1])  # first call
        return ()

    def gate_fn(analysis, evidence):
        seen["gate"] = [(c.state, c.tool) for c in analysis.tool_calls][-1]
        return SimpleNamespace(status="PASS")

    machine.run_analysis(
        "How did THYAO do?",
        ScriptedClient(*price_summary_script()),
        call_tool=FakeTools(),
        today=TODAY,
        evidence_fn=evidence_fn,
        gate_fn=gate_fn,
    )
    assert seen == {
        "evidence": "build_evidence_bundle",
        "gate": ("RISK_GATE", "check_data_quality"),
    }


def test_the_gate_hook_overrules_a_passing_quality_tool():
    analysis = machine.run_analysis(
        "How did THYAO do?",
        ScriptedClient(*price_summary_script()),
        call_tool=FakeTools(quality="PASS"),
        today=TODAY,
        gate_fn=Spy(SimpleNamespace(status="HARD_BLOCK")),
    )
    assert analysis.outcome == "ANALYSIS_UNSAFE"
    assert record_of(analysis, "GENERATE_EXPLANATION").status == "SKIPPED"


def test_default_gate_blocks_when_the_quality_check_gives_no_status():
    class BrokenQuality(FakeTools):
        def __call__(self, name, arguments):
            if name == "check_data_quality":
                self.calls.append((name, arguments))
                return {"error": {"code": "UNKNOWN_ANALYSIS", "message": "?"}}
            return super().__call__(name, arguments)

    analysis = machine.run_analysis(
        "How did THYAO do?",
        ScriptedClient(*price_summary_script()),
        call_tool=BrokenQuality(),
        today=TODAY,
    )
    assert analysis.gate_status == "HARD_BLOCK" and analysis.outcome == "ANALYSIS_UNSAFE"


def test_a_raising_tool_is_recorded_as_an_error():
    class Raising(FakeTools):
        def __call__(self, name, arguments):
            if name == "get_stock_history":
                raise OSError("disk gone")
            return super().__call__(name, arguments)

    analysis = machine.run_analysis(
        "How did THYAO do?",
        ScriptedClient(*price_summary_script()),
        call_tool=Raising(),
        today=TODAY,
    )
    first = analysis.tool_calls[0]
    assert first.allowed and first.output["error"]["code"] == "TOOL_FAILED"
    assert "disk gone" in first.output["error"]["message"]


# --- Fix round 1: the model server fails mid-run -------------------------------------
PRIVATE_HOST = "gpu-box.internal"
PRIVATE_IP = "10.1.2.3"


class FailingClient(ScriptedClient):
    """Answers like ScriptedClient, but raises ``error`` on its ``fail_on``-th call."""

    def __init__(self, fail_on, error, *script):
        super().__init__(*script)
        self.fail_on = fail_on
        self.error = error

    def chat(self, messages, tools=None, **kwargs):
        if len(self.requests) + 1 == self.fail_on:
            self.requests.append({"messages": messages, "tools": tools, **kwargs})
            raise self.error
        return super().chat(messages, tools, **kwargs)


def unreachable():
    return LLMUnavailableError(
        f"cannot reach the LLM endpoint at http://{PRIVATE_HOST}:11434/api/chat (ConnectError)"
    )


def test_model_failure_in_a_tool_state_ends_with_an_outcome(conn):
    client = FailingClient(2, unreachable(), *price_summary_script())
    explain = Spy()
    analysis = machine.run_analysis(
        "How did THYAO do?",
        client,
        call_tool=FakeTools(),
        today=TODAY,
        conn=conn,
        explain_fn=explain,
    )
    assert analysis.outcome == "MODEL_UNAVAILABLE"
    assert analysis.answer == machine.MODEL_UNAVAILABLE_ANSWERS["en"]
    failed = record_of(analysis, "LOAD_MARKET_DATA")
    assert failed.status == "FAILED"
    assert failed.detail["error"] == "LLMUnavailableError"
    assert "cannot reach the LLM endpoint" in failed.detail["message"]
    # No further model turn; the remaining model states are skipped.
    assert len(client.requests) == 2 and explain.calls == []
    assert record_of(analysis, "CALCULATE_TECHNICALS").status == "SKIPPED"
    assert record_of(analysis, "CALCULATE_TECHNICALS").detail == {"reason": "MODEL_UNAVAILABLE"}
    assert record_of(analysis, "GENERATE_EXPLANATION").detail == {"reason": "MODEL_UNAVAILABLE"}
    # The states the harness runs itself still run.
    assert [(c.state, c.tool, c.source) for c in analysis.tool_calls] == [
        ("CHECK_DATA_QUALITY", "check_data_quality", "harness"),
        ("BUILD_EVIDENCE", "build_evidence_bundle", "harness"),
        ("RISK_GATE", "check_data_quality", "harness"),
    ]
    assert analysis.gate_status == "PASS"
    assert record_of(analysis, "HUMAN_REVIEW").status == "RAN"
    assert visited(analysis) == list(ROUTES["PRICE_SUMMARY"])
    loaded = session.load(analysis.analysis_id, conn)
    assert loaded.outcome == "MODEL_UNAVAILABLE" and loaded.trail == analysis.trail


def test_calls_made_before_the_failure_are_kept():
    client = FailingClient(3, unreachable(), *price_summary_script())
    analysis = machine.run_analysis("How did THYAO do?", client, call_tool=FakeTools(), today=TODAY)
    assert [c.tool for c in analysis.tool_calls][:2] == ["get_stock_history", "get_index_history"]
    assert record_of(analysis, "LOAD_MARKET_DATA").status == "RAN"
    assert record_of(analysis, "CALCULATE_TECHNICALS").status == "FAILED"
    assert analysis.outcome == "MODEL_UNAVAILABLE"


def test_model_failure_at_the_intent_ends_before_any_tool(conn):
    client = FailingClient(1, httpx.ReadTimeout("timed out"))
    tools = FakeTools()
    analysis = machine.run_analysis(
        "THYAO nasıl gitti?", client, call_tool=tools, today=TODAY, conn=conn
    )
    assert tools.calls == [] and analysis.intent is None
    assert analysis.outcome == "MODEL_UNAVAILABLE"
    assert analysis.answer == machine.MODEL_UNAVAILABLE_ANSWERS["tr"]
    assert record_of(analysis, "START").status == "FAILED"
    assert record_of(analysis, "START").detail["error"] == "ReadTimeout"
    assert visited(analysis) == list(GUARDED_ROUTE)
    assert session.load(analysis.analysis_id, conn).outcome == "MODEL_UNAVAILABLE"


def test_model_failure_in_the_explanation_ends_with_an_outcome():
    def explain_fn(analysis, client, evidence, gate):
        raise unreachable()

    analysis = machine.run_analysis(
        "How did THYAO do?",
        ScriptedClient(*price_summary_script()),
        call_tool=FakeTools(),
        today=TODAY,
        explain_fn=explain_fn,
    )
    assert analysis.outcome == "MODEL_UNAVAILABLE"
    assert record_of(analysis, "GENERATE_EXPLANATION").status == "FAILED"


@pytest.mark.parametrize(
    "error",
    [
        unreachable(),
        httpx.ConnectError(f"[Errno 111] refused: http://{PRIVATE_IP}:11434/api/chat"),
        LLMUnavailableError(f"proxy {PRIVATE_IP}:11434 and {PRIVATE_HOST}:8080 said no"),
    ],
)
def test_the_server_address_is_never_recorded(error, conn):
    client = FailingClient(2, error, *price_summary_script())
    analysis = machine.run_analysis(
        "How did THYAO do?", client, call_tool=FakeTools(), today=TODAY, conn=conn
    )
    assert analysis.outcome == "MODEL_UNAVAILABLE"
    stored = json.dumps(
        [
            conn.execute("SELECT * FROM analyses").fetchall(),
            conn.execute("SELECT * FROM tool_calls").fetchall(),
        ]
    )
    for secret in (PRIVATE_HOST, PRIVATE_IP, "11434", "8080", "http://"):
        assert secret not in stored
        assert secret not in json.dumps([r.detail for r in analysis.trail])


def test_a_programming_error_in_the_client_is_not_swallowed():
    client = FailingClient(2, KeyError("bug"), *price_summary_script())
    with pytest.raises(KeyError):
        machine.run_analysis("How did THYAO do?", client, call_tool=FakeTools(), today=TODAY)


# --- Task 6: the final evidence feeds the gate; the default gate is the quality gate ------
def test_the_evidence_is_rebuilt_at_the_risk_gate_from_all_calls_so_far():
    seen = []

    def evidence_fn(analysis, *, language):
        seen.append([(c.state, c.tool) for c in analysis.tool_calls][-1])
        return (f"E-{len(seen)}",)

    gate_fn = Spy(SimpleNamespace(status="PASS", hard_blocks=()))
    explain_fn = Spy(SimpleNamespace(action="WATCH"))
    machine.run_analysis(
        "How did THYAO do?",
        ScriptedClient(*price_summary_script()),
        call_tool=FakeTools(),
        today=TODAY,
        evidence_fn=evidence_fn,
        gate_fn=gate_fn,
        explain_fn=explain_fn,
    )
    assert seen == [
        ("BUILD_EVIDENCE", "build_evidence_bundle"),
        ("RISK_GATE", "check_data_quality"),
    ]
    assert gate_fn.calls[0][0][1] == ("E-2",)  # the gate sees the final set
    assert explain_fn.calls[0][0][2] == ("E-2",)  # and so does the explanation


def test_the_default_gate_is_the_quality_gate():
    class EmptyHistory(FakeTools):
        def __call__(self, name, arguments):
            output = super().__call__(name, arguments)
            if name == "get_stock_history":
                output["rows"] = 0
            return output

    explain = Spy()
    analysis = machine.run_analysis(
        "How did THYAO do?",
        ScriptedClient(*price_summary_script()),
        call_tool=EmptyHistory(),
        today=TODAY,
        explain_fn=explain,
    )
    assert analysis.gate_status == "HARD_BLOCK" and analysis.outcome == "ANALYSIS_UNSAFE"
    assert explain.calls == []


def test_the_default_gate_warns_without_blocking():
    class Warned(FakeTools):
        def __call__(self, name, arguments):
            output = super().__call__(name, arguments)
            if name == "calculate_indicators":
                output["sample_warning"] = "few events"
            return output

    analysis = machine.run_analysis(
        "How did THYAO do?",
        ScriptedClient(*price_summary_script()),
        call_tool=Warned(),
        today=TODAY,
    )
    assert analysis.gate_status == "PASS_WITH_WARNINGS" and analysis.outcome == "INVESTIGATE"


def test_run_analysis_records_its_today(conn):
    client = ScriptedClient(intent(scenario="ADVICE_REQUEST"))
    analysis = machine.run_analysis(
        "Should I buy THYAO?", client, call_tool=FakeTools(), today=TODAY, conn=conn
    )
    assert analysis.today == TODAY
    assert session.load(analysis.analysis_id, conn).today == TODAY
