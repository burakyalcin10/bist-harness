"""The template check: training text against the prompt Ollama renders, byte for byte.

Ollama is a ``httpx.MockTransport`` and the tokenizer a fake; no network, model or train
group is needed.
"""

from __future__ import annotations

import json

import httpx
import pytest

from bist_harness.finetune import template_check as tc
from bist_harness.finetune import train as ft

from .test_finetune_train_config import TOOL, FakeTokenizer, record

CALL = {
    "type": "function",
    "function": {"name": "get_stock_history", "arguments": {"ticker": "THYAO"}},
}


def records():
    return [
        record("intent", {"role": "assistant", "content": "{}"}),
        record("tool_call", {"role": "assistant", "tool_calls": [CALL]}, tools=[TOOL]),
    ]


def faithful(tokenizer):
    """An Ollama that renders exactly as the training does."""
    return lambda rec: ft.render_example(rec, tokenizer)[0]


def test_identical_renders_pass():
    tokenizer = FakeTokenizer()
    result = tc.check(records(), tokenizer, faithful(tokenizer))
    assert result["checked"] == 2 and result["identical"] == 2
    assert result["mismatches"] == []


def test_reordered_keys_of_equal_length_are_caught():
    """Token counts and byte lengths cannot see this; the byte comparison does."""
    tokenizer = FakeTokenizer()

    def reordering(rec):
        text = ft.render_example(rec, tokenizer)[0]
        return text.replace(
            '{"type": "string", "description": "BIST ticker."}',
            '{"description": "BIST ticker.", "type": "string"}',
        )

    result = tc.check(records(), tokenizer, reordering)
    assert result["identical"] == 1
    (miss,) = result["mismatches"]
    assert miss["record_id"] == "q-0001-tool_call"
    assert miss["training_bytes"] == miss["ollama_bytes"]  # same length, still caught
    assert miss["training"].startswith('"type": "string"')
    assert miss["ollama"].startswith('"description"')


def test_the_raw_schema_render_is_reported_beside_it():
    tokenizer = FakeTokenizer()
    result = tc.check(records(), tokenizer, faithful(tokenizer))
    # the harness's raw schema (additionalProperties, field order) is not what Ollama shows
    assert result["raw_schema_identical"] == 1


def test_ollama_prompt_asks_for_the_render_only():
    seen = []

    def answer(request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"_debug_info": {"rendered_template": "<prompt>"}})

    with httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(answer)) as h:
        rendered = tc.ollama_prompt(h, "qwen3.5:0.8b", [{"role": "user", "content": "x"}], [TOOL])
    assert rendered == "<prompt>"
    path, body = seen[0]
    assert path == "/api/chat"
    assert body["_debug_render_only"] is True and body["think"] is False
    assert body["stream"] is False and body["tools"] == [TOOL]
    assert body["model"] == "qwen3.5:0.8b"


def test_an_ollama_without_render_only_fails_clearly():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"done": True}))
    with httpx.Client(base_url="http://ollama.test", transport=transport) as h:
        with pytest.raises(RuntimeError, match="_debug_render_only"):
            tc.ollama_prompt(h, "m", [{"role": "user", "content": "x"}], [])


def test_choose_records_covers_every_turn_and_tool_set_first():
    pool = [
        record("intent", {"role": "assistant", "content": "{}"}),
        record("intent", {"role": "assistant", "content": "{}"}),
        record("tool_call", {"role": "assistant", "tool_calls": [CALL]}, tools=[TOOL]),
        record("explanation", {"role": "assistant", "content": "{}"}),
    ]
    chosen = tc.choose_records(pool, 3)
    assert [r.turn for r in chosen] == ["intent", "tool_call", "explanation"]
    assert len(tc.choose_records(pool, 10)) == 4
