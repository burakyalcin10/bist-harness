"""Quality checks of the fine-tuning data (Sprint 5, Task 4; EC-052).

``run_qc`` re-checks every record with the harness's own code, so a record that trains the
model on something the harness would reject is found before training. ``dedupe`` removes
near-duplicate questions and questions whose text is shared with a different target.
``sample_for_review`` draws the records Burak reads by hand. The CLI reports; it does not
rewrite the data files::

    uv run python -m bist_harness.finetune.qc data/finetune/

writes ``qc.json`` (findings, counts per check, dedupe counts) and ``review-sample.md``.

How a record is read: the records carry no ``tool`` messages. The evidence an explanation
may cite is the evidence list in the explanation turn's user message, so the number check
runs against that list. Tool calls are checked against the state and the intent the state
prompt renders (the teacher's own parsing).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from bist_harness.eval import questions as frozen
from bist_harness.finetune.build import test_period_dates
from bist_harness.finetune.record import TrainingRecord, read_jsonl
from bist_harness.finetune.teacher import (
    Gold,
    TeacherClient,
    _explanation_flags,
    _listed_evidence,
)
from bist_harness.harness.evidence import DISCLAIMER, TEMPLATES
from bist_harness.harness.intent import fold_text
from bist_harness.harness.machine import check_call
from bist_harness.harness.validator import (
    advice_language,
    period_notes,
    unsupported_values,
    validate_explanation,
)
from bist_harness.tools.schemas import ACTIONS, validate_tool_call

__all__ = ["CHECKS", "QCFinding", "dedupe", "dedupe_report", "run_qc", "sample_for_review"]

CHECKS = (
    "numbers_in_tool_output",
    "call_schema_valid",
    "call_allowed_and_on_intent",
    "label_in_eight",
    "no_advice_language",
    "validator_accepts",
    "no_frozen_overlap",
    "no_test_period_data",
)
DEDUPE_THRESHOLD = 0.95
_EVIDENCE = "\n\nEvidence:\n"


@dataclass(frozen=True)
class QCFinding:
    record_id: str
    check: str
    detail: str


# --- the test-period phrases, derived from the harness's own sentence templates -------------
def _test_period_phrases() -> tuple[str, ...]:
    """Folded date-free phrases that name the test period, read from the ``by_period`` templates.

    Those templates are the ones that say it in words ("test döneminde", "In the test
    period"); the phrases are cut out of them, so a reworded template changes them too.
    """
    phrases: list[str] = []
    for (_, field), forms in TEMPLATES.items():
        if not field.startswith("by_period."):
            continue
        tr = re.search(r"test d\w+", forms["tr"])
        en = re.search(r"the test period", forms["en"], re.IGNORECASE)
        phrases += [fold_text(m[0]).strip() for m in (tr, en) if m]
    return tuple(dict.fromkeys(phrases))


TEST_PERIOD_PHRASES = _test_period_phrases()


# --- reading a record -------------------------------------------------------------------------
def _question_text(record: TrainingRecord) -> str:
    """The question of the record: its user message (an explanation's has a prefix)."""
    user = next((m.get("content", "") for m in record.messages if m.get("role") == "user"), "")
    if record.turn == "explanation":
        try:
            return _listed_evidence(user)[0]
        except ValueError:
            return user.removeprefix("Question: ").split(_EVIDENCE)[0]
    return user


def _explanation_parts(record: TrainingRecord) -> dict:
    """Everything an explanation check needs, or ``{"error": ...}`` when it cannot be read."""
    try:
        eligible = list(record.meta["eligible"])
        system = record.messages[0]["content"]
        question, committed = _listed_evidence(record.messages[1]["content"])
        language, defaulted, bound = _explanation_flags(system, eligible)
        data = json.loads(record.target["content"])
        action, text = data["action"], data["explanation"]
        if not isinstance(action, str) or not isinstance(text, str):
            raise ValueError("action and explanation are not strings")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return {"error": f"the explanation turn cannot be read: {exc}"}
    return {
        "eligible": eligible,
        "question": question,
        "committed": committed,
        "language": language,
        "defaulted": defaulted,
        "bound": bound,
        "action": action,
        "text": text,
    }


def _without_fixed_lines(text: str, language: str) -> str:
    """The text without the disclaimer and the period notes (the harness strips them too)."""
    text = text.replace(DISCLAIMER[language], "\n")
    for note in period_notes(language):
        text = text.replace(note, "\n")
    return text


# --- the checks ---------------------------------------------------------------------------------
def _explanation_findings(record: TrainingRecord) -> list[tuple[str, str]]:
    parts = _explanation_parts(record)
    if "error" in parts:
        return [("validator_accepts", parts["error"])]
    out: list[tuple[str, str]] = []
    language = parts["language"]
    body = _without_fixed_lines(parts["text"], language)
    numbers, dates = unsupported_values(body, parts["committed"], parts["question"])
    if numbers or dates:
        shown = [f"{n:g}" for n in numbers] + list(dates)
        out.append(("numbers_in_tool_output", "not in the cited evidence: " + ", ".join(shown)))
    if parts["action"] not in ACTIONS:
        out.append(("label_in_eight", f"{parts['action']!r} is not one of the eight labels"))
    phrases = advice_language(body)
    if phrases:
        out.append(("no_advice_language", "advice or prediction language: " + ", ".join(phrases)))
    problems = validate_explanation(
        parts["text"],
        action=parts["action"],
        eligible=parts["eligible"],
        evidence=parts["committed"],
        question=parts["question"],
        language=language,
        defaulted_period=parts["defaulted"],
        defaulted_bound=parts["bound"],
    )
    if problems:
        out.append(("validator_accepts", "; ".join(problems)))
    return out


def _call_findings(record: TrainingRecord) -> list[tuple[str, str]]:
    calls = record.target.get("tool_calls") or []
    if not calls:
        return [("call_schema_valid", "a tool_call record without a tool call")]
    offered = {t.get("function", {}).get("name") for t in record.tools}
    out: list[tuple[str, str]] = []
    valid: list[tuple[str, dict]] = []
    for call in calls:
        function = call.get("function", {})
        name, arguments = function.get("name"), function.get("arguments")
        problem = validate_tool_call(name, arguments)
        if problem is None and name not in offered:
            problem = f"{name} is not among the tools offered in the record"
        if problem is not None:
            out.append(("call_schema_valid", problem))
        if validate_tool_call(name, arguments) is None:
            valid.append((name, arguments))
    # the state and the intent, as the teacher reads them from the state prompt
    gold = Gold(
        {
            "scenario": record.scenario,
            "ticker": None,
            "sector": None,
            "start": None,
            "end": None,
            "as_of": None,
            "language": record.language,
        }
    )
    try:
        state, intent = TeacherClient(gold)._state_intent(record.messages[0]["content"])
    except (ValueError, KeyError, IndexError) as exc:
        return [*out, ("call_allowed_and_on_intent", f"the state prompt cannot be read: {exc}")]
    if state != record.state:
        out.append(
            ("call_allowed_and_on_intent", f"state {state} in the prompt, not {record.state}")
        )
    question = _question_text(record)
    for name, arguments in valid:
        problem = check_call(state, name, arguments, intent, analysis_id="", question=question)
        if problem is not None:
            out.append(("call_allowed_and_on_intent", f"{problem[0]}: {problem[1]}"))
    return out


def _test_period_findings(record: TrainingRecord) -> list[tuple[str, str]]:
    found = test_period_dates(record)
    text = fold_text(json.dumps([record.messages, record.tools, record.target], ensure_ascii=False))
    found += [phrase for phrase in TEST_PERIOD_PHRASES if phrase in text]
    if not found:
        return []
    return [("no_test_period_data", "test-period evidence: " + ", ".join(found))]


def run_qc(records: Sequence[TrainingRecord]) -> list[QCFinding]:
    """Every finding of the checks over the records, in record order then ``CHECKS`` order."""
    records = list(records)
    texts = list(dict.fromkeys(_question_text(r) for r in records))
    overlapping: dict[str, tuple[str, str, float]] = {}
    for found in frozen.overlaps(texts):
        overlapping.setdefault(found[0], found)
    findings: list[QCFinding] = []
    for record in records:
        raw: list[tuple[str, str]] = []
        if record.turn == "explanation":
            raw += _explanation_findings(record)
        elif record.turn == "tool_call":
            raw += _call_findings(record)
        hit = overlapping.get(_question_text(record))
        if hit is not None:
            raw.append(("no_frozen_overlap", f"overlaps frozen question {hit[1]} ({hit[2]})"))
        raw += _test_period_findings(record)
        raw.sort(key=lambda item: CHECKS.index(item[0]))
        findings += [QCFinding(record.record_id, check, detail) for check, detail in raw]
    return findings


# --- dedupe ---------------------------------------------------------------------------------------
def _signature(group: list[TrainingRecord]) -> tuple:
    return tuple((r.turn, json.dumps(r.target, ensure_ascii=False, sort_keys=True)) for r in group)


def _similar(a: str, b: str, threshold: float) -> bool:
    matcher = SequenceMatcher(None, a, b)
    return (
        matcher.real_quick_ratio() >= threshold
        and matcher.quick_ratio() >= threshold
        and matcher.ratio() >= threshold
    )


def dedupe_report(
    records: Sequence[TrainingRecord], *, threshold: float = DEDUPE_THRESHOLD
) -> tuple[list[TrainingRecord], dict]:
    """``(kept records, report)``; the report names every dropped question and its twin.

    Questions are taken in ``question_id`` order and the first of a pair stays. A question
    goes when an earlier kept one has (a) a folded text with similarity >= ``threshold``
    and the same turns with the same targets (near duplicate), or (b) the identical folded
    text, another family and different targets (two families teach one text two answers).
    All turns of a question stay or go together; the records keep their order.
    """
    groups: dict[str, list[TrainingRecord]] = {}
    for record in records:
        groups.setdefault(record.question_id, []).append(record)
    kept_ids: list[str] = []
    meta: dict[str, tuple[str, str, tuple]] = {}  # id -> (folded text, family, signature)
    near: list[dict] = []
    conflicting: list[dict] = []
    for qid in sorted(groups):
        group = groups[qid]
        folded = fold_text(_question_text(group[0])).strip()
        family, signature = group[0].family, _signature(group)
        verdict = None
        for other in kept_ids:
            other_text, other_family, other_signature = meta[other]
            if signature == other_signature and (
                folded == other_text or _similar(folded, other_text, threshold)
            ):
                verdict = ("near_duplicate", other)
                break
            if folded == other_text and family != other_family and signature != other_signature:
                verdict = ("conflicting_targets", other)
                break
        if verdict is None:
            kept_ids.append(qid)
            meta[qid] = (folded, family, signature)
            continue
        row = {"question_id": qid, "family": family, "kept": verdict[1], "records": len(group)}
        (near if verdict[0] == "near_duplicate" else conflicting).append(row)
    dropped = {row["question_id"] for row in near + conflicting}
    kept = [r for r in records if r.question_id not in dropped]
    report = {
        "threshold": threshold,
        "near_duplicate_questions": len(near),
        "conflicting_target_questions": len(conflicting),
        "records_removed": len(records) - len(kept),
        "dropped": {"near_duplicate": near, "conflicting_targets": conflicting},
    }
    return kept, report


def dedupe(
    records: Sequence[TrainingRecord], *, threshold: float = DEDUPE_THRESHOLD
) -> tuple[list[TrainingRecord], int]:
    """``(kept records, number of records removed)``; ``dedupe_report`` has the details."""
    kept, report = dedupe_report(records, threshold=threshold)
    return kept, report["records_removed"]


# --- the review sample ----------------------------------------------------------------------------
def sample_for_review(
    records: Sequence[TrainingRecord], n: int = 50, *, seed: int = 42
) -> list[TrainingRecord]:
    """``n`` records stratified by scenario and turn kind, the same for a seed.

    The strata are visited round robin in sorted order, one random record of the stratum
    each time, until ``n`` records are taken or none are left.
    """
    rng = random.Random(seed)
    strata: dict[tuple[str, str], list[TrainingRecord]] = {}
    for record in sorted(records, key=lambda r: r.record_id):
        strata.setdefault((record.scenario, record.turn), []).append(record)
    for key in sorted(strata):
        rng.shuffle(strata[key])
    chosen: list[TrainingRecord] = []
    while len(chosen) < n and any(strata.values()):
        for key in sorted(strata):
            if strata[key] and len(chosen) < n:
                chosen.append(strata[key].pop())
    return chosen


def _show(record: TrainingRecord) -> str:
    where = f"{record.scenario} / {record.turn}"
    if record.state:
        where += f" / {record.state}"
    lines = [
        f"## {record.record_id} ({where} / {record.language} / {record.family})",
        "",
        f"**Question:** {_question_text(record)}",
        "",
    ]
    if record.turn == "intent":
        lines += ["**Target (intent):**", "```json", record.target.get("content", ""), "```"]
    elif record.turn == "tool_call":
        system = record.messages[0]["content"]
        shown = [
            ln for ln in system.splitlines() if ln.startswith(("Current state", "Use exactly"))
        ]
        calls = json.dumps(record.target.get("tool_calls"), ensure_ascii=False, indent=1)
        lines += ["**Prompt (state and intent values):**", "```", *shown, "```"]
        lines += ["**Target (tool calls):**", "```json", calls, "```"]
    else:
        parts = _explanation_parts(record)
        if "error" in parts:
            lines += [f"**Unreadable:** {parts['error']}"]
        else:
            cited = set(re.findall(r"\[(E\d+)\]", parts["text"]))
            lines += [f"**Eligible labels:** {', '.join(parts['eligible'])}", ""]
            lines += ["**Cited evidence:**"]
            lines += [f"- [{e.label}] {e.sentence}" for e in parts["committed"] if e.label in cited]
            lines += ["", f"**Target action:** {parts['action']}", "", "**Target explanation:**"]
            lines += ["```", parts["text"], "```"]
    lines += [""]
    return "\n".join(lines)


def _review_markdown(sample: Sequence[TrainingRecord], seed: int) -> str:
    head = (
        f"# Review sample\n\n{len(sample)} records, stratified by scenario and turn kind "
        f"(seed {seed}). To be read by hand; problems found go back into the templates and "
        "the data is rebuilt.\n\n"
    )
    return head + "\n".join(_show(r) for r in sample)


# --- command line ---------------------------------------------------------------------------------
def _write(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quality checks of the fine-tuning data.")
    parser.add_argument("directory", type=Path, help="the folder with train/val/test.jsonl")
    parser.add_argument("--sample", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    records: list[TrainingRecord] = []
    for name in ("train", "val", "test"):
        path = args.directory / f"{name}.jsonl"
        if path.exists():
            records += read_jsonl(path)
    findings = run_qc(records)
    _, report = dedupe_report(records)
    counts = Counter(f.check for f in findings)
    payload = {
        "records": len(records),
        "findings_total": len(findings),
        "counts": {check: counts.get(check, 0) for check in CHECKS},
        "dedupe": report,
        "findings": [
            {"record_id": f.record_id, "check": f.check, "detail": f.detail} for f in findings
        ],
    }
    _write(args.directory / "qc.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    sample = sample_for_review(records, args.sample, seed=args.seed)
    _write(args.directory / "review-sample.md", _review_markdown(sample, args.seed))
    print(f"[qc] {len(records)} records, {len(findings)} findings {json.dumps(payload['counts'])}")
    print(
        f"[qc] dedupe would remove {report['near_duplicate_questions']} near-duplicate and "
        f"{report['conflicting_target_questions']} conflicting-target questions "
        f"({report['records_removed']} records)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
