"""The grading metrics counted on a small hand-labelled sample (card EC-061).

``fixtures/labelled_records.jsonl`` holds twelve synthetic records written by hand and
``fixtures/labelled_expected.json`` holds the value of every metric on them, written by hand
with a one-line reason each. The tests assert the code reproduces every value exactly. The
backtest accuracy is checked with a stub tool that returns a matching and a mismatching
output. Nothing here reads the data folder, calls a model or uses the network.
"""

import json
from pathlib import Path

import pytest

from bist_harness.eval import metrics, run_eval

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIXTURES / "labelled_expected.json").read_text(encoding="utf-8"))

PER_RECORD = {
    "answer_numbers": metrics.answer_numbers,
    "attempt_numbers": metrics.attempt_numbers,
    "wrong_calls": metrics.wrong_calls,
    "tool_call_count": metrics.tool_call_count,
    "unsupported_conclusion": metrics.unsupported_conclusion,
    "evidence_completeness": metrics.evidence_completeness,
    "rule_violations": metrics.rule_violations,
    "explanation_fallback": metrics.explanation_fallback,
    "invented_fields": metrics.invented_fields,
}


@pytest.fixture(scope="module")
def labelled() -> dict[str, dict]:
    lines = (FIXTURES / "labelled_records.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    return {r["fixture_id"]: r for r in records}


def _jsonable(value):
    return list(value) if isinstance(value, tuple) else value


def test_the_sample_is_twelve_records_with_a_reason_for_every_expected_value(labelled):
    assert len(labelled) == 12
    for entry in (*EXPECTED["records"], *EXPECTED["groups"], EXPECTED["backtest"]):
        assert entry["reason"].strip(), entry
    assert {e["id"] for e in EXPECTED["records"]} <= set(labelled)
    for group in EXPECTED["groups"]:
        assert set(group["ids"]) <= set(labelled)


@pytest.mark.parametrize("entry", EXPECTED["records"], ids=lambda e: f"{e['id']}-{e['metric']}")
def test_a_record_metric_equals_its_hand_written_value(labelled, entry):
    got = PER_RECORD[entry["metric"]](labelled[entry["id"]])
    assert _jsonable(got) == entry["expected"], entry["reason"]


@pytest.mark.parametrize(
    "entry", EXPECTED["groups"], ids=lambda e: f"{'+'.join(e['ids'])}-{e['metric']}"
)
def test_a_group_metric_equals_its_hand_written_value(labelled, entry):
    group = [labelled[i] for i in entry["ids"]]
    if entry["metric"] == "reproducibility":
        got = _jsonable(metrics.reproducibility(group))
    else:
        got = metrics.summarize_experiment(group)[entry["metric"]]
    assert got == entry["expected"], entry["reason"]


# --- backtest accuracy ------------------------------------------------------------------------
REPORTED = {
    "cumulative_return_pct": 73.39,
    "win_rate_pct": 61.11,
    "max_drawdown_pct": -14.17,
    "trades": 18,
}


class StubTools:
    """A backtest tool that answers by holding days: 10 as reported, 20 with another win rate."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        output = {"result_id": "stub-result", **REPORTED}
        if arguments["holding_days"] == 20:
            output["win_rate_pct"] = 55.56
        return output


def _backtest_call(seq, output, *, allowed=True, holding_days=10):
    return {
        "seq": seq,
        "state": "RUN_BACKTEST",
        "tool": "run_backtest",
        "arguments": {"ticker": "TOASO", "holding_days": holding_days},
        "output": output,
        "allowed": allowed,
        "source": "model",
    }


def _with_calls(*calls, qid="FX-90", repeat=0):
    return {"experiment": "D", "question_id": qid, "repeat": repeat, "tool_calls": list(calls)}


def test_the_labelled_sample_backtest_accuracy_is_the_hand_written_one(labelled):
    tools = StubTools()
    records = list(labelled.values())
    expected = EXPECTED["backtest"]
    check = metrics.backtest_check(records, tools)
    assert check["compared"] == expected["compared"]
    assert check["matched"] == expected["matched"]
    assert check["accuracy"] == expected["accuracy"], expected["reason"]
    assert check["mismatches"] == expected["mismatches"]
    assert metrics.backtest_accuracy(records, StubTools()) == expected["accuracy"]
    assert [name for name, _ in tools.calls] == ["run_backtest"] * 2
    assert {c[1]["holding_days"] for c in tools.calls} == {10, 20}


def test_every_reported_field_must_match_exactly():
    for field, value in (
        ("cumulative_return_pct", 73.4),
        ("max_drawdown_pct", -14.1),
        ("trades", 19),
    ):
        record = _with_calls(_backtest_call(1, {"result_id": "x", **REPORTED, field: value}))
        check = metrics.backtest_check([record], StubTools())
        assert check["accuracy"] == 0.0
        assert [m["field"] for m in check["mismatches"]] == [field]


def test_a_matching_call_is_a_hit_and_other_fields_are_not_compared():
    output = {"result_id": "another", "sharpe": 9.99, "signals": 1, **REPORTED}
    record = _with_calls(_backtest_call(1, output))
    check = metrics.backtest_check([record], StubTools())
    assert (check["compared"], check["matched"], check["accuracy"]) == (1, 1, 1.0)
    assert check["mismatches"] == []


def test_only_allowed_error_free_run_backtest_calls_count():
    other = {**_backtest_call(1, {"result_id": "x", **REPORTED}), "tool": "get_stock_history"}
    refused = _backtest_call(2, {"error": {"code": "SCHEMA"}}, allowed=False)
    failed = _backtest_call(3, {"error": {"code": "NO_DATA"}})
    tools = StubTools()
    assert metrics.backtest_accuracy([_with_calls(other, refused, failed)], tools) is None
    assert tools.calls == []
    assert metrics.backtest_accuracy([], tools) is None


def test_a_rerun_that_fails_or_returns_an_error_is_a_mismatch():
    record = _with_calls(_backtest_call(1, {"result_id": "x", **REPORTED}))

    def raises(name, arguments):
        raise RuntimeError("no data")

    def errors(name, arguments):
        return {"error": {"code": "NO_DATA"}}

    for tool in (raises, errors):
        check = metrics.backtest_check([record], tool)
        assert check["accuracy"] == 0.0
        assert check["mismatches"] == [
            {"call": "D/FX-90/r0#1", "field": "rerun", "reported": None, "recomputed": None}
        ]


def test_the_summary_gets_a_backtest_block_only_when_asked(labelled):
    records = list(labelled.values())
    plain = run_eval.summarize_records(records, call_tool=None)
    assert "backtest_accuracy" not in plain["D"]
    asked = run_eval.summarize_records(records, call_tool=StubTools(), backtest_accuracy=True)
    block = asked["D"]["backtest_accuracy"]
    assert block["accuracy"] == EXPECTED["backtest"]["accuracy"]
    assert block["compared"] == 2
    assert set(block["mismatches"][0]) == {"call", "field", "reported", "recomputed"}
    assert {k: v for k, v in asked["D"].items() if k != "backtest_accuracy"} == plain["D"]


def test_the_command_line_has_an_opt_in_backtest_accuracy_flag():
    parser = run_eval.build_parser()
    assert parser.parse_args([]).backtest_accuracy is False
    assert parser.parse_args(["--backtest-accuracy"]).backtest_accuracy is True


# --- the definitions in the report ------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
METRIC_NAMES = (
    "numeric_hallucination_rate",
    "model_numeric_hallucination_rate",
    "uncited_number_rate",
    "wrong_tool_call_rate",
    "unsupported_conclusion_rate",
    "evidence_completeness",
    "reproducibility_rate",
    "rule_violations",
    "tool_calls_total",
    "harness_interventions",
    "explanation_fallbacks",
    "scenario_accuracy",
    "ticker_accuracy_grounded",
    "ticker_accuracy_raw",
    "invented_fields",
    "latency_s_median",
    "backtest_accuracy",
)


def test_docs_metrics_defines_every_metric_with_numerator_and_denominator():
    text = (ROOT / "docs" / "metrics.md").read_text(encoding="utf-8")
    for name in METRIC_NAMES:
        assert f"`{name}`" in text, name
    assert text.count("**Payı:**") >= len(METRIC_NAMES) - 5
    assert text.count("**Paydası:**") >= len(METRIC_NAMES) - 5
    assert "**Sınırlar:**" in text
    assert "bağımsız" in text


def test_the_module_docstring_points_to_the_report_definitions():
    assert "docs/metrics.md" in (metrics.__doc__ or "")
    assert "backtest_accuracy" in (metrics.__doc__ or "")
