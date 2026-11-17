"""Evidence-based action eligibility: which of the eight labels the model may choose."""

import dataclasses
import re
from types import SimpleNamespace

import pytest

from bist_harness.harness import session
from bist_harness.harness.actions import eligible_actions
from bist_harness.harness.evidence import MINIMUM, Evidence, committed_set
from bist_harness.tools.schemas import ACTIONS

CANDIDATE = {
    "SECTOR_LAGGARD": "POTENTIAL_CATCH_UP_CANDIDATE",
    "TECHNICAL_REVERSAL": "TECHNICAL_REVERSAL_CANDIDATE",
    "FUNDAMENTAL_REACTION": "FUNDAMENTAL_IMPROVEMENT_CANDIDATE",
}
BASE = ("HOLD", "WATCH", "INVESTIGATE")
GATE_PASS = SimpleNamespace(status="PASS", hard_blocks=(), warnings=())
GATE_WARN = SimpleNamespace(status="PASS_WITH_WARNINGS", hard_blocks=(), warnings=("w",))
GATE_BLOCK = SimpleNamespace(status="HARD_BLOCK", hard_blocks=("x",), warnings=())
GATE_UNSAFE = SimpleNamespace(status="ANALYSIS_UNSAFE", hard_blocks=(), warnings=())


def analysis_of(scenario, *, backtest=None, calendar=None):
    """An analysis of the scenario; ``backtest`` / ``calendar`` are tool outputs or None."""
    analysis = session.Analysis(
        analysis_id="AN-test00000001",
        question="test",
        created_at="2026-11-17T00:00:00+00:00",
        model="fake",
        snapshot_id="snap",
        adjustments_id="adj",
        intent={"scenario": scenario, "ticker": "THYAO", "language": "en"},
    )
    if backtest is not None:
        out = {"result_id": "run_backtest-1", "flags": [], **backtest}
        session.record_call(
            analysis, state="RUN_BACKTEST", tool="run_backtest", arguments={}, output=out
        )
    if calendar is not None:
        out = {"result_id": "test_weekday_pattern-1", "interpretation_flags": [], **calendar}
        session.record_call(
            analysis, state="X", tool="test_weekday_pattern", arguments={}, output=out
        )
    return analysis


# The item that meets a requirement, with a value in the candidate's direction: the stock
# lags its sector, the fundamentals improve, most reversal events succeeded.
RIGHT_DIRECTION = {
    "lag_score": (("rank_sector_relative_strength", "members.lag_score_pct"), -2.5),
    "fundamental_change": (("calculate_fundamental_change", "fundamental_trend"), "Improving"),
    "reversal_stats": (("detect_reversal_events", "success_rate_pct"), 66.67),
}


def evidence_of(scenario, *, skip=(), committed=True, values=None, extra=()):
    """One item for every minimum-evidence requirement, except those named in ``skip``.

    ``values`` replaces the (kind, value) of a requirement; ``extra`` adds (kind, value)
    items. A row field names the analysis's stock, THYAO.
    """
    chosen = {**RIGHT_DIRECTION, **(values or {})}
    pairs = []
    for name, kinds in MINIMUM.get(scenario, ()):
        if name not in skip:
            pairs.append(chosen.get(name, (kinds[0], 1.0)))
    items = []
    for (tool, field), value in [*pairs, *extra]:
        field = re.sub(r"^(\w+)\.(\w+)$", r"\1[THYAO].\2", field) if "." in field else field
        items.append(
            Evidence(
                label=f"E{len(items) + 1}",
                tool=tool,
                result_id=f"{tool}-1",
                field=field,
                value=value,
                sentence="s",
                committed=False,
            )
        )
    return committed_set(items, scenario) if committed else items


def labels_for(scenario, gate=GATE_PASS, *, skip=(), committed=True, **calls):
    analysis = analysis_of(scenario, **calls)
    return eligible_actions(analysis, evidence_of(scenario, skip=skip, committed=committed), gate)


# --- the full table: every label x the conditions that allow it ------------------------------
CLEAN = {"backtest": {}}
TABLE = [
    # (case id, scenario, kwargs, gate, expected eligible labels)
    ("hard block", "SECTOR_LAGGARD", CLEAN, GATE_BLOCK, ("ANALYSIS_UNSAFE",)),
    ("analysis unsafe", "SECTOR_LAGGARD", CLEAN, GATE_UNSAFE, ("ANALYSIS_UNSAFE",)),
    ("hard block context", "PRICE_SUMMARY", {}, GATE_BLOCK, ("ANALYSIS_UNSAFE",)),
    (
        "catch-up, clean",
        "SECTOR_LAGGARD",
        CLEAN,
        GATE_PASS,
        (*BASE, "POTENTIAL_CATCH_UP_CANDIDATE"),
    ),
    (
        "catch-up, warnings",
        "SECTOR_LAGGARD",
        CLEAN,
        GATE_WARN,
        (*BASE, "POTENTIAL_CATCH_UP_CANDIDATE"),
    ),
    (
        "reversal, clean",
        "TECHNICAL_REVERSAL",
        CLEAN,
        GATE_PASS,
        (*BASE, "TECHNICAL_REVERSAL_CANDIDATE"),
    ),
    (
        "fundamental, clean",
        "FUNDAMENTAL_REACTION",
        CLEAN,
        GATE_PASS,
        (*BASE, "FUNDAMENTAL_IMPROVEMENT_CANDIDATE"),
    ),
    (
        "catch-up, no backtest run",
        "SECTOR_LAGGARD",
        {"skip": ("backtest_summary",)},
        GATE_PASS,
        ("INVESTIGATE",),
    ),
    (
        "catch-up, underperforms",
        "SECTOR_LAGGARD",
        {"backtest": {"flags": ["UNDERPERFORMS_BUY_AND_HOLD"]}},
        GATE_PASS,
        BASE,
    ),
    (
        "catch-up, few trades",
        "SECTOR_LAGGARD",
        {"backtest": {"flags": ["FEW_TRADES"]}},
        GATE_PASS,
        BASE,
    ),
    (
        "reversal, both flags",
        "TECHNICAL_REVERSAL",
        {"backtest": {"flags": ["FEW_TRADES", "UNDERPERFORMS_BUY_AND_HOLD"]}},
        GATE_PASS,
        BASE,
    ),
    (
        "catch-up, other flag only",
        "SECTOR_LAGGARD",
        {"backtest": {"flags": ["NEGATIVE_AFTER_COST"]}},
        GATE_PASS,
        (*BASE, "POTENTIAL_CATCH_UP_CANDIDATE"),
    ),
    (
        "catch-up, evidence missing",
        "SECTOR_LAGGARD",
        {**CLEAN, "skip": ("technical_state",)},
        GATE_PASS,
        ("INVESTIGATE",),
    ),
    (
        "catch-up, set not committed",
        "SECTOR_LAGGARD",
        {**CLEAN, "committed": False},
        GATE_PASS,
        ("INVESTIGATE",),
    ),
    (
        "calendar, not significant",
        "CALENDAR_PATTERN",
        {**CLEAN, "calendar": {"interpretation_flags": ["NOT_SIGNIFICANT"]}},
        GATE_PASS,
        ("REJECT_SIGNAL",),
    ),
    (
        "calendar, not significant, warnings",
        "CALENDAR_PATTERN",
        {**CLEAN, "calendar": {"interpretation_flags": ["NOT_SIGNIFICANT", "FEW_TRADES"]}},
        GATE_WARN,
        ("REJECT_SIGNAL",),
    ),
    (
        "calendar, significant",
        "CALENDAR_PATTERN",
        {**CLEAN, "calendar": {}},
        GATE_PASS,
        BASE,
    ),
    (
        "calendar, evidence missing",
        "CALENDAR_PATTERN",
        {"calendar": {}, "skip": ("backtest_summary",)},
        GATE_PASS,
        ("INVESTIGATE",),
    ),
    ("backtest question, clean", "BACKTEST", CLEAN, GATE_PASS, BASE),
    (
        "backtest question, evidence missing",
        "BACKTEST",
        {"skip": ("benchmark_comparison",)},
        GATE_PASS,
        ("INVESTIGATE",),
    ),
    ("price summary, complete", "PRICE_SUMMARY", {}, GATE_PASS, BASE),
    (
        "price summary, missing",
        "PRICE_SUMMARY",
        {"skip": ("technical_state",)},
        GATE_PASS,
        ("INVESTIGATE",),
    ),
    ("macro, complete", "MACRO_CONTEXT", {}, GATE_WARN, BASE),
    ("news, complete", "NEWS_CONTEXT", {}, GATE_PASS, BASE),
]


def run_case(scenario, kwargs, gate):
    kwargs = dict(kwargs)
    skip = kwargs.pop("skip", ())
    committed = kwargs.pop("committed", True)
    return labels_for(scenario, gate, skip=skip, committed=committed, **kwargs)


@pytest.mark.parametrize("case", TABLE, ids=[row[0] for row in TABLE])
def test_each_case_of_the_table(case):
    _, scenario, kwargs, gate, expected = case
    assert run_case(scenario, kwargs, gate) == expected


@pytest.mark.parametrize("case", TABLE, ids=[row[0] for row in TABLE])
def test_every_label_is_allowed_exactly_when_the_table_says(case):
    _, scenario, kwargs, gate, expected = case
    got = run_case(scenario, kwargs, gate)
    for label in ACTIONS:
        assert (label in got) == (label in expected), label


def test_the_table_reaches_every_one_of_the_eight_labels():
    reached = {label for *_, expected in TABLE for label in expected}
    assert reached == set(ACTIONS)


def test_each_candidate_label_belongs_to_its_own_scenario_only():
    for scenario, label in CANDIDATE.items():
        for other in CANDIDATE:
            got = labels_for(other, backtest={})
            assert (label in got) == (other == scenario), (scenario, other)


def test_the_backtest_must_have_run_even_when_the_evidence_claims_it():
    # Evidence names a backtest field, but the analysis holds no run_backtest call.
    analysis = analysis_of("SECTOR_LAGGARD")
    got = eligible_actions(analysis, evidence_of("SECTOR_LAGGARD"), GATE_PASS)
    assert "POTENTIAL_CATCH_UP_CANDIDATE" not in got


def test_a_failed_backtest_call_does_not_count_as_a_run():
    analysis = analysis_of("SECTOR_LAGGARD")
    error = {"result_id": "run_backtest-9", "error": {"code": "DATA_UNAVAILABLE", "message": "?"}}
    session.record_call(
        analysis, state="RUN_BACKTEST", tool="run_backtest", arguments={}, output=error
    )
    got = eligible_actions(analysis, evidence_of("SECTOR_LAGGARD"), GATE_PASS)
    assert "POTENTIAL_CATCH_UP_CANDIDATE" not in got


def test_a_rejected_backtest_call_does_not_count_as_a_run():
    analysis = analysis_of("SECTOR_LAGGARD")
    session.record_call(
        analysis,
        state="RUN_BACKTEST",
        tool="run_backtest",
        arguments={},
        output={"result_id": "run_backtest-9", "flags": []},
        allowed=False,
    )
    got = eligible_actions(analysis, evidence_of("SECTOR_LAGGARD"), GATE_PASS)
    assert "POTENTIAL_CATCH_UP_CANDIDATE" not in got


def test_a_scenario_without_a_candidate_label_gets_the_base_labels():
    analysis = analysis_of("NOT_A_SCENARIO", backtest={})
    assert eligible_actions(analysis, (), GATE_PASS) == BASE


def test_the_unsafe_label_is_never_offered_without_a_block():
    for _, scenario, kwargs, gate, _ in TABLE:
        if gate.status not in ("HARD_BLOCK", "ANALYSIS_UNSAFE"):
            assert "ANALYSIS_UNSAFE" not in run_case(scenario, kwargs, gate)


# --- determinism ---------------------------------------------------------------------------
def test_same_input_gives_the_same_tuple_in_label_order():
    first = labels_for("SECTOR_LAGGARD", backtest={})
    second = labels_for("SECTOR_LAGGARD", backtest={})
    assert first == second and isinstance(first, tuple)
    assert list(first) == sorted(first, key=ACTIONS.index)
    assert len(set(first)) == len(first)


def test_every_eligible_label_is_one_of_the_eight():
    for _, scenario, kwargs, gate, _ in TABLE:
        assert set(run_case(scenario, kwargs, gate)) <= set(ACTIONS)


def test_eligibility_does_not_change_the_analysis_or_evidence():
    analysis = analysis_of("SECTOR_LAGGARD", backtest={})
    evidence = evidence_of("SECTOR_LAGGARD")
    before = (len(analysis.tool_calls), list(evidence))
    eligible_actions(analysis, evidence, GATE_PASS)
    assert (len(analysis.tool_calls), list(evidence)) == before


# --- I2: a candidate label needs evidence pointing its way -------------------------------
LAG = ("rank_sector_relative_strength", "members.lag_score_pct")
RETURN = ("rank_sector_relative_strength", "members.return_pct")
TREND = ("calculate_fundamental_change", "fundamental_trend")
REAL_PROFIT = ("calculate_fundamental_change", "net_profit_real_yoy_pct")
SUCCESS = ("detect_reversal_events", "success_rate_pct")
AVERAGE = ("detect_reversal_events", "average_forward_return_pct")


def candidate_offered(scenario, *, analysis=None, **evidence_kwargs):
    analysis = analysis or analysis_of(scenario, backtest={})
    got = eligible_actions(analysis, evidence_of(scenario, **evidence_kwargs), GATE_PASS)
    return CANDIDATE[scenario] in got


@pytest.mark.parametrize(
    ("values", "offered"),
    [
        ({"lag_score": (LAG, -2.5)}, True),  # behind its sector: lag score < 0
        ({"lag_score": (LAG, 6.39)}, False),  # SL-01 live: PGSUS led its sector
        ({"lag_score": (LAG, 0.0)}, False),
        ({"lag_score": (RETURN, -4.0)}, False),  # a return alone is no lag evidence
    ],
)
def test_catch_up_needs_the_stock_to_lag_its_sector(values, offered):
    assert candidate_offered("SECTOR_LAGGARD", values=values) is offered


def test_catch_up_reads_the_lag_score_of_the_analysis_stock():
    # THYAO (the analysis's stock) leads; a peer that lags does not make THYAO a candidate.
    peer = (("rank_sector_relative_strength", "members.lag_score_pct"), -3.0)
    evidence = evidence_of("SECTOR_LAGGARD", values={"lag_score": (LAG, 4.0)}, extra=(peer,))
    evidence = [
        dataclasses.replace(item, field="members[AKBNK].lag_score_pct")
        if item.value == -3.0
        else item
        for item in evidence
    ]
    analysis = analysis_of("SECTOR_LAGGARD", backtest={})
    assert "POTENTIAL_CATCH_UP_CANDIDATE" not in eligible_actions(analysis, evidence, GATE_PASS)


@pytest.mark.parametrize(
    ("values", "extra", "offered"),
    [
        ({"fundamental_change": (TREND, "Improving")}, (), True),
        ({"fundamental_change": (TREND, "Deteriorating")}, (), False),
        ({"fundamental_change": (TREND, "Mixed")}, (), False),
        ({"fundamental_change": (REAL_PROFIT, 12.5)}, (), True),  # no trend: real profit grew
        ({"fundamental_change": (REAL_PROFIT, -12.5)}, (), False),
        ({"fundamental_change": (TREND, "Deteriorating")}, ((REAL_PROFIT, 12.5),), False),
    ],
)
def test_fundamental_improvement_needs_improving_fundamentals(values, extra, offered):
    assert candidate_offered("FUNDAMENTAL_REACTION", values=values, extra=extra) is offered


def reversal_analysis(direction):
    analysis = analysis_of("TECHNICAL_REVERSAL", backtest={})
    session.record_call(
        analysis,
        state="RUN_PATTERN_AND_REVERSAL_ANALYSIS",
        tool="detect_reversal_events",
        arguments={},
        output={"result_id": "detect_reversal_events-1", "direction": direction},
    )
    return analysis


@pytest.mark.parametrize(
    ("direction", "values", "extra", "offered"),
    [
        ("BULLISH", {"reversal_stats": (SUCCESS, 66.67)}, ((AVERAGE, 1.2),), True),
        ("BULLISH", {"reversal_stats": (SUCCESS, 16.67)}, (), False),  # 1 of 6 live
        ("BULLISH", {"reversal_stats": (SUCCESS, 50.0)}, (), False),  # not a majority
        ("BULLISH", {"reversal_stats": (SUCCESS, 60.0)}, ((AVERAGE, -1.2),), False),
        ("BEARISH", {"reversal_stats": (SUCCESS, 60.0)}, ((AVERAGE, -1.2),), True),
        ("BEARISH", {"reversal_stats": (SUCCESS, 60.0)}, ((AVERAGE, 1.2),), False),
        ("BULLISH", {"reversal_stats": (AVERAGE, 1.2)}, (), False),  # no success rate
    ],
)
def test_reversal_candidate_needs_successful_events_in_their_direction(
    direction, values, extra, offered
):
    analysis = reversal_analysis(direction)
    assert (
        candidate_offered("TECHNICAL_REVERSAL", analysis=analysis, values=values, extra=extra)
        is offered
    )
