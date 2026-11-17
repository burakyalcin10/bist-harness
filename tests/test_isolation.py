"""Tests never read the real data folder (C2 of the Sprint 4 final review).

The autouse fixture in ``conftest.py`` points every data path at a temp folder and pins the
data-version ids the tools stamp on their outputs, so the suite behaves the same on a fresh
clone without any snapshot.
"""

import os
from pathlib import Path

import pytest

from bist_harness.config import Settings
from bist_harness.harness import session
from bist_harness.mcp_server import server


def test_the_data_folder_is_a_temp_folder(tmp_path_factory):
    data_dir = Settings.from_env().data_dir.resolve()
    temp_root = tmp_path_factory.getbasetemp().resolve()
    assert data_dir.is_relative_to(temp_root), data_dir


def test_the_store_lives_in_the_temp_data_folder(tmp_path_factory):
    store = Path(session._store_path()).resolve()
    assert store.is_relative_to(tmp_path_factory.getbasetemp().resolve()), store


def test_tool_outputs_name_pinned_data_versions():
    from tests.conftest import TEST_ADJUSTMENTS_ID, TEST_LAYERS_ID, TEST_SNAPSHOT_ID

    assert server._versions() == {
        "snapshot_id": TEST_SNAPSHOT_ID,
        "adjustments_id": TEST_ADJUSTMENTS_ID,
        "layers_id": TEST_LAYERS_ID,
        "data_source": server.DATA_SOURCE,
    }


@pytest.mark.real_data
def test_a_real_data_test_runs_only_on_request():
    if os.environ.get("BIST_REAL_DATA") != "1":
        pytest.fail("a real_data test ran without BIST_REAL_DATA=1")
