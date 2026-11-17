"""The state machine against the real MCP tool functions on the seeded golden snapshot.

``test_machine.py`` uses fake tools; these tests cross the seam between the machine, the
server's quality tool and the gate. The model is a scripted fake client; the data is the
synthetic snapshot of ``tests/golden_snapshot.py``, never the real data folder.
"""

from __future__ import annotations

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
