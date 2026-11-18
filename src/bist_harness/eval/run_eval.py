"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

The evaluation runner (card EC-060, design spec section 12): the harness experiments A-E
with one model on the frozen question set.

| Exp. | What runs |
| --- | --- |
| A | Raw model. Its intent (no keyword guard) picks the data; the canonical calls of the
      route are made by code and their outputs are given to the model as text; the model
      answers freely with a label from all eight or REFUSED_ADVICE / OUT_OF_SCOPE. When
      its own intent says advice, prediction or out of scope, that is its outcome (no data
      is loaded; its answer is still shown and checked). No tool requirement, states,
      checks. |
| B | Model + tools. All tool schemas are offered in a loop of up to ``MAX_TOOL_ROUNDS``
      turns; a call is checked against its schema only, then executed; the model answers
      freely, a refusal (REFUSED_ADVICE / OUT_OF_SCOPE) included. No intent, states,
      permissions or gate. |
| C | B + the stateful harness: ``machine.run_analysis`` with intent, guards, routes and
      state permissions, but no evidence builder, a gate that always passes and a free,
      unvalidated explanation over the raw outputs. |
| D | C + evidence and quality gate: ``run_analysis`` as built (evidence, gate, eligible
      labels, output validator). |
| E | D + memory and human review: the analysis and its decision log are stored in a
      SQLite memory under the run directory (human review stays pending) and replayed
      from there (``harness.replay``). |

Every run is recorded the same way (``eval.metrics`` describes the record): the evidence
is built from the record's own allowed calls, model-written text that was shown as a
conclusion is checked by the output validator afterwards (for A-C this is measurement,
not control), and every answer the model wrote at the explanation step is kept in
``attempts`` (rejected ones included), so the model's own hallucination rate is measured
before the validator.

Usage (the endpoint comes from the settings, ``BIST_LLM_BASE_URL``; it is never printed)::

    uv run python -m bist_harness.eval.run_eval --experiments A,B,C,D,E --repeats 2
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from bist_harness.config import REPO_ROOT, Settings
from bist_harness.eval import metrics
from bist_harness.eval import questions as question_set
from bist_harness.harness import machine, session
from bist_harness.harness.actions import eligible_actions
from bist_harness.harness.evidence import build_evidence
from bist_harness.harness.gate import PASS, GateResult, quality_gate
from bist_harness.harness.intent import _guess_language, parse_intent
from bist_harness.harness.replay import replay
from bist_harness.harness.routes import ROUTES
from bist_harness.harness.validator import explanation_schema, validate_explanation
from bist_harness.storage import db
from bist_harness.tools.schemas import ACTIONS, to_ollama_tools, validate_tool_call

EXPERIMENTS = ("A", "B", "C", "D", "E")
MAX_TOOL_ROUNDS = 6  # experiment B: tool-call turns before the final answer
OUTPUT_CHARS = 6000  # each tool output is cut to this length when given to the model as text
DATA_STATE = "DATA_AS_TEXT"  # state name of the calls experiment A makes for its data
LOOP_STATE = "TOOL_LOOP"  # state name of the calls of experiment B
ToolCaller = Callable[[str, dict], dict]

_ANSWER_PROMPT = (
    "You answer questions about the stocks of an educational BIST 100 study universe. "
    "Write in {language}. Answer with one JSON object: "
    '{{"action": <one of {actions}>, "explanation": <text>}}.'
)
_DATA_PROMPT = "Question: {question}\n\nData (tool outputs as JSON):\n{data}"
_LOOP_PROMPT = (
    "You answer questions about the stocks of an educational BIST 100 study universe. "
    "Use the tools to get the data you need. Today is {today}. This analysis has the id "
    "{analysis_id} (some tools ask for it). When you have the data, reply with text."
)
_FINAL_REQUEST = (
    "Now answer the question in {language} with one JSON object: "
    '{{"action": <one of {actions}>, "explanation": <text>}}.'
)
LANGUAGE_NAMES = {"tr": "Turkish", "en": "English"}
REFUSALS = (machine.REFUSED_ADVICE, machine.OUT_OF_SCOPE)
# A and B may refuse: their free answer offers the two refusals besides the eight labels.
FREE_LABELS = (*ACTIONS, *REFUSALS)
# A's own intent label that is a refusal.
INTENT_REFUSAL = {
    "ADVICE_REQUEST": machine.REFUSED_ADVICE,
    "PREDICTION_REQUEST": machine.REFUSED_ADVICE,
    "OUT_OF_SCOPE": machine.OUT_OF_SCOPE,
}


@dataclasses.dataclass(frozen=True)
class FreeAnswer:
    """A model answer that no validator checked (experiments A to C)."""

    action: str | None
    text: str
    fallback: bool = False


# --- shared pieces -------------------------------------------------------------------------
class AttemptRecorder:
    """Passes every request to the client and keeps each answer the model wrote at an
    explanation step (a request whose schema has an ``action``), rejected ones included."""

    def __init__(self, client):
        self.client = client
        self.model = getattr(client, "model", "unknown")
        self.attempts: list[dict] = []

    def chat(self, messages, tools=None, **kwargs):
        result = self.client.chat(messages, tools, **kwargs)
        schema = kwargs.get("response_format") or {}
        if "action" in (schema.get("properties") or {}):
            answer = _parse_answer(result.content, FREE_LABELS)
            self.attempts.append({"action": answer.action, "text": answer.text})
        return result


def _execute(analysis, call_tool: ToolCaller, state: str, name: str, arguments: dict, source):
    try:
        output = call_tool(name, arguments)
    except Exception as exc:  # a tool failure is recorded, never lost
        output = {"error": {"code": "TOOL_FAILED", "message": f"{type(exc).__name__}: {exc}"}}
    return session.record_call(
        analysis, state=state, tool=name, arguments=arguments, output=output, source=source
    )


def _as_text(output: object) -> str:
    return json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)[:OUTPUT_CHARS]


def _parse_answer(content: str, labels: Sequence[str] = ACTIONS) -> FreeAnswer:
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return FreeAnswer(None, content)
    if not isinstance(data, dict):
        return FreeAnswer(None, content)
    action, text = data.get("action"), data.get("explanation")
    return FreeAnswer(
        action if action in labels else None, text if isinstance(text, str) else content
    )


def _free_answer(
    client,
    question: str,
    outputs: Sequence[object],
    language: str,
    labels: Sequence[str] = ACTIONS,
) -> FreeAnswer:
    """One schema-constrained answer over raw outputs given as text (experiments A and C;
    A also offers the two refusals)."""
    data = "\n".join(_as_text(o) for o in outputs) or "(no data)"
    messages = [
        {
            "role": "system",
            "content": _ANSWER_PROMPT.format(
                language=LANGUAGE_NAMES[language], actions=", ".join(labels)
            ),
        },
        {"role": "user", "content": _DATA_PROMPT.format(question=question, data=data)},
    ]
    result = client.chat(
        messages,
        response_format=explanation_schema(labels),
        temperature=session.TEMPERATURE,
        seed=session.SEED,
    )
    return _parse_answer(result.content, labels)


def _allowed_outputs(analysis) -> list[object]:
    return [c.output for c in analysis.tool_calls if c.allowed]


def _new(question: str, client, today: str):
    analysis = session.new_analysis(question, model=getattr(client, "model", "unknown"))
    analysis.today = today
    return analysis


def _unavailable(analysis, exc: BaseException, language: str):
    analysis.trail.append(session.StateRecord("START", "FAILED", machine._failure(exc)))
    analysis.outcome = machine.MODEL_UNAVAILABLE
    analysis.answer = machine.MODEL_UNAVAILABLE_ANSWERS[language]
    return analysis


# --- A: raw model, data as text --------------------------------------------------------------
def run_raw(question: str, client, *, call_tool: ToolCaller, today: str):
    analysis = _new(question, client, today)
    language = _guess_language(question)
    try:
        intent = parse_intent(question, client, today=today, guard=False)
        analysis.intent = dataclasses.asdict(intent)
        language = intent.language
        for state in ROUTES.get(intent.scenario, ())[1:-1]:
            for name, arguments in machine.canonical_calls(state, intent):
                _execute(analysis, call_tool, DATA_STATE, name, arguments, "harness")
        answer = _free_answer(client, question, _allowed_outputs(analysis), language, FREE_LABELS)
    except machine.MODEL_ERRORS as exc:
        return _unavailable(analysis, exc, language)
    # The model's own intent label is a model decision: a refusal there is A's outcome.
    refusal = INTENT_REFUSAL.get(intent.scenario)
    analysis.outcome = refusal or answer.action or machine.COMPLETED
    analysis.answer = answer.text
    return analysis


# --- B: model + tools ------------------------------------------------------------------------
def run_tools(question: str, client, *, call_tool: ToolCaller, today: str):
    analysis = _new(question, client, today)
    language = _guess_language(question)
    tools = to_ollama_tools()
    prompt = _LOOP_PROMPT.format(today=today, analysis_id=analysis.analysis_id)
    messages: list[dict] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": question},
    ]
    options = {"temperature": session.TEMPERATURE, "seed": session.SEED}
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            result = client.chat(messages, tools=tools, **options)
            if result.malformed_tool_call:
                message = "The tool call could not be parsed."
                session.record_call(
                    analysis,
                    state=LOOP_STATE,
                    tool=machine.MALFORMED_TOOL,
                    arguments={},
                    output={"error": {"code": "MALFORMED_CALL", "message": message}},
                    allowed=False,
                    source="model",
                )
                if not result.tool_calls:
                    messages += [
                        {"role": "assistant", "content": result.content},
                        {"role": "user", "content": message},
                    ]
                    continue
            if not result.tool_calls:
                break
            calls = [
                {"function": {"name": c.name, "arguments": c.arguments}} for c in result.tool_calls
            ]
            messages.append({"role": "assistant", "content": result.content, "tool_calls": calls})
            for proposal in result.tool_calls:
                arguments = dict(proposal.arguments)
                problem = validate_tool_call(proposal.name, arguments)
                if problem is not None:
                    output = {"error": {"code": "INVALID_CALL", "message": problem}}
                    session.record_call(
                        analysis,
                        state=LOOP_STATE,
                        tool=proposal.name,
                        arguments=arguments,
                        output=output,
                        allowed=False,
                        source="model",
                    )
                else:
                    record = _execute(
                        analysis, call_tool, LOOP_STATE, proposal.name, arguments, "model"
                    )
                    output = record.output
                messages.append({"role": "tool", "content": _as_text(output)})
        request = _FINAL_REQUEST.format(
            language=LANGUAGE_NAMES[language], actions=", ".join(FREE_LABELS)
        )
        result = client.chat(
            [*messages, {"role": "user", "content": request}],
            response_format=explanation_schema(FREE_LABELS),
            **options,
        )
    except machine.MODEL_ERRORS as exc:
        return _unavailable(analysis, exc, language)
    answer = _parse_answer(result.content, FREE_LABELS)
    analysis.outcome = answer.action or machine.COMPLETED
    analysis.answer = answer.text
    return analysis


# --- C: the state machine without evidence, gate or validation ------------------------------
def _no_evidence(analysis, *, language: str) -> list:
    return []


def _no_gate(analysis, evidence) -> GateResult:
    return GateResult(PASS)


def _free_explanation(analysis, client, evidence, gate) -> FreeAnswer:
    language = (analysis.intent or {}).get("language") or _guess_language(analysis.question)
    return _free_answer(client, analysis.question, _allowed_outputs(analysis), language)


def run_stateful(question: str, client, *, call_tool: ToolCaller, today: str, max_attempts=2):
    return machine.run_analysis(
        question,
        client,
        call_tool=call_tool,
        today=today,
        max_attempts=max_attempts,
        evidence_fn=_no_evidence,
        gate_fn=_no_gate,
        explain_fn=_free_explanation,
    )


# --- the record ----------------------------------------------------------------------------
def _answer_by(experiment: str, analysis) -> str | None:
    if analysis.answer is None:
        return None
    if analysis.outcome == machine.MODEL_UNAVAILABLE:
        return "harness"
    if experiment in ("A", "B"):
        return "model"
    if analysis.outcome in metrics.CONCLUSIONS or analysis.outcome == machine.COMPLETED:
        explained = [r for r in analysis.trail if r.state == "GENERATE_EXPLANATION"]
        fallback = any(r.detail.get("fallback") is True for r in explained)
        return "harness" if fallback else "model"
    return "harness"  # a fixed refusal, out-of-scope or unsafe answer


def make_record(
    experiment: str,
    question: dict,
    repeat: int,
    analysis,
    *,
    latency_s: float,
    replay_status: str | None = None,
    attempts: Sequence[dict] = (),
) -> dict:
    """The JSON record of one run (fields in ``eval.metrics``)."""
    intent = analysis.intent
    scenario = (intent or {}).get("scenario") or question["expected"]["scenarios"][0]
    language = (intent or {}).get("language") or _guess_language(analysis.question)
    scored = dataclasses.replace(analysis, intent={**(intent or {}), "scenario": scenario})
    evidence = build_evidence(scored, language=language)
    answer_by = _answer_by(experiment, analysis)
    validation: list[str] = []
    concluded = analysis.outcome not in (*REFUSALS, machine.ANALYSIS_UNSAFE)
    if answer_by == "model" and concluded:
        eligible = eligible_actions(scored, evidence, quality_gate(scored, evidence))
        validation = validate_explanation(
            analysis.answer,
            action=str(analysis.outcome),
            eligible=eligible,
            evidence=evidence,
            question=analysis.question,
            language=language,
            defaulted_period=bool((intent or {}).get("defaulted_period")),
            defaulted_bound=(intent or {}).get("defaulted_bound"),
        )
    return {
        "experiment": experiment,
        "question_id": question["id"],
        "repeat": repeat,
        "question": analysis.question,
        "language": language,
        "expected": question["expected"],
        "intent": intent,
        "outcome": analysis.outcome,
        "answer": analysis.answer,
        "answer_by": answer_by,
        "tool_calls": [
            {
                "seq": c.seq,
                "state": c.state,
                "tool": c.tool,
                "arguments": c.arguments,
                "output": c.output,
                "allowed": c.allowed,
                "source": c.source,
            }
            for c in analysis.tool_calls
        ],
        "trail": [
            {"state": r.state, "status": r.status, "detail": r.detail} for r in analysis.trail
        ],
        "evidence": [dataclasses.asdict(e) for e in evidence],
        "validation": validation,
        "latency_s": latency_s,
        "replay": replay_status,
        "error": None,
        "attempts": list(attempts),
        "data_shown": "committed_evidence" if experiment in ("D", "E") else "tool_outputs",
        "real_gate": experiment in ("D", "E")
        and any(r.state == "RISK_GATE" and r.status == "RAN" for r in analysis.trail),
    }


def _error_record(experiment: str, question: dict, repeat: int, exc: BaseException) -> dict:
    failure = machine._failure(exc)  # the message without any server address
    return {
        "experiment": experiment,
        "question_id": question["id"],
        "repeat": repeat,
        "question": question["question"],
        "language": question["lang"],
        "expected": question["expected"],
        "intent": None,
        "outcome": None,
        "answer": None,
        "answer_by": None,
        "tool_calls": [],
        "trail": [],
        "evidence": [],
        "validation": [],
        "latency_s": None,
        "replay": None,
        "error": f"{failure['error']}: {failure['message']}",
        "attempts": [],
        "data_shown": "committed_evidence" if experiment in ("D", "E") else "tool_outputs",
        "real_gate": False,
    }


# --- the run -------------------------------------------------------------------------------
def run_one(
    experiment: str,
    question: dict,
    repeat: int,
    client,
    *,
    call_tool: ToolCaller,
    today: str,
    memory=None,
    max_attempts: int = 2,
    replay_options: dict | None = None,
) -> dict:
    """Run one question once under one experiment and return its record.

    A question that carries its own ``today`` (a generated development question) runs
    on that day; any other runs on ``today``.
    """
    text = question["question"]
    today = question.get("today") or today
    client = AttemptRecorder(client)
    started = time.perf_counter()
    if experiment == "A":
        analysis = run_raw(text, client, call_tool=call_tool, today=today)
    elif experiment == "B":
        analysis = run_tools(text, client, call_tool=call_tool, today=today)
    elif experiment == "C":
        analysis = run_stateful(
            text, client, call_tool=call_tool, today=today, max_attempts=max_attempts
        )
    elif experiment in ("D", "E"):
        analysis = machine.run_analysis(
            text,
            client,
            call_tool=call_tool,
            today=today,
            max_attempts=max_attempts,
            conn=memory if experiment == "E" else None,
            memory=experiment == "E",
        )
    else:
        raise ValueError(f"unknown experiment: {experiment}")
    latency = time.perf_counter() - started
    status = None
    if experiment == "E":
        stored = session.load(analysis.analysis_id, memory)  # read back from the memory
        status = replay(stored, call_tool=call_tool, **(replay_options or {})).status
    return make_record(
        experiment,
        question,
        repeat,
        analysis,
        latency_s=latency,
        replay_status=status,
        attempts=client.attempts,
    )


def summarize_records(
    records: Sequence[dict], *, call_tool: ToolCaller | None, backtest_accuracy: bool = False
) -> dict[str, dict]:
    """The metrics of each experiment; with ``backtest_accuracy`` each also gets the
    ``backtest_accuracy`` block (every executed backtest re-run through ``call_tool``)."""
    result = metrics.summarize(records)
    if backtest_accuracy:
        for name, values in result.items():
            own = [r for r in records if r["experiment"] == name]
            values["backtest_accuracy"] = metrics.backtest_check(own, call_tool)
    return result


def run_eval(
    questions: Sequence[dict],
    client,
    *,
    experiments: Sequence[str] = EXPERIMENTS,
    call_tool: ToolCaller,
    today: str,
    repeats: int = 2,
    out_dir: Path,
    max_attempts: int = 2,
    replay_options: dict | None = None,
    endpoint: str = "not recorded",
    progress: Callable[[dict], None] | None = None,
    question_set_sha256: str | None = None,
    backtest_accuracy: bool = False,
) -> dict:
    """Run every experiment on every question ``repeats`` times; write ``records.jsonl``
    and ``summary.json`` under ``out_dir`` and return the summary.

    ``question_set_sha256`` names the question file in the summary (default: the frozen
    set's recorded hash). ``backtest_accuracy`` re-runs every executed backtest of the
    records after the grading and adds the ``backtest_accuracy`` block to each experiment's
    metrics (slow, so off by default)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    memory = db.connect(out_dir / "memory.sqlite") if "E" in experiments else None
    records: list[dict] = []
    try:
        with (out_dir / "records.jsonl").open("w", encoding="utf-8", newline="\n") as sink:
            for experiment in experiments:
                for question in questions:
                    for repeat in range(repeats):
                        try:
                            record = run_one(
                                experiment,
                                question,
                                repeat,
                                client,
                                call_tool=call_tool,
                                today=today,
                                memory=memory,
                                max_attempts=max_attempts,
                                replay_options=replay_options,
                            )
                        except Exception as exc:  # one broken run must not stop the grading
                            record = _error_record(experiment, question, repeat, exc)
                        records.append(record)
                        sink.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                        sink.flush()
                        if progress is not None:
                            progress(record)
    finally:
        if memory is not None:
            memory.close()
    summary = {
        "config": {
            "model": getattr(client, "model", "unknown"),
            "endpoint": endpoint,
            "experiments": list(experiments),
            "repeats": repeats,
            "today": today,
            "max_attempts": max_attempts,
            "question_set_sha256": question_set_sha256 or question_set.recorded_sha256(),
            "questions": [q["id"] for q in questions],
            "started_at": started,
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "metrics": summarize_records(
            records, call_tool=call_tool, backtest_accuracy=backtest_accuracy
        ),
    }
    with (out_dir / "summary.json").open("w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    return summary


# --- command line --------------------------------------------------------------------------
QUESTION_KEYS = ("id", "question", "lang", "expected")
EXPECTED_KEYS = (
    "scenarios",
    "outcomes",
    "ticker",
    "sector",
    "start",
    "end",
    "as_of",
    "reason",
    "tools",
)


def load_question_set(path: Path | None = None) -> list[dict]:
    """The questions to run: the frozen set (verified first) or another file in its format.

    ``path`` None or the frozen file: ``verify_frozen`` must pass. Any other file (such
    as the fine-tuning build's ``dev_questions.jsonl``) is read as it is; every line needs
    ``id``, ``question``, ``lang`` and an ``expected`` with the frozen set's keys.
    Raises ``ValueError`` otherwise.
    """
    frozen_path = question_set.QUESTIONS_PATH
    if path is None or Path(path).resolve() == Path(frozen_path).resolve():
        question_set.verify_frozen(frozen_path)
        return question_set.load_questions(frozen_path)
    questions = question_set.load_questions(Path(path))
    for number, question in enumerate(questions, start=1):
        missing = [key for key in QUESTION_KEYS if key not in question]
        missing += [
            f"expected.{key}" for key in EXPECTED_KEYS if key not in question.get("expected", {})
        ]
        if missing:
            raise ValueError(f"{path} line {number} lacks {', '.join(missing)}")
    return questions


def _server_call_tool(name: str, arguments: dict) -> dict:
    from bist_harness.mcp_server import server

    return getattr(server, name)(**arguments)


def _print_record(record: dict) -> None:
    latency = record["latency_s"]
    shown = "-" if latency is None else f"{latency:.1f}s"
    outcome = record["outcome"] or record["error"]
    print(
        f"[eval] {record['experiment']} {record['question_id']} r{record['repeat']} "
        f"{outcome} {shown}",
        flush=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    parser.add_argument("--experiments", default=",".join(EXPERIMENTS))
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--ids", help="comma-separated question ids (default: all)")
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument("--model", help="model tag (default: BIST_LLM_MODEL)")
    parser.add_argument("--today", default=date.today().isoformat())
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "runs")
    parser.add_argument(
        "--questions-file",
        type=Path,
        help="questions in the frozen-set format, e.g. the fine-tuning dev questions "
        "(default: the frozen set, verified)",
    )
    parser.add_argument(
        "--backtest-accuracy",
        action="store_true",
        help="re-run every executed backtest and report how many reproduce exactly "
        "(slow; off by default)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        chosen = load_question_set(args.questions_file)
    except ValueError as exc:
        print(f"[eval] {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    experiments = [e.strip().upper() for e in args.experiments.split(",") if e.strip()]
    unknown = [e for e in experiments if e not in EXPERIMENTS]
    if unknown:
        raise SystemExit(f"[eval] unknown experiment(s): {', '.join(unknown)}")
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        chosen = [q for q in chosen if q["id"] in wanted]
    if args.limit:
        chosen = chosen[: args.limit]

    from bist_harness.bakeoff.run import endpoint_label
    from bist_harness.llm.client import OllamaClient

    settings = Settings.from_env()
    client = OllamaClient(
        settings.llm_base_url,
        args.model or settings.llm_model,
        timeout_s=args.timeout,
        api=settings.llm_api,
    )
    endpoint = endpoint_label(settings.llm_base_url)
    if settings.llm_api == "openai":
        endpoint += " (OpenAI-compatible route)"
    out_dir = args.out / f"eval-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    print(
        f"[eval] {len(chosen)} questions, experiments {','.join(experiments)}, "
        f"{args.repeats} repeat(s), model {client.model} on the {endpoint}",
        flush=True,
    )
    summary = run_eval(
        chosen,
        client,
        experiments=experiments,
        call_tool=_server_call_tool,
        today=args.today,
        repeats=args.repeats,
        out_dir=out_dir,
        max_attempts=args.max_attempts,
        endpoint=endpoint,
        progress=_print_record,
        backtest_accuracy=args.backtest_accuracy,
        question_set_sha256=(
            question_set.file_sha256(args.questions_file) if args.questions_file else None
        ),
    )
    for name, values in summary["metrics"].items():
        print(f"[eval] {name}: {json.dumps(values, default=str)}", flush=True)
    print(f"[eval] written to {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
