"""QLoRA training: settings files, chat examples, the missing train group and the bundle.

None of these tests needs the ``train`` dependency group, a GPU or the real data folder:
the tokenizer is a fake with the two methods ``to_chat_examples`` uses, and the bundle is
built from synthetic files in a temp folder.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from bist_harness.finetune import train as ft
from bist_harness.finetune.record import TrainingRecord, write_jsonl

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "configs" / "qlora"
FIELDS = [f.name for f in dataclasses.fields(ft.TrainConfig)]


# --- settings files -------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name",
    ["r16-e2.toml", "r32-e3.toml", "trial-9b.toml", "laptop-trial.toml", "laptop-trial-lean.toml"],
)
def test_config_files_load_and_record_every_setting(name):
    path = CONFIGS / name
    written = tomllib.loads(path.read_text(encoding="utf-8"))
    # every setting is written in the file: nothing is left to a code default
    assert sorted(written) == sorted(FIELDS)
    config = ft.load_config(path)
    settings = ft.config_settings(config)
    assert sorted(settings) == sorted(FIELDS)
    assert settings["target_modules"] == list(config.target_modules)
    assert config.seed == 42
    assert config.load_in_4bit is True
    json.dumps(settings)  # run.json can hold it as it is


def test_the_two_desktop_configs_differ_in_rank_and_epochs():
    r16 = ft.load_config(CONFIGS / "r16-e2.toml")
    r32 = ft.load_config(CONFIGS / "r32-e3.toml")
    assert (r16.rank, r16.epochs, r32.rank, r32.epochs) == (16, 2, 32, 3)
    assert (r16.max_steps, r16.train_limit, r16.val_limit) == (0, 0, 0)
    same = {"rank", "alpha", "epochs", "learning_rate"}
    assert {k: v for k, v in dataclasses.asdict(r16).items() if k not in same} == {
        k: v for k, v in dataclasses.asdict(r32).items() if k not in same
    }


def test_the_desktop_configs_train_qwen35_9b_at_a_pinned_commit_on_the_lean_path():
    for name in ("r16-e2.toml", "r32-e3.toml", "trial-9b.toml"):
        config = ft.load_config(CONFIGS / name)
        assert config.base_model == "Qwen/Qwen3.5-9B"
        assert re.fullmatch(r"[0-9a-f]{40}", config.revision)  # a full commit, not a branch
        assert config.lean_memory and config.target_only_logits and config.logits_chunk > 0
        # every linear layer kind of the 9B's language model (Gated DeltaNet, full
        # attention, MLP); the names are the checkpoint's (docs/results, section 9)
        assert config.target_modules == (
            "q_proj", "k_proj", "v_proj", "o_proj", "in_proj_qkv", "in_proj_z", "out_proj",
            "gate_proj", "up_proj", "down_proj",
        )  # fmt: skip


def test_the_9b_trial_is_the_heaviest_real_run_on_the_longest_records():
    """A pass must mean the real runs fit: same memory settings as r32, longest turns."""
    trial = ft.load_config(CONFIGS / "trial-9b.toml")
    r16 = ft.load_config(CONFIGS / "r16-e2.toml")
    r32 = ft.load_config(CONFIGS / "r32-e3.toml")
    assert trial.rank == max(r16.rank, r32.rank) == 32
    memory = (
        "base_model", "revision", "rank", "alpha", "target_modules", "batch_size",
        "max_seq_len", "load_in_4bit", "gradient_checkpointing", "lean_memory",
        "target_only_logits", "logits_chunk", "grad_accum",
    )  # fmt: skip
    for name in memory:
        assert getattr(trial, name) == getattr(r32, name), name
    assert max(r16.max_seq_len, r32.max_seq_len) == trial.max_seq_len
    assert (trial.max_steps, trial.sample) == (20, "longest")
    assert trial.train_limit > 0 and trial.val_limit > 0


def test_the_laptop_lean_trial_differs_from_the_task_8_trial_only_in_memory_settings():
    old = dataclasses.asdict(ft.load_config(CONFIGS / "laptop-trial.toml"))
    lean = dataclasses.asdict(ft.load_config(CONFIGS / "laptop-trial-lean.toml"))
    changed = {k for k in old if old[k] != lean[k]}
    assert changed == {"lean_memory", "target_only_logits", "logits_chunk"}
    assert (old["lean_memory"], old["target_only_logits"], old["logits_chunk"]) == (False, False, 0)


def test_logits_chunk_needs_target_only_logits(tmp_path):
    text = (CONFIGS / "r16-e2.toml").read_text(encoding="utf-8")
    bad = tmp_path / "bad.toml"
    bad.write_text(
        text.replace("target_only_logits = true", "target_only_logits = false"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="logits_chunk"):
        ft.load_config(bad)
    negative = tmp_path / "negative.toml"
    negative.write_text(text.replace("logits_chunk = 128", "logits_chunk = -1"), encoding="utf-8")
    with pytest.raises(ValueError, match="logits_chunk"):
        ft.load_config(negative)


def test_length_summary_separates_the_trained_splits_from_test():
    """A memory trial compares with train + val: the test split never trains."""

    def rows(*lengths):
        return [{"input_ids": [0] * n} for n in lengths]

    summary = ft.length_summary({"train": rows(5, 9), "val": rows(7), "test": rows(12)})
    assert summary == {"max_example_tokens": 12, "max_train_val_tokens": 9}
    assert ft.length_summary({"train": rows(3), "val": [], "test": []}) == {
        "max_example_tokens": 3,
        "max_train_val_tokens": 3,
    }


def test_config_rejects_unknown_and_missing_settings(tmp_path):
    text = (CONFIGS / "r16-e2.toml").read_text(encoding="utf-8")
    unknown = tmp_path / "unknown.toml"
    unknown.write_text(text + "\nlearnin_rate = 1e-4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="learnin_rate"):
        ft.load_config(unknown)
    missing = tmp_path / "missing.toml"
    missing.write_text(
        "\n".join(line for line in text.splitlines() if not line.startswith("rank")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="rank"):
        ft.load_config(missing)


def test_config_sample_must_be_seeded_or_longest(tmp_path):
    text = (CONFIGS / "r16-e2.toml").read_text(encoding="utf-8")
    assert ft.load_config(CONFIGS / "r16-e2.toml").sample == "seeded"
    bad = tmp_path / "bad.toml"
    bad.write_text(text.replace('sample = "seeded"', 'sample = "shortest"'), encoding="utf-8")
    with pytest.raises(ValueError, match="sample"):
        ft.load_config(bad)


def test_longest_sample_keeps_the_longest_examples_in_data_order():
    """A memory trial must meet the data set's longest turns, not a random few."""
    rows = [{"record_id": f"r{i}", "input_ids": [0] * n} for i, n in enumerate([5, 9, 2, 9, 7])]
    assert [r["record_id"] for r in ft.longest_examples(rows, 3)] == ["r1", "r3", "r4"]
    assert ft.longest_examples(rows, 0) == rows  # 0: every example
    assert ft.longest_examples(rows, 10) == rows


# --- chat examples --------------------------------------------------------------------------
class FakeTokenizer:
    """One token per character; the chat template is a short ChatML stand-in.

    It records the tool schemas it was given, so the test can see what the template saw.
    """

    def __init__(self):
        self.seen_tools = []

    def apply_chat_template(
        self, messages, tools=None, add_generation_prompt=False, tokenize=False, **kwargs
    ):
        assert tokenize is False
        self.seen_tools.append(tools)
        text = ""
        if tools:
            text += "<tools>" + "\n".join(json.dumps(t) for t in tools) + "</tools>"
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        for i, message in enumerate(messages):
            text += f"<|{message['role']}|>"
            if message["role"] == "assistant" and i > last_user:
                text += "<think></think>"
            text += message.get("content") or ""
            for call in message.get("tool_calls") or []:
                text += "<call>" + json.dumps(call["function"]) + "</call>"
            text += "<|end|>"
        if add_generation_prompt:
            text += "<|assistant|><think></think>"
        return text

    def __call__(self, text, add_special_tokens=True):
        assert add_special_tokens is False
        return {"input_ids": [ord(c) for c in text]}


TOOL = {
    "type": "function",
    "function": {
        "name": "get_stock_history",
        "description": "Daily summary.",
        "parameters": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "BIST ticker."}},
            "required": ["ticker"],
            "additionalProperties": False,
        },
    },
}


def record(turn: str, target: dict, tools=()) -> TrainingRecord:
    return TrainingRecord(
        record_id=f"q-0001-{turn}",
        question_id="q-0001",
        family="price_summary",
        language="en",
        scenario="PRICE_SUMMARY",
        turn=turn,
        state="FETCH" if turn == "tool_call" else None,
        messages=[
            {"role": "system", "content": "You are the harness."},
            {"role": "user", "content": "How did THYAO do?"},
        ],
        tools=list(tools),
        target=target,
        meta={},
    )


def decode(ids):
    return "".join(chr(i) for i in ids)


def test_chat_examples_mask_everything_but_target():
    tokenizer = FakeTokenizer()
    call = {
        "type": "function",
        "function": {"name": "get_stock_history", "arguments": {"ticker": "THYAO"}},
    }
    records = [
        record("intent", {"role": "assistant", "content": '{"scenario": "PRICE_SUMMARY"}'}),
        record("tool_call", {"role": "assistant", "tool_calls": [call]}, tools=[TOOL]),
    ]
    examples = ft.to_chat_examples(records, tokenizer)
    assert [e["record_id"] for e in examples] == ["q-0001-intent", "q-0001-tool_call"]
    for example, rec in zip(examples, records, strict=True):
        ids, labels = example["input_ids"], example["labels"]
        assert len(ids) == len(labels) == len(example["attention_mask"])
        prompt = tokenizer.apply_chat_template(
            rec.messages, tools=ft.ollama_tools(rec.tools) or None, add_generation_prompt=True
        )
        # every prompt token is masked; every target token is learned, unchanged
        assert labels[: len(prompt)] == [-100] * len(prompt)
        assert labels[len(prompt) :] == ids[len(prompt) :]
        assert decode(ids[: len(prompt)]) == prompt
        assert example["prompt_tokens"] == len(prompt)
    assert decode(examples[0]["input_ids"][examples[0]["prompt_tokens"] :]) == (
        '{"scenario": "PRICE_SUMMARY"}<|end|>'
    )
    learned = decode(examples[1]["input_ids"][examples[1]["prompt_tokens"] :])
    assert learned.startswith("<call>") and "THYAO" in learned and learned.endswith("<|end|>")
    # the template saw the tool schema as Ollama shows it, not the harness's raw schema
    assert tokenizer.seen_tools[-1] == ft.ollama_tools([TOOL])
    assert "additionalProperties" not in json.dumps(tokenizer.seen_tools[-1])


def test_a_template_that_changes_the_prompt_is_refused():
    class Shifting(FakeTokenizer):
        def apply_chat_template(self, messages, tools=None, add_generation_prompt=False, **kw):
            text = super().apply_chat_template(messages, tools, add_generation_prompt, **kw)
            return text if add_generation_prompt else "X" + text

    target = {"role": "assistant", "content": "ok"}
    with pytest.raises(ValueError, match="q-0001-intent"):
        ft.to_chat_examples([record("intent", target)], Shifting())


def test_ollama_tools_match_ollamas_go_marshal():
    """Ollama re-marshals each tool through its Go structs (api.Tool, v0.40.16) before the
    qwen3.5 renderer writes it: fields in struct order, unknown fields dropped, ``items``
    as a Go map (sorted keys), single types as a string."""
    tool = {
        "type": "function",
        "function": {
            "name": "calculate_indicators",
            "description": "Indicators.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"description": "Ticker.", "type": "string", "pattern": "^[A-Z]+$"},
                    "indicators": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["RSI", "MACD"]},
                        "description": "Which.",
                    },
                    "days": {"type": ["integer"], "default": 5},
                },
                "required": ["ticker"],
                "additionalProperties": False,
            },
        },
    }
    shown = ft.ollama_tools([tool])
    assert json.dumps(shown) == (
        '[{"type": "function", "function": {"name": "calculate_indicators", '
        '"description": "Indicators.", "parameters": {"type": "object", '
        '"required": ["ticker"], "properties": {'
        '"ticker": {"type": "string", "description": "Ticker."}, '
        '"indicators": {"type": "array", "items": {"enum": ["RSI", "MACD"], "type": "string"}, '
        '"description": "Which."}, '
        '"days": {"type": "integer"}}}}}]'
    )
    with pytest.raises(ValueError, match="escape"):
        ft.ollama_tools([{**tool, "function": {**tool["function"], "description": "a < b"}}])


# --- the train group ------------------------------------------------------------------------
def test_train_without_group_fails_clearly(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "torch", None)  # import torch now raises ImportError
    config = ft.load_config(CONFIGS / "laptop-trial.toml")
    with pytest.raises(ft.TrainGroupMissingError, match="uv sync --group train"):
        ft.train(config, tmp_path / "no-data", tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_a_placeholder_base_model_is_refused(tmp_path):
    config = dataclasses.replace(
        ft.load_config(CONFIGS / "r16-e2.toml"), base_model=ft.BASE_MODEL_PLACEHOLDER
    )
    with pytest.raises(ValueError, match="Task 7"):
        ft.train(config, tmp_path / "no-data", tmp_path / "out")


def test_importing_the_scripts_loads_no_training_library():
    code = (
        "import sys, bist_harness.finetune.train, bist_harness.finetune.export,"
        " bist_harness.finetune.memory;"
        "print(sorted(m for m in ('torch','transformers','peft','bitsandbytes','accelerate')"
        " if m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == "[]"


TRAINING_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(torch|transformers|peft|bitsandbytes|accelerate|trl)\b", re.M
)


def test_the_harness_never_imports_training_libraries():
    allowed = {"train.py", "export.py", "template_check.py"}
    src = REPO_ROOT / "src" / "bist_harness"
    offenders = [
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if TRAINING_IMPORT.search(path.read_text(encoding="utf-8"))
        and not (path.parent.name == "finetune" and path.name in allowed)
    ]
    assert offenders == []
    # and the fine-tuning scripts import them only inside functions
    for name in allowed:
        text = (src / "finetune" / name).read_text(encoding="utf-8")
        top_level = re.findall(r"^(?:import|from)\s+(\w+)", text, re.M)
        assert not {"torch", "transformers", "peft", "bitsandbytes"} & set(top_level)


# --- the bundle for the desktop -------------------------------------------------------------
def synthetic_data(root: Path) -> Path:
    data = root / "finetune"
    data.mkdir(parents=True)
    files = {}
    for split in ("train", "val", "test"):
        target = {"role": "assistant", "content": f"{split} answer"}
        digest = write_jsonl([record("intent", target)], data / f"{split}.jsonl")
        files[f"{split}.jsonl"] = {"records": 1, "sha256": digest}
    dev = '{"id": "q-0001", "question": "How did THYAO do?"}\n'
    (data / "dev_questions.jsonl").write_text(dev, encoding="utf-8", newline="\n")
    files["dev_questions.jsonl"] = {
        "records": 1,
        "sha256": hashlib.sha256(dev.encode("utf-8")).hexdigest(),
    }
    manifest = {"files": files, "seed": 42, "snapshot_id": "test-snapshot"}
    (data / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    (data / "review-sample.md").write_text("not shipped", encoding="utf-8")
    return data


def test_bundle_packs_data_configs_manifest_and_readme(tmp_path):
    data = synthetic_data(tmp_path)
    out = tmp_path / "runs" / "finetune-bundle-test.zip"
    configs = [CONFIGS / "r16-e2.toml", CONFIGS / "r32-e3.toml"]
    info = ft.bundle(data, configs, out)
    with zipfile.ZipFile(out) as archive:
        names = sorted(archive.namelist())
        listed = json.loads(archive.read("BUNDLE.json"))
        readme = archive.read("README.md").decode("utf-8")
        for name in names:
            if name in listed["files"]:
                content = archive.read(name)
                assert hashlib.sha256(content).hexdigest() == listed["files"][name]
    assert names == sorted(
        [
            "BUNDLE.json",
            "README.md",
            "configs/qlora/r16-e2.toml",
            "configs/qlora/r32-e3.toml",
            "data/finetune/dev_questions.jsonl",
            "data/finetune/manifest.json",
            "data/finetune/test.jsonl",
            "data/finetune/train.jsonl",
            "data/finetune/val.jsonl",
        ]
    )
    assert info["files"] == listed["files"]
    assert "uv sync --group train" in readme
    assert "bist_harness.finetune.train run" in readme and "r32-e3.toml" in readme
    # no address of any machine is written into the bundle
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b|\.ts\.net|https?://", readme)


def test_bundle_refuses_data_that_does_not_match_its_manifest(tmp_path):
    data = synthetic_data(tmp_path)
    with (data / "val.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("{}\n")
    with pytest.raises(ValueError, match="val.jsonl"):
        ft.bundle(data, [CONFIGS / "r16-e2.toml"], tmp_path / "bundle.zip")
    assert not (tmp_path / "bundle.zip").exists()
