# BIST Agentic Harness — Tasarım Belgesi

Durum: **taslak, Burak'ın onayını bekliyor.** 17 Kasım 2026 gece vardiyasında Claude
tarafından yazıldı. K1–K3 kararları Burak'ın yerine verildi ve `docs/decision-log.md`
içinde K-005, K-006, K-007 olarak kayıtlı; onay gelene kadar geçici sayılır.

Kaynaklar: proje istemi (39 bölüm; bu belgede § ile anılır), hocanın üç Teams duyurusu,
üç haftalık ders slaytları, hocanın iki örnek betiği (`reference/instructor/`).

## 1. Amaç ve kapsam dışı

**Amaç.** BIST 100'den seçilmiş 30 hisselik evren üzerinde çalışan, eğitim ve araştırma
amaçlı bir analiz sistemi. Sistem bir araştırma sorusuna, kanıta dayalı bir analitik
durumla cevap verir: `POTENTIAL_CATCH_UP_CANDIDATE`, `ANALYSIS_UNSAFE` gibi.

**Temel ilke (§2).** LLM yorumlar ve açıklar. Python araçları hesaplar. Harness kontrol
eder. Backtest doğrular. Kanıt kaydedilir. Son kararı insan verir. Model yerelde çalışır.

**Not nasıl verilecek (Duyuru 3).** İnce ayarlı model canlı olarak, önceden verilmeyen
sorularla sınanacak. Ölçütler: sayısal halüsinasyon oranı, hatalı araç çağrısı oranı,
kanıtsız sonuç oranı, kanıt bütünlüğü ve tekrarlanabilirlik, kural ihlalleri.

**Kapsam dışı.** Aracı kurum bağlantısı, gerçek emir, para yönetimi, kişiye özel yatırım
tavsiyesi (§2). Bulut yapay zekâ servisi. Gerçek zamanlı veri akışı. Kurumsal altyapı (§24).

**Başarısızlık sayılacak durumlar.** Sistem bir sayı uydurursa; kalite ya da backtest
adımını atlayıp güçlü bir sonuç verirse; al/sat önerirse; aynı soruya aynı veriyle farklı
sonuç verirse. Bunlar sistem çalışsa bile projeyi başarısız kılar.

## 2. Değişmez kurallar

1. Final sistemde bulut yapay zekâ API çağrısı yok. Model, sahibi olduğumuz makinede Ollama
   ile çalışır.
2. LLM hesap yapmaz. Cevaptaki her sayı bir araç çıktısından gelir.
3. Sonuç yalnız sekiz eylem etiketinden biridir (`tools/schemas.py::ACTIONS`).
4. Her veri, kamuya açıklandığı tarihle kullanılır (point-in-time). t günündeki karar
   t+1 bilgisini kullanamaz.
5. `CHECK_DATA_QUALITY`, `RUN_BACKTEST` ve `RISK_GATE` durumları atlanamaz.
6. Her analiz kaydedilir ve aynı veri sürümüyle yeniden oynatılabilir.
7. Uzak sunucu adresi, tailnet adı ve IP'ler repoya ve belgelere yazılmaz.
8. Kod, yorumlar ve README İngilizce; plan ve tasarım belgeleri Türkçe.

## 3. Katmanlar: araç, servis, ajan

İstem (§20, §37) üç şeyin karıştırılmamasını istiyor.

| Katman | Ne yapar | Örnek | LLM var mı |
| --- | --- | --- | --- |
| Servis (worker) | Veri toplar, önbelleğe alır, sürümler | `data/market.py`, evren yükleyici | Hayır |
| Araç (tool) | Deterministik hesap; MCP üzerinden çağrılır | `detect_reversal_events` | Hayır |
| Harness | Durumları yürütür, izinleri uygular, kanıtı ve günlüğü tutar, çıktıyı denetler | durum makinesi, kalite kapısı, çıktı doğrulayıcı | Hayır |
| Ajan (reasoning) | Soruyu anlar, izinli araçlardan seçer, kanıta dayalı açıklama yazar | Orchestrator ve rol istemleri | Evet |

Tek bir yerel model vardır. İstemdeki altı ajan (§20) ayrı model değil, aynı modelin
farklı sistem istemi ve farklı araç alt kümesiyle çağrılmasıdır.

```
Soru
  └─ Harness (durum makinesi)
       ├─ LLM  ── araç çağrısı ──► MCP sunucusu ──► araçlar ──► servisler ──► veri
       ├─ Kanıt oluşturucu   (gözlenen bağlam → committed evidence set)
       ├─ Kalite kapısı      (PASS … HARD_BLOCK)
       ├─ LLM  ── açıklama ──► çıktı doğrulayıcı (sayı, etiket, kanıt, tavsiye dili)
       ├─ İnsan incelemesi   (kabul / değiştir / reddet)
       └─ Karar günlüğü ve replay
```

## 4. Veri modeli ve point-in-time kuralları

| Veri | Kaynak | Saklama | "Ne zaman bilinebilir" kuralı |
| --- | --- | --- | --- |
| Günlük OHLCV, endeksler | Yahoo Finance (`yfinance`, `auto_adjust=True`) | Parquet anlık görüntü + manifest | t gününün kapanışı, t günü kapanıştan sonra |
| Evren ve sektör haritası | İstem §5 | `data/reference/universe.csv` | Deney boyunca sabit |
| Çeyreklik finansal tablolar | Sprint 3'te seçilecek | Parquet + açıklama tarihi | KAP açıklama zamanı; seans sonrası açıklama ertesi işlem gününe yazılır |
| Makro (kur, TCMB faizi, Fed, TÜFE) | TCMB EVDS, TÜİK, Federal Reserve | Parquet + yayın tarihi | Yayın tarihi; revizyon geçmişe işlenmez |
| Haber ve KAP olayları | KAP | SQLite | Bildirim zaman damgası |
| Konuşma dökümleri | Seçilmiş kamuya açık videolar | SQLite | Videonun yayın zamanı |
| Analizler, kanıt, kararlar | Harness | SQLite | — |

Veri penceresi: fiyat tabanlı senaryolarda 2020-01-01 – 2024-12-31 keşif, 2025-01-01 –
Kasım 2026 test (karar K-003). Temel veride TMS 29 sonrası, kendi içinde tutarlı dönem
(Duyuru 1 madde 4).

Analizler indirilmiş anlık görüntüden çalışır. Canlı indirme yalnız açık bir yenileme
komutuyla yapılır; böylece aynı soru aynı sonucu verir ve sistem internet olmadan çalışır.

## 5. Araç sözleşmeleri

Adlar istemin §22 tablosundan, parametreler `src/bist_harness/tools/schemas.py`
dosyasından gelir; o dosya tek doğruluk kaynağıdır ve testle korunur.

| Araç | Parametreler |
| --- | --- |
| `get_stock_history` | `ticker`, `start`, `end` |
| `get_index_history` | `index`, `start`, `end` |
| `calculate_indicators` | `ticker`, `start`, `end`, `indicators[]` |
| `detect_reversal_events` | `ticker`, `start`, `end`, `event_type`, `forward_days` |
| `find_support_resistance` | `ticker`, `start`, `end`, `tolerance` |
| `rank_sector_relative_strength` | `sector`, `horizon_days`, `as_of` |
| `test_weekday_pattern` | `ticker`, `pattern`, `start`, `end` |
| `get_fundamental_metrics` | `ticker`, `as_of` |
| `calculate_fundamental_change` | `ticker`, `as_of`, `periods` |
| `get_macro_context` | `start`, `end` |
| `get_news_events` | `ticker?`, `topic?`, `start`, `end` |
| `get_speech_features` | `source_id` |
| `run_backtest` | `strategy`, `universe[]`, `start`, `end` |
| `check_data_quality` | `analysis_id` |
| `build_evidence_bundle` | `analysis_id` |

**Ortak kurallar**

- Tarihler `YYYY-MM-DD`; `ticker` büyük harf, `.IS` eki olmadan.
- **Çıktı özet düzeyindedir (karar K-007).** Araç ham seri döndürmez; özet istatistik,
  sayım ve bir `result_id` döndürür. Küçük modelin bağlamı korunur, sayı denetimi kolaylaşır.
- **Yuvarlama araçtadır.** Yüzdeler 2 ondalığa yuvarlanmış döner; model sayıyı kopyalar.
- **Hata bir çıktıdır, istisna değil:** `{"error": {"code": "...", "message": "..."}}`.
  Kodlar: `UNKNOWN_TICKER`, `INVALID_DATE_RANGE`, `FUTURE_DATE`, `DATA_UNAVAILABLE`,
  `NOT_IMPLEMENTED`.
- **`result_id`:** araç adı, argümanlar ve çıktının kanonik JSON'unun SHA-256 özetinin ilk
  12 karakteri. Aynı girdi ve aynı veri sürümü aynı kimliği verir; kanıt maddeleri bu
  kimliğe bağlanır.
- Her çıktıda `data_source` ve verinin tarih aralığı bulunur.
- Küçük örneklem uyarısı (hocanın betiği): 5'ten az olay `Very small sample size`, 20'den
  az `Limited sample size`.

Teknik dönüş olaylarının tanımı hocanın Senaryo 3 betiğinden alınır. Örnek:
`BOLLINGER_LOWER_TOUCH`, dün kapanışın alt bandın altında ya da üzerinde olup bugün
kapanışın alt bandın üstüne dönmesidir; olay bugünün kapanışında, yalnız bugüne kadarki
veriyle saptanır ve ileri getiri bugünün kapanışından ölçülür.

## 6. Durum makinesi

**Karar K-005 (K1): durum geçişlerini kod yönetir.** Model bir sonraki durumu seçmez;
her durumda yalnız o durumun izinli araçlarını görür. Gerekçe: "Agent thinks. Harness
controls." (2. hafta); hatalı araç çağrısı ve adım atlama riskini düşürür; harness deneyi
C'nin (araçlar + durumlu harness) tanımı budur.

| # | Durum | İzinli araçlar | LLM turu |
| --- | --- | --- | --- |
| 1 | `START` | — | Niyet çıkarımı (şemaya kısıtlı JSON) |
| 2 | `SELECT_UNIVERSE` | — | Hayır |
| 3 | `LOAD_MARKET_DATA` | `get_stock_history`, `get_index_history` | Evet |
| 4 | `CHECK_DATA_QUALITY` | `check_data_quality` | Hayır (harness çağırır) |
| 5 | `CALCULATE_TECHNICALS` | `calculate_indicators`, `find_support_resistance` | Evet |
| 6 | `RUN_SECTOR_RELATIVE_ANALYSIS` | `rank_sector_relative_strength` | Evet |
| 7 | `RUN_PATTERN_AND_REVERSAL_ANALYSIS` | `detect_reversal_events`, `test_weekday_pattern` | Evet |
| 8 | `LOAD_FUNDAMENTALS` | `get_fundamental_metrics`, `calculate_fundamental_change` | Evet |
| 9 | `LOAD_MACRO_CONTEXT` | `get_macro_context` | Evet |
| 10 | `LOAD_NEWS_AND_SPEECH_CONTEXT` | `get_news_events`, `get_speech_features` | Evet |
| 11 | `BUILD_EVIDENCE` | `build_evidence_bundle` | Hayır |
| 12 | `PREVIEW_STRATEGIES` | — | Hayır (varyantları harness listeler) |
| 13 | `RUN_BACKTEST` | `run_backtest` | Evet |
| 14 | `RISK_GATE` | `check_data_quality` | Hayır |
| 15 | `GENERATE_EXPLANATION` | — | Evet (araçsız; yalnız kanıt kümesi) |
| 16 | `HUMAN_REVIEW` | — | Hayır |
| 17 | `LOG_AND_CLOSE` | — | Hayır |

**Yürütme.** `START` durumunda model soruyu yapılandırılmış bir niyete çevirir: senaryo
türü, hisse ya da sektör, dönem. Harness bu niyete göre bir rota seçer; soruyla ilgisi
olmayan veri durumları "uygulanamaz" kaydıyla geçilir, zorunlu durumlar her rotada bulunur.
Rotadaki her araçlı durumda model, yalnız o durumun araçlarıyla bir tur alır.

**Koruyucular**

- İzin dışı araç çağrısı reddedilir, kayda geçer ve hatalı araç çağrısı sayılır.
- Backtest çalışmadıysa `*_CANDIDATE` etiketleri verilemez (2. hafta slaytı).
- Niyet "yatırım tavsiyesi" ya da "fiyat tahmini" ise analiz başlamaz; sistem eğitim
  amaçlı olduğunu söyleyen sabit bir cevap verir.
- Evren dışı hisse, gelecek tarih ya da ters tarih aralığı `ANALYSIS_UNSAFE` ile sonuçlanır.

Rotaların ve tur sayılarının ayrıntısı Sprint 4 planında belirlenir.

## 7. Kanıt paketi ve committed evidence set

İstem (§25) iki şeyi ayırıyor: gözlenen bütün özellikler ve sonucu gerekçelendirmek için
kullanılan küçük küme.

```
Observed Context        : bu analizde araçların döndürdüğü bütün alanlar
Committed Evidence Set  : E1 … En; her biri {tool, result_id, field, value, sentence}
Educational State       : sekiz etiketten biri
Warnings                : "Historical evidence only; no guarantee of future return." ve kapı uyarıları
```

- Kanıt cümleleri şablondan üretilir; sayı araç çıktısından kopyalanır.
- Kaynağı olmayan madde kümeye eklenemez.
- Her etiket için asgari kanıt kuralı vardır. Örnek: `POTENTIAL_CATCH_UP_CANDIDATE` için
  sektör lag kanıtı, teknik durum kanıtı ve backtest kanıtı; biri eksikse etiket
  `INVESTIGATE` olur.
- Açıklama yalnız kümedeki maddelere `E1`, `E2` biçiminde atıf yapabilir.

## 8. Kalite kapısı

Çıktılar (§26): `PASS`, `PASS_WITH_WARNINGS`, `INVESTIGATE`, `ANALYSIS_UNSAFE`, `HARD_BLOCK`.

| Sert blok | Nasıl saptanır |
| --- | --- |
| Gelecekteki finansal tablo daha erken bir tarihe giriyor | Açıklama tarihi > analiz tarihi |
| Gösterge ya da sinyalde geleceğe bakış | Sinyal kaydırma testi; kesilmiş veriyle yeniden hesap |
| Yanlış sembol ya da bozuk fiyat geçmişi | Evren denetimi, boşluk ve sıçrama denetimi |
| Fiyat ile finansal veri arasında dönem uyumsuzluğu | Dönem hizası denetimi |
| Backtest karar anında olmayan bilgiyi kullanıyor | İşlem günlüğünde bilgi tarihi ≤ karar tarihi |

Yumuşak uyarılar: makro seri eksik; haber kapsamı seyrek; döküm kalitesi düşük; geçmiş
olay sayısı az; peer grubu çok küçük.

Kapının kararını model değiştiremez. `HARD_BLOCK` sonrasında açıklama üretilmez; sonuç
`ANALYSIS_UNSAFE` ve gerekçedir.

## 9. Çıktı doğrulayıcı ve sonlu eylem kümesi

Modelin açıklaması kullanıcıya gösterilmeden önce denetlenir.

1. Etiket sekiz izinli etiketten biri mi.
2. Açıklamadaki her sayı kanıt kümesinde ya da soruda var mı (`eval/number_check.py`).
3. Her iddia bir kanıt numarasına bağlı mı.
4. Yatırım tavsiyesi dili var mı.
5. Zorunlu uyarı satırı var mı.

Reddedilen açıklama bir kez yeniden istenir; ikinci başarısızlıkta sistem yalnız kanıt
kümesini ve `INVESTIGATE` etiketini gösterir.

**Sayı eşleştirme kuralı (karar K-008, Burak'ın katkı noktasıydı).** Cevaptaki bir sayı,
araç çıktısındaki bir sayıya 2 ondalığa yuvarlandığında eşitse desteklenmiş sayılır.
Yüzde–kesir dönüşümü, tam sayıya yuvarlama ve işaret değiştirme kabul edilmez. Araçlar
zaten 2 ondalık döndürdüğü için katı kural mümkündür; bedeli, "yaklaşık 63" diyen doğru
bir cevabın reddedilmesidir. Bu, ince ayar verisinde modelin sayıyı birebir aktarmayı
öğrenmesiyle karşılanır.

**Cevap dili (karar K-006, K2).** Sistem sorunun dilinde cevap verir; Türkçe ve İngilizce
desteklenir. Etiketler ve araç adları her iki dilde İngilizce kalır.

## 10. Bellek ve karar günlüğü

| Bellek (§24) | İçerik | Yer |
| --- | --- | --- |
| Zamansal | Fiyat, gösterge, makro, finansal metrik, olay geçmişi | Parquet |
| Epizodik | Geçmiş analizler: durum → kanıt → eylem → backtest sonucu → insan kararı | SQLite |
| Prosedürel | İş akışı sırası, araç izinleri, doğrulama kuralları, şablonlar | Kod ve yapılandırma |

Karar günlüğü (§28) her analiz için şunları tutar: hisse ve sektör; analiz zamanı ve veri
dönemi; veri sürümleri ve yayın zamanları; çağrılan araçlar ve çıktıları; teknik, sektör,
temel ve makro durumlar; haber ve konuşma kaynak metadatası; tam kanıt paketi ve committed
evidence set; strateji varyantı ve backtest sonucu; kapı durumu; ajan sonucu ve açıklaması;
insan incelemesi sonucu ve gerekçesi.

Replay, kayıtlı bir analizi aynı veri sürümüyle yeniden çalıştırır ve araç çıktılarının
birebir aynı olduğunu doğrular.

## 11. Model

**İki makine.** Çıkarım için iki uç nokta vardır ve kod yalnız `BIST_LLM_BASE_URL`
değişkenine bakar: dizüstündeki Ollama (RTX 3050 Ti, 4 GB) ve uzaktaki masaüstü (RTX 5070,
12 GB), ikincisine özel ağ üzerinden erişilir. Uzak makinedeki geçit yalnız çıkarım
isteklerini geçirir; model indirme ve eğitim o makinenin başında yapılır.

**Temel model.** Sprint 1'de ölçülerek seçilir (`docs/results/2026-11-17-model-bakeoff.md`).
Ölçüt: araç çağırma doğruluğu, hız, 12 GB'de QLoRA ile eğitilebilirlik, dizüstünde yedek
olarak çalışabilme. Seçim Burak'ındır.

**İnce ayar (Duyuru 3).** Kayıt biçimi: soru → doğru araç çağrısı → araç çıktısı → kanıta
dayalı açıklama. Veri şablonlarla ve gerçek araç çıktılarıyla üretilir; dört zorunlu
senaryoyu, sekiz etiketi ve olumsuz örnekleri (kanıt yetersiz, kapı bloğu, tavsiye isteği,
geçersiz girdi) kapsar; iki dildedir. Yöntem QLoRA. Model GGUF'a çevrilip Ollama'da
çalıştırılır.

**Weight-space programming (yan yol, Sprint 6).** Temel model, LoRA modeli ve LoRA +
ağırlık düzenlemesi aynı değerlendirme setinde karşılaştırılır; sonuç ne olursa olsun
raporlanır ve yapay zekâ kullanım ekinde belgelenir.

**Çağrı ayarları.** `temperature=0`, `seed=42`, `think=false`; sistem istemi ve araç
şemaları bir analiz boyunca aynı kalır.

## 12. Değerlendirme

Harness deneyleri (§30), model sabit tutularak:

| Sürüm | İçerik |
| --- | --- |
| A | Ham LLM; veri metin olarak verilir, araç zorunluluğu yok |
| B | LLM + araçlar |
| C | B + durumlu harness (izinler ve sıra) |
| D | C + kanıt ve kalite kapısı |
| E | D + bellek ve insan incelemesi |

Metrikler: sayısal halüsinasyon oranı, hatalı araç çağrısı oranı, kanıtsız sonuç oranı,
kanıt bütünlüğü, tekrarlanabilirlik, backtest doğruluğu, araç çağrısı sayısı, gecikme.

Araştırma katmanlarının metrikleri (§31) senaryo raporlarında verilir. Değerlendirme soru
seti ince ayar verisinden önce dondurulur ve eğitimle çakışmaz.

## 13. Açık sorular ve bilinen sorunlar

- **Temel veri kaynağı** seçilmedi (Sprint 3).
- **Peer grubu:** 30 hissenin 12'sinin evrende sektör eşi yok; referans hisseler ve sektör
  endeksleri Sprint 2'de belirlenir.
- **Nihai temel model** RTX 5070 ölçümünden sonra seçilecek.
- **QLoRA'nın 12 GB'de ve Windows'ta çalışması** Sprint 2'de denenecek (EC-006).
- Sprint 1 ince hat sonuçları ve orada görülen sorunlar bu bölüme eklenir.
