"""The fine-tuning data build and its family-held-out split (Sprint 5, Task 3).

The build runs generated questions through the real harness with the teacher; the tools
run in process on the synthetic snapshot of ``tests/golden_snapshot.py``, never on the
real data folder. The generator's stock list is narrowed to the six synthetic stocks and
two study stocks the snapshot has no data for (their questions end ``INVESTIGATE``), so
the runs reach as many coverage cells as synthetic data can.
"""

from __future__ import annotations

import contextlib
import json
from collections import Counter
from pathlib import Path

import pytest

from bist_harness.data import macro as macro_data
from bist_harness.data import snapshot as snapshot_module
from bist_harness.eval import questions as frozen
from bist_harness.eval import run_eval
from bist_harness.finetune import build as fb
from bist_harness.finetune import questions as fq
from bist_harness.finetune.record import TrainingRecord, read_jsonl
from bist_harness.finetune.teacher import TeacherClient, TeacherError
from bist_harness.harness import session
from bist_harness.mcp_server import server as srv
from bist_harness.tools.schemas import ACTIONS

from .golden_snapshot import STOCKS, build_golden_snapshot

# two study stocks the synthetic snapshot holds no prices for
NO_DATA = ("BIMAS", "KCHOL")
SYNTHETIC_UNIVERSE = sorted([*STOCKS, *NO_DATA])
TODAY_RANGE = ("2023-09-01", "2024-12-31")  # the synthetic prices start on 2023-01-02
N = 8  # questions per family in the shared build
RECORD_FILES = ("train.jsonl", "val.jsonl", "test.jsonl")

# Cells of the four scenarios x eight labels the harness can reach by construction (the
# eligible labels of ``harness.actions.eligible_actions`` and the teacher's preference):
# WATCH (complete evidence), INVESTIGATE (incomplete), ANALYSIS_UNSAFE (gate), the
# scenario's own candidate label, and REJECT_SIGNAL for a calendar pattern only.
REACHABLE = {
    "SECTOR_LAGGARD": ("WATCH", "INVESTIGATE", "ANALYSIS_UNSAFE", "POTENTIAL_CATCH_UP_CANDIDATE"),
    "CALENDAR_PATTERN": ("WATCH", "INVESTIGATE", "ANALYSIS_UNSAFE", "REJECT_SIGNAL"),
    "TECHNICAL_REVERSAL": (
        "WATCH",
        "INVESTIGATE",
        "ANALYSIS_UNSAFE",
        "TECHNICAL_REVERSAL_CANDIDATE",
    ),
    "FUNDAMENTAL_REACTION": (
        "WATCH",
        "INVESTIGATE",
        "ANALYSIS_UNSAFE",
        "FUNDAMENTAL_IMPROVEMENT_CANDIDATE",
    ),
}
# Reachable cells the synthetic snapshot cannot fill, each with its reason. The real-data
# manifest is the authority on these (docs/finetune.md, "Kapsama"). An entry here must
# stay empty: a cell that fills on synthetic data is taken off this list.
SYNTHETIC_EMPTY = {
    ("CALENDAR_PATTERN", "WATCH"): "synthetic random-walk prices show no significant weekday "
    "effect, so every complete calendar run is REJECT_SIGNAL",
    ("FUNDAMENTAL_REACTION", "WATCH"): "the synthetic fundamentals have one report before 2025 "
    "(2024 Q3), so the fundamental change is never complete before the test period",
    ("FUNDAMENTAL_REACTION", "FUNDAMENTAL_IMPROVEMENT_CANDIDATE"): "as above: no complete "
    "fundamental evidence before 2025 on synthetic data",
    ("SECTOR_LAGGARD", "POTENTIAL_CATCH_UP_CANDIDATE"): "the synthetic sector backtests are "
    "capped (few trades or below buy and hold), so the candidate is never eligible",
}
NEGATIVE_FAMILIES = (
    "advice_request",
    "prediction_request",
    "out_of_universe",
    "future_date",
    "no_tool_greeting",
    "no_tool_off_topic",
    "missing_information",
)


@contextlib.contextmanager
def synthetic(tmp: Path):
    """The synthetic snapshot behind every tool and the narrowed stock list."""
    outside = fq._outside()  # computed on the full universe, before narrowing it
    with pytest.MonkeyPatch.context() as mp:
        root = tmp / "data"
        build_golden_snapshot(root / "snapshots")
        mp.setenv("BIST_DATA_DIR", str(root))
        no_adjustments = tmp / "adjustments.csv"
        no_adjustments.write_text("ticker,effective_date,factor,reason\n", encoding="utf-8")
        mp.setattr(snapshot_module, "ADJUSTMENTS_PATH", no_adjustments)
        mp.setattr(srv, "load_macro", lambda name: macro_data.load_macro(name, cpi_releases=None))
        mp.setattr(srv, "current_snapshot_id", lambda: "test-snapshot")
        mp.setattr(srv, "current_adjustments_id", lambda: "testadj0")
        mp.setattr(srv, "current_layers_id", lambda: "testlay0")
        mp.setattr(session, "_store_path", lambda: tmp / "store.sqlite")
        mp.setattr(fq, "_universe", lambda: SYNTHETIC_UNIVERSE)
        mp.setattr(fq, "_outside", lambda: outside)
        session._LIVE.clear()
        try:
            yield
        finally:
            session._LIVE.clear()


def run_build(tmp: Path, n: int, **kwargs) -> tuple[Path, dict]:
    out = tmp / "out"
    with synthetic(tmp):
        manifest = fb.build(n, out, today_range=TODAY_RANGE, **kwargs)
    return out, manifest


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return run_build(tmp_path_factory.mktemp("ft-build"), N)


def records_of(out: Path) -> dict[str, list[TrainingRecord]]:
    return {name.split(".")[0]: read_jsonl(out / name) for name in RECORD_FILES}


# --- determinism ----------------------------------------------------------------------------
def test_build_twice_gives_identical_files(tmp_path_factory):
    a, manifest_a = run_build(tmp_path_factory.mktemp("ft-a"), 2)
    b, manifest_b = run_build(tmp_path_factory.mktemp("ft-b"), 2)
    for name in (*RECORD_FILES, "dev_questions.jsonl"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
        assert manifest_a["files"][name]["sha256"] == manifest_b["files"][name]["sha256"]
    stable_a = {k: v for k, v in manifest_a.items() if k != "wall_time_s"}
    stable_b = {k: v for k, v in manifest_b.items() if k != "wall_time_s"}
    assert stable_a == stable_b
    assert manifest_a["seed"] == 42 and manifest_a["n_per_family"] == 2
    on_disk = json.loads((a / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest_a
    assert b"\r\n" not in (a / "train.jsonl").read_bytes()


# --- the split ------------------------------------------------------------------------------
def fake_records() -> list[TrainingRecord]:
    """One question per family, language and paraphrase, two turns each."""
    out = []
    for family in fq.FAMILIES.values():
        for language in fq.LANGS:
            for index, template in enumerate(family.templates[language]):
                qid = f"{family.name}-{language}-{index:02d}"
                for turn in range(2):
                    out.append(
                        TrainingRecord(
                            record_id=f"{qid}-{turn:02d}",
                            question_id=qid,
                            family=family.name,
                            language=language,
                            scenario=family.scenario or "PRICE_SUMMARY",
                            turn="intent",
                            state=None,
                            messages=[],
                            tools=[],
                            target={"role": "assistant", "content": "{}"},
                            meta={"template": template},
                        )
                    )
    return out


def templates_by(split_records) -> dict[tuple[str, str], set[str]]:
    found: dict[tuple[str, str], set[str]] = {}
    for record in split_records:
        found.setdefault((record.family, record.language), set()).add(record.meta["template"])
    return found


def test_split_holds_out_template_families(built):
    splits = fb.split_by_family(fake_records())
    assert set(splits) == {"train", "val", "test"}
    by_split = {name: templates_by(records) for name, records in splits.items()}
    for family in fq.FAMILIES.values():
        for language in fq.LANGS:
            key = (family.name, language)
            train = by_split["train"].get(key, set())
            assert train, key  # training keeps some of every family's paraphrases
            if len(family.templates[language]) >= fb.MIN_PARAPHRASES:
                assert by_split["val"].get(key, set()) - train, key
                assert by_split["test"].get(key, set()) - train, key
    # a paraphrase shared by several families is held out of training for all of them
    seen = {name: {r.meta["template"] for r in records} for name, records in splits.items()}
    assert not seen["train"] & (seen["val"] | seen["test"])
    assert not seen["val"] & seen["test"]
    # deterministic with the seed
    again = fb.split_by_family(fake_records())
    assert {k: [r.record_id for r in v] for k, v in again.items()} == {
        k: [r.record_id for r in v] for k, v in splits.items()
    }
    other = fb.split_by_family(fake_records(), seed=7)
    assert [r.record_id for r in other["val"]] != [r.record_id for r in splits["val"]]

    # the built files: a question's turns stay in one split; paraphrases never cross
    out, _ = built
    files = records_of(out)
    where: dict[str, set[str]] = {}
    for name, records in files.items():
        for record in records:
            where.setdefault(record.question_id, set()).add(name)
    assert all(len(names) == 1 for names in where.values())
    seen = {name: {r.meta["template"] for r in records} for name, records in files.items()}
    assert seen["val"] and seen["test"]
    assert not seen["train"] & (seen["val"] | seen["test"])
    # every family with records outside training has a paraphrase training never saw
    held = templates_by([*files["val"], *files["test"]])
    train = templates_by(files["train"])
    families = {family for family, _ in held}
    for family in families:
        unseen = set().union(*(held[k] - train.get(k, set()) for k in held if k[0] == family))
        assert unseen, family


# --- manifest and coverage ------------------------------------------------------------------
def test_manifest_counts_match_files(built):
    out, manifest = built
    files = records_of(out)
    cells: Counter = Counter()
    for name, records in files.items():
        for r in records:
            key = (name, r.turn, r.scenario, r.meta["outcome"], r.language, r.family)
            cells["|".join(key)] += 1
    assert manifest["counts"]["cells"] == dict(cells)
    for name, records in files.items():
        assert manifest["records"][name] == len(records)
        turns = Counter(r.turn for r in records)
        assert manifest["counts"]["by_split_turn"][name] == dict(turns)
        assert manifest["files"][f"{name}.jsonl"]["records"] == len(records)
    for name, entry in manifest["files"].items():
        import hashlib

        data = (out / name).read_bytes()
        assert entry["sha256"] == hashlib.sha256(data).hexdigest(), name
        assert entry["bytes"] == len(data)
    questions = {name: len({r.question_id for r in records}) for name, records in files.items()}
    assert manifest["questions"]["by_split"] == questions
    generated = manifest["questions"]["generated"]
    dropped = sum(manifest["dropped_counts"].values())
    assert generated == len(fq.FAMILIES) * N
    assert generated - dropped == sum(questions.values())
    for key in ("snapshot_id", "layers_id", "git_commit", "seed", "n_per_family", "wall_time_s"):
        assert key in manifest
    assert manifest["snapshot_id"] == "test-snapshot" and manifest["layers_id"] == "testlay0"


def test_coverage_has_no_empty_cell(built):
    out, manifest = built
    records = [r for rs in records_of(out).values() for r in rs]
    cells = Counter((r.scenario, r.meta["outcome"]) for r in records)
    assert all(scenario in REACHABLE for scenario, _ in SYNTHETIC_EMPTY)
    assert all(label in REACHABLE[s] for s, label in SYNTHETIC_EMPTY)
    assert all(reason.strip() for reason in SYNTHETIC_EMPTY.values())
    for scenario, labels in REACHABLE.items():
        for label in labels:
            if (scenario, label) in SYNTHETIC_EMPTY:
                assert cells[scenario, label] == 0, (
                    f"{scenario}/{label} fills: drop it from the list"
                )
            else:
                assert cells[scenario, label] > 0, f"{scenario}/{label} is empty"
    families = Counter(r.family for r in records)
    for family in NEGATIVE_FAMILIES:
        assert families[family] > 0, family
    # the explicit HOLD families reach HOLD; the manifest lists the empty cells it sees
    assert cells["PRICE_SUMMARY", "HOLD"] > 0 and cells["MACRO_CONTEXT", "HOLD"] > 0
    table = manifest["coverage"]["scenario_label"]
    assert set(table) == set(REACHABLE)
    assert all(set(row) == set(ACTIONS) for row in table.values())
    empty = {tuple(cell.split("/")) for cell in manifest["coverage"]["empty_cells"]}
    assert empty == {(s, a) for s in REACHABLE for a in ACTIONS if cells[s, a] == 0}


def test_run_level_meta_is_added_to_every_record(built):
    out, _ = built
    by_question: dict[str, list[TrainingRecord]] = {}
    for records in records_of(out).values():
        for r in records:
            by_question.setdefault(r.question_id, []).append(r)
    run_keys = ("outcome", "snapshot_id", "layers_id", "today", "template")
    for qid, records in by_question.items():
        runs = {json.dumps([r.meta[k] for k in run_keys]) for r in records}
        assert len(runs) == 1, qid  # one run, the same run-level meta on every turn
        first = records[0].meta
        assert first["snapshot_id"] == "test-snapshot" and first["layers_id"] == "testlay0"
        assert first["today"] < fb.CUTOFF
        assert first["template"] in fq.FAMILIES[records[0].family].templates[records[0].language]
        for r in records:  # the teacher's turn-level meta is kept
            if r.turn == "tool_call":
                assert r.meta["state"] == r.state
            if r.turn == "explanation":
                assert r.meta["action"] in r.meta["eligible"]
                assert r.meta["action"] == r.meta["outcome"]


# --- what the build drops -------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("close on 2024-12-31 was 10", []),
        ("annual inflation for 2024-12 was 44%", []),
        ("2024Q4 report", []),
        ("from 2025-01-01", ["2025-01-01"]),
        ("inflation for 2025-03 was 39%", ["2025-03"]),
        ("the 2025Q1 report", ["2025Q1"]),
        ("rate 50.00% (2026-11-18)", ["2026-11-18"]),
        ("id 12025-01-011 and value 2025-13-01", []),
    ],
)
def test_test_period_dates_are_found(text, found):
    record = TrainingRecord(
        record_id="x-00",
        question_id="x",
        family="f",
        language="en",
        scenario="PRICE_SUMMARY",
        turn="explanation",
        state=None,
        messages=[{"role": "user", "content": text}],
        tools=[],
        target={"role": "assistant", "content": "{}"},
        meta={"today": "2024-12-31", "snapshot_id": "2026-11-10"},  # meta is not training text
    )
    assert fb.test_period_dates(record) == found


SHIFTED = "2025-02-03"


def shift_macro_dates(name: str, arguments: dict) -> dict:
    """The real tool, but the macro context reports its period end as a 2025 date."""
    output = getattr(srv, name)(**arguments)
    if name != "get_macro_context":
        return output
    end = arguments.get("end")
    text = json.dumps(output, ensure_ascii=False).replace(f'"{end}"', f'"{SHIFTED}"')
    return json.loads(text)


def test_a_test_period_date_in_a_tool_output_drops_the_question(tmp_path_factory):
    out, manifest = run_build(tmp_path_factory.mktemp("ft-r1"), 2, call_tool=shift_macro_dates)
    dropped = manifest["dropped"]["test_period_date"]
    families = {d["family"] for d in dropped}
    assert families and families <= {"macro_context", "macro_context_hold"}
    assert all(SHIFTED in d["dates"] for d in dropped)
    assert manifest["dropped_counts"]["test_period_date"] == len(dropped)
    kept = {r.question_id for rs in records_of(out).values() for r in rs}
    assert not kept & {d["question_id"] for d in dropped}
    for name in RECORD_FILES:
        assert SHIFTED not in (out / name).read_text(encoding="utf-8")


def test_teacher_errors_are_counted_and_the_build_goes_on(tmp_path_factory, monkeypatch):
    class Failing(TeacherClient):
        def chat(self, messages, tools=None, response_format=None, **kwargs):
            if self.family == "advice_request":
                raise TeacherError("gold action WATCH is not eligible: INVESTIGATE")
            if self.family == "no_tool_greeting":
                raise ValueError("not a model turn of the harness")
            return super().chat(messages, tools, response_format, **kwargs)

    monkeypatch.setattr(fb, "TeacherClient", Failing)
    out, manifest = run_build(tmp_path_factory.mktemp("ft-te"), 1)
    errors = manifest["teacher_errors"]
    assert {e["family"] for e in errors} == {"advice_request", "no_tool_greeting"}
    assert {e["error"] for e in errors} == {"TeacherError", "ValueError"}
    assert any("not eligible" in e["message"] for e in errors)
    assert manifest["dropped_counts"]["teacher_errors"] == len(errors) == 2
    families = {r.family for rs in records_of(out).values() for r in rs}
    assert "advice_request" not in families and "prediction_request" in families


def test_overlapping_questions_are_dropped_with_their_reason(tmp_path_factory, monkeypatch):
    pool = frozen.load_questions()
    copied = next(q for q in pool if q["lang"] == "en")["question"]
    real_generate = fq.generate

    def with_a_copy(n, **kwargs):
        qs = real_generate(n, **kwargs)
        first = qs[0]
        from dataclasses import replace

        return [replace(first, question_id="copy-0000", text=copied), *qs]

    monkeypatch.setattr(fb.gen, "generate", with_a_copy)
    _, manifest = run_build(tmp_path_factory.mktemp("ft-ov"), 1)
    overlap = manifest["dropped"]["overlap"]
    assert [d["question_id"] for d in overlap if d["reason"] == "text_overlap"] == ["copy-0000"]
    assert manifest["dropped_counts"]["overlap"] == len(overlap)


# --- the development questions for run_eval (ruling R2) -------------------------------------
def test_run_eval_loads_the_written_dev_questions(built):
    out, manifest = built
    path = out / "dev_questions.jsonl"
    questions = run_eval.load_question_set(path)
    test_ids = {r.question_id for r in records_of(out)["test"]}
    assert [q["id"] for q in questions] == sorted(test_ids, key=[q["id"] for q in questions].index)
    assert {q["id"] for q in questions} == test_ids
    assert manifest["files"]["dev_questions.jsonl"]["records"] == len(questions)
    expected_keys = {
        "scenarios",
        "outcomes",
        "ticker",
        "sector",
        "start",
        "end",
        "as_of",
        "reason",
        "tools",
    }
    intents = {r.question_id: r for r in records_of(out)["test"] if r.turn == "intent"}
    for q in questions:
        assert {"id", "question", "lang", "expected", "today"} <= set(q)
        assert set(q["expected"]) == expected_keys
        assert q["expected"]["outcomes"][0] in frozen.OUTCOMES
        assert q["today"] < fb.CUTOFF
        assert q["question"] == intents[q["id"]].messages[1]["content"]
    unsafe = [q for q in questions if q["expected"]["reason"]]
    assert all(q["expected"]["outcomes"] == ["ANALYSIS_UNSAFE"] for q in unsafe)


def test_run_eval_takes_a_questions_file(built, monkeypatch, tmp_path):
    out, _ = built
    seen = {}

    def fake_run_eval(questions, client, **kwargs):
        seen.update(questions=questions, **kwargs)
        return {"metrics": {}}

    def refuse(path=None):
        raise AssertionError("verify_frozen runs only for the frozen file")

    monkeypatch.setattr(run_eval, "run_eval", fake_run_eval)
    monkeypatch.setattr(frozen, "verify_frozen", refuse)
    path = out / "dev_questions.jsonl"
    run_eval.main(["--questions-file", str(path), "--limit", "2", "--out", str(tmp_path)])
    assert [q["id"] for q in seen["questions"]] == [
        q["id"] for q in run_eval.load_question_set(path)[:2]
    ]
    assert seen["question_set_sha256"] == frozen.file_sha256(path)


def test_the_frozen_file_is_still_verified(monkeypatch, tmp_path):
    changed = tmp_path / "questions.jsonl"
    changed.write_bytes(frozen.QUESTIONS_PATH.read_bytes() + b"\n{}")
    monkeypatch.setattr(frozen, "QUESTIONS_PATH", changed)
    with pytest.raises(ValueError, match="frozen"):
        run_eval.load_question_set()
    with pytest.raises(ValueError, match="frozen"):
        run_eval.load_question_set(changed)


def test_a_question_with_its_own_today_runs_on_that_day(monkeypatch):
    days = []

    def fake_run(question, client, *, call_tool, today, **kwargs):
        days.append(today)
        raise RuntimeError("stop")

    monkeypatch.setattr(run_eval.machine, "run_analysis", fake_run)
    question = {"id": "x", "question": "q", "lang": "en", "today": "2024-03-01", "expected": {}}
    for q in (question, {k: v for k, v in question.items() if k != "today"}):
        with pytest.raises(RuntimeError):
            run_eval.run_one("D", q, 0, object(), call_tool=lambda n, a: {}, today="2026-11-17")
    assert days == ["2024-03-01", "2026-11-17"]
