"""CSE-481 Engineering Economics — Educational use only. Not investment advice.

Thin end-to-end slice (Sprint 1): a question goes to the local model, the model calls
tools over MCP, and every number in the final answer is checked against the tool
outputs. This is a spike that proves the pieces connect; the stateful harness of
Sprint 4 replaces the free tool loop used here.

Usage:
    uv run python -m bist_harness.slice.run_slice "ASELS'te ... 5 günlük getiri nasıl?"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from mcp import Client, StdioServerParameters

from bist_harness.bakeoff.prompt import TODAY
from bist_harness.config import Settings
from bist_harness.eval.number_check import collect_numbers, find_unsupported_numbers
from bist_harness.llm.client import OllamaClient
from bist_harness.mcp_server.server import unwrap_tool_result
from bist_harness.tools.schemas import to_ollama_tools
from bist_harness.universe import load_universe

NUM_CTX = 8192

_SYSTEM = """You are the analysis assistant of an educational BIST 100 research system.
You never calculate, estimate or guess numbers yourself. To answer a data question, call one of the provided tools.
After a tool returns, answer in the language of the question, in at most four sentences.
Use only numbers that appear in the tool output and copy them exactly: same digits, no rounding, no conversion.
If the tool output has a sample_warning, mention it. If it has an error, explain the error and do not guess.
Never give investment advice or price predictions; if asked, say the system is educational and cannot give advice.
Tickers are written without the ".IS" suffix. Dates are YYYY-MM-DD. Today is {today}.
Study universe: {tickers}"""


def system_prompt() -> str:
    return _SYSTEM.format(today=TODAY, tickers=", ".join(load_universe()["ticker"]))


def _stdio_server() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable, args=["-m", "bist_harness.mcp_server.server"]
    )


async def _run(question: str, client, max_turns: int, server) -> dict:
    tool_calls: list[dict] = []
    tool_outputs: list[dict] = []
    answer = ""

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
                answer = result.content.strip()
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
                if call.name in allowed:
                    output = unwrap_tool_result(await mcp.call_tool(call.name, call.arguments))
                else:
                    output = {
                        "error": {
                            "code": "TOOL_NOT_ALLOWED",
                            "message": f"{call.name} is not available in this step.",
                        }
                    }
                tool_outputs.append(output)
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": call.name,
                        "content": json.dumps(output, ensure_ascii=False),
                    }
                )

    # Numbers the user wrote, and numbers the model passed as tool arguments, are not
    # inventions; everything else in the answer must come from a tool output.
    echoed = collect_numbers(question) + collect_numbers([c["arguments"] for c in tool_calls])
    unsupported = find_unsupported_numbers(answer, tool_outputs, allowed=echoed) if answer else []
    if not answer:
        verdict = "NO_ANSWER"
    else:
        verdict = "UNSUPPORTED_NUMBERS" if unsupported else "NUMBERS_OK"
    return {
        "question": question,
        "model": getattr(client, "model", None),
        "tool_calls": tool_calls,
        "tool_outputs": tool_outputs,
        "answer": answer,
        "unsupported_numbers": unsupported,
        "verdict": verdict,
    }


def run_slice(question: str, client, *, max_turns: int = 4, server=None) -> dict:
    """Answer one question end to end.

    ``server`` is an in-process MCP server (tests); by default the MCP server is started
    as a subprocess and reached over stdio, exactly as an external MCP client would.
    """
    return asyncio.run(_run(question, client, max_turns, server))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--model", help="override BIST_LLM_MODEL")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    client = OllamaClient(
        settings.llm_base_url, args.model or settings.llm_model, timeout_s=args.timeout
    )
    out = run_slice(args.question, client)

    print(f"QUESTION : {out['question']}")
    print(f"MODEL    : {out['model']}")
    for call, output in zip(out["tool_calls"], out["tool_outputs"], strict=True):
        print(f"TOOL CALL: {call['name']} {json.dumps(call['arguments'], ensure_ascii=False)}")
        print(f"TOOL OUT : {json.dumps(output, ensure_ascii=False)}")
    print(f"ANSWER   : {out['answer']}")
    print(f"VERDICT  : {out['verdict']} {out['unsupported_numbers'] or ''}")

    runs = Path("runs")
    runs.mkdir(exist_ok=True)
    log = runs / f"slice-{datetime.now():%Y%m%d-%H%M%S}.json"
    log.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"LOG      : {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
