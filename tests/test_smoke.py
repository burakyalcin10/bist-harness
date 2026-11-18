"""Project-level guarantees: configuration defaults and the no-cloud-AI rule."""

from bist_harness.config import Settings

from .conftest import REPO_ROOT

ENV_KEYS = ("BIST_LLM_BASE_URL", "BIST_LLM_MODEL", "BIST_DATA_DIR")


def test_settings_defaults(monkeypatch, tmp_path):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    s = Settings.from_env()
    assert s.llm_base_url == "http://127.0.0.1:11434"
    assert s.llm_model == "qwen3.5:9b-q4_K_M"
    assert (s.temperature, s.seed) == (0.0, 42)


def test_settings_reads_dotenv_from_working_directory(monkeypatch, tmp_path):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "# comment\nBIST_LLM_MODEL=from-dotenv\nBIST_LLM_BASE_URL=https://example.invalid/\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    s = Settings.from_env()
    assert s.llm_model == "from-dotenv"
    assert s.llm_base_url == "https://example.invalid"  # trailing slash stripped


def test_environment_variable_wins_over_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("BIST_LLM_MODEL=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BIST_LLM_MODEL", "from-env")
    assert Settings.from_env().llm_model == "from-env"


def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BIST_DATA_DIR", str(tmp_path / "elsewhere"))
    assert Settings.from_env().data_dir == tmp_path / "elsewhere"


def test_no_cloud_ai_dependencies():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    for name in ("openai", "anthropic", "google-generativeai", "cohere", "mistralai"):
        assert name not in text


def test_llm_api_defaults_to_native_ollama(monkeypatch, tmp_path):
    monkeypatch.delenv("BIST_LLM_API", raising=False)
    monkeypatch.chdir(tmp_path)
    assert Settings.from_env().llm_api == "ollama"


def test_llm_api_can_select_the_openai_compatible_route(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BIST_LLM_API", "OpenAI")
    assert Settings.from_env().llm_api == "openai"


def test_unknown_llm_api_is_refused(monkeypatch, tmp_path):
    import pytest

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BIST_LLM_API", "grpc")
    with pytest.raises(ValueError, match="BIST_LLM_API"):
        Settings.from_env()
