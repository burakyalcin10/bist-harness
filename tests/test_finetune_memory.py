"""The peak-VRAM estimate: shapes from tensor names, terms, and the laptop calibration.

Pure arithmetic: no torch, no network. The model shapes below are the counts the Hub's
safetensors headers give (``memory.hub_shape``), written out so the test runs offline.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from bist_harness.finetune import memory as mem
from bist_harness.finetune import train as ft

CONFIGS = Path(__file__).resolve().parents[1] / "configs" / "qlora"


def test_shape_from_tensors_sorts_the_parameters():
    tensors = {
        "model.language_model.embed_tokens.weight": (100, 8),
        "lm_head.weight": (100, 8),
        "model.language_model.layers.0.linear_attn.in_proj_qkv.weight": (24, 8),
        "model.language_model.layers.0.linear_attn.conv1d.weight": (24, 1, 4),
        "model.language_model.layers.0.linear_attn.A_log": (2,),
        "model.language_model.layers.0.mlp.down_proj.weight": (8, 16),
        "model.language_model.norm.weight": (8,),
        "model.visual.blocks.0.attn.qkv.weight": (12, 4),
        "model.visual.pos_embed.weight": (10, 4),
        "mtp.fc.weight": (8, 16),  # not loaded by transformers
    }
    config = {"text_config": {"vocab_size": 100, "hidden_size": 8, "num_hidden_layers": 1}}
    shape = mem.shape_from_tensors(tensors, config)
    assert shape.tied is False
    assert shape.embed_params == 800
    assert shape.quantized_params == 24 * 8 + 8 * 16 + 12 * 4
    assert shape.vector_params == 2 + 8
    assert shape.other_params == 24 * 4 + 10 * 4
    # LoRA only on the language model's layers, (in, out) of each
    assert shape.lora_params(2, ["in_proj_qkv"]) == 2 * (8 + 24)
    assert shape.lora_params(2, ["in_proj_qkv", "down_proj", "qkv"]) == 2 * (8 + 24 + 16 + 8)


# Qwen3.5 checkpoints at the pinned revisions (``memory.hub_shape`` on the Hub's
# safetensors headers, 18 Kasım 2026): every Gated DeltaNet layer has in_proj_qkv/z/a/b and
# out_proj, every full attention layer (each 4th) q/k/v/o_proj, every layer the MLP.
def _qwen35(hidden, inter, layers, qkv, value, q_out, kv_out, heads_v):
    linear = [("in_proj_qkv", hidden, qkv), ("in_proj_z", hidden, value)]
    linear += [("in_proj_a", hidden, heads_v), ("in_proj_b", hidden, heads_v)]
    linear += [("out_proj", value, hidden)]
    full = [("q_proj", hidden, q_out), ("k_proj", hidden, kv_out), ("v_proj", hidden, kv_out)]
    full += [("o_proj", q_out // 2, hidden)]
    mlp = [("gate_proj", hidden, inter), ("up_proj", hidden, inter), ("down_proj", inter, hidden)]
    shapes = []
    for i in range(layers):
        shapes += (full if (i + 1) % 4 == 0 else linear) + mlp
    return tuple(shapes)


QWEN_08B = mem.ModelShape(
    vocab=248320, hidden=1024, layers=24, tied=True, quantized_params=595_132_416,
    vector_params=182_336, other_params=3_391_488,
    lora_shapes=_qwen35(1024, 3584, 24, 6144, 2048, 4096, 512, 16),
)  # fmt: skip
QWEN_9B = mem.ModelShape(
    vocab=248320, hidden=4096, layers=32, tied=False, quantized_params=7_369_682_944,
    vector_params=683_248, other_params=5_210_112,
    lora_shapes=_qwen35(4096, 12288, 32, 8192, 4096, 8192, 1024, 32),
)  # fmt: skip
QWEN_4B = mem.ModelShape(
    vocab=248320, hidden=2560, layers=32, tied=True, quantized_params=3_898_343_424,
    vector_params=504_320, other_params=4_718_592,
    lora_shapes=_qwen35(2560, 9216, 32, 8192, 4096, 8192, 1024, 32),
)  # fmt: skip


def test_lora_parameter_counts_match_the_trainers():
    targets = ft.load_config(CONFIGS / "r16-e2.toml").target_modules
    # the Task 8 trial's run.json: 5,111,808 trainable parameters at r8 on 0.8B
    assert QWEN_08B.lora_params(8, targets) == 5_111_808
    assert QWEN_9B.lora_params(16, targets) == 40_108_032
    assert QWEN_9B.lora_params(32, targets) == 80_216_064


@pytest.mark.parametrize(
    ("config", "tokens", "target", "measured"),
    [
        ("laptop-trial.toml", 1241, 501, 5.357),  # Task 8, PEFT path
        ("laptop-trial-lean.toml", 1241, 501, 1.260),  # Task 8b, seeded records
        ("laptop-trial-lean.toml", 1475, 622, 1.325),  # Task 8b, longest records
    ],
)
def test_the_estimate_meets_the_laptop_trials(config, tokens, target, measured):
    """Peak allocated VRAM of the three 0.8B trials (run.json), within 5 %."""
    estimate = mem.estimate(
        QWEN_08B, ft.load_config(CONFIGS / config), tokens=tokens, target_tokens=target
    )
    assert estimate["total"] == pytest.approx(measured, rel=0.05)


def test_the_9b_estimate_on_the_lean_path_and_on_the_old_one():
    trial = ft.load_config(CONFIGS / "trial-9b.toml")
    r16 = mem.estimate(QWEN_9B, dataclasses.replace(trial, rank=16), tokens=1475, target_tokens=622)
    r32 = mem.estimate(QWEN_9B, trial, tokens=1475, target_tokens=622)
    assert round(r16["total"], 2) == 8.99
    assert round(r32["total"], 2) == 9.29
    assert r32["total"] < 10.5  # the trial's pass line for allocated memory
    old = dataclasses.replace(trial, lean_memory=False, target_only_logits=False, logits_chunk=0)
    assert mem.estimate(QWEN_9B, old, tokens=1475, target_tokens=622)["total"] > 16
    four_b = mem.estimate(QWEN_4B, trial, tokens=1475, target_tokens=622)
    assert round(four_b["total"], 2) == 4.58


def test_layer_work_is_measured_at_three_widths_and_interpolated_between():
    assert mem.layer_work(4096, 1000) == 1000 * 651_760 + 102_800_000
    between = mem.layer_work(3328, 1000)
    assert mem.layer_work(2560, 1000) < between < mem.layer_work(4096, 1000)


def test_the_lean_path_saves_the_fp32_embedding_and_the_full_logits():
    old = ft.load_config(CONFIGS / "laptop-trial.toml")
    lean = ft.load_config(CONFIGS / "laptop-trial-lean.toml")
    before = mem.estimate(QWEN_08B, old, tokens=1241, target_tokens=500)
    after = mem.estimate(QWEN_08B, lean, tokens=1241, target_tokens=500)
    assert after["embedding_and_output"] == pytest.approx(before["embedding_and_output"] / 2)
    assert after["logits"] < before["logits"] / 5
    assert after["total"] < before["total"]


def test_target_only_logits_grow_with_the_chunk_not_the_sequence():
    lean = ft.load_config(CONFIGS / "laptop-trial-lean.toml")
    short = mem.estimate(QWEN_08B, lean, tokens=600, target_tokens=600)["logits"]
    long = mem.estimate(QWEN_08B, lean, tokens=1475, target_tokens=622)["logits"]
    assert short == long  # 128 rows at a time either way
    one_piece = dataclasses.replace(lean, logits_chunk=0)
    assert mem.estimate(QWEN_08B, one_piece, tokens=1475, target_tokens=622)["logits"] > long


def test_the_estimate_refuses_a_batch_it_was_not_calibrated_for():
    config = dataclasses.replace(ft.load_config(CONFIGS / "trial-9b.toml"), batch_size=2)
    with pytest.raises(ValueError, match="batch_size"):
        mem.estimate(QWEN_08B, config, tokens=100, target_tokens=10)
