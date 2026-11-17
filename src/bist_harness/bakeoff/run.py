"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

Base-model bake-off: ask each candidate model the same 30 questions with all 15 tool
schemas available and measure whether it picks the right tool with the right arguments.
The tools are not executed here; only the model's choice is scored.

Usage:
    uv run python -m bist_harness.bakeoff.run --models qwen3.5:4b,qwen3.5:2b
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

from bist_harness.bakeoff.prompt import system_prompt
from bist_harness.bakeoff.score import (
    CaseScore,
    failed_case,
    load_cases,
    score_case,
    summarize,
)
from bist_harness.config import Settings
from bist_harness.errors import LLMUnavailableError
from bist_harness.llm.client import OllamaClient
from bist_harness.tools.schemas import to_ollama_tools

NUM_CTX = 8192


def endpoint_label(base_url: str) -> str:
    """Describe the endpoint without revealing a private address."""
    local = ("//127.0.0.1", "//localhost")
    return (
        "local Ollama on this machine"
        if any(marker in base_url for marker in local)
        else "private remote endpoint"
    )


def run_model(client: OllamaClient, cases: list[dict], *, num_ctx: int = NUM_CTX) -> dict:
    """Run every case against one model and return its result row."""
    tools = to_ollama_tools()
    system = {"role": "system", "content": system_prompt()}
    scores: list[CaseScore] = []
    details: list[dict] = []
    latencies: list[float] = []
    speeds: list[float] = []
    row = {
        "model": client.model,
        "reachable": True,
        "summary": None,
        "median_latency_s": None,
        "tokens_per_s": None,
        "notes": "",
        "details": details,
    }

    for case in cases:
        messages = [system, {"role": "user", "content": case["question"]}]
        started = time.perf_counter()
        try:
            result = client.chat(messages, tools=tools, num_ctx=num_ctx)
        except LLMUnavailableError as exc:
            if not details:  # first call failed: the model or endpoint is not usable
                row.update(reachable=False, notes=str(exc))
                return row
            details.append({"id": case["id"], "error": str(exc)})
            scores.append(failed_case(case))  # a failed request never counts as a pass
            continue
        latencies.append(time.perf_counter() - started)
        if result.eval_tokens_per_s:
            speeds.append(result.eval_tokens_per_s)
        score = score_case(case, result.tool_calls, malformed=result.malformed_tool_call)
        scores.append(score)
        details.append(
            {
                "id": case["id"],
                "tool_ok": score.tool_ok,
                "args_ok": score.args_ok,
                "no_tool_ok": score.no_tool_ok,
                "malformed": score.malformed,
                "calls": [{"name": c.name, "arguments": c.arguments} for c in result.tool_calls],
                "content": result.content[:300],
            }
        )

    errors = sum("error" in d for d in details)
    row.update(
        summary=summarize(scores),
        median_latency_s=round(statistics.median(latencies), 2) if latencies else None,
        tokens_per_s=round(statistics.median(speeds), 1) if speeds else None,
        notes=f"{errors} request(s) failed" if errors else "",
    )
    return row


def _cell(value: object) -> str:
    return "—" if value is None else str(value)


def render_markdown(rows: list[dict], *, endpoint: str, generated: str) -> str:
    lines = [
        f"Endpoint: {endpoint}. Generated: {generated}. Cases: 30 "
        "(25 tool cases, 5 no-tool cases); all 15 tool schemas offered; "
        f"temperature 0, seed 42, think off, num_ctx {NUM_CTX}.",
        "",
        "| model | reachable | tool_ok % | args_ok % | no_tool_ok % "
        "| median latency (s) | tokens/s | notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        s = row["summary"] or {}
        lines.append(
            f"| {row['model']} | {'yes' if row['reachable'] else 'no'} "
            f"| {_cell(s.get('tool_ok_pct'))} | {_cell(s.get('args_ok_pct'))} "
            f"| {_cell(s.get('no_tool_ok_pct'))} | {_cell(row['median_latency_s'])} "
            f"| {_cell(row['tokens_per_s'])} | {row['notes']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", required=True, help="comma-separated model tags")
    parser.add_argument("--out", type=Path, help="append the result table to this file")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    cases = load_cases()
    rows = []
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        print(f"[bakeoff] {model} ...", flush=True)
        client = OllamaClient(settings.llm_base_url, model, timeout_s=args.timeout)
        row = run_model(client, cases)
        rows.append(row)
        print(f"[bakeoff] {model}: {row['summary'] or row['notes']}", flush=True)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    table = render_markdown(rows, endpoint=endpoint_label(settings.llm_base_url), generated=stamp)
    print(table)

    runs = Path("runs")
    runs.mkdir(exist_ok=True)
    detail_path = runs / f"bakeoff-{datetime.now():%Y%m%d-%H%M%S}.json"
    detail_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[bakeoff] per-case details: {detail_path}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write("\n" + table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
