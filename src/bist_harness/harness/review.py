"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

Human review and the decision log (design spec section 10, card EC-048).

* ``decision_log`` assembles, for one analysis, every field of the section 28 decision log
  (``storage.db.DECISION_LOG_FIELDS``). A field that does not apply is the literal string
  ``"not applicable"``, never empty; a review that has not happened yet is ``"pending"``.
* ``record_review`` stores the human's ACCEPT, MODIFY or REJECT with the reason.

Command line (store path from the settings)::

    uv run python -m bist_harness.harness.review <analysis_id> ACCEPT|MODIFY|REJECT "reason"
    uv run python -m bist_harness.harness.review log <analysis_id>
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import sys
from datetime import UTC, datetime

from bist_harness.harness import session
from bist_harness.harness.evidence import build_evidence
from bist_harness.storage import db

NOT_APPLICABLE = "not applicable"
PENDING = "pending"  # the analysis has no human review yet
VERDICTS = ("ACCEPT", "MODIFY", "REJECT")
STATE_GROUPS = (
    "CALCULATE_TECHNICALS",
    "RUN_SECTOR_RELATIVE_ANALYSIS",
    "LOAD_FUNDAMENTALS",
    "LOAD_MACRO_CONTEXT",
)
SOURCE_TOOLS = ("get_news_events", "get_speech_features")
VERSION_KEYS = ("snapshot_id", "adjustments_id", "layers_id", "data_source")


def _fill(value):
    """The value, or ``"not applicable"`` when it is empty."""
    return NOT_APPLICABLE if value is None or value in ("", [], {}) else value


def _calls(analysis: session.Analysis, tool: str) -> list:
    return [c for c in analysis.tool_calls if c.tool == tool and c.allowed]


def _versions(analysis: session.Analysis) -> dict:
    versions = {"snapshot_id": analysis.snapshot_id, "adjustments_id": analysis.adjustments_id}
    for call in analysis.tool_calls:
        if call.allowed and isinstance(call.output, dict) and "snapshot_id" in call.output:
            versions.update({k: call.output[k] for k in VERSION_KEYS if k in call.output})
            break
    return {**versions, "analysis_time": analysis.created_at, "reference_date": analysis.today}


def latest_review(analysis_id: str, conn: sqlite3.Connection) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT human_result, reason FROM decisions WHERE analysis_id = ? ORDER BY id DESC LIMIT 1",
        (analysis_id,),
    ).fetchone()
    return None if row is None else (row[0], row[1])


def decision_log(analysis: session.Analysis, conn: sqlite3.Connection) -> dict:
    """Every decision-log field of one analysis; none is ever empty."""
    intent = analysis.intent or {}
    language = intent.get("language") if intent.get("language") in ("tr", "en") else "en"
    calls = analysis.tool_calls
    states = {r.state: r.status for r in analysis.trail}
    evidence = [dataclasses.asdict(e) for e in build_evidence(analysis, language=language)]
    backtests = _calls(analysis, "run_backtest")
    sources = [
        {"seq": c.seq, "tool": c.tool, "arguments": c.arguments, "output": c.output}
        for tool in SOURCE_TOOLS
        for c in _calls(analysis, tool)
    ]
    review = latest_review(analysis.analysis_id, conn)
    log = {
        "stock": intent.get("ticker"),
        "sector": intent.get("sector"),
        "analysis_time": analysis.created_at,
        "data_period_start": intent.get("start"),
        "data_period_end": intent.get("end"),
        "data_versions_and_publication_times": _versions(analysis),
        "market_data_snapshot": analysis.snapshot_id,
        "tools_called": [f"{c.seq}:{c.tool}" for c in calls],
        "tool_arguments": {str(c.seq): c.arguments for c in calls},
        "tool_outputs": {str(c.seq): c.output for c in calls},
        "technical_sector_fundamental_macro_states": {
            s: states.get(s, "NOT_APPLICABLE") for s in STATE_GROUPS
        },
        "news_and_speech_source_metadata": sources,
        "evidence_bundle": evidence,
        "committed_evidence_set": [e["label"] for e in evidence if e["committed"]],
        "strategy_variant": backtests[-1].arguments.get("strategy") if backtests else None,
        "backtest_result": backtests[-1].output if backtests else None,
        "gate_status": analysis.gate_status,
        "agent_result": analysis.outcome,
        "agent_explanation": analysis.answer,
        "human_review_result": review[0] if review else PENDING,
        "human_review_reason": (review[1] or NOT_APPLICABLE) if review else PENDING,
    }
    return {field: _fill(log[field]) for field in db.DECISION_LOG_FIELDS}


def record_review(analysis_id: str, verdict: str, reason: str, conn: sqlite3.Connection) -> None:
    """Store a human review. ``KeyError``: unknown analysis; ``ValueError``: bad input."""
    verdict = verdict.strip().upper()
    if verdict not in VERDICTS:
        raise ValueError("the review result must be ACCEPT, MODIFY or REJECT")
    if not reason.strip():
        raise ValueError("a reason is required")
    if (
        conn.execute("SELECT 1 FROM analyses WHERE analysis_id = ?", (analysis_id,)).fetchone()
        is None
    ):
        raise KeyError(f"unknown analysis: {analysis_id}")
    with conn:
        conn.execute(
            "INSERT INTO decisions (analysis_id, reviewed_at, human_result, reason) "
            "VALUES (?, ?, ?, ?)",
            (analysis_id, datetime.now(UTC).isoformat(timespec="seconds"), verdict, reason.strip()),
        )


def _open_store() -> sqlite3.Connection | None:
    path = session._store_path()
    return db.connect(path) if path.is_file() else None  # never create the file


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    usage = (
        "usage: python -m bist_harness.harness.review <analysis_id> ACCEPT|MODIFY|REJECT "
        '"reason"\n       python -m bist_harness.harness.review log <analysis_id>'
    )
    if args[:1] == ["log"] and len(args) == 2:
        analysis_id = args[1]
        verdict = reason = None
    elif len(args) == 3:
        analysis_id, verdict, reason = args
    else:
        print(usage, file=sys.stderr)
        return 2
    if verdict is not None and verdict.strip().upper() not in VERDICTS:
        return _fail(f"bad review result {verdict!r}: use ACCEPT, MODIFY or REJECT")
    conn = _open_store()
    if conn is None:
        return _fail(f"unknown analysis: {analysis_id} (no store at {session._store_path()})")
    try:
        if verdict is None:
            analysis = session._read(analysis_id, conn)
            print(json.dumps(decision_log(analysis, conn), ensure_ascii=False, indent=2))
            return 0
        record_review(analysis_id, verdict, reason, conn)
    except KeyError:
        return _fail(f"unknown analysis: {analysis_id}")
    except ValueError as exc:
        return _fail(str(exc))
    finally:
        conn.close()
    print(f"{analysis_id}: {verdict.strip().upper()} recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
