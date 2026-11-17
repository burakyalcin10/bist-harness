# Sprint 1 — Temel ve İnce Hat: Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bu gecenin sonunda repo ve ortam kurulu, tasarım belgesi onaylı, temel model ölçülerek seçilmiş ve tek senaryoda (ASELS, teknik dönüş) "soru → araç çağrısı → araç çıktısına dayalı cevap → sayı denetimi" hattı çalışıyor olsun.

**Architecture:** Deterministik hesaplar `src/bist_harness` paketinde düz Python fonksiyonlarıdır ve resmî `mcp` SDK'sı (FastMCP, stdio) ile MCP aracı olarak sunulur. LLM'e Ollama'nın yerel `/api/chat` uç noktasından, ortam değişkeniyle ayarlanan bir adres üzerinden erişilir (varsayılan dizüstündeki Ollama, isteğe bağlı uzak RTX 5070). İnce hat çalıştırıcısı MCP istemcisi olarak bağlanır, modelin araç çağırmasına izin verir ve cevaptaki her sayıyı araç çıktısıyla karşılaştırır.

**Tech Stack:** Python 3.12 (`uv`), pandas, numpy, yfinance, matplotlib, pyarrow, httpx, mcp, pydantic; geliştirme: pytest, ruff.

**Spec:** `Engineering Economics Project_2026_CSE-481.pdf` (§ numaraları), `Hoca Teams Duyuruları.md`, ve Task 3'te yazılan `docs/superpowers/specs/2026-11-17-bist-harness-design.md`. Kartlar: Notion "CSE-481 | Görevler", Sprint S1 (EC-001, 003, 004, 005, 007, 008, 009, 010).

## Global Constraints

- Repo `C:\Users\burak\Projects\bist-harness` içinde kurulur (OneDrive dışında; `lokal` ile aynı düzen). Ders belgeleri `C:\Users\burak\OneDrive\Masaüstü\econproject` içinde kalır.
- Python 3.12, `uv`. Bütün testler tek komutla: `uv run pytest -q`.
- Kod, yorumlar, README ve komut satırı çıktıları İngilizce; plan ve tasarım belgeleri Türkçe.
- Bağımlılıklarda ve kodda bulut yapay zekâ SDK'sı ya da adresi olmaz (`openai`, `anthropic`, `google-generativeai`, `cohere`, `mistralai`). LLM'e yalnız Ollama uç noktasından erişilir.
- Uzak sunucu adresi, tailnet adı ve IP'ler repoya, belgelere ve günlüklere yazılmaz. Yalnız `BIST_LLM_BASE_URL` ortam değişkeninde ya da git'e girmeyen `.env` dosyasında durur.
- LLM çağrıları: `temperature=0`, `seed=42`, `think=false`.
- Fiyat verisi `yfinance`, `auto_adjust=True`; Yahoo sembolü `<TICKER>.IS` (hocanın betikleri).
- Araç çıktılarındaki yüzdeler 2 ondalığa yuvarlanmış olarak döner; model sayıyı olduğu gibi aktarır.
- Eylem etiketleri yalnız şu sekizi: `HOLD`, `WATCH`, `INVESTIGATE`, `POTENTIAL_CATCH_UP_CANDIDATE`, `TECHNICAL_REVERSAL_CANDIDATE`, `FUNDAMENTAL_IMPROVEMENT_CANDIDATE`, `REJECT_SIGNAL`, `ANALYSIS_UNSAFE`.
- Çalıştırılabilir her betiğin başında: `CSE-481 Engineering Economics — Educational use only. Not investment advice.`
- Her görev commit ile biter; commit mesajları İngilizce (`feat:`, `test:`, `docs:`, `chore:`).

## Review Focus

1. **Uzak sunucu kapalı ya da 403/502 dönüyor.** `OllamaClient` anlaşılır bir `LLMUnavailableError` fırlatır; model ölçümü o modeli "unreachable" yazar ve devam eder. Test: Task 5.
2. **Model araç çağrısını `tool_calls` alanı yerine metin içinde JSON olarak veriyor.** `parse_tool_calls` metinden de ayıklar; ayıklanamayan çağrı "invalid" sayılır. Test: Task 5.
3. **yfinance boş tablo ya da MultiIndex sütun döndürüyor.** `load_stock_data` sütunları düzleştirir; tablo boşsa `DataUnavailableError`. Test: Task 6.
4. **Cevapta Türkçe sayı biçimi var** (`%62,5`, `1.234,56`). `extract_numbers` iki biçimi de okur; tarihleri ve `E1` gibi kimlikleri sayı saymaz. Test: Task 6.
5. **Evrende olmayan hisse soruluyor** (`GARAN`). Araç istisna fırlatmaz; `{"error": {"code": "UNKNOWN_TICKER", ...}}` döndürür. Test: Task 6.

## Dosya yapısı

```
bist-harness/
  pyproject.toml  uv.lock  README.md  .gitignore  .env.example
  data/reference/universe.csv            # commit edilir
  data/cache/                            # gitignore: parquet anlık görüntüleri
  runs/                                  # gitignore: çalıştırma günlükleri
  reference/instructor/                  # hocanın iki betiği, değiştirilmeden
  docs/ai_usage_log.md
  docs/superpowers/specs/2026-11-17-bist-harness-design.md
  docs/superpowers/plans/2026-11-17-sprint-1-temel-ve-ince-hat.md
  docs/results/2026-11-17-model-bakeoff.md
  src/bist_harness/
    config.py            # Settings
    errors.py            # LLMUnavailableError, DataUnavailableError
    universe.py          # load_universe, is_in_universe
    data/market.py       # load_stock_data
    tools/schemas.py     # TOOL_SCHEMAS (15), ACTIONS (8), to_ollama_tools
    tools/reversal.py    # bollinger_lower_touch_summary
    llm/client.py        # OllamaClient, ChatResult, ToolCall, parse_tool_calls
    mcp_server/server.py # FastMCP: get_stock_history, detect_reversal_events
    eval/number_check.py # extract_numbers, numbers_match, find_unsupported_numbers
    bakeoff/prompt.py  bakeoff/cases.jsonl  bakeoff/score.py  bakeoff/run.py
    slice/run_slice.py
  tests/
```

## Bu gecenin sırası ve süre hedefleri

| Görev | Kart | Hedef süre | Sana düşen |
| --- | --- | --- | --- |
| 0 Hocaya mesaj | EC-001, EC-008 | 5 dk | Mesajı gönder |
| 1 Repo ve ortam | EC-003 | 40 dk | Repo konumunu onayla |
| 2 Yapay zekâ kullanım günlüğü | EC-007 | 10 dk | "Nasıl doğruladım" sütunu |
| 3 Tasarım belgesi ve araç şemaları | EC-004 | 75 dk | K1–K3 kararları, onay |
| 4 Evren | EC-010 | 20 dk | — |
| 5 LLM istemcisi ve model ölçümü | EC-005 | 90 dk | RTX 5070'i aç, aday modelleri sunucuya indir, modeli seç |
| 6 Uçtan uca ince hat | EC-009 | 100 dk | `numbers_match` kuralını yaz (5–10 satır) |
| 7 Sprint kapanışı | — | 15 dk | Kartları gözden geçir |

---

### Task 0: Hocaya mesaj ve proposal kartı (EC-001, EC-008)

- [ ] **Step 1 (Burak):** Ek A'daki mesajı Teams'ten hocaya gönder. Gönderim saatini EC-001 kartına yaz.
- [ ] **Step 2:** EC-008 kapalı (proposal yok). Başka iş yok.

---

### Task 1: Repo ve ortam (EC-003)

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`, `src/bist_harness/__init__.py`, `src/bist_harness/config.py`, `src/bist_harness/errors.py`
- Create: `reference/instructor/scenario2_thyao_weekday_patterns.py`, `reference/instructor/scenario3_technical_reversal_events_3_periods.py` (econproject `dersnotes/` içinden kopya)
- Test: `tests/test_smoke.py`

**Interfaces:**
- Produces: `bist_harness.config.Settings` (frozen dataclass) alanları `llm_base_url: str`, `llm_model: str`, `temperature: float`, `seed: int`, `data_dir: Path`; `Settings.from_env() -> Settings`. `bist_harness.errors.LLMUnavailableError`, `bist_harness.errors.DataUnavailableError`.

- [ ] **Step 1 (Burak):** Repo konumunu onayla: `C:\Users\burak\Projects\bist-harness`.
- [ ] **Step 2:** Klasörü oluştur, `git init`, `uv init --lib --name bist-harness --python 3.12`. Bağımlılıklar: `uv add pandas numpy yfinance matplotlib pyarrow httpx mcp pydantic`, `uv add --dev pytest ruff`.
- [ ] **Step 3: Kalan testi yaz** (`tests/test_smoke.py`)

```python
def test_settings_defaults(monkeypatch, tmp_path):
    for k in ("BIST_LLM_BASE_URL", "BIST_LLM_MODEL", "BIST_DATA_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    s = Settings.from_env()
    assert s.llm_base_url == "http://127.0.0.1:11434"
    assert s.llm_model == "qwen3.5:9b-q4_K_M"
    assert (s.temperature, s.seed) == (0.0, 42)


def test_settings_env_and_dotenv(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("BIST_LLM_MODEL=from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BIST_LLM_BASE_URL", "https://example.invalid/")
    s = Settings.from_env()
    assert s.llm_base_url == "https://example.invalid"  # trailing slash stripped
    assert s.llm_model == "from-dotenv"  # env var wins over .env when both set


def test_no_cloud_ai_dependencies():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    for name in ("openai", "anthropic", "google-generativeai", "cohere", "mistralai"):
        assert name not in text
```

- [ ] **Step 4:** `uv run pytest tests/test_smoke.py -q` → FAIL (`Settings` yok).
- [ ] **Step 5:** `Settings.from_env()` yaz. `.env` çalışma dizininden, bağımlılıksız basit bir `KEY=VALUE` okuyucuyla yüklenir; ortam değişkeni `.env`'den önce gelir. `data_dir` varsayılanı repo kökündeki `data`.
- [ ] **Step 6:** `uv run pytest tests/test_smoke.py -q` → PASS.
- [ ] **Step 7:** `.gitignore`: `.venv/`, `data/cache/`, `runs/`, `models/`, `*.gguf`, `.env`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`. `.env.example`: `BIST_LLM_BASE_URL=http://127.0.0.1:11434` ve `BIST_LLM_MODEL=qwen3.5:9b-q4_K_M`. README (İngilizce): amaç, eğitim amaçlı kullanım notu, kurulum (`uv sync`), test komutu, model adresinin nasıl ayarlandığı.
- [ ] **Step 8:** Hocanın iki betiğini `reference/instructor/` altına kopyala; bu planı ve sonraki belgeleri `docs/superpowers/` altına taşı.
- [ ] **Step 9:** `uv run ruff check .` temiz. Commit: `chore: scaffold bist-harness package and environment`.

---

### Task 2: Yapay zekâ kullanım günlüğü (EC-007)

**Files:**
- Create: `docs/ai_usage_log.md`

- [ ] **Step 1:** Günlüğü şu sütunlarla aç: `Date | Tool / model | Prompt (verbatim or summary) | Output used in the project | How I verified it | Card`. Başlıkta ders politikası alıntısı (1. hafta s. 31).
- [ ] **Step 2:** İlk kayıtlar: 17 Kasım planlama oturumu (Notion planı ve pano; sprint planı), weight-space programming araştırması (kaynak bağlantılarıyla), Task 1 iskeleti.
- [ ] **Step 3 (Burak):** Her satırın "How I verified it" hücresini kendi cümlenle doldur.
- [ ] **Step 4:** Commit: `docs: start AI usage log`.

---

### Task 3: Tasarım belgesi ve araç şemaları (EC-004)

**Files:**
- Create: `docs/superpowers/specs/2026-11-17-bist-harness-design.md`
- Create: `src/bist_harness/tools/__init__.py`, `src/bist_harness/tools/schemas.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Produces: `TOOL_SCHEMAS: dict[str, dict]` (anahtar araç adı; değer `{"description": str, "parameters": <JSON Schema object>}`), `ACTIONS: tuple[str, ...]`, `to_ollama_tools(names: Iterable[str] | None = None) -> list[dict]` (Ollama `tools` biçimi: `{"type": "function", "function": {"name", "description", "parameters"}}`).

**Araç parametreleri (v0; adlar §22'den, parametreler bu planın kararı):**

| Araç | Parametreler |
| --- | --- |
| `get_stock_history` | `ticker`, `start`, `end` |
| `get_index_history` | `index` (ör. `XU100`), `start`, `end` |
| `calculate_indicators` | `ticker`, `start`, `end`, `indicators[]` ∈ `SMA, EMA, KAMA, RSI, MACD, BOLLINGER, ATR, SUPERTREND, ICHIMOKU` |
| `detect_reversal_events` | `ticker`, `start`, `end`, `event_type` ∈ `BOLLINGER_LOWER_TOUCH, BOLLINGER_MIDDLE_TEST, BOLLINGER_UPPER_TOUCH, RSI_LOCAL_TROUGH, RSI_LOCAL_PEAK, SUPERTREND_FLIP, KAMA_TURN, ICHIMOKU_BREAKOUT, SUPPORT_RESISTANCE_TOUCH`, `forward_days` ∈ `1, 3, 5, 10` (varsayılan 5) |
| `find_support_resistance` | `ticker`, `start`, `end`, `tolerance` (varsayılan 0.015) |
| `rank_sector_relative_strength` | `sector`, `horizon_days` ∈ `5, 10, 20, 60`, `as_of` |
| `test_weekday_pattern` | `ticker`, `pattern` ∈ `WEEKDAY_MEANS, MON_WEAK_FRI_STRONG, THREE_DOWN_TWO_UP, POST_LARGE_DOWN_REVERSION, END_OF_WEEK_CONTINUATION`, `start`, `end` |
| `get_fundamental_metrics` | `ticker`, `as_of` |
| `calculate_fundamental_change` | `ticker`, `as_of`, `periods` (varsayılan 4) |
| `get_macro_context` | `start`, `end` |
| `get_news_events` | `ticker` (isteğe bağlı), `topic` (isteğe bağlı), `start`, `end` |
| `get_speech_features` | `source_id` |
| `run_backtest` | `strategy` ∈ `A_TECHNICAL, B_TECH_SECTOR, C_TECH_SECTOR_FUND, D_FULL_STRUCTURED, E_FULL_CONTEXTUAL`, `universe[]`, `start`, `end` |
| `check_data_quality` | `analysis_id` |
| `build_evidence_bundle` | `analysis_id` |

Tarihler `YYYY-MM-DD` dizgisidir. `ticker` `.IS` eki olmadan, büyük harfle.

**Tasarım belgesinin bölümleri (sabit liste):** 1 Amaç ve kapsam dışı; 2 Değişmez kurallar; 3 Katmanlar ve araç / servis / ajan ayrımı (§37); 4 Veri modeli ve point-in-time kuralları; 5 Araç sözleşmeleri (yukarıdaki tablo, çıktı alanları, hata biçimi `{"error": {"code", "message"}}`, `result_id`); 6 Durum makinesi: 17 durum ve durum başına izinli araçlar (§23); 7 Kanıt paketi ve committed evidence set (§25); 8 Kalite kapısı (§26); 9 Çıktı doğrulayıcı ve sonlu eylem kümesi; 10 Bellek ve karar günlüğü (§24, §28); 11 Model: iki makine düzeni, ince ayar, weight-space programming yan yolu; 12 Değerlendirme (§30); 13 Açık sorular.

- [ ] **Step 1: Kalan testi yaz** (`tests/test_schemas.py`)

```python
SPEC_TOOLS = {
    "get_stock_history",
    "get_index_history",
    "calculate_indicators",
    "detect_reversal_events",
    "find_support_resistance",
    "rank_sector_relative_strength",
    "test_weekday_pattern",
    "get_fundamental_metrics",
    "calculate_fundamental_change",
    "get_macro_context",
    "get_news_events",
    "get_speech_features",
    "run_backtest",
    "check_data_quality",
    "build_evidence_bundle",
}


def test_tool_names_match_spec():
    assert set(TOOL_SCHEMAS) == SPEC_TOOLS


def test_actions_are_the_eight_spec_labels_in_order():
    assert ACTIONS == (
        "HOLD",
        "WATCH",
        "INVESTIGATE",
        "POTENTIAL_CATCH_UP_CANDIDATE",
        "TECHNICAL_REVERSAL_CANDIDATE",
        "FUNDAMENTAL_IMPROVEMENT_CANDIDATE",
        "REJECT_SIGNAL",
        "ANALYSIS_UNSAFE",
    )


def test_ollama_tool_shape():
    for t in to_ollama_tools():
        f = t["function"]
        assert t["type"] == "function" and f["description"]
        assert f["parameters"]["type"] == "object"
        assert f["parameters"].get("additionalProperties") is False
        assert all(p.get("description") for p in f["parameters"]["properties"].values())


def test_subset_selection():
    assert [t["function"]["name"] for t in to_ollama_tools(["run_backtest"])] == ["run_backtest"]
```

- [ ] **Step 2:** Test FAIL → `schemas.py` yaz → test PASS.
- [ ] **Step 3:** Tasarım belgesini yukarıdaki 13 bölümle yaz.
- [ ] **Step 4 (Burak): üç karar.**
  - **K1 Harness kontrol biçimi.** (a) Durum geçişlerini kod yönetir; model her durumda yalnız izinli araçlardan seçer ve açıklamayı yazar. (b) Model bir sonraki durumu da izinli geçişler arasından seçer. Öneri (a): hatalı araç çağrısı ve adım atlama riskini düşürür; "Agent thinks. Harness controls." ile uyumlu. (b) daha esnek ama küçük modelde daha kırılgan.
  - **K2 Cevap dili.** Sorunun dili / hep İngilizce / hep Türkçe. Öneri: sorunun dili; ince ayar verisi iki dilde üretilir.
  - **K3 Araç çıktısı.** Özet istatistik ve `result_id` / ham seri. Öneri: özet; küçük modelin bağlamını korur ve sayı denetimini kolaylaştırır.
- [ ] **Step 5 (Burak):** Belgeyi oku, düzelt, onayla. Onay tarihi belgenin başına yazılır.
- [ ] **Step 6:** Commit: `docs: add system design and v0 tool schemas`.

---

### Task 4: Evren (EC-010)

**Files:**
- Create: `data/reference/universe.csv`, `src/bist_harness/universe.py`
- Test: `tests/test_universe.py`

**Interfaces:**
- Produces: `load_universe(path: Path | None = None) -> pandas.DataFrame` (sütunlar tam olarak `ticker, yahoo_symbol, sector`), `is_in_universe(ticker: str) -> bool` (büyük-küçük harf ve `.IS` eki duyarsız).

`universe.csv` içeriği (§5; başlık satırı `ticker,yahoo_symbol,sector`, `yahoo_symbol = ticker + ".IS"`):

```
ASELS  Technology / Defense          TUPRS  Petroleum / Refining
BIMAS  Retail Trade                  THYAO  Transportation / Airlines
AKBNK  Banking                       KCHOL  Holding / Investment
EREGL  Basic Metals / Steel          TCELL  Telecommunications
CCOLA  Food & Beverage               MGROS  Retail Trade
SASA   Chemicals / Plastics          TRALT  Mining
FROTO  Automotive                    ENKAI  Construction
PGSUS  Transportation / Airlines     MPARK  Healthcare
EKGYO  Real Estate Investment Trust  GUBRF  Chemicals / Fertilizer
TURSG  Insurance                     ENJSA  Electric Utilities
TTKOM  Telecommunications            OYAKC  Cement
AKSEN  Electric Utilities            ISMEN  Brokerage / Capital Markets
ARCLK  Durables / Machinery          ECILC  Healthcare / Pharmaceuticals
MAVI   Retail / Apparel              PETKM  Petrochemicals
TOASO  Automotive                    KRDMD  Basic Metals / Steel
```

- [ ] **Step 1: Kalan testi yaz**

```python
def test_universe_shape():
    u = load_universe()
    assert list(u.columns) == ["ticker", "yahoo_symbol", "sector"]
    assert len(u) == 30 and u["ticker"].is_unique
    assert (u["yahoo_symbol"] == u["ticker"] + ".IS").all()
    assert u["sector"].str.len().gt(0).all()


def test_universe_spot_checks():
    s = load_universe().set_index("ticker")["sector"]
    assert s["ASELS"] == "Technology / Defense"
    assert s["KRDMD"] == "Basic Metals / Steel"
    assert s["TRALT"] == "Mining"


def test_is_in_universe():
    assert is_in_universe("asels") and is_in_universe("THYAO.IS")
    assert not is_in_universe("GARAN")
```

- [ ] **Step 2:** FAIL → CSV ve `universe.py` → PASS.
- [ ] **Step 3 (ağ gerekir):** 30 sembolün her biri için `yfinance` ile son 5 günün verisini iste; boş dönen sembolleri EC-010 kartına yaz. Dondurma tarihi ve kaynak README'ye eklenir.
- [ ] **Step 4:** Commit: `feat: freeze 30-stock study universe`.

---

### Task 5: LLM istemcisi ve model ölçümü (EC-005) — RTX 5070 açık olmalı

**Files:**
- Create: `src/bist_harness/llm/__init__.py`, `src/bist_harness/llm/client.py`
- Create: `src/bist_harness/bakeoff/__init__.py`, `prompt.py`, `cases.jsonl`, `score.py`, `run.py`
- Create: `docs/results/2026-11-17-model-bakeoff.md`
- Test: `tests/test_llm_client.py`, `tests/test_bakeoff_score.py`

**Interfaces:**
- Consumes: `Settings` (Task 1), `to_ollama_tools` (Task 3), `load_universe` (Task 4).
- Produces:

```python
@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass(frozen=True)
class ChatResult:
    content: str
    tool_calls: tuple[ToolCall, ...]
    prompt_tokens: int
    completion_tokens: int
    total_duration_s: float
    eval_tokens_per_s: float | None
    raw: dict


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_s: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ): ...
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        temperature: float = 0.0,
        seed: int = 42,
        think: bool = False,
        response_format: dict | None = None,
        num_ctx: int | None = None,
    ) -> ChatResult: ...
    def list_models(self) -> list[str]: ...  # GET /api/tags


def parse_tool_calls(message: dict) -> tuple[ToolCall, ...]: ...


@dataclass(frozen=True)
class CaseScore:
    tool_ok: bool
    args_ok: bool
    no_tool_ok: bool | None  # None unless the case expects no tool call


def score_case(expected: dict, calls: Sequence[ToolCall]) -> CaseScore: ...
```

- İstek: `POST {base_url}/api/chat`, gövde `{"model", "messages", "tools", "stream": false, "think", "format", "options": {"temperature", "seed", "num_ctx"}}`. Yanıt alanları: `message.content`, `message.tool_calls[].function.{name, arguments}`, `prompt_eval_count`, `eval_count`, `total_duration`, `eval_duration` (nanosaniye).
- `parse_tool_calls` sırası: önce `message.tool_calls`; yoksa `content` içinde `<tool_call>…</tool_call>`, ```` ```json ```` çiti ya da çıplak `{"name": …, "arguments": …}` nesnesi.
- `score_case`: yalnız ilk çağrı sayılır. `tool_ok`: ad eşit. `args_ok`: `expected["args"]` içindeki her anahtar, normalleştirmeden sonra eşit (ticker büyük harf ve `.IS` eki atılmış; tarihler ISO). `expected["expect"] == "no_tool"` ise `no_tool_ok = (len(calls) == 0)`.

**Sistem istemi (`bakeoff/prompt.py`, sabit metin):**

```
You are the analysis assistant of an educational BIST 100 research system.
You never calculate, estimate or guess numbers yourself.
If a question needs market, fundamental, macro or news data, call exactly one of the provided tools with correct arguments.
If the user asks for investment advice or a price prediction, do not call a tool; say that the system is educational and cannot give advice.
Tickers are written without the ".IS" suffix. Dates are YYYY-MM-DD. Today is 2026-11-17.
Study universe: {comma-separated 30 tickers}
```

**`cases.jsonl` (30 satır):** her satır `{"id", "lang", "question", "tool", "args"}` ya da `{"id", "lang", "question", "expect": "no_tool"}`. Dağılım: dört senaryonun her birinden 5 (catch-up → `rank_sector_relative_strength`; takvim → `test_weekday_pattern`; teknik dönüş → `detect_reversal_events` / `find_support_resistance`; temel → `get_fundamental_metrics` / `calculate_fundamental_change`), diğer araçlardan 5 (`get_macro_context`, `get_news_events`, `run_backtest`, `get_stock_history`, `calculate_indicators`), araçsız 5 (yatırım tavsiyesi isteği, fiyat tahmini isteği, selamlaşma). Yarısı Türkçe, yarısı İngilizce. Örnekler:

```json
{"id": "rev-01", "lang": "tr", "question": "ASELS'te 2020 başından 2024 sonuna kadar alt Bollinger bandı dokunuşlarından sonra 5 günlük getiri nasıl olmuş?", "tool": "detect_reversal_events", "args": {"ticker": "ASELS", "event_type": "BOLLINGER_LOWER_TOUCH", "forward_days": 5, "start": "2020-01-01", "end": "2024-12-31"}}
{"id": "cal-03", "lang": "en", "question": "Does THYAO show a Monday-weak, Friday-strong pattern between 2025-01-01 and 2026-10-31?", "tool": "test_weekday_pattern", "args": {"ticker": "THYAO", "pattern": "MON_WEAK_FRI_STRONG", "start": "2025-01-01", "end": "2026-10-31"}}
{"id": "trap-02", "lang": "tr", "question": "Elimde 100 bin lira var, TUPRS alayım mı?", "expect": "no_tool"}
```

- [ ] **Step 1: Kalan testleri yaz** (`httpx.MockTransport` ile)

```python
def test_chat_sends_deterministic_options():        # body: stream False, think False,
    ...                                              # options.temperature == 0, options.seed == 42
def test_native_tool_calls_parsed():                 # message.tool_calls -> ToolCall("get_stock_history", {...})
def test_text_embedded_tool_call_parsed():           # content with ```json {"name":..., "arguments":...} ``` and <tool_call> forms
def test_plain_text_has_no_tool_calls():
def test_metrics_converted():                        # eval_count 100, eval_duration 2e9 ns -> 50.0 tok/s
def test_connection_error_raises_llm_unavailable():  # httpx.ConnectError -> LLMUnavailableError
def test_http_403_raises_llm_unavailable_with_status():

def test_score_exact_match():                        # tool_ok and args_ok
def test_score_normalises_ticker_and_suffix():       # "asels.IS" == "ASELS"
def test_score_wrong_tool():                         # tool_ok False, args_ok False
def test_score_extra_args_do_not_fail():             # actual has more keys than expected
def test_score_no_tool_case():                       # no calls -> True; one call -> False
```

- [ ] **Step 2:** FAIL → `client.py`, `score.py` → PASS. Alan adlarını Ollama API belgesinden doğrula; farklıysa bu planı ve testi düzelt.
- [ ] **Step 3:** `cases.jsonl` ve `prompt.py` yaz. `tests/test_bakeoff_score.py` içine dağılım testi ekle: 30 satır, kimlikler tekil, her `tool` `TOOL_SCHEMAS` içinde, her `args` anahtarı o aracın şemasında, 15 `tr` / 15 `en`, 5 `no_tool`.
- [ ] **Step 4:** `run.py`: `uv run python -m bist_harness.bakeoff.run --models <m1,m2,…> --out docs/results/2026-11-17-model-bakeoff.md`. Her model için 30 soruyu 15 aracın tamamı açıkken sorar; tablo sütunları `model | reachable | tool_ok % | args_ok % | no_tool_ok % | median latency (s) | tokens/s | notes`. Adres ve makine adı çıktıya yazılmaz.
- [ ] **Step 5 (Burak): adayları hazırla.** RTX 5070'i aç. Sunucuda zaten `qwen3.5:9b-q4_K_M` ve `ministral-3:8b` var. İki aday daha indir (geçit uzaktan indirmeye izin vermiyor, sunucunun başında ya da uzak masaüstünden): Qwen3.5'in 4 milyar parametreye en yakın boyutu ve başka bir aileden (Gemma, Phi ya da Llama güncel sürümü) 4 milyar civarı bir model. Etiketler indirmeden önce Ollama kitaplığından doğrulanır. Dizüstündeki Ollama 0.15.2; güncelle ve en küçük adayı oraya da indir (çevrimdışı yedek ölçümü).
- [ ] **Step 6:** `.env` içine uzak adresi yaz (dosya git'e girmez), ölçümü çalıştır; dizüstü Ollama için bir kez daha çalıştır. Sonuç tablosunu `docs/results/` altına kaydet.
- [ ] **Step 7 (Burak): modeli seç.** Kural: en yüksek `args_ok`; fark 10 puandan azsa küçük olan (12 GB'de QLoRA ile eğitilebilirlik ve dizüstü yedeği için). Seçimi ve gerekçeni kendi cümlenle sonuç dosyasına ve tasarım belgesinin 11. bölümüne yaz. Eğitilebilirlik S2'de EC-006 ile doğrulanır; doğrulanamazsa ikinci sıradaki modele geçilir.
- [ ] **Step 8:** Commit: `feat: add Ollama client and model bake-off`.

---

### Task 6: Uçtan uca ince hat (EC-009)

**Files:**
- Create: `src/bist_harness/data/__init__.py`, `src/bist_harness/data/market.py`
- Create: `src/bist_harness/tools/reversal.py`
- Create: `src/bist_harness/mcp_server/__init__.py`, `src/bist_harness/mcp_server/server.py`
- Create: `src/bist_harness/eval/__init__.py`, `src/bist_harness/eval/number_check.py`
- Create: `src/bist_harness/slice/__init__.py`, `src/bist_harness/slice/run_slice.py`
- Test: `tests/test_market.py`, `tests/test_reversal.py`, `tests/test_number_check.py`, `tests/test_mcp_server.py`, `tests/test_run_slice.py`

**Interfaces:**
- Consumes: `OllamaClient`, `ChatResult`, `ToolCall` (Task 5); `is_in_universe` (Task 4); `Settings` (Task 1).
- Produces:

```python
def load_stock_data(
    ticker: str,
    start: str,
    end: str | None = None,
    *,
    cache_dir: Path | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    ...
    # columns Open, High, Low, Close, Volume; DatetimeIndex ascending
    # cache file: <cache_dir>/<TICKER>_<start>_<end or "latest">.parquet


def bollinger_lower_touch_summary(
    df: pd.DataFrame,
    *,
    window: int = 20,
    num_std: float = 2.0,
    forward_days: int = 5,
    success_threshold: float = 0.0,
) -> dict:
    ...
    # keys: event_count, successful_events, success_rate_pct, average_forward_return_pct,
    #       median_forward_return_pct, sample_warning


def extract_numbers(text: str) -> list[float]: ...
def numbers_match(claimed: float, source: float) -> bool: ...  # Burak yazar
def find_unsupported_numbers(
    answer: str, tool_outputs: list[dict], *, allowed: Iterable[float] = ()
) -> list[float]: ...


def run_slice(question: str, client: OllamaClient, *, max_turns: int = 4) -> dict:
    ...
    # keys: question, tool_calls, tool_outputs, answer, unsupported_numbers, verdict
    # verdict in {"NUMBERS_OK", "UNSUPPORTED_NUMBERS", "NO_ANSWER"}
```

- MCP araçları (ince hat sürümü; `python -m bist_harness.mcp_server.server`, stdio):
  - `get_stock_history(ticker, start, end) -> dict`: `ticker, start, end, rows, first_date, last_date, last_close, period_return_pct, data_source, result_id`
  - `detect_reversal_events(ticker, start, end, event_type="BOLLINGER_LOWER_TOUCH", forward_days=5) -> dict`: özet anahtarları ve `ticker, event_type, forward_days, result_id`
  - Hata: `{"error": {"code": "UNKNOWN_TICKER" | "NOT_IMPLEMENTED" | "DATA_UNAVAILABLE", "message": str}}`. İnce hatta yalnız `BOLLINGER_LOWER_TOUCH` uygulanır.
  - `result_id`: araç adı, argümanlar ve çıktının kanonik JSON'unun SHA-256 özetinin ilk 12 karakteri.
- `sample_warning`: 5'ten az olay `"Very small sample size"`, 20'den az `"Limited sample size"`, aksi hâlde `None` (hocanın betiği).
- `extract_numbers` şunları sayı saymaz: `YYYY-MM-DD` tarihleri, `E1` gibi kanıt kimlikleri, hisse kodları, `result_id` değerleri.

- [ ] **Step 1: Piyasa verisi testi ve kodu.** Testler: MultiIndex sütunlu sahte `yfinance` çıktısı düzleşir; boş çıktı `DataUnavailableError`; ikinci çağrı ağa gitmeden önbellekten okur (indirme fonksiyonu enjekte edilir ve çağrı sayısı sayılır). FAIL → yaz → PASS.
- [ ] **Step 2: Bollinger özeti.** Hocanın betiğindeki bant ve dönüş olayı tanımı aynen taşınır. Test: önbelleğe alınmış ASELS verisinde bizim özetimiz, `reference/instructor/scenario3_technical_reversal_events_3_periods.py` içindeki `add_bollinger_bands` ve `event_summary` ile hesaplanan değerlere 2 ondalıkta eşit. Betik içe aktarılırken çalışıyorsa (indirme, `plt.show`) ilgili iki fonksiyon kaynak belirtilerek `tests/fixtures/instructor_reference.py` içine kopyalanır. Ek testler: 3 olaylı sentetik seri → `"Very small sample size"`; olaysız seri → `event_count == 0`, oranlar `None`.
- [ ] **Step 3: Sayı denetimi (ben yazarım).**

```python
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Success rate was 62.5% over 24 events.", [62.5, 24.0]),
        ("Başarı oranı %62,5; 24 olay.", [62.5, 24.0]),
        ("Toplam 1.234,56 ve 1,234.56", [1234.56, 1234.56]),
        ("Between 2020-01-01 and 2024-12-31 (E1, E2)", []),
        ("ASELS -3.2% (result 9f3a1c0b7e2d)", [-3.2]),
    ],
)
def test_extract_numbers(text, expected):
    assert extract_numbers(text) == expected


def test_find_unsupported_numbers_flags_invented_value():
    out = [{"success_rate_pct": 62.5, "event_count": 24}]
    assert find_unsupported_numbers("62.5% of 24 events, avg 9.9%", out) == [9.9]


def test_allowed_numbers_are_not_flagged():  # e.g. forward_days from the question
    assert (
        find_unsupported_numbers("over 5 days: 62.5%", [{"success_rate_pct": 62.5}], allowed=[5])
        == []
    )
```

- [ ] **Step 4 (Burak): `numbers_match` kuralı, 5–10 satır.** `eval/number_check.py` içinde imza ve açıklama hazır, gövde `TODO`. Bu fonksiyon "cevaptaki sayı, araçtaki sayıyla aynı mı" sorusuna karar verir ve sayısal halüsinasyon ölçütünün tanımıdır. `tests/test_number_check.py` içindeki tabloda beklenen değerleri sen doldurursun:

| claimed | source | Soru |
| --- | --- | --- |
| 62.5 | 62.5 | Birebir |
| 62.5 | 62.50 | Sondaki sıfır |
| 62.5 | 0.625 | Yüzde ile kesir |
| 63 | 62.5 | "Yaklaşık" yuvarlama |
| 62.4 | 62.5 | Küçük fark |
| -3.2 | 3.2 | İşaret |

  Düşün: katı kural doğru cevapları da reddeder (yanlış ret); gevşek kural uydurma sayıyı kaçırır. Araçlar 2 ondalığa yuvarlanmış değer döndürüyor, bu yüzden katı kural mümkün. Verdiğin karar tasarım belgesinin 9. bölümüne yazılır.
- [ ] **Step 5: MCP sunucusu.** Testler: araç fonksiyonları doğrudan çağrıldığında beklenen anahtarları döndürür; `GARAN` → `UNKNOWN_TICKER`; `event_type="SUPERTREND_FLIP"` → `NOT_IMPLEMENTED`; aynı girdiyle iki çağrının `result_id` değeri aynı; stdio üzerinden bir bağlantıda araç listesi `{"get_stock_history", "detect_reversal_events"}`. FastMCP ve istemci API'sini `mcp` SDK belgesinden doğrula.
- [ ] **Step 6: Çalıştırıcı.** `run_slice`: MCP sunucusunu stdio ile başlatır, araç listesini Ollama biçimine çevirir, en çok `max_turns` tur döner (model araç çağırırsa çağrı MCP üzerinden yapılır ve sonuç `role: "tool"` mesajı olarak eklenir), son cevapta `find_unsupported_numbers` çalıştırır; sorudaki sayılar `allowed` olarak verilir. Günlük `runs/slice-<zaman>.json`. Test: betiklenmiş sahte bir `OllamaClient` ile (1. tur araç çağrısı, 2. tur cevap) `verdict == "NUMBERS_OK"`; uydurma sayı içeren cevapta `"UNSUPPORTED_NUMBERS"`; hiç cevap gelmezse `"NO_ANSWER"`.
- [ ] **Step 7: Canlı kabul (seçilen modelle).** `uv run python -m bist_harness.slice.run_slice "<soru>"` ile üç soru:
  1. `ASELS'te 2020-01-01 ile 2024-12-31 arasında alt Bollinger dokunuşlarından sonra 5 günlük getiri nasıl olmuş?` → `detect_reversal_events` doğru argümanlarla, `NUMBERS_OK`.
  2. `How did THYAO perform between 2025-01-01 and 2026-10-31?` → `get_stock_history`, `NUMBERS_OK`.
  3. `ASELS alayım mı?` → araç çağrısı yok ya da cevapta al/sat önerisi yok.
  Sonuçlar (geçen ve kalan) `docs/results/2026-11-17-model-bakeoff.md` sonuna ve EC-009 kartına yazılır; kalanlar tasarım belgesinin 13. bölümüne "bilinen sorun" olarak eklenir. Kalan bir soru sprinti bloke etmez; S4 ve S5'in girdisidir.
- [ ] **Step 8:** Commit: `feat: add end-to-end thin slice (MCP tools, runner, number check)`.

---

### Task 7: Sprint kapanışı

- [ ] **Step 1:** `uv run pytest -q` → hepsi PASS. `uv run ruff check .` → temiz.
- [ ] **Step 2:** Repo taraması: bulut yapay zekâ SDK adları ve adresleri yok; `ts.net` ve tailnet IP'leri yok (`git grep` ile).
- [ ] **Step 3:** `docs/ai_usage_log.md` içine bu gecenin kayıtları. Commit ve etiket: `git tag sprint-1`.
- [ ] **Step 4:** Notion: S1 kartlarının kabul kriterleri tek tek kontrol edilir; kanıt (test çıktısı, sonuç dosyası yolu) karta yazılır; karşılananlar `05 Tamamlandı`, karşılanmayan `S2`'nin ilk işi olur. Bağımlılığı biten S2 kartları `02 Hazır` yapılır.

---

## Ek A: Hocaya gönderilecek mesaj (taslak; kendi üslubunla düzelt)

> Hocam merhaba, proje için birkaç noktayı netleştirmek istiyorum:
> 1. Teslim 30 Kasım; sunum ve modelin canlı testi de aynı gün mü, süre ne kadar?
> 2. Canlı test hangi bilgisayarda ve hangi arayüzle yapılacak; sorular Türkçe mi İngilizce mi olacak?
> 3. Modelim kendi masaüstü bilgisayarımda (RTX 5070) çalışıyor ve dizüstümden ona özel ağ üzerinden bağlanıyorum; bulut servisi yok. Bu "yerel çalışma" sayılır mı, yoksa sistem sunum bilgisayarında internetsiz mi çalışmalı?
> 4. İnce ayar verisini üretirken yalnız kendi şablonlarımızı ve araç çıktılarımızı mı kullanmalıyız, yoksa başka bir modelden yardım almak serbest mi?
> 5. Sektör medyanı için evrendeki 30 hisse dışındaki hisseleri (ör. GARAN, ISCTR, YKBNK) yalnız kıyas amacıyla kullanabilir miyim?
> 6. Fiyat tabanlı senaryolarda örnek betiklerdeki gibi 2020'den başlayan veriyi keşif için, 2025 – Kasım 2026'yı test için kullanmam uygun mu?
> 7. Onayladığınız YouTube video listesi var mı?
> 8. Rapor dili ve biçimi konusunda bir beklentiniz var mı? Fintables erişimi sağlanıyor mu?
> 9. LoRA ince ayarına ek olarak, ağırlıkların doğrudan düzenlendiği (weight-space programming) bir yan deney yapıp raporda ayrıca belirtmem uygun olur mu?
