"""The memory-lean QLoRA path: target-only logits and the lean model preparation.

These tests build a tiny, randomly initialised Qwen3.5 text model on the CPU. They need
torch, transformers and peft (the ``train`` group) and skip cleanly without them; no GPU,
no download and no network.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
peft = pytest.importorskip("peft")

from bist_harness.finetune import train as ft  # noqa: E402

TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "in_proj_qkv", "in_proj_z", "out_proj"]
TARGETS += ["gate_proj", "up_proj", "down_proj"]
VOCAB = 211


def _tiny_model(*, tie: bool = False, dtype=None):
    config = transformers.Qwen3_5TextConfig(
        vocab_size=VOCAB,
        hidden_size=32,
        intermediate_size=48,
        num_hidden_layers=4,  # three Gated DeltaNet layers and one full attention layer
        num_attention_heads=2,
        num_key_value_heads=1,
        head_dim=16,
        linear_num_key_heads=2,
        linear_num_value_heads=2,
        linear_key_head_dim=8,
        linear_value_head_dim=8,
        tie_word_embeddings=tie,
        max_position_embeddings=256,
    )
    torch.manual_seed(0)
    model = transformers.Qwen3_5ForCausalLM(config)
    if dtype is not None:
        model = model.to(dtype)
    return model


def _lora(model, rank: int = 4):
    config = peft.LoraConfig(
        r=rank, lora_alpha=8, lora_dropout=0.0, target_modules=TARGETS, task_type="CAUSAL_LM"
    )
    lora_model = peft.get_peft_model(model, config)
    # PEFT starts B at zero; random B makes the LoRA gradients and the loss non-trivial
    torch.manual_seed(1)
    for name, param in lora_model.named_parameters():
        if "lora_B" in name:
            param.data.normal_(0, 0.05)
    return lora_model


def _batch():
    """Two rows of different length: padding, a masked prompt and a target in each."""
    torch.manual_seed(2)
    ids = torch.randint(0, VOCAB, (2, 23))
    attention = torch.ones_like(ids)
    attention[1, 17:] = 0  # the second row is padded
    labels = ids.clone()
    labels[0, :9] = ft.IGNORE_INDEX  # prompt
    labels[1, :12] = ft.IGNORE_INDEX
    labels[1, 17:] = ft.IGNORE_INDEX  # padding
    return {"input_ids": ids, "attention_mask": attention, "labels": labels}


def _lora_grads(model) -> dict:
    return {n: p.grad.clone() for n, p in model.named_parameters() if p.requires_grad}


def _standard(model, batch, num_items_in_batch=None):
    kwargs = {} if num_items_in_batch is None else {"num_items_in_batch": num_items_in_batch}
    model.zero_grad(set_to_none=True)
    loss = model(**batch, **kwargs).loss
    loss.backward()
    return loss.detach(), _lora_grads(model)


def _target_only(model, batch, num_items_in_batch=None, chunk=0):
    model.zero_grad(set_to_none=True)
    loss = ft.target_only_loss(model, batch, num_items_in_batch=num_items_in_batch, chunk=chunk)
    loss.backward()
    return loss.detach(), _lora_grads(model)


@pytest.mark.parametrize("chunk", [0, 1, 5, 64])
def test_target_only_loss_equals_the_standard_masked_cross_entropy(chunk):
    model = _lora(_tiny_model())
    batch = _batch()
    expected_loss, expected_grads = _standard(model, batch)
    loss, grads = _target_only(model, batch, chunk=chunk)
    torch.testing.assert_close(loss, expected_loss, rtol=1e-5, atol=1e-6)
    assert grads.keys() == expected_grads.keys()
    assert any("lora_A" in name for name in grads)
    for name, grad in grads.items():
        torch.testing.assert_close(grad, expected_grads[name], rtol=1e-4, atol=1e-6, msg=name)


def test_target_only_loss_divides_by_the_accumulated_token_count_like_the_model():
    """With gradient accumulation the Trainer passes ``num_items_in_batch``."""
    model = _lora(_tiny_model())
    batch = _batch()
    tokens = int((batch["labels"][:, 1:] != ft.IGNORE_INDEX).sum())
    count = torch.tensor(tokens * 3)  # as if three such micro-batches were accumulated
    expected_loss, expected_grads = _standard(model, batch, count)
    loss, grads = _target_only(model, batch, count, chunk=4)
    torch.testing.assert_close(loss, expected_loss, rtol=1e-5, atol=1e-6)
    for name, grad in grads.items():
        torch.testing.assert_close(grad, expected_grads[name], rtol=1e-4, atol=1e-6, msg=name)


def test_target_only_loss_computes_the_output_layer_only_at_target_positions():
    model = _lora(_tiny_model())
    batch = _batch()
    rows = []
    head = model.get_base_model().get_output_embeddings()
    hook = head.register_forward_hook(lambda module, args, out: rows.append(args[0].shape[0]))
    try:
        ft.target_only_loss(model, batch, chunk=0)
    finally:
        hook.remove()
    targets = int((batch["labels"][:, 1:] != ft.IGNORE_INDEX).sum())
    assert rows == [targets]  # one call, on the labelled positions only (2 x 23 positions in all)


def test_target_only_loss_with_tied_embeddings():
    model = _lora(_tiny_model(tie=True))
    batch = _batch()
    expected_loss, expected_grads = _standard(model, batch)
    loss, grads = _target_only(model, batch, chunk=3)
    torch.testing.assert_close(loss, expected_loss, rtol=1e-5, atol=1e-6)
    for name, grad in grads.items():
        torch.testing.assert_close(grad, expected_grads[name], rtol=1e-4, atol=1e-6, msg=name)


def test_target_only_loss_without_any_target_is_zero_and_keeps_the_graph():
    model = _lora(_tiny_model())
    batch = _batch()
    batch["labels"][:] = ft.IGNORE_INDEX
    loss = ft.target_only_loss(model, batch)
    assert float(loss) == 0.0
    loss.backward()  # no error: the loss is still connected to the trainable weights


def test_lean_preparation_keeps_embeddings_and_output_layer_frozen_in_bf16():
    model = _tiny_model(dtype=torch.bfloat16)
    ft.prepare_lean(model, gradient_checkpointing=True)
    assert model.get_input_embeddings().weight.dtype == torch.bfloat16
    assert model.get_output_embeddings().weight.dtype == torch.bfloat16
    assert not any(p.requires_grad for p in model.parameters())
    # the small parameters (norms, the Gated DeltaNet's A_log and dt_bias) are fp32
    params = dict(model.named_parameters())
    assert params["model.norm.weight"].dtype == torch.float32
    assert params["model.layers.0.linear_attn.A_log"].dtype == torch.float32
    assert params["model.layers.0.linear_attn.dt_bias"].dtype == torch.float32
    assert params["model.layers.0.input_layernorm.weight"].dtype == torch.float32
    # the large matrices are left as loaded (4-bit in a real run; here bf16)
    assert params["model.layers.0.mlp.down_proj.weight"].dtype == torch.bfloat16
    assert model.is_gradient_checkpointing
    # the input embeddings' output requires grad, so checkpointed layers see a grad path
    out = model.get_input_embeddings()(torch.tensor([[1, 2]]))
    assert out.requires_grad


def test_lean_preparation_then_lora_trains_only_the_adapter():
    model = _tiny_model(dtype=torch.bfloat16)
    ft.prepare_lean(model, gradient_checkpointing=False)
    lora_model = _lora(model)
    trainable = [n for n, p in lora_model.named_parameters() if p.requires_grad]
    assert trainable and all("lora_" in n for n in trainable)
    assert not model.is_gradient_checkpointing
