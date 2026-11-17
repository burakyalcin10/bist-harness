"""Shared test helpers."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_SNAPSHOT_ID = "test-snapshot"
# Tools the MCP server exposes so far; grows as tools are implemented.
IMPLEMENTED_TOOLS = {
    "get_stock_history",
    "get_index_history",
    "calculate_indicators",
    "find_support_resistance",
    "rank_sector_relative_strength",
    "test_weekday_pattern",
    "run_backtest",
    "get_macro_context",
    "get_fundamental_metrics",
    "calculate_fundamental_change",
    "get_news_events",
    "detect_reversal_events",
}


@pytest.fixture(autouse=True)
def fixed_snapshot_id(monkeypatch):
    """Tools report a fixed snapshot id; no test depends on a real snapshot on disk."""
    from bist_harness.mcp_server import server

    monkeypatch.setattr(server, "current_snapshot_id", lambda: TEST_SNAPSHOT_ID, raising=False)
