"""The fine-tuning data build: questions -> harness runs with the teacher -> split files.

One command builds the whole data set, with the same bytes every time::

    uv run python -m bist_harness.finetune.build --n-per-family 30 --out data/finetune/

Steps:

1. ``questions.generate(n_per_family, seed)``, then ``drop_overlaps`` against the frozen
   evaluation set (dropped questions are counted with their reason).
2. Each question runs through the real harness (``machine.run_analysis``) with a
   ``TeacherClient`` in place of the model; the tools run in process on the active
   snapshot. The teacher's turn records get the run-level meta (``outcome``,
   ``snapshot_id``, ``layers_id``, ``today``, ``template``).
3. A question is dropped, with its reason, when the teacher cannot answer a turn
   (``TeacherError`` or ``ValueError``: ``teacher_errors``) or when any of its records
   carries a date of the pre-registered test period (on or after 2025-01-01) in a
   message, a tool schema or the target (``test_period_date``).
4. ``split_by_family`` splits by paraphrase: a question's turns stay in one split, and
   ``val``/``test`` hold paraphrases that ``train`` never sees.
5. ``train.jsonl``, ``val.jsonl``, ``test.jsonl`` (``TrainingRecord`` lines),
   ``dev_questions.jsonl`` (the test questions in the frozen-set format, for
   ``run_eval --questions-file``) and ``manifest.json`` (counts, drops, versions,
   SHA-256 of every file, seed, wall time).
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import random
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from bist_harness.eval import metrics
from bist_harness.finetune import questions as gen
from bist_harness.finetune.record import TrainingRecord, write_jsonl
from bist_harness.finetune.teacher import TeacherClient, TeacherError
from bist_harness.harness import machine, session
from bist_harness.tools.schemas import ACTIONS

__all__ = [
    "CUTOFF",
    "HOLDOUT",
    "MIN_PARAPHRASES",
    "build",
    "split_by_family",
    "test_period_dates",
]

ToolCaller = Callable[[str, dict], dict]
CUTOFF = gen.CUTOFF  # the pre-registered test period starts here
SPLITS = ("train", "val", "test")
HOLDOUT = (("val", 0.1), ("test", 0.1))
MIN_PARAPHRASES = 3  # a pool with fewer paraphrases per language is split by question
RECORD_FILES = {name: f"{name}.jsonl" for name in SPLITS}
DEV_QUESTIONS = "dev_questions.jsonl"
MANIFEST = "manifest.json"
# The coverage table: the four mandatory scenarios x the eight action labels.
COVERAGE_SCENARIOS = (
    "SECTOR_LAGGARD",
    "CALENDAR_PATTERN",
    "TECHNICAL_REVERSAL",
    "FUNDAMENTAL_REACTION",
)
NEGATIVE_FAMILIES = (
    "advice_request",
    "prediction_request",
    "out_of_universe",
    "future_date",
    "no_tool_greeting",
    "no_tool_off_topic",
    "missing_information",
)
REPO_ROOT = Path(__file__).resolve().parents[3]

# Dates of the test period in training text: YYYY-MM-DD, YYYY-MM and YYYYQn.
_DATE = re.compile(r"(?<!\d)((?:19|20)\d\d)-(0[1-9]|1[0-2])(?:-(0[1-9]|[12]\d|3[01]))?(?!\d)")
_QUARTER = re.compile(r"(?<!\d)((?:19|20)\d\d) ?Q([1-4])(?!\d)")


def test_period_dates(record: TrainingRecord) -> list[str]:
    """The dates on or after 2025-01-01 in a record's messages, tool schemas and target.

    Full dates, year-months and quarters (``2025Q1``), in order of first appearance. The
    meta is not training text and is not searched.
    """
    text = json.dumps([record.messages, record.tools, record.target], ensure_ascii=False)
    found: dict[int, str] = {}
    for match in _DATE.finditer(text):
        if match[0] >= CUTOFF[: len(match[0])]:
            found.setdefault(match.start(), match[0])
    for match in _QUARTER.finditer(text):
        if match[1] >= CUTOFF[:4]:
            found.setdefault(match.start(), match[0].replace(" ", ""))
    return list(dict.fromkeys(found[k] for k in sorted(found)))


test_period_dates.__test__ = False  # type: ignore[attr-defined]  # not a pytest test


# --- the split ------------------------------------------------------------------------------
def _held_out_templates(rng: random.Random, holdout: Sequence[tuple[str, float]]) -> dict[str, str]:
    """Paraphrase template -> the held-out split it belongs to.

    Every pool of paraphrases (a family's templates in one language; families that share
    their paraphrases share one pool) with at least ``MIN_PARAPHRASES`` templates gives
    each held-out split ``max(1, round(fraction * size))`` of them, drawn with ``rng``;
    the rest stay in training.
    """
    pools: list[tuple[str, ...]] = []
    for family in gen.FAMILIES.values():
        for language in gen.LANGS:
            pool = tuple(family.templates[language])
            if pool not in pools:
                pools.append(pool)
    held: dict[str, str] = {}
    for pool in pools:
        if len(pool) < MIN_PARAPHRASES:
            continue
        order = list(pool)
        rng.shuffle(order)
        taken = 0
        for split, fraction in holdout:
            count = max(1, round(fraction * len(pool)))
            for template in order[taken : taken + count]:
                held.setdefault(template, split)
            taken += count
        if taken >= len(pool):
            raise ValueError("the held-out fractions leave no paraphrase for training")
    return held


def split_by_family(
    records: Iterable[TrainingRecord],
    *,
    seed: int = 42,
    holdout: tuple[tuple[str, float], ...] = HOLDOUT,
) -> dict[str, list]:
    """``{"train": [...], <held-out split>: [...]}``, records in their given order.

    The unit is the question: all its turns go to one split. A question goes to a
    held-out split when its paraphrase template (``meta["template"]``) is held out (see
    ``_held_out_templates``), so ``val`` and ``test`` hold paraphrases ``train`` never
    sees, for every family with at least ``MIN_PARAPHRASES`` per language. A question
    whose template is in no such pool is drawn by question with ``rng`` and the fractions.
    Deterministic for a seed.
    """
    rng = random.Random(seed)
    held = _held_out_templates(rng, holdout)
    names = ("train", *(split for split, _ in holdout))
    out: dict[str, list] = {name: [] for name in names}
    assigned: dict[str, str] = {}
    for record in records:
        split = assigned.get(record.question_id)
        if split is None:
            split = held.get(record.meta.get("template", ""))
            if split is None and not _in_a_pool(record.meta.get("template", "")):
                split = _draw(rng, holdout)
            assigned[record.question_id] = split or "train"
            split = assigned[record.question_id]
        out[split].append(record)
    return out


def _in_a_pool(template: str) -> bool:
    for family in gen.FAMILIES.values():
        for language in gen.LANGS:
            pool = family.templates[language]
            if template in pool and len(pool) >= MIN_PARAPHRASES:
                return True
    return False


def _draw(rng: random.Random, holdout: Sequence[tuple[str, float]]) -> str:
    value, edge = rng.random(), 0.0
    for split, fraction in holdout:
        edge += fraction
        if value < edge:
            return split
    return "train"


# --- one question ---------------------------------------------------------------------------
def _run(question: gen.GenQuestion, call_tool: ToolCaller):
    """``(records, analysis)`` of one harness run with the teacher."""
    teacher = TeacherClient(question.gold, question_id=question.question_id, family=question.family)
    before = set(session._LIVE)
    try:
        analysis = machine.run_analysis(
            question.text, teacher, call_tool=call_tool, today=question.today
        )
    finally:  # a build runs hundreds of questions: drop each finished run from memory
        for key in set(session._LIVE) - before:
            session._LIVE.pop(key, None)
    return teacher.turns, analysis


def _with_run_meta(records, analysis, question: gen.GenQuestion, layers_id: str) -> list:
    run_meta = {
        "outcome": analysis.outcome,
        "snapshot_id": analysis.snapshot_id,
        "layers_id": layers_id,
        "today": question.today,
        "template": question.template,
    }
    return [dataclasses.replace(r, meta={**r.meta, **run_meta}) for r in records]


def _dev_question(question: gen.GenQuestion, records: list, analysis) -> dict:
    """The question in the frozen-set format, its expectation from the gold and the run."""
    intent = question.gold.intent
    start = next((r for r in analysis.trail if r.state == "START"), None)
    reason = start.detail.get("reason") if start is not None else None
    tools: list[str] = []
    for record in records:
        for call in record.target.get("tool_calls", []):
            if call["function"]["name"] not in tools:
                tools.append(call["function"]["name"])
    negative = question.family in NEGATIVE_FAMILIES
    return {
        "id": question.question_id,
        "category": "TRAP" if negative else intent["scenario"],
        "lang": question.language,
        "question": question.text,
        "source": "generated",
        "trap": question.family if negative else None,
        "family": question.family,
        "today": question.today,
        "expected": {
            "scenarios": [intent["scenario"]],
            "outcomes": [metrics.outcome_class({"outcome": analysis.outcome})],
            "ticker": intent["ticker"],
            "sector": intent["sector"],
            "start": intent["start"],
            "end": intent["end"],
            "as_of": intent["as_of"],
            "reason": reason,
            "tools": tools,
        },
    }


# --- the build ------------------------------------------------------------------------------
def build(
    n_per_family: int,
    out: Path,
    *,
    seed: int = 42,
    call_tool: ToolCaller | None = None,
    today_range: tuple[str, str] = gen.TODAY_RANGE,
) -> dict:
    """Build the data files under ``out`` and return the manifest (also written there)."""
    started = time.perf_counter()
    if call_tool is None:
        from bist_harness.eval.run_eval import _server_call_tool

        call_tool = _server_call_tool
    from bist_harness.mcp_server import server

    layers_id = server.current_layers_id()
    snapshot_id = server.current_snapshot_id()
    generated = gen.generate(n_per_family, seed=seed, today_range=today_range)
    kept, overlap = gen.drop_overlaps(generated)

    records: list[TrainingRecord] = []
    runs: dict[str, tuple[gen.GenQuestion, list, object]] = {}
    teacher_errors: list[dict] = []
    test_period: list[dict] = []
    for question in kept:
        try:
            turns, analysis = _run(question, call_tool)
        except (TeacherError, ValueError) as exc:
            teacher_errors.append(_drop(question, error=type(exc).__name__, message=str(exc)))
            continue
        dates = list(dict.fromkeys(d for r in turns for d in test_period_dates(r)))
        if dates:
            test_period.append(_drop(question, reason="test_period_date", dates=dates))
            continue
        turns = _with_run_meta(turns, analysis, question, layers_id)
        runs[question.question_id] = (question, turns, analysis)
        records.extend(turns)

    splits = split_by_family(records, seed=seed)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}
    for name, split_records in splits.items():
        path = out / RECORD_FILES[name]
        digest = write_jsonl(split_records, path)
        files[RECORD_FILES[name]] = _file_entry(path, digest, len(split_records))
    test_ids = list(dict.fromkeys(r.question_id for r in splits["test"]))
    dev = [_dev_question(*runs[qid]) for qid in test_ids]
    path = out / DEV_QUESTIONS
    digest = _write_lines(dev, path)
    files[DEV_QUESTIONS] = _file_entry(path, digest, len(dev))

    manifest = {
        "seed": seed,
        "n_per_family": n_per_family,
        "today_range": list(today_range),
        "snapshot_id": snapshot_id,
        "layers_id": layers_id,
        "git_commit": _git_commit(),
        "families": len(gen.FAMILIES),
        "questions": {
            "generated": len(generated),
            "kept": len(runs),
            "by_split": {name: len({r.question_id for r in rs}) for name, rs in splits.items()},
        },
        "records": {name: len(rs) for name, rs in splits.items()},
        "dropped": {"overlap": overlap, "test_period_date": test_period},
        "teacher_errors": teacher_errors,
        "dropped_counts": {
            "overlap": len(overlap),
            "test_period_date": len(test_period),
            "teacher_errors": len(teacher_errors),
        },
        "counts": _counts(splits),
        "coverage": _coverage(records),
        "files": files,
        "wall_time_s": round(time.perf_counter() - started, 1),
    }
    with (out / MANIFEST).open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return manifest


def _drop(question: gen.GenQuestion, **detail) -> dict:
    return {"question_id": question.question_id, "family": question.family, **detail}


def _write_lines(rows: list[dict], path: Path) -> str:
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_entry(path: Path, digest: str, count: int) -> dict:
    return {"sha256": digest, "records": count, "bytes": path.stat().st_size}


def _git_commit() -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return done.stdout.strip() or "unknown"


def _label(record: TrainingRecord) -> str:
    return str(record.meta.get("outcome"))


def _counts(splits: dict[str, list]) -> dict:
    """Record counts by split x turn x scenario x label x language x family, and margins."""
    cells: Counter = Counter()
    margins: dict[str, Counter] = {}
    for name, records in splits.items():
        for r in records:
            key = (name, r.turn, r.scenario, _label(r), r.language, r.family)
            cells["|".join(key)] += 1
            for axis, value in (
                ("turn", r.turn),
                ("scenario", r.scenario),
                ("label", _label(r)),
                ("language", r.language),
                ("family", r.family),
            ):
                margins.setdefault(f"{name}|{axis}", Counter())[value] += 1
    counts: dict = {"key": "split|turn|scenario|label|language|family", "cells": dict(cells)}
    for axis in ("turn", "scenario", "label", "language", "family"):
        counts[f"by_split_{axis}"] = {
            name: dict(margins.get(f"{name}|{axis}", Counter())) for name in splits
        }
    return counts


def _coverage(records: list[TrainingRecord]) -> dict:
    """Records per mandatory scenario x label (zeros kept), empty cells, negative families."""
    cells = Counter((r.scenario, _label(r)) for r in records)
    table = {s: {a: cells[s, a] for a in ACTIONS} for s in COVERAGE_SCENARIOS}
    families = Counter(r.family for r in records)
    return {
        "scenario_label": table,
        "empty_cells": [f"{s}/{a}" for s in COVERAGE_SCENARIOS for a in ACTIONS if not cells[s, a]],
        "negative_families": {f: families[f] for f in NEGATIVE_FAMILIES},
    }


# --- command line ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the fine-tuning data set.")
    parser.add_argument("--n-per-family", type=int, default=30, help="questions per family")
    parser.add_argument("--out", type=Path, default=Path("data") / "finetune")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    manifest = build(args.n_per_family, args.out, seed=args.seed)
    q = manifest["questions"]
    print(
        f"[build] {q['generated']} questions generated, {q['kept']} kept; "
        f"dropped {json.dumps(manifest['dropped_counts'], sort_keys=True)}",
        flush=True,
    )
    print(f"[build] records {json.dumps(manifest['records'])}", flush=True)
    print(f"[build] empty coverage cells: {len(manifest['coverage']['empty_cells'])}", flush=True)
    print(f"[build] {manifest['wall_time_s']} s, written to {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
