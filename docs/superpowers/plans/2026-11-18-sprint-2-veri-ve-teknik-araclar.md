# Sprint 2 — Veri ve Teknik Araçlar: Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 19 Kasım sonunda sürümlenmiş bir fiyat anlık görüntüsü, veri kalite denetimleri, hocanın betikleriyle sayısal olarak eşleşen gösterge seti, dokuz olay ailesi, sektör göreli güç sıralaması ve takvim örüntü testi hazır olsun; bunlar MCP aracı olarak çağrılabilsin; RTX 5070'te deneme eğitimi yapılmış ve temel model seçilmiş olsun.

**Architecture:** Sprint 1'in düzeni korunur: hesaplar `src/bist_harness/tools/` altında düz fonksiyonlardır, `mcp_server/server.py` onları ince bir doğrulama katmanıyla sunar. Veri artık hisse başına tek dosyadan değil, kimliği olan bir anlık görüntüden (snapshot) okunur; her araç çıktısı o kimliği taşır. Hocanın betiklerinde bulunan her hesap, o betiğin kendi fonksiyonuyla karşılaştırılarak test edilir.

**Tech Stack:** Sprint 1 ile aynı (Python 3.12, uv, pandas, numpy, yfinance, pyarrow, mcp 2.x `MCPServer`, pytest, ruff). Yeni bağımlılık: yok (SQLite standart kitaplıktan). Deneme eğitimi için gerekenler yalnız RTX 5070'li makinede kurulur ve bu repoya bağımlılık olarak girmez.

**Spec:** `docs/superpowers/specs/2026-11-17-bist-harness-design.md`; istem §5–§13, §22, §26; `reference/instructor/` altındaki iki betik. Kartlar: Notion Sprint S2 (EC-006, 011, 012, 013, 018, 019, 020, 021, 022, 023, 024) ve Sprint 1'den devreden EC-005 kalanı.

## Global Constraints

Sprint 1 planındaki kısıtların tamamı geçerlidir. Ek olarak:

- Hocanın betiğinde tanımlı her gösterge ve olay, **o betiğin fonksiyonuyla** aynı sentetik veride karşılaştırılır (`tests/instructor.py`). Sayısal eşitlik 2 ondalıkta aranır.
- Her gösterge ve olay için "geleceğe bakmama" testi vardır: veri t gününde kesildiğinde t ve öncesinin değerleri değişmez.
- Araçlar ham seri döndürmez (karar K-007). Liste dönen araçlarda en çok 12 satır döner.
- Yüzdeler ve fiyatlar araçta 2 ondalığa yuvarlanır.
- İşlem maliyeti varsayılanı 0.001 (hocanın Senaryo 2 betiği). Zaman sıralı ayrım oranı 0.70.
- Rastgelelik kullanan her hesap (permütasyon testi) `seed=42` ile çalışır.
- Evren dışı referans hisseler yalnız sektör medyanı için kullanılır; araçlar onları analiz hedefi olarak kabul etmez (`UNKNOWN_TICKER`).
- `tools/schemas.py` değişirse `tests/test_schemas.py` ve `bakeoff/cases.jsonl` aynı commit'te güncellenir.

## Review Focus

1. **Anlık görüntü yokken araç çağrılıyor.** Araç `DATA_UNAVAILABLE` döndürür ve hangi komutun çalıştırılacağını söyler; ağa kendiliğinden gitmez. Test: Task 1.
2. **Kısa geçmişli hisse** (yeni halka arz, 60 günden az veri). Göstergeler `None` döner, olay sayısı 0 ve `Very small sample size` uyarısı gelir; hata fırlatılmaz. Test: Task 4 ve Task 6.
3. **Bölünme ya da bedelli kaynaklı fiyat sıçraması.** `auto_adjust=True` çoğunu düzeltir; düzeltilmemiş %40'tan büyük günlük hareket kalite denetiminde `PRICE_JUMP` uyarısı üretir. Test: Task 3.
4. **Peer grubunda hedef hisse dışında 2'den az üye kalıyor** (verisi gelmeyen referanslar). Araç sıralamayı yine döndürür ama `PEER_GROUP_TOO_SMALL` uyarısı ekler ve `sector_strong` alanı `None` olur. Test: Task 7.
5. **Tatil yüzünden eksik günü olan hafta.** Haftalık örüntüler yalnız beş işlem günü tam olan haftalarda sayılır (hocanın betiği); eksik haftalar sayısı çıktıda raporlanır. Test: Task 8.

## Dosya yapısı (yeni ve değişen)

```
data/reference/peer_groups.csv            # yeni: sektör grubu, hisse, rol
data/snapshots/<snapshot_id>/*.parquet    # gitignore
data/snapshots/<snapshot_id>/manifest.json
data/snapshots/ACTIVE                     # etkin anlık görüntünün kimliği
docs/data_dictionary.md                   # yeni
src/bist_harness/
  data/snapshot.py          # build_snapshot, load_history, active_snapshot_id, Manifest
  data/peers.py             # load_peer_groups, peer_group_of, PeerGroup
  quality/checks.py         # check_price_series, Finding
  storage/db.py             # connect, SCHEMA_VERSION, tablolar
  tools/indicators.py       # SMA, EMA, MACD, Bollinger, RSI, KAMA, ATR, Supertrend, Ichimoku, hacim
  tools/support_resistance.py
  tools/events.py           # dokuz olay ailesi, summarize_events, piyasa durumu kaydı
  tools/reversal.py         # Sprint 1 fonksiyonu events.py üzerine taşınır, adı korunur
  tools/sector.py           # rank_sector_relative_strength
  tools/calendar_patterns.py
  mcp_server/server.py      # yeni araçlar eklenir, load_history anlık görüntüden okur
```

## Sıra ve süre hedefleri

| Görev | Kart | Hedef süre | RTX 5070 | Burak gerekir mi |
| --- | --- | --- | --- | --- |
| 1 Anlık görüntü ve manifest | EC-012 | 90 dk | Hayır | Hayır |
| 2 Peer grupları | EC-011 | 60 dk | Hayır | Grup listesini onayla |
| 3 Veri kalite denetimleri | EC-013 | 75 dk | Hayır | Hayır |
| 4 Göstergeler | EC-020 | 150 dk | Hayır | Hayır |
| 5 Destek ve direnç | EC-021 | 75 dk | Hayır | Hayır |
| 6 Olay ailesi çerçevesi | EC-022 | 180 dk | Hayır | Olay tanımlarını onayla |
| 7 Sektör göreli güç | EC-023 | 75 dk | Hayır | Hayır |
| 8 Takvim örüntüleri | EC-024 | 150 dk | Hayır | Hayır |
| 9 Depolama şeması | EC-019 | 60 dk | Hayır | Hayır |
| 10 Veri sözlüğü | EC-018 | 45 dk | Hayır | Hayır |
| 11 Model seçimi ve deneme eğitimi | EC-005, EC-006 | 120 dk | **Evet** | **Evet** |
| 12 Sprint kapanışı | — | 20 dk | Hayır | Kartları gözden geçir |

Görev 11, makine açıldığı anda öne alınır; diğer görevler ona bağlı değildir.

---

### Task 1: Anlık görüntü ve manifest (EC-012)

**Files:** Create `src/bist_harness/data/snapshot.py`, `tests/test_snapshot.py`. Modify `src/bist_harness/mcp_server/server.py` (`load_history`, `get_index_history`), `tests/test_mcp_server.py`.

**Interfaces — Produces:**

```python
INDEX_SYMBOLS = {"XU100": "XU100.IS", "XU030": "XU030.IS", "XBANK": "XBANK.IS", "XUSIN": "XUSIN.IS"}


@dataclass(frozen=True)
class SeriesInfo:  # one manifest entry
    symbol: str
    rows: int
    first_date: str
    last_date: str
    sha256: str


@dataclass(frozen=True)
class Manifest:
    snapshot_id: str
    created_at: str
    source: str
    start: str
    series: tuple[SeriesInfo, ...]


def build_snapshot(
    symbols: Iterable[str],
    *,
    start: str = "2020-01-01",
    snapshot_id: str | None = None,
    root: Path | None = None,
    downloader: Downloader | None = None,
) -> Manifest: ...
def active_snapshot_id(root: Path | None = None) -> str: ...  # raises DataUnavailableError if none
def load_history(
    symbol: str, *, snapshot_id: str | None = None, root: Path | None = None
) -> pd.DataFrame: ...
def load_manifest(snapshot_id: str | None = None, root: Path | None = None) -> Manifest: ...
```

- `snapshot_id` varsayılanı `YYYYMMDD-HHMM`. `build_snapshot` bittiğinde `ACTIVE` dosyasını yeni kimlikle yazar.
- Bir sembol veri vermezse manifestte `rows=0` ile yer alır ve dosya yazılmaz; işlem durmaz.
- CLI: `uv run python -m bist_harness.data.snapshot build` (evren + referans hisseler + dört endeks).
- Yahoo'da yalnız XU100, XU030, XBANK ve XUSIN endekslerinin geçmişi var (17 Kasım'da doğrulandı); diğer sektör endeksleri için sektör getirisi peer grubundan hesaplanır.

- [ ] **Step 1: Kalan testleri yaz** — sahte indiriciyle: iki sembollü anlık görüntü iki parquet ve bir manifest üretir; `ACTIVE` güncellenir; `load_history` yazılanı geri okur; boş dönen sembol `rows == 0` ile manifestte ve dosyası yok; aynı veriyle iki kurulumun `sha256` değerleri eşit; `ACTIVE` yokken `load_history` → `DataUnavailableError` ve mesajda `snapshot build` geçer; `snapshot_id` açıkça verilirse eski sürüm okunur.
- [ ] **Step 2:** FAIL → `snapshot.py` → PASS.
- [ ] **Step 3: MCP testi** — her araç çıktısında `snapshot_id` var ve `result_id` ona bağlı (aynı argüman, farklı anlık görüntü → farklı `result_id`); `get_index_history("XU100", …)` `get_stock_history` ile aynı alanları `index` anahtarıyla döndürür; listede olmayan endeks → `UNKNOWN_INDEX`. FAIL → sunucuyu güncelle → PASS.
- [ ] **Step 4 (ağ):** Gerçek anlık görüntüyü kur; manifesti `docs/results/` altına özetle (sembol sayısı, boş gelenler, tarih aralığı).
- [ ] **Step 5:** Commit: `feat: versioned market data snapshot and index history tool`.

---

### Task 2: Peer grupları (EC-011)

**Files:** Create `data/reference/peer_groups.csv`, `src/bist_harness/data/peers.py`, `tests/test_peers.py`.

**Karar önerisi (Burak onaylar):** sektör medyanı, evrendeki hisseler ile aşağıdaki referans hisselerden hesaplanır. Referansların tamamı 17 Kasım'da Yahoo'da 2020'den beri veriyle doğrulandı.

| Grup | Evrendeki hisseler | Referans hisseler |
| --- | --- | --- |
| Banking | AKBNK | GARAN, ISCTR, YKBNK, HALKB, VAKBN |
| Defense / Vehicles | ASELS | OTKAR, KATMR, TTRAK |
| Energy / Petrochemicals | TUPRS, PETKM | AYGAZ, AKSA |
| Holding | KCHOL | SAHOL, DOHOL, ALARK, AGHOL |
| Food & Beverage | CCOLA | AEFES, ULKER, TATGD |
| Retail | BIMAS, MGROS, MAVI | SOKM, VAKKO |
| Airlines / Transport | THYAO, PGSUS | TAVHL, CLEBI |
| Steel | EREGL, KRDMD | ISDMR, BRSAN |
| Telecom | TCELL, TTKOM | — (2 üye; uyarıyla) |
| Chemicals / Fertilizer | SASA, GUBRF | ALKIM, HEKTS, BAGFS |
| Mining | TRALT | TRMET, TRENJ |
| Automotive | FROTO, TOASO | DOAS |
| Construction | ENKAI | TKFEN |
| Healthcare / Pharma | MPARK, ECILC | LKMNH, DEVA, SELEC |
| Real Estate | EKGYO | ISGYO, TRGYO, SNGYO, HLGYO |
| Insurance | TURSG | ANSGR, AKGRT, AGESA, RAYSG |
| Electric Utilities | ENJSA, AKSEN | ZOREN, ODAS |
| Cement | OYAKC | CIMSA, AKCNS, NUHCM, BTCIM |
| Brokerage | ISMEN | GEDIK, INFO, OSMEN |
| Durables | ARCLK | VESTL, VESBE |

**Interfaces — Produces:**

```python
@dataclass(frozen=True)
class PeerGroup:
    name: str
    universe: tuple[str, ...]
    reference: tuple[str, ...]

    @property
    def members(self) -> tuple[str, ...]: ...


MIN_PEERS = 3  # members including the target


def load_peer_groups(path: Path | None = None) -> dict[str, PeerGroup]: ...
def peer_group_of(ticker: str) -> PeerGroup: ...  # KeyError for non-universe tickers
def resolve_sector(name: str) -> PeerGroup: ...  # accepts group name or a universe sector label
def all_symbols() -> list[str]: ...  # universe + reference, unique
```

- `resolve_sector`, evren dosyasındaki sektör etiketlerini de kabul eder (ör. `Basic Metals / Steel` → `Steel`), böylece model her iki adı da kullanabilir.

- [ ] **Step 1: Kalan testler** — 30 evren hissesinin her biri tam bir gruba ait; hiçbir referans hisse evrende değil; hiçbir hisse iki grupta değil; `Telecom` dışındaki grupların üye sayısı ≥ 3; `resolve_sector("Basic Metals / Steel").name == "Steel"`; `peer_group_of("GARAN")` → `KeyError`.
- [ ] **Step 2:** FAIL → CSV ve `peers.py` → PASS.
- [ ] **Step 3 (Burak):** Tabloyu gözden geçir; değiştirmek istediğin grup varsa CSV'yi düzelt, testler korur.
- [ ] **Step 4:** Commit: `feat: sector peer groups with reference stocks`.

---

### Task 3: Veri kalite denetimleri (EC-013)

**Files:** Create `src/bist_harness/quality/__init__.py`, `quality/checks.py`, `tests/test_quality.py`.

**Interfaces — Produces:**

```python
@dataclass(frozen=True)
class Finding:
    code: str
    severity: Literal["hard", "soft"]
    message: str
    count: int = 1


def check_price_series(
    df: pd.DataFrame,
    *,
    as_of: str,
    expected_days: pd.DatetimeIndex | None = None,
    min_rows: int = 60,
    stale_after_days: int = 5,
) -> list[Finding]: ...
```

| Kod | Önem | Koşul |
| --- | --- | --- |
| `EMPTY_SERIES` | hard | Hiç satır yok |
| `SHORT_HISTORY` | soft | `min_rows`'tan az satır |
| `DUPLICATE_DATES` | hard | Yinelenen tarih |
| `NON_MONOTONIC_INDEX` | hard | Tarihler sıralı değil |
| `NON_POSITIVE_PRICE` | hard | Sıfır ya da negatif fiyat |
| `OHLC_INCONSISTENT` | hard | `High < max(Open, Close)` ya da `Low > min(Open, Close)` |
| `PRICE_JUMP` | soft | Günlük kapanış değişimi mutlak değerce %40'tan büyük |
| `ZERO_VOLUME` | soft | Sıfır hacimli gün |
| `MISSING_DAYS` | soft | `expected_days` içinde olup seride olmayan gün (endeks takvimine göre) |
| `STALE_DATA` | soft | Son satır `as_of` tarihinden `stale_after_days` işlem gününden eski |
| `FUTURE_ROWS` | hard | `as_of` tarihinden sonraki satır |

- [ ] **Step 1: Kalan testler** — temiz seri → boş liste; her kod için onu tetikleyen bilerek bozulmuş bir seri ve `code`, `severity`, `count` doğrulaması; birden çok sorun aynı anda raporlanır.
- [ ] **Step 2:** FAIL → `checks.py` → PASS.
- [ ] **Step 3 (ağ):** Etkin anlık görüntüdeki bütün seriler için rapor: `docs/results/2026-11-18-data-quality.md` (sembol, bulgu kodları, sayılar).
- [ ] **Step 4:** Commit: `feat: price-series data quality checks`.

---

### Task 4: Göstergeler (EC-020)

**Files:** Create `src/bist_harness/tools/indicators.py`, `tests/test_indicators.py`. Modify `mcp_server/server.py` (`calculate_indicators`), `tests/test_mcp_server.py`.

**Interfaces — Produces** (her fonksiyon `df`'in kopyasına sütun ekler; sütun adları hocanın betiğiyle aynıdır):

```python
def add_sma(df, window: int = 20) -> pd.DataFrame          # SMA_<window>
def add_ema(df, span: int = 20) -> pd.DataFrame            # EMA_<span>
def add_macd(df, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame   # MACD, MACD_Signal, MACD_Hist
def add_bollinger_bands(df, window: int = 20, num_std: float = 2) -> pd.DataFrame   # BB_Middle, BB_Upper, BB_Lower
def add_rsi(df, period: int = 14) -> pd.DataFrame          # RSI (Wilder)
def add_kama(df, er_period: int = 10, fast: int = 2, slow: int = 30) -> pd.DataFrame  # KAMA, KAMA_Slope
def add_atr(df, period: int = 10) -> pd.DataFrame          # ATR
def add_supertrend(df, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame   # betikteki sütunlar
def add_ichimoku(df) -> pd.DataFrame                       # 9/26/52, betikteki sütunlar
def add_volume_features(df, window: int = 20) -> pd.DataFrame                       # betikteki sütunlar
def add_all_indicators(df) -> pd.DataFrame
def indicator_state(df, indicators: Sequence[str]) -> dict   # son günün değerleri ve durum etiketleri
```

- Bollinger, RSI, KAMA, ATR, Supertrend, Ichimoku ve hacim özelliklerinin sütun adları ve tanımları betikten birebir alınır; önce betikteki fonksiyon okunur, sonra test yazılır.
- Ichimoku'nun ileri kaydırılan sütunları (Senkou) yalnız çizim içindir. Durum etiketi ("Above Cloud", "In Cloud", "Below Cloud") bugünün fiyatını **bugün için geçmişte hesaplanmış** bulutla karşılaştırır; ileri kaydırılmış değer hiçbir sinyalde t gününden sonraki fiyatı kullanmaz. Geriye kaydırılan Chikou sinyalde kullanılmaz.
- `indicator_state` etiketleri: KAMA eğimi `Rising / Flattening / Falling` (mutlak eğim, kapanışın %0,05'inden küçükse `Flattening`), Supertrend `Bullish / Bearish`, Ichimoku üç durum, RSI `Local Low / Local High / Neutral` (betikteki yerel dip tanımı ve aynası), hacim `High / Normal / Low` (20 günlük ortalamanın 1,5 katından büyük / 0,5 katından küçük).

- [ ] **Step 1: Kalan testler** — betikte bulunan yedi fonksiyonun her biri için: üç farklı tohumla üretilmiş sentetik OHLCV'de bizim çıktımız betiğin çıktısına eşit (`pd.testing.assert_frame_equal`, `check_exact=False, rtol=1e-9`). SMA, EMA ve MACD için elle hesaplanmış 6 satırlık örnek. Her fonksiyon için kesme testi: `f(df.iloc[:k])` ile `f(df).iloc[:k]` eşit (Ichimoku'nun ileri kaydırılmış sütunları hariç; onlar için ayrı test: durum etiketi kesmeden etkilenmez). 30 satırlık seri → hata yok, uzun pencereli sütunlar `NaN`.
- [ ] **Step 2:** FAIL → `indicators.py` → PASS.
- [ ] **Step 3: MCP** — `calculate_indicators(ticker, start, end, indicators)` son günün değerlerini ve durum etiketlerini döndürür; bilinmeyen gösterge adı → `INVALID_ARGUMENT`; `indicators` boşsa hepsi. Test → uygulama.
- [ ] **Step 4:** Commit: `feat: technical indicators matching the instructor script`.

---

### Task 5: Destek ve direnç (EC-021)

**Files:** Create `src/bist_harness/tools/support_resistance.py`, `tests/test_support_resistance.py`. Modify sunucu ve testi.

**Interfaces — Produces:**

```python
def find_pivots(df, window: int = 5) -> pd.DataFrame      # sütunlar: pivot_high, pivot_low, known_from
def find_support_resistance(df, *, window: int = 5, tolerance: float = 0.015, as_of: str | None = None,
                            max_levels: int = 6) -> list[dict]
    # her seviye: level, kind ("support"|"resistance"), touches, recent_touches, last_touch_date, strength
```

- Yöntem 1. hafta slaytından: pivot, `2*window+1` günlük ortalanmış pencerede en yüksek ya da en düşük; pivotlar `tolerance` oranında kümelenir; güç = `touches*1.0 + recent_touches*1.5 + high_volume_reactions*1.2 + reversal_strength*1.0`.
- Ortalanmış pencere geleceği kullanır. Bu yüzden her pivotun `known_from` tarihi, pivot gününden `window` işlem günü sonrasıdır; `as_of` verildiğinde yalnız `known_from <= as_of` olan pivotlar kullanılır.
- "Recent" son 60 işlem günü; "high volume" 20 günlük ortalamanın 1,5 katı.
- `kind`: seviye son kapanışın altındaysa `support`, üstündeyse `resistance`.

- [ ] **Step 1: Kalan testler** — elle kurulmuş zikzak seride beklenen pivot günleri; iki yakın pivot tek seviyede kümelenir, uzak olan ayrı kalır; `as_of` pivot gününden `window - 1` gün sonraysa pivot görünmez, `window` gün sonraysa görünür; seviye sayısı `max_levels`'ı aşmaz ve güce göre sıralıdır; 15 satırlık seri → boş liste.
- [ ] **Step 2:** FAIL → uygulama → PASS. MCP aracı ve testi.
- [ ] **Step 3:** Commit: `feat: support and resistance levels without look-ahead`.

---

### Task 6: Olay ailesi çerçevesi (EC-022)

**Files:** Create `src/bist_harness/tools/events.py`, `tests/test_events.py`. Modify `tools/reversal.py` (Sprint 1 fonksiyonu `events.py`'yi çağırır, adı ve çıktısı korunur), `tools/schemas.py` (`direction` parametresi), `tests/test_schemas.py`, sunucu ve testi.

**Şema değişikliği:** `detect_reversal_events` aracına isteğe bağlı `direction` ∈ `BULLISH, BEARISH` eklenir (varsayılan `BULLISH`). Tek yönlü olay türlerinde yok sayılır ve çıktıda gerçek yön yazılır.

**Olay tanımları (t gününün kapanışında, yalnız t'ye kadarki veriyle):**

| `event_type` | BULLISH | BEARISH | Kaynak |
| --- | --- | --- | --- |
| `BOLLINGER_LOWER_TOUCH` | `Close[t-1] <= BB_Lower[t-1]` ve `Close[t] > BB_Lower[t]` | — | Betik |
| `BOLLINGER_UPPER_TOUCH` | — | `Close[t-1] >= BB_Upper[t-1]` ve `Close[t] < BB_Upper[t]` | Betiğin aynası |
| `BOLLINGER_MIDDLE_TEST` | Önceki 5 kapanış orta bandın üstünde ve `Low[t] <= BB_Middle[t]` | Önceki 5 kapanış altında ve `High[t] >= BB_Middle[t]` | Bu plan |
| `RSI_LOCAL_TROUGH` | `RSI[t-1] < RSI[t-2]`, `RSI[t-1] < RSI[t]`, `RSI[t-1] < 40` | — | Betik |
| `RSI_LOCAL_PEAK` | — | `RSI[t-1] > RSI[t-2]`, `RSI[t-1] > RSI[t]`, `RSI[t-1] > 60` | Betiğin aynası |
| `SUPERTREND_FLIP` | Supertrend ayıdan boğaya döner | Boğadan ayıya döner | Betik (boğa), aynası |
| `KAMA_TURN` | `KAMA_Slope[t-1] <= 0` ve `KAMA_Slope[t] > 0` | Aynası | Betik (boğa), aynası |
| `ICHIMOKU_BREAKOUT` | Kapanış bulutun üstüne çıkar | Kapanış bulutun altına iner | Betik (boğa), aynası |
| `SUPPORT_RESISTANCE_TOUCH` | `Low[t]`, t'de bilinen bir desteğin `tolerance` yakınında ve `Close[t]` seviyenin üstünde | `High[t]` bir direncin yakınında ve `Close[t]` altında | Bu plan |

- Başarı: BULLISH olayda ileri getiri `> 0`, BEARISH olayda `< 0`. `BOLLINGER_MIDDLE_TEST` için başarı "devam"dır (BULLISH: ileri getiri `> 0`); çıktıda `continuation_count` ve `rejection_count` ayrıca yer alır. `ICHIMOKU_BREAKOUT` çıktısında `rejection_count` (kırılımdan sonraki `forward_days` içinde kapanışın buluta geri dönmesi) yer alır.
- Dönüş gücü (§8): BULLISH için `max(High[t+1..t+k]) / Close[t] - 1`, BEARISH için `1 - min(Low[t+1..t+k]) / Close[t]`; çıktıda ortalama ve medyan (`average_reversal_strength_pct`, `median_reversal_strength_pct`).

**Interfaces — Produces:**

```python
EVENT_TYPES: tuple[str, ...]                     # schemas.REVERSAL_EVENT_TYPES ile aynı
def event_mask(df_with_indicators, event_type: str, direction: str = "BULLISH", **kw) -> pd.Series   # bool
def market_state(df_with_indicators, day) -> dict
    # rsi_state, supertrend_state, kama_slope, ichimoku_state, volume_regime  (§8 örnek kaydı)
def summarize_events(df, mask: pd.Series, *, direction: str, forward_days: int = 5,
                     since: str | None = None, success_threshold: float = 0.0) -> dict
    # event_count, successful_events, success_rate_pct, average_forward_return_pct,
    # median_forward_return_pct, average_reversal_strength_pct, median_reversal_strength_pct, sample_warning
def event_records(df, mask, *, ticker: str, event_type: str, direction: str,
                  horizons: Sequence[int] = (1, 3, 5, 10), since: str | None = None) -> pd.DataFrame
    # satır başına §8 kaydı: ticker, event, date, piyasa durumu alanları, forward_<h>d_return_pct, reversal_strength_pct
def detect_events(df, event_type, direction="BULLISH", *, forward_days=5, since=None) -> dict
```

- [ ] **Step 1: Kalan testler** — betikte bulunan beş olay (`Bollinger_Reversal`, `RSI_Local_Trough`, `KAMA_Bullish_Turn`, `Supertrend_Bullish_Flip`, `Ichimoku_Bullish_Breakout`) için bizim maskemiz betiğin sütununa üç tohumda eşit ve `summarize_events` betiğin `event_summary` değerlerine 2 ondalıkta eşit. Ayna olaylar için: fiyat serisi `1/Close` ile ters çevrildiğinde BEARISH maske, özgün serinin BULLISH maskesine eşit (uygulanabilen türlerde). Her tür için kesme testi. `BOLLINGER_MIDDLE_TEST` ve `SUPPORT_RESISTANCE_TOUCH` için elle kurulmuş küçük seride beklenen olay günleri. `event_records` sütunları §8 örneğindeki alanları içerir. Olaysız seri → sayım 0, istatistikler `None`.
- [ ] **Step 2:** FAIL → `events.py` → PASS. `reversal.py` içindeki Sprint 1 fonksiyonu `detect_events` üzerine taşınır; Sprint 1 testleri değişmeden geçer.
- [ ] **Step 3: MCP** — dokuz türün hepsi çalışır; `NOT_IMPLEMENTED` yolu kalkar ve ilgili test, geçersiz `direction` → `INVALID_ARGUMENT` testine dönüşür. `bakeoff/cases.jsonl` etkilenmez (argümanlar alt küme).
- [ ] **Step 4 (Burak):** Tablodaki "Bu plan" kaynaklı iki tanımı ve ayna tanımlarını onayla.
- [ ] **Step 5:** Commit: `feat: nine reversal event families with market-state records`.

---

### Task 7: Sektör göreli güç (EC-023)

**Files:** Create `src/bist_harness/tools/sector.py`, `tests/test_sector.py`. Modify sunucu ve testi.

**Interfaces — Produces:**

```python
def rank_sector_relative_strength(closes: dict[str, pd.Series], group: PeerGroup, *, horizon_days: int,
                                  as_of: str, benchmark: pd.Series | None = None) -> dict
```

Çıktı: `sector`, `horizon_days`, `as_of`, `sector_median_return_pct`, `benchmark_return_pct`, `sector_strong` (medyan > XU100 getirisi; hesaplanamıyorsa `None`), `members` (en çok 12 satır; `ticker`, `role`, `return_pct`, `lag_score_pct = return − sector median`, `rank`), `laggards` ve `leaders` (yalnız evren hisseleri), `warnings`.

- Getiri: `as_of` tarihindeki ya da ondan önceki son kapanış ile `horizon_days` işlem günü önceki kapanış arasında. `as_of` sonrasındaki hiçbir fiyat kullanılmaz.
- Verisi eksik üye sıralamadan çıkarılır ve `warnings` içine yazılır. Hedef dışında 2'den az üye kalırsa `PEER_GROUP_TOO_SMALL`.

- [ ] **Step 1: Kalan testler** — istemdeki banka örneği sentetik olarak kurulur (üç banka +%11 ile +%16, biri +%3): medyan, lag skoru ve laggard doğru; referans hisseler `leaders`/`laggards` içinde yer almaz; `as_of` sonrasına eklenen sahte fiyatlar sonucu değiştirmez; eksik üyeli grup uyarı üretir; `sector_strong` XU100'e göre doğru.
- [ ] **Step 2:** FAIL → uygulama → PASS. MCP aracı (`sector` için `resolve_sector`; bilinmeyen sektör → `UNKNOWN_SECTOR`) ve testi.
- [ ] **Step 3:** Commit: `feat: sector relative strength ranking`.

---

### Task 8: Takvim örüntüleri (EC-024)

**Files:** Create `src/bist_harness/tools/calendar_patterns.py`, `tests/test_calendar_patterns.py`. Modify sunucu ve testi.

**Doğrulanmış bulgu (karar K-014):** Hocanın Senaryo 2 betiğinde `detect_pattern`, örüntüyü Pzt, Sal, Çar `< 0` ve Per, Cum `> 0` olarak tanımlıyor; `pattern_summary` aynı haftaların Perşembe–Cuma getirisini "örüntü sonrası getiri" olarak raporluyor. Bu getiri tanım gereği pozitiftir. Bizim tanımımız koşulu yalnız önceki günlere dayandırır; betiğin sıklık sayısı (`Pattern occurrences`) ayrıca `instructor_full_pattern_count` alanında raporlanır ve betiğin `pattern_summary` çıktısıyla karşılaştırılarak test edilir.

**Örüntüler:**

| `pattern` | Koşul (yalnız geçmiş günler) | Ölçülen sonuç |
| --- | --- | --- |
| `WEEKDAY_MEANS` | — | Haftanın her günü için ortalama, medyan, pozitif gün oranı |
| `MON_WEAK_FRI_STRONG` | Pazartesi getirisi `< 0` | Aynı haftanın Cuma getirisi |
| `THREE_DOWN_TWO_UP` | Üç ardışık düşüş günü | Sonraki iki günün bileşik getirisi |
| `POST_LARGE_DOWN_REVERSION` | Günlük getiri, 60 günlük kayan standart sapmanın −2 katından küçük | Sonraki günün getirisi |
| `END_OF_WEEK_CONTINUATION` | Pazartesi–Perşembe bileşik getirisinin işareti | Cuma getirisinin aynı işarette olma oranı |

**Çıktı alanları:** `occurrences`, `conditional_mean_return_pct`, `conditional_median_return_pct`, `positive_rate_pct`, `unconditional_mean_return_pct` (aynı ufuk), `mean_after_cost_pct` (maliyet 0.001 bir kez düşülür), `train` ve `test` alt özetleri (0.70 zaman sıralı ayrım), `p_value` (permütasyon, 2.000 karıştırma, `seed=42`), `patterns_in_family` (5) ve `p_value_bonferroni`, `incomplete_weeks_skipped`, `sample_warning`, `interpretation_flags` (`NOT_SIGNIFICANT`, `UNSTABLE_OUT_OF_SAMPLE`, `NEGATIVE_AFTER_COST`).

- [ ] **Step 1:** Betikteki `weekday_statistics`, `build_weekly_pattern_table` ve `train_test_split_by_time` okunur (`detect_pattern` ve `pattern_summary` 17 Kasım'da okundu).
- [ ] **Step 2: Kalan testler** — `WEEKDAY_MEANS` betiğin `weekday_statistics` çıktısına eşit; `train_test_split_by_time` ile aynı ayrım noktası; rastgele yürüyüş getirilerinde beş örüntünün hiçbiri Bonferroni sonrası anlamlı çıkmaz (üç tohum); Pazartesi negatifse Cuma'ya bilerek +%1 eklenmiş sentetik seride `MON_WEAK_FRI_STRONG` anlamlı çıkar; koşul yalnız geçmiş günleri kullanır (Cuma getirileri değiştirildiğinde `occurrences` değişmez); tatil nedeniyle dört günlük hafta haftalık örüntülerde sayılmaz ve `incomplete_weeks_skipped` artar; aynı girdiyle iki çağrının `p_value` değeri aynı.
- [ ] **Step 3:** FAIL → uygulama → PASS. MCP aracı ve testi.
- [ ] **Step 4:** Commit: `feat: weekday and multi-day pattern tests with significance diagnostics`.

---

### Task 9: Depolama şeması (EC-019)

**Files:** Create `src/bist_harness/storage/__init__.py`, `storage/db.py`, `tests/test_storage.py`.

**Interfaces — Produces:** `SCHEMA_VERSION = 1`; `connect(path: Path | None = None) -> sqlite3.Connection` (yoksa oluşturur, `PRAGMA user_version` yazar, yabancı anahtarları açar).

| Tablo | Sütunlar |
| --- | --- |
| `analyses` | `analysis_id` PK, `created_at`, `question`, `intent_json`, `snapshot_id`, `model`, `state`, `gate_status`, `action`, `explanation` |
| `tool_calls` | `id` PK, `analysis_id` FK, `seq`, `state`, `tool`, `arguments_json`, `output_json`, `result_id`, `allowed` |
| `evidence` | `id` PK, `analysis_id` FK, `label` (E1…), `tool`, `result_id`, `field`, `value`, `sentence`, `committed` |
| `decisions` | `id` PK, `analysis_id` FK, `reviewed_at`, `human_result` (ACCEPT / MODIFY / REJECT), `reason` |
| `events` | `id` PK, `snapshot_id`, `ticker`, `event_type`, `direction`, `event_date`, `state_json`, `forward_json` |

- [ ] **Step 1: Kalan testler** — yeni dosyada beş tablo ve `user_version == 1`; var olan dosya yeniden açıldığında veri korunur; olmayan `analysis_id` ile `tool_calls` satırı eklenemez; §28'deki her karar günlüğü alanı için karşılık gelen sütun bir eşleme tablosuyla doğrulanır.
- [ ] **Step 2:** FAIL → `db.py` → PASS.
- [ ] **Step 3:** Commit: `feat: SQLite schema for analyses, evidence, decisions and events`.

---

### Task 10: Veri sözlüğü (EC-018)

**Files:** Create `docs/data_dictionary.md`, `tests/test_data_dictionary.py`.

- Her satır: özellik adı, katman, tanım, birim, kaynak, hesaplama, "ne zaman bilinebilir" kuralı, üreten fonksiyon.
- Kapsam: bu sprintte üretilen bütün sütunlar ve araç çıktı alanları; §10'daki henüz üretilmemiş gruplar "Sprint 3" notuyla yer tutucu olarak listelenir.

- [ ] **Step 1: Kalan test** — `add_all_indicators` çıktısındaki her sütun adı ve her MCP aracının çıktı anahtarı sözlükte geçer (test dosyası sözlüğü okur ve eksikleri listeler).
- [ ] **Step 2:** FAIL → sözlüğü yaz → PASS.
- [ ] **Step 3:** Commit: `docs: data dictionary for market, indicator and event features`.

---

### Task 11: Model seçimi ve deneme eğitimi (EC-005 kalanı, EC-006) — RTX 5070 ve Burak gerekir

- [ ] **Step 1 (Burak):** RTX 5070'li makineyi aç. Sunucuda `qwen3.5:4b`, `qwen3.5:2b` ve bir Gemma 4 küçük boyutunu indir (geçit uzaktan indirmeye izin vermiyor). `qwen3.5:9b-q4_K_M` zaten var.
- [ ] **Step 2:** Dizüstünde `.env` içine uzak adresi yaz ve ölçümü çalıştır: `uv run python -m bist_harness.bakeoff.run --models qwen3.5:9b-q4_K_M,qwen3.5:4b,qwen3.5:2b,<gemma etiketi> --out docs/results/2026-11-17-model-bakeoff.md`.
- [ ] **Step 3 (Burak): modeli seç.** Kural: en yüksek `args_ok`; fark 10 puandan azsa küçük olan. Gerekçeyi kendi cümlenle sonuç dosyasına ve tasarım belgesinin 11. bölümüne yaz.
- [ ] **Step 4 (uzak makinede):** Eğitim ortamını kur (ayrı klasör, bu repoya bağımlılık eklenmez): CUDA'lı PyTorch, `transformers`, `peft`, `bitsandbytes`, `datasets`. Sürümler kurulum sırasında güncel belgeden doğrulanır ve bir `requirements-train.txt` dosyasına yazılır.
- [ ] **Step 5:** `bakeoff/cases.jsonl` içindeki 25 araç sorusundan, seçilen modelin sohbet ve araç çağırma şablonuyla 50–100 kayıtlık deneme veri seti üret; 1 epoch QLoRA (rank 16, 4 bit) çalıştır; adaptörü kaydet. Tepe ekran kartı belleği ve süre kaydedilir.
- [ ] **Step 6:** Adaptörü temel modelle birleştir, GGUF'a çevir, Ollama'da `bist-smoke` adıyla oluştur; dizüstünden ince hat çalıştırıcısıyla bir soru sor.
- [ ] **Step 7:** Sonuçları (bellek, süre, kullanılan sürümler, karşılaşılan sorunlar) `docs/results/2026-11-18-qlora-smoke-test.md` dosyasına yaz. 12 GB yetmediyse ikinci sıradaki modele geçilir ve karar günlüğüne işlenir.

---

### Task 12: Sprint kapanışı

- [ ] `uv run pytest -q` ve `uv run ruff check .` temiz.
- [ ] Sprint 1 ince hat soruları yeni araçlarla yeniden çalıştırılır; sonuç bozulmamış olmalı.
- [ ] `docs/ai_usage_log.md` ve `docs/decision-log.md` güncellenir; `git tag sprint-2`.
- [ ] Notion: S2 kartlarının kabul kriterleri kanıtla kontrol edilir; bağımlılığı biten S3 kartları `02 Hazır` yapılır.
