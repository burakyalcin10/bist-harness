"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

Thin end-to-end slice (Sprint 1): a question goes to the local model, the model calls
tools over MCP, and every number and date in the final answer is checked against the
tool outputs. This is a spike that proves the pieces connect; the stateful harness of
Sprint 4 replaces the free tool loop used here.

Usage:
    uv run python -m bist_harness.slice.run_slice "ASELS'te ... 5 günlük getiri nasıl?"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import TextIO

from mcp import Client, StdioServerParameters

from bist_harness.config import Settings
from bist_harness.eval.number_check import (
    find_unsupported_dates,
    find_unsupported_numbers,
    question_numbers,
)
from bist_harness.llm.client import OllamaClient
from bist_harness.mcp_server.server import unwrap_tool_result
from bist_harness.tools.schemas import to_ollama_tools, validate_tool_call
from bist_harness.universe import load_universe

NUM_CTX = 8192

_SYSTEM = """You are the analysis assistant of an educational BIST 100 research system.
You never calculate, estimate or guess numbers yourself. To answer a data question, call one of the provided tools.
After a tool returns, answer in the language of the question, in at most four sentences.
Use only numbers that appear in the tool output and copy them exactly: same digits, no rounding, no conversion.
Write dates exactly as they appear in the tool output, as YYYY-MM-DD.
If the tool output has a sample_warning or a coverage_warning, mention it. If it has an error, explain the error and do not guess.
Never give investment advice or price predictions; if asked, say the system is educational and cannot give advice.
Tickers are written without the ".IS" suffix. Dates are YYYY-MM-DD. Today is {today}.
Study universe: {tickers}"""


def system_prompt() -> str:
    return _SYSTEM.format(
        today=date.today().isoformat(), tickers=", ".join(load_universe()["ticker"])
    )


def _stdio_server() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable, args=["-m", "bist_harness.mcp_server.server"]
    )


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


async def _run(question: str, client, max_turns: int, server) -> dict:
    tool_calls: list[dict] = []
    tool_outputs: list[dict] = []
    answer = ""
    malformed = False

    async with Client(server if server is not None else _stdio_server()) as mcp:
        allowed = [tool.name for tool in (await mcp.list_tools()).tools]
        tools = to_ollama_tools(allowed)
        messages = [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": question},
        ]
        for _ in range(max_turns):
            result = await asyncio.to_thread(client.chat, messages, tools=tools, num_ctx=NUM_CTX)
            if not result.tool_calls:
                # A broken tool-call attempt is neither an answer nor a call.
                malformed = bool(getattr(result, "malformed_tool_call", False))
                answer = "" if malformed else result.content.strip()
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": result.content,
                    "tool_calls": [
                        {"function": {"name": c.name, "arguments": c.arguments}}
                        for c in result.tool_calls
                    ],
                }
            )
            for call in result.tool_calls:
                tool_calls.append({"name": call.name, "arguments": call.arguments})
                problem = validate_tool_call(call.name, call.arguments)
                if call.name not in allowed:
                    output = _error(
                        "TOOL_NOT_ALLOWED", f"{call.name} is not available in this step."
                    )
                elif problem:
                    # Checked against the schema before the tool runs, so an extra or
                    # wrongly typed argument is reported instead of silently ignored.
                    output = _error("INVALID_ARGUMENT", problem)
                else:
                    output = unwrap_tool_result(await mcp.call_tool(call.name, call.arguments))
                tool_outputs.append(output)
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": call.name,
                        "content": json.dumps(output, ensure_ascii=False),
                    }
                )

    # Only numbers the user wrote are exempt. Tool arguments are chosen by the model and
    # are not evidence: a successful tool echoes its arguments in its own output anyway.
    unsupported: list[float] = []
    unsupported_dates: list[str] = []
    if answer:
        unsupported = find_unsupported_numbers(
            answer, tool_outputs, allowed=question_numbers(question)
        )
        unsupported_dates = find_unsupported_dates(answer, tool_outputs, question)
    if malformed:
        verdict = "INVALID_TOOL_CALL"
    elif not answer:
        verdict = "NO_ANSWER"
    else:
        verdict = "UNSUPPORTED_NUMBERS" if (unsupported or unsupported_dates) else "NUMBERS_OK"
    return {
        "question": question,
        "model": getattr(client, "model", None),
        "tool_calls": tool_calls,
        "tool_outputs": tool_outputs,
        "answer": answer,
        "unsupported_numbers": unsupported,
        "unsupported_dates": unsupported_dates,
        "verdict": verdict,
    }


def run_slice(question: str, client, *, max_turns: int = 4, server=None) -> dict:
    """Answer one question end to end.

    ``server`` is an in-process MCP server (tests); by default the MCP server is started
    as a subprocess and reached over stdio, exactly as an external MCP client would.
    """
    return asyncio.run(_run(question, client, max_turns, server))


def safe_print(text: str, *, stream: TextIO | None = None) -> None:
    """Print text that may contain characters the console encoding cannot show."""
    stream = stream or sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    stream.write(text.encode(encoding, errors="replace").decode(encoding) + "\n")


def report(out: dict, *, runs_dir: Path | None = None) -> Path:
    """Write the run log, then print the summary. The log comes first so that a console
    problem can never lose the record of a run."""
    runs = runs_dir or Path("runs")
    runs.mkdir(parents=True, exist_ok=True)
    log = runs / f"slice-{datetime.now():%Y%m%d-%H%M%S}.json"
    log.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    safe_print(f"QUESTION : {out['question']}")
    safe_print(f"MODEL    : {out['model']}")
    for call, output in zip(out["tool_calls"], out["tool_outputs"], strict=True):
        safe_print(f"TOOL CALL: {call['name']} {json.dumps(call['arguments'], ensure_ascii=False)}")
        safe_print(f"TOOL OUT : {json.dumps(output, ensure_ascii=False)}")
    safe_print(f"ANSWER   : {out['answer']}")
    flagged = [*out["unsupported_numbers"], *out["unsupported_dates"]]
    safe_print(f"VERDICT  : {out['verdict']} {flagged or ''}")
    safe_print(f"LOG      : {log}")
    return log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--model", help="override BIST_LLM_MODEL")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    client = OllamaClient(
        settings.llm_base_url,
        args.model or settings.llm_model,
        timeout_s=args.timeout,
        api=settings.llm_api,
    )
    report(run_slice(args.question, client))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
