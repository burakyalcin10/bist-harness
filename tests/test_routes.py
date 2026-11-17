import pytest

from bist_harness.harness.intent import GUARDED_SCENARIOS, SCENARIOS
from bist_harness.harness.routes import (
    ALLOWED_TOOLS,
    MANDATORY,
    ROUTES,
    STATES,
)
from bist_harness.tools.schemas import TOOL_SCHEMAS

ANALYSIS = [s for s in SCENARIOS if s not in GUARDED_SCENARIOS]


def test_seventeen_states_in_spec_order():
    assert len(STATES) == 17
    assert STATES[0] == "START" and STATES[-1] == "LOG_AND_CLOSE"
    order = [STATES.index(s) for s in ("CHECK_DATA_QUALITY", "RUN_BACKTEST", "RISK_GATE")]
    assert order == sorted(order)


def test_every_scenario_has_a_route():
    assert set(ROUTES) == set(SCENARIOS)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_route_states_are_valid_unique_and_in_state_order(scenario):
    route = ROUTES[scenario]
    assert set(route) <= set(STATES)
    assert [s for s in STATES if s in route] == list(route)
    assert route[0] == "START" and route[-1] == "LOG_AND_CLOSE"


@pytest.mark.parametrize("scenario", ANALYSIS)
def test_analysis_routes_contain_mandatory_states(scenario):
    assert set(MANDATORY) <= set(ROUTES[scenario])


def test_mandatory_is_the_brief_value():
    assert MANDATORY == ("CHECK_DATA_QUALITY", "RISK_GATE", "LOG_AND_CLOSE")


CANDIDATE_CAPABLE = [
    "SECTOR_LAGGARD",
    "CALENDAR_PATTERN",
    "TECHNICAL_REVERSAL",
    "FUNDAMENTAL_REACTION",
    "BACKTEST",
]


@pytest.mark.parametrize("scenario", CANDIDATE_CAPABLE)
def test_candidate_capable_routes_preview_and_backtest(scenario):
    assert {"PREVIEW_STRATEGIES", "RUN_BACKTEST"} <= set(ROUTES[scenario])


def test_production_candidate_list_matches_the_hard_coded_one():
    from bist_harness.harness.routes import CANDIDATE_SCENARIOS

    assert sorted(CANDIDATE_SCENARIOS) == sorted(CANDIDATE_CAPABLE)


@pytest.mark.parametrize("scenario", GUARDED_SCENARIOS)
def test_guarded_routes_never_start_an_analysis(scenario):
    route = ROUTES[scenario]
    assert route == ("START", "LOG_AND_CLOSE")
    assert not any(ALLOWED_TOOLS[s] for s in route)


def test_allowed_tools_cover_every_state_and_exist_in_schema():
    assert set(ALLOWED_TOOLS) == set(STATES)
    for tools in ALLOWED_TOOLS.values():
        for tool in tools:
            assert tool in TOOL_SCHEMAS


def test_data_states_only_in_matching_routes():
    assert "LOAD_FUNDAMENTALS" in ROUTES["FUNDAMENTAL_REACTION"]
    assert "LOAD_MACRO_CONTEXT" in ROUTES["MACRO_CONTEXT"]
    assert "LOAD_NEWS_AND_SPEECH_CONTEXT" in ROUTES["NEWS_CONTEXT"]
    assert "RUN_SECTOR_RELATIVE_ANALYSIS" in ROUTES["SECTOR_LAGGARD"]


SPEC_SECTION_6_TOOLS = {
    "START": (),
    "SELECT_UNIVERSE": (),
    "LOAD_MARKET_DATA": ("get_stock_history", "get_index_history"),
    "CHECK_DATA_QUALITY": ("check_data_quality",),
    "CALCULATE_TECHNICALS": ("calculate_indicators", "find_support_resistance"),
    "RUN_SECTOR_RELATIVE_ANALYSIS": ("rank_sector_relative_strength",),
    "RUN_PATTERN_AND_REVERSAL_ANALYSIS": ("detect_reversal_events", "test_weekday_pattern"),
    "LOAD_FUNDAMENTALS": ("get_fundamental_metrics", "calculate_fundamental_change"),
    "LOAD_MACRO_CONTEXT": ("get_macro_context",),
    "LOAD_NEWS_AND_SPEECH_CONTEXT": ("get_news_events", "get_speech_features"),
    "BUILD_EVIDENCE": ("build_evidence_bundle",),
    "PREVIEW_STRATEGIES": (),
    "RUN_BACKTEST": ("run_backtest",),
    "RISK_GATE": ("check_data_quality",),
    "GENERATE_EXPLANATION": (),
    "HUMAN_REVIEW": (),
    "LOG_AND_CLOSE": (),
}


def test_allowed_tools_equal_the_spec_table():
    assert ALLOWED_TOOLS == SPEC_SECTION_6_TOOLS


def test_quality_states_expose_check_data_quality():
    assert "check_data_quality" in ALLOWED_TOOLS["RISK_GATE"]
    assert "check_data_quality" in ALLOWED_TOOLS["CHECK_DATA_QUALITY"]


@pytest.mark.parametrize(
    ("state", "owners"),
    [
        ("LOAD_FUNDAMENTALS", {"FUNDAMENTAL_REACTION"}),
        ("LOAD_MACRO_CONTEXT", {"MACRO_CONTEXT"}),
        ("LOAD_NEWS_AND_SPEECH_CONTEXT", {"NEWS_CONTEXT"}),
        ("RUN_SECTOR_RELATIVE_ANALYSIS", {"SECTOR_LAGGARD"}),
    ],
)
def test_data_states_are_absent_from_unrelated_routes(state, owners):
    assert {s for s, route in ROUTES.items() if state in route} == owners
