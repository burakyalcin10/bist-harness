"""The teacher: a chat client that gives the harness the correct reply at every model turn.

Fine-tuning data is not written by hand. The real harness (``machine.run_analysis``) runs
a generated question with a ``TeacherClient`` in place of the model; the tools run on real
data. At each model turn the teacher builds the correct reply in code and records the
turn as a ``TrainingRecord``: the messages and tool schemas the harness sent, as sent, and
the reply as the target. So the training format is the inference format.

The turn kind is recognised from what the harness sent, by its shared constants:

- ``intent``: the system message is ``intent.INTENT_SYSTEM_PROMPT``. Target: the gold
  intent as JSON. The gold intent must already be what ``ground_intent`` keeps of it for
  the question (no field the question does not name), and a question the keyword guard
  labels as advice or prediction must have that scenario.
- ``tool_call``: the system message starts with ``machine.TOOL_STATE_PROMPT``; the state is
  read from the prompt, which must re-render exactly. Target: ``canonical_calls(state,
  intent, question=...)``, each one checked with ``machine.check_call``.
- ``explanation``: called with ``validator.explanation_schema(eligible)``. Target: the
  action (``Gold.action``; when it is None, the first eligible label) and one line per
  committed evidence item, the item's sentence copied as written (numbers with their sign)
  and cited ``[En]``; then the period note when the period was defaulted, and the
  disclaimer line, both in the validator's exact wording.

Anything else raises ``ValueError``. The teacher never writes a target it cannot stand
behind; it raises ``TeacherError`` instead (the harness does not catch it, so the run
stops and the caller drops the question):

- a target that fails its own check (grounding, guard, ``check_call``, an action that is
  not eligible, ``validate_explanation``);
- a second request for the same turn: the harness rejected the teacher's reply.

The explanation check runs ``validate_explanation`` with the eligible labels, question,
language and period flags of the prompt (each confirmed by re-rendering the prompt) and
with the committed items the prompt lists. The harness validates the same reply again with
its full evidence set; a rejection there comes back as a second request and raises.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass

from bist_harness.harness.evidence import DISCLAIMER, LANGUAGES, Evidence
from bist_harness.harness.intent import (
    INTENT_SCHEMA,
    INTENT_SYSTEM_PROMPT,
    SCENARIOS,
    Intent,
    ground_intent,
    keyword_guard,
)
from bist_harness.harness.machine import (
    TOOL_STATE_PROMPT,
    _state_prompt,
    canonical_calls,
    check_call,
)
from bist_harness.harness.routes import ALLOWED_TOOLS
from bist_harness.harness.validator import (
    _system_prompt,
    _user_prompt,
    explanation_schema,
    period_note,
    validate_explanation,
)
from bist_harness.llm.client import ChatResult, ToolCall
from bist_harness.tools.schemas import ACTIONS

from .record import TrainingRecord

__all__ = ["CapturingClient", "Gold", "TeacherClient", "TeacherError"]

_GUARDED = ("ADVICE_REQUEST", "PREDICTION_REQUEST")
_STATE = re.compile(r"^Current state: ([A-Z_]+)\.", re.MULTILINE)
_VALUES = re.compile(
    r"^Use exactly these values from the question's intent: ticker=(.*), sector=(.*), "
    r"start=(.*), end=(.*), as_of=(.*)\.$",
    re.MULTILINE,
)
# (defaulted_period, defaulted_bound) of an intent, as the explanation prompt renders them.
_PERIOD_CASES = ((False, None), (True, None), (True, "start"), (True, "end"))
_QUESTION, _EVIDENCE = "Question: ", "\n\nEvidence:\n"


class TeacherError(RuntimeError):
    """The teacher cannot give a correct reply for this turn; drop the question."""


@dataclass(frozen=True)
class Gold:
    """The correct answers for one question.

    ``intent`` fits ``INTENT_SCHEMA`` (all seven keys). ``action`` is the label of the
    explanation turn; when it is None and the harness allows several labels, the teacher
    takes the first one of the eligible list (``actions.eligible_actions`` keeps the order
    of ``ACTIONS``, so HOLD comes first when it is allowed). A gold action that the harness
    does not allow for the run raises ``TeacherError``.
    """

    intent: dict
    action: str | None = None

    def __post_init__(self) -> None:
        required = INTENT_SCHEMA["required"]
        if set(self.intent) != set(required):
            raise ValueError(f"a gold intent has exactly the keys {', '.join(required)}")
        if self.intent["scenario"] not in SCENARIOS:
            raise ValueError(f"unknown scenario: {self.intent['scenario']!r}")
        if self.intent["language"] not in LANGUAGES:
            raise ValueError(f"unknown language: {self.intent['language']!r}")
        for key in ("ticker", "sector", "start", "end", "as_of"):
            if self.intent[key] is not None and not isinstance(self.intent[key], str):
                raise ValueError(f"{key} is a string or None")
        if self.action is not None and self.action not in ACTIONS:
            raise ValueError(f"unknown action label: {self.action!r}")


def _reply(content: str = "", calls: tuple[ToolCall, ...] = ()) -> ChatResult:
    return ChatResult(
        content=content,
        tool_calls=calls,
        prompt_tokens=0,
        completion_tokens=0,
        total_duration_s=0.0,
        eval_tokens_per_s=None,
        raw={},
    )


def _none(value: str) -> str | None:
    return None if value == "None" else value


class TeacherClient:
    """A ``ChatClient`` that answers each model turn correctly and records it in ``turns``.

    One teacher per question. ``question_id`` and ``family`` only label the records.
    """

    model = "teacher"

    def __init__(self, gold: Gold, *, question_id: str = "", family: str = ""):
        self.gold = gold
        self.question_id = question_id
        self.family = family
        self.turns: list[TrainingRecord] = []

    # --- the ChatClient interface ------------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        **kwargs,
    ) -> ChatResult:
        first = messages[0] if messages else {}
        system = first.get("content", "") if first.get("role") == "system" else ""
        if system == INTENT_SYSTEM_PROMPT:
            kind = "intent"
        elif system.startswith(TOOL_STATE_PROMPT):
            kind = "tool_call"
        elif _eligible_of(response_format) is not None:
            kind = "explanation"
        else:
            raise ValueError("not a model turn of the harness: no known prompt or schema")
        if len(messages) != 2:  # system and question; more means a rejected reply
            last = messages[-1].get("content", "")
            raise TeacherError(f"the harness rejected the teacher's {kind} reply: {last}")
        if kind == "intent":
            return self._intent(messages, response_format)
        if kind == "tool_call":
            return self._tool_call(messages, tools)
        return self._explanation(messages, response_format)

    # --- the three turns -----------------------------------------------------------------
    def _intent(self, messages: list[dict], response_format: dict | None) -> ChatResult:
        if response_format != INTENT_SCHEMA:
            raise ValueError("an intent turn is constrained by INTENT_SCHEMA")
        question = messages[1]["content"]
        intent = Intent(**self.gold.intent)
        grounded = ground_intent(intent, question)
        if grounded != intent:
            raise TeacherError(
                f"the gold intent names what the question does not: {grounded.grounded}"
            )
        found = keyword_guard(question)
        if found is not None and intent.scenario not in _GUARDED:
            raise TeacherError(f"the keyword guard labels the question {found}")
        ordered = {key: self.gold.intent[key] for key in INTENT_SCHEMA["required"]}
        content = json.dumps(ordered, ensure_ascii=False)
        self._record("intent", None, messages, [], {"role": "assistant", "content": content})
        return _reply(content)

    def _tool_call(self, messages: list[dict], tools: list[dict] | None) -> ChatResult:
        system, question = messages[0]["content"], messages[1]["content"]
        state, intent = self._state_intent(system)
        calls = canonical_calls(state, intent, question=question)
        if not calls:
            raise TeacherError(f"no canonical call in {state} for this intent")
        for name, arguments in calls:
            problem = check_call(state, name, arguments, intent, analysis_id="", question=question)
            if problem is not None:
                raise TeacherError(f"canonical call rejected in {state}: {problem[1]}")
        target = {
            "role": "assistant",
            "tool_calls": [
                {"type": "function", "function": {"name": name, "arguments": arguments}}
                for name, arguments in calls
            ],
        }
        self._record("tool_call", state, messages, tools or [], copy.deepcopy(target))
        return _reply(calls=tuple(ToolCall(n, copy.deepcopy(a)) for n, a in calls))

    def _explanation(self, messages: list[dict], response_format: dict | None) -> ChatResult:
        eligible = _eligible_of(response_format) or []
        language, defaulted, bound = _explanation_flags(messages[0]["content"], eligible)
        question, committed = _listed_evidence(messages[1]["content"])
        action = self.gold.action or eligible[0]
        if action not in eligible:
            raise TeacherError(f"gold action {action} is not eligible: {', '.join(eligible)}")
        lines = [f"{e.sentence} [{e.label}]" for e in committed]
        if defaulted:
            lines.append(period_note(language, bound))
        lines.append(DISCLAIMER[language])
        text = "\n".join(lines)
        problems = validate_explanation(
            text,
            action=action,
            eligible=eligible,
            evidence=committed,
            question=question,
            language=language,
            defaulted_period=defaulted,
            defaulted_bound=bound,
        )
        if problems:
            raise TeacherError("the explanation target fails the validator: " + "; ".join(problems))
        content = json.dumps({"action": action, "explanation": text}, ensure_ascii=False)
        meta = {"action": action, "eligible": list(eligible)}
        target = {"role": "assistant", "content": content}
        self._record("explanation", None, messages, [], target, meta, language=language)
        return _reply(content)

    # --- helpers --------------------------------------------------------------------------
    def _state_intent(self, system: str) -> tuple[str, Intent]:
        """The state and the harness's intent of a tool-state prompt, which must re-render."""
        state, values = _STATE.search(system), _VALUES.search(system)
        if state is None or values is None or state[1] not in ALLOWED_TOOLS:
            raise ValueError("a tool-state prompt that names no known state and intent")
        ticker, sector, start, end, as_of = (_none(v) for v in values.groups())
        intent = Intent(
            scenario=self.gold.intent["scenario"],
            ticker=ticker,
            sector=sector,
            start=start,
            end=end,
            as_of=as_of,  # rendered as ``as_of or end``, which is all a canonical call uses
            language=self.gold.intent["language"],
        )
        if _state_prompt(state[1], intent) != system:
            raise ValueError("the tool-state prompt does not re-render from its values")
        return state[1], intent

    def _record(
        self,
        turn: str,
        state: str | None,
        messages: list[dict],
        tools: list[dict],
        target: dict,
        meta: dict | None = None,
        *,
        language: str | None = None,
    ) -> None:
        self.turns.append(
            TrainingRecord(
                record_id=f"{self.question_id}-{len(self.turns):02d}",
                question_id=self.question_id,
                family=self.family,
                language=language or self.gold.intent["language"],
                scenario=self.gold.intent["scenario"],
                turn=turn,
                state=state,
                messages=copy.deepcopy(messages),
                tools=copy.deepcopy(tools),
                target=target,
                meta=meta or {},
            )
        )


def _eligible_of(response_format: object) -> list[str] | None:
    """The eligible labels when ``response_format`` is an explanation schema, else None."""
    try:
        eligible = list(response_format["properties"]["action"]["enum"])  # type: ignore[index]
    except (TypeError, KeyError):
        return None
    if not eligible or response_format != explanation_schema(eligible):
        return None
    return eligible


def _explanation_flags(system: str, eligible: list[str]) -> tuple[str, bool, str | None]:
    """Language, defaulted period and defaulted bound whose prompt is exactly ``system``."""
    for language in LANGUAGES:
        for defaulted, bound in _PERIOD_CASES:
            if _system_prompt(eligible, language, defaulted, bound) == system:
                return language, defaulted, bound
    raise ValueError("an explanation prompt that does not re-render")


def _listed_evidence(user: str) -> tuple[str, list[Evidence]]:
    """The question and the committed items the explanation prompt lists, re-rendered."""
    head, found, body = user.partition(_EVIDENCE)
    if not found or not head.startswith(_QUESTION):
        raise ValueError("an explanation prompt without a question and evidence")
    question = head[len(_QUESTION) :]
    items = []
    for line in body.split("\n"):
        label, _, sentence = line.partition(": ")
        items.append(Evidence(label, "", "", "", None, sentence, True))
    if _user_prompt(question, items) != user:
        raise ValueError("an explanation prompt that does not re-render")
    return question, items


class CapturingClient:
    """Passes every call to ``inner`` and keeps a copy of what was sent, in ``requests``."""

    def __init__(self, inner):
        self.inner = inner
        self.requests: list[dict] = []

    @property
    def model(self) -> str:
        return getattr(self.inner, "model", "unknown")

    def chat(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> ChatResult:
        sent = {"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)}
        self.requests.append({**sent, **copy.deepcopy(kwargs)})
        return self.inner.chat(messages, tools=tools, **kwargs)
