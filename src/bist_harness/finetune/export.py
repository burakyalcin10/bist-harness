"""Export a trained adapter to Ollama: merge, GGUF, Modelfile, ``ollama create``.

1. The adapter is merged into the base checkpoint shard by shard, in its own precision
   (``stream_merge``; a 9B model in bf16 does not fit the desktop's 16 GB RAM whole).
   ``merge_adapter`` is PEFT's whole-model merge, kept as the reference it is tested against.
2. llama.cpp's ``convert_hf_to_gguf.py`` writes an f16 GGUF (``convert_to_gguf``). The
   checkout is not part of this repository (``tools/llama.cpp/``, git-ignored) and must
   be the llama.cpp commit the installed Ollama runs (``llama-server.exe --version`` in
   Ollama's ``lib/ollama`` folder; Ollama 0.40.16: ``6c01da627``). A newer converter
   fuses tensors (``attn_qkv_gate``, ``ssm_beta_alpha``) that Ollama's runtime rejects.
3. The Modelfile takes the chat and tool template of the base Ollama model as it is
   (``TEMPLATE``, or a built-in ``RENDERER``/``PARSER``, and its ``stop`` words), with
   ``temperature 0``, ``seed 42`` and a ``num_ctx`` that holds the harness's longest turn.
4. ``llama-quantize`` writes the q4_K_M GGUF (``quant=None`` keeps f16). Ollama 0.40
   quantizes only safetensors imports (``ollama create --quantize`` on a GGUF stops with
   "create-time quantization is only supported for safetensors imports"); the quantizer
   Ollama ships in ``lib/ollama`` is used, built from the same commit as its runtime.
5. ``ollama create <name> -f Modelfile``.

Command line::

    uv run --group train python -m bist_harness.finetune.export \\
        --adapter runs/finetune-r16-e2/adapter --name bist-r16-e2 \\
        --template-from qwen3.5:4b --llama-cpp tools/llama.cpp
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from bist_harness.finetune.train import TrainGroupMissingError, _load_base, require_train_group

KEPT_INSTRUCTIONS = ("TEMPLATE", "RENDERER", "PARSER")
ROOM_TO_ANSWER = 1024  # tokens the reply may take beyond the longest training example
MIN_NUM_CTX = 4096


# --- the Modelfile ----------------------------------------------------------------------
def _instructions(modelfile: str) -> list[tuple[str, str]]:
    """``(keyword, raw text)`` of every instruction; a ``\"\"\"`` value may span lines."""
    found: list[tuple[str, str]] = []
    lines = modelfile.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        i += 1
        if not stripped or stripped.startswith("#"):
            continue
        keyword = stripped.split(maxsplit=1)[0].upper()
        block = [line]
        if stripped.count('"""') == 1:  # an opened, unclosed multi-line value
            while i < len(lines):
                block.append(lines[i])
                i += 1
                if '"""' in block[-1]:
                    break
        found.append((keyword, "\n".join(block)))
    return found


def render_modelfile(gguf_name: str, base_modelfile: str, *, num_ctx: int) -> str:
    """The Modelfile of the exported model.

    From the base model's Modelfile (``ollama show <base> --modelfile``) only the chat and
    tool template is kept: ``TEMPLATE``, ``RENDERER``, ``PARSER`` and ``PARAMETER stop``.
    Its sampling settings, draft model, blobs and licence do not carry over.
    """
    kept = []
    for keyword, text in _instructions(base_modelfile):
        if keyword in KEPT_INSTRUCTIONS:
            kept.append(text)
        elif keyword == "PARAMETER" and text.split()[1:2] == ["stop"]:
            kept.append(text)
    if not any(t.lstrip().upper().startswith(("TEMPLATE", "RENDERER")) for t in kept):
        raise ValueError(
            "the base Modelfile has no TEMPLATE or RENDERER: the chat and tool template "
            "cannot be carried over"
        )
    lines = [f"FROM ./{gguf_name}", *kept]
    lines += ["PARAMETER temperature 0", "PARAMETER seed 42", f"PARAMETER num_ctx {num_ctx}"]
    return "\n".join(lines) + "\n"


def num_ctx_for(longest_tokens: int) -> int:
    """A context that holds the longest turn and its reply, in steps of 1024 tokens."""
    needed = math.ceil((longest_tokens + ROOM_TO_ANSWER) / 1024) * 1024
    return max(MIN_NUM_CTX, needed)


# --- the heavy steps --------------------------------------------------------------------
def _executable(name: str) -> str:
    """``name`` on PATH, or Ollama's default Windows install folder when PATH lacks it."""
    found = shutil.which(name)
    if found:
        return found
    if name == "ollama" and os.environ.get("LOCALAPPDATA"):
        default = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Ollama" / "ollama.exe"
        if default.is_file():
            return str(default)
    return name


def default_quantizer() -> Path | None:
    """The ``llama-quantize`` Ollama ships (Windows install folder), if present."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    path = Path(local) / "Programs" / "Ollama" / "lib" / "ollama" / "llama-quantize.exe"
    return path if path.is_file() else None


def _run(args: list[str], *, cwd: Path | None = None) -> str:
    command = [_executable(str(args[0])), *(str(a) for a in args[1:])]
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"cannot start {args[0]}: {exc}") from None
    if done.returncode != 0:
        tail = "\n".join((done.stderr or done.stdout).strip().splitlines()[-15:])
        raise RuntimeError(f"{' '.join(str(a) for a in args[:3])} failed:\n{tail}")
    return done.stdout


def _output(args: list) -> str:
    """stdout and stderr of a command, or "" when it cannot run (a probe, never fatal)."""
    try:
        done = subprocess.run(
            [str(a) for a in args], capture_output=True, text=True, encoding="utf-8"
        )
    except OSError:
        return ""
    return (done.stdout or "") + (done.stderr or "")


def runtime_commit_of(version_text: str) -> str | None:
    """The llama.cpp commit in ``llama-server --version`` output (a short hash)."""
    found = re.search(r"commit ([0-9a-f]{7,40})", version_text)
    return found.group(1) if found else None


def ollama_runtime() -> dict:
    """The installed Ollama's version and the llama.cpp commit its runtime is built from."""
    ollama = Path(_executable("ollama"))
    version = re.search(r"(\d+\.\d+\.\d+\S*)", _output([ollama, "--version"]))
    commit = None
    for lib in (ollama.parent / "lib" / "ollama", ollama.parent.parent / "lib" / "ollama"):
        for server in (lib / "llama-server.exe", lib / "llama-server"):
            if server.is_file():
                commit = runtime_commit_of(_output([server, "--version"]))
                break
        if commit:
            break
    return {"ollama_version": version.group(1) if version else None, "runtime_commit": commit}


def converter_commit(llama_cpp: Path) -> str | None:
    """The commit the llama.cpp checkout is at, or None when it is not a git checkout."""
    found = re.search(r"\b([0-9a-f]{40})\b", _output(["git", "-C", llama_cpp, "rev-parse", "HEAD"]))
    return found.group(1) if found else None


def _ollama_url() -> str:
    """The local Ollama the ``ollama`` command talks to (``OLLAMA_HOST``); never logged."""
    host = os.environ.get("OLLAMA_HOST", "").strip() or "127.0.0.1:11434"
    if "://" not in host:
        host = "http://" + host
    return host.replace("://0.0.0.0", "://127.0.0.1").rstrip("/")


def load_check(name: str, *, transport: httpx.BaseTransport | None = None) -> None:
    """Load the created model and generate one token; raise if Ollama cannot load it.

    ``ollama create`` does not load the weights: a GGUF whose tensors the runtime does
    not know is created without complaint and fails only at the first request.
    """
    payload = {
        "model": name,
        "prompt": "ok",
        "stream": False,
        "think": False,
        "keep_alive": 0,
        "options": {"num_predict": 1, "temperature": 0, "seed": 42},
    }
    try:
        with httpx.Client(base_url=_ollama_url(), timeout=600, transport=transport) as http:
            response = http.post("/api/generate", json=payload)
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"cannot reach the local Ollama to load {name} ({type(exc).__name__})"
        ) from None
    if response.status_code >= 400:
        try:
            error = str(response.json().get("error", ""))
        except ValueError:
            error = response.text[:300]
        raise RuntimeError(
            f"Ollama cannot load {name}: {error}. The GGUF was probably converted with another "
            "llama.cpp commit than the one Ollama runs (docs/finetune.md); remove it with "
            f"`ollama rm {name}`"
        )


def merge_adapter(
    adapter_dir: Path, base_model: str, merged_dir: Path, *, revision: str | None = None
) -> Path:
    """Merge the LoRA adapter into the base weights and save a Hugging Face checkpoint."""
    modules = require_train_group()
    torch = modules["torch"]
    from peft import PeftModel
    from transformers import AutoTokenizer

    base = _load_base(base_model, revision or "main", dtype=torch.bfloat16, device_map="cpu")
    merged = PeftModel.from_pretrained(base, str(adapter_dir)).merge_and_unload()
    merged_dir = Path(merged_dir)
    merged_dir.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(merged_dir, safe_serialization=True)
    AutoTokenizer.from_pretrained(base_model, revision=revision or "main").save_pretrained(
        merged_dir
    )
    return merged_dir


# --- the streaming merge ----------------------------------------------------------------
# Tensors transformers ignores when it loads a Qwen3.5 checkpoint
# (``_keys_to_ignore_on_load_unexpected``): the PEFT merge never wrote them, and neither
# does the streaming merge, so the converter sees the same set of tensors on both paths.
SKIPPED_PREFIXES = ("mtp.",)
# adapter settings the merge does not implement: an adapter that sets one is refused
_UNSUPPORTED = (
    "use_dora",
    "lora_bias",
    "fan_in_fan_out",
    "rank_pattern",
    "alpha_pattern",
    "modules_to_save",
    "trainable_token_indices",
    "target_parameters",
    "layer_replication",
)
_ADAPTER_PREFIX = "base_model.model."
DEFAULT_SHARD_BYTES = 2 * 2**30


def _base_snapshot(base_model: str, revision: str | None) -> Path:
    """A local folder with the base checkpoint: the folder itself, or the Hub snapshot."""
    if Path(base_model).is_dir():
        return Path(base_model)
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(base_model, revision=revision or "main"))


def _adapter_deltas(adapter_dir: Path) -> tuple[dict, float]:
    """``{module path: (A, B)}`` of the adapter and its scaling (``alpha / r``)."""
    from safetensors.torch import load_file

    config = json.loads((adapter_dir / "adapter_config.json").read_text(encoding="utf-8"))
    for key in _UNSUPPORTED:
        if config.get(key):
            raise ValueError(
                f"the adapter sets {key} = {config.get(key)!r}; the streaming merge implements "
                "plain LoRA only"
            )
    if config.get("peft_type", "LORA") != "LORA":
        raise ValueError(f"not a LoRA adapter: {config.get('peft_type')}")
    rank, alpha = int(config["r"]), float(config["lora_alpha"])
    scaling = alpha / math.sqrt(rank) if config.get("use_rslora") else alpha / rank
    pairs: dict[str, dict] = {}
    for key, tensor in load_file(adapter_dir / "adapter_model.safetensors").items():
        found = re.fullmatch(r"(.+)\.lora_([AB])\.weight", key)
        if not found or not key.startswith(_ADAPTER_PREFIX):
            raise ValueError(f"unexpected adapter tensor {key}")
        pairs.setdefault(found.group(1)[len(_ADAPTER_PREFIX) :], {})[found.group(2)] = tensor
    deltas = {}
    for module, pair in pairs.items():
        if set(pair) != {"A", "B"} or pair["A"].shape[0] != rank:
            raise ValueError(f"adapter layer {module}: lora_A/lora_B of rank {rank} expected")
        deltas[module] = (pair["A"], pair["B"])
    return deltas, scaling


def _shard_names(base_dir: Path) -> list[str]:
    index = base_dir / "model.safetensors.index.json"
    if index.is_file():
        weight_map = json.loads(index.read_text(encoding="utf-8"))["weight_map"]
        return sorted(set(weight_map.values()))
    if (base_dir / "model.safetensors").is_file():
        return ["model.safetensors"]
    raise FileNotFoundError(f"no safetensors checkpoint in {base_dir}")


def stream_merge(
    adapter_dir: Path,
    base_model: str | Path,
    merged_dir: Path,
    *,
    revision: str | None = None,
    max_shard_bytes: int = DEFAULT_SHARD_BYTES,
) -> Path:
    """Merge a LoRA adapter into the base checkpoint one tensor at a time.

    PEFT's ``merge_and_unload`` needs the whole bf16 model in memory (about 18 GB for 9B,
    more than the desktop's 16 GB). Here each base shard is opened memory-mapped, every
    tensor is read alone, each LoRA target gets ``W + scale * (B @ A)`` with PEFT's
    arithmetic (the product in fp32, the sum rounded once to the weight's dtype), and
    the result is written in new shards of at most ``max_shard_bytes``. Peak memory is
    about one output shard plus one tensor. Every non-weight file of the base (config,
    tokenizer, chat template) is copied unchanged. Returns ``merged_dir``.
    """
    require_train_group()
    from safetensors import safe_open
    from safetensors.torch import save_file

    adapter_dir, merged_dir = Path(adapter_dir), Path(merged_dir)
    deltas, scaling = _adapter_deltas(adapter_dir)
    base_dir = _base_snapshot(str(base_model), revision)
    merged_dir.mkdir(parents=True, exist_ok=True)
    for stale in merged_dir.glob("*.safetensors"):
        stale.unlink()

    used: set[str] = set()
    written: list[tuple[str, list[str]]] = []
    pending: dict = {}
    pending_bytes = 0
    total_bytes = 0

    def flush() -> None:
        nonlocal pending, pending_bytes
        if not pending:
            return
        name = f"part-{len(written) + 1:05d}.safetensors"
        save_file(pending, merged_dir / name, metadata={"format": "pt"})
        written.append((name, list(pending)))
        pending, pending_bytes = {}, 0

    for shard in _shard_names(base_dir):
        with safe_open(base_dir / shard, framework="pt") as handle:
            for key in handle.keys():
                if key.startswith(SKIPPED_PREFIXES):
                    continue
                tensor = handle.get_tensor(key)
                module = key[: -len(".weight")] if key.endswith(".weight") else None
                if module in deltas:
                    lora_a, lora_b = deltas[module]
                    delta = (lora_b.float() @ lora_a.float()) * scaling
                    if delta.shape != tensor.shape:
                        raise ValueError(f"{key}: LoRA delta {tuple(delta.shape)} does not fit")
                    tensor = (tensor.float() + delta).to(tensor.dtype)
                    used.add(module)
                size = tensor.numel() * tensor.element_size()
                if pending and pending_bytes + size > max_shard_bytes:
                    flush()
                pending[key] = tensor.contiguous()
                pending_bytes += size
                total_bytes += size
    flush()
    missing = sorted(set(deltas) - used)
    if missing:
        raise ValueError(
            f"{len(missing)} adapter layer(s) have no weight in the base checkpoint, e.g. "
            f"{missing[0]}; is the adapter from another base model?"
        )

    count = len(written)
    weight_map = {}
    for number, (name, keys) in enumerate(written, start=1):
        final = f"model-{number:05d}-of-{count:05d}.safetensors"
        os.replace(merged_dir / name, merged_dir / final)
        weight_map.update(dict.fromkeys(keys, final))
    index = {"metadata": {"total_size": total_bytes}, "weight_map": weight_map}
    with (merged_dir / "model.safetensors.index.json").open(
        "w", encoding="utf-8", newline="\n"
    ) as handle:
        json.dump(index, handle, indent=2)
        handle.write("\n")
    for path in base_dir.iterdir():
        if (
            path.is_file()
            and not path.name.endswith(".safetensors")
            and path.name not in ("model.safetensors.index.json",)
        ):
            shutil.copyfile(path, merged_dir / path.name)
    return merged_dir


def convert_to_gguf(merged_dir: Path, gguf_path: Path, *, llama_cpp: Path) -> Path:
    """llama.cpp's converter, run with this interpreter (it needs the train group)."""
    script = Path(llama_cpp) / "convert_hf_to_gguf.py"
    if not script.is_file():
        raise FileNotFoundError(
            f"{script} not found: clone llama.cpp at the pinned tag (docs/finetune.md)"
        )
    _run(
        [sys.executable, script, merged_dir, "--outfile", gguf_path, "--outtype", "f16"],
    )
    return Path(gguf_path)


def quantize_gguf(f16_gguf: Path, out_gguf: Path, quant: str, *, llama_quantize: Path) -> Path:
    """llama.cpp's quantizer: ``llama-quantize <f16.gguf> <out.gguf> <TYPE>``."""
    _run([llama_quantize, f16_gguf, out_gguf, quant.upper()])
    return Path(out_gguf)


def export(
    adapter_dir: Path,
    base_model: str,
    out_dir: Path,
    *,
    quant: str | None = "q4_K_M",
    name: str,
    template_from: str,
    llama_cpp: Path,
    llama_quantize: Path | None = None,
    num_ctx: int | None = None,
    revision: str | None = None,
    keep_merged: bool = False,
) -> Path:
    """Merge, convert, write the Modelfile and create the Ollama model; return the Modelfile.

    ``template_from`` is the Ollama tag of the base model whose template is carried over.
    ``llama_quantize`` is llama.cpp's quantizer, needed unless ``quant`` is None.
    ``num_ctx`` and ``revision`` default to the training run's ``run.json`` next to the
    adapter folder.
    """
    adapter_dir, out_dir = Path(adapter_dir), Path(out_dir)
    run_path = adapter_dir.parent / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8")) if run_path.is_file() else {}
    revision = revision or run.get("config", {}).get("revision")
    if num_ctx is None:
        if "max_example_tokens" not in run:
            raise ValueError("num_ctx unknown: pass it or keep run.json next to the adapter")
        num_ctx = num_ctx_for(run["max_example_tokens"])
    runtime = ollama_runtime()
    converter = converter_commit(Path(llama_cpp))
    expected = runtime.get("runtime_commit")
    if expected and converter and not converter.startswith(expected):
        raise ValueError(
            f"the llama.cpp checkout is at {converter[:9]}, but Ollama "
            f"{runtime.get('ollama_version')} runs llama.cpp {expected}: check out that commit "
            "(docs/finetune.md). A GGUF from another converter is created but does not load."
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    merged = stream_merge(adapter_dir, base_model, out_dir / "merged", revision=revision)
    gguf = convert_to_gguf(merged, out_dir / "model-f16.gguf", llama_cpp=Path(llama_cpp))
    if not keep_merged:
        shutil.rmtree(out_dir / "merged", ignore_errors=True)
    if quant:
        if llama_quantize is None:
            raise ValueError("quantization needs llama.cpp's llama-quantize (--llama-quantize)")
        gguf = quantize_gguf(
            gguf, out_dir / f"model-{quant}.gguf", quant, llama_quantize=Path(llama_quantize)
        )
    base_modelfile = _run(["ollama", "show", template_from, "--modelfile"])
    modelfile = out_dir / "Modelfile"
    with modelfile.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_modelfile(gguf.name, base_modelfile, num_ctx=num_ctx))
    _run(["ollama", "create", name, "-f", "Modelfile"], cwd=out_dir)
    load_check(name)

    record = {
        "name": name,
        "quant": quant or "f16",
        "template_from": template_from,
        "num_ctx": num_ctx,
        "base_model": base_model,
        "revision": revision,
        "adapter": adapter_dir.parent.name + "/" + adapter_dir.name,
        "gguf": gguf.name,
        "ollama_version": runtime.get("ollama_version"),
        "runtime_commit": expected,
        "converter_commit": converter,
        "load_check": "passed",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    with (out_dir / "export.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    return modelfile


# --- command line -----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="export a trained adapter to Ollama")
    parser.add_argument("--adapter", type=Path, required=True, help="the run's adapter/ folder")
    parser.add_argument("--name", required=True, help="the Ollama model name to create")
    parser.add_argument(
        "--template-from", required=True, help="Ollama tag of the base model, e.g. qwen3.5:0.8b"
    )
    parser.add_argument("--llama-cpp", type=Path, default=Path("tools/llama.cpp"))
    parser.add_argument(
        "--llama-quantize",
        type=Path,
        help="llama.cpp's quantizer (default: the one in Ollama's lib/ollama folder)",
    )
    parser.add_argument("--out", type=Path, help="default: <run>/export-<name>")
    parser.add_argument("--quant", default="q4_K_M", help="'none' keeps the f16 weights")
    parser.add_argument("--num-ctx", type=int, help="default: from run.json")
    parser.add_argument("--base-model", help="default: from run.json")
    parser.add_argument("--keep-merged", action="store_true")
    args = parser.parse_args(argv)

    run_path = args.adapter.parent / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8")) if run_path.is_file() else {}
    base_model = args.base_model or run.get("config", {}).get("base_model")
    if not base_model:
        print("[export] base model unknown: pass --base-model", file=sys.stderr)
        return 2
    out = args.out or args.adapter.parent / f"export-{args.name.replace(':', '-')}"
    try:
        modelfile = export(
            args.adapter,
            base_model,
            out,
            quant=None if args.quant.lower() in ("none", "f16") else args.quant,
            name=args.name,
            template_from=args.template_from,
            llama_cpp=args.llama_cpp,
            llama_quantize=args.llama_quantize or default_quantizer(),
            num_ctx=args.num_ctx,
            keep_merged=args.keep_merged,
        )
    except (TrainGroupMissingError, ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"[export] {exc}", file=sys.stderr)
        return 2
    print(f"[export] {args.name} created from {modelfile}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
