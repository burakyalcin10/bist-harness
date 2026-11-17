"""The quality gate: hard blocks, soft warnings and a decision that is code, not the model's."""

import pytest

from bist_harness.harness import session
from bist_harness.harness.gate import GateResult, quality_gate

OK_QUALITY = {"result_id": "q-1", "status": "PASS", "findings": [], "checked": []}


def make(*calls, scenario="PRICE_SUMMARY", ticker="THYAO", quality=OK_QUALITY):
    """An analysis with the given (tool, arguments, output) calls and a quality check last."""
    analysis = session.Analysis(
        analysis_id="AN-test00000001",
        question="test",
        created_at="2026-11-17T00:00:00+00:00",
        model="fake",
        snapshot_id="snap",
        adjustments_id="adj",
        intent={"scenario": scenario, "ticker": ticker, "language": "en"},
    )
    for i, (tool, arguments, output) in enumerate(calls, 1):
        output = {"result_id": f"{tool}-{i}", **output}
        session.record_call(analysis, state="X", tool=tool, arguments=arguments, output=output)
    if quality is not None:
        session.record_call(
            analysis, state="RISK_GATE", tool="check_data_quality", arguments={}, output=quality
        )
    return analysis


def history(rows=120, **arguments):
    return ("get_stock_history", {"ticker": "THYAO", **arguments}, {"rows": rows})


def gate_of(analysis):
    return quality_gate(analysis, ())


# --- a clean analysis ---------------------------------------------------------------------
def test_a_clean_analysis_passes():
    result = gate_of(make(history()))
    assert isinstance(result, GateResult)
    assert (result.status, result.hard_blocks, result.warnings) == ("PASS", (), ())


# --- every hard block has a triggering analysis ---------------------------------------------
def test_hard_block_symbol_outside_the_universe_in_the_intent():
    result = gate_of(make(history(), ticker="AAPL"))
    assert result.status == "HARD_BLOCK"
    assert any("AAPL" in reason for reason in result.hard_blocks)


def test_hard_block_symbol_outside_the_universe_in_a_tool_call():
    analysis = make(("get_stock_history", {"ticker": "FOOBAR"}, {"rows": 10}))
    result = gate_of(analysis)
    assert result.status == "HARD_BLOCK"
    assert any("FOOBAR" in reason for reason in result.hard_blocks)


def test_hard_block_symbol_outside_the_universe_in_a_backtest_universe_list():
    analysis = make(("run_backtest", {"universe": ["THYAO", "ZZZZ"]}, {"flags": []}))
    assert gate_of(analysis).status == "HARD_BLOCK"


def test_a_rejected_call_with_a_foreign_symbol_is_not_a_block():
    # The tool refused it: nothing foreign entered the analysis.
    error = {"error": {"code": "UNKNOWN_TICKER", "message": "no"}}
    analysis = make(("get_stock_history", {"ticker": "FOOBAR"}, error))
    assert gate_of(analysis).status == "PASS"


def test_hard_block_hard_finding_from_the_quality_check():
    quality = {
        "result_id": "q-1",
        "status": "PASS_WITH_WARNINGS",
        "findings": [{"code": "PRICE_JUMP", "severity": "hard", "message": "jump", "count": 1}],
        "checked": [],
    }
    result = gate_of(make(history(), quality=quality))
    assert result.status == "HARD_BLOCK"
    assert any("PRICE_JUMP" in reason for reason in result.hard_blocks)


def test_hard_block_when_the_quality_check_says_so():
    quality = {"result_id": "q-1", "status": "HARD_BLOCK", "findings": [], "checked": []}
    assert gate_of(make(history(), quality=quality)).status == "HARD_BLOCK"


def test_hard_block_when_the_quality_check_gave_no_status():
    quality = {"error": {"code": "UNKNOWN_ANALYSIS", "message": "?"}}
    result = gate_of(make(history(), quality=quality))
    assert result.status == "HARD_BLOCK"
    assert any("UNKNOWN_ANALYSIS" in reason for reason in result.hard_blocks)


def test_hard_block_when_no_quality_check_ran():
    assert gate_of(make(history(), quality=None)).status == "HARD_BLOCK"


def test_hard_block_trade_that_used_information_after_its_signal_date():
    sample = [
        {"ticker": "THYAO", "signal_date": "2025-03-10", "info_date": "2025-03-10"},
        {"ticker": "THYAO", "signal_date": "2025-03-11", "info_date": "2025-03-12"},
    ]
    analysis = make(("run_backtest", {}, {"flags": [], "trade_sample": sample}))
    result = gate_of(analysis)
    assert result.status == "HARD_BLOCK"
    assert any("2025-03-12" in reason for reason in result.hard_blocks)


def test_trades_with_information_up_to_the_signal_date_are_fine():
    sample = [{"ticker": "THYAO", "signal_date": "2025-03-11", "info_date": "2025-03-11"}]
    analysis = make(("run_backtest", {}, {"flags": [], "trade_sample": sample}))
    assert gate_of(analysis).status == "PASS"


def test_hard_block_statement_known_after_the_as_of_date():
    output = {"as_of": "2025-05-01", "period": "2025Q1", "known_from": "2025-05-20"}
    analysis = make(("get_fundamental_metrics", {"ticker": "THYAO"}, output))
    result = gate_of(analysis)
    assert result.status == "HARD_BLOCK"
    assert any("2025-05-20" in reason for reason in result.hard_blocks)


def test_hard_block_a_quarter_row_known_after_the_as_of_date():
    output = {
        "as_of": "2025-05-01",
        "known_from": "2025-04-20",
        "quarters": [
            {"period": "2025Q1", "known_from": "2025-04-20"},
            {"known_from": "2025-06-01"},
        ],
    }
    analysis = make(("calculate_fundamental_change", {"ticker": "THYAO"}, output))
    assert gate_of(analysis).status == "HARD_BLOCK"


def test_statements_known_by_the_as_of_date_are_fine():
    output = {"as_of": "2025-05-01", "known_from": "2025-05-01", "quarters": []}
    assert gate_of(make(("get_fundamental_metrics", {}, output))).status == "PASS"


def test_hard_block_empty_price_data():
    assert gate_of(make(history(rows=0))).status == "HARD_BLOCK"


def test_hard_block_a_checked_series_without_rows():
    quality = {
        "result_id": "q-1",
        "status": "PASS",
        "findings": [],
        "checked": [{"ticker": "THYAO", "as_of": "2025-06-30", "rows": 0}],
    }
    assert gate_of(make(history(), quality=quality)).status == "HARD_BLOCK"


def test_every_block_is_listed_not_only_the_first():
    sample = [{"signal_date": "2025-03-11", "info_date": "2025-03-12"}]
    analysis = make(
        history(rows=0), ("run_backtest", {}, {"flags": [], "trade_sample": sample}), ticker="AAPL"
    )
    assert len(gate_of(analysis).hard_blocks) == 3


# --- soft warnings ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "output",
    [
        {"sample_warning": "Only 3 trades."},
        {"coverage_warning": "News coverage is sparse."},
        {"warnings": ["Peer group has only 3 members."]},
        {"warnings": ["Macro series CPI is missing for 2025-06."]},
        {"interpretation_flags": ["NOT_SIGNIFICANT"]},
        {"flags": ["FEW_TRADES"]},
    ],
)
def test_a_tool_warning_makes_pass_with_warnings(output):
    result = gate_of(make(("run_backtest", {}, output)))
    assert result.status == "PASS_WITH_WARNINGS"
    assert result.hard_blocks == ()
    assert len(result.warnings) == 1


def test_a_soft_quality_finding_makes_pass_with_warnings():
    quality = {
        "result_id": "q-1",
        "status": "PASS_WITH_WARNINGS",
        "findings": [{"code": "ZERO_VOLUME", "severity": "soft", "message": "3 days", "count": 3}],
        "checked": [],
    }
    result = gate_of(make(history(), quality=quality))
    assert result.status == "PASS_WITH_WARNINGS"
    assert any("ZERO_VOLUME" in w for w in result.warnings)


def test_the_same_warning_is_listed_once():
    output = {"sample_warning": "Only 3 trades."}
    analysis = make(("run_backtest", {}, output), ("test_weekday_pattern", {}, output))
    assert gate_of(analysis).warnings == ("Only 3 trades.",)


def test_sasa_with_volume_based_features_warns():
    analysis = make(
        ("calculate_indicators", {"ticker": "SASA", "indicators": ["VOLUME"]}, {}), ticker="SASA"
    )
    result = gate_of(analysis)
    assert result.status == "PASS_WITH_WARNINGS"
    assert any("SASA" in w and "volume" in w.lower() for w in result.warnings)


def test_sasa_with_all_indicators_warns():
    analysis = make(
        ("calculate_indicators", {"ticker": "SASA", "indicators": []}, {}), ticker="SASA"
    )
    assert any("SASA" in w for w in gate_of(analysis).warnings)


def test_sasa_without_volume_features_does_not_warn():
    analysis = make(
        ("calculate_indicators", {"ticker": "SASA", "indicators": ["RSI"]}, {}), ticker="SASA"
    )
    assert gate_of(analysis).warnings == ()


def test_volume_features_of_another_stock_do_not_warn():
    analysis = make(("calculate_indicators", {"ticker": "THYAO", "indicators": ["VOLUME"]}, {}))
    assert gate_of(analysis).warnings == ()


def test_a_hard_block_still_lists_the_warnings():
    output = {"sample_warning": "Only 3 trades."}
    result = gate_of(make(history(rows=0), ("run_backtest", {}, output)))
    assert result.status == "HARD_BLOCK" and "Only 3 trades." in result.warnings


# --- determinism: the decision is code ---------------------------------------------------------
def test_the_same_input_gives_the_same_decision():
    def build():
        sample = [{"signal_date": "2025-03-11", "info_date": "2025-03-12"}]
        return make(
            ("run_backtest", {}, {"flags": ["FEW_TRADES"], "trade_sample": sample}),
            ("calculate_indicators", {"ticker": "SASA", "indicators": []}, {}),
            ticker="SASA",
        )

    first, second = gate_of(build()), gate_of(build())
    assert first == second
    assert first.status == "HARD_BLOCK"


def test_the_gate_does_not_depend_on_the_evidence_it_is_given():
    analysis = make(history())
    assert quality_gate(analysis, ()) == quality_gate(analysis, ["anything"])


def test_the_gate_does_not_change_the_analysis():
    analysis = make(history(rows=0))
    gate_of(analysis)
    assert analysis.gate_status is None and len(analysis.tool_calls) == 2


def test_a_quality_check_that_reports_warnings_gives_pass_with_warnings():
    quality = {"result_id": "q-1", "status": "PASS_WITH_WARNINGS", "findings": [], "checked": []}
    result = gate_of(make(history(), quality=quality))
    assert result.status == "PASS_WITH_WARNINGS" and result.hard_blocks == ()
