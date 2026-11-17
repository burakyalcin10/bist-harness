"""Contract tests and golden outputs of the 15 MCP tools (EC-041).

Each tool has one successful and one failing call whose output is stored in
``tests/golden``. A changed output fails the test and shows a diff; when the change is
intended, ``UPDATE_GOLDEN=1 uv run pytest tests/test_contracts.py`` rewrites the files and
the difference appears in the commit. The data behind the calls is a seeded synthetic
snapshot (``tests/golden_snapshot.py``) with pinned version ids: the real data folder is
never read.
"""

from __future__ import annotations

import difflib
import inspect
import json
import os
import re
from pathlib import Path

import pytest

from bist_harness.data import macro as macro_data
from bist_harness.data import snapshot as snapshot_module
from bist_harness.harness import session
from bist_harness.mcp_server import server as srv
from bist_harness.tools.schemas import TOOL_SCHEMAS

from .golden_snapshot import build_golden_snapshot

GOLDEN_DIR = Path(__file__).parent / "golden"
MAX_LIST_ROWS = 12
PINNED = {"snapshot": "golden-snapshot", "adjustments": "adj00000", "layers": "lay00000"}

TOOLS = list(TOOL_SCHEMAS)
STUBS = {"build_evidence_bundle", "get_speech_features"}  # not implemented yet


@pytest.fixture(autouse=True)
def golden_data(monkeypatch, tmp_path):
    """The seeded snapshot behind every tool; versions pinned; no real data read."""
    root = tmp_path / "data"
    build_golden_snapshot(root / "snapshots")
    monkeypatch.setenv("BIST_DATA_DIR", str(root))
    monkeypatch.setattr(srv, "current_snapshot_id", lambda: PINNED["snapshot"])
    monkeypatch.setattr(srv, "current_adjustments_id", lambda: PINNED["adjustments"])
    monkeypatch.setattr(srv, "current_layers_id", lambda: PINNED["layers"])
    # no price corrections and no recorded CPI release days: only the synthetic files
    no_adjustments = tmp_path / "adjustments.csv"
    no_adjustments.write_text("ticker,effective_date,factor,reason\n", encoding="utf-8")
    monkeypatch.setattr(snapshot_module, "ADJUSTMENTS_PATH", no_adjustments)
    monkeypatch.setattr(
        srv, "load_macro", lambda name: macro_data.load_macro(name, cpi_releases=None)
    )
    videos = tmp_path / "approved_videos.csv"
    videos.write_text("source_id\nVID-001\n", encoding="utf-8")
    monkeypatch.setattr(srv, "APPROVED_VIDEOS", videos)
    # analyses get predictable ids and live in a store of their own
    counter = iter(range(1, 1000))
    monkeypatch.setattr(
        session.uuid, "uuid4", lambda: type("U", (), {"hex": f"{next(counter):032x}"})()
    )
    monkeypatch.setattr(session, "_store_path", lambda: tmp_path / "store.sqlite")
    session._LIVE.clear()
    yield
    session._LIVE.clear()


def _analysis_id() -> str:
    """A running analysis that has already made one price call."""
    analysis = session.new_analysis("Is ASELS a buy?", model="golden-model")
    arguments = {"ticker": "ASELS", "start": "2024-01-02", "end": "2024-12-31"}
    session.record_call(
        analysis,
        state="COLLECT",
        tool="get_stock_history",
        arguments=arguments,
        output=srv.get_stock_history(**arguments),
    )
    return analysis.analysis_id


# tool -> (arguments of the successful call, arguments of the failing call, error code).
# A callable argument set is built inside the test (it needs an analysis).
CASES = {
    "get_stock_history": (
        {"ticker": "ASELS", "start": "2024-01-02", "end": "2024-12-31"},
        {"ticker": "GARAN", "start": "2024-01-02", "end": "2024-12-31"},
        "UNKNOWN_TICKER",
    ),
    "get_index_history": (
        {"index": "XU100", "start": "2024-01-02", "end": "2024-12-31"},
        {"index": "XU999", "start": "2024-01-02", "end": "2024-12-31"},
        "UNKNOWN_INDEX",
    ),
    "calculate_indicators": (
        {
            "ticker": "ASELS",
            "start": "2024-01-02",
            "end": "2024-12-31",
            "indicators": ["RSI", "MACD", "SMA"],
        },
        {"ticker": "ASELS", "start": "2024-12-31", "end": "2024-01-02", "indicators": ["RSI"]},
        "INVALID_DATE_RANGE",
    ),
    "find_support_resistance": (
        {"ticker": "ASELS", "start": "2023-06-01", "end": "2024-12-31"},
        {"ticker": "ASELS", "start": "2024-01-02", "end": "2024-12-31", "tolerance": 0.5},
        "INVALID_ARGUMENT",
    ),
    "detect_reversal_events": (
        {
            "ticker": "ASELS",
            "start": "2023-06-01",
            "end": "2025-06-30",
            "event_type": "BOLLINGER_LOWER_TOUCH",
            "forward_days": 5,
        },
        {
            "ticker": "ASELS",
            "start": "01.01.2024",
            "end": "2024-12-31",
            "event_type": "BOLLINGER_LOWER_TOUCH",
        },
        "INVALID_DATE",
    ),
    "test_weekday_pattern": (
        {
            "ticker": "ASELS",
            "pattern": "WEEKDAY_MEANS",
            "start": "2023-02-01",
            "end": "2025-06-30",
        },
        {"ticker": "ASELS", "pattern": "WEEKDAY_MEANS", "start": "2024-01-02", "end": "2999-01-01"},
        "FUTURE_DATE",
    ),
    "rank_sector_relative_strength": (
        {"sector": "Banking", "horizon_days": 20, "as_of": "2025-06-30"},
        {"sector": "Nonexistent", "horizon_days": 20, "as_of": "2025-06-30"},
        "UNKNOWN_SECTOR",
    ),
    "get_fundamental_metrics": (
        {"ticker": "TUPRS", "as_of": "2025-11-10"},
        {"ticker": "TUPRS", "as_of": "2024-01-01"},
        "DATA_UNAVAILABLE",
    ),
    "calculate_fundamental_change": (
        {"ticker": "ASELS", "as_of": "2025-11-10", "periods": 3},
        {"ticker": "ASELS", "as_of": "2025-11-10", "periods": 99},
        "INVALID_ARGUMENT",
    ),
    "get_macro_context": (
        {"start": "2024-01-02", "end": "2025-06-30"},
        {"start": "2025-06-30", "end": "2024-01-02"},
        "INVALID_DATE_RANGE",
    ),
    "get_news_events": (
        {"start": "2025-01-01", "end": "2025-12-31", "ticker": "ASELS"},
        {"start": "2025-01-01", "end": "2025-12-31", "topic": "astrology"},
        "INVALID_ARGUMENT",
    ),
    "get_speech_features": (
        {"source_id": "VID-001"},
        {"source_id": "VID-404"},
        "UNKNOWN_SOURCE",
    ),
    "run_backtest": (
        {
            "strategy": "A_TECHNICAL",
            "universe": ["ASELS", "TUPRS"],
            "start": "2024-01-02",
            "end": "2025-06-30",
        },
        {
            "strategy": "A_TECHNICAL",
            "universe": ["GARAN"],
            "start": "2024-01-02",
            "end": "2024-12-31",
        },
        "UNKNOWN_TICKER",
    ),
    "check_data_quality": (
        lambda: {"analysis_id": _analysis_id()},
        {"analysis_id": "AN-unknown"},
        "UNKNOWN_ANALYSIS",
    ),
    "build_evidence_bundle": (
        lambda: {"analysis_id": _analysis_id()},
        {"analysis_id": "AN-unknown"},
        "UNKNOWN_ANALYSIS",
    ),
}


def _arguments(entry) -> dict:
    return entry() if callable(entry) else entry


def _call(tool: str, arguments: dict) -> dict:
    return getattr(srv, tool)(**arguments)


def _render(output: dict) -> str:
    return json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def _check_golden(name: str, output: dict) -> None:
    path = GOLDEN_DIR / f"{name}.json"
    text = _render(output)
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN_DIR.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return
    assert path.is_file(), f"{path.name} is missing; run with UPDATE_GOLDEN=1 to create it"
    stored = path.read_text(encoding="utf-8")
    if stored != text:
        diff = "".join(
            difflib.unified_diff(stored.splitlines(True), text.splitlines(True), "golden", "actual")
        )
        pytest.fail(f"{name} differs from its golden output:\n{diff}")


def _lists(value, path="$"):
    if isinstance(value, list):
        yield path, value
        for i, item in enumerate(value):
            yield from _lists(item, f"{path}[{i}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _lists(item, f"{path}.{key}")


def test_the_fifteen_tools_are_the_registered_tools():
    registered = {tool.name for tool in srv.server._tool_manager.list_tools()}
    assert len(TOOLS) == 15
    assert registered == set(TOOLS) == set(CASES)


@pytest.mark.parametrize("tool", TOOLS)
def test_schema_matches_the_function_signature(tool):
    parameters = inspect.signature(getattr(srv, tool)).parameters
    schema = TOOL_SCHEMAS[tool]["parameters"]
    assert schema["type"] == "object" and schema.get("additionalProperties") is False
    assert set(schema["properties"]) == set(parameters)
    required = {name for name, p in parameters.items() if p.default is inspect.Parameter.empty}
    assert set(schema["required"]) == required
    for name, spec in schema["properties"].items():
        default = parameters[name].default
        if "default" in spec:
            assert spec["default"] == default
        described = re.search(r"default ([\w.]+)", spec.get("description", ""))
        if described and default is not inspect.Parameter.empty:
            assert described.group(1).rstrip(".") == str(default)
        if "enum" in spec and default not in (inspect.Parameter.empty, None):
            assert default in spec["enum"]


@pytest.mark.parametrize("tool", TOOLS)
def test_successful_call_matches_its_golden_and_the_output_contract(tool):
    ok, _, _ = CASES[tool]
    output = _call(tool, _arguments(ok))
    _check_golden(f"{tool}.ok", output)
    if tool in STUBS:  # answers NOT_IMPLEMENTED until the feature exists
        assert set(output) == {"error"}
        return
    assert "error" not in output, output
    for key in ("snapshot_id", "adjustments_id", "layers_id", "data_source", "result_id"):
        assert output.get(key), key
    assert output["snapshot_id"] == PINNED["snapshot"]
    assert output["adjustments_id"] == PINNED["adjustments"]
    assert output["layers_id"] == PINNED["layers"]
    assert re.fullmatch(r"[0-9a-f]{12}", output["result_id"])
    json.dumps(output, allow_nan=False)  # no NaN or infinity anywhere
    for where, rows in _lists(output):
        assert len(rows) <= MAX_LIST_ROWS, f"{where} has {len(rows)} rows"


@pytest.mark.parametrize("tool", TOOLS)
def test_failing_call_matches_its_golden_and_carries_only_the_error(tool):
    _, bad, code = CASES[tool]
    output = _call(tool, _arguments(bad))
    _check_golden(f"{tool}.error", output)
    assert set(output) == {"error"}
    assert output["error"]["code"] == code
    assert output["error"]["message"]
    json.dumps(output, allow_nan=False)


@pytest.mark.parametrize("tool", TOOLS)
def test_missing_or_unknown_arguments_are_reported_not_raised(tool):
    schema = TOOL_SCHEMAS[tool]["parameters"]
    for arguments in ({"surprise": 1}, {k: None for k in schema["required"]}):
        output = getattr(srv, tool)(**arguments)
        assert set(output) == {"error"}
        assert output["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("tool", [t for t in TOOLS if t not in STUBS])
def test_same_call_gives_the_same_output(tool):
    ok, _, _ = CASES[tool]
    arguments = _arguments(ok)
    assert _call(tool, arguments) == _call(tool, arguments)
