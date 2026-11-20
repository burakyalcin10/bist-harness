"""The A-E experiment runner on three questions of the frozen set.

The model is a rule-based fake client and the tools are a fake ``call_tool`` built on the
golden outputs; no real model, network, data download or cloud SDK is involved.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

from bist_harness.eval import questions as qs
from bist_harness.eval import run_eval
from bist_harness.harness import machine, session
from bist_harness.harness.intent import Intent, parse_intent
from bist_harness.llm.client import ChatResult, ToolCall
from bist_harness.storage import db

TODAY = "2026-11-17"
GOLDEN = Path(__file__).parent / "golden"
IDS = ("AM-02", "TP-01", "TP-15")
# What the fake model reads from each question. TP-01 is an advice trap the fake model
# misses (it answers PRICE_SUMMARY); only a guard can stop it.
INTENTS = {
    "AM-02": {"scenario": "PRICE_SUMMARY", "ticker": "THYAO", "language": "tr"},
    "TP-01": {"scenario": "PRICE_SUMMARY", "ticker": "THYAO", "language": "tr"},
    "TP-15": {
        "scenario": "CALENDAR_PATTERN",
        "ticker": "FROTO",
        "start": "2025-09-30",
        "end": "2024-03-01",
        "language": "en",
    },
}
B_CALLS = [
    ToolCall("get_stock_history", {"ticker": "THYAO", "start": "2025-01-02", "end": "2025-06-30"}),
    ToolCall("calculate_indicators", {"ticker": "THYAO"}),  # misses required arguments
]
FREE_ANSWER = '{"action": "HOLD", "explanation": "The data was reviewed. You should buy THYAO."}'
_STATE = re.compile(
    r"Current state: (\w+)\..*ticker=(\S+), sector=(.+?), start=(\S+), end=(\S+), as_of=(\S+)\.",
    re.DOTALL,
)


def reply(content="", calls=()):
    return ChatResult(
        content=content,
        tool_calls=tuple(calls),
        prompt_tokens=0,
        completion_tokens=0,
        total_duration_s=0.0,
        eval_tokens_per_s=None,
        raw={},
        malformed_tool_call=False,
    )


def _none(value):
    return None if value == "None" else value


class RuleClient:
    """A deterministic stand-in for OllamaClient that answers by the kind of request."""

    model = "fake-model"

    def __init__(self, by_question, *, answers=None, bad_first_explanation=False):
        self.by_question = by_question  # question text -> intent fields
        self.answers = answers or {}  # question text -> free answer JSON (default FREE_ANSWER)
        self.bad_first_explanation = bad_first_explanation
        self.scenario = None
        self.requests = []

    def chat(self, messages, tools=None, **kwargs):
        self.requests.append({"messages": messages, "tools": tools, **kwargs})
        system = messages[0]["content"]
        schema = kwargs.get("response_format") or {}
        properties = schema.get("properties") or {}
        if "scenario" in properties:  # START: the intent
            fields = dict.fromkeys(("ticker", "sector", "start", "end", "as_of"))
            fields.update(self.by_question[messages[1]["content"]])
            self.scenario = fields["scenario"]
            return reply(json.dumps(fields))
        if tools and "Current state:" in system:  # a machine tool state
            found = _STATE.search(system)
            state, ticker, sector, start, end, as_of = found.groups()
            intent = Intent(
                self.scenario, _none(ticker), _none(sector), start, end, _none(as_of), "en"
            )
            calls = machine.canonical_calls(state, intent)
            return reply("", [ToolCall(n, a) for n, a in calls]) if calls else reply("none")
        if tools:  # experiment B's loop
            if any(m.get("role") == "tool" for m in messages):
                return reply("I have what I need.")
            return reply("", B_CALLS)
        if "action" in properties and system.startswith("You write the explanation step"):
            text = self._explanation(system, messages[1]["content"])
            if self.bad_first_explanation and len(messages) == 2:  # the first try only
                text = text.replace('"explanation": "', '"explanation": "It moved 4321.98%. ', 1)
            return reply(text)
        if "action" in properties:  # a free answer (A, B, C)
            question = next(
                (q for q in self.answers if any(q in str(m["content"]) for m in messages)), None
            )
            return reply(self.answers.get(question, FREE_ANSWER))
        raise AssertionError(f"unexpected request: {system[:80]}")

    @staticmethod
    def _explanation(system, user):
        lines = re.findall(r"^(E\d+): (.+)$", user, re.MULTILINE)
        text = " ".join(f"{sentence} [{label}]" for label, sentence in lines)
        note = re.search(r"Include this line exactly: (.+)", system)
        if note:
            text += "\n" + note[1]
        text += "\n" + re.search(r"End with this line exactly: (.+)", system)[1]
        return json.dumps({"action": "WATCH", "explanation": text})


class GoldenTools:
    """Golden outputs with the asked stock; the result id follows tool and arguments."""

    def __init__(self):
        self.calls = []

    def __call__(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        path = GOLDEN / f"{name}.ok.json"
        output = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if "ticker" in arguments and "ticker" in output:
            output["ticker"] = arguments["ticker"]
        key = json.dumps([name, arguments], sort_keys=True, default=str)
        output["result_id"] = hashlib.sha256(key.encode()).hexdigest()[:12]
        return output


@pytest.fixture(autouse=True)
def private_store(monkeypatch, tmp_path):
    path = tmp_path / "default-store.sqlite"
    monkeypatch.setattr(session, "_store_path", lambda: path)


@pytest.fixture(scope="module")
def chosen():
    by_id = {q["id"]: q for q in qs.load_questions()}
    return [by_id[i] for i in IDS]


@pytest.fixture
def result(chosen, tmp_path):
    client = RuleClient({q["question"]: INTENTS[q["id"]] for q in chosen})
    summary = run_eval.run_eval(
        chosen,
        client,
        experiments=run_eval.EXPERIMENTS,
        call_tool=GoldenTools(),
        today=TODAY,
        repeats=2,
        out_dir=tmp_path / "run",
        replay_options={"verify": lambda snapshot_id: []},
    )
    records = [
        json.loads(line)
        for line in (tmp_path / "run" / "records.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return summary, records, tmp_path / "run"


def pick(records, experiment, qid, repeat=0):
    return next(
        r
        for r in records
        if (r["experiment"], r["question_id"], r["repeat"]) == (experiment, qid, repeat)
    )


# --- G5a: the files -----------------------------------------------------------------------
def test_one_record_per_experiment_question_and_repeat(result):
    summary, records, out = result
    assert len(records) == 5 * 3 * 2
    assert {r["experiment"] for r in records} == set("ABCDE")
    assert all(r["error"] is None for r in records)
    written = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert written == summary
    assert set(summary["metrics"]) == set("ABCDE")
    config = summary["config"]
    assert config["model"] == "fake-model" and config["repeats"] == 2
    assert config["question_set_sha256"] == qs.recorded_sha256()
    assert config["questions"] == list(IDS) and config["today"] == TODAY


def test_nothing_written_names_an_endpoint(result):
    _, _, out = result
    for path in out.iterdir():
        if path.suffix in (".json", ".jsonl"):
            text = path.read_text(encoding="utf-8")
            assert "http" not in text and "11434" not in text


# --- G5b: the configurations --------------------------------------------------------------
def test_d_runs_the_full_harness(result):
    _, records, _ = result
    analysis = pick(records, "D", "AM-02")
    assert analysis["outcome"] == "WATCH" and analysis["answer_by"] == "model"
    assert analysis["validation"] == []
    assert {t["state"] for t in analysis["trail"]} >= {"CHECK_DATA_QUALITY", "RISK_GATE"}
    refused = pick(records, "D", "TP-01")
    assert refused["outcome"] == "REFUSED_ADVICE" and refused["tool_calls"] == []
    unsafe = pick(records, "D", "TP-15")
    assert unsafe["outcome"] == "ANALYSIS_UNSAFE" and unsafe["tool_calls"] == []


def test_e_stores_the_analysis_and_replays_it(result):
    _, records, out = result
    analysis = pick(records, "E", "AM-02")
    assert analysis["outcome"] == "WATCH" and analysis["replay"] == "MATCH"
    conn = db.connect(out / "memory.sqlite")
    try:
        stored = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    finally:
        conn.close()
    assert stored == 3 * 2
    assert pick(records, "D", "AM-02")["replay"] is None


def test_c_has_the_state_machine_but_no_evidence_gate_or_validation(result):
    _, records, _ = result
    analysis = pick(records, "C", "AM-02")
    assert analysis["outcome"] == "HOLD" and analysis["answer_by"] == "model"
    assert analysis["answer"] == json.loads(FREE_ANSWER)["explanation"]
    assert analysis["validation"]  # shown although it fails the validator
    assert pick(records, "C", "TP-01")["outcome"] == "REFUSED_ADVICE"


def test_b_lets_the_model_call_any_tool_checked_by_schema_only(result):
    _, records, _ = result
    analysis = pick(records, "B", "AM-02")
    assert analysis["intent"] is None and analysis["trail"] == []
    calls = [(c["tool"], c["allowed"], c["source"]) for c in analysis["tool_calls"]]
    assert calls == [
        ("get_stock_history", True, "model"),
        ("calculate_indicators", False, "model"),
    ]
    assert analysis["outcome"] == "HOLD"


def test_a_gives_data_as_text_with_no_guard(result):
    _, records, _ = result
    trap = pick(records, "A", "TP-01")  # the keyword guard does not run in A
    assert trap["outcome"] == "HOLD" and trap["trail"] == []
    assert trap["tool_calls"] and {c["source"] for c in trap["tool_calls"]} == {"harness"}
    assert {c["state"] for c in trap["tool_calls"]} == {"DATA_AS_TEXT"}


def test_the_summary_shows_what_each_layer_adds(result):
    summary, _, _ = result
    m = summary["metrics"]
    for name in "ABCDE":
        assert m[name]["reproducibility_rate"] == 1.0, name
    assert m["A"]["rule_violations"]["guarded_tool_calls"] > 0
    assert m["A"]["rule_violations"]["advice_shown"] > 0
    assert m["B"]["wrong_tool_call_rate"] == 0.5
    assert m["C"]["unsupported_conclusion_rate"] == 1.0
    for name in "DE":
        assert m[name]["rule_violations"]["total"] == 0, name
        assert m[name]["unsupported_conclusion_rate"] == 0.0, name
        assert m[name]["numeric_hallucination_rate"] == 0.0, name
        assert m[name]["trap_handling_rate"] == 1.0, name


def test_the_raw_intent_skips_the_keyword_guard():
    client = RuleClient({"THYAO alsam mı?": INTENTS["TP-01"]})
    raw = parse_intent("THYAO alsam mı?", client, today=TODAY, guard=False)
    assert raw.scenario == "PRICE_SUMMARY"
    guarded = parse_intent("THYAO alsam mı?", client, today=TODAY)
    assert guarded.scenario == "ADVICE_REQUEST"


def test_the_runner_refuses_a_changed_question_set(monkeypatch, tmp_path):
    changed = tmp_path / "questions.jsonl"
    changed.write_bytes(qs.QUESTIONS_PATH.read_bytes() + b"\n{}")
    monkeypatch.setattr(qs, "QUESTIONS_PATH", changed)
    with pytest.raises(SystemExit):
        run_eval.main(["--limit", "1", "--out", str(tmp_path)])


# --- fix round 1 -----------------------------------------------------------------------------
REFUSAL = '{"action": "REFUSED_ADVICE", "explanation": "I cannot give investment advice."}'
OFF_TOPIC = '{"action": "OUT_OF_SCOPE", "explanation": "This is not about the study stocks."}'


def _record_of(experiment, qid, client, tmp_path=None, **kwargs):
    question = {q["id"]: q for q in qs.load_questions()}[qid]
    memory = db.connect(tmp_path / "m.sqlite") if experiment == "E" else None
    try:
        return run_eval.run_one(
            experiment,
            question,
            0,
            client,
            call_tool=GoldenTools(),
            today=TODAY,
            memory=memory,
            replay_options={"verify": lambda snapshot_id: []},
            **kwargs,
        )
    finally:
        if memory is not None:
            memory.close()


@pytest.mark.parametrize("experiment", ["A", "B"])
def test_a_and_b_are_offered_refusal_and_out_of_scope(experiment):
    from bist_harness.eval import metrics

    question = "Can I buy THYAO?"
    client = RuleClient({question: INTENTS["TP-01"]}, answers={question: REFUSAL})
    record = _record_of(experiment, "TP-14", client)
    assert record["outcome"] == "REFUSED_ADVICE"
    assert metrics.outcome_class(record) == "REFUSED_ADVICE"
    assert metrics.unsupported_conclusion(record) is None
    final = client.requests[-1]["response_format"]["properties"]["action"]["enum"]
    assert {"REFUSED_ADVICE", "OUT_OF_SCOPE"} <= set(final)
    weather = {q["id"]: q for q in qs.load_questions()}["TP-19"]["question"]  # by id, not text
    off_topic = RuleClient({weather: INTENTS["TP-01"]}, answers={weather: OFF_TOPIC})
    assert _record_of(experiment, "TP-19", off_topic)["outcome"] == "OUT_OF_SCOPE"


@pytest.mark.parametrize(
    "scenario, outcome",
    [
        ("ADVICE_REQUEST", "REFUSED_ADVICE"),
        ("PREDICTION_REQUEST", "REFUSED_ADVICE"),
        ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ],
)
def test_a_keeps_its_raw_intent_signal(scenario, outcome):
    question = "What will THYAO's price be tomorrow?"
    client = RuleClient({question: {"scenario": scenario, "ticker": "THYAO", "language": "en"}})
    record = _record_of("A", "TP-11", client)
    assert record["intent"]["scenario"] == scenario
    assert record["outcome"] == outcome and record["tool_calls"] == []
    assert record["answer_by"] == "model"  # the model's own text is still shown and checked


def test_every_explanation_attempt_is_recorded(tmp_path):
    from bist_harness.eval import metrics

    question = {q["id"]: q for q in qs.load_questions()}["AM-02"]["question"]
    client = RuleClient({question: INTENTS["AM-02"]}, bad_first_explanation=True)
    record = _record_of("D", "AM-02", client)
    assert record["outcome"] == "WATCH" and record["validation"] == []
    assert len(record["attempts"]) == 2 and "4321.98" in record["attempts"][0]["text"]
    written, unsupported, _ = metrics.answer_numbers(record)
    assert written > 0 and unsupported == 0
    assert metrics.attempt_numbers(record)[1] == 1  # the invented number of the first try


def test_records_say_what_the_model_was_shown_and_whether_a_real_gate_ran(result):
    from bist_harness.eval import metrics

    _, records, _ = result
    for experiment, shown, gate in (
        ("A", "tool_outputs", False),
        ("B", "tool_outputs", False),
        ("C", "tool_outputs", False),
        ("D", "committed_evidence", True),
        ("E", "committed_evidence", True),
    ):
        analysis = pick(records, experiment, "AM-02")
        assert analysis["data_shown"] == shown, experiment
        assert analysis["real_gate"] is gate, experiment
        assert analysis["attempts"], experiment
    assert metrics.rule_violations(pick(records, "C", "AM-02"))["skipped_mandatory"] == 1
    assert metrics.rule_violations(pick(records, "D", "AM-02"))["skipped_mandatory"] == 0
    # D's guarded question never reached a gate
    assert pick(records, "D", "TP-01")["real_gate"] is False


# --- Sprint 5: the harness memory section is not validated as model text ---------------------
def test_e_validates_the_model_text_without_the_harness_memory_section(tmp_path):
    from bist_harness.harness import memory as mem

    question = {q["id"]: q for q in qs.load_questions()}["AM-02"]
    conn = db.connect(tmp_path / "m.sqlite")
    records = []
    try:
        for today in ("2026-11-10", TODAY):  # the later default period recalls the earlier
            client = RuleClient({question["question"]: INTENTS["AM-02"]})
            records.append(
                run_eval.run_one(
                    "E",
                    question,
                    0,
                    client,
                    call_tool=GoldenTools(),
                    today=today,
                    memory=conn,
                    replay_options={"verify": lambda snapshot_id: []},
                )
            )
    finally:
        conn.close()
    later = records[1]
    assert mem.episodes_in(later["trail"])  # the earlier analysis was recalled
    stripped = mem.strip_section(later["answer"], later["trail"], later["language"])
    assert stripped != later["answer"]  # and its section was appended to the shown answer
    assert later["answer_by"] == "model"
    assert later["validation"] == []
