"""Export a trained adapter to Ollama: merge, GGUF, Modelfile, ``ollama create``.

1. The adapter is merged into the base model in its own precision (``merge_adapter``).
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

    merged = merge_adapter(adapter_dir, base_model, out_dir / "merged", revision=revision)
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
