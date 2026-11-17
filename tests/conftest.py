"""Shared test helpers.

Tests never read the real data folder: the autouse fixture points ``BIST_DATA_DIR`` and the
analysis store at a temp folder and pins the data-version ids every tool output carries. A test
that genuinely needs the real data is marked ``real_data`` and runs only with
``BIST_REAL_DATA=1 uv run pytest -m real_data``.
"""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_SNAPSHOT_ID = "test-snapshot"
TEST_ADJUSTMENTS_ID = "testadj0"
TEST_LAYERS_ID = "testlay0"
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
    "check_data_quality",
    "build_evidence_bundle",
    "get_speech_features",
}


REAL_DATA_ENV = "BIST_REAL_DATA"


def pytest_collection_modifyitems(config, items):
    """``real_data`` tests read the real data folder; they run only on request."""
    if os.environ.get(REAL_DATA_ENV) == "1":
        return
    skip = pytest.mark.skip(reason=f"reads the real data folder; set {REAL_DATA_ENV}=1 to run")
    for item in items:
        if "real_data" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolated_data(request, monkeypatch, tmp_path_factory):
    """Tools see a temp data folder, a temp store and fixed data-version ids.

    No test depends on a real snapshot, layer file or ``harness.sqlite`` on disk.
    """
    if "real_data" in request.keywords:
        return
    from bist_harness.harness import session
    from bist_harness.mcp_server import server
    from bist_harness.storage import db

    data_dir = tmp_path_factory.mktemp("bist-data")
    monkeypatch.setenv("BIST_DATA_DIR", str(data_dir))
    monkeypatch.setattr(session, "_store_path", lambda: data_dir / db.DEFAULT_FILE)
    monkeypatch.setattr(server, "current_snapshot_id", lambda: TEST_SNAPSHOT_ID, raising=False)
    monkeypatch.setattr(server, "current_adjustments_id", lambda: TEST_ADJUSTMENTS_ID)
    monkeypatch.setattr(server, "current_layers_id", lambda: TEST_LAYERS_ID)
