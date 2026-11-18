"""The fine-tuning data quality checks (Sprint 5, Task 4).

Records come from a small build on the synthetic snapshot (never the real data folder); each
test breaks one record in one way and expects that check to fire.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from bist_harness.eval import questions as frozen
from bist_harness.finetune import qc
from bist_harness.finetune.record import TrainingRecord, read_jsonl, write_jsonl
from bist_harness.harness.evidence import DISCLAIMER
from bist_harness.harness.routes import ALLOWED_TOOLS
from bist_harness.tools.schemas import to_ollama_tools

from .test_finetune_build import run_build


@pytest.fixture(scope="module")
def records(tmp_path_factory):
    out, _ = run_build(tmp_path_factory.mktemp("ft-qc"), 3)
    found = []
    for name in ("train", "val", "test"):
        found += read_jsonl(out / f"{name}.jsonl")
    return found


def of_turn(records, turn, *, language=None):
    return [r for r in records if r.turn == turn and (language is None or r.language == language)]


def checks_of(record) -> list[str]:
    return [f.check for f in qc.run_qc([record])]


def with_explanation(record: TrainingRecord, edit) -> TrainingRecord:
    data = edit(json.loads(record.target["content"]))
    target = {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)}
    return dataclasses.replace(record, target=target)


def an_explanation(records, language="en") -> TrainingRecord:
    return of_turn(records, "explanation", language=language)[0]


# --- the order of the checks -------------------------------------------------------------------
def test_checks_in_the_agreed_order():
    assert qc.CHECKS == (
        "numbers_in_tool_output",
        "call_schema_valid",
        "call_allowed_and_on_intent",
        "label_in_eight",
        "no_advice_language",
        "validator_accepts",
        "no_frozen_overlap",
        "no_test_period_data",
    )


def test_every_record_of_a_correct_build_passes(records):
    assert qc.run_qc(records) == []


# --- explanation checks ------------------------------------------------------------------------
@pytest.mark.parametrize("language", ["tr", "en"])
def test_a_number_not_in_the_evidence_is_caught(records, language):
    good = an_explanation(records, language)
    extra = "Extra 12.35 points. [E1]"

    def edit(data):
        data["explanation"] = data["explanation"].replace(
            DISCLAIMER[language], extra + "\n" + DISCLAIMER[language]
        )
        return data

    assert "numbers_in_tool_output" in checks_of(with_explanation(good, edit))
    assert "numbers_in_tool_output" not in checks_of(good)


def test_an_action_outside_the_eight_labels_is_caught(records):
    good = an_explanation(records)
    bad = with_explanation(good, lambda d: {**d, "action": "BUY_NOW"})
    assert "label_in_eight" in checks_of(bad)
    assert "label_in_eight" not in checks_of(good)


def test_advice_language_is_caught_but_the_disclaimer_is_not(records):
    good = an_explanation(records, "tr")
    assert "no_advice_language" not in checks_of(good)  # the fixed lines are stripped first
    bad = with_explanation(
        good, lambda d: {**d, "explanation": d["explanation"] + "\nHisseyi alın. [E1]"}
    )
    assert "no_advice_language" in checks_of(bad)


def test_the_validator_rejects_a_missing_disclaimer(records):
    good = an_explanation(records)
    bad = with_explanation(
        good,
        lambda d: {**d, "explanation": d["explanation"].replace(DISCLAIMER[good.language], "")},
    )
    assert "validator_accepts" in checks_of(bad)
    assert "validator_accepts" not in checks_of(good)


def test_an_unreadable_explanation_turn_is_a_finding_not_a_crash(records):
    bad = dataclasses.replace(
        an_explanation(records), target={"role": "assistant", "content": "not json"}
    )
    assert "validator_accepts" in checks_of(bad)


# --- tool-call checks -----------------------------------------------------------------------------
def first_call(record):
    return record.target["tool_calls"][0]["function"]


def with_call(record: TrainingRecord, name=None, arguments=None, tools=None) -> TrainingRecord:
    call = json.loads(json.dumps(record.target["tool_calls"][0]))
    if name is not None:
        call["function"]["name"] = name
    if arguments is not None:
        call["function"]["arguments"] = arguments
    changes: dict = {"target": {"role": "assistant", "tool_calls": [call]}}
    if tools is not None:
        changes["tools"] = tools
    return dataclasses.replace(record, **changes)


def test_correct_tool_calls_pass(records):
    for record in of_turn(records, "tool_call")[:20]:
        assert checks_of(record) == []


def test_an_argument_the_schema_does_not_have_is_caught(records):
    good = of_turn(records, "tool_call")[0]
    arguments = {**first_call(good)["arguments"], "bogus": 1}
    assert "call_schema_valid" in checks_of(with_call(good, arguments=arguments))


def test_a_tool_the_record_did_not_offer_is_caught(records):
    good = of_turn(records, "tool_call")[0]
    assert "call_schema_valid" in checks_of(dataclasses.replace(good, tools=[]))


def test_a_tool_the_state_does_not_allow_is_caught(records):
    calls = {r.state: r for r in of_turn(records, "tool_call")}
    for state, record in calls.items():
        for other in calls.values():
            name = first_call(other)["name"]
            if name not in ALLOWED_TOOLS[state]:
                bad = with_call(
                    record,
                    name=name,
                    arguments=first_call(other)["arguments"],
                    tools=to_ollama_tools(),
                )
                assert "call_allowed_and_on_intent" in checks_of(bad)
                assert "call_schema_valid" not in checks_of(bad)
                return
    pytest.fail("no pair of states with a disallowed tool")


def test_a_ticker_the_question_did_not_name_is_caught(records):
    for record in of_turn(records, "tool_call"):
        arguments = first_call(record)["arguments"]
        if arguments.get("ticker"):
            other = "THYAO" if arguments["ticker"] != "THYAO" else "AKBNK"
            bad = with_call(record, arguments={**arguments, "ticker": other})
            assert "call_allowed_and_on_intent" in checks_of(bad)
            return
    pytest.fail("no tool call with a ticker")


# --- the frozen set and the test period -----------------------------------------------------------
def with_user_text(record: TrainingRecord, text: str, *, replace: bool = False) -> TrainingRecord:
    messages = [dict(m) for m in record.messages]
    old = messages[1]["content"]
    messages[1] = {**messages[1], "content": text if replace else old + text}
    return dataclasses.replace(record, messages=messages)


def test_a_question_copied_from_the_frozen_set_is_caught(records):
    good = of_turn(records, "intent")[0]
    bad = with_user_text(good, frozen.load_questions()[0]["question"], replace=True)
    assert "no_frozen_overlap" in checks_of(bad)
    assert "no_frozen_overlap" not in checks_of(good)


def test_a_test_period_date_is_caught(records):
    good = of_turn(records, "intent")[0]
    assert "no_test_period_data" not in checks_of(good)
    assert "no_test_period_data" in checks_of(with_user_text(good, " 2025-03-14"))


@pytest.mark.parametrize(
    "phrase",
    ["In the test period the share of winning trades was high.", "Test döneminde kazandı."],
)
def test_a_date_free_test_period_phrase_is_caught(records, phrase):
    good = of_turn(records, "intent")[0]
    assert "no_test_period_data" in checks_of(with_user_text(good, " " + phrase))


def test_the_phrases_come_from_the_templates():
    assert any("test period" in p for p in qc.TEST_PERIOD_PHRASES)
    assert any("test donem" in p for p in qc.TEST_PERIOD_PHRASES)


# --- dedupe -------------------------------------------------------------------------------------------
def renamed(record, question_id, family=None):
    return dataclasses.replace(
        record,
        question_id=question_id,
        record_id=record.record_id.replace(record.question_id, question_id),
        family=family or record.family,
    )


def one_question(records):
    first = records[0].question_id
    return [r for r in records if r.question_id == first]


def other_target(group, question_id, family=None):
    changed = [dataclasses.replace(r, target={"role": "assistant", "content": "{}"}) for r in group]
    return [renamed(r, question_id, family) for r in changed]


def test_dedupe_drops_a_copy_with_the_same_target_and_keeps_all_turns(records):
    group = one_question(records)
    copy = [renamed(r, "zz-copy") for r in group]
    kept, removed = qc.dedupe(group + copy)
    assert removed == len(group)
    assert {r.question_id for r in kept} == {group[0].question_id}
    assert len(kept) == len(group)


def test_dedupe_keeps_a_same_text_question_of_the_same_family_with_another_target(records):
    group = one_question(records)
    kept, removed = qc.dedupe(group + other_target(group, "zz-other"))
    assert removed == 0 and len(kept) == len(group) * 2


def test_dedupe_drops_the_later_of_two_families_teaching_one_text_two_targets(records):
    group = one_question(records)
    other = other_target(group, "aa-other", family="other_family")  # sorts first
    kept, removed = qc.dedupe(group + other)
    assert removed == len(group)
    assert {r.question_id for r in kept} == {"aa-other"}  # the first by question_id stays
    assert qc.dedupe_report(group + other)[1]["conflicting_target_questions"] == 1


def test_dedupe_keeps_a_question_with_a_different_text(records):
    group = one_question(records)
    far = [
        with_user_text(renamed(r, "zz-far"), " and then a long different tail", replace=False)
        for r in group
    ]
    kept, removed = qc.dedupe(group + far)
    assert removed == 0 and len(kept) == len(group) * 2


def test_dedupe_report_counts_what_it_drops(records):
    kept, report = qc.dedupe_report(records)
    assert report["records_removed"] == len(records) - len(kept)
    assert report["near_duplicate_questions"] + report["conflicting_target_questions"] <= len(
        records
    )


# --- the review sample ------------------------------------------------------------------------------
def test_sample_is_deterministic_and_stratified(records):
    a = qc.sample_for_review(records, 12, seed=42)
    b = qc.sample_for_review(records, 12, seed=42)
    assert [r.record_id for r in a] == [r.record_id for r in b]
    assert len({r.record_id for r in a}) == 12
    strata = {(r.scenario, r.turn) for r in records}
    assert len({(r.scenario, r.turn) for r in a}) == min(12, len(strata))
    other = qc.sample_for_review(records, 12, seed=1)
    assert [r.record_id for r in other] != [r.record_id for r in a]


# --- the command ------------------------------------------------------------------------------------------
def test_cli_writes_the_report_and_the_sample_and_leaves_the_data_alone(records, tmp_path):
    write_jsonl(records, tmp_path / "train.jsonl")
    before = (tmp_path / "train.jsonl").read_bytes()
    assert qc.main([str(tmp_path), "--sample", "10"]) == 0
    report = json.loads((tmp_path / "qc.json").read_text(encoding="utf-8"))
    assert list(report["counts"]) == list(qc.CHECKS)
    assert report["findings_total"] == 0 and report["records"] == len(records)
    assert "records_removed" in report["dedupe"]
    sample = (tmp_path / "review-sample.md").read_text(encoding="utf-8")
    assert sample.count("\n## ") == 10 and "**Question:**" in sample
    assert (tmp_path / "train.jsonl").read_bytes() == before
