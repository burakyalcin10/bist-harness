"""Check the training text against the prompt Ollama renders, byte for byte.

For each chosen record, the prompt of the training text (the tokenizer's chat template
with ``train.ollama_tools``, thinking off; ``train.render_example``) is compared with the
prompt the local Ollama renders for the same messages and tools. Ollama returns its
rendered prompt without running the model when a chat request carries
``"_debug_render_only": true`` (``_debug_info.rendered_template``; Ollama 0.40.16 has it).
The comparison is on the full text, so reordered keys or changed whitespace are found even
when the length stays the same. The render with the harness's raw tool schemas is counted
beside it, to show what ``ollama_tools`` changes.

Command line (needs the ``train`` group for the tokenizer and a running Ollama with the
base model; the endpoint is ``BIST_LLM_BASE_URL``, never printed)::

    uv run --group train python -m bist_harness.finetune.template_check \\
        --data data/finetune --base-model Qwen/Qwen3.5-0.8B \\
        --revision 2fc06364715b967f1860aea9cf38778875588b17 --ollama-model qwen3.5:0.8b

Exit code 0 when every record is identical, 1 otherwise; ``--out`` writes the result.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx

from bist_harness.finetune.record import TrainingRecord, read_jsonl
from bist_harness.finetune.train import RECORD_FILES, TrainGroupMissingError, render_example

CONTEXT = 60  # characters shown from the first difference on


def ollama_prompt(http: httpx.Client, model: str, messages: list, tools: list) -> str:
    """The prompt Ollama renders for a chat request, without running the model."""
    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "_debug_render_only": True,
    }
    if tools:
        payload["tools"] = tools
    try:
        response = http.post("/api/chat", json=payload)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"cannot reach Ollama ({type(exc).__name__})") from None
    if response.status_code >= 400:
        raise RuntimeError(f"Ollama returned HTTP {response.status_code}")
    rendered = (response.json().get("_debug_info") or {}).get("rendered_template")
    if not isinstance(rendered, str):
        raise RuntimeError(
            "Ollama returned no rendered prompt: this version does not support "
            "_debug_render_only; compare token ids instead"
        )
    return rendered


def choose_records(records: Sequence[TrainingRecord], n: int) -> list[TrainingRecord]:
    """The first record of every (turn, tool set), then evenly spaced others, up to ``n``."""
    first: list[int] = []
    seen: set = set()
    for i, rec in enumerate(records):
        key = (rec.turn, tuple(t["function"]["name"] for t in rec.tools))
        if key not in seen:
            seen.add(key)
            first.append(i)
    rest = [i for i in range(len(records)) if i not in set(first)]
    step = max(1, len(rest) // max(1, n - len(first))) if n > len(first) else 0
    picked = first + (rest[::step] if step else [])
    return [records[i] for i in picked[:n]]


def _first_difference(a: str, b: str) -> int | None:
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def _raw_prompt(rec: TrainingRecord, tokenizer) -> str:
    return tokenizer.apply_chat_template(
        rec.messages,
        tools=rec.tools or None,
        add_generation_prompt=True,
        tokenize=False,
        enable_thinking=False,
    )


def check(
    records: Sequence[TrainingRecord], tokenizer, render_ollama: Callable[[TrainingRecord], str]
) -> dict:
    """Compare the training prompt of each record with Ollama's, byte for byte."""
    identical = raw_identical = 0
    mismatches = []
    for rec in records:
        training = render_example(rec, tokenizer)[0]
        ollama = render_ollama(rec)
        raw_identical += _raw_prompt(rec, tokenizer) == ollama
        offset = _first_difference(training, ollama)
        if offset is None:
            identical += 1
            continue
        start = max(training.rfind(c, 0, offset) for c in "{ \n") + 1
        mismatches.append(
            {
                "record_id": rec.record_id,
                "offset": offset,
                "training_bytes": len(training.encode("utf-8")),
                "ollama_bytes": len(ollama.encode("utf-8")),
                "training": training[start : offset + CONTEXT],
                "ollama": ollama[start : offset + CONTEXT],
            }
        )
    return {
        "checked": len(records),
        "identical": identical,
        "raw_schema_identical": raw_identical,
        "mismatches": mismatches,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="training text vs Ollama's rendered prompt")
    parser.add_argument("--data", type=Path, default=Path("data/finetune"))
    parser.add_argument("--base-model", required=True, help="Hugging Face repository id")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--ollama-model", required=True, help="the base model's Ollama tag")
    parser.add_argument("--n", type=int, default=40, help="records to compare")
    parser.add_argument("--out", type=Path, help="write the result as JSON")
    args = parser.parse_args(argv)

    try:
        from transformers import AutoTokenizer
    except ImportError:
        print(
            str(TrainGroupMissingError("run `uv sync --group train` and `uv run --group train`")),
            file=sys.stderr,
        )
        return 2
    from bist_harness.config import Settings

    records: list[TrainingRecord] = []
    for name in RECORD_FILES:
        records += read_jsonl(args.data / name)
    chosen = choose_records(records, args.n)
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, revision=args.revision)
    settings = Settings.from_env()
    try:
        with httpx.Client(base_url=settings.llm_base_url, timeout=300) as http:
            result = check(
                chosen,
                tokenizer,
                lambda rec: ollama_prompt(http, args.ollama_model, rec.messages, rec.tools),
            )
    except RuntimeError as exc:
        print(f"[template-check] {exc}", file=sys.stderr)
        return 2
    result.update(
        base_model=args.base_model, revision=args.revision, ollama_model=args.ollama_model
    )
    print(
        f"[template-check] {result['identical']}/{result['checked']} identical byte for byte "
        f"(raw schemas: {result['raw_schema_identical']}/{result['checked']})",
        flush=True,
    )
    for miss in result["mismatches"]:
        print(
            f"[template-check] {miss['record_id']} differs at {miss['offset']}: "
            f"training {miss['training']!r} vs ollama {miss['ollama']!r}",
            flush=True,
        )
    if args.out:
        with args.out.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return 0 if not result["mismatches"] else 1


if __name__ == "__main__":
    sys.exit(main())
