"""Scoring rules of the model bake-off and integrity of its 30 cases."""

import json
from collections import Counter

from bist_harness.bakeoff.score import load_cases, score_case, summarize
from bist_harness.llm.client import ToolCall
from bist_harness.tools.schemas import TOOL_SCHEMAS

EXPECTED = {
    "tool": "detect_reversal_events",
    "args": {"ticker": "ASELS", "event_type": "BOLLINGER_LOWER_TOUCH", "start": "2020-01-01"},
}


def test_exact_match_scores_tool_and_arguments():
    call = ToolCall("detect_reversal_events", dict(EXPECTED["args"]))
    s = score_case(EXPECTED, [call])
    assert (s.tool_ok, s.args_ok, s.no_tool_ok) == (True, True, None)


def test_ticker_case_and_yahoo_suffix_are_normalised():
    call = ToolCall("detect_reversal_events", {**EXPECTED["args"], "ticker": "asels.IS"})
    assert score_case(EXPECTED, [call]).args_ok


def test_extra_arguments_do_not_fail_the_case():
    call = ToolCall("detect_reversal_events", {**EXPECTED["args"], "forward_days": 5})
    assert score_case(EXPECTED, [call]).args_ok


def test_wrong_argument_value_fails_arguments_only():
    call = ToolCall("detect_reversal_events", {**EXPECTED["args"], "start": "2021-01-01"})
    s = score_case(EXPECTED, [call])
    assert (s.tool_ok, s.args_ok) == (True, False)


def test_numeric_strings_equal_numbers():
    expected = {"tool": "rank_sector_relative_strength", "args": {"horizon_days": 20}}
    call = ToolCall("rank_sector_relative_strength", {"horizon_days": "20"})
    assert score_case(expected, [call]).args_ok


def test_wrong_tool_fails_both():
    s = score_case(EXPECTED, [ToolCall("get_stock_history", dict(EXPECTED["args"]))])
    assert (s.tool_ok, s.args_ok) == (False, False)


def test_only_the_first_call_counts():
    calls = [
        ToolCall("get_stock_history", {}),
        ToolCall("detect_reversal_events", EXPECTED["args"]),
    ]
    assert not score_case(EXPECTED, calls).tool_ok


def test_missing_call_fails_a_tool_case():
    s = score_case(EXPECTED, [])
    assert (s.tool_ok, s.args_ok) == (False, False)


def test_no_tool_case_passes_only_without_calls():
    expected = {"expect": "no_tool"}
    assert score_case(expected, []).no_tool_ok is True
    assert score_case(expected, [ToolCall("get_stock_history", {})]).no_tool_ok is False


def test_summary_percentages_use_the_right_denominators():
    scores = [
        score_case(EXPECTED, [ToolCall("detect_reversal_events", dict(EXPECTED["args"]))]),
        score_case(EXPECTED, []),
        score_case({"expect": "no_tool"}, []),
    ]
    assert summarize(scores) == {
        "tool_ok_pct": 50.0,
        "args_ok_pct": 50.0,
        "no_tool_ok_pct": 100.0,
        "tool_cases": 2,
        "no_tool_cases": 1,
    }


def test_case_file_distribution_and_schema_consistency():
    cases = load_cases()
    assert len(cases) == 30
    assert len({c["id"] for c in cases}) == 30
    assert Counter(c["lang"] for c in cases) == {"tr": 15, "en": 15}
    assert sum(c.get("expect") == "no_tool" for c in cases) == 5
    for case in cases:
        assert case["question"].strip()
        if case.get("expect") == "no_tool":
            assert "tool" not in case
            continue
        properties = TOOL_SCHEMAS[case["tool"]]["parameters"]["properties"]
        assert set(case["args"]) <= set(properties), case["id"]
        json.dumps(case)  # serialisable


def test_every_mandatory_scenario_has_five_cases():
    by_prefix = Counter(c["id"].split("-")[0] for c in load_cases())
    assert by_prefix == {"cu": 5, "cal": 5, "rev": 5, "fun": 5, "oth": 5, "trap": 5}
