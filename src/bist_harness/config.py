"""Runtime settings.

The LLM endpoint is always an Ollama-compatible server the student controls:
the laptop's own Ollama by default, or a private machine set through
``BIST_LLM_BASE_URL``. No cloud AI provider is ever contacted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:9b-q4_K_M"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_dotenv(path: Path) -> dict[str, str]:
    """Parse a minimal KEY=VALUE file; blank lines and # comments are ignored."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    llm_base_url: str = DEFAULT_BASE_URL
    llm_model: str = DEFAULT_MODEL
    temperature: float = 0.0
    seed: int = 42
    data_dir: Path = Path("data")

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from the environment, falling back to ./.env, then defaults."""
        dotenv = _read_dotenv(Path.cwd() / ".env")

        def get(key: str) -> str | None:
            return os.environ.get(key) or dotenv.get(key) or None

        base_url = (get("BIST_LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        data_dir = get("BIST_DATA_DIR")
        return cls(
            llm_base_url=base_url,
            llm_model=get("BIST_LLM_MODEL") or DEFAULT_MODEL,
            data_dir=Path(data_dir) if data_dir else REPO_ROOT / "data",
        )
