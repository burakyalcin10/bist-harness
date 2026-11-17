"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

Replay (design spec section 10, card EC-048): re-run a recorded analysis and check that it
gives the same results. The recorded allowed tool calls run again with the same arguments;
the model is never called. The replay is a ``MATCH`` only when

* ``snapshot verify`` (layer seal included) passes for the recorded snapshot,
* the active snapshot is still the recorded one, and
* every call's new ``result_id`` equals the recorded one.

Otherwise it is a ``MISMATCH`` and says which calls differ and why. A tool that reads the
analysis itself (``check_data_quality``, ``build_evidence_bundle``) is replayed against the
analysis as it was when that call ran: the calls before it, not the calls after.

Command line: ``uv run python -m bist_harness.harness.replay <analysis_id>``.
"""

from __future__ import annotations

import copy
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from bist_harness.harness import session
from bist_harness.storage import db

MATCH = "MATCH"
MISMATCH = "MISMATCH"

ToolCaller = Callable[[str, dict], dict]


@dataclass
class Difference:
    seq: int
    tool: str
    recorded: str | None
    new: str | None
    reason: str  # "snapshot verify failed", "different snapshot", "changed output", ...


@dataclass
class ReplayResult:
    analysis_id: str
    status: str
    snapshot_id: str
    current_snapshot_id: str
    today: str | None
    replayed: int
    snapshot_problems: list[str] = field(default_factory=list)
    differences: list[Difference] = field(default_factory=list)


def _default_call_tool(name: str, arguments: dict) -> dict:
    from bist_harness.mcp_server import server

    return getattr(server, name)(**arguments)


def _default_verify(snapshot_id: str) -> list[str]:
    from bist_harness.data import snapshot

    return snapshot.verify_snapshot(snapshot_id)


def _default_current() -> str:
    from bist_harness.mcp_server import server

    return server.current_snapshot_id()


def _call_as_it_was(analysis: session.Analysis, call, call_tool: ToolCaller) -> dict:
    """Run one call; a tool that reads the analysis by id sees only the calls before it."""
    if call.arguments.get("analysis_id") != analysis.analysis_id:
        return call_tool(call.tool, dict(call.arguments))
    past = copy.copy(analysis)
    past.tool_calls = [c for c in analysis.tool_calls if c.seq < call.seq]
    had = session._LIVE.get(analysis.analysis_id)
    session._LIVE[analysis.analysis_id] = past
    try:
        return call_tool(call.tool, dict(call.arguments))
    finally:
        if had is None:
            session._LIVE.pop(analysis.analysis_id, None)
        else:
            session._LIVE[analysis.analysis_id] = had


def replay(
    analysis: session.Analysis,
    *,
    call_tool: ToolCaller = _default_call_tool,
    verify: Callable[[str], list[str]] = _default_verify,
    current_snapshot_id: Callable[[], str] = _default_current,
) -> ReplayResult:
    """Re-run the allowed calls of ``analysis`` and compare every ``result_id``."""
    problems = list(verify(analysis.snapshot_id))
    current = current_snapshot_id()
    if problems:
        why = "snapshot verify failed"
    elif current != analysis.snapshot_id:
        why = "different snapshot"
    else:
        why = "changed output"
    differences: list[Difference] = []
    calls = [c for c in analysis.tool_calls if c.allowed]
    for call in calls:
        try:
            output = _call_as_it_was(analysis, call, call_tool)
        except Exception as exc:  # a tool that fails now is a difference, not a crash
            differences.append(
                Difference(call.seq, call.tool, call.result_id, None, f"tool failed: {exc}")
            )
            continue
        new = output.get("result_id") if isinstance(output, dict) else None
        if new != call.result_id:
            differences.append(Difference(call.seq, call.tool, call.result_id, new, why))
    same = not problems and current == analysis.snapshot_id and not differences
    return ReplayResult(
        analysis_id=analysis.analysis_id,
        status=MATCH if same else MISMATCH,
        snapshot_id=analysis.snapshot_id,
        current_snapshot_id=current,
        today=analysis.today,
        replayed=len(calls),
        snapshot_problems=problems,
        differences=differences,
    )


def format_result(result: ReplayResult) -> str:
    lines = [
        f"{result.status}  {result.analysis_id}  snapshot {result.snapshot_id}  "
        f"today {result.today or 'not recorded'}  {result.replayed} calls replayed"
    ]
    if result.current_snapshot_id != result.snapshot_id:
        lines.append(f"active snapshot is now {result.current_snapshot_id}")
    lines += [f"snapshot verify: {p}" for p in result.snapshot_problems]
    lines += [
        f"call {d.seq} {d.tool}: recorded {d.recorded}, now {d.new} ({d.reason})"
        for d in result.differences
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m bist_harness.harness.replay <analysis_id>", file=sys.stderr)
        return 2
    path = session._store_path()
    if not path.is_file():
        print(f"unknown analysis: {args[0]} (no store at {path})", file=sys.stderr)
        return 1
    conn = db.connect(path)
    try:
        analysis = session.load(args[0], conn)
    except KeyError:
        print(f"unknown analysis: {args[0]}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    result = replay(analysis)
    print(format_result(result))
    return 0 if result.status == MATCH else 1


if __name__ == "__main__":
    raise SystemExit(main())
