"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

The stateful harness (decision K-005: "Agent thinks. Harness controls.").

Code drives the state transitions. The model speaks in three places only: the intent at
``START``, one tool-call proposal in each tool state of the route (from that state's
allowed tools alone), and the explanation at ``GENERATE_EXPLANATION`` (schema-constrained
JSON checked by ``harness.validator``; the run's outcome is the chosen action label). Every
proposed call is checked in
order (schema, permission of the state, agreement with the intent: stock, sector, dates
and the reversal event family and direction the question names); a rejected call is
recorded with ``allowed=False`` and the model gets a short error. After ``max_attempts``
without a valid call the harness makes the canonical call derived from the intent itself
(``source="harness"``), which experiment C counts as a harness intervention. After the
model's valid calls in a state, the harness also tops up the canonical calls of that state
that the scenario's minimum evidence (``evidence.MINIMUM``) still needs (``top_up_calls``,
also ``source="harness"`` and counted as interventions); the model's calls are kept.
"""

from __future__ import annotations

import dataclasses
import re
import sqlite3
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

from bist_harness.backtest.periods import TEST as TEST_PERIOD
from bist_harness.backtest.strategies import FEATURE_FILTERS
from bist_harness.data import peers
from bist_harness.errors import LLMUnavailableError
from bist_harness.harness import session
from bist_harness.harness.evidence import MINIMUM, build_evidence, missing_requirements
from bist_harness.harness.gate import quality_gate
from bist_harness.harness.intent import (
    Intent,
    _guess_language,
    check_intent,
    keyword_guard,
    parse_intent,
    reversal_grounding,
)
from bist_harness.harness.routes import ALLOWED_TOOLS, GUARDED_ROUTE, ROUTES, STATES
from bist_harness.harness.validator import generate_explanation
from bist_harness.tools.events import SINGLE_DIRECTION
from bist_harness.tools.schemas import (
    REVERSAL_EVENT_TYPES,
    STRATEGY_VARIANTS,
    to_ollama_tools,
    validate_tool_call,
)
from bist_harness.universe import normalize_ticker

ToolCaller = Callable[[str, dict], dict]

REFUSED_ADVICE = "REFUSED_ADVICE"
ANALYSIS_UNSAFE = "ANALYSIS_UNSAFE"
OUT_OF_SCOPE = "OUT_OF_SCOPE"
COMPLETED = "COMPLETED"  # the route ran to the end but an explain hook returned no label
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"  # the model server failed mid-run

# What a failing model server raises: the client's own error, or a transport error from a
# client that does not wrap them. Anything else is a bug and is not swallowed.
MODEL_ERRORS = (LLMUnavailableError, httpx.HTTPError, OSError)
_ADDRESS = re.compile(
    r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+"  # a URL
    r"|\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"  # an IPv4 address, with or without a port
    r"|\b[\w.-]+:\d{2,5}\b"  # host:port
)

# States the harness runs itself: no model turn (design spec section 6).
HARNESS_STATES = ("CHECK_DATA_QUALITY", "BUILD_EVIDENCE", "RISK_GATE")
# Gate statuses after which no explanation is generated (design spec section 8).
BLOCKING_STATUSES = ("HARD_BLOCK", "ANALYSIS_UNSAFE")

REFUSAL_ANSWERS = {
    "tr": (
        "Bu sistem eğitim amaçlıdır ve yatırım tavsiyesi ya da fiyat tahmini vermez. "
        "Bir hissenin geçmiş fiyat hareketini, sektör içindeki göreli durumunu ya da "
        "bir stratejinin geçmiş testini sorabilirsiniz."
    ),
    "en": (
        "This system is for educational use only and gives no investment advice or price "
        "predictions. You can ask about a stock's past price behaviour, its standing "
        "within its sector or a historical test of a strategy."
    ),
}
OUT_OF_SCOPE_ANSWERS = {
    "tr": (
        "Bu soru sistemin kapsamı dışında. Sistem yalnız BIST 100 çalışma evrenindeki "
        "hisseler hakkında eğitim amaçlı geçmiş veri analizi yapar."
    ),
    "en": (
        "This question is outside the system's scope. It only runs educational analyses "
        "of historical data for the stocks of the BIST 100 study universe."
    ),
}
MODEL_UNAVAILABLE_ANSWERS = {
    "tr": "Model sunucusuna ulaşılamadı; analiz tamamlanamadı. Lütfen daha sonra deneyin.",
    "en": "The model server could not be reached; the analysis was not completed. "
    "Please try again later.",
}
UNSAFE_ANSWERS = {
    "tr": "Analiz güvenli biçimde yapılamaz ({reason}); sonuç ANALYSIS_UNSAFE.",
    "en": "The analysis cannot be run safely ({reason}); the result is ANALYSIS_UNSAFE.",
}


# --- hooks -----------------------------------------------------------------------------
default_evidence = build_evidence  # BUILD_EVIDENCE: templated sentences E1..En
default_explanation = generate_explanation  # GENERATE_EXPLANATION: label + checked text
EvidenceFn = Callable[..., Any]  # (analysis, *, language) -> evidence
GateFn = Callable[[session.Analysis, Any], Any]  # (analysis, evidence) -> result with .status
ExplainFn = Callable[..., Any]  # (analysis, client, evidence, gate) -> None or result
# Optional attributes of an explain result that are recorded in the state trail.
EXPLANATION_DETAIL = ("eligible", "attempts", "fallback", "problems")


# --- counters for the evaluation (Task 9) --------------------------------------------
def wrong_tool_calls(analysis: session.Analysis) -> int:
    """Rejected model calls (schema, permission or intent), malformed ones included."""
    return sum(1 for c in analysis.tool_calls if not c.allowed)


def harness_interventions(analysis: session.Analysis) -> int:
    """Calls the harness made in a model state (the model gave no valid call, or its valid
    calls left the minimum evidence short and the harness topped it up), plus
    one for each fallback that had no canonical call to make (a sector question in a
    state that needs a stock): the model still failed there and the harness stepped in."""
    calls = [
        c for c in analysis.tool_calls if c.source == "harness" and c.state not in HARNESS_STATES
    ]
    with_calls = {c.state for c in calls}
    empty = sum(
        1
        for r in analysis.trail
        if r.detail.get("fallback") is True
        and r.state not in (*HARNESS_STATES, "GENERATE_EXPLANATION")
        and r.state not in with_calls
    )
    return len(calls) + empty


# --- the run ---------------------------------------------------------------------------
class _Run:
    """One analysis in progress: recording, saving and the state trail."""

    def __init__(self, analysis: session.Analysis, conn: sqlite3.Connection | None):
        self.analysis = analysis
        self.conn = conn

    def save(self) -> None:
        if self.conn is not None:
            session.save(self.analysis, self.conn)

    def record(self, state: str, tool: str, arguments: dict, output: dict, **flags):
        record = session.record_call(
            self.analysis, state=state, tool=tool, arguments=arguments, output=output, **flags
        )
        self.save()  # a tool such as check_data_quality may read the analysis by id
        return record

    def execute(self, call_tool: ToolCaller, state: str, tool: str, arguments: dict, source: str):
        self.analysis.state = state
        try:
            output = call_tool(tool, arguments)
        except Exception as exc:  # a tool failure is recorded, never lost
            output = {"error": {"code": "TOOL_FAILED", "message": f"{type(exc).__name__}: {exc}"}}
        return self.record(state, tool, arguments, output, source=source)

    def mark(self, state: str, status: str, /, **detail) -> None:
        self.analysis.state = state
        self.analysis.trail.append(session.StateRecord(state, status, detail))

    def close(self, route: tuple[str, ...], outcome: str, answer: str | None = None) -> None:
        """Mark every state the route does not visit, end in LOG_AND_CLOSE and save."""
        self.analysis.outcome = outcome
        self.analysis.answer = answer
        done = {r.state for r in self.analysis.trail}
        for state in STATES:
            if state != "LOG_AND_CLOSE" and state not in done and state not in route:
                self.analysis.trail.append(session.StateRecord(state, "NOT_APPLICABLE"))
        order = {s: i for i, s in enumerate(STATES)}
        self.analysis.trail.sort(key=lambda r: order[r.state])
        self.mark("LOG_AND_CLOSE", "RAN", outcome=outcome)
        self.save()


def _guarded_outcome(intent: Intent, question: str) -> str | None:
    """REFUSED_ADVICE or OUT_OF_SCOPE when no analysis may start (model label or guard)."""
    if intent.scenario in ("ADVICE_REQUEST", "PREDICTION_REQUEST") or keyword_guard(question):
        return REFUSED_ADVICE
    if intent.scenario == "OUT_OF_SCOPE":
        return OUT_OF_SCOPE
    return None


def run_analysis(
    question: str,
    client,
    *,
    call_tool: ToolCaller,
    today: str | None = None,
    max_attempts: int = 2,
    conn: sqlite3.Connection | None = None,
    evidence_fn: EvidenceFn = default_evidence,
    gate_fn: GateFn = quality_gate,
    explain_fn: ExplainFn = default_explanation,
) -> session.Analysis:
    """Run one question through its route and return the recorded analysis.

    ``evidence_fn``, ``gate_fn`` and ``explain_fn`` are the BUILD_EVIDENCE, RISK_GATE and
    GENERATE_EXPLANATION steps (defaults: ``build_evidence``, ``quality_gate`` and
    ``generate_explanation``). The explain step gets the final evidence of RISK_GATE; its
    ``action`` becomes the outcome and its ``text`` the answer.
    """
    today = today or date.today().isoformat()
    analysis = session.new_analysis(question, model=getattr(client, "model", "unknown"))
    analysis.today = today
    run = _Run(analysis, conn)
    try:
        intent = parse_intent(question, client, today=today)
    except MODEL_ERRORS as exc:
        run.mark("START", "FAILED", **_failure(exc))
        answer = MODEL_UNAVAILABLE_ANSWERS[_guess_language(question)]
        run.close(GUARDED_ROUTE, MODEL_UNAVAILABLE, answer)
        return analysis
    analysis.intent = dataclasses.asdict(intent)
    language = intent.language

    guarded = _guarded_outcome(intent, question)
    if guarded is not None:
        run.mark("START", "RAN", scenario=intent.scenario)
        answers = REFUSAL_ANSWERS if guarded == REFUSED_ADVICE else OUT_OF_SCOPE_ANSWERS
        run.close(GUARDED_ROUTE, guarded, answers[language])
        return analysis
    problem = check_intent(intent, today=today)
    if problem is not None:
        run.mark("START", "RAN", scenario=intent.scenario, reason=problem)
        run.close(GUARDED_ROUTE, ANALYSIS_UNSAFE, UNSAFE_ANSWERS[language].format(reason=problem))
        return analysis

    route = ROUTES[intent.scenario]
    run.mark("START", "RAN", scenario=intent.scenario)
    run.save()
    own_id = {"analysis_id": analysis.analysis_id}
    evidence: Any = ()
    gate: Any = None
    action: str | None = None
    answer: str | None = None
    failure: dict | None = None  # set when the model server fails; no model turn after it
    for state in route[1:-1]:  # START is done; LOG_AND_CLOSE closes the run
        if state == "SELECT_UNIVERSE":
            run.mark(state, "RAN", ticker=intent.ticker, sector=intent.sector)
        elif state == "CHECK_DATA_QUALITY":
            run.execute(call_tool, state, "check_data_quality", dict(own_id), "harness")
            run.mark(state, "RAN")
        elif state == "BUILD_EVIDENCE":
            run.execute(call_tool, state, "build_evidence_bundle", dict(own_id), "harness")
            evidence = evidence_fn(analysis, language=language)
            run.mark(state, "RAN")
        elif state == "PREVIEW_STRATEGIES":
            run.mark(state, "RAN", variants=list(STRATEGY_VARIANTS))
        elif state == "RISK_GATE":
            run.execute(call_tool, state, "check_data_quality", dict(own_id), "harness")
            # BUILD_EVIDENCE comes before RUN_BACKTEST, so the backtest items are only
            # there now: rebuild from every call so far; gate and eligibility use this set.
            evidence = evidence_fn(analysis, language=language)
            gate = gate_fn(analysis, evidence)
            analysis.gate_status = gate.status
            run.mark(state, "RAN", status=gate.status)
        elif state == "GENERATE_EXPLANATION":
            if gate is not None and gate.status in BLOCKING_STATUSES:
                run.mark(state, "SKIPPED", reason=gate.status)
                continue
            if failure is not None:
                run.mark(state, "SKIPPED", reason=MODEL_UNAVAILABLE)
                continue
            try:
                explanation = explain_fn(analysis, client, evidence, gate)
            except MODEL_ERRORS as exc:
                failure = _failure(exc)
                run.mark(state, "FAILED", **failure)
                continue
            if explanation is None:
                run.mark(state, "RAN", placeholder=True)
            else:
                action = getattr(explanation, "action", None)
                answer = getattr(explanation, "text", None)
                detail = {
                    key: getattr(explanation, key)
                    for key in EXPLANATION_DETAIL
                    if hasattr(explanation, key)
                }
                run.mark(state, "RAN", action=action, **detail)
        elif state == "HUMAN_REVIEW":
            run.mark(state, "RAN", pending=True)  # the review command arrives with Task 8
        elif failure is not None:
            run.mark(state, "SKIPPED", reason=MODEL_UNAVAILABLE)
        else:
            try:
                _model_state(run, client, call_tool, state, intent, question, max_attempts)
            except MODEL_ERRORS as exc:
                failure = _failure(exc)
                run.mark(state, "FAILED", **failure)

    if failure is not None:
        run.close(route, MODEL_UNAVAILABLE, MODEL_UNAVAILABLE_ANSWERS[language])
        return analysis
    blocked = gate is not None and gate.status in BLOCKING_STATUSES
    if blocked:
        run.close(route, ANALYSIS_UNSAFE)
    else:
        run.close(route, action or COMPLETED, answer)
    return analysis


def _failure(exc: BaseException) -> dict:
    """The error class and a short message, with any server address taken out."""
    message = _ADDRESS.sub("<address>", str(exc))[:300]
    return {"error": type(exc).__name__, "message": message}


# --- call checks -----------------------------------------------------------------------
# One resolver of sector names, shared with the intent check (harness.intent).
_sector_group = peers.sector_group


def _intent_group(intent: Intent) -> str | None:
    """The peer group the question is about: its sector, else its stock's group."""
    if intent.sector:
        return _sector_group(intent.sector)
    if intent.ticker:
        try:
            return peers.peer_group_of(intent.ticker).name
        except KeyError:
            return None
    return None


def _ticker_problem(ticker: object, intent: Intent) -> str | None:
    wanted = normalize_ticker(ticker) if isinstance(ticker, str) else ticker
    if intent.ticker:
        return None if wanted == intent.ticker else f"ticker must be {intent.ticker}"
    group = _intent_group(intent)
    if group and wanted not in peers.resolve_sector(group).universe:
        return f"ticker must be a stock of the {group} group"
    return None


def _event_problem(arguments: dict, question: str) -> str | None:
    """Do the reversal event type and direction of a call fit what the question names?

    Only arguments that change what is analysed are checked; a question that names no
    event family or direction leaves them free (``intent.reversal_grounding``).
    """
    event_type = arguments.get("event_type")
    if not question or not isinstance(event_type, str):
        return None
    types, direction = reversal_grounding(question)
    if types and event_type not in types:
        return f"event_type must be {' or '.join(types)}"
    if direction:
        side = arguments.get("direction") or "BULLISH"  # the tool's default
        if SINGLE_DIRECTION.get(event_type, side) != direction:
            return f"direction must be {direction}"
    return None


def _intent_problem(
    arguments: dict, intent: Intent, analysis_id: str, question: str = ""
) -> str | None:
    """Do the stock, sector, dates and event of a call match the question's intent?"""
    if "analysis_id" in arguments and arguments["analysis_id"] != analysis_id:
        return f"analysis_id must be {analysis_id}"
    for key in ("start", "end"):
        if key in arguments and arguments[key] != getattr(intent, key):
            return f"{key} must be {getattr(intent, key)}"
    as_of = intent.as_of or intent.end
    if "as_of" in arguments and arguments["as_of"] != as_of:
        return f"as_of must be {as_of}"
    tickers = [arguments["ticker"]] if "ticker" in arguments else []
    tickers += list(arguments.get("universe") or [])
    for ticker in tickers:
        problem = _ticker_problem(ticker, intent)
        if problem:
            return problem
    if "sector" in arguments:
        group = _intent_group(intent)
        if group and _sector_group(arguments["sector"]) != group:
            return f"sector must be {group}"
    return _event_problem(arguments, question)


def check_call(
    state: str,
    name: str,
    arguments: dict,
    intent: Intent,
    *,
    analysis_id: str,
    question: str = "",
) -> tuple[str, str] | None:
    """Check one proposed call in order: schema, permission of the state, intent.

    Returns ``(code, message)`` for a rejected call, ``None`` for a valid one. The message
    is short: it goes back to the model.
    """
    problem = validate_tool_call(name, arguments)
    if problem is not None:
        return "INVALID_CALL", f"{name}: {problem}."
    if name not in ALLOWED_TOOLS[state]:
        allowed = ", ".join(ALLOWED_TOOLS[state])
        return "TOOL_NOT_ALLOWED", f"{name} is not allowed in {state}; call one of: {allowed}."
    problem = _intent_problem(arguments, intent, analysis_id, question)
    if problem is not None:
        return "INTENT_MISMATCH", f"{name}: {problem}, as the question asks."
    return None


# --- canonical calls: what the harness calls when the model gives no valid call -------
BENCHMARK_INDEX = "XU100"
SECTOR_HORIZON_DAYS = 20
REVERSAL_EVENT = "BOLLINGER_LOWER_TOUCH"
# Canonical event when the question names a direction but no family: the first that fits.
_EVENT_PREFERENCE = (
    REVERSAL_EVENT,
    "BOLLINGER_UPPER_TOUCH",
    *(t for t in REVERSAL_EVENT_TYPES if t not in (REVERSAL_EVENT, "BOLLINGER_UPPER_TOUCH")),
)
REVERSAL_FORWARD_DAYS = 5
WEEKDAY_PATTERN = "WEEKDAY_MEANS"
# The variant whose feature layers match the scenario; A_TECHNICAL for the rest.
DEFAULT_STRATEGY = {"SECTOR_LAGGARD": "B_TECH_SECTOR", "FUNDAMENTAL_REACTION": "C_TECH_SECTOR_FUND"}
# The fundamentals variants are defined from the test period on: ``run_backtest`` rejects
# a period that ends before it (and clamps one that only starts before it), so a period
# ending before the test period falls back to the sector variant.
FUNDAMENTALS_FROM = TEST_PERIOD[0]
PRE_FUNDAMENTALS_STRATEGY = "B_TECH_SECTOR"
MALFORMED_TOOL = "(malformed)"  # tool name recorded for a call that could not be parsed


def _grounded_event(question: str) -> dict:
    """``event_type`` (and ``direction`` for a two-sided family) grounded in the question."""
    types, direction = reversal_grounding(question) if question else (None, None)
    if types:
        event_type = types[0]
    elif direction is None:
        event_type = REVERSAL_EVENT
    else:
        event_type = next(
            t for t in _EVENT_PREFERENCE if SINGLE_DIRECTION.get(t, direction) == direction
        )
    if direction and event_type not in SINGLE_DIRECTION:
        return {"event_type": event_type, "direction": direction}
    return {"event_type": event_type}


def canonical_calls(state: str, intent: Intent, *, question: str = "") -> list[tuple[str, dict]]:
    """The calls a tool state makes for this intent, every one valid under ``check_call``
    (with the same ``question``: the reversal event follows what the question names).

    A state that needs a stock while the intent names none (a sector question) has no
    canonical call: ``[]``.
    """
    ticker, period = intent.ticker, {"start": intent.start, "end": intent.end}
    as_of = intent.as_of or intent.end
    group = _intent_group(intent)
    if state == "LOAD_MARKET_DATA":
        index = [("get_index_history", {"index": BENCHMARK_INDEX, **period})]
        return [("get_stock_history", {"ticker": ticker, **period}), *index] if ticker else index
    if state == "CALCULATE_TECHNICALS" and ticker:
        return [
            ("calculate_indicators", {"ticker": ticker, **period, "indicators": []}),
            ("find_support_resistance", {"ticker": ticker, **period}),
        ]
    if state == "RUN_SECTOR_RELATIVE_ANALYSIS" and group:
        arguments = {"sector": group, "horizon_days": SECTOR_HORIZON_DAYS, "as_of": as_of}
        return [("rank_sector_relative_strength", arguments)]
    if state == "RUN_PATTERN_AND_REVERSAL_ANALYSIS" and ticker:
        if intent.scenario == "CALENDAR_PATTERN":
            pattern = {"ticker": ticker, "pattern": WEEKDAY_PATTERN, **period}
            return [("test_weekday_pattern", pattern)]
        event = {
            "ticker": ticker,
            **period,
            **_grounded_event(question),
            "forward_days": REVERSAL_FORWARD_DAYS,
        }
        return [("detect_reversal_events", event)]
    if state == "LOAD_FUNDAMENTALS" and ticker:
        return [
            ("get_fundamental_metrics", {"ticker": ticker, "as_of": as_of}),
            ("calculate_fundamental_change", {"ticker": ticker, "as_of": as_of}),
        ]
    if state == "LOAD_MACRO_CONTEXT":
        return [("get_macro_context", dict(period))]
    if state == "LOAD_NEWS_AND_SPEECH_CONTEXT":
        return [("get_news_events", {"ticker": ticker, **period} if ticker else dict(period))]
    if state == "RUN_BACKTEST":
        if ticker:
            universe = [ticker]
        elif group:
            universe = list(peers.resolve_sector(group).universe)
        else:
            universe = []
        strategy = DEFAULT_STRATEGY.get(intent.scenario, "A_TECHNICAL")
        if strategy in FEATURE_FILTERS and (intent.end or "") < FUNDAMENTALS_FROM:
            strategy = PRE_FUNDAMENTALS_STRATEGY
        return [("run_backtest", {"strategy": strategy, "universe": universe, **period})]
    return []


# --- model states ----------------------------------------------------------------------
# First line of every tool-state prompt: the fine-tuning teacher recognises the turn by it.
TOOL_STATE_PROMPT = "You are the tool-calling step of an educational BIST 100 analysis harness."


def _state_prompt(state: str, intent: Intent) -> str:
    lines = [
        TOOL_STATE_PROMPT,
        f"Current state: {state}. Call one or more of these tools: "
        f"{', '.join(ALLOWED_TOOLS[state])}.",
        "Use exactly these values from the question's intent: "
        f"ticker={intent.ticker}, sector={intent.sector}, start={intent.start}, "
        f"end={intent.end}, as_of={intent.as_of or intent.end}.",
        "Answer with tool calls only, never with text.",
    ]
    if state == "RUN_BACKTEST":
        lines.append(f"Strategy variants: {', '.join(STRATEGY_VARIANTS)}.")
    return "\n".join(lines)


def _model_state(
    run: _Run,
    client,
    call_tool: ToolCaller,
    state: str,
    intent: Intent,
    question: str,
    max_attempts: int,
) -> None:
    """One model turn in a tool state: propose, check and execute; retry, then fall back."""
    tools = to_ollama_tools(ALLOWED_TOOLS[state])
    messages = [
        {"role": "system", "content": _state_prompt(state, intent)},
        {"role": "user", "content": question},
    ]
    allowed = ", ".join(ALLOWED_TOOLS[state])
    attempts = rejected = text_replies = 0
    executed = False
    while attempts < max_attempts and not executed:
        attempts += 1
        result = client.chat(
            messages, tools=tools, temperature=session.TEMPERATURE, seed=session.SEED
        )
        errors: list[str] = []
        if result.malformed_tool_call:
            # A call attempt that could not be parsed counts as a wrong tool call.
            message = f"The tool call could not be parsed; call one of: {allowed}."
            run.record(
                state,
                MALFORMED_TOOL,
                {},
                {"error": {"code": "MALFORMED_CALL", "message": message}},
                allowed=False,
                source="model",
            )
            rejected += 1
            errors.append(message)
        elif not result.tool_calls:
            text_replies += 1
            errors.append(f"A text answer is not accepted in {state}; call one of: {allowed}.")
        for proposal in result.tool_calls:
            arguments = dict(proposal.arguments)
            problem = check_call(
                state,
                proposal.name,
                arguments,
                intent,
                analysis_id=run.analysis.analysis_id,
                question=question,
            )
            if problem is not None:
                code, message = problem
                run.record(
                    state,
                    proposal.name,
                    arguments,
                    {"error": {"code": code, "message": message}},
                    allowed=False,
                    source="model",
                )
                rejected += 1
                errors.append(message)
                continue
            run.execute(call_tool, state, proposal.name, arguments, "model")
            executed = True
        if not executed:
            messages = [
                *messages,
                {"role": "assistant", "content": result.content},
                {"role": "user", "content": "Rejected: " + " ".join(errors)},
            ]
    fallback = not executed
    topped_up: list[str] = []
    if fallback:  # no valid call in max_attempts: the harness calls what the intent implies
        for name, arguments in canonical_calls(state, intent, question=question):
            run.execute(call_tool, state, name, arguments, "harness")
    else:  # the model's valid calls stay; the harness adds what the minimum still needs
        for name, arguments in top_up_calls(run.analysis, state, intent, question=question):
            run.execute(call_tool, state, name, arguments, "harness")
            topped_up.append(name)
    extra = {"topped_up": topped_up} if topped_up else {}
    run.mark(
        state,
        "RAN",
        attempts=attempts,
        rejected=rejected,
        text_replies=text_replies,
        fallback=fallback,
        **extra,
    )


def _same_call_key(arguments: dict) -> dict:
    """Arguments as the tool reads them: a ticker in any case is the same stock."""
    ticker = arguments.get("ticker")
    return (
        {**arguments, "ticker": normalize_ticker(ticker)} if isinstance(ticker, str) else arguments
    )


def top_up_calls(
    analysis: session.Analysis, state: str, intent: Intent, *, question: str = ""
) -> list[tuple[str, dict]]:
    """Canonical calls of the state that the scenario's minimum evidence still needs.

    A call is added when its tool supplies a ``(tool, field)`` kind of a requirement of
    ``evidence.MINIMUM`` that no executed call has met yet, and the same call (tool and
    arguments) has not run already. So one partial model call (``calculate_indicators``
    with only ``BOLLINGER``, ``get_fundamental_metrics`` without
    ``calculate_fundamental_change``) no longer decides what evidence the analysis has.
    """
    missing = set(missing_requirements(build_evidence(analysis, language="en"), intent.scenario))
    needed = {
        tool
        for name, kinds in MINIMUM.get(intent.scenario, ())
        if name in missing
        for tool, _ in kinds
    }
    ran = [
        (c.tool, _same_call_key(c.arguments))
        for c in analysis.tool_calls
        if c.allowed and isinstance(c.output, dict) and "error" not in c.output
    ]
    calls = []
    for name, arguments in canonical_calls(state, intent, question=question):
        if name in needed and (name, _same_call_key(arguments)) not in ran:
            calls.append((name, arguments))
    return calls
