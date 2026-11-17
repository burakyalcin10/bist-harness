# Sprint 4 — MCP ve Harness: Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sprint sonunda bir soru, 17 durumlu harness içinden geçerek kanıt paketi, kalite kapısı kararı, sekiz etiketten biri ve kanıta atıflı bir açıklamayla sonuçlansın; her adım kaydedilsin, insan incelemesi alınabilsin ve analiz aynı veriyle yeniden oynatılabilsin. On beş MCP aracının hepsi sözleşme testinden geçsin; görülmemiş soru seti ve beş not ölçütünü hesaplayan puanlayıcı hazır olsun.

**Architecture:** Harness, modelin etrafındaki koddur (`src/bist_harness/harness/`). Durum geçişlerini kod yönetir (K-005); model yalnız üç yerde konuşur: niyet çıkarımı, izinli araçlardan çağrı önerme, kanıt kümesine atıfla açıklama yazma. Araçlar MCP üzerinden çağrılır; her çağrı önce şemaya, sonra durumun izin listesine, sonra niyete göre denetlenir. Kanıt cümleleri şablondan üretilir, sayı araç çıktısından kopyalanır. Kapı ve doğrulayıcı kararlarını model değiştiremez.

**Tech Stack:** Sprint 3 ile aynı; yeni bağımlılık yok. Model çağrıları `llm/client.py` üzerinden (Ollama, `format` ile şemaya kısıtlı JSON). Testlerde model, senaryolu sahte istemcidir; canlı model yalnız Task 10'da çalışır.

**Spec:** `docs/superpowers/specs/2026-11-17-bist-harness-design.md` §5–§10, §12; istem §17, §20–§28, §30, §33; Duyuru 3. Kartlar: EC-040, 041, 042, 043, 044, 045, 048, 060.

## Global Constraints

Önceki sprintlerin kısıtlarının tamamı geçerlidir. Ek olarak:

- Model hiçbir sayıyı hesaplamaz ve hiçbir kanıt cümlesini kendi yazmaz; yalnız kanıt numaralarına (`E1`, `E2` …) atıf yapar.
- `CHECK_DATA_QUALITY`, `RUN_BACKTEST` (aday etiketleri için) ve `RISK_GATE` durumları hiçbir rotada atlanmaz.
- Yatırım tavsiyesi ya da fiyat tahmini isteyen soruda araç çağrılmaz; sabit eğitim amaçlı cevap döner ve etiket `ANALYSIS_UNSAFE` olmaz, sonuç `REFUSED_ADVICE` olarak kaydedilir.
- Açıklama sorunun dilinde yazılır (Türkçe ya da İngilizce); etiketler ve araç adları İngilizce kalır (K-006).
- Her analiz `analysis_id`, `snapshot_id`, `adjustments_id`, model adı, sıcaklık 0 ve tohum 42 ile kaydedilir.
- Sprint 2 ve 3'ten devreden küçük bulgular bu sprintte kapanır: MCP katmanında katı argüman denetimi; kayıtlarda NaN yerine `None`; SASA için hacim uyarısı; özellik tablosu önbelleği.
- Bulut yapay zekâ servisi çağrısı yoktur; test ve geliştirme sırasında da yalnız yerel modeller kullanılır.

## Review Focus

1. **Model izinli olmayan bir aracı çağırıyor ya da niyetteki hisseden başka bir hisse soruyor.** Çağrı reddedilir, kayda geçer, hatalı çağrı sayılır; analiz doğru çağrıyla sürer. Test: Task 4.
2. **Model araç çağırmadan cevap yazmaya çalışıyor.** Araçlı durumda metin cevabı kabul edilmez; iki denemeden sonra harness çağrıyı kendisi yapar ve bunu kaydeder. Test: Task 4.
3. **Açıklamada kanıt kümesinde olmayan bir sayı, tarih ya da şirket adı var.** Doğrulayıcı reddeder; bir kez yeniden ister; ikinci başarısızlıkta yalnız kanıt kümesi ve `INVESTIGATE` gösterilir. Test: Task 7.
4. **Backtest stratejinin al-tut'un gerisinde kaldığını söylüyor ama model aday etiketi veriyor.** Etiket uygunluğu koddadır; model yalnız uygun etiketler arasından seçer. Test: Task 6 ve 7.
5. **Replay sırasında veri değişmiş.** `snapshot verify` başarısızsa ya da bir `result_id` tutmuyorsa replay `MISMATCH` raporlar ve hangi çağrının farklı olduğunu söyler. Test: Task 8.

## Dosya yapısı

```
src/bist_harness/harness/
  intent.py        # Intent, parse_intent, niyet şeması, tavsiye/tahmin koruyucusu
  routes.py        # STATES, ROUTES, ALLOWED_TOOLS, zorunlu durumlar
  session.py       # Analysis, araç çağrısı kaydı, SQLite yazımı
  machine.py       # run_analysis: durum döngüsü, çağrı denetimi, geri düşüş
  evidence.py      # şablonlar, build_evidence, committed set kuralları
  gate.py          # quality_gate: sert bloklar, yumuşak uyarılar, karar
  actions.py       # eligible_actions: kanıta göre izinli etiketler
  validator.py     # validate_explanation: etiket, sayı, atıf, tavsiye dili, uyarı satırı
  review.py        # insan incelemesi CLI'si
  replay.py        # replay_analysis
src/bist_harness/eval/
  questions.jsonl  # görülmemiş soru seti
  metrics.py       # beş not ölçütü
  run_eval.py      # deney A–E koşucusu
```

## Sıra

| Görev | Kart | Not |
| --- | --- | --- |
| 0 Sprint 3'ten devreden düzeltmeler ve test dönemi çalıştırması | EC-014, 025, 012 | Temel veri yeniden kurulmadan harness onu kullanmaz |
| 1 Oturum kaydı ve kalan üç araç | EC-040 | `check_data_quality`, `build_evidence_bundle`, `get_speech_features` |
| 2 Sözleşme testleri ve referans çıktılar | EC-041 | 15 aracın hepsi |
| 3 Niyet çıkarımı ve rotalar | EC-042 | |
| 4 Durum makinesi | EC-042 | |
| 5 Kanıt oluşturucu | EC-043 | |
| 6 Kalite kapısı ve etiket uygunluğu | EC-044, EC-045 | |
| 7 Çıktı doğrulayıcı | EC-045 | |
| 8 İnsan incelemesi, günlük, replay | EC-048 | |
| 9 Görülmemiş soru seti ve puanlayıcı | EC-060 | |
| 10 Canlı uçtan uca deneme ve kapanış | — | Yerel model gerekir |

---

### Task 0: Sprint 3'ten devreden düzeltmeler (EC-014, EC-025, EC-012) — önce bu

Sprint 3 incelemesi temel veri kaynağının zamana göre doğru olmadığını gösterdi (karar K-048). Harness bu katmanı kullanmadan önce:

- [ ] **Temel veri, yayımlandığı günkü rakamlardan yeniden kurulur.** Önce hangi yolun mümkün olduğu ölçülür: (a) KAP'taki "Finansal Rapor" bildiriminin kendisinden kalemleri okumak; (b) kaynaktaki yeniden düzeltilmiş değeri, bir sonraki yılın raporunun fiyat düzeyinden TÜFE oranıyla geri çevirmek. (b) seçilirse en az beş hisse ve iki dönem için sonuç, KAP'taki rapordaki rakamla karşılaştırılır ve fark belgelenir. Hangi dönemlerin yeniden düzeltildiği (gelir tablosu, bilanço, yıl sonu) hisse bazında saptanır; karışık fiyat düzeyli toplamlar (son 12 ay, özkaynak kârlılığı) aynı düzeye getirilir ya da verilmez.
- [ ] Anlık görüntüye düzeltilmemiş kapanış eklenir; değerleme oranları onunla hesaplanır.
- [ ] Makro, temel ve KAP katmanlarının özetleri `result_id` kimliğine girer; `snapshot verify` bu dosyaları da denetler.
- [ ] TÜFE yayın günleri kayıtlı bir tablodan alınır; kur, özellik tablosunda bir gün gecikmeyle kullanılır.
- [ ] `fundamental_trend` denetimleri (nakit akışı, zarardan kâra geçiş) tutarlı hâle getirilir; motorun bilgi tarihi denetimi gerçek bir denetime çevrilir.
- [ ] Bunlar bittikten sonra, **bir kez**: `uv run python -m bist_harness.backtest.study test`; sonuç `docs/results/` altına, ön kayıt protokolündeki tanımlar değiştirilmeden yazılır.

### Task 1: Oturum kaydı ve kalan üç araç (EC-040)

**Files:** Create `harness/__init__.py`, `harness/session.py`, `tests/test_session.py`. Modify `mcp_server/server.py`, `storage/db.py` (gerekirse), `tools/events.py` (NaN → `None`), testler.

```python
@dataclass
class Analysis:
    analysis_id: str; question: str; created_at: str; model: str
    snapshot_id: str; adjustments_id: str
    intent: dict | None; state: str
    tool_calls: list[ToolCallRecord]       # seq, state, tool, arguments, output, result_id, allowed, source ("model"|"harness")
def new_analysis(question: str, *, model: str) -> Analysis
def record_call(analysis, *, state, tool, arguments, output, allowed=True, source="model") -> ToolCallRecord
def save(analysis, conn) -> None           # analyses + tool_calls
def load(analysis_id, conn) -> Analysis
```

- `check_data_quality(analysis_id)`: analizde çağrılan her hisse ve dönem için `check_price_series` ve çıktılardaki `coverage_warning`, `sample_warning`, `warnings` alanlarını toplar; `status` ∈ `PASS`, `PASS_WITH_WARNINGS`, `HARD_BLOCK` ve bulgu listesi döndürür.
- `build_evidence_bundle(analysis_id)`: Task 5'teki `build_evidence` çıktısını döndürür (Task 5'e kadar `NOT_IMPLEMENTED`).
- `get_speech_features(source_id)`: onaylı liste `data/reference/approved_videos.csv` (Sprint 7'de dolar); listede olmayan kimlik → `UNKNOWN_SOURCE`; liste boşken `DATA_UNAVAILABLE`.
- Bütün araç fonksiyonları ortak bir sarmalayıcıdan geçer: önce `validate_tool_call`; hata `INVALID_ARGUMENT` nesnesi olur (yanlış tip MCP katmanında sessizce çevrilmez).

- [ ] Kalan testler: kimlik benzersiz ve sıralı çağrı numarası; kayıt ve geri okuma eşit; olmayan `analysis_id` → `UNKNOWN_ANALYSIS`; kalite aracı bozuk seride `HARD_BLOCK`; `forward_days="5"` MCP üzerinden `INVALID_ARGUMENT`; `event_records` çıktısı `json.dumps(allow_nan=False)` ile yazılabilir.
- [ ] FAIL → uygulama → PASS. Commit: `feat: analysis session store and the remaining MCP tools`.

### Task 2: Sözleşme testleri ve referans çıktılar (EC-041)

**Files:** Create `tests/golden/*.json`, `tests/test_contracts.py`, `tests/golden_snapshot.py`.

- Sabit tohumlu sentetik bir anlık görüntü (fiyat, makro, temel, KAP) kurulur; 15 aracın her biri için en az bir başarılı ve bir hatalı çağrının çıktısı `tests/golden/` altında saklanır. Çıktı değişirse test kalır; değişiklik bilinçliyse dosya `UPDATE_GOLDEN=1` ile yenilenir ve fark commit'te görünür.
- Her araç için: şemadaki parametre adları, zorunlu alanlar ve varsayılanlar fonksiyon imzasıyla aynı; çıktı JSON'a NaN'sız yazılabiliyor; `result_id`, `snapshot_id`, `adjustments_id` var; hata nesnesi yalnız `error` anahtarı taşıyor; liste alanları 12 satırı aşmıyor.

- [ ] Testleri yaz → çalıştır → referansları üret → gözden geçir → commit: `test: tool contract tests and golden outputs`.

### Task 3: Niyet çıkarımı ve rotalar (EC-042)

**Files:** Create `harness/intent.py`, `harness/routes.py`, `tests/test_intent.py`, `tests/test_routes.py`.

```python
SCENARIOS = ("SECTOR_LAGGARD", "CALENDAR_PATTERN", "TECHNICAL_REVERSAL", "FUNDAMENTAL_REACTION",
             "PRICE_SUMMARY", "MACRO_CONTEXT", "NEWS_CONTEXT", "BACKTEST", "ADVICE_REQUEST", "PREDICTION_REQUEST", "OUT_OF_SCOPE")
@dataclass(frozen=True)
class Intent:
    scenario: str; ticker: str | None; sector: str | None
    start: str | None; end: str | None; as_of: str | None; language: str      # "tr" | "en"
INTENT_SCHEMA: dict                         # Ollama `format` için JSON şeması
def parse_intent(question: str, client, *, today: str) -> Intent      # model + kod denetimi
def check_intent(intent: Intent, *, today: str) -> str | None          # UNKNOWN_TICKER, FUTURE_DATE, INVALID_DATE_RANGE …
STATES: tuple[str, ...]                     # 17 durum, tasarım belgesi §6 sırasıyla
ALLOWED_TOOLS: dict[str, tuple[str, ...]]
ROUTES: dict[str, tuple[str, ...]]          # senaryo → durum dizisi
MANDATORY = ("CHECK_DATA_QUALITY", "RISK_GATE", "LOG_AND_CLOSE")
```

- Niyet, modelden şemaya kısıtlı JSON olarak istenir; sonra kodla denetlenir: hisse evrende mi, tarihler geçerli mi. Tarih verilmemişse varsayılan dönem senaryoya göre atanır ve bu, açıklamada belirtilir.
- **Tavsiye koruyucusu iki katmanlıdır:** modelin `ADVICE_REQUEST`/`PREDICTION_REQUEST` etiketi ve bundan bağımsız bir anahtar sözcük denetimi ("alayım mı", "satmalı mıyım", "should I buy", "yükselir mi", "hedef fiyat" …). İkisinden biri tetiklenirse analiz başlamaz. (Sprint 1 ve 2 bulgusu: ince ayarsız modeller bu soruda araç çağırıyor.)
- Rotalar: her senaryo için hangi durumların çalışacağı; aday etiketi verebilen rotalarda `PREVIEW_STRATEGIES` ve `RUN_BACKTEST` bulunur.

- [ ] Kalan testler: 40 soruluk tablo (TR/EN) için kural tabanlı koruyucu; sahte istemciyle niyet ayrıştırma; bozuk JSON → bir kez yeniden iste, sonra `OUT_OF_SCOPE`; her rota zorunlu durumları içerir ve durum sırası `STATES` sırasını bozmaz; izin tablosundaki her araç şemada var.
- [ ] FAIL → uygulama → PASS. Commit: `feat: intent parsing, advice guard and state routes`.

### Task 4: Durum makinesi (EC-042)

**Files:** Create `harness/machine.py`, `tests/test_machine.py`.

```python
def run_analysis(question: str, client, *, call_tool: ToolCaller, today: str | None = None,
                 max_attempts: int = 2, conn=None) -> Analysis
```

- Araçlı durumda modele yalnız o durumun araçları sunulur. Önerilen çağrı sırayla denetlenir: şema (`validate_tool_call`), izin (`ALLOWED_TOOLS[state]`), niyet uyumu (hisse/sektör/tarih niyettekiyle aynı). Reddedilen çağrı `allowed=False` ile kaydedilir ve modele kısa bir hata mesajı döner.
- `max_attempts` denemede geçerli çağrı gelmezse harness, niyetten türetilen kanonik çağrıyı kendisi yapar (`source="harness"`). Bu, deney C'de "harness müdahalesi" olarak sayılır.
- Harness'in kendi çağırdığı durumlar (`CHECK_DATA_QUALITY`, `BUILD_EVIDENCE`, `RISK_GATE`) model turu içermez.
- Kapı `HARD_BLOCK` verirse `GENERATE_EXPLANATION` atlanır; sonuç `ANALYSIS_UNSAFE`.

- [ ] Kalan testler (senaryolu sahte istemci): doğru yol baştan sona; izinsiz araç reddi ve sayımı; başka hisse için çağrı reddi; metin cevabı → yeniden iste → geri düşüş; tavsiye sorusunda sıfır araç çağrısı; evren dışı hisse → `ANALYSIS_UNSAFE`; her durumda kayıt; durum sırası rotayla aynı.
- [ ] FAIL → uygulama → PASS. Commit: `feat: stateful harness with tool permissions`.

### Task 5: Kanıt oluşturucu (EC-043)

**Files:** Create `harness/evidence.py`, `tests/test_evidence.py`. Modify sunucu (`build_evidence_bundle`).

```python
@dataclass(frozen=True)
class Evidence:
    label: str; tool: str; result_id: str; field: str; value: object; sentence: str; committed: bool
TEMPLATES: dict[tuple[str, str], dict[str, str]]     # (araç, alan) → {"tr": …, "en": …}
def build_evidence(analysis: Analysis, *, language: str) -> list[Evidence]
def committed_set(evidence: Sequence[Evidence], scenario: str) -> list[Evidence]
```

- Her şablon tek bir alanı tek bir cümleye çevirir ve alanın anlamını söyler ("26 olayın 16'sı başarılıydı", "başarı oranı %61,54"). Sayı, araç çıktısından biçimlendirilerek kopyalanır; şablon dışında cümle üretilmez. (Sprint 2 bulgusu: model doğru sayıyı yanlış etikete bağlıyor.)
- `committed_set`, senaryonun asgari kanıt kuralına göre seçer: örneğin `SECTOR_LAGGARD` için sektör medyanı, lag skoru, sektörün endekse göre durumu, teknik durum ve backtest özeti.
- Uyarılar (`sample_warning`, `coverage_warning`, bayraklar) kanıt maddesi olarak değil, uyarı listesi olarak taşınır.

- [ ] Kalan testler: her şablon için TR ve EN cümlede yalnız o alanın sayısı var (`number_check` ile); `None` alan cümle üretmez; etiketler `E1…En` ardışık; committed set kuralı her senaryoda; aynı analiz iki kez aynı kümeyi verir.
- [ ] FAIL → uygulama → PASS. Commit: `feat: evidence builder with templated sentences`.

### Task 6: Kalite kapısı ve etiket uygunluğu (EC-044, EC-045)

**Files:** Create `harness/gate.py`, `harness/actions.py`, `tests/test_gate.py`, `tests/test_actions.py`.

```python
def quality_gate(analysis: Analysis, evidence: Sequence[Evidence]) -> GateResult   # status, hard_blocks, warnings
def eligible_actions(analysis, evidence, gate) -> tuple[str, ...]
```

- Sert bloklar (tasarım §8): evren dışı sembol; kalite denetiminde `hard` bulgu; `info_date > signal_date` olan işlem; `known_from > as_of` olan tablo; boş veri. Yumuşak uyarılar: örneklem uyarıları, kapsama uyarısı, peer grubu küçük, makro seri eksik, SASA hacim uyarısı, takvim bayrakları.
- Etiket uygunluğu (kod, model değil): `HARD_BLOCK` → yalnız `ANALYSIS_UNSAFE`. Aday etiketleri için backtest çalışmış olmalı ve committed set tam olmalı. Backtest `UNDERPERFORMS_BUY_AND_HOLD` ya da `FEW_TRADES` taşıyorsa aday etiketi yerine en çok `WATCH`/`INVESTIGATE`. Anlamlı bulunmayan takvim örüntüsü → `REJECT_SIGNAL`. Kanıt eksikse `INVESTIGATE`.

- [ ] Kalan testler: her sert blok için tetikleyen bir analiz; her etiket için uygunluk tablosu; kapı kararı aynı girdide aynı.
- [ ] FAIL → uygulama → PASS. Commit: `feat: quality gate and evidence-based action eligibility`.

### Task 7: Çıktı doğrulayıcı (EC-045)

**Files:** Create `harness/validator.py`, `tests/test_validator.py`. Modify `machine.py` (`GENERATE_EXPLANATION`).

```python
def validate_explanation(text: str, *, action: str, eligible: Sequence[str], evidence: Sequence[Evidence],
                         question: str, language: str) -> list[str]        # boş liste = geçti
```

Denetimler: etiket uygun kümede; her sayı ve tarih committed kümede ya da soruda (`number_check`); her cümle en az bir `E` numarasına atıf yapıyor ve atıf kümede var; tavsiye dili yok (al/sat/tut tavsiyesi, "garanti", "kesin yükselir" …); zorunlu uyarı satırı var; kanıt kümesinde geçmeyen şirket adı yok. Model çıktısı şemaya kısıtlı JSON'dur: `{"action": …, "explanation": …}`.

- [ ] Kalan testler: her kural için geçen ve kalan bir örnek (TR/EN); bir kez yeniden isteme; ikinci başarısızlıkta kanıt kümesi + `INVESTIGATE`.
- [ ] FAIL → uygulama → PASS. Commit: `feat: output validator and finite action space`.

### Task 8: İnsan incelemesi, günlük, replay (EC-048)

**Files:** Create `harness/review.py`, `harness/replay.py`, `tests/test_review.py`, `tests/test_replay.py`.

- Günlük: §28'in her alanı (`storage.db.DECISION_LOG_FIELDS`) doldurulur; test, tamamlanmış bir analizde hiçbir alanın boş kalmadığını doğrular (uygulanamaz alanlar açıkça `"not applicable"`).
- İnceleme: `uv run python -m bist_harness.harness.review <analysis_id> ACCEPT|MODIFY|REJECT "gerekçe"`.
- Replay: kayıtlı çağrıları aynı `snapshot_id` ile yeniden çalıştırır; `snapshot verify` ve her `result_id` karşılaştırılır; sonuç `MATCH` ya da `MISMATCH` ve farklı çağrıların listesi. Model yeniden çağrılmaz.

- [ ] Testler → uygulama → PASS. Commit: `feat: human review, decision log and replay`.

### Task 9: Görülmemiş soru seti ve puanlayıcı (EC-060)

**Files:** Create `eval/questions.jsonl`, `eval/metrics.py`, `eval/run_eval.py`, `tests/test_metrics.py`.

- 120 soru: dört zorunlu senaryodan 20'şer (yarısı Türkçe), 20 tuzak (tavsiye, tahmin, evren dışı hisse, gelecek tarih, ters aralık, yazım hatalı hisse), 20 belirsiz ya da iki araç gerektiren soru. İnce ayar verisiyle (Sprint 5) hiçbir soru paylaşılmaz; set bu sprintte dondurulur ve özeti kaydedilir.
- Ölçütler: sayısal halüsinasyon oranı, hatalı araç çağrısı oranı, desteksiz sonuç oranı, kanıt tamlığı, tekrarlanabilirlik (aynı soru iki kez → aynı kanıt kümesi ve etiket), kural ihlali sayısı, araç çağrısı sayısı, gecikme.
- Koşucu, deney A–E düzenlerini (istem §30) aynı modelle çalıştırır: A ham model, B araçlı, C durumlu, D kanıt ve kapı, E bellek ve insan incelemesi.

- [ ] Testler (elle kurulmuş analiz kayıtlarından ölçüt hesabı) → uygulama → PASS. Commit: `feat: unseen question set and grading metrics`.

### Task 10: Canlı uçtan uca deneme ve kapanış

- [ ] Dizüstünde `qwen3.5:2b` ile (RTX 5070 açıksa seçilen modelle) dört senaryodan birer soru ve iki tuzak soru; sonuç `docs/results/2026-11-20-harness-live.md`.
- [ ] `uv run pytest -q`, `uv run ruff check .` temiz; bağımsız inceleme; bulgular tek geçişte düzeltilir.
- [ ] Karar günlüğü, kullanım günlüğü, `git tag sprint-4`, Notion kartları, Sprint 5 planı (ince ayar verisi: harness kayıtlarından üretilir).
