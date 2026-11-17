"""Replay: re-run the recorded allowed tool calls on the same snapshot, never the model.

``call_tool`` and the verify function are injected; no real data or model is involved.
"""

import pytest

from bist_harness.harness import replay, session


@pytest.fixture(autouse=True)
def fixed_versions(monkeypatch, tmp_path):
    monkeypatch.setattr(session, "_versions", lambda: ("SNAP-1", "ADJ-1"))
    monkeypatch.setattr(session, "_store_path", lambda: tmp_path / "default-store.sqlite")


def make_analysis(today="2026-11-17"):
    analysis = session.new_analysis("THYAO last year?", model="m")
    analysis.today = today
    add = lambda state, tool, args, rid, **kw: session.record_call(  # noqa: E731
        analysis, state=state, tool=tool, arguments=args, output={"result_id": rid}, **kw
    )
    add("LOAD_MARKET_DATA", "get_stock_history", {"ticker": "THYAO"}, "r1")
    add("LOAD_MARKET_DATA", "get_index_history", {"index": "XU100"}, "r2", source="harness")
    session.record_call(
        analysis,
        state="CALCULATE_TECHNICALS",
        tool="calculate_indicators",
        arguments={"ticker": "THYAO"},
        output={"error": {"code": "INVALID_CALL"}},
        allowed=False,
    )
    return analysis


class Tools:
    def __init__(self, changed=(), boom=()):
        self.calls, self.changed, self.boom = [], set(changed), set(boom)

    def __call__(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if name in self.boom:
            raise RuntimeError("tool down")
        rid = {"get_stock_history": "r1", "get_index_history": "r2"}[name]
        return {"result_id": rid + "x" if name in self.changed else rid}


def ok_verify(snapshot_id):
    return []


def run(analysis, tools=None, verify=ok_verify, current="SNAP-1"):
    tools = tools or Tools()
    return replay.replay(
        analysis, call_tool=tools, verify=verify, current_snapshot_id=lambda: current
    ), tools


def test_match_replays_allowed_calls_with_the_same_arguments():
    result, tools = run(make_analysis())
    assert result.status == "MATCH" and result.differences == []
    assert tools.calls == [
        ("get_stock_history", {"ticker": "THYAO"}),
        ("get_index_history", {"index": "XU100"}),  # harness-made calls replay too
    ]  # the rejected call is not replayed
    assert result.replayed == 2 and result.today == "2026-11-17"
    assert result.snapshot_id == "SNAP-1"


def test_a_changed_result_id_is_a_mismatch_naming_the_call():
    result, _ = run(make_analysis(), Tools(changed=["get_index_history"]))
    assert result.status == "MISMATCH"
    (diff,) = result.differences
    assert (diff.seq, diff.tool, diff.recorded, diff.new) == (2, "get_index_history", "r2", "r2x")
    assert diff.reason == "changed output"


def test_snapshot_verify_failure_is_a_mismatch_even_when_ids_match():
    result, _ = run(make_analysis(), verify=lambda sid: ["THYAO: content changed"])
    assert result.status == "MISMATCH"
    assert result.snapshot_problems == ["THYAO: content changed"]


def test_verify_failure_is_the_reason_of_a_differing_call():
    result, _ = run(
        make_analysis(), Tools(changed=["get_stock_history"]), verify=lambda s: ["X: file missing"]
    )
    assert result.differences[0].reason == "snapshot verify failed"


def test_a_different_active_snapshot_is_a_mismatch():
    result, _ = run(make_analysis(), Tools(changed=["get_stock_history"]), current="SNAP-2")
    assert result.status == "MISMATCH" and result.current_snapshot_id == "SNAP-2"
    assert result.differences[0].reason == "different snapshot"


def test_different_snapshot_alone_is_a_mismatch():
    result, _ = run(make_analysis(), current="SNAP-2")
    assert result.status == "MISMATCH" and result.differences == []


def test_a_failing_tool_is_a_difference_not_a_crash():
    result, _ = run(make_analysis(), Tools(boom=["get_stock_history"]))
    assert result.status == "MISMATCH"
    assert result.differences[0].new is None
    assert "tool down" in result.differences[0].reason


def test_analysis_dependent_calls_see_the_analysis_as_it_was_then():
    analysis = make_analysis()
    session.record_call(
        analysis,
        state="BUILD_EVIDENCE",
        tool="build_evidence_bundle",
        arguments={"analysis_id": analysis.analysis_id},
        output={"result_id": "b1"},
        source="harness",
    )
    session.record_call(
        analysis,
        state="RISK_GATE",
        tool="get_stock_history",
        arguments={"ticker": "X"},
        output={"result_id": "r1"},
    )
    seen = []

    def tools(name, arguments):
        if name == "build_evidence_bundle":
            seen.append(len(session.resolve(arguments["analysis_id"]).tool_calls))
            return {"result_id": "b1"}
        return {"result_id": "r1" if name == "get_stock_history" else "r2"}

    result = replay.replay(
        analysis, call_tool=tools, verify=ok_verify, current_snapshot_id=lambda: "SNAP-1"
    )
    assert seen == [3]  # calls 1..3 existed when seq 4 ran (the rejected one counts)
    assert result.status == "MATCH"
    assert session.resolve(analysis.analysis_id) is analysis  # restored afterwards


# --- the command line ----------------------------------------------------------------
@pytest.fixture
def stored(tmp_path):
    from bist_harness.storage import db

    analysis = make_analysis()
    conn = db.connect(tmp_path / "default-store.sqlite")
    session.save(analysis, conn)
    conn.close()
    return analysis


def patch_replay(monkeypatch, tools):
    real = replay.replay
    monkeypatch.setattr(
        replay,
        "replay",
        lambda a: real(a, call_tool=tools, verify=ok_verify, current_snapshot_id=lambda: "SNAP-1"),
    )


def test_cli_prints_match_and_exits_zero(stored, monkeypatch, capsys):
    patch_replay(monkeypatch, Tools())
    assert replay.main([stored.analysis_id]) == 0
    out = capsys.readouterr().out
    assert out.startswith("MATCH") and "2026-11-17" in out


def test_cli_prints_the_differing_call_and_exits_nonzero(stored, monkeypatch, capsys):
    patch_replay(monkeypatch, Tools(changed=["get_index_history"]))
    assert replay.main([stored.analysis_id]) == 1
    out = capsys.readouterr().out
    assert out.startswith("MISMATCH")
    assert "call 2 get_index_history: recorded r2, now r2x (changed output)" in out


def test_cli_unknown_analysis_is_a_clear_error(stored, capsys):
    assert replay.main(["AN-nope"]) != 0
    assert "unknown analysis" in capsys.readouterr().err
