"""SQLite store: the episodic memory and the decision log (project brief, sections 24 and 28).

Five tables:

* ``analyses``   one row per analysis run: question, data versions, states, gate, action
* ``tool_calls`` every tool call of an analysis, in order, with arguments and output
* ``evidence``   the evidence bundle; ``committed = 1`` marks the committed evidence set
* ``decisions``  human review of an analysis: ACCEPT, MODIFY or REJECT, with a reason
* ``events``     detected reversal events with their market state and forward returns

Structured values are stored as JSON text in ``*_json`` columns.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bist_harness.config import Settings

SCHEMA_VERSION = 1
DEFAULT_FILE = "harness.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    analysis_id        TEXT PRIMARY KEY,
    created_at         TEXT NOT NULL,
    question           TEXT NOT NULL,
    intent_json        TEXT,
    ticker             TEXT,
    sector             TEXT,
    as_of              TEXT,
    period_start       TEXT,
    period_end         TEXT,
    snapshot_id        TEXT,
    data_versions_json TEXT,
    model              TEXT,
    state              TEXT,
    states_json        TEXT,
    sources_json       TEXT,
    strategy_variant   TEXT,
    backtest_json      TEXT,
    gate_status        TEXT,
    action             TEXT,
    explanation        TEXT
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id             INTEGER PRIMARY KEY,
    analysis_id    TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
    seq            INTEGER NOT NULL,
    state          TEXT,
    tool           TEXT NOT NULL,
    arguments_json TEXT,
    output_json    TEXT,
    result_id      TEXT,
    allowed        INTEGER NOT NULL DEFAULT 1,
    UNIQUE (analysis_id, seq)
);

CREATE TABLE IF NOT EXISTS evidence (
    id          INTEGER PRIMARY KEY,
    analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    tool        TEXT,
    result_id   TEXT,
    field       TEXT,
    value       TEXT,
    sentence    TEXT NOT NULL,
    committed   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (analysis_id, label)
);

CREATE TABLE IF NOT EXISTS decisions (
    id           INTEGER PRIMARY KEY,
    analysis_id  TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
    reviewed_at  TEXT NOT NULL,
    human_result TEXT NOT NULL CHECK (human_result IN ('ACCEPT', 'MODIFY', 'REJECT')),
    reason       TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY,
    snapshot_id  TEXT NOT NULL,
    ticker       TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    direction    TEXT NOT NULL,
    event_date   TEXT NOT NULL,
    state_json   TEXT,
    forward_json TEXT,
    UNIQUE (snapshot_id, ticker, event_type, direction, event_date)
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_analysis ON tool_calls (analysis_id, seq);
CREATE INDEX IF NOT EXISTS idx_evidence_analysis ON evidence (analysis_id);
CREATE INDEX IF NOT EXISTS idx_events_ticker ON events (ticker, event_type, event_date);
"""

# Where each decision-log field of section 28 is stored: field -> (table, column).
DECISION_LOG_FIELDS: dict[str, tuple[str, str]] = {
    "stock": ("analyses", "ticker"),
    "sector": ("analyses", "sector"),
    "analysis_time": ("analyses", "created_at"),
    "data_period_start": ("analyses", "period_start"),
    "data_period_end": ("analyses", "period_end"),
    "data_versions_and_publication_times": ("analyses", "data_versions_json"),
    "market_data_snapshot": ("analyses", "snapshot_id"),
    "tools_called": ("tool_calls", "tool"),
    "tool_arguments": ("tool_calls", "arguments_json"),
    "tool_outputs": ("tool_calls", "output_json"),
    "technical_sector_fundamental_macro_states": ("analyses", "states_json"),
    "news_and_speech_source_metadata": ("analyses", "sources_json"),
    "evidence_bundle": ("evidence", "sentence"),
    "committed_evidence_set": ("evidence", "committed"),
    "strategy_variant": ("analyses", "strategy_variant"),
    "backtest_result": ("analyses", "backtest_json"),
    "gate_status": ("analyses", "gate_status"),
    "agent_result": ("analyses", "action"),
    "agent_explanation": ("analyses", "explanation"),
    "human_review_result": ("decisions", "human_result"),
    "human_review_reason": ("decisions", "reason"),
}


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the store, creating the file and the tables if needed.

    A file written by a newer schema version is refused rather than silently used.
    """
    path = path or Settings.from_env().data_dir / DEFAULT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(
            f"{path.name} has schema version {version}; this code supports {SCHEMA_VERSION}."
        )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return conn
