"""Task 9 tables: tuned vs control (vs the ready-made model) on the frozen questions.

Reads ``runs/finetune-comparison/<model>/eval-*/records.jsonl`` (one directory per model,
experiments D and E in each), recomputes the metrics with ``eval/metrics.py`` and prints
Markdown tables: overall per experiment, per question category, candidate-label use when
eligible, the questions where the tuned model is worse (and better) than the control, and
every record of the questions named with ``--show``.

    uv run python scripts/finetune_compare.py --tuned bist-r16-e2 --control bist-base-9b \
        --reference qwen3.5-9b-q4_K_M --show AM-03

Numbers come only from the records, recomputed with the current metrics; a run's own
``summary.json`` may predate a metric fix (K-089). A re-run of some questions goes into a
newer ``eval-*`` directory under the same model folder: its records replace the earlier ones
with the same (experiment, question, repeat).
"""

from __future__ import annotations

import argparse
import glob
import json
from collections import defaultdict
from pathlib import Path

from bist_harness.eval.metrics import (
    explanation_fallback,
    outcome_matches,
    summarize_experiment,
    unsupported_conclusion,
)

ROOT = Path("runs/finetune-comparison")


def load(root: Path, model: str) -> list[dict]:
    paths = sorted(glob.glob(str(root / model / "eval-*" / "records.jsonl")))
    if not paths:
        raise SystemExit(f"no records for {model}")
    records = []
    for path in paths:  # a later directory (a re-run) replaces the same (experiment, id, repeat)
        for line in open(path, encoding="utf-8"):
            records.append(json.loads(line))
    latest: dict[tuple, dict] = {}
    for r in records:
        latest[(r["experiment"], r["question_id"], r["repeat"])] = r
    return list(latest.values())


def explanation_step(record: dict) -> dict | None:
    for t in record["trail"]:
        if t["state"] == "GENERATE_EXPLANATION" and t.get("status") == "RAN":
            return t.get("detail") or {}
    return None


def acceptance(records: list[dict]) -> tuple[int, int]:
    by_model = sum(1 for r in records if r["answer_by"] == "model")
    fallbacks = sum(1 for r in records if explanation_fallback(r))
    return by_model, by_model + fallbacks


def pct(a: int, b: int) -> str:
    return f"{a} / {b} ({100 * a / b:.1f}%)" if b else "—"


def num(x) -> str:
    return "—" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))


def overall(models: dict[str, list[dict]], experiment: str) -> None:
    rows: dict[str, list[str]] = defaultdict(list)
    for recs in models.values():
        rs = [r for r in recs if r["experiment"] == experiment]
        if not rs:
            for name in rows or ["records / unavailable / errors"]:
                rows[name].append("—")
            continue
        s = summarize_experiment(rs)
        unavailable = sum(r.get("outcome") == "MODEL_UNAVAILABLE" for r in rs)
        errors = sum(1 for r in rs if r.get("error"))
        rows["records / unavailable / errors"].append(f"{len(rs)} / {unavailable} / {errors}")
        rows["explanation acceptance"].append(pct(*acceptance(rs)))
        rows["outcome match"].append(num(s["outcome_match_rate"]))
        rows["scenario accuracy"].append(num(s["scenario_accuracy"]))
        rows["trap handled / false refusal"].append(
            f"{num(s['trap_handling_rate'])} / {num(s['false_refusal_rate'])}"
        )
        rows["wrong tool calls (rejected / proposed)"].append(
            f"{s['rejected_calls']} / {s['proposed_calls']} ({num(s['wrong_tool_call_rate'])})"
        )
        rows["harness interventions"].append(str(s["harness_interventions"]))
        rows["unsupported numbers, shown answer"].append(
            f"{s['numbers_unsupported']} / {s['numbers_written']}"
        )
        rows["unsupported numbers, every model attempt"].append(
            f"{s['model_numbers_unsupported']} / {s['model_numbers_written']}"
        )
        rows["conclusions without evidence"].append(
            f"{s['unsupported_conclusions']} / {s['conclusions']}"
        )
        rows["evidence completeness"].append(num(s["evidence_completeness"]))
        rows["rule violations"].append(str(s["rule_violations"]["total"]))
        rows["ticker accuracy raw / grounded"].append(
            f"{num(s['ticker_accuracy_raw'])} / {num(s['ticker_accuracy_grounded'])}"
        )
        rows["invented fields"].append(str(s["invented_fields"]))
        rows["reproducible questions"].append(
            f"{s['reproducible_questions']} / {s['repeated_questions']}"
        )
        rows["latency median / mean / max (s)"].append(
            " / ".join(
                "—" if s[k] is None else f"{s[k]:.1f}"
                for k in ("latency_s_median", "latency_s_mean", "latency_s_max")
            )
        )
    print(f"\n#### Experiment {experiment}\n")
    print("| Metric | " + " | ".join(f"`{m}`" for m in models) + " |")
    print("| --- |" + " --- |" * len(models))
    for name, vals in rows.items():
        print(f"| {name} | " + " | ".join(vals) + " |")


def by_category(models: dict[str, list[dict]], categories: dict[str, str], experiment: str):
    print(
        f"\n#### Experiment {experiment} by category (outcome match; acceptance; "
        "conclusions without evidence)\n"
    )
    cats = sorted(set(categories.values()))
    print("| Category | " + " | ".join(f"`{m}`" for m in models) + " |")
    print("| --- |" + " --- |" * len(models))
    for cat in cats:
        cells = []
        for recs in models.values():
            rs = [
                r
                for r in recs
                if r["experiment"] == experiment and categories[r["question_id"]] == cat
            ]
            match = sum(outcome_matches(r) for r in rs)
            a, n = acceptance(rs)
            unc = [unsupported_conclusion(r) for r in rs]
            unc_n = sum(1 for u in unc if u is not None)
            cells.append(f"{match}/{len(rs)}; {a}/{n}; {sum(1 for u in unc if u)}/{unc_n}")
        print(f"| {cat} | " + " | ".join(cells) + " |")


def candidates(models: dict[str, list[dict]], experiment: str) -> None:
    print(f"\n#### Experiment {experiment}: candidate labels when eligible\n")
    print("| Model | records with a candidate eligible | candidate chosen |")
    print("| --- | --- | --- |")
    for model, recs in models.items():
        eligible = chosen = 0
        for r in recs:
            if r["experiment"] != experiment:
                continue
            step = explanation_step(r)
            if not step:
                continue
            if any(e.endswith("_CANDIDATE") for e in step.get("eligible") or []):
                eligible += 1
                chosen += str(step.get("action", "")).endswith("_CANDIDATE")
        print(f"| `{model}` | {eligible} | {chosen} |")


def _worse_ways(a: dict, b: dict) -> list[str]:
    """How record ``a`` is worse than record ``b`` of the same question."""
    hows = []
    if outcome_matches(b) and not outcome_matches(a):
        hows.append("outcome")
    if unsupported_conclusion(a) and unsupported_conclusion(b) is False:
        hows.append("conclusion without evidence")
    if explanation_fallback(a) and b["answer_by"] == "model":
        hows.append("explanation fell back")
    return hows


def compare(models: dict[str, list[dict]], tuned: str, control: str, experiment: str) -> None:
    def index(recs):
        return {(r["question_id"], r["repeat"]): r for r in recs if r["experiment"] == experiment}

    t, c = index(models[tuned]), index(models[control])
    for title, first, second in (("worse", t, c), ("better", c, t)):
        print(
            f"\n#### Experiment {experiment}: questions where `{tuned}` is {title} than "
            f"`{control}` (repeat 0)\n"
        )
        print("| Question | How | Tuned | Control |")
        print("| --- | --- | --- | --- |")
        for key in sorted(t):
            if key[1] != 0 or key not in c:
                continue
            hows = _worse_ways(first[key], second[key])
            if hows:
                row = [key[0], ", ".join(hows), str(t[key]["outcome"]), str(c[key]["outcome"])]
                print("| " + " | ".join(row) + " |")


def show(models: dict[str, list[dict]], ids: list[str]) -> None:
    print("\n#### Named questions, every record\n")
    print("| Question | Experiment | Repeat | " + " | ".join(f"`{m}`" for m in models) + " |")
    print("| --- | --- | --- |" + " --- |" * len(models))
    keys = sorted(
        {
            (r["question_id"], r["experiment"], r["repeat"])
            for recs in models.values()
            for r in recs
            if r["question_id"] in ids
        }
    )
    for qid, exp, rep in keys:
        cells = []
        for recs in models.values():
            match = [
                x
                for x in recs
                if (x["question_id"], x["experiment"], x["repeat"]) == (qid, exp, rep)
            ]
            if not match:
                cells.append("—")
                continue
            r = match[0]
            scenario = (r.get("intent") or {}).get("scenario")
            mark = "ok" if outcome_matches(r) else "MISS"
            cells.append(f"{r.get('outcome')} ({mark}; {scenario}; {r['answer_by']})")
        print(f"| {qid} | {exp} | {rep} | " + " | ".join(cells) + " |")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tuned", required=True)
    p.add_argument("--control", required=True)
    p.add_argument("--reference", action="append", default=[])
    p.add_argument("--questions", default="src/bist_harness/eval/questions.jsonl")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--experiments", default="D,E")
    p.add_argument("--show", action="append", default=[], help="a question id to list in full")
    args = p.parse_args()
    names = [args.tuned, args.control, *args.reference]
    for required in (args.tuned, args.control):
        if not glob.glob(str(args.root / required / "eval-*")):
            raise SystemExit(f"no records for {required} under {args.root}")
    models = {m: load(args.root, m) for m in names if glob.glob(str(args.root / m / "eval-*"))}
    categories = {
        q["id"]: q["category"] for q in map(json.loads, open(args.questions, encoding="utf-8"))
    }
    for exp in args.experiments.split(","):
        overall(models, exp)
        by_category(models, categories, exp)
        candidates(models, exp)
        compare(models, args.tuned, args.control, exp)
    if args.show:
        show(models, args.show)


if __name__ == "__main__":
    main()
