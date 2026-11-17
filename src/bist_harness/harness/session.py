"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

The analysis session: one question, its data versions and every tool call made for it.

Two places hold an analysis:

* an in-process registry of live analyses, so a tool such as ``check_data_quality`` can
  resolve an ``analysis_id`` in the middle of a run, before anything is saved;
* SQLite (``analyses`` and ``tool_calls``), written by ``save`` and read by ``load``.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bist_harness.config import Settings
from bist_harness.storage import db


@dataclass
class ToolCallRecord:
    seq: int
    state: str
    tool: str
    arguments: dict
    output: dict
    result_id: str | None
    allowed: bool = True
    source: str = "model"  # "model" or "harness"


@dataclass
class StateRecord:
    """What happened in one harness state: RAN, SKIPPED or NOT_APPLICABLE, with details."""

    state: str
    status: str
    detail: dict = field(default_factory=dict)


# Model settings every analysis runs with (temperature 0, fixed seed): same question, same
# data, same tool calls.
TEMPERATURE = 0.0
SEED = 42


@dataclass
class Analysis:
    analysis_id: str
    question: str
    created_at: str
    model: str
    snapshot_id: str
    adjustments_id: str
    intent: dict | None = None
    state: str = "START"
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    temperature: float = TEMPERATURE
    seed: int = SEED
    outcome: str | None = None  # REFUSED_ADVICE, ANALYSIS_UNSAFE, ... once the run ends
    answer: str | None = None  # the fixed answer of a refused or unsafe question
    gate_status: str | None = None
    trail: list[StateRecord] = field(default_factory=list)  # one record per state


_LIVE: dict[str, Analysis] = {}


def _versions() -> tuple[str, str]:
    # Imported here: the MCP server module imports this one.
    from bist_harness.mcp_server import server

    return server.current_snapshot_id(), server.current_adjustments_id()


def new_analysis(question: str, *, model: str) -> Analysis:
    """Start an analysis on the active data versions and register it as live."""
    snapshot_id, adjustments_id = _versions()
    analysis = Analysis(
        analysis_id=f"AN-{uuid.uuid4().hex[:12]}",
        question=question,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        model=model,
        snapshot_id=snapshot_id,
        adjustments_id=adjustments_id,
    )
    _LIVE[analysis.analysis_id] = analysis
    return analysis


def get(analysis_id: str) -> Analysis | None:
    """A live (or loaded) analysis by id, or ``None``."""
    return _LIVE.get(analysis_id)


def _store_path() -> Path:
    return Settings.from_env().data_dir / db.DEFAULT_FILE


def resolve(analysis_id: str) -> Analysis | None:
    """A live analysis, else one saved in the default store (never creating the file).

    A store read is not cached: in an MCP server process the harness saves new calls
    after every step, so each lookup must see the store as it is now.
    """
    live = _LIVE.get(analysis_id)
    if live is not None:
        return live
    path = _store_path()
    if not path.is_file():
        return None
    conn = db.connect(path)
    try:
        return _read(analysis_id, conn)
    except KeyError:
        return None
    finally:
        conn.close()


def record_call(
    analysis: Analysis,
    *,
    state: str,
    tool: str,
    arguments: dict,
    output: dict,
    allowed: bool = True,
    source: str = "model",
) -> ToolCallRecord:
    """Append one tool call; the call number is the position in the analysis."""
    result_id = output.get("result_id") if isinstance(output, dict) else None
    record = ToolCallRecord(
        seq=len(analysis.tool_calls) + 1,
        state=state,
        tool=tool,
        arguments=arguments,
        output=output,
        result_id=result_id,
        allowed=allowed,
        source=source,
    )
    analysis.tool_calls.append(record)
    return record


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def save(analysis: Analysis, conn: sqlite3.Connection) -> None:
    """Write the analysis and its tool calls; saving again replaces what was stored."""
    intent = analysis.intent or {}
    versions = {"adjustments_id": analysis.adjustments_id}
    run = {
        "temperature": analysis.temperature,
        "seed": analysis.seed,
        "answer": analysis.answer,
        "trail": [
            {"state": r.state, "status": r.status, "detail": r.detail} for r in analysis.trail
        ],
    }
    with conn:
        conn.execute(
            """
            INSERT INTO analyses (analysis_id, created_at, question, intent_json, ticker,
                                  sector, as_of, period_start, period_end, snapshot_id,
                                  data_versions_json, model, state, gate_status, outcome,
                                  run_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(analysis_id) DO UPDATE SET
                question = excluded.question, intent_json = excluded.intent_json,
                ticker = excluded.ticker, sector = excluded.sector, as_of = excluded.as_of,
                period_start = excluded.period_start, period_end = excluded.period_end,
                snapshot_id = excluded.snapshot_id,
                data_versions_json = excluded.data_versions_json,
                model = excluded.model, state = excluded.state,
                gate_status = excluded.gate_status, outcome = excluded.outcome,
                run_json = excluded.run_json
            """,
            (
                analysis.analysis_id,
                analysis.created_at,
                analysis.question,
                None if analysis.intent is None else _dump(analysis.intent),
                intent.get("ticker"),
                intent.get("sector"),
                intent.get("as_of"),
                intent.get("start"),
                intent.get("end"),
                analysis.snapshot_id,
                _dump(versions),
                analysis.model,
                analysis.state,
                analysis.gate_status,
                analysis.outcome,
                _dump(run),
            ),
        )
        conn.execute("DELETE FROM tool_calls WHERE analysis_id = ?", (analysis.analysis_id,))
        conn.executemany(
            """
            INSERT INTO tool_calls (analysis_id, seq, state, tool, arguments_json, output_json,
                                    result_id, allowed, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    analysis.analysis_id,
                    call.seq,
                    call.state,
                    call.tool,
                    _dump(call.arguments),
                    _dump(call.output),
                    call.result_id,
                    int(call.allowed),
                    call.source,
                )
                for call in analysis.tool_calls
            ],
        )


def load(analysis_id: str, conn: sqlite3.Connection) -> Analysis:
    """Read an analysis back (and register it as live); ``KeyError`` if it is not stored."""
    analysis = _read(analysis_id, conn)
    _LIVE[analysis.analysis_id] = analysis
    return analysis


def _read(analysis_id: str, conn: sqlite3.Connection) -> Analysis:
    """Read an analysis from the store without registering it; ``KeyError`` if absent."""
    row = conn.execute(
        "SELECT analysis_id, question, created_at, model, snapshot_id, data_versions_json, "
        "intent_json, state, gate_status, outcome, run_json FROM analyses WHERE analysis_id = ?",
        (analysis_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown analysis: {analysis_id}")
    run = {} if row[10] is None else json.loads(row[10])  # None: saved before version 3
    calls = conn.execute(
        "SELECT seq, state, tool, arguments_json, output_json, result_id, allowed, source "
        "FROM tool_calls WHERE analysis_id = ? ORDER BY seq",
        (analysis_id,),
    ).fetchall()
    analysis = Analysis(
        analysis_id=row[0],
        question=row[1],
        created_at=row[2],
        model=row[3],
        snapshot_id=row[4],
        adjustments_id=json.loads(row[5])["adjustments_id"],
        intent=None if row[6] is None else json.loads(row[6]),
        state=row[7],
        tool_calls=[
            ToolCallRecord(
                seq=c[0],
                state=c[1],
                tool=c[2],
                arguments=json.loads(c[3]),
                output=json.loads(c[4]),
                result_id=c[5],
                allowed=bool(c[6]),
                source=c[7],
            )
            for c in calls
        ],
        temperature=run.get("temperature", TEMPERATURE),
        seed=run.get("seed", SEED),
        outcome=row[9],
        answer=run.get("answer"),
        gate_status=row[8],
        trail=[StateRecord(r["state"], r["status"], r["detail"]) for r in run.get("trail", [])],
    )
    return analysis
