# Sprint 3 — Backtest ve Temel Veri: Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sprint sonunda ön kayıt protokolü yazılmış; strateji varyantlarını geleceğe bakmadan sınayan bir backtest motoru, yayın tarihine hizalı makro seriler, açıklama zamanına hizalı çeyreklik temel veriler, açıklama sonrası anormal getiri hesabı, KAP olay katmanı ve bunları birleştiren özellik tablosu hazır olsun; ilgili beş MCP aracı çağrılabilsin.

**Architecture:** Sprint 2 düzeni korunur: hesap `tools/` altında düz fonksiyon, veri `data/` altında, sunucu ince doğrulama katmanı. Yeni veri (makro, temel, KAP) aynı anlık görüntünün alt klasörlerine yazılır ve manifestte yer alır; araçlar yine ağa gitmez. Zamana bağlı her kayıt iki tarih taşır: ait olduğu dönem ve **kamuya açıklandığı an**; araçlar yalnız ikincisine göre süzer.

**Tech Stack:** Sprint 2 ile aynı. Yeni bağımlılık: `lxml` (HTML tablolarını okumak için; `pandas.read_html`). Ağ çağrıları yalnız `build` komutlarında, `httpx` ile.

**Spec:** `docs/superpowers/specs/2026-11-17-bist-harness-design.md` §4, §5, §8; istem §9, §10, §14–§18, §29, §31, §34; Duyuru 1 madde 2, 3, 4. Kartlar: EC-014, 015, 016, 025, 026, 027, 030, 031.

## Global Constraints

Sprint 1 ve 2 kısıtlarının tamamı geçerlidir. Ek olarak:

- **Dönemler (K-003):** keşif 2020-01-01 – 2024-12-31; test 2025-01-01 – 2026-11-13. Temel veri analizinin ana dönemi TMS 29 sonrasıdır (Duyuru 1 madde 4): 2024 yıl sonu ve sonrası tablolar.
- Test dönemine ait hiçbir backtest ya da olay çalışması sonucu, `docs/preregistration.md` commit'lenmeden önce üretilmez. Protokolden önce görülmüş sonuçlar protokolde açıkça listelenir.
- Karar t gününün kapanışında verilir; işlem **t+1 açılışında** yapılır. Hiçbir işlem, kararın verildiği barın fiyatıyla gerçekleşmez.
- Maliyet: işlem başına tek yön 0.001 komisyon + 0.0005 kayma (giriş ve çıkışta ayrı ayrı). Sharpe yıllıklandırması 252 gün, risksiz oran 0 (çıktıda belirtilir).
- Bir finansal tablo, KAP'taki yayın zaman damgasından sonra kapanan ilk işlem gününden itibaren kullanılabilir: yayın işlem günü 18:00'den önceyse o gün, değilse sonraki işlem günü.
- Makro veri yayın tarihine göre hizalanır; revizyonlar geçmişe işlenmez.
- Bankalar, sigorta ve aracı kurum için sanayi oranları (FAVÖK, net borç/FAVÖK, cari oran) hesaplanmaz; alan `None` döner ve `not_applicable` listesine yazılır.
- Araç çıktılarında NaN ya da sonsuz değer bulunmaz; hesaplanamayan değer `None` olur.
- Kaynak, erişim tarihi ve dönüşümler `docs/data_sources.md` içinde belgelenir (Duyuru 1 madde 2).

## Review Focus

1. **Sinyal ile işlem aynı barda.** Karar günü kapanışı işlem fiyatı olarak kullanılırsa sonuç iyimser olur. Test: Task 2 (giriş fiyatı t+1 açılışıdır; t+1 verisi yoksa işlem açılmaz).
2. **Tablo, yayınlanmadan önce kullanılıyor.** Dönem sonu tarihiyle hizalama geleceği sızdırır. Test: Task 5 ve Task 8 (yayın gününden bir gün önceki `as_of` bir önceki çeyreği döndürür).
3. **Yayın saati seans sonrası.** 18:00'den sonra yayımlanan tablo aynı günün kapanışında bilinemez. Test: Task 4.
4. **Banka için sanayi oranı.** FAVÖK ve net borç bankada anlamsızdır. Test: Task 5.
5. **Az işlemli strateji.** Beşten az işlemle yüksek getiri raporlanırsa `sample_warning` ve `FEW_TRADES` bayrağı gelir. Test: Task 2.

## Dosya yapısı (yeni ve değişen)

```
docs/preregistration.md
docs/data_sources.md
data/reference/kap_members.csv            # ticker → KAP üye kimliği
data/reference/fundamental_items.csv      # kalem kodu → ad eşlemesi
src/bist_harness/
  backtest/engine.py        # Trade, run_trades, portfolio_returns, performance
  backtest/strategies.py    # A–E varyantlarının giriş kuralları
  backtest/periods.py       # keşif/test dönemleri, rejim etiketi
  data/macro.py             # dört makro serinin indirilmesi ve yayın tarihleri
  data/fundamentals.py      # tablo indirme, KAP yayın zamanları, known_from
  data/kap.py               # KAP bildirim üst verisi, konu etiketleri
  tools/macro.py            # macro_context
  tools/fundamentals.py     # fundamental_metrics, fundamental_change
  tools/disclosure.py       # açıklama sonrası getiri ve anormal getiri
  tools/news.py             # news_events
  features/table.py         # build_feature_table
  mcp_server/server.py      # run_backtest, get_macro_context, get_fundamental_metrics,
                            # calculate_fundamental_change, get_news_events
```

## Sıra

| Görev | Kart | Ağ | Not |
| --- | --- | --- | --- |
| 1 Ön kayıt protokolü | EC-031 | Hayır | Test dönemi sonucu üretilmeden önce |
| 2 Backtest motoru, A ve B varyantları | EC-030 | Hayır | Yalnız Sprint 2 araçlarına dayanır |
| 3 Makro veri ve aracı | EC-015 | Evet | TÜFE, temel veride reel büyüme için gerekir |
| 4 Temel veri kaynağı ve yayın zamanları | EC-014 | Evet | |
| 5 Temel metrikler ve değişim araçları | EC-025 | Hayır | |
| 6 Açıklama sonrası anormal getiri | EC-026 | Hayır | |
| 7 KAP olay katmanı ve aracı | EC-016 | Evet | |
| 8 Özellik tablosu, C–E varyantları | EC-027, EC-030 | Hayır | |
| 9 Sprint kapanışı | — | Hayır | |

---

### Task 1: Ön kayıt protokolü (EC-031)

**Files:** Create `docs/preregistration.md`, `src/bist_harness/backtest/__init__.py`, `backtest/periods.py`, `tests/test_periods.py`.

**Interfaces — Produces:**

```python
DISCOVERY = ("2020-01-01", "2024-12-31")
TEST = ("2025-01-01", "2026-11-13")
def period_of(day) -> str | None            # "discovery", "test" ya da None
def split_period(start: str, end: str) -> dict[str, tuple[str, str]]   # isteği dönemlere böler
def market_regime(benchmark_close: pd.Series) -> pd.Series   # "Uptrend"/"Downtrend": XU100, 200 günlük SMA'ya göre; ilk 200 gün None
```

Protokol içeriği: araştırma soruları (dört senaryo), her biri için önceden sabitlenen tanım ve parametreler (olay tanımları Sprint 2'den, ufuklar, tutma süresi 10 gün, maliyet, başarı ölçütü), dönem ayrımı, çoklu test düzeltmesi, "protokolden önce görülen sonuçlar" listesi, protokolden sapmanın nasıl raporlanacağı.

- [ ] **Step 1:** Kalan testler — sınır günleri doğru döneme düşer; dönemler örtüşmez; `split_period("2023-01-01","2025-06-30")` iki parça döndürür; rejim etiketi yalnız geçmiş 200 günü kullanır (kesme testi).
- [ ] **Step 2:** FAIL → `periods.py` → PASS. Protokolü yaz.
- [ ] **Step 3:** Commit: `docs: pre-registration protocol and period split`.

---

### Task 2: Backtest motoru, A ve B varyantları (EC-030)

**Files:** Create `backtest/engine.py`, `backtest/strategies.py`, `tests/test_backtest_engine.py`, `tests/test_strategies.py`. Modify sunucu (`run_backtest`), şema testi, `tests/test_mcp_server.py`.

**Kurallar (ön kayıtla aynı):**

- Giriş sinyali t gününün kapanışında oluşur. Giriş fiyatı `Open[t+1]`; çıkış `Close[t+holding_days]` (varsayılan 10). Aynı hissede açık işlem varken yeni sinyal yok sayılır.
- İşlem getirisi: `Close_exit / Open_entry × (1 − c)² − 1`, `c = 0.0015`.
- Portföy: aynı gün açık işlemlerin günlük getirilerinin eşit ağırlıklı ortalaması; açık işlem yoksa 0.
- Kıyaslar: evrendeki hisselerin eşit ağırlıklı al-tut getirisi; XU100; (B ve sonrası için) ilgili peer gruplarının eşit ağırlıklı getirisi.
- **A_TECHNICAL:** `RSI_LOCAL_TROUGH` ya da `BOLLINGER_LOWER_TOUCH` olayı ve o gün `supertrend_state` ya da `kama_slope` yükseliş yönünde değil şartı aranmaz; yalnız olay. (Ters dönüş girişi.)
- **B_TECH_SECTOR:** A + o gün hissenin 20 günlük lag skoru `< 0` ve `sector_strong` doğru.
- C, D, E varyantları Task 8'de eklenir; o zamana kadar `NOT_IMPLEMENTED` döner.

**Interfaces — Produces:**

```python
@dataclass(frozen=True)
class Trade:
    ticker: str; signal_date: str; entry_date: str; exit_date: str
    entry_price: float; exit_price: float; return_pct: float; info_date: str   # kullanılan en geç bilginin tarihi

def run_trades(df: pd.DataFrame, signal: pd.Series, *, ticker: str, holding_days: int = 10,
               cost: float = 0.0015, info_dates: pd.Series | None = None) -> list[Trade]
def portfolio_returns(trades: Sequence[Trade], closes: dict[str, pd.Series], opens: dict[str, pd.Series],
                      calendar: pd.DatetimeIndex, *, cost: float = 0.0015) -> pd.Series
def performance(returns: pd.Series) -> dict
    # cumulative_return_pct, cagr_pct, sharpe, max_drawdown_pct, exposure_pct
def summarize_backtest(trades, returns, benchmarks: dict[str, pd.Series], regimes: pd.Series | None) -> dict
    # trades, win_rate_pct, average_trade_return_pct, median_trade_return_pct, performans alanları,
    # benchmark_* alanları ve farklar, by_period, by_regime, sample_warning, flags
def signals(variant: str, context: StrategyContext) -> dict[str, pd.Series]      # strategies.py
```

- [ ] **Step 1: Kalan testler (motor)** — elle kurulmuş 30 günlük seride tek sinyal: giriş t+1 açılışı, çıkış t+10 kapanışı, getiri elle hesaplanan değere eşit; son gündeki sinyal işlem açmaz; açık işlem varken gelen sinyal yok sayılır; maliyet sıfırken getiri ham orana eşit; sinyal sonrası fiyatlar değiştirildiğinde `signal_date` ve `entry_date` değişmez; her işlemde `info_date <= signal_date`; `performance` sabit %1 günlük getiride bilinen kümülatif getiriyi, bilinen düşüşlü seride bilinen azami düşüşü verir; 5'ten az işlem → `FEW_TRADES`.
- [ ] **Step 2:** FAIL → `engine.py` → PASS.
- [ ] **Step 3: Kalan testler (stratejiler)** — A sinyalleri, iki olay maskesinin birleşimine eşit; B sinyalleri A'nın alt kümesi ve her birinde lag `< 0` ve sektör güçlü; kesme testi (veri t'de kesilince t ve öncesinin sinyalleri değişmez).
- [ ] **Step 4:** FAIL → `strategies.py` → PASS.
- [ ] **Step 5: MCP** — `run_backtest(strategy, universe, start, end)`: boş `universe` bütün evren; evren dışı hisse → `UNKNOWN_TICKER`; çıktı özet ve en çok 12 satırlık işlem örneği; aynı girdi aynı `result_id`. Test → uygulama.
- [ ] **Step 6:** Keşif dönemi (2020–2024) için A ve B'yi çalıştır; sonucu `docs/results/2026-11-18-backtest-discovery.md` dosyasına yaz. **Test dönemi çalıştırılmaz** (Task 9'a kadar).
- [ ] **Step 7:** Commit: `feat: backtest engine with next-open execution and strategy variants A and B`.

---

### Task 3: Makro veri ve aracı (EC-015)

**Files:** Create `data/macro.py`, `tools/macro.py`, `tests/test_macro.py`, `docs/data_sources.md`. Modify `data/snapshot.py` (CLI `build` makroyu da kurar), sunucu, testler.

**Kaynaklar (17 Kasım'da denendi):**

| Seri | Kaynak | Yayın kuralı |
| --- | --- | --- |
| USD/TRY, EUR/TRY | Yahoo Finance (`USDTRY=X`, `EURTRY=X`), günlük kapanış. EVDS anahtar istediği için kullanılmadı; birkaç gün TCMB gösterge kuruyla karşılaştırılır | Günün kapanışı |
| TCMB politika faizi | TCMB "1 Hafta Repo" sayfasındaki karar tablosu | Karar tarihi |
| Fed hedef aralığı | Federal Reserve "Open Market Operations" sayfası; olmazsa FRED `DFEDTARU`/`DFEDTARL` | Karar tarihi |
| TÜFE (yıllık ve aylık % değişim) | TCMB "Tüketici Fiyatları" sayfası (TÜİK verisi) | Ait olduğu ayı izleyen ayın 3'ü, hafta sonuysa sonraki iş günü |

**Interfaces — Produces:**

```python
def parse_policy_rate(html: str) -> pd.DataFrame        # effective_date, rate
def parse_cpi(html: str) -> pd.DataFrame                # period (ay sonu), annual_pct, monthly_pct, published
def parse_fed_target(html_or_csv: str) -> pd.DataFrame  # effective_date, lower, upper
def cpi_publication_date(period) -> pd.Timestamp
def build_macro(folder: Path, *, fetch: Fetcher | None = None) -> dict[str, int]   # yazılan satır sayıları
def load_macro(name: str, *, snapshot_id=None, root=None) -> pd.DataFrame          # "fx", "policy_rate", "fed_target", "cpi"
def macro_context(series: dict[str, pd.DataFrame], *, start: str, end: str) -> dict   # tools/macro.py
def cpi_index(cpi: pd.DataFrame) -> pd.Series           # aylık değişimlerden zincirlenmiş endeks (reel büyüme için)
```

`macro_context` çıktısı: `usdtry_start`, `usdtry_end`, `usdtry_change_pct`, aynısı `eurtry`; `policy_rate_start`, `policy_rate_end`, `policy_rate_changes` (dönemdeki karar sayısı), `last_policy_decision_date`; `fed_target_upper_start/end`, `fed_changes`; `cpi_annual_pct` ve `cpi_monthly_pct` (`end` tarihinde **yayımlanmış** son ay), `cpi_period`, `cpi_published`; `warnings` (eksik seri).

- [ ] **Step 1: Kalan testler** — kaydedilmiş küçük HTML parçalarından ayrıştırma (üç kaynak); `cpi_publication_date("2026-10")` 2026-11-03; ayın 3'ü cumartesiyse pazartesi; `macro_context` `end` tarihinden sonra yayımlanan TÜFE'yi kullanmaz (Ekim verisi 2 Kasım'da görünmez, 3 Kasım'da görünür); faiz kararı sayımı; eksik seri uyarı üretir, hata fırlatmaz; `cpi_index` iki aylık örnekte elle hesapla eşit.
- [ ] **Step 2:** FAIL → uygulama → PASS. MCP aracı `get_macro_context(start, end)` ve testi.
- [ ] **Step 3 (ağ):** Makroyu kur; `docs/data_sources.md` içine kaynak, erişim tarihi, satır sayıları, TCMB kuruyla karşılaştırma sonucu.
- [ ] **Step 4:** Commit: `feat: macro context aligned by publication date`.

---

### Task 4: Temel veri kaynağı ve yayın zamanları (EC-014)

**Files:** Create `data/fundamentals.py`, `data/reference/kap_members.csv`, `data/reference/fundamental_items.csv`, `tests/test_fundamentals_data.py`. Modify `docs/data_sources.md`, snapshot CLI.

**Karar (K-003'ün devamı):** Fintables erişimi yok. Tablolar İş Yatırım'ın herkese açık mali tablo servisinden (kalem kodlu, dönemsel kümülatif değerler), yayın zamanları KAP bildirim sorgusundan (`disclosureClass = FR`, `publishDate`) alınır. Her ikisi de 17 Kasım'da denendi.

**Interfaces — Produces:**

```python
@dataclass(frozen=True)
class Period:
    year: int; quarter: int            # quarter: 1..4 (3, 6, 9, 12. ay)
    @property
    def end_date(self) -> pd.Timestamp

def fetch_statements(ticker: str, periods: Sequence[Period], *, fetch=None) -> pd.DataFrame
    # uzun biçim: ticker, year, quarter, item_code, item_name, value (kümülatif, TL)
def fetch_report_disclosures(ticker: str, start: str, end: str, *, fetch=None) -> pd.DataFrame
    # published_at (zaman damgası), year, quarter, subject, disclosure_index
def known_from(published_at: pd.Timestamp, calendar: pd.DatetimeIndex) -> pd.Timestamp
def build_fundamentals(folder: Path, tickers, *, first: Period, last: Period, fetch=None) -> pd.DataFrame   # özet
def load_statements(ticker, *, snapshot_id=None, root=None) -> pd.DataFrame
def load_disclosure_calendar(*, snapshot_id=None, root=None) -> pd.DataFrame
    # ticker, year, quarter, published_at, known_from
def financial_group(ticker: str) -> str     # sanayi / banka / sigorta ayrımı
```

- Kapsam: 30 evren hissesi, 2022 4. çeyrek – 2026 3. çeyrek (yıllık karşılaştırma ve son 12 ay toplamı için bir önceki yıl gerekir).
- Bir dönem için KAP'ta birden çok finansal rapor bildirimi varsa (düzeltme) **ilk** yayın zamanı kullanılır ve düzeltme sayısı kaydedilir.
- Yayın zamanı bulunamayan dönem `published_at = None` ile kaydedilir ve araçlarda kullanılmaz (uyarıyla).

- [ ] **Step 1: Kalan testler** — kaydedilmiş örnek cevaplardan ayrıştırma (tablo ve bildirim); `known_from`: 17:59 → aynı gün, 18:00 ve sonrası → sonraki işlem günü, hafta sonu → pazartesi, tatil → takvimdeki sonraki gün; aynı dönem için iki bildirimde ilk zaman; boş cevap hata fırlatmaz; banka için ayrı mali grup.
- [ ] **Step 2:** FAIL → uygulama → PASS.
- [ ] **Step 3 (ağ):** Veriyi kur; kapsam tablosu (hisse × dönem: tablo var mı, yayın zamanı var mı) `docs/results/2026-11-18-fundamentals-coverage.md`.
- [ ] **Step 4:** Commit: `feat: quarterly statements with KAP disclosure timestamps`.

---

### Task 5: Temel metrikler ve değişim araçları (EC-025)

**Files:** Create `tools/fundamentals.py`, `tests/test_fundamentals_tools.py`. Modify sunucu ve testleri, veri sözlüğü.

**Metrikler (istem §9):** büyüme (hasılat, FAVÖK, net kâr; çeyreklik ve yıllık; nominal ve TÜFE ile düzeltilmiş), kârlılık (ROE, ROA, FAVÖK marjı, net kâr marjı), kaldıraç (net borç/FAVÖK, borç/özkaynak), likidite (cari oran, asit-test), değerleme (F/K, PD/DD, FD/FAVÖK; `as_of` kapanışıyla), nakit akışı (işletme nakit akışı, nakit dönüşümü).

- Çeyreklik değer = kümülatif fark (1. çeyrek hariç). Son 12 ay = bu dönem kümülatif + önceki yıl sonu − önceki yıl aynı dönem kümülatif.
- Reel yıllık büyüme = `değer_t / (değer_{t−1y} × TÜFE_t / TÜFE_{t−1y}) − 1`.
- `as_of` tarihinde `known_from <= as_of` olan en son dönem kullanılır.

**Interfaces — Produces:**

```python
def latest_known_period(calendar: pd.DataFrame, ticker: str, as_of: str) -> Period | None
def fundamental_metrics(statements, calendar, *, ticker: str, as_of: str, close: pd.Series | None = None,
                        cpi: pd.Series | None = None) -> dict
def fundamental_change(statements, calendar, *, ticker: str, as_of: str, periods: int = 4,
                       cpi: pd.Series | None = None) -> dict
    # quarters: en çok `periods` satır (dönem, yayın günü, hasılat, FAVÖK, net kâr, marjlar, çeyreklik ve yıllık değişim)
    # improvement_flags: REVENUE_UP, MARGIN_UP, LEVERAGE_DOWN, CASH_FLOW_UP … ve fundamental_trend ("Improving"/"Mixed"/"Deteriorating")
```

- [ ] **Step 1: Kalan testler** — üç dönemlik elle kurulmuş tablodan her oran elle hesaplanan değere eşit; yayın gününden bir gün önceki `as_of` önceki çeyreği döndürür, yayın günü yenisini; yayın zamanı olmayan dönem kullanılmaz; banka için FAVÖK alanları `None` ve `not_applicable` dolu; payda sıfır ya da negatif özkaynakta oran `None`; reel büyüme elle hesapla eşit; hiç dönem yoksa `DATA_UNAVAILABLE`.
- [ ] **Step 2:** FAIL → uygulama → PASS. MCP araçları `get_fundamental_metrics(ticker, as_of)` ve `calculate_fundamental_change(ticker, as_of, periods=4)` ve testleri.
- [ ] **Step 3:** Commit: `feat: point-in-time fundamental metrics and quarterly change`.

---

### Task 6: Açıklama sonrası anormal getiri (EC-026)

**Files:** Create `tools/disclosure.py`, `tests/test_disclosure.py`. Modify `tools/fundamentals.py` (değişim çıktısına tepki alanları), veri sözlüğü.

- Olay günü `known_from`. Getiri: olay gününden **önceki** kapanıştan olay gününden sonraki 1., 5. ve 20. işlem gününün kapanışına. (Yayın seans içindeyse o günün kapanışı tepkiyi içerir; önceki kapanış temiz başlangıçtır.)
- Anormal getiri: aynı penceredeki XU100 getirisi ve peer grubunun (hisse hariç) eşit ağırlıklı getirisi çıkarılır.
- Özet: çeyrek sayısı, ortalama ve medyan (1/5/20 gün; ham, XU100'e göre, peer'a göre), temel eğilime göre kırılım ("Improving" ve diğerleri), `sample_warning`.

**Interfaces — Produces:**

```python
def post_disclosure_returns(close: pd.Series, event_days: Sequence[pd.Timestamp], *, benchmark: pd.Series,
                            peers: dict[str, pd.Series], horizons=(1, 5, 20)) -> pd.DataFrame
def summarize_reactions(reactions: pd.DataFrame, groups: pd.Series | None = None) -> dict
```

- [ ] **Step 1: Kalan testler** — elle kurulmuş seride getiriler ve anormal getiriler elle hesaba eşit; ufku dolmamış olay o ufukta `None`; peer verisi yoksa peer alanı `None` ve uyarı; olaydan sonraki fiyatları değiştirmek olay gününü değiştirmez; gruplu özet.
- [ ] **Step 2:** FAIL → uygulama → PASS.
- [ ] **Step 3:** Commit: `feat: post-disclosure returns and abnormal returns`.

---

### Task 7: KAP olay katmanı ve aracı (EC-016)

**Files:** Create `data/kap.py`, `tools/news.py`, `tests/test_kap.py`. Modify snapshot CLI, sunucu, testler, `docs/data_sources.md`.

- Kaynak: KAP bildirim sorgusu; sınıflar `FR` (finansal rapor) ve `ODA` (özel durum açıklaması). Yalnız üst veri saklanır: zaman damgası, şirket, sınıf, konu, özet satırı, bildirim numarası ve bağlantısı. Bildirim metni saklanmaz.
- Konu etiketi kural tabanlıdır (anahtar sözcük → etiket): `earnings`, `dividend`, `capital_increase`, `buyback`, `contract`, `investment`, `financing`, `merger_acquisition`, `regulation_legal`, `management`, `other`. Duygu etiketi üretilmez.
- Araç metni sayısal veri yerine kullanılmaz; çıktıda `context_only: true` bulunur (Duyuru 1 madde 3).

**Interfaces — Produces:**

```python
def tag_topic(subject: str, summary: str) -> str
def fetch_disclosures(ticker: str, start: str, end: str, *, classes=("FR", "ODA"), fetch=None) -> pd.DataFrame
def build_kap(folder: Path, tickers, *, start: str, end: str, fetch=None) -> int
def load_disclosures(*, snapshot_id=None, root=None) -> pd.DataFrame
def news_events(disclosures: pd.DataFrame, *, start: str, end: str, ticker: str | None = None,
                topic: str | None = None, limit: int = 12) -> dict
    # total, by_topic, events (en yeni önce; published_at, ticker, topic, subject, url), context_only, warnings
```

- [ ] **Step 1: Kalan testler** — etiket kuralları (Türkçe konu başlıklarıyla tablo testi); `end` zaman damgasından sonraki bildirim listelenmez; `limit` aşılmaz ve en yeni önce; hisse ve konu süzgeci; bilinmeyen konu → hata nesnesi; boş sonuç `total == 0`.
- [ ] **Step 2:** FAIL → uygulama → PASS. MCP aracı `get_news_events` ve testi.
- [ ] **Step 3 (ağ):** 2025-01-01'den bugüne evren için kur; konu dağılımını `docs/data_sources.md` içine yaz.
- [ ] **Step 4:** Commit: `feat: KAP disclosure metadata as timestamped context`.

---

### Task 8: Özellik tablosu ve C–E varyantları (EC-027, EC-030)

**Files:** Create `features/__init__.py`, `features/table.py`, `tests/test_feature_table.py`. Modify `backtest/strategies.py`, testleri, veri sözlüğü.

- Satır: (hisse, gün). Sütun grupları: teknik durum etiketleri, 5/10/20/60 günlük lag skoru ve `sector_strong`, son 60 gündeki olay sayıları, o gün bilinen son çeyreğin `fundamental_trend` değeri ve yayın günü, makro değişimler (USD/TRY 20 gün, faiz 60 gün değişimi, yayımlanmış TÜFE), son 5 gündeki KAP bildirim sayısı ve konuları.
- Her sütun için bilgi tarihi tutulur; satırın `info_date` değeri bunların en geçidir ve satır tarihini aşamaz.
- **C_TECH_SECTOR_FUND:** B + `fundamental_trend == "Improving"`. **D_FULL_STRUCTURED:** C + son 60 günde politika faizi artmamış. **E_FULL_CONTEXTUAL:** D + son 5 günde `regulation_legal` etiketli bildirim yok.
- C–E, temel verinin TMS 29 dönemiyle sınırlı olması nedeniyle yalnız test döneminde tanımlıdır; keşif döneminde `NOT_AVAILABLE_BEFORE_2025` uyarısıyla boş sonuç döner.

- [ ] **Step 1: Kalan testler** — sentetik katmanlarla: her satırda `info_date <= date`; veri t'de kesilince t ve öncesinin satırları değişmez; yayın gününden önce yeni çeyrek görünmez; C ⊆ B, D ⊆ C, E ⊆ D; C–E keşif döneminde uyarıyla boş.
- [ ] **Step 2:** FAIL → uygulama → PASS. `run_backtest` C–E'yi çalıştırır; ilgili testler güncellenir.
- [ ] **Step 3:** Commit: `feat: unified point-in-time feature table and strategy variants C to E`.

---

### Task 9: Sprint kapanışı

- [ ] `uv run pytest -q` ve `uv run ruff check .` temiz; veri sözlüğü testi yeni alanlarla geçer.
- [ ] Ön kayıt commit'inden sonra: test dönemi backtest'i (A–E) ve Senaryo 4 olay çalışması bir kez çalıştırılır; sonuç `docs/results/2026-11-19-backtest-test-period.md`. Sonuca bakıp parametre değiştirilmez.
- [ ] Bağımsız inceleme; bulgular tek geçişte, önce kalan testle düzeltilir.
- [ ] `docs/ai_usage_log.md`, `docs/decision-log.md`, `git tag sprint-3`; Notion kartları; Sprint 4 planı.
