"""Evidence-based action eligibility: which of the eight labels the model may choose."""

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


def evidence_of(scenario, *, skip=(), committed=True):
    """One item for every minimum-evidence requirement, except those named in ``skip``."""
    items = []
    for name, kinds in MINIMUM.get(scenario, ()):
        if name in skip:
            continue
        tool, field = kinds[0]
        field = re.sub(r"^(\w+)\.(\w+)$", r"\1[X].\2", field) if "." in field else field
        items.append(
            Evidence(
                label=f"E{len(items) + 1}",
                tool=tool,
                result_id=f"{tool}-1",
                field=field,
                value=1.0,
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
