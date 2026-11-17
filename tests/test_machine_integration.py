"""The state machine against the real MCP tool functions on the seeded golden snapshot.

``test_machine.py`` uses fake tools; these tests cross the seam between the machine, the
server's quality tool and the gate. The model is a scripted fake client; the data is the
synthetic snapshot of ``tests/golden_snapshot.py``, never the real data folder.
"""

from __future__ import annotations

import dataclasses

import pytest

from bist_harness.data import macro as macro_data
from bist_harness.data import snapshot as snapshot_module
from bist_harness.harness import machine, session
from bist_harness.mcp_server import server as srv

from .golden_snapshot import build_golden_snapshot
from .test_machine import ScriptedClient, call, intent

TODAY = "2026-11-17"
PERIOD = {"start": "2025-01-02", "end": "2025-06-30"}
QUESTION = "How did ASELS trade from 2025-01-02 to 2025-06-30?"


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


def no_explanation(analysis, client, evidence, gate):
    return None


def run(*script, **kwargs):
    return machine.run_analysis(
        script[0],
        ScriptedClient(*script[1:]),
        call_tool=real_tools,
        today=TODAY,
        explain_fn=kwargs.pop("explain_fn", no_explanation),
        **kwargs,
    )


# --- C1: a rejected call never reaches the quality check -----------------------------
def test_a_rejected_bad_date_call_does_not_block_a_valid_analysis():
    analysis = run(
        QUESTION,
        intent(ticker="ASELS", **PERIOD),
        [call("get_stock_history", ticker="ASELS", **PERIOD)],
        # rejected (not an ISO date), then a valid call
        [call("calculate_indicators", ticker="ASELS", start=PERIOD["start"], end="son ceyrek")],
        [call("calculate_indicators", ticker="ASELS", **PERIOD, indicators=[])],
    )
    rejected = [c for c in analysis.tool_calls if not c.allowed]
    assert [c.arguments.get("end") for c in rejected] == ["son ceyrek"]
    quality = [c for c in analysis.tool_calls if c.tool == "check_data_quality"]
    assert len(quality) == 2 and all(c.output["status"] != "HARD_BLOCK" for c in quality)
    assert all(row["as_of"] != "son ceyrek" for c in quality for row in c.output["checked"])
    assert analysis.gate_status != "HARD_BLOCK"
    assert analysis.outcome != machine.ANALYSIS_UNSAFE


def test_a_rejected_call_before_the_data_starts_adds_no_finding():
    early = {"start": "2010-01-04", "end": "2010-06-30"}
    analysis = run(
        QUESTION,
        intent(ticker="ASELS", **PERIOD),
        # rejected: the dates disagree with the intent (never executed)
        [call("get_stock_history", ticker="ASELS", **early)],
        [call("get_stock_history", ticker="ASELS", **PERIOD)],
        [call("calculate_indicators", ticker="ASELS", **PERIOD, indicators=[])],
    )
    quality = [c for c in analysis.tool_calls if c.tool == "check_data_quality"]
    for check in quality:
        assert all(row["as_of"] != early["end"] for row in check.output["checked"])
        assert all(f["code"] != "EMPTY_SERIES" for f in check.output["findings"])
    assert analysis.outcome != machine.ANALYSIS_UNSAFE


# --- I1: the harness tops up the scenario's minimum evidence -------------------------
FR_PERIOD = {"start": "2025-05-02", "end": "2025-11-10"}
FR_QUESTION = "How did TUPRS's price react to its quarterly results from 2025-05-02 to 2025-11-10?"


def harness_calls(analysis, state):
    return [
        (c.tool, c.arguments)
        for c in analysis.tool_calls
        if c.state == state and c.source == "harness" and c.allowed
    ]


def model_calls(analysis, state):
    return [
        (c.tool, c.arguments)
        for c in analysis.tool_calls
        if c.state == state and c.source == "model" and c.allowed
    ]


def test_one_partial_call_per_state_is_topped_up_to_the_minimum_evidence():
    from bist_harness.eval import metrics
    from bist_harness.harness.evidence import build_evidence, missing_requirements

    analysis = run(
        FR_QUESTION,
        intent(scenario="FUNDAMENTAL_REACTION", ticker="TUPRS", **FR_PERIOD),
        [call("get_stock_history", ticker="TUPRS", **FR_PERIOD)],
        [call("calculate_indicators", ticker="TUPRS", **FR_PERIOD, indicators=["BOLLINGER"])],
        [call("get_fundamental_metrics", ticker="TUPRS", as_of=FR_PERIOD["end"])],
        [call("run_backtest", strategy="C_TECH_SECTOR_FUND", universe=["TUPRS"], **FR_PERIOD)],
    )
    # the model's valid calls are kept
    assert model_calls(analysis, "CALCULATE_TECHNICALS") == [
        ("calculate_indicators", {"ticker": "TUPRS", **FR_PERIOD, "indicators": ["BOLLINGER"]})
    ]
    assert model_calls(analysis, "LOAD_FUNDAMENTALS") == [
        ("get_fundamental_metrics", {"ticker": "TUPRS", "as_of": FR_PERIOD["end"]})
    ]
    # the harness adds what the minimum evidence still needs, and nothing else
    assert harness_calls(analysis, "CALCULATE_TECHNICALS") == [
        ("calculate_indicators", {"ticker": "TUPRS", **FR_PERIOD, "indicators": []})
    ]
    assert harness_calls(analysis, "LOAD_FUNDAMENTALS") == [
        ("calculate_fundamental_change", {"ticker": "TUPRS", "as_of": FR_PERIOD["end"]})
    ]
    assert harness_calls(analysis, "LOAD_MARKET_DATA") == []  # the price call is enough
    assert harness_calls(analysis, "RUN_BACKTEST") == []
    missing = missing_requirements(build_evidence(analysis, language="en"), "FUNDAMENTAL_REACTION")
    assert missing == []
    # counted as interventions, by the machine and by the evaluation metrics
    assert machine.harness_interventions(analysis) == 2
    record = {
        "tool_calls": [dataclasses.asdict(c) for c in analysis.tool_calls],
        "trail": [dataclasses.asdict(r) for r in analysis.trail],
    }
    assert metrics.harness_interventions(record) == 2
    detail = next(r.detail for r in analysis.trail if r.state == "LOAD_FUNDAMENTALS")
    assert detail["fallback"] is False and detail["topped_up"] == ["calculate_fundamental_change"]


def test_a_complete_model_call_needs_no_top_up():
    analysis = run(
        QUESTION,
        intent(ticker="ASELS", **PERIOD),
        [call("get_stock_history", ticker="ASELS", **PERIOD)],
        [call("calculate_indicators", ticker="ASELS", **PERIOD, indicators=["RSI"])],
    )
    assert [c.source for c in analysis.tool_calls if c.state not in machine.HARNESS_STATES] == [
        "model",
        "model",
    ]
    assert machine.harness_interventions(analysis) == 0
