"""The templated question generator and the frozen-set overlap filter (Sprint 5, Task 2).

Frozen question text is never copied here: a test that needs one loads it by id.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from bist_harness.eval import questions as frozen
from bist_harness.finetune import questions as fq
from bist_harness.finetune.teacher import Gold
from bist_harness.harness.intent import (
    GUARDED_SCENARIOS,
    INTENT_SCHEMA,
    Intent,
    detect_language,
    ground_intent,
    keyword_guard,
)
from bist_harness.tools.schemas import ACTIONS

CUTOFF = "2025-01-01"


@pytest.fixture(scope="module")
def sample() -> list[fq.GenQuestion]:
    return fq.generate(20)


def test_generation_is_deterministic():
    a, b = fq.generate(6, seed=42), fq.generate(6, seed=42)
    assert [(q.question_id, q.text, q.gold, q.today) for q in a] == [
        (q.question_id, q.text, q.gold, q.today) for q in b
    ]
    other = fq.generate(6, seed=7)
    assert [q.text for q in other] != [q.text for q in a]


def test_ids_are_unique_and_stable(sample):
    ids = [q.question_id for q in sample]
    assert len(set(ids)) == len(ids)
    assert ids[0] == f"{sample[0].family}-0000"
    assert {q.family for q in sample} == set(fq.FAMILIES)
    assert all(sum(q.family == f for q in sample) == 20 for f in fq.FAMILIES)


def test_every_family_has_both_languages(sample):
    for name, family in fq.FAMILIES.items():
        assert set(family.templates) == {"tr", "en"}, name
        assert all(len(t) >= 4 for t in family.templates.values()), name
        assert {q.language for q in sample if q.family == name} == {"tr", "en"}, name


def test_gold_intent_matches_schema(sample):
    keys = set(INTENT_SCHEMA["required"])
    for q in sample:
        assert set(q.gold.intent) == keys, q.question_id
        assert q.gold.intent["language"] == q.language
        assert q.gold.intent["scenario"] in INTENT_SCHEMA["properties"]["scenario"]["enum"]


def test_no_date_after_test_period_start(sample):
    for q in sample:
        assert q.today < CUTOFF, q.question_id
        for key in ("start", "end", "as_of"):
            value = q.gold.intent[key]
            assert value is None or value < CUTOFF, (q.question_id, key)


def test_dates_follow_today_except_future_date_family(sample):
    for q in sample:
        i = q.gold.intent
        if q.family == "future_date":
            assert i["start"] > q.today and i["start"] < i["end"]
        elif i["end"] is not None:
            assert i["start"] < i["end"] <= q.today, q.question_id


def test_grounding_leaves_every_generated_gold_intent_unchanged():
    for q in fq.generate(40):
        intent = Intent(**q.gold.intent)
        grounded = ground_intent(intent, q.text)
        assert grounded == intent, (q.question_id, q.text)
        assert grounded.grounded == {}, (q.question_id, q.text)


def test_dated_questions_state_their_dates_and_undated_none(sample):
    for q in sample:
        if q.gold.intent["start"] is None:
            assert not any(ch.isdigit() for ch in q.text), q.text
        else:
            assert q.gold.intent["end"] is not None


def test_keyword_guard_agrees_with_the_gold_scenario(sample):
    for q in sample:
        scenario = q.gold.intent["scenario"]
        found = keyword_guard(q.text)
        if scenario in ("ADVICE_REQUEST", "PREDICTION_REQUEST"):
            assert found == scenario, (q.question_id, q.text)
        else:
            assert found is None, (q.question_id, q.text)


def test_negative_families_have_the_documented_golds(sample):
    by_family = {}
    for q in sample:
        by_family.setdefault(q.family, []).append(q.gold.intent)
    assert {i["scenario"] for i in by_family["advice_request"]} == {"ADVICE_REQUEST"}
    assert {i["scenario"] for i in by_family["prediction_request"]} == {"PREDICTION_REQUEST"}
    assert {i["scenario"] for i in by_family["no_tool_greeting"]} == {"OUT_OF_SCOPE"}
    assert {i["scenario"] for i in by_family["no_tool_off_topic"]} == {"OUT_OF_SCOPE"}
    from bist_harness.universe import is_in_universe

    assert all(not is_in_universe(i["ticker"]) for i in by_family["out_of_universe"])
    assert all(i["ticker"] is None for i in by_family["missing_information"])
    assert all(i["scenario"] not in GUARDED_SCENARIOS for i in by_family["missing_information"])


def test_all_mandatory_scenarios_and_extras_are_covered(sample):
    scenarios = {q.gold.intent["scenario"] for q in sample}
    assert scenarios >= {
        "SECTOR_LAGGARD",
        "CALENDAR_PATTERN",
        "TECHNICAL_REVERSAL",
        "FUNDAMENTAL_REACTION",
        "BACKTEST",
        "PRICE_SUMMARY",
        "MACRO_CONTEXT",
        "NEWS_CONTEXT",
    }


def test_every_action_label_is_reachable_from_some_family():
    """ANALYSIS_UNSAFE comes from the gate on real data; the others by the teacher's
    default preference or an explicit gold action (the table is checked in Task 3)."""
    explicit = {f.action for f in fq.FAMILIES.values() if f.action}
    assert explicit <= set(ACTIONS)
    assert "HOLD" in explicit
    assert fq.REACHABLE_BY_DEFAULT | explicit | {"ANALYSIS_UNSAFE"} == set(ACTIONS)


def test_language_of_every_question_is_what_the_harness_would_detect(sample):
    for q in sample:
        assert detect_language(q.text) in (q.language, None), q.text


def test_gold_objects_are_teacher_golds(sample):
    assert all(isinstance(q.gold, Gold) for q in sample)


def test_generated_questions_never_overlap_frozen_set(sample):
    kept, dropped = fq.drop_overlaps(sample)
    assert frozen.overlaps([q.text for q in kept]) == []
    assert len(kept) + len(dropped) == len(sample)
    assert len(kept) > 0.9 * len(sample)


def test_a_frozen_question_is_dropped_by_text_and_by_triple(sample):
    pool = frozen.load_questions()
    by_id = {q["id"]: q for q in pool}
    dated = next(
        q
        for q in pool
        if all(q["expected"][k] for k in ("ticker", "start", "end")) and q["lang"] in ("tr", "en")
    )
    base = sample[0]
    copy = replace(base, question_id="copy-0000", text=by_id[dated["id"]]["question"])
    triple_gold = Gold(
        {
            **base.gold.intent,
            "ticker": dated["expected"]["ticker"],
            "start": dated["expected"]["start"],
            "end": dated["expected"]["end"],
        }
    )
    triple = replace(base, question_id="triple-0000", text="Zzz qqq xxx.", gold=triple_gold)
    kept, dropped = fq.drop_overlaps([copy, triple, base])
    assert [q.question_id for q in kept] == [base.question_id]
    reasons = {d["question_id"]: d["reason"] for d in dropped}
    assert reasons == {"copy-0000": "text_overlap", "triple-0000": "expected_triple"}
    assert all(d["frozen_id"] == dated["id"] for d in dropped)


def test_diacritic_free_turkish_forms_exist(sample):
    tr = [q.text for q in fq.generate(60) if q.language == "tr"]
    assert any(not any(c in "ıİşŞğĞüÜöÖçÇ" for c in t) for t in tr)
    assert any(any(c in "ıİşŞğĞüÜöÖçÇ" for c in t) for t in tr)


# --- the paraphrase template (Task 3 splits by it) -----------------------------------------
# SHA-256 of generate(4)'s ids, texts, golds and todays before the template field was added:
# exposing the template must not change a single generated question.
GENERATE_4_SHA256 = "1820d1fe1d384026091b7ac60c10477903d3d6f4c1e98b3f8d589514579540ec"


def test_exposing_the_template_leaves_generation_unchanged():
    import hashlib
    import json

    rows = [[q.question_id, q.text, q.gold.intent, q.gold.action, q.today] for q in fq.generate(4)]
    text = json.dumps(rows, ensure_ascii=False)
    assert hashlib.sha256(text.encode()).hexdigest() == GENERATE_4_SHA256


def test_every_question_names_the_paraphrase_it_was_written_from(sample):
    import re

    plain = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC")
    for q in sample:
        assert q.template in fq.FAMILIES[q.family].templates[q.language], q.question_id
        text = q.text.translate(plain)
        fixed = [p for p in re.split(r"\{\w+\}", q.template) if p.strip()]
        assert all(p.translate(plain) in text for p in fixed), (q.template, q.text)
