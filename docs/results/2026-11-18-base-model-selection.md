# Temel model ölçümü ve seçimi (Task 7, EC-005)

CSE-481 Mühendislik Ekonomisi — yalnız eğitim amaçlıdır, yatırım tavsiyesi değildir.

Ölçüm günü: 18 Kasım 2026. Seçim Burak'ındır; bu belge seçenekleri ve önerimi yazar,
karar günlüğüne `Bekliyor` olarak girer. Seçim gelene kadar Task 8'in dizüstü denemesi
`qwen3.5` 0.8B ile sürer.

Üç aday da aynı donanımda, RTX 5070'te ölçüldü: `qwen3.5:2b`, `qwen3.5:4b`,
`qwen3.5:9b-q4_K_M`. `qwen3.5:2b` ve `qwen3.5:4b`'yi Burak ölçüm günü masaüstünde indirdi
(geçit model indirmeye izin vermez). Eğitilebilirlik ve dizüstü sütunlarında ölçülmeyen
değerler "tahmin" diye işaretlidir. Saatler Türkiye saatidir (UTC+3).

## Ortam

| | |
| --- | --- |
| Çıkarım | RTX 5070 (12 GB), masaüstü; dizüstünden kullanıcının geçidi üzerinden (adres yalnız git dışı `.env`'de) |
| Masaüstü Ollama | **0.40.4** (geçitten `/api/version`) |
| Ölçülen modeller | `qwen3.5:2b` (1,9 B, Q8_0, 2,68 GB), `qwen3.5:4b` (4,2 B, Q4_K_M, 3,32 GB), `qwen3.5:9b-q4_K_M` (9,0 B, Q4_K_M, 6,55 GB); boyutlar görüntü projektörü dahil, `/api/tags`. 2b ve 4b dizüstündekilerle aynı yapı (manifest özeti `0689d440…`, `d8b0f5e9…`) |
| Harness kodu | `452e032` (`sprint-5-dev`) |
| Anlık görüntü | `20261117-0722`, `layers_id` `21b3a428` |
| Ayarlar | deney E, sıcaklık 0, tohum 42, düşünme kapalı, iki tekrar |

### Geçit yalnız OpenAI uyumlu yolu geçiriyor

İlk koşuda 120 kaydın hepsi `MODEL_UNAVAILABLE` ile bitti: geçit Ollama'nın yerel
`/api/chat` ve `/api/generate` yollarına `404 Inference route only` döndürüyor; yalnız
`/v1/chat/completions` (ve listeleme: `/api/tags`, `/api/version`, `/v1/models`) geçiyor.
Harness yalnız `/api/chat` kullanıyordu. Bu yüzden istemciye ikinci bir yol eklendi
(`452e032`): `BIST_LLM_API=openai` aynı isteği `/v1/chat/completions`'a gönderir —
aynı model, mesajlar, araç şemaları, JSON şeması (`response_format` `json_schema`),
sıcaklık, tohum; `think: false` bu yolda `reasoning_effort: "none"`dır. Bağlam boyutu
(`num_ctx`) bu yolda verilemez; isteyen çağrı reddedilir (harness vermez, yalnız
`bakeoff` verir). Varsayılan yol değişmedi.

**Eşdeğerlik denetimi:** dizüstündeki Ollama 0.40.16'da `qwen3.5:0.8b` ile aynı 8
geliştirme sorusu (dört ana senaryo, `PRICE_SUMMARY`, `MACRO_CONTEXT`, `BACKTEST`, bir
tavsiye tuzağı), deney E, 1 tekrar, iki yoldan koşuldu. 8 sorunun hepsinde niyet, araç
çağrıları (yalnız rastgele `analysis_id` farklı), cevap ve açıklama denemeleri aynıydı;
gecikmeler aynı düzeydeydi. Gecikme ölçüsü iki yolda da harness'in duvar saati süresidir.
Fark: bu yolda Ollama üretim süresi bildirmez, `eval_tokens_per_s` boş kalır.

## Geliştirme soruları

`data/finetune/dev_questions.jsonl` zaten Task 3'ün `test` bölümünün 139 sorusunu
donmuş setin biçiminde taşıyor (sorular `test.jsonl`'daki `question_id`'lerle birebir
aynı). Bunlardan 60 soru senaryo dengeli seçildi (tohum 42; her kategoride diller
dönüşümlü, aile içinde döngüyle): dört ana senaryodan 8'er (4 Türkçe, 4 İngilizce),
`PRICE_SUMMARY` 5, `MACRO_CONTEXT` 5, `BACKTEST` 4, `NEWS_CONTEXT` 2 ve 12 tuzak (tavsiye,
tahmin, evren dışı, gelecek tarih, araçsız soru, eksik bilgi). Beklenen sonuç: 48
`ANALYSIS`, 4 `REFUSED_ADVICE`, 4 `ANALYSIS_UNSAFE`, 4 `OUT_OF_SCOPE`. Donmuş 120 soruluk
set kullanılmadı; test dönemi çalışması koşulmadı.

Dosya `data/finetune/dev60.jsonl` (git dışı), SHA-256
`1b7186aecdf59f7116d8ed0d3a081d98f6153832bb225c2112870cdacb35666c`; aynı dosya
`dev_questions.jsonl`'dan bu kimliklerle, dosyadaki sırayla çıkarılır:

```
sector_laggard_dated-0000,sector_laggard_dated-0012,sector_laggard_dated-0029,sector_laggard_undated-0001,sector_laggard_undated-0004,sector_laggard_company-0002,sector_laggard_company-0025,sector_laggard_lowercase-0007,calendar_pattern_dated-0013,calendar_pattern_dated-0024,calendar_pattern_undated-0027,calendar_pattern_company-0001,calendar_pattern_company-0002,calendar_pattern_company-0008,calendar_pattern_lowercase-0004,calendar_pattern_lowercase-0023,technical_reversal_dated-0000,technical_reversal_dated-0019,technical_reversal_undated-0008,technical_reversal_company-0007,technical_reversal_company-0010,technical_reversal_company-0017,technical_reversal_lowercase-0002,technical_reversal_lowercase-0017,fundamental_reaction_dated-0001,fundamental_reaction_dated-0006,fundamental_reaction_undated-0001,fundamental_reaction_undated-0018,fundamental_reaction_company-0015,fundamental_reaction_company-0024,fundamental_reaction_lowercase-0002,fundamental_reaction_lowercase-0011,backtest-0012,backtest-0014,backtest-0018,backtest-0019,price_summary-0000,price_summary-0025,macro_context-0002,macro_context-0005,news_context-0004,news_context-0025,price_summary_hold-0007,price_summary_hold-0008,price_summary_hold-0018,macro_context_hold-0002,macro_context_hold-0017,macro_context_hold-0028,advice_request-0023,advice_request-0026,prediction_request-0000,prediction_request-0023,out_of_universe-0025,future_date-0009,future_date-0024,no_tool_greeting-0002,no_tool_greeting-0023,no_tool_off_topic-0012,no_tool_off_topic-0021,missing_information-0006
```

Komut (her aday için `--model` değişir):

```
BIST_LLM_API=openai uv run python -m bist_harness.eval.run_eval --experiments E --repeats 2 \
  --questions-file data/finetune/dev60.jsonl --model qwen3.5:9b-q4_K_M \
  --out runs/base-model-selection/qwen3.5-9b
```

## Sonuçlar

Her model 60 soru × 2 tekrar = 120 kayıt, sırayla (aynı anda tek model):

| Model | Başlangıç – bitiş (TSİ) | Duvar saati | Hata kaydı |
| --- | --- | --- | --- |
| `qwen3.5:9b-q4_K_M` | 13:20:32 – 13:36:31 | 15 dk 59 sn | 0 |
| `qwen3.5:4b` | 14:18:17 – 14:31:32 | 13 dk 15 sn | 0 |
| `qwen3.5:2b` | 14:31:35 – 14:40:30 | 8 dk 55 sn | 0 |

Geçit hiçbir koşuda kesilmedi. 2b ve 4b'nin ilk denemesi (13:49'dan itibaren) iki koşu
aynı anda GPU'yu paylaşacak biçimde başladığı için gecikmesi geçersiz sayıldı, durduruldu
ve atıldı (`runs/base-model-selection/discarded-overlap/`); tablodakiler sıralı yeniden
koşulardır. Ölçütler `eval/metrics.py`'den (`summary.json`,
`runs/base-model-selection/qwen3.5-*/`, git dışı).

| Ölçüt | `qwen3.5:2b` | `qwen3.5:4b` | `qwen3.5:9b-q4_K_M` |
| --- | --- | --- | --- |
| Niyet: hisse doğruluğu, ham (`ticker_accuracy_raw`) | 0,395 | 0,698 | **0,767** |
| Niyet: hisse doğruluğu, temellendirmeden sonra (`ticker_accuracy_grounded`) | 0,907 | **0,977** | 0,907 |
| Uydurulan alan (`invented_fields`, 120 kayıtta) | 168 (sektör 78, hisse 50, tarih 40) | 38 (hisse 34, tarih 4) | **24** (hisse 14, sektör 4, tarih 6) |
| Senaryo doğruluğu (`scenario_accuracy`) | 0,750 | 0,938 | **1,000** |
| Hatalı çağrı oranı (`wrong_tool_call_rate`, ret / önerilen) | 0,098 (28 / 286) | 0,092 (36 / 392) | **0,042** (16 / 378) |
| Harness müdahalesi (kanonik geri dönüş) | 62 | 86 | **48** |
| Açıklama kabulü (geri düşmeden, açıklamaya ulaşan kayıtta) | 2 / 78 (%2,6) | 64 / 92 (%69,6) | **72 / 88 (%81,8)** |
| Açıklama geri dönüşü (`explanation_fallbacks`) | 76 / 78 (%97,4) | 28 / 92 (%30,4) | **16 / 88 (%18,2)** |
| Sonuç eşleşmesi (`outcome_match_rate`) | 0,850 | **0,967** | 0,933 |
| Tuzak doğru ele alındı / yanlış ret | 1,000 / 0,083 | 1,000 / 0,021 | 1,000 / **0,000** |
| Modelin yazdığı desteksiz sayı (bütün denemeler) | 60 / 564 (0,106) | 20 / 894 (0,022) | **4 / 734 (0,005)** |
| Gösterilen cevapta desteksiz sayı | 0 / 6 | 0 / 408 | 0 / 544 |
| Tekrarlanabilirlik (aynı soru, iki tekrar) | 60 / 60 | 60 / 60 | 60 / 60 |
| Kural ihlali | 0 | 0 | 0 |
| Gecikme medyanı / ortalama / en çok (sn, 5070) | **3,5 / 3,4 / 13,9** | 5,9 / 5,6 / 17,3 | 6,8 / 6,8 / 15,2 |

Okuma, model model (ince ayarsız; 60 soru, 2 tekrar: bir sorunun değişmesi bir oranı
yaklaşık 1,7 puan oynatır; iki tekrar her modelde birebir aynı çıktığı için tekrarlar
bağımsız örnek sayılmaz):

**`qwen3.5:2b`:** harness'in kapıları sayesinde güvenli (kural ihlali 0, gösterilen
cevapta desteksiz sayı yok, tuzaklar doğru) ama model kendi başına zayıf. Niyet turunda
her sorunun ortalama 1,4 alanını uyduruyor (çoğu sektör); senaryoyu dört kayıttan birinde
yanlış seçiyor (çoğu `PRICE_SUMMARY`, makro sorularında `OUT_OF_SCOPE`). Açıklamaların
neredeyse hepsi (76/78) doğrulayıcıdan geçmedi ve harness'in kendi açıklamasına düştü;
yazdığı sayıların %10,6'sı kanıtta yok. Sonuç eşleşmesindeki kayıplar (9 soru): makro
sorularının beşi (dördü `OUT_OF_SCOPE` — yanlış retlerin hepsi bunlar —, biri
`ANALYSIS_UNSAFE`), takvim sorularının üçü ve `backtest-0012` (`ANALYSIS_UNSAFE`). En hızlısı (medyan 3,5 sn).

**`qwen3.5:4b`:** sonuç eşleşmesi en yüksek (0,967): temellendirme hisseyi en çok bu
modelde kurtarıyor (0,977), çünkü model kodu yanlış yazsa da soruda adı geçen hisseyle
çelişmiyor. Ham hisse doğruluğu 0,70; uydurulan 38 alanın 34'ü hisse. Hatalı çağrı oranı
9B'nin iki katı (36 ret; sektör 12, örüntü 12, veri yükleme 6, backtest 4) ve harness en
çok bu modele müdahale etti (86; 40'ı `FUNDAMENTAL_REACTION`). Açıklama kabulü %70.
Kayıplar: `technical_reversal_company-0007` (`MISSING_TICKER`, 9B'de de) ve
`macro_context_hold-0002` (`OUT_OF_SCOPE`). İki kayıtta yanlış ret var (bu soru).

**`qwen3.5:9b-q4_K_M`:**

- **Niyet turu ana zayıflık.** Senaryo her kayıtta doğru, ama hisse kodu ham hâliyle
  %77 doğru: model şirket adıyla sorulan sorularda kodu değil adı yazıyor
  (`TOFAS` → doğrusu `TOASO`) ya da hisseyi boş bırakıyor (`ISMEN`). Temellendirme bunun
  bir kısmını düzeltiyor (%91); düzeltemediği dört soru (`sector_laggard_company-0025`,
  `backtest-0012`: `UNKNOWN_TICKER`; `technical_reversal_company-0007`,
  `fundamental_reaction_lowercase-0002`: `MISSING_TICKER`) iki tekrarda da
  `ANALYSIS_UNSAFE` ile kapandı — sonuç eşleşmesindeki 8 kaybın hepsi bunlar. Uydurulan
  24 alanın 14'ü hisse; aileler `*_company`, `price_summary*`, `news_context`,
  `advice_request`.
- **Araç turları iyi:** 378 önerilen çağrının 16'sı reddedildi, hepsi sektör
  (`RUN_SECTOR_RELATIVE_ANALYSIS`, 12) ve örüntü (`RUN_PATTERN_AND_REVERSAL_ANALYSIS`, 4)
  durumlarında. Harness'in 48 müdahalesinin 26'sı `FUNDAMENTAL_REACTION` sorularında.
- **Açıklama:** açıklamaya ulaşan 88 kaydın 16'sında doğrulayıcı iki denemeyi de
  reddetti ve harness kendi açıklamasına düştü; bunların 8'i `CALENDAR_PATTERN`
  (`dated`, `lowercase`), 6'sı `FUNDAMENTAL_REACTION`.
- Tuzakların hepsi doğru, yanlış ret yok, iki tekrar birebir aynı, kural ihlali yok.
- 9B, temellendirmeden önceki model davranışında her ölçütte en iyisi (ham hisse,
  uydurulan alan, senaryo, hatalı çağrı, açıklama, desteksiz sayı); sonuç eşleşmesinde 4B
  bir soru (iki kayıt) önde, çünkü 9B'nin şirket adı yazdığı iki soruyu temellendirme
  kurtaramıyor.

**Ortak:** üç modelin zayıflıkları aynı yerde ve eğitim verisinin öğrettiği şeyler:
şirket adından/küçük harften hisse kodu, sektör (`RUN_SECTOR_RELATIVE_ANALYSIS`) ve
örüntü çağrıları, `FUNDAMENTAL_REACTION` araç durumları, takvim ve temel veri açıklamaları.

## QLoRA ile 12 GB'de eğitilebilirlik (tahmin)

Parametre sayıları: 0.8B, 2B ve 4B için dizüstündeki Ollama GGUF'larının tensör
boyutlarından (dil modeli; Ollama'nın `general.size_label`'ıyla aynı), 9B için Hugging
Face `Qwen/Qwen3.5-9B` yapılandırmasından (`c2022362`) hesaplandı. Hepsi aynı mimari
(Gated DeltaNet + her 4 katmanda bir tam dikkat), sözlük 248.320 belirteç. 2B ve 4B'de
gömme ile çıkış katmanı paylaşılır; **9B'de paylaşılmaz** (ayrı `lm_head`).

Bellek tahmini, eğitimin bugünkü kodu (`finetune/train.py`) ve 5070 ayarları için
(toplu boyut 1, en uzun kayıt 1.475 belirteç): NF4 dil ve görüntü katmanları (çift
nicemlemeyle ≈ 0,516 bayt/parametre); `prepare_model_for_kbit_training`'in fp32'ye
yükselttiği gömme (ve 9B'de çıkış) katmanı; LoRA ağırlığı, gradyanı ve 8 bit Adam
(≈ 10 bayt/parametre); gradient checkpointing'li etkinlikler; logit ve kayıp belleği.
Logit terimi (≈ 3,7 GB) dizüstü denemesinden ayarlandı: 0.8B'de ölçülen en yüksek ayrılmış
bellek 5,36 GB, öteki terimlerin toplamı ≈ 1,6 GB (`docs/results/2026-11-18-finetune-training.md`).
Logit terimi model boyutuna değil sözlüğe ve dizi uzunluğuna bağlıdır; bu yüzden
küçük modellerde baskındır.

| Model | Dil modeli parametresi | Gömme (+ çıkış) | LoRA r16 / r32 | Tahmini en yüksek bellek r16 / r32 | 12 GB |
| --- | --- | --- | --- | --- | --- |
| 0.8B (ölçüm, r8) | 0,752 B | 0,254 B (paylaşılan) | 5,1 M (r8) | 5,36 GB ölçüldü | — |
| 2B | 1,882 B | 0,509 B (paylaşılan) | 15,6 M / 31,3 M | ≈ 7,2 / 7,4 GB | sığar |
| 4B | 4,206 B | 0,636 B (paylaşılan) | 30,5 M / 60,9 M | ≈ 9,3 / 9,6 GB | sığar, pay ≈ 2 GB |
| 9B | 8,95 B | 2,034 B (ayrı) | 40,1 M / 80,2 M | ≈ 17,2 / 17,6 GB | **sığmaz** |

- **9B bugünkü kodla 12 GB'ye sığmaz:** fp32'ye yükseltilen gömme ve çıkış katmanları tek
  başına ≈ 8,1 GB. Sığdırmak için kod değişikliği gerekir: bu iki katmanı bf16'da donuk
  bırakmak ve kaybı parçalı hesaplamak (tam sözlük logitini tutmamak). O zaman tahmin
  ≈ 9,7 GB (r16) — sınırda, Windows'un ekran belleğiyle risklidir ve denenmedi.
- Tahminler PyTorch'un ayırdığı bellektir; CUDA bağlamı (≈ 0,5 GB) ve parçalanma
  (dizüstünde rezerve 9,9 GB / ayrılmış 5,4 GB) eklenmez. 4B için masaüstünde 20 adımlık
  bir deneme bu tahmini ölçer (`docs/finetune.md`, adım 4b). 12 GB aşılırsa Windows
  paylaşılan belleğe taşır: koşu düşmez, yavaşlar.
- Eğitim sırasında Ollama 5070'te model tutmamalıdır.

## Dizüstünde yedek olarak çalışabilme (çoğu tahmin)

Dizüstü: RTX 3050 Ti 4 GB, 16 GB RAM, Ollama 0.40.16. Kurallar gereği `qwen3.5:4b`
dizüstünde yeniden çalıştırılmadı (önceki bir arka plan koşusu bellek darlığından
sistemce durdurulmuştu).

| Model | Ollama'daki boyut (model + görüntü projektörü) | Dizüstü | Kaynak |
| --- | --- | --- | --- |
| `qwen3.5:2b` | 2,01 GB (Q8_0) + 0,67 GB | çalışır, yavaş (5070'te medyan 3,5 sn): harness E gecikme medyanı 57–65 sn (donmuş setten 6 soru); bakeoff'ta %37 CPU / %63 GPU | ölçüldü (`2026-11-18-harness-live.md`, `2026-11-17-model-bakeoff.md`) |
| `qwen3.5:4b` | 2,65 GB (Q4_K_M) + 0,68 GB | ince ayarsız model pratikte çalışmaz: bakeoff'ta %52 CPU / %48 GPU, 6,9 belirteç/sn; harness koşusu bellek darlığından durdu | ölçüldü (eski koşular) |
| ince ayarlı 4B (q4_K_M, dışa aktarılan) | ≈ 2,6 GB, projektör ve taslak bloğu yok | belirsiz: 4 GB'a sınırda sığabilir (projektör yok, 8 tam dikkat katmanlı küçük KV önbelleği) | **tahmin**, ölçülmedi |
| `qwen3.5:9b-q4_K_M` | 6,55 GB | çalışmaz (4 GB VRAM; 16 GB RAM'de CPU'ya taşırsa çok yavaş) | **tahmin** |

## Seçenekler ve önerim

| Seçenek | Artı | Eksi |
| --- | --- | --- |
| A. `qwen3.5:4b` ile ince ayar | 12 GB'ye bugünkü kodla sığar (≈ 9,5 GB, tahmin); ince ayarsız hâli 9B'ye yakın (sonuç eşleşmesi 0,967, senaryo 0,94); 9B'den hızlı (medyan 5,9 sn); ince ayarlı q4_K_M dizüstünde belki çalışır | model davranışında 9B'nin gerisinde: hatalı çağrı 0,092, açıklama kabulü %70, desteksiz sayı %2,2 |
| B. `qwen3.5:2b` ile ince ayar | rahat sığar (≈ 7,3 GB); en hızlı (3,5 sn); dizüstü yedeği kesin çalışır | en zayıf temel: açıklama kabulü %2,6, senaryo 0,75, 168 uydurulan alan, desteksiz sayı %10,6 |
| C. `qwen3.5:9b` ile ince ayar | ince ayarsız hâli en güçlü (hatalı çağrı 0,042, açıklama kabulü %82, desteksiz sayı %0,5) | bugünkü kodla 12 GB'ye sığmaz (≈ 17 GB); kod değişikliği ve sınırda bellek (≈ 9,7 GB, denenmedi); dizüstü yedeği yok |
| D. İnce ayar yok, `qwen3.5:9b` ince ayarsız | ölçüldü, en iyi model davranışı; ek iş yok | dersin ince ayar ayağını karşılamaz; dizüstü yedeği yok |

**Önerim: A — `qwen3.5:4b` ile ince ayar; `qwen3.5:9b` ince ayarsız hâliyle
karşılaştırma tabanı olarak kalır, `qwen3.5:2b` (ince ayarsız) dizüstü yedeği.**
Gerekçe:

- 12 GB'de bugünkü kodla eğitilebilen en büyük aday 4B; 9B kod değişikliği ister ve
  sığacağı bile belli değil.
- İnce ayarsız 4B, harness'in kapılarıyla birlikte 9B'ye çok yakın (sonuç eşleşmesi
  0,967'ye 0,933, tuzaklar 1,000) ve daha hızlı. Geride kaldığı yerler (hatalı çağrı,
  açıklama kabulü, uydurulan hisse) tam da eğitim verisinin öğrettiği turlar; 20 adımlık
  0.8B denemesi bile bu turlarda belirgin iyileşme göstermişti.
- "İnce ayarlı 4B, ince ayarsız 9B'ye yetişiyor mu" sorusu mühendislik ekonomisi açısından
  anlamlı: daha küçük model, daha az bellek, daha ucuz donanım.
- 2B'nin açıklama turu neredeyse hiç geçmiyor; ince ayar temeli olarak en riskli aday.
  Dizüstü yedeği olarak kalır: harness'in kapıları onu güvenli tutuyor (kural ihlali 0,
  gösterilen cevapta desteksiz sayı 0), açıklamayı harness yazıyor.

Şart: masaüstündeki 20 adımlık 4B denemesi (`docs/finetune.md`, adım 4b) 12 GB'ye
sığmalı. Sığmazsa 2B'ye geçmek ya da eğitim kodunda bellek düzeltmesi (bf16 gömme,
parçalı kayıp) seçenektir.

Seçilen modelin Hugging Face deposu ve commit'i (5070 ayar dosyalarına yazılacak):
`Qwen/Qwen3.5-4B` `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`, `Qwen/Qwen3.5-2B`
`15852e8c16360a2fea060d615a32b45270f8a8fc`, `Qwen/Qwen3.5-9B`
`c202236235762e1c871ad0ccb60c8ee5ba337b9a` (18 Kasım 2026'daki `main`). Ollama
GGUF'larının metaverisi `Qwen/Qwen3.5-<boyut>-Base`'i taban gösterir; eşleşen sohbet
deposu `-Base`'siz olandır (0.8B'deki gerekçeyle).

## Burak için masaüstü adımları

Masaüstündeki Ollama resmî Windows ZIP'inden `C:\AI-Server\ollama` klasörüne kurulu,
oturum açılışında zamanlanmış görevle başlıyor ve PATH'te değil. Bu yüzden her `ollama`
komutu tam yolla verilir; Git Bash'te önce:

```bash
OLLAMA="/c/AI-Server/ollama/ollama.exe"
export PATH="$PATH:/c/AI-Server/ollama"   # export.py ollama'yı PATH'te arar
```

(PowerShell: `$ollama = "C:\AI-Server\ollama\ollama.exe"`, `$env:Path += ";C:\AI-Server\ollama"`.)

1. (Yapıldı, 18 Kasım) `"$OLLAMA" pull qwen3.5:2b` ve `"$OLLAMA" pull qwen3.5:4b`.
   Başka bir model gerekirse aynı biçimde; geçit indirmeye izin vermiyor.
2. EC-006: `uv sync --group train` ve 20 adımlık deneme — `docs/finetune.md`, "RTX 5070'te
   çalıştırma", adım 0, 1 ve 4; seçilen modelle bellek denemesi adım 4b. Eğitimden önce
   `"$OLLAMA" stop <model>`: 5070'te Ollama model tutmamalı.
3. **Ollama 0.40.4:** dizüstünün dönüştürücü sabitlemesi (llama.cpp `6c01da627`,
   0.40.16) masaüstünde geçersizdir. Dışa aktarmadan önce 0.40.4'ün
   `/c/AI-Server/ollama/lib/ollama/llama-server.exe --version` commit'ine sabitlenir ve
   `template_check` 0.40.4'te, seçilen modelle yeniden koşulur (adım 6).
   `export` Ollama'yı PATH'te arar (`shutil.which("ollama")`; yoksa yalnız
   `%LOCALAPPDATA%\Programs\Ollama`'ya bakar): sürüm ve `llama-server` commit denetimi,
   `ollama create` ve yükleme denemesi bunun için PATH eklemesi olmadan çalışmaz.
   Nicemleyici de oradan aranır; `export`'a
   `--llama-quantize /c/AI-Server/ollama/lib/ollama/llama-quantize.exe` verilir.
   0.40.4'te `llama-server.exe`, `llama-quantize.exe` ve `_debug_render_only` olup
   olmadığı uzaktan doğrulanamadı.
4. Harness'i geçitten koşmak için ortamda ya da git dışı `.env`'de `BIST_LLM_API=openai`.
   Ya da geçide `/api/chat` eklenirse bu gerekmez.
