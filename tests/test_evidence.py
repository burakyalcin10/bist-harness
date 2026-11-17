"""The evidence builder: templated sentences E1..En and the committed evidence set (EC-043).

The tool outputs are the golden outputs of the contract tests, so the sentences are built
from the real output shapes. No model, network or data folder is involved.
"""

import copy
import json
import re
import string
from pathlib import Path

import pytest

from bist_harness.eval.number_check import dates_in, extract_numbers, numbers_match
from bist_harness.harness import evidence as ev
from bist_harness.harness import session
from bist_harness.harness.evidence import TEMPLATES, build_evidence, committed_set
from bist_harness.harness.intent import SCENARIOS
from bist_harness.mcp_server import server as srv

GOLDEN = Path(__file__).parent / "golden"
EVIDENCE_TOOLS = (
    "get_stock_history",
    "get_index_history",
    "calculate_indicators",
    "find_support_resistance",
    "rank_sector_relative_strength",
    "detect_reversal_events",
    "test_weekday_pattern",
    "get_fundamental_metrics",
    "calculate_fundamental_change",
    "get_macro_context",
    "get_news_events",
    "run_backtest",
)


def golden(tool: str) -> dict:
    return json.loads((GOLDEN / f"{tool}.ok.json").read_text(encoding="utf-8"))


def make_analysis(tools=EVIDENCE_TOOLS, *, scenario="SECTOR_LAGGARD", language="en", outputs=None):
    """An analysis whose calls return the golden outputs (or the given ones)."""
    analysis = session.Analysis(
        analysis_id="AN-test00000001",
        question="test",
        created_at="2026-11-17T00:00:00+00:00",
        model="fake",
        snapshot_id="golden-snapshot",
        adjustments_id="adj00000",
        intent={"scenario": scenario, "language": language},
    )
    for tool in tools:
        output = (outputs or {}).get(tool) or golden(tool)
        session.record_call(analysis, state="X", tool=tool, arguments={}, output=output)
    return analysis


# --- scope: the fields a sentence is allowed to draw from --------------------------------
ROW = re.compile(r"^(\w+)\[(.+?)\]\.(\w+)$")


def template_key(item) -> tuple[str, str]:
    return item.tool, ROW.sub(lambda m: f"{m[1]}.{m[3]}", item.field)


def scope_of(output: dict, field: str) -> dict:
    """Top-level scalars of the output plus the row a bracketed field path points at."""
    scope = {k: v for k, v in output.items() if not isinstance(v, dict | list)}
    match = ROW.match(field)
    if match:
        container, key, _ = match.groups()
        rows = output[container]
        row = rows[key] if isinstance(rows, dict) else next(r for r in rows if key in r.values())
        scope.update(row)
    return scope


def placeholders(template: str) -> list[str]:
    return [name for _, name, _, _ in string.Formatter().parse(template) if name]


def allowed_numbers(item, output: dict, language: str) -> list[float]:
    """Numbers of the fields named in the template (strings may carry digits, e.g. 2025Q3)."""
    scope = scope_of(output, item.field)
    numbers: list[float] = []
    for name in placeholders(TEMPLATES[template_key(item)][language]):
        value = scope[name]
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            numbers.append(float(value))
        elif isinstance(value, str):
            numbers.extend(extract_numbers(value))
    return numbers


def items_of(language: str, **kwargs):
    analysis = make_analysis(language=language, **kwargs)
    outputs = {c.tool: c.output for c in analysis.tool_calls}
    return build_evidence(analysis, language=language), outputs


# --- one template per (tool, field), TR and EN -------------------------------------------
def test_every_template_has_a_turkish_and_an_english_sentence():
    assert TEMPLATES
    for key, texts in TEMPLATES.items():
        assert set(texts) == {"tr", "en"}, key
        assert all(texts[lang].strip() for lang in texts), key
        assert key[0] in EVIDENCE_TOOLS


def test_every_template_is_used_on_the_golden_outputs():
    items, _ = items_of("en")
    assert {template_key(i) for i in items} == set(TEMPLATES)


@pytest.mark.parametrize("language", ["tr", "en"])
def test_a_sentence_holds_only_the_numbers_of_its_own_field(language):
    items, outputs = items_of(language)
    assert items
    for item in items:
        allowed = allowed_numbers(item, outputs[item.tool], language)
        found = extract_numbers(item.sentence)
        assert len(found) == len(allowed), (item.field, item.sentence)
        for number in found:
            assert any(numbers_match(number, a) for a in allowed), (item.field, item.sentence)
        for number in allowed:
            assert any(numbers_match(f, number) for f in found), (item.field, item.sentence)


@pytest.mark.parametrize("language", ["tr", "en"])
def test_dates_of_a_sentence_come_from_its_output(language):
    items, outputs = items_of(language)
    assert items
    for item in items:
        known = set(dates_in(json.dumps(outputs[item.tool])))
        assert set(dates_in(item.sentence)) <= known, item.sentence


def test_the_field_value_is_copied_from_the_tool_output():
    items, outputs = items_of("en")
    assert items
    for item in items:
        scope = scope_of(outputs[item.tool], item.field)
        assert item.value == scope[item.field.rsplit(".", 1)[-1]], item.field
        assert item.result_id == outputs[item.tool]["result_id"]


def test_turkish_sentence_uses_a_decimal_comma_and_stays_readable_by_the_number_check():
    items, _ = items_of("tr")
    rate = next(i for i in items if i.field == "success_rate_pct")
    assert rate.sentence == (
        "Teknik dönüş olaylarında başarı oranı %80,00 (BOLLINGER_LOWER_TOUCH, ASELS)."
    )
    assert extract_numbers(rate.sentence) == [80.0]
    stock = next(
        i for i in items if i.tool == "get_stock_history" and i.field == "period_return_pct"
    )
    assert "32,80" in stock.sentence and not re.search(r"\d\.\d", stock.sentence)


def test_english_sentence_uses_a_decimal_point():
    items, _ = items_of("en")
    rate = next(i for i in items if i.field == "success_rate_pct")
    assert rate.sentence == (
        "Success rate of the technical reversal events was 80.00% (BOLLINGER_LOWER_TOUCH, ASELS)."
    )


def test_a_sentence_states_the_meaning_of_the_field_with_its_count():
    items, _ = items_of("tr")
    wins = next(i for i in items if i.field == "successful_events")
    assert "10" in wins.sentence and "8" in wins.sentence and "başarılı" in wins.sentence
    items, _ = items_of("en")
    wins = next(i for i in items if i.field == "successful_events")
    assert "8 of the 10" in wins.sentence


def test_a_negative_value_keeps_its_sign():
    items, _ = items_of("en")
    drawdown = next(i for i in items if i.field == "max_drawdown_pct")
    assert extract_numbers(drawdown.sentence) == [-14.17]
    assert not numbers_match(extract_numbers(drawdown.sentence)[0], 14.17)


def test_a_value_with_more_decimals_is_written_at_two_so_a_turkish_comma_is_not_a_thousands_mark():
    assert golden("get_macro_context")["usdtry_start"] == 31.132
    items, _ = items_of("tr", tools=("get_macro_context",))
    assert items
    for item in items:
        assert not re.search(r"\d,\d{3}(?!\d)", item.sentence), item.sentence


def test_a_p_value_keeps_its_four_decimals():
    items, _ = items_of("en")
    p = next(i for i in items if i.field == "p_value")
    assert "0.7196" in p.sentence
    assert numbers_match(extract_numbers(p.sentence)[0], 0.7196)


def test_a_p_value_of_one_is_not_written_with_four_decimals():
    # "1.0000" would be read as the thousands group "1.000" followed by "0".
    items, _ = items_of("en")
    bonferroni = next(i for i in items if i.field == "p_value_bonferroni")
    assert bonferroni.value == 1.0 and "1.00." in bonferroni.sentence
    assert extract_numbers(bonferroni.sentence) == [1.0]


def test_a_boolean_or_text_field_gives_a_sentence_without_numbers():
    items, _ = items_of("en")
    strong = next(i for i in items if i.field == "sector_strong")
    assert extract_numbers(strong.sentence) == []
    state = next(i for i in items if i.field == "rsi_state")
    assert "neutral" in state.sentence.lower()


# --- missing values, errors, permissions -------------------------------------------------
def test_a_field_with_no_value_gives_no_sentence():
    output = golden("calculate_indicators")
    output["rsi"] = None
    output["rsi_state"] = None
    items, _ = items_of(
        "en", tools=("calculate_indicators",), outputs={"calculate_indicators": output}
    )
    fields = {i.field for i in items}
    assert "rsi" not in fields and "rsi_state" not in fields and "macd" in fields


def test_a_null_value_is_not_written_as_text():
    items, _ = items_of("en")
    assert items
    assert not any("None" in i.sentence or "null" in i.sentence for i in items)


def test_an_error_output_gives_no_evidence():
    error = {"error": {"code": "DATA_UNAVAILABLE", "message": "no data"}}
    items, _ = items_of("en", tools=("run_backtest",), outputs={"run_backtest": error})
    assert items == []


def test_a_call_that_was_not_allowed_gives_no_evidence():
    analysis = make_analysis(("run_backtest",))
    assert build_evidence(analysis, language="en")  # allowed, it has evidence
    analysis.tool_calls[0].allowed = False
    assert build_evidence(analysis, language="en") == []


def test_tools_without_a_template_give_no_evidence():
    analysis = make_analysis(("get_stock_history",))
    session.record_call(
        analysis,
        state="X",
        tool="check_data_quality",
        arguments={},
        output=golden("check_data_quality"),
    )
    assert {i.tool for i in build_evidence(analysis, language="en")} == {"get_stock_history"}


def test_the_same_result_called_twice_is_one_set_of_sentences():
    once = make_analysis(("run_backtest",))
    twice = make_analysis(("run_backtest", "run_backtest"))
    assert build_evidence(once, language="en")
    assert len(build_evidence(twice, language="en")) == len(build_evidence(once, language="en"))


# --- labels and determinism --------------------------------------------------------------
@pytest.mark.parametrize("language", ["tr", "en"])
def test_labels_run_from_e1_without_a_gap(language):
    items, _ = items_of(language)
    assert items
    assert [i.label for i in items] == [f"E{n}" for n in range(1, len(items) + 1)]


def test_the_same_analysis_gives_the_same_list_twice():
    analysis = make_analysis()
    first = build_evidence(analysis, language="en")
    assert first and first == build_evidence(analysis, language="en")
    assert build_evidence(analysis, language="tr") == build_evidence(
        copy.deepcopy(analysis), language="tr"
    )


def test_the_two_languages_give_the_same_labels_fields_and_values():
    en, _ = items_of("en")
    tr, _ = items_of("tr")
    assert en
    assert [(i.label, i.tool, i.field, i.value, i.result_id) for i in en] == [
        (i.label, i.tool, i.field, i.value, i.result_id) for i in tr
    ]
    assert all(a.sentence != b.sentence for a, b in zip(en, tr, strict=True))


# --- warnings are not evidence -----------------------------------------------------------
def test_warnings_are_carried_separately_and_never_become_sentences():
    analysis = make_analysis()
    items = build_evidence(analysis, language="en")
    banned = {"sample_warning", "coverage_warning", "warnings", "flags", "interpretation_flags"}
    assert not banned & {i.field for i in items}
    found = ev.collect_warnings(analysis)
    texts = {w["text"] for w in found}
    assert "Limited sample size" in texts  # sample_warning of the reversal and backtest tools
    assert "UNDERPERFORMS_XU100" in texts  # a backtest flag
    assert "NOT_SIGNIFICANT" in texts  # an interpretation flag
    assert any(t.startswith("NO_DATA") for t in texts)  # a tool warning
    assert all({"tool", "result_id", "text"} <= set(w) for w in found)
    assert ev.DISCLAIMER["en"] in {w["text"] for w in ev.collect_warnings(analysis, language="en")}


def test_a_null_warning_is_not_carried():
    analysis = make_analysis(("get_stock_history",))
    assert [w for w in ev.collect_warnings(analysis) if w["tool"] == "get_stock_history"] == []


# --- the committed evidence set ----------------------------------------------------------
REQUIRED_PER_SCENARIO = {
    "SECTOR_LAGGARD": {
        "sector_median": ("rank_sector_relative_strength", "sector_median_return_pct"),
        "lag_score": ("rank_sector_relative_strength", "members.lag_score_pct"),
        "sector_vs_index": ("rank_sector_relative_strength", "sector_strong"),
        "technical_state": ("calculate_indicators", "rsi_state"),
        "backtest_summary": ("run_backtest", "win_rate_pct"),
    },
    "CALENDAR_PATTERN": {
        "pattern_result": ("test_weekday_pattern", "spread_pct"),
        "significance": ("test_weekday_pattern", "p_value"),
        "backtest_summary": ("run_backtest", "win_rate_pct"),
    },
    "TECHNICAL_REVERSAL": {
        "reversal_stats": ("detect_reversal_events", "success_rate_pct"),
        "technical_state": ("calculate_indicators", "rsi_state"),
        "backtest_summary": ("run_backtest", "win_rate_pct"),
    },
    "FUNDAMENTAL_REACTION": {
        "fundamental_change": ("calculate_fundamental_change", "fundamental_trend"),
        "price_reaction": ("calculate_fundamental_change", "quarters.reaction_5d_pct"),
        "technical_state": ("calculate_indicators", "rsi_state"),
        "backtest_summary": ("run_backtest", "win_rate_pct"),
    },
    "BACKTEST": {
        "backtest_summary": ("run_backtest", "win_rate_pct"),
        "benchmark_comparison": ("run_backtest", "excess_vs_xu100_pct"),
    },
    "PRICE_SUMMARY": {
        "price_change": ("get_stock_history", "period_return_pct"),
        "technical_state": ("calculate_indicators", "rsi_state"),
    },
    "MACRO_CONTEXT": {"macro_context": ("get_macro_context", "policy_rate_end")},
    "NEWS_CONTEXT": {"news_count": ("get_news_events", "total")},
}


def test_every_scenario_is_known_to_the_rules():
    assert set(REQUIRED_PER_SCENARIO) <= set(SCENARIOS)
    guarded = set(SCENARIOS) - set(REQUIRED_PER_SCENARIO)
    assert guarded == {"ADVICE_REQUEST", "PREDICTION_REQUEST", "OUT_OF_SCOPE"}
    items, _ = items_of("en")
    assert items
    for scenario in guarded:
        assert committed_set(items, scenario) == []
        assert ev.missing_requirements(items, scenario) == []


@pytest.mark.parametrize("scenario", sorted(REQUIRED_PER_SCENARIO))
def test_the_committed_set_holds_the_minimum_evidence_of_its_scenario(scenario):
    analysis = make_analysis(scenario=scenario)
    items = build_evidence(analysis, language="en")
    committed = committed_set(items, scenario)
    assert committed
    assert ev.missing_requirements(items, scenario) == []
    keys = {template_key(i) for i in committed}
    for name, key in REQUIRED_PER_SCENARIO[scenario].items():
        assert key in keys, (scenario, name)
    assert all(i.committed for i in committed)
    assert committed == [i for i in items if i.committed]


def test_the_committed_set_of_a_sector_laggard_is_not_everything_observed():
    items = build_evidence(make_analysis(), language="en")
    committed = committed_set(items, "SECTOR_LAGGARD")
    assert {i.tool for i in committed} == {
        "rank_sector_relative_strength",
        "calculate_indicators",
        "run_backtest",
    }
    assert 0 < len(committed) < len(items)


@pytest.mark.parametrize("scenario", sorted(REQUIRED_PER_SCENARIO))
def test_a_missing_kind_of_evidence_is_reported_and_nothing_is_invented(scenario):
    for name, (tool, _) in REQUIRED_PER_SCENARIO[scenario].items():
        tools = tuple(t for t in EVIDENCE_TOOLS if t != tool)
        items = build_evidence(make_analysis(tools, scenario=scenario), language="en")
        committed = committed_set(items, scenario)
        missing = ev.missing_requirements(items, scenario)
        assert name in missing, (scenario, name)
        assert all(i.tool != tool for i in committed)  # nothing from the absent tool
        assert set(committed) <= set(items)  # only items that exist


def test_the_committed_flag_follows_the_scenario_of_the_analysis():
    laggard = build_evidence(make_analysis(scenario="SECTOR_LAGGARD"), language="en")
    price = build_evidence(make_analysis(scenario="PRICE_SUMMARY"), language="en")
    assert {i.label for i in laggard if i.committed} != {i.label for i in price if i.committed}
    assert committed_set(laggard, "SECTOR_LAGGARD") == [i for i in laggard if i.committed]


def test_the_same_analysis_gives_the_same_committed_set_twice():
    analysis = make_analysis()
    first = committed_set(build_evidence(analysis, language="en"), "SECTOR_LAGGARD")
    second = committed_set(build_evidence(analysis, language="en"), "SECTOR_LAGGARD")
    assert first and first == second


def test_only_the_analysed_stock_gets_a_lag_score_sentence():
    items, _ = items_of("en")
    assert [i.field for i in items if i.field.endswith("lag_score_pct")] == [
        "members[AKBNK].lag_score_pct"
    ]


# --- the MCP tool ------------------------------------------------------------------------
@pytest.fixture
def registered(monkeypatch):
    monkeypatch.setattr(srv, "current_snapshot_id", lambda: "golden-snapshot")
    monkeypatch.setattr(srv, "current_adjustments_id", lambda: "adj00000")
    monkeypatch.setattr(srv, "current_layers_id", lambda: "lay00000")
    analysis = make_analysis(language="tr")
    session._LIVE[analysis.analysis_id] = analysis
    yield analysis
    session._LIVE.pop(analysis.analysis_id, None)


def test_the_bundle_tool_returns_evidence_committed_set_warnings_and_versions(registered):
    output = srv.build_evidence_bundle(registered.analysis_id)
    assert "error" not in output, output
    assert re.fullmatch(r"[0-9a-f]{12}", output["result_id"])
    assert output["snapshot_id"] == "golden-snapshot" and output["adjustments_id"] == "adj00000"
    assert output["scenario"] == "SECTOR_LAGGARD" and output["language"] == "tr"
    expected = build_evidence(registered, language="tr")
    assert [e["label"] for e in output["evidence"]] == [i.label for i in expected]
    assert output["evidence"][0]["sentence"] == expected[0].sentence
    assert output["committed_labels"] == [i.label for i in expected if i.committed]
    assert output["missing_requirements"] == []
    assert output["warnings"]
    json.dumps(output, allow_nan=False)


def test_the_bundle_tool_reports_a_missing_requirement(registered):
    registered.tool_calls = [c for c in registered.tool_calls if c.tool != "run_backtest"]
    output = srv.build_evidence_bundle(registered.analysis_id)
    assert output["missing_requirements"] == ["backtest_summary"]


def test_the_bundle_tool_is_deterministic_and_reports_an_unknown_analysis(registered):
    assert srv.build_evidence_bundle(registered.analysis_id) == srv.build_evidence_bundle(
        registered.analysis_id
    )
    assert srv.build_evidence_bundle("AN-unknown")["error"]["code"] == "UNKNOWN_ANALYSIS"
