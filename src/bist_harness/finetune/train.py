"""QLoRA training on the fine-tuning records, and the bundle that carries them to the GPU.

Every record is rendered with the base model tokenizer's own chat template, with the tool
schemas of the turn, so the training text is the prompt Ollama renders at inference
followed by the target reply. Ollama does not pass a tool schema through as it is: it
decodes it into its Go structs and marshals it again (``ollama_tools``), and the training
text shows the schema the same way. The loss is computed on the target turn only.

The training libraries live in the ``train`` dependency group (``uv sync --group train``).
They are imported inside the functions that need them; the harness itself never imports
them, and without the group ``train`` stops with a clear message.

Command line::

    uv run --group train python -m bist_harness.finetune.train run \\
        --config configs/qlora/r16-e2.toml --data data/finetune --out runs/finetune-r16-e2
    uv run python -m bist_harness.finetune.train bundle --data data/finetune \\
        --config configs/qlora/r16-e2.toml --config configs/qlora/r32-e3.toml \\
        --out runs/finetune-bundle-<id>.zip
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import importlib
import json
import platform
import random
import subprocess
import sys
import time
import tomllib
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bist_harness.finetune.record import TrainingRecord, read_jsonl

# Task 7 chooses the base model; until then the desktop configs hold this value.
BASE_MODEL_PLACEHOLDER = "TASK-7-CHOOSES-THE-BASE-MODEL"
TRAIN_LIBRARIES = ("torch", "transformers", "peft", "bitsandbytes", "accelerate")
IGNORE_INDEX = -100
RECORD_FILES = ("train.jsonl", "val.jsonl", "test.jsonl")
BUNDLE_DATA_FILES = (*RECORD_FILES, "dev_questions.jsonl")


class TrainGroupMissingError(RuntimeError):
    """The training libraries (the ``train`` dependency group) are not installed."""


@dataclass(frozen=True)
class TrainConfig:
    base_model: str  # Hugging Face repository id
    revision: str  # the repository commit the run downloads ("main" only for a test)
    rank: int
    alpha: int
    dropout: float
    target_modules: tuple[str, ...]  # linear layer names of the language model
    learning_rate: float
    epochs: int
    batch_size: int
    grad_accum: int
    max_seq_len: int  # a longer example is left out (and counted), never cut
    seed: int = 42
    load_in_4bit: bool = True
    eval_steps: int = 50
    early_stop_patience: int = 3
    warmup_ratio: float = 0.03
    gradient_checkpointing: bool = True
    max_steps: int = 0  # 0: train for ``epochs``; otherwise stop after this many steps
    train_limit: int = 0  # 0: every training record; otherwise a seeded sample of this size
    val_limit: int = 0  # 0: every validation record; otherwise a seeded sample


_TYPES = {
    "base_model": str,
    "revision": str,
    "rank": int,
    "alpha": int,
    "dropout": float,
    "target_modules": list,
    "learning_rate": float,
    "epochs": int,
    "batch_size": int,
    "grad_accum": int,
    "max_seq_len": int,
    "seed": int,
    "load_in_4bit": bool,
    "eval_steps": int,
    "early_stop_patience": int,
    "warmup_ratio": float,
    "gradient_checkpointing": bool,
    "max_steps": int,
    "train_limit": int,
    "val_limit": int,
}


def load_config(path: Path) -> TrainConfig:
    """Read a settings file. Every setting must be written in it: none is left to a default."""
    path = Path(path)
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    names = [f.name for f in dataclasses.fields(TrainConfig)]
    unknown = sorted(set(raw) - set(names))
    if unknown:
        raise ValueError(f"{path.name}: unknown setting(s): {', '.join(unknown)}")
    missing = [name for name in names if name not in raw]
    if missing:
        raise ValueError(f"{path.name}: missing setting(s): {', '.join(missing)}")
    for name, kind in _TYPES.items():
        value = raw[name]
        ok = isinstance(value, kind) and not (kind is int and isinstance(value, bool))
        if kind is float and isinstance(value, int) and not isinstance(value, bool):
            raw[name] = float(value)
            ok = True
        if not ok:
            raise ValueError(f"{path.name}: {name} must be {kind.__name__}, got {value!r}")
    raw["target_modules"] = tuple(raw["target_modules"])
    return TrainConfig(**raw)


def config_settings(config: TrainConfig) -> dict:
    """Every setting of a run, JSON-ready, for run.json."""
    settings = dataclasses.asdict(config)
    settings["target_modules"] = list(config.target_modules)
    return settings


# --- the tool schemas as Ollama shows them ----------------------------------------------
def _go_any(value):
    """A JSON value Go decoded into ``any``: its objects marshal again with sorted keys."""
    if isinstance(value, dict):
        return {key: _go_any(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_go_any(item) for item in value]
    return value


def _ollama_property(prop: dict) -> dict:
    """``api.ToolProperty``: anyOf, type, items, description, enum, properties, required."""
    out: dict = {}
    if prop.get("anyOf"):
        out["anyOf"] = [_ollama_property(p) for p in prop["anyOf"]]
    kind = prop.get("type")
    if kind:
        types = [kind] if isinstance(kind, str) else list(kind)
        out["type"] = types[0] if len(types) == 1 else types
    if prop.get("items") is not None:
        out["items"] = _go_any(prop["items"])
    if prop.get("description"):
        out["description"] = prop["description"]
    if prop.get("enum"):
        out["enum"] = _go_any(prop["enum"])
    if prop.get("properties") is not None:
        out["properties"] = {k: _ollama_property(v) for k, v in prop["properties"].items()}
    if prop.get("required"):
        out["required"] = list(prop["required"])
    return out


def _ollama_tool(tool: dict) -> dict:
    function = tool.get("function") or {}
    params = function.get("parameters") or {}
    shown_params: dict = {"type": params.get("type", "")}
    if params.get("$defs") is not None:
        shown_params["$defs"] = _go_any(params["$defs"])
    if params.get("items") is not None:
        shown_params["items"] = _go_any(params["items"])
    if params.get("required"):
        shown_params["required"] = list(params["required"])
    properties = params.get("properties")
    shown_params["properties"] = (
        None
        if properties is None
        else {name: _ollama_property(prop) for name, prop in properties.items()}
    )
    shown_function: dict = {"name": function.get("name", "")}
    if function.get("description"):
        shown_function["description"] = function["description"]
    shown_function["parameters"] = shown_params
    shown: dict = {"type": tool.get("type", "")}
    if tool.get("items") is not None:
        shown["items"] = _go_any(tool["items"])
    shown["function"] = shown_function
    text = json.dumps(shown, ensure_ascii=False)
    escaped = [c for c in ("<", ">", "&", "\u2028", "\u2029") if c in text]
    if escaped:
        raise ValueError(
            f"tool {shown_function['name']!r}: Go's JSON encoder would escape {escaped!r}, "
            "so the chat template cannot render it as Ollama does"
        )
    return shown


def ollama_tools(tools: Sequence[dict]) -> list[dict]:
    """The tool schemas as Ollama (v0.40.16) hands them to the model's renderer.

    Ollama decodes each tool into ``api.Tool`` and marshals it again: fields come in the
    struct order (``required`` before ``properties``), fields the structs do not have
    (``additionalProperties``, ``default``, ``pattern`` ...) are dropped, a value typed
    ``any`` (``items``, ``enum``) has its object keys sorted, and a one-element type list
    becomes a string. The qwen3.5 renderer then writes it with ``", "``/``": "``
    separators, which is what the Hugging Face template's ``tojson`` writes.
    """
    return [_ollama_tool(tool) for tool in tools]


# --- chat examples ----------------------------------------------------------------------
def render_example(record: TrainingRecord, tokenizer) -> tuple[str, str]:
    """``(prompt, completion)`` text of one record with the tokenizer's chat template.

    The prompt is what the harness sends (thinking off, as the client asks Ollama); the
    completion is the target turn as the template renders it after that prompt.
    """
    tools = ollama_tools(record.tools) or None
    prompt = tokenizer.apply_chat_template(
        record.messages,
        tools=tools,
        add_generation_prompt=True,
        tokenize=False,
        enable_thinking=False,
    )
    full = tokenizer.apply_chat_template(
        [*record.messages, record.target], tools=tools, tokenize=False, enable_thinking=False
    )
    if not full.startswith(prompt):
        raise ValueError(
            f"{record.record_id}: the chat template renders the prompt differently once the "
            "target turn is added; the loss mask would be wrong"
        )
    return prompt, full[len(prompt) :]


def to_chat_examples(records: Sequence[TrainingRecord], tokenizer) -> list[dict]:
    """Token ids and labels of every record; every prompt token is masked (-100).

    Prompt and completion are tokenized apart, as at inference: Ollama tokenizes the
    prompt and the model writes the reply token by token after it.
    """
    examples = []
    for record in records:
        prompt, completion = render_example(record, tokenizer)
        prompt_ids = list(tokenizer(prompt, add_special_tokens=False)["input_ids"])
        target_ids = list(tokenizer(completion, add_special_tokens=False)["input_ids"])
        ids = prompt_ids + target_ids
        examples.append(
            {
                "record_id": record.record_id,
                "turn": record.turn,
                "input_ids": ids,
                "labels": [IGNORE_INDEX] * len(prompt_ids) + target_ids,
                "attention_mask": [1] * len(ids),
                "prompt_tokens": len(prompt_ids),
            }
        )
    return examples


# --- the training run -------------------------------------------------------------------
def require_train_group() -> dict:
    """Import the training libraries, or stop with what to install."""
    modules = {}
    for name in TRAIN_LIBRARIES:
        try:
            modules[name] = importlib.import_module(name)
        except ImportError as exc:
            raise TrainGroupMissingError(
                f"the training libraries are not installed ({name}: {exc}); run "
                "`uv sync --group train` and start the script with `uv run --group train`"
            ) from None
    return modules


def _sample(records: list[TrainingRecord], limit: int, seed: int) -> list[TrainingRecord]:
    if not limit or limit >= len(records):
        return records
    chosen = sorted(random.Random(seed).sample(range(len(records)), limit))
    return [records[i] for i in chosen]


def _lora_targets(model, names: Sequence[str]):
    """Only the language model's layers: a vision tower's projections stay frozen."""
    has_language_model = any(".language_model." in f".{name}." for name, _ in model.named_modules())
    if not has_language_model:
        return list(names)
    return r".*\.language_model\..*\.(" + "|".join(names) + r")$"


def _load_base(base_model: str, revision: str, **kwargs):
    from transformers import AutoConfig, AutoModelForCausalLM, AutoModelForImageTextToText

    config = AutoConfig.from_pretrained(base_model, revision=revision)
    multimodal = any(a.endswith("ForConditionalGeneration") for a in config.architectures or [])
    loader = AutoModelForImageTextToText if multimodal else AutoModelForCausalLM
    return loader.from_pretrained(base_model, revision=revision, **kwargs)


class _Examples:
    def __init__(self, examples: list[dict]):
        self.items = [
            {k: e[k] for k in ("input_ids", "labels", "attention_mask")} for e in examples
        ]

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> dict:
        return self.items[index]


def _collator(pad_id: int):
    import torch

    def collate(batch: list[dict]) -> dict:
        width = max(len(item["input_ids"]) for item in batch)
        out = {"input_ids": [], "labels": [], "attention_mask": []}
        for item in batch:
            gap = width - len(item["input_ids"])
            out["input_ids"].append(item["input_ids"] + [pad_id] * gap)
            out["labels"].append(item["labels"] + [IGNORE_INDEX] * gap)
            out["attention_mask"].append(item["attention_mask"] + [0] * gap)
        return {k: torch.tensor(v, dtype=torch.long) for k, v in out.items()}

    return collate


def _write_loss_csv(log_history: list[dict], path: Path) -> None:
    columns = ("step", "epoch", "train_loss", "eval_loss", "learning_rate", "grad_norm")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for entry in log_history:
            if "loss" not in entry and "eval_loss" not in entry:
                continue
            writer.writerow(
                [
                    entry.get("step"),
                    entry.get("epoch"),
                    entry.get("loss", ""),
                    entry.get("eval_loss", ""),
                    entry.get("learning_rate", ""),
                    entry.get("grad_norm", ""),
                ]
            )


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _resolved_commit(repo_id: str, revision: str) -> str | None:
    """The commit of the downloaded files (the cache folder is named after it)."""
    from huggingface_hub import try_to_load_from_cache

    cached = try_to_load_from_cache(repo_id, "config.json", revision=revision)
    return Path(cached).parent.name if isinstance(cached, str) else None


def _versions(modules: dict) -> dict:
    versions = {name: getattr(module, "__version__", "?") for name, module in modules.items()}
    torch = modules["torch"]
    versions["python"] = platform.python_version()
    versions["cuda"] = torch.version.cuda
    return versions


def train(config: TrainConfig, data_dir: Path, out_dir: Path) -> dict:
    """Train a LoRA adapter on ``data_dir``'s train split; return what run.json holds.

    Writes ``out_dir/adapter/`` (the best adapter by validation loss), ``loss.csv`` and
    ``run.json`` (settings, library versions, data hashes, time, peak VRAM, best step).
    Validation loss is measured every ``eval_steps``; training stops early after
    ``early_stop_patience`` evaluations without improvement.
    """
    if config.base_model == BASE_MODEL_PLACEHOLDER:
        raise ValueError(
            "base_model is still the placeholder: Task 7 chooses the base model; write its "
            "Hugging Face id and revision into the config first"
        )
    modules = require_train_group()
    return _train(config, Path(data_dir), Path(out_dir), modules)


def _train(config: TrainConfig, data_dir: Path, out_dir: Path, modules: dict) -> dict:
    torch = modules["torch"]
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoTokenizer,
        BitsAndBytesConfig,
        EarlyStoppingCallback,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    started = time.perf_counter()
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    set_seed(config.seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    splits = {name: read_jsonl(data_dir / f"{name}.jsonl") for name in ("train", "val", "test")}
    train_records = _sample(splits["train"], config.train_limit, config.seed)
    val_records = _sample(splits["val"], config.val_limit, config.seed)

    tokenizer = AutoTokenizer.from_pretrained(config.base_model, revision=config.revision)
    examples = {
        "train": to_chat_examples(train_records, tokenizer),
        "val": to_chat_examples(val_records, tokenizer),
    }
    # the longest turn of the whole data set, sampled or not: the export's num_ctx
    longest = max(
        len(e["input_ids"])
        for records in splits.values()
        for e in to_chat_examples(records, tokenizer)
    )
    dropped = {
        split: [e["record_id"] for e in rows if len(e["input_ids"]) > config.max_seq_len]
        for split, rows in examples.items()
    }
    kept = {
        split: [e for e in rows if len(e["input_ids"]) <= config.max_seq_len]
        for split, rows in examples.items()
    }

    cuda = torch.cuda.is_available()
    if cuda:
        torch.cuda.reset_peak_memory_stats()
    bf16 = cuda and torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if bf16 else torch.float16
    quantization = None
    if config.load_in_4bit:
        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype,
        )
    model = _load_base(
        config.base_model,
        config.revision,
        quantization_config=quantization,
        dtype=dtype,
        device_map={"": 0} if cuda else None,
    )
    model.config.use_cache = False
    if config.load_in_4bit:
        model = prepare_model_for_kbit_training(
            model,
            use_gradient_checkpointing=config.gradient_checkpointing,
            gradient_checkpointing_kwargs={"use_reentrant": False},
        )
    elif config.gradient_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
    lora = LoraConfig(
        r=config.rank,
        lora_alpha=config.alpha,
        lora_dropout=config.dropout,
        target_modules=_lora_targets(model, config.target_modules),
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora)
    trainable, total = model.get_nb_trainable_parameters()

    args = TrainingArguments(
        output_dir=str(out_dir / "checkpoints"),
        per_device_train_batch_size=config.batch_size,
        per_device_eval_batch_size=config.batch_size,
        gradient_accumulation_steps=config.grad_accum,
        learning_rate=config.learning_rate,
        num_train_epochs=config.epochs,
        max_steps=config.max_steps if config.max_steps else -1,
        warmup_steps=config.warmup_ratio,
        lr_scheduler_type="cosine",
        logging_steps=1,
        eval_strategy="steps",
        eval_steps=config.eval_steps,
        save_strategy="steps",
        save_steps=config.eval_steps,
        save_total_limit=2,
        save_only_model=True,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        bf16=bf16,
        fp16=cuda and not bf16,
        gradient_checkpointing=config.gradient_checkpointing,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="paged_adamw_8bit" if config.load_in_4bit else "adamw_torch",
        seed=config.seed,
        data_seed=config.seed,
        report_to="none",
        remove_unused_columns=False,
        dataloader_num_workers=0,
    )
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else 0
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=_Examples(kept["train"]),
        eval_dataset=_Examples(kept["val"]),
        data_collator=_collator(pad_id),
        callbacks=[EarlyStoppingCallback(early_stopping_patience=config.early_stop_patience)],
    )
    trainer.train()

    adapter_dir = out_dir / "adapter"
    trainer.model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)
    state = trainer.state
    _write_loss_csv(state.log_history, out_dir / "loss.csv")
    eval_losses = [e["eval_loss"] for e in state.log_history if "eval_loss" in e]
    planned = state.max_steps
    result = {
        "config": config_settings(config),
        "base_model": {
            "repo_id": config.base_model,
            "revision": config.revision,
            "resolved_commit": _resolved_commit(config.base_model, config.revision),
        },
        "data": {
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "files": {name: manifest["files"][name]["sha256"] for name in RECORD_FILES},
            "snapshot_id": manifest.get("snapshot_id"),
            "seed": manifest.get("seed"),
        },
        "examples": {split: len(rows) for split, rows in kept.items()},
        "examples_by_turn": {
            split: {
                turn: sum(1 for e in rows if e["turn"] == turn)
                for turn in ("intent", "tool_call", "explanation")
            }
            for split, rows in kept.items()
        },
        "dropped_too_long": dropped,
        "max_example_tokens": longest,
        "trainable_parameters": trainable,
        "total_parameters": total,
        "steps": state.global_step,
        "planned_steps": planned,
        "stopped_early": state.global_step < planned,
        "best_step": getattr(state, "best_global_step", None),
        "best_eval_loss": state.best_metric,
        "first_eval_loss": eval_losses[0] if eval_losses else None,
        "last_train_loss": next(
            (e["loss"] for e in reversed(state.log_history) if "loss" in e), None
        ),
        "precision": "bf16" if bf16 else ("fp16" if cuda else "fp32"),
        "wall_time_s": round(time.perf_counter() - started, 1),
        "peak_vram_gb": {
            "allocated": round(torch.cuda.max_memory_allocated() / 2**30, 3) if cuda else None,
            "reserved": round(torch.cuda.max_memory_reserved() / 2**30, 3) if cuda else None,
        },
        "gpu": torch.cuda.get_device_name(0) if cuda else None,
        "versions": _versions(modules),
        "git_commit": _git_commit(),
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    with (out_dir / "run.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return result


# --- the bundle for the GPU machine -----------------------------------------------------
BUNDLE_README = """# İnce ayar paketi (fine-tuning bundle)

Bu paket eğitim verisini ve ayarlarını GPU makinesine taşır; veri git dışıdır.
`BUNDLE.json` her dosyanın SHA-256'sını tutar.

1. Depoyu güncelle ve eğitim kütüphanelerini kur:

       git pull
       uv sync --group train

2. Paketi deponun köküne aç (dosyalar `data/finetune/` ve `configs/qlora/` altına gider).
3. Önce 20 adımlık deneme (EC-006, `laptop-trial`), sonra paketteki ayarlar:

{runs}

4. Çıktılar `runs/finetune-<ayar>/` altındadır: `adapter/`, `loss.csv`, `run.json`.
   Dizüstüne yalnız bunları geri getir (`checkpoints/` gerekmez).

Ayrıntılar: `docs/finetune.md`, "Eğitim ve dışa aktarma (RTX 5070)".
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle(data_dir: Path, configs: Sequence[Path], out: Path) -> dict:
    """Zip the record files, dev questions, manifest, settings files and a README.

    Every data file must match the SHA-256 the manifest recorded; otherwise nothing is
    written. Returns the bundle's index (``BUNDLE.json``).
    """
    data_dir, out = Path(data_dir), Path(out)
    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries: dict[str, Path] = {}
    for name in BUNDLE_DATA_FILES:
        path = data_dir / name
        recorded = manifest.get("files", {}).get(name, {}).get("sha256")
        if not path.is_file() or _sha256(path) != recorded:
            raise ValueError(f"{name} is missing or does not match the manifest's SHA-256")
        entries[f"data/finetune/{name}"] = path
    entries["data/finetune/manifest.json"] = manifest_path
    for config in configs:
        load_config(config)  # a broken settings file is not shipped
        entries[f"configs/qlora/{Path(config).name}"] = Path(config)
    stems = dict.fromkeys(["laptop-trial", *(Path(c).stem for c in configs)])
    runs = "\n".join(
        "       uv run --group train python -m bist_harness.finetune.train run "
        f"--config configs/qlora/{stem}.toml --data data/finetune --out runs/finetune-{stem}"
        for stem in stems
    )
    readme = BUNDLE_README.replace("{runs}", runs).encode("utf-8")
    index = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "snapshot_id": manifest.get("snapshot_id"),
        "files": {name: _sha256(path) for name, path in sorted(entries.items())},
    }
    index["files"]["README.md"] = hashlib.sha256(readme).hexdigest()
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(entries.items()):
            archive.write(path, name)
        archive.writestr("README.md", readme)
        archive.writestr("BUNDLE.json", json.dumps(index, indent=2) + "\n")
    return index


# --- command line -----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QLoRA training and the training bundle")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="train one adapter")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--data", type=Path, default=Path("data/finetune"))
    run.add_argument("--out", type=Path, required=True)
    pack = commands.add_parser("bundle", help="zip data and settings for the GPU machine")
    pack.add_argument("--data", type=Path, default=Path("data/finetune"))
    pack.add_argument("--config", type=Path, action="append", required=True)
    pack.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            result = train(load_config(args.config), args.data, args.out)
            print(
                f"[train] {result['steps']} steps, best eval loss {result['best_eval_loss']} "
                f"at step {result['best_step']}, {result['wall_time_s']} s, peak VRAM "
                f"{result['peak_vram_gb']['allocated']} GB; written to {args.out}",
                flush=True,
            )
        else:
            index = bundle(args.data, args.config, args.out)
            print(f"[bundle] {len(index['files'])} files written to {args.out}", flush=True)
    except (TrainGroupMissingError, ValueError) as exc:
        print(f"[train] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
