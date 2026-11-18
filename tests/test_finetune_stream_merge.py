"""The streaming merge: shard by shard, the same tensors as PEFT's ``merge_and_unload``.

A tiny randomly initialised Qwen3.5 text model is saved in several safetensors shards with
a trained-looking LoRA adapter. Needs torch, transformers, peft and safetensors (the
``train`` group) and skips cleanly without them; CPU only, no network.
"""

from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
peft = pytest.importorskip("peft")
safetensors_torch = pytest.importorskip("safetensors.torch")

from bist_harness.finetune import export as fx  # noqa: E402

TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "in_proj_qkv", "in_proj_z", "out_proj"]
TARGETS += ["gate_proj", "up_proj", "down_proj"]


def _tiny_base(tmp_path):
    config = transformers.Qwen3_5TextConfig(
        vocab_size=173,
        hidden_size=32,
        intermediate_size=48,
        num_hidden_layers=4,
        num_attention_heads=2,
        num_key_value_heads=1,
        head_dim=16,
        linear_num_key_heads=2,
        linear_num_value_heads=2,
        linear_key_head_dim=8,
        linear_value_head_dim=8,
        tie_word_embeddings=False,
        max_position_embeddings=256,
    )
    torch.manual_seed(0)
    model = transformers.Qwen3_5ForCausalLM(config).to(torch.bfloat16)
    base_dir = tmp_path / "base"
    model.save_pretrained(base_dir, max_shard_size="40KB")  # several shards
    return model, base_dir


def _adapter(model, tmp_path, *, rank=4, alpha=8, rslora=False):
    config = peft.LoraConfig(
        r=rank,
        lora_alpha=alpha,
        lora_dropout=0.05,
        target_modules=TARGETS,
        task_type="CAUSAL_LM",
        use_rslora=rslora,
    )
    lora_model = peft.get_peft_model(model, config)
    torch.manual_seed(3)
    for name, param in lora_model.named_parameters():
        if "lora_" in name:
            param.data.normal_(0, 0.05)
    adapter_dir = tmp_path / "adapter"
    lora_model.save_pretrained(adapter_dir)
    return adapter_dir


def _peft_merged(base_dir, adapter_dir) -> dict:
    base = transformers.Qwen3_5ForCausalLM.from_pretrained(base_dir, dtype=torch.bfloat16)
    merged = peft.PeftModel.from_pretrained(base, str(adapter_dir)).merge_and_unload()
    return {k: v.detach().clone() for k, v in merged.state_dict().items()}


def _read_dir(path) -> dict:
    index = json.loads((path / "model.safetensors.index.json").read_text(encoding="utf-8"))
    tensors = {}
    for shard in sorted(set(index["weight_map"].values())):
        tensors.update(safetensors_torch.load_file(path / shard))
    assert set(tensors) == set(index["weight_map"])
    return tensors


@pytest.mark.parametrize("rslora", [False, True])
def test_stream_merge_gives_the_same_tensors_as_peft(tmp_path, rslora):
    model, base_dir = _tiny_base(tmp_path)
    shards = sorted(p.name for p in base_dir.glob("*.safetensors"))
    assert len(shards) > 2  # the test exercises the shard-by-shard path
    adapter_dir = _adapter(model, tmp_path, rslora=rslora)
    expected = _peft_merged(base_dir, adapter_dir)

    out = fx.stream_merge(adapter_dir, base_dir, tmp_path / "merged", max_shard_bytes=30_000)
    merged = _read_dir(out)
    assert len({p.name for p in out.glob("*.safetensors")}) > 1  # written in several shards
    assert set(merged) == set(expected)
    for name, tensor in merged.items():
        assert tensor.dtype == expected[name].dtype, name
        assert torch.equal(tensor, expected[name]), name  # bit for bit
    base = _read_dir(base_dir)
    assert any(not torch.equal(merged[name], base[name]) for name in merged)
    # the config and every non-weight file of the base come along; the adapter's do not
    assert json.loads((out / "config.json").read_text()) == json.loads(
        (base_dir / "config.json").read_text()
    )
    assert not (out / "adapter_config.json").exists()


def test_stream_merge_changes_exactly_the_adapted_layers(tmp_path):
    model, base_dir = _tiny_base(tmp_path)
    adapter_dir = _adapter(model, tmp_path)
    base = _read_dir(base_dir)
    merged = _read_dir(fx.stream_merge(adapter_dir, base_dir, tmp_path / "merged"))
    changed = sorted(name for name in merged if not torch.equal(merged[name], base[name]))
    adapted = sorted(
        name
        for name in base
        if name.endswith(".weight") and name.split(".")[-2] in TARGETS and ".layers." in name
    )
    assert changed == adapted


def test_stream_merge_leaves_out_the_mtp_block_like_the_peft_path(tmp_path):
    """transformers ignores ``mtp.*`` on load, so the PEFT merge never wrote it."""
    model, base_dir = _tiny_base(tmp_path)
    adapter_dir = _adapter(model, tmp_path)
    extra = {"mtp.fc.weight": torch.ones(4, 4, dtype=torch.bfloat16)}
    safetensors_torch.save_file(extra, base_dir / "extra.safetensors", metadata={"format": "pt"})
    index_path = base_dir / "model.safetensors.index.json"
    index = json.loads(index_path.read_text())
    index["weight_map"]["mtp.fc.weight"] = "extra.safetensors"
    index_path.write_text(json.dumps(index))
    merged = _read_dir(fx.stream_merge(adapter_dir, base_dir, tmp_path / "merged"))
    assert "mtp.fc.weight" not in merged
    assert "model.norm.weight" in merged


def test_stream_merge_refuses_an_adapter_layer_the_base_does_not_have(tmp_path):
    model, base_dir = _tiny_base(tmp_path)
    adapter_dir = _adapter(model, tmp_path)
    path = adapter_dir / "adapter_model.safetensors"
    tensors = safetensors_torch.load_file(path)
    renamed = {k.replace("layers.0.", "layers.9."): v for k, v in tensors.items()}
    safetensors_torch.save_file(renamed, path, metadata={"format": "pt"})
    with pytest.raises(ValueError, match="layers.9"):
        fx.stream_merge(adapter_dir, base_dir, tmp_path / "merged")


@pytest.mark.parametrize(
    "setting", [{"use_dora": True}, {"rank_pattern": {"q_proj": 2}}, {"lora_bias": True}]
)
def test_stream_merge_refuses_adapter_settings_it_does_not_implement(tmp_path, setting):
    model, base_dir = _tiny_base(tmp_path)
    adapter_dir = _adapter(model, tmp_path)
    config_path = adapter_dir / "adapter_config.json"
    config = json.loads(config_path.read_text())
    config.update(setting)
    config_path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match=next(iter(setting))):
        fx.stream_merge(adapter_dir, base_dir, tmp_path / "merged")
