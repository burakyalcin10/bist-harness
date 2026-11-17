"""The tool contracts are the single source of truth for the MCP server and the LLM."""

from bist_harness.tools.schemas import ACTIONS, TOOL_SCHEMAS, to_ollama_tools

SPEC_TOOLS = {
    "get_stock_history",
    "get_index_history",
    "calculate_indicators",
    "detect_reversal_events",
    "find_support_resistance",
    "rank_sector_relative_strength",
    "test_weekday_pattern",
    "get_fundamental_metrics",
    "calculate_fundamental_change",
    "get_macro_context",
    "get_news_events",
    "get_speech_features",
    "run_backtest",
    "check_data_quality",
    "build_evidence_bundle",
}


def test_tool_names_match_spec_section_22():
    assert set(TOOL_SCHEMAS) == SPEC_TOOLS


def test_actions_are_the_eight_spec_labels_in_order():
    assert ACTIONS == (
        "HOLD",
        "WATCH",
        "INVESTIGATE",
        "POTENTIAL_CATCH_UP_CANDIDATE",
        "TECHNICAL_REVERSAL_CANDIDATE",
        "FUNDAMENTAL_IMPROVEMENT_CANDIDATE",
        "REJECT_SIGNAL",
        "ANALYSIS_UNSAFE",
    )


def test_every_tool_is_a_strict_described_object_schema():
    for tool in to_ollama_tools():
        fn = tool["function"]
        params = fn["parameters"]
        assert tool["type"] == "function"
        assert fn["description"]
        assert params["type"] == "object"
        assert params["additionalProperties"] is False
        assert set(params["required"]) <= set(params["properties"])
        for name, prop in params["properties"].items():
            assert prop.get("description"), f"{fn['name']}.{name} has no description"


def test_subset_selection_keeps_requested_order():
    names = ["run_backtest", "get_stock_history"]
    assert [t["function"]["name"] for t in to_ollama_tools(names)] == names


def test_unknown_tool_name_is_rejected():
    try:
        to_ollama_tools(["place_order"])
    except KeyError as exc:
        assert "place_order" in str(exc)
    else:
        raise AssertionError("expected KeyError for a tool outside the spec")


def test_reversal_event_types_cover_the_mandatory_families():
    enum = TOOL_SCHEMAS["detect_reversal_events"]["parameters"]["properties"]["event_type"]["enum"]
    assert {
        "BOLLINGER_LOWER_TOUCH",
        "BOLLINGER_MIDDLE_TEST",
        "BOLLINGER_UPPER_TOUCH",
        "RSI_LOCAL_TROUGH",
        "RSI_LOCAL_PEAK",
        "SUPERTREND_FLIP",
        "KAMA_TURN",
        "ICHIMOKU_BREAKOUT",
        "SUPPORT_RESISTANCE_TOUCH",
    } == set(enum)


def test_reversal_events_accept_an_optional_direction():
    from bist_harness.tools.schemas import validate_tool_call

    base = {
        "ticker": "ASELS",
        "start": "2021-01-01",
        "end": "2021-12-31",
        "event_type": "KAMA_TURN",
    }
    assert validate_tool_call("detect_reversal_events", base) is None
    assert validate_tool_call("detect_reversal_events", {**base, "direction": "BEARISH"}) is None
    assert "direction" in validate_tool_call("detect_reversal_events", {**base, "direction": "UP"})
