import pytest

from bist_harness.harness.intent import GUARDED_SCENARIOS, SCENARIOS
from bist_harness.harness.routes import (
    ALLOWED_TOOLS,
    CANDIDATE_SCENARIOS,
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


@pytest.mark.parametrize("scenario", CANDIDATE_SCENARIOS)
def test_candidate_capable_routes_preview_and_backtest(scenario):
    assert {"PREVIEW_STRATEGIES", "RUN_BACKTEST"} <= set(ROUTES[scenario])


def test_candidate_scenarios_cover_the_candidate_labels():
    assert {"SECTOR_LAGGARD", "TECHNICAL_REVERSAL", "FUNDAMENTAL_REACTION"} <= set(
        CANDIDATE_SCENARIOS
    )


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
