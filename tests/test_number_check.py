"""Numeric-hallucination check: every number in an answer must come from a tool output."""

import pytest

from bist_harness.eval.number_check import (
    collect_numbers,
    extract_numbers,
    find_unsupported_numbers,
    numbers_match,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Success rate was 62.5% over 24 events.", [62.5, 24.0]),
        ("Başarı oranı %62,5; 24 olay.", [62.5, 24.0]),
        ("Toplam 1.234,56 ve 1,234.56", [1234.56, 1234.56]),
        ("Between 2020-01-01 and 2024-12-31 (E1, E2)", []),
        ("ASELS -3.2% (result_id 9f3a1c0b7e2d)", [-3.2]),
        ("Ortalama getiri −1,25 oldu.", [-1.25]),  # Unicode minus sign
        ("Volume 1,250,000 shares", [1250000.0]),
        ("5 günlük getiri: 0.75%.", [5.0, 0.75]),
        ("No numbers here.", []),
    ],
)
def test_extract_numbers(text, expected):
    assert extract_numbers(text) == expected


def test_known_identifier_shapes_are_not_numbers():
    text = "Tool get_stock_history; evidence E12; result 9f3a1c0b7e2d; index XU100; BIST 100; ticker ISMEN"
    assert extract_numbers(text) == []


def test_digits_glued_to_other_words_are_still_numbers():
    # Skipping every letter-adjacent digit would let "TL62.5" or "7x" through unchecked.
    assert extract_numbers("model qwen3.5 and code A1B2") == [3.5, 1.0, 2.0]


# Decision K-008 (docs/decision-log.md): two numbers are the same only when they are
# equal after rounding to two decimals. No percent<->fraction conversion, no rounding
# to integers, no sign changes.
@pytest.mark.parametrize(
    "claimed,source,expected",
    [
        (62.5, 62.5, True),  # exact
        (62.5, 62.50, True),  # trailing zero
        (62.5, 62.504, True),  # source carries more decimals than the tool rounds to
        (62.5, 0.625, False),  # percent versus fraction
        (63, 62.5, False),  # "about 63"
        (62.4, 62.5, False),  # small difference
        (-3.2, 3.2, False),  # sign
        (24, 24.0, True),  # integer count
    ],
)
def test_numbers_match_rule(claimed, source, expected):
    assert numbers_match(claimed, source) is expected


def test_collect_numbers_walks_nested_tool_output_and_skips_booleans():
    output = {
        "event_count": 24,
        "ok": True,
        "nested": {"success_rate_pct": 62.5, "list": [1.5, {"x": -2}]},
        "label": "ASELS",
        "none": None,
    }
    assert sorted(collect_numbers(output)) == [-2.0, 1.5, 24.0, 62.5]


def test_numbers_inside_tool_output_strings_do_not_count_as_support():
    output = {"first_date": "2020-01-02", "note": "window 20, 2 std"}
    assert find_unsupported_numbers("Window 20 with 2 std.", [output]) == [20.0, 2.0]


def test_invented_number_is_flagged():
    out = [{"success_rate_pct": 62.5, "event_count": 24}]
    assert find_unsupported_numbers("62.5% of 24 events, average 9.9%.", out) == [9.9]


def test_allowed_numbers_from_the_question_are_not_flagged():
    out = [{"success_rate_pct": 62.5}]
    assert find_unsupported_numbers("Over 5 days: 62.5%.", out, allowed=[5]) == []


def test_answer_without_numbers_has_nothing_unsupported():
    assert find_unsupported_numbers("The system is educational.", []) == []


def test_each_unsupported_value_is_reported_once():
    assert find_unsupported_numbers("9.9 and again 9.9", [{"a": 1}]) == [9.9]
