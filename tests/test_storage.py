"""SQLite store for analyses, tool calls, evidence, human decisions and event records."""

import sqlite3

import pytest

from bist_harness.storage import db

TABLES = {"analyses", "tool_calls", "evidence", "decisions", "events"}

# Section 28 of the project brief: what the decision log must hold for every analysis.
SECTION_28_FIELDS = {
    "stock",
    "sector",
    "analysis_time",
    "data_period_start",
    "data_period_end",
    "data_versions_and_publication_times",
    "market_data_snapshot",
    "tools_called",
    "tool_arguments",
    "tool_outputs",
    "technical_sector_fundamental_macro_states",
    "news_and_speech_source_metadata",
    "evidence_bundle",
    "committed_evidence_set",
    "strategy_variant",
    "backtest_result",
    "gate_status",
    "agent_result",
    "agent_explanation",
    "human_review_result",
    "human_review_reason",
}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_analysis(conn: sqlite3.Connection, analysis_id: str = "a1") -> None:
    conn.execute(
        "INSERT INTO analyses (analysis_id, created_at, question) VALUES (?, ?, ?)",
        (analysis_id, "2026-11-17T00:00:00+00:00", "ASELS?"),
    )


def test_new_file_has_the_five_tables_and_the_schema_version(tmp_path):
    conn = db.connect(tmp_path / "store.sqlite")
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert TABLES <= names
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 3
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_reopening_an_existing_file_keeps_its_rows(tmp_path):
    path = tmp_path / "store.sqlite"
    conn = db.connect(path)
    _add_analysis(conn)
    conn.commit()
    conn.close()
    again = db.connect(path)
    assert again.execute("SELECT question FROM analyses").fetchall() == [("ASELS?",)]


def test_child_rows_need_an_existing_analysis(tmp_path):
    conn = db.connect(tmp_path / "store.sqlite")
    for statement in (
        "INSERT INTO tool_calls (analysis_id, seq, tool) VALUES ('missing', 1, 'get_stock_history')",
        "INSERT INTO evidence (analysis_id, label, sentence) VALUES ('missing', 'E1', 'x')",
        "INSERT INTO decisions (analysis_id, reviewed_at, human_result) "
        "VALUES ('missing', '2026-11-17', 'ACCEPT')",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement)
    _add_analysis(conn)
    conn.execute(
        "INSERT INTO tool_calls (analysis_id, seq, tool) VALUES ('a1', 1, 'get_stock_history')"
    )


def test_human_result_is_limited_to_the_three_review_outcomes(tmp_path):
    conn = db.connect(tmp_path / "store.sqlite")
    _add_analysis(conn)
    for outcome in ("ACCEPT", "MODIFY", "REJECT"):
        conn.execute(
            "INSERT INTO decisions (analysis_id, reviewed_at, human_result) VALUES ('a1', 'now', ?)",
            (outcome,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO decisions (analysis_id, reviewed_at, human_result) "
            "VALUES ('a1', 'now', 'MAYBE')"
        )


def test_tool_call_sequence_and_evidence_label_are_unique_within_an_analysis(tmp_path):
    conn = db.connect(tmp_path / "store.sqlite")
    _add_analysis(conn)
    conn.execute("INSERT INTO tool_calls (analysis_id, seq, tool) VALUES ('a1', 1, 't')")
    conn.execute("INSERT INTO evidence (analysis_id, label, sentence) VALUES ('a1', 'E1', 's')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tool_calls (analysis_id, seq, tool) VALUES ('a1', 1, 't')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO evidence (analysis_id, label, sentence) VALUES ('a1', 'E1', 's')")


def test_every_decision_log_field_of_section_28_has_a_column(tmp_path):
    conn = db.connect(tmp_path / "store.sqlite")
    assert set(db.DECISION_LOG_FIELDS) == SECTION_28_FIELDS
    for field, (table, column) in db.DECISION_LOG_FIELDS.items():
        assert column in _columns(conn, table), field


def test_a_file_written_by_a_newer_schema_is_refused(tmp_path):
    path = tmp_path / "store.sqlite"
    raw = sqlite3.connect(path)
    raw.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    raw.commit()
    raw.close()
    with pytest.raises(RuntimeError, match="schema version"):
        db.connect(path)


def test_default_path_is_inside_the_data_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("BIST_DATA_DIR", str(tmp_path))
    conn = db.connect()
    conn.close()
    assert (tmp_path / "harness.sqlite").is_file()
