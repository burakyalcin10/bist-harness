"""The data dictionary names every indicator column and every tool output field."""

import re

import numpy as np
import pandas as pd
import pytest

from bist_harness.mcp_server import server as srv
from bist_harness.tools.indicators import add_all_indicators

from .conftest import REPO_ROOT
from .synth import ohlcv

DICTIONARY = REPO_ROOT / "docs" / "data_dictionary.md"


def _documented() -> set[str]:
    return set(re.findall(r"`([A-Za-z0-9_]+)`", DICTIONARY.read_text(encoding="utf-8")))


def _keys(value) -> set[str]:
    """Every dictionary key in a tool output, at any depth."""
    if isinstance(value, dict):
        return set(value) | {k for item in value.values() for k in _keys(item)}
    if isinstance(value, list):
        return {k for item in value for k in _keys(item)}
    return set()


PLAIN_TYPES = {"str", "int", "float", "bool", "NoneType"}


def _leaves(value):
    """Every value in a tool output that is not a container."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item)
    else:
        yield value


@pytest.fixture
def histories(monkeypatch):
    frames: dict[str, pd.DataFrame] = {}

    def load(symbol):
        if symbol not in frames:
            frames[symbol] = ohlcv(1200, seed=sum(map(ord, symbol)))
        return frames[symbol]

    monkeypatch.setattr(srv, "load_history", load)
    from .test_macro import _series

    macro = _series()
    monkeypatch.setattr(srv, "load_macro", lambda name: macro[name])
    from .test_fundamentals_tools import _calendar, _statements

    monkeypatch.setattr(srv, "load_statements", lambda: _statements())
    monkeypatch.setattr(srv, "load_disclosure_calendar", lambda: _calendar())


def test_every_indicator_column_is_in_the_dictionary():
    columns = set(add_all_indicators(ohlcv(100, 1)).columns)
    missing = sorted(columns - _documented())
    assert not missing, f"not documented: {missing}"


def test_every_tool_output_field_is_in_the_dictionary(histories):
    period = ("2021-01-01", "2023-12-31")
    outputs = [
        srv.get_stock_history("ASELS", *period),
        srv.get_index_history("XU100", *period),
        srv.calculate_indicators("ASELS", *period, []),
        srv.find_support_resistance("ASELS", *period),
        srv.detect_reversal_events("ASELS", *period, "BOLLINGER_MIDDLE_TEST"),
        srv.detect_reversal_events("ASELS", *period, "ICHIMOKU_BREAKOUT"),
        srv.rank_sector_relative_strength("Banking", 20, "2023-12-29"),
        srv.test_weekday_pattern("ASELS", "WEEKDAY_MEANS", *period),
        srv.test_weekday_pattern("ASELS", "THREE_DOWN_TWO_UP", *period),
        srv.run_backtest("B_TECH_SECTOR", ["AKBNK", "THYAO"], *period),
        srv.get_macro_context("2026-09-01", "2026-11-03"),
        srv.get_fundamental_metrics("TUPRS", "2025-11-10"),
        srv.calculate_fundamental_change("TUPRS", "2025-11-10"),
        srv.get_stock_history("GARAN", *period),
    ]
    assert not any(np.isnan(v) for o in outputs for v in o.values() if isinstance(v, float))
    for output in outputs:
        odd = sorted({type(v).__name__ for v in _leaves(output)} - PLAIN_TYPES)
        assert not odd, f"{output.get('result_id')}: values of type {odd} in a tool output"
    fields = {key for output in outputs for key in _keys(output)}
    missing = sorted(fields - _documented())
    assert not missing, f"not documented: {missing}"
