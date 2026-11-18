"""Expected peak VRAM of a QLoRA run, before the GPU is touched.

The estimate is PyTorch's peak *allocated* memory (``torch.cuda.max_memory_allocated``,
what ``run.json`` records as ``peak_vram_gb.allocated``), in GiB (2**30 bytes, written
"GB" as in run.json). It does not count the CUDA context, the caching allocator's
reserve, Windows' display memory or bitsandbytes' paged optimizer states (managed
memory, outside PyTorch's allocator). Terms:

- weights: 4-bit NF4 linear layers (double quantization), the embedding and output layer
  (bf16 on the lean path, fp32 after PEFT's ``prepare_model_for_kbit_training``), the
  other small parameters;
- LoRA: fp32 weight and gradient of every adapter parameter;
- activations: with gradient checkpointing, one hidden state per layer and token is
  kept, plus the work space of the one decoder layer being recomputed in the backward
  pass (Gated DeltaNet's PyTorch reference kernels, the dequantized 4-bit weight, LoRA);
- logits: the vocabulary-sized output, over the whole sequence (standard loss) or only
  over ``logits_chunk`` target positions at a time (``target_only_logits``).

The layer work space and a chunk of target-only logits are alive at different moments
of the backward pass (the output layer runs first, then the layers one by one), so the
peak holds the larger of the two, not their sum.

Calibration (laptop, RTX 3050 Ti; ``docs/results/2026-11-18-finetune-training.md``,
section 9): the layer work space was measured on 4-bit stacks of Qwen3.5 decoder layers
with random weights at the 0.8B, 4B and 9B widths (two sequence lengths each: a per-token
slope and a fixed part); the chunk of logits on a bf16 output layer of the real
vocabulary; the full-sequence logits on the Task 8 trial (PEFT path). The estimate then
falls within 2-4 % (under) of the measured 0.8B lean trials.

Command line (the model's tensor shapes come from the Hugging Face Hub metadata, no
weights are downloaded)::

    uv run --group train python -m bist_harness.finetune.memory \\
        --config configs/qlora/trial-9b.toml --tokens 1475 --target-tokens 622
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from bist_harness.finetune.train import TrainConfig, load_config

GIB = 2**30
# NF4 with double quantization: 4 bits, an 8-bit absmax per 64 weights, an fp32 absmax
# per 256 blocks
NF4_BYTES = 0.5 + 1 / 64 + 4 / (64 * 256)
# LoRA, per adapter parameter: fp32 weight and fp32 gradient (the 8-bit Adam states are
# paged, outside PyTorch's allocator)
LORA_BYTES = 8

# --- calibration (laptop measurements, docs/results/2026-11-18-finetune-training.md §9) --
# work space of the one decoder layer recomputed in the backward pass, by hidden size:
# (bytes per token, fixed bytes), measured on 4-bit Qwen3.5 layer stacks at 737 and 1,475
# tokens, LoRA r32 on the ten target layers; between and beyond the measured widths the
# values are interpolated linearly in the hidden size
LAYER_WORK = {
    1024: (284_760, 18_300_000),  # 0.8B width
    2560: (564_790, 63_100_000),  # 4B width
    4096: (651_760, 102_800_000),  # 9B width
}
# bytes per element of one chunk of target-only logits: bf16 logits, their fp32 copy,
# the saved log-softmax and the fp32 gradient (measured, 248,320 x 64/128/256 rows)
CHUNK_LOGIT_BYTES = 12.7
# bytes per element of the full-sequence logits on PEFT's path (the Task 8 trial's peak
# less its other terms; a bare microbenchmark of the same loss gives 16.0)
FULL_LOGIT_BYTES = 13.8


def layer_work(hidden: int, tokens: int) -> float:
    """Bytes of the recomputed layer's work space at ``tokens`` (interpolated in width)."""
    widths = sorted(LAYER_WORK)
    if hidden in LAYER_WORK:
        per_token, fixed = LAYER_WORK[hidden]
    else:
        low, high = (
            (widths[0], widths[1])
            if hidden < widths[0]
            else (widths[-2], widths[-1])
            if hidden > widths[-1]
            else next((a, b) for a, b in zip(widths, widths[1:], strict=False) if a < hidden < b)
        )
        share = (hidden - low) / (high - low)
        per_token, fixed = (
            LAYER_WORK[low][i] + share * (LAYER_WORK[high][i] - LAYER_WORK[low][i]) for i in (0, 1)
        )
    return tokens * per_token + fixed


@dataclass(frozen=True)
class ModelShape:
    """What the estimate needs to know of a model, from its tensor shapes and config."""

    vocab: int
    hidden: int
    layers: int
    tied: bool  # the output layer shares the embedding's weight
    quantized_params: int  # linear weights that load in 4 bits (language model and vision)
    vector_params: int  # one-dimensional parameters (norms, biases, A_log, dt_bias)
    other_params: int  # the rest that does not quantize (convolution kernels, patch embeds)
    lora_shapes: tuple[tuple[str, int, int], ...]  # (layer name, in, out) of the LM's linears

    @property
    def embed_params(self) -> int:
        return self.vocab * self.hidden

    def lora_params(self, rank: int, targets: Sequence[str]) -> int:
        return sum(
            rank * (n_in + n_out) for name, n_in, n_out in self.lora_shapes if name in targets
        )


def _text_config(config: Mapping) -> Mapping:
    return config.get("text_config") or config


def shape_from_tensors(tensors: Mapping[str, Sequence[int]], config: Mapping) -> ModelShape:
    """A ``ModelShape`` from ``{tensor name: shape}`` of a checkpoint and its config.json.

    Tensors transformers does not load (``mtp.*``) are left out. A two-dimensional weight
    quantizes unless it is an embedding (``*embed*``) or the output layer (``lm_head``).
    """
    text = _text_config(config)
    tied = bool(text.get("tie_word_embeddings", config.get("tie_word_embeddings", False)))
    quantized = vector = other = 0
    lora: list[tuple[str, int, int]] = []
    for name, shape in tensors.items():
        if name.startswith("mtp."):
            continue
        count = math.prod(shape)
        if "embed_tokens" in name or name == "lm_head.weight":
            continue
        if len(shape) <= 1:
            vector += count
        elif len(shape) == 2 and name.endswith(".weight") and "embed" not in name:
            quantized += count
            if "visual" not in name and re.search(r"\.layers\.\d+\.", name):
                lora.append((name.split(".")[-2], shape[1], shape[0]))
        else:
            other += count
    return ModelShape(
        vocab=int(text["vocab_size"]),
        hidden=int(text["hidden_size"]),
        layers=int(text["num_hidden_layers"]),
        tied=tied,
        quantized_params=quantized,
        vector_params=vector,
        other_params=other,
        lora_shapes=tuple(lora),
    )


def estimate(
    shape: ModelShape, config: TrainConfig, *, tokens: int, target_tokens: int
) -> dict[str, float]:
    """Expected peak allocated VRAM (GiB) by term, and ``total``, for one batch-1 example.

    ``tokens`` is the longest example the run trains on; ``target_tokens`` the longest
    target (labelled) part of an example.
    """
    if config.batch_size != 1:
        raise ValueError("the estimate is calibrated for batch_size = 1")
    lean = config.lean_memory
    embed_bytes = 2 if lean else 4
    heads = 1 if shape.tied else 2
    terms = {
        "weights_4bit": shape.quantized_params * NF4_BYTES,
        "embedding_and_output": heads * shape.embed_params * embed_bytes,
        "other_weights": shape.vector_params * 4 + shape.other_params * (2 if lean else 4),
        "lora": shape.lora_params(config.rank, config.target_modules) * LORA_BYTES,
        # the checkpointed hidden states: bf16 on the lean path; fp32 after PEFT's upcast
        # (the fp32 embedding output makes the residual stream fp32)
        "checkpoints": shape.layers * tokens * shape.hidden * (2 if lean else 4),
    }
    work = layer_work(shape.hidden, tokens)
    if config.target_only_logits:
        rows = min(config.logits_chunk or target_tokens, target_tokens)
        logits = rows * shape.vocab * CHUNK_LOGIT_BYTES
    else:
        logits = tokens * shape.vocab * FULL_LOGIT_BYTES
    # the output layer's backward runs before the layers' recompute: the larger one counts
    terms["layer_work_or_logits"] = max(work, logits)
    result = {name: value / GIB for name, value in terms.items()}
    result["layer_work"] = work / GIB
    result["logits"] = logits / GIB
    result["total"] = sum(v for k, v in result.items() if k not in ("layer_work", "logits"))
    return result


# --- command line -----------------------------------------------------------------------
def hub_shape(repo_id: str, revision: str) -> ModelShape:
    """The shape of a Hub model from its safetensors headers and config.json."""
    from huggingface_hub import get_safetensors_metadata, hf_hub_download

    metadata = get_safetensors_metadata(repo_id, revision=revision)
    tensors = {
        name: info.shape
        for file in metadata.files_metadata.values()
        for name, info in file.tensors.items()
    }
    config = json.loads(
        Path(hf_hub_download(repo_id, "config.json", revision=revision)).read_text("utf-8")
    )
    return shape_from_tensors(tensors, config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="expected peak VRAM of a QLoRA run")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tokens", type=int, default=1475, help="the longest trained example")
    parser.add_argument("--target-tokens", type=int, default=622, help="its target part")
    parser.add_argument("--rank", type=int, action="append", help="estimate these ranks too")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    try:
        shape = hub_shape(config.base_model, config.revision)
    except ImportError:
        print(
            "[memory] huggingface_hub is missing: run with `uv run --group train`", file=sys.stderr
        )
        return 2
    for rank in args.rank or [config.rank]:
        run = replace(config, rank=rank)
        terms = estimate(shape, run, tokens=args.tokens, target_tokens=args.target_tokens)
        parts = ", ".join(f"{k} {v:.2f}" for k, v in terms.items() if k != "total")
        print(
            f"[memory] {config.base_model} r{rank}, {args.tokens} tokens "
            f"({args.target_tokens} target): {terms['total']:.2f} GB ({parts})",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
