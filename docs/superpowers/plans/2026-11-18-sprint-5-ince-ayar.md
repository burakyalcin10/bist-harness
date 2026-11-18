# Sprint 5 — İnce Ayar: Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sprint sonunda harness'in kendi istemleriyle birebir aynı biçimde üretilmiş, denetlenmiş ve donmuş soru setiyle çakışmayan bir ince ayar veri seti; bu veriyle QLoRA eğitilmiş, GGUF'a çevrilip Ollama'da internetsiz çalışan bir model; ve temel modelle ince ayarlı modelin aynı soru setinde karşılaştırması olsun. Epizodik bellek (deney E) ve metrik betiklerinin eksikleri de bu sprintte kapanır.

**Architecture:** Eğitim verisi elle yazılmaz, harness çalıştırılarak toplanır. Harness'e gerçek model yerine "öğretmen" bir istemci verilir (`finetune/teacher.py`): her model turunda (niyet, durum başına araç çağrısı, açıklama) doğru cevabı koddan kurar. Araçlar gerçek veriyle çalışır, açıklama yalnız committed evidence'a atıf yapar. Harness'in modele gönderdiği mesajlar ve araç şemaları olduğu gibi, öğretmenin cevabı hedef olarak kaydedilir; böylece eğitimdeki biçim ile çıkarımdaki biçim aynı kalır. Sorular şablonlardan üretilir, tarihleri keşif döneminde (2025-01-01 öncesi) tutulur. Eğitim ayrı bir bağımlılık grubunda (`train`) ve RTX 5070'te Burak'ın başında koşar; dizüstü yalnız küçük bir deneme koşusu yapar.

**Tech Stack:** Sprint 4 ile aynı. Yeni: isteğe bağlı `train` grubu (`torch` CUDA 12.8 yapısı — RTX 5070 Blackwell, `transformers`, `peft`, `trl`, `bitsandbytes`, `accelerate`, `datasets`); GGUF için `llama.cpp` dönüştürücüsü (repoya eklenmez, sürümü kaydedilir). Kütüphane arayüzleri sık değişiyor: betik yazılırken güncel belgeye bakılır, sürümler `uv.lock` ve eğitim günlüğünde sabitlenir.

**Spec:** `docs/superpowers/specs/2026-11-17-bist-harness-design.md` §10, §11, §12; istem §24, §30, §31; Duyuru 3 (madde 1–6). Kartlar: EC-005, 006 (Sprint 2'den devreden), 047, 050, 051, 052, 053, 054, 055, 061.

## Global Constraints

Önceki sprintlerin kısıtlarının tamamı geçerlidir. Ek olarak:

- Bulut yapay zekâ servisi çağrısı yoktur; veri üretiminde, eğitimde ve değerlendirmede yalnız yerel modeller. Açık ağırlıkların indirilmesi bu kurala girmez; indirilen model ve sürümü kaydedilir.
- Donmuş soru seti (`src/bist_harness/eval/questions.jsonl`, SHA-256 `e6141ea876724b786d84d78e7960f7865146a9f13074687cefe64aaa1fb3bcae`) değişmez ve eğitim, doğrulama ya da model seçiminde kullanılmaz; yalnız son karşılaştırmada (Task 9). Çakışma `questions.overlaps()` ile sıfır olmalı.
- Eğitim sorularının tarihleri ve `today` değerleri 2025-01-01'den öncedir (ön kayıtlı test dönemi eğitime girmez).
- Eğitim kaydı biçimi: soru → doğru araç çağrısı → araç çıktısı → kanıta dayalı açıklama (Duyuru 3), temel modelin kendi sohbet ve araç şablonuyla. Kayıttaki mesajlar harness'in o turda modele gönderdiği mesajlarla bayt bayt aynıdır.
- Her eğitim hedefi kodun denetimlerinden geçer: açıklama `validate_explanation`'dan, araç çağrısı şema, izin ve niyet denetiminden (`machine.check_call`).
- Tohum 42 her yerde (soru üretimi, bölme, eğitim). Veri seti tek komutla aynı baytlarla yeniden üretilir.
- Uzak sunucunun adresi, tailnet adı ya da IP'si hiçbir dosyaya, günlüğe ya da Notion'a yazılmaz; yalnız `BIST_LLM_BASE_URL` ve git dışı `.env`.
- Testler gerçek veri klasörünü okumaz (Sprint 4 son incelemesi C2); veri isteyen testler `real_data` işaretiyle varsayılan koşudan çıkar.
- Eğitim sonuçları ne olursa olsun raporlanır; ince ayarın kötüleştirdiği durumlar da yazılır.

## Review Focus

1. **Öğretmenin cevabı, harness'in o turdaki mesajına uymuyor** (ör. niyet turuna araç çağrısı, araç turuna metin). Beklenen: üretim hattı turu tanır, uymayan hedefi yazmaz ve sayar. Test: Task 1 (`test_teacher_reply_matches_turn_kind`).
2. **Üretilen bir soru donmuş setteki bir soruya çok benziyor ya da aynı hisse–tarih birleşimini taşıyor.** Beklenen: üretim o soruyu atar, sayısını rapora yazar. Test: Task 2 (`test_generated_questions_never_overlap_frozen_set`).
3. **Aynı soru farklı tarihle tekrarlanınca model sayıları ezberliyor.** Beklenen: aynı şablon farklı tarih ve hisseyle farklı araç çıktısı taşır; bölme şablon ailesine göre yapılır, doğrulama ve test bölümlerinde eğitimde görülmemiş aileler vardır. Test: Task 3 (`test_split_holds_out_template_families`).
4. **Bellek gelecekten bilgi sızdırıyor** (sonraki tarihli bir analiz ya da daha sonra verilmiş bir insan kararı bağlama giriyor). Beklenen: yalnız `as_of`'u ve inceleme zamanı yeni analizin `as_of`'undan önce olanlar. Test: Task 5 (`test_memory_never_recalls_later_episodes`).
5. **Nicemleme ya da GGUF dönüşümü araç çağırma biçimini bozuyor** (sohbet şablonu kayboluyor, araç çağrısı metin olarak geliyor). Beklenen: dönüşümden önce ve sonra aynı geliştirme sorularında araç çağrısı doğruluğu ölçülür; düşüş raporlanır. Test: Task 8 (`test_modelfile_carries_tool_template` + ölçüm adımı).

## Dosya yapısı

```
src/bist_harness/finetune/
  record.py      # TrainingRecord, turn türleri, JSONL okuma/yazma
  teacher.py     # TeacherClient: her turda doğru cevabı koddan kurar; CapturingClient
  questions.py   # soru şablonları (TR/EN), parametreler, olumsuz örnekler, çakışma süzgeci
  build.py       # CLI: soruları üret → harness'i öğretmenle çalıştır → train/val/test + manifest
  qc.py          # otomatik denetimler, yakın kopya ayıklama, rapor, elle okuma örneklemi
  train.py       # QLoRA eğitimi (train grubu gerekir), hiperparametre ve kayıp kaydı
  export.py      # adaptörü birleştir, GGUF'a çevir, Modelfile yaz, ollama create
src/bist_harness/harness/memory.py   # epizodik bellek: recall, özet kanıt maddeleri
configs/qlora/*.toml                  # eğitim ayarları (en az iki koşu)
docs/finetune.md                      # veri tasarımı, kapsama tablosu, eğitim ve dışa aktarma talimatı
docs/metrics.md                       # metrik tanımları, rapora girecek biçimde
```

## Sıra

| Görev | Kart | Not |
| --- | --- | --- |
| 1 Kayıt biçimi ve öğretmen istemci | EC-050 | |
| 2 Soru üretici ve çakışma süzgeci | EC-050, 051 | |
| 3 Üretim hattı ve bölme | EC-051 | gerçek veriyle tek komut |
| 4 Veri kalite kontrolü | EC-052 | 50 kaydı Burak okur |
| 5 Epizodik bellek | EC-047 | deney E |
| 6 Metrik betikleri ve tanımlar | EC-061 | |
| 7 Temel model ölçümü ve seçimi | EC-005, 006 | RTX 5070 (çıkarım geçitten); seçim Burak'ın |
| 8 QLoRA eğitimi ve dışa aktarma | EC-053, 054 | eğitim 5070'in başında, Burak koşar |
| 9 Karşılaştırma ve kapanış | EC-055 | donmuş set yalnız burada |

---

### Task 1: Kayıt biçimi ve öğretmen istemci (EC-050)

**Files:** Create `finetune/record.py`, `finetune/teacher.py`, `tests/test_finetune_teacher.py`, `docs/finetune.md` (veri tasarımı ve kapsama tablosu bölümü).

**Interfaces:**
- Consumes: `harness.machine.run_analysis`, `machine.canonical_calls(state, intent)`, `intent.INTENT_SCHEMA`, `intent._SYSTEM_PROMPT` (adıyla dışa açılır: `INTENT_SYSTEM_PROMPT`), `validator.explanation_schema`, `validator.validate_explanation`, `actions.eligible_actions`, `llm.client.ChatResult`/`ToolCall`.
- Produces:

```python
TURN_KINDS = ("intent", "tool_call", "explanation")
@dataclass(frozen=True)
class TrainingRecord:
    record_id: str; question_id: str; family: str; language: str; scenario: str
    turn: str              # TURN_KINDS
    state: str | None      # tool_call turunda durum adı
    messages: list[dict]   # harness'in gönderdiği mesajlar, olduğu gibi
    tools: list[dict]      # o turda sunulan araç şemaları ([] niyet ve açıklama turunda)
    target: dict           # {"role": "assistant", "content": str} ya da {"role": "assistant", "tool_calls": [...]}
    meta: dict             # outcome, eligible, action, snapshot_id, layers_id, today
def write_jsonl(records: Iterable[TrainingRecord], path: Path) -> str   # sha256 döner; newline="\n", sort_keys
def read_jsonl(path: Path) -> list[TrainingRecord]
@dataclass(frozen=True)
class Gold:
    intent: dict           # INTENT_SCHEMA'ya uyan doğru niyet
    action: str | None     # açıklama turunda seçilecek etiket (None → eligible'ın ilki)
class TeacherClient:       # ChatClient arayüzü: chat(messages, tools=None, response_format=None, **kw) -> ChatResult
    def __init__(self, gold: Gold): ...
    turns: list[TrainingRecord]   # her chat çağrısında bir kayıt eklenir
```

- Tur türü mesajdan tanınır: sistem mesajı `INTENT_SYSTEM_PROMPT` ise `intent`; "You are the tool-calling step" ile başlıyorsa `tool_call` (durum adı istemden okunur); `explanation_schema` ile çağrılmışsa `explanation`. Tanınmayan tur `ValueError`.
- `tool_call` hedefi: `canonical_calls(state, intent)` (Sprint 4 son düzeltme dalgasından sonra asgari kanıtı tamamlayan çağrılar ve sorudan temellenen `event_type`/`direction`).
- `explanation` hedefi: seçilen etiket ve her committed madde için bir cümle; her cümle kanıt cümlesini sayısıyla (işaretiyle birlikte) aktarır ve `[En]` atfı taşır; sonra varsayılan dönem notu (gerekiyorsa) ve uyarı satırı, `validator`'daki tam metinle. Hedef `validate_explanation`'dan geçmezse `TeacherError` (yazılmaz).

- [ ] Testler (sentetik anlık görüntü, `tests/golden_snapshot.py`; sahte değil gerçek harness):
  - `test_teacher_reply_matches_turn_kind`: dört senaryonun her birinde bir koşu; `turns` içinde sırasıyla bir `intent`, durum başına `tool_call`, bir `explanation` var; `intent` hedefi JSON ve `INTENT_SCHEMA`'ya uyuyor; `tool_call` hedefinde metin yok.
  - `test_teacher_messages_are_what_the_harness_sent`: `messages` her turda harness'in o çağrıdaki listesine eşit (araya `CapturingClient` koyarak karşılaştır).
  - `test_teacher_explanation_passes_validator` ve `test_teacher_copies_sign` (`max_drawdown_pct` −16,88 → metinde `%-16,88`).
  - `test_advice_question_yields_only_intent_turn`: "THYAO alsam mı?" benzeri üretilmiş soru → tek `intent` kaydı, `scenario` `ADVICE_REQUEST`, araç turu yok.
- [ ] FAIL → uygulama → PASS. Commit: `feat: teacher client records harness turns as training targets`.

### Task 2: Soru üretici ve çakışma süzgeci (EC-050, EC-051)

**Files:** Create `finetune/questions.py`, `tests/test_finetune_questions.py`.

**Interfaces:**
- Consumes: `universe.load_universe()`, peer grupları, `eval.questions.overlaps`, `eval.questions.load_questions`.
- Produces:

```python
@dataclass(frozen=True)
class GenQuestion:
    question_id: str; family: str; language: str; text: str; gold: Gold
FAMILIES: dict[str, Family]    # aile adı → TR/EN parafraz şablonları + parametre üretici + gold kurucu
def generate(n_per_family: int, *, seed: int = 42, today_range=("2019-06-01", "2024-12-31")) -> list[GenQuestion]
def drop_overlaps(qs: list[GenQuestion]) -> tuple[list[GenQuestion], list[dict]]   # kalanlar, atılanlar (neden ile)
```

- Aileler (her biri TR ve EN, resmî ve günlük, en az 4 parafraz): dört zorunlu senaryo × {tarihli, tarihsiz (varsayılan dönem), şirket adıyla, küçük harfli kodla}; `BACKTEST`, `PRICE_SUMMARY`, `MACRO_CONTEXT`, `NEWS_CONTEXT`; olumsuzlar: tavsiye isteği, fiyat tahmini, evren dışı hisse, gelecek tarih, araç gerektirmeyen soru (selamlama, kapsam dışı), eksik bilgi (hisse yok). Sekiz eylem etiketinin hepsi en az bir ailenin gold'unda erişilebilir olmalı (kapsama tablosu Task 3'te gerçek çıktıyla doğrulanır).
- `today` ve sorudaki tarihler `today_range` içinde; dönem en geç 2024-12-31'de biter.
- `drop_overlaps`: `overlaps()` eşiğini aşan ya da donmuş setin beklenen niyetindeki (hisse, başlangıç, bitiş) üçlüsünü taşıyan soruyu atar.

- [ ] Testler:
  - `test_generation_is_deterministic`: aynı tohum → aynı liste (metin ve gold); farklı tohum → farklı.
  - `test_generated_questions_never_overlap_frozen_set`: `generate(20)` sonrası `drop_overlaps` → `overlaps(kalanlar) == []`; donmuş setin bir sorusunu elle listeye ekleyince atılanlarda çıkıyor (soruyu id ile yükle, metni teste kopyalama).
  - `test_no_date_after_test_period_start`: bütün gold tarihleri ve `today` < `2025-01-01`.
  - `test_every_family_has_both_languages` ve `test_gold_intent_matches_schema`.
- [ ] FAIL → uygulama → PASS. Commit: `feat: templated question generator for fine-tuning data`.

### Task 3: Üretim hattı ve bölme (EC-051)

**Files:** Create `finetune/build.py`, `tests/test_finetune_build.py`; `docs/finetune.md` (üretim bölümü). Modify `pyproject.toml` (`real_data` işareti zaten Sprint 4 son düzeltmesinde eklendiyse yalnız kullan).

**Interfaces:**
- Consumes: Task 1 `TeacherClient`, `write_jsonl`; Task 2 `generate`, `drop_overlaps`; `machine.run_analysis` (araçlar süreç içinde, `run_eval._server_call_tool` ile aynı çağırıcı).
- Produces: `uv run python -m bist_harness.finetune.build --n-per-family 30 --out data/finetune/` → `train.jsonl`, `val.jsonl`, `test.jsonl`, `manifest.json`.

```python
def build(n_per_family: int, out: Path, *, seed: int = 42, call_tool: ToolCaller | None = None) -> dict  # manifest
def split_by_family(records, *, seed: int = 42,
                    holdout: tuple[tuple[str, float], ...] = (("val", 0.1), ("test", 0.1))) -> dict[str, list]
```

- Bölme şablon ailesinin parafraz şablonuna göre yapılır: her ailenin parafrazlarının bir kısmı yalnız `val`/`test`'te görünür; aynı soru kaydının turları aynı bölümde kalır.
- Manifest: kayıt sayısı bölüm × tur × senaryo × etiket × dil × aile; atılan sorular (çakışma) ve nedenleri; öğretmen hataları; `snapshot_id`, `layers_id`, kod commit'i, her dosyanın SHA-256'sı, tohum, üretim süresi. Rapora "kaç örnek kullandık" sorusu buradan cevaplanır (Duyuru 3).
- Hedef boyut: 30 soru × aile (≈ 25 aile) ≈ 750 soru → ≈ 3.000–4.000 tur kaydı. Kesin sayı manifestte.

- [ ] Testler (sentetik anlık görüntü):
  - `test_build_twice_gives_identical_files` (SHA-256 eşit).
  - `test_split_holds_out_template_families`: `val`/`test`'te en az bir parafraz şablonu `train`'de yok; bir sorunun turları tek bölümde.
  - `test_manifest_counts_match_files` ve `test_coverage_has_no_empty_cell`: dört senaryo × sekiz etiketin ulaşılabilir hücreleri ve beş olumsuz tür sıfırdan büyük (ulaşılamayan hücre gerekçesiyle `docs/finetune.md`'de listelenir, sayılmaz).
- [ ] FAIL → uygulama → PASS. Commit: `feat: fine-tuning data build with family-held-out split`.
- [ ] Gerçek veriyle bir kez çalıştır (`real_data`), manifest özetini `docs/results/<gün>-finetune-data.md`'ye yaz. Commit: `docs: fine-tuning data build results`.

### Task 4: Veri kalite kontrolü (EC-052)

**Files:** Create `finetune/qc.py`, `tests/test_finetune_qc.py`.

```python
@dataclass(frozen=True)
class QCFinding: record_id: str; check: str; detail: str
CHECKS = ("numbers_in_tool_output", "call_schema_valid", "call_allowed_and_on_intent",
          "label_in_eight", "no_advice_language", "validator_accepts", "no_frozen_overlap")
def run_qc(records: Sequence[TrainingRecord]) -> list[QCFinding]
def dedupe(records, *, threshold: float = 0.95) -> tuple[list[TrainingRecord], int]   # yakın kopyalar (katlanmış metin benzerliği, aynı tur ve hedef)
def sample_for_review(records, n: int = 50, *, seed: int = 42) -> list[TrainingRecord]
```

- CLI: `uv run python -m bist_harness.finetune.qc data/finetune/` → `qc.json`, `review-sample.md` (50 kayıt, senaryo ve tur türüne göre katmanlı; her kayıt soru, hedef ve araç çıktısının ilgili alanıyla okunur biçimde). Elle okumayı Burak yapar (kart kabul kriteri); bulduğu sorunlar şablonlara geri yazılır ve veri yeniden üretilir.

- [ ] Testler: her denetim için bozuk bir kayıt yakalanıyor, doğru kayıt geçiyor (ör. açıklamaya kanıtta olmayan 12,35 eklenmiş kayıt → `numbers_in_tool_output`; izin dışı araç → `call_allowed_and_on_intent`; "hisseyi alın" → `no_advice_language`); `dedupe` aynı metnin iki kaydından birini atar; örneklem deterministik ve katmanlı.
- [ ] FAIL → uygulama → PASS. Commit: `feat: fine-tuning data quality checks`.
- [ ] Gerçek veride QC: bulgu sayısı 0 olana kadar şablon düzelt → yeniden üret. Sonuç `docs/results/<gün>-finetune-data.md`'ye eklenir.

### Task 5: Epizodik bellek (EC-047)

**Files:** Create `harness/memory.py`, `tests/test_memory.py`. Modify `harness/machine.py` (bellek kancası), `harness/evidence.py` (bellek maddeleri), `eval/run_eval.py` (E'de açık, D'de kapalı).

```python
@dataclass(frozen=True)
class Episode:
    analysis_id: str; as_of: str; scenario: str; action: str | None; outcome: str
    human_result: str | None; reason: str | None; reviewed_at: str | None
def recall(conn: sqlite3.Connection, *, ticker: str, as_of: str, limit: int = 3) -> list[Episode]
def memory_items(episodes: Sequence[Episode], *, language: str) -> list[Evidence]   # committed=False, tool="memory"
```

- `run_analysis(..., memory: bool = False)`; açıkken `BUILD_EVIDENCE`'ta aynı hissenin önceki analizleri bağlama "gözlenen bağlam" maddesi olarak eklenir (committed değil; açıklamada atıf yapılamaz, cevapta ve inceleme ekranında görünür).
- Yalnız `as_of < yeni as_of` ve (varsa) `reviewed_at < yeni analizin created_at` olan bölümler. Zamansal bellek (Parquet katmanları) ve prosedürel bellek (rotalar, izinler, şablonlar) zaten var; `docs/finetune.md` değil `docs/data_dictionary.md`'de üç belleğin yeri bir tabloda yazılır.

- [ ] Testler: `test_second_analysis_shows_previous_and_human_decision` (aynı hisse, iki analiz, ilkine `review` ile ACCEPT → ikincinin kanıtında bellek maddesi ve insan kararı); `test_memory_never_recalls_later_episodes`; `test_memory_off_gives_same_committed_set` (D ve E aynı committed set'i üretir, yalnız gözlenen bağlam farklı); `test_replay_with_memory_matches`.
- [ ] FAIL → uygulama → PASS. Commit: `feat: episodic memory of past analyses and human decisions`.

### Task 6: Metrik betikleri ve tanımlar (EC-061)

**Files:** Modify `eval/metrics.py`; create `tests/fixtures/labelled_records.jsonl` (elle etiketlenmiş 12 kayıt, sentetik), `tests/test_metrics_labelled.py`, `docs/metrics.md`.

- Eksik metrik: **backtest doğruluğu** — kayıttaki her `run_backtest` çağrısı aynı argüman ve aynı veri sürümüyle yeniden çalıştırılır; raporlanan alanlar (`total_return_pct`, `win_rate_pct`, `max_drawdown_pct`, işlem sayısı) birebir eşleşme oranı. `def backtest_accuracy(records, call_tool) -> float | None`.
- Elle etiketlenmiş kayıtlar: her metrik için en az bir pozitif ve bir negatif örnek; beklenen değerler fikstürde elle yazılı. Test, betiğin her metriği bu değerlerle aynı saydığını gösterir.
- `docs/metrics.md`: her metriğin tanımı (rapora aynen girecek Türkçe), payı ve paydası, A–E'de neyi ölçtüğü ve tanım gereği sabit kalan durumlar (Sprint 4 son düzeltme dalgasındaki I5 notlarıyla birleşik).

- [ ] FAIL → uygulama → PASS. Commit: `feat: backtest accuracy metric and hand-labelled metric checks`.

### Task 7: Temel model ölçümü ve seçimi (EC-005, EC-006)

**Files:** Create `docs/results/<gün>-base-model-selection.md`. Modify `eval/run_eval.py` yalnız gerekirse (`--questions-file` ile donmuş set dışında bir dosya: Task 3'ün `test.jsonl`'undan soru metinleri).

- Adaylar: `qwen3.5:2b`, `qwen3.5:4b` ve RTX 5070'teki `qwen3.5:9b` (Burak'ın 5070'te kurulu modeli). Ölçüm geliştirme sorularıyla (Task 3 `test` bölümünden 60 soru, senaryo dengeli), deney E, iki tekrar; donmuş set kullanılmaz.
- RTX 5070'e çıkarım geçitten gider: `.env`'de `BIST_LLM_BASE_URL` (git dışı); adres hiçbir dosyaya yazılmaz. Makine kapalıysa Burak'tan açması istenir.
- Ölçütler: niyet doğruluğu (temellendirmeden önceki ham değer ve uydurulan alan sayısı), hatalı çağrı oranı, açıklama kabul oranı (geri düşüş oranı), gecikme, 12 GB'de QLoRA ile eğitilebilirlik (parametre sayısı ve 4 bit bellek tahmini), dizüstünde yedek olarak çalışabilme.
- Seçim Burak'ındır; belge seçenekleri ve önerimi yazar, karar günlüğüne `Bekliyor` olarak girer. Seçim gelene kadar Task 8'in dizüstü deneme koşusu `qwen3.5` 0.8B ile ilerler.
- EC-006: 5070'te `train` grubunun kurulumu ve 20 adımlık deneme koşusu (Task 8'in betiğiyle) — Burak makinenin başında; komutlar `docs/finetune.md`'de.

- [ ] Ölçümü çalıştır, belgeyi yaz. Commit: `docs: base model measurement on the development questions`.

### Task 8: QLoRA eğitimi ve dışa aktarma (EC-053, EC-054)

**Files:** Create `finetune/train.py`, `finetune/export.py`, `configs/qlora/r16-e2.toml`, `configs/qlora/r32-e3.toml`, `tests/test_finetune_train_config.py`, `tests/test_finetune_export.py`; `docs/finetune.md` (eğitim ve dışa aktarma talimatı). Modify `pyproject.toml` (`[dependency-groups] train = [...]`, torch için CUDA 12.8 indeksi).

```python
@dataclass(frozen=True)
class TrainConfig:
    base_model: str; rank: int; alpha: int; dropout: float; target_modules: tuple[str, ...]
    learning_rate: float; epochs: int; batch_size: int; grad_accum: int; max_seq_len: int
    seed: int = 42; load_in_4bit: bool = True; eval_steps: int = 50; early_stop_patience: int = 3
def load_config(path: Path) -> TrainConfig
def to_chat_examples(records: Sequence[TrainingRecord], tokenizer) -> list[dict]   # temel modelin chat şablonu, tools ile; kayıp yalnız hedef turda
def train(config: TrainConfig, data_dir: Path, out_dir: Path) -> dict   # adaptör, loss.csv, run.json (ayarlar, kütüphane sürümleri, süre, en iyi adım)
def export(adapter_dir: Path, base_model: str, out_dir: Path, *, quant: str = "q4_K_M", name: str) -> Path   # birleştir → GGUF → Modelfile → `ollama create`
```

- `train.py` `train` grubu yoksa açık hata verir; harness'in kendisi bu kütüphaneleri hiç içe aktarmaz.
- Kayıp yalnız hedef asistan turunda hesaplanır (mesajların geri kalanı maskeli). Doğrulama kaybı `eval_steps`'te izlenir; `early_stop_patience` kez iyileşmezse durur.
- Modelfile: temel modelin sohbet ve araç şablonu, `temperature 0`, `seed 42`; `num_ctx` harness'in en uzun turuna yetecek değer (manifestteki en uzun tur + pay).
- Koşular: dizüstünde 0.8B ile 20 adımlık deneme (boru hattının uçtan uca çalıştığını gösterir); 5070'te seçilen modelle iki ayar (`r16-e2`, `r32-e3`). Seçilen koşu doğrulama kaybı ve geliştirme sorularında açıklama kabul oranıyla seçilir, gerekçe `docs/results/<gün>-finetune-training.md`'de.
- Veri ve ayarlar 5070'e `runs/finetune-bundle-<id>.zip` olarak taşınır (veri git dışı); adaptör ve kayıp dosyaları geri getirilir.

- [ ] Testler (eğitim kütüphanesi olmadan çalışan): `test_config_files_load_and_record_every_setting`; `test_chat_examples_mask_everything_but_target` (sahte tokenizer); `test_train_without_group_fails_clearly`; `test_modelfile_carries_tool_template` (üretilen Modelfile'da TEMPLATE, `temperature 0`, `seed 42`).
- [ ] FAIL → uygulama → PASS. Commit: `feat: QLoRA training and GGUF export scripts`.
- [ ] Dizüstü deneme koşusu + `export` + `ollama run` ile bir soru; nicemleme öncesi ve sonrası araç çağrısı doğruluğu geliştirme sorularında karşılaştırılır (Review Focus 5).
- [ ] 5070 koşuları (Burak): iki ayar, kayıp eğrileri, seçim. Dışa aktarılan model dizüstünde ve 5070'te `ollama list`'te.
- [ ] İnternetsiz çalışma: `tests/test_offline.py` — uçtan uca bir harness koşusu (sahte model, sentetik veri) sırasında yerel olmayan her soket bağlantısını reddeden bir yama; bulut SDK'sı aramayla yok (`openai|anthropic|google.generativeai|cohere|mistralai`). Ayrıca Burak Wi-Fi kapalıyken bir soruyu canlı çalıştırır; süre kayda geçer.

### Task 9: Karşılaştırma ve kapanış (EC-055)

**Files:** Create `docs/results/<gün>-finetune-comparison.md`.

- Temel model ve ince ayarlı model, donmuş 120 soruda, deney D ve E, iki tekrar, aynı ayarlarla (`run_eval --experiments D,E`). Model 5070'te (geçitten); 5070 kapalıysa dizüstünde, bu durum belgeye yazılır.
- Tablo: sayısal halüsinasyon (gösterilen ve model düzeyi), hatalı araç çağrısı, kanıtsız sonuç, kural ihlali, açıklama kabul oranı, ham niyet doğruluğu ve uydurulan alan sayısı, gecikme; senaryo ve soru türü kırılımı. İnce ayarın kötüleştirdiği sorular örnekleriyle. "Bilinen sınırlamalar" listesi (Duyuru 3).
- [ ] `uv run pytest -q` (normal ve boş veri klasörüyle), `uv run ruff check .` temiz; bütün dal incelemesi; tek düzeltme dalgası.
- [ ] Karar günlüğü, `docs/ai_usage_log.md` (model indirmeleri ve eğitim koşuları dahil), `git tag sprint-5`, Notion kartları, Sprint 6 planı (harness deneyleri A–E iki modelle, senaryo raporları, weight-space programming yan deneyi EC-057).
