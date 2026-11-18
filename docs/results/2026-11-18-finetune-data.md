# İnce ayar verisi üretimi (Task 3, 18 Kasım 2026)

CSE-481 Mühendislik Ekonomisi — yalnız eğitim amaçlıdır, yatırım tavsiyesi değildir.

## Komut

```
uv run python -m bist_harness.finetune.build --n-per-family 30 --out data/finetune/
```

Gerçek anlık görüntü (`snapshot_id` `20261117-0722`, `layers_id` `21b3a428`), araçlar süreç
içinde, öğretmen istemci; model ve ağ yok. Kod commit'i `ab1d741`, tohum 42,
`today` aralığı 2019-06-01 – 2024-12-31. Süre: 237 s (870 soru, soru başına ≈ 0,27 s).
Veri dosyaları git dışıdır (`data/finetune/`); sayılar `manifest.json`'dan.

## Sorular ve atılanlar

29 aile × 30 = 870 soru üretildi, 870'i veride kaldı.

| Atılma nedeni | Soru |
| --- | --- |
| Donmuş setle çakışma (`overlap`) | 0 |
| Öğretmen hatası (`teacher_errors`) | 0 |
| Test dönemi tarihi (`test_period_date`, ≥ 2025-01-01) | 0 |

## Kayıt sayıları

| Bölüm | Soru | Kayıt | `intent` | `tool_call` | `explanation` | `tr` | `en` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| train | 582 | 2.407 | 582 | 1.440 | 385 | 1.203 | 1.204 |
| val | 144 | 628 | 144 | 377 | 107 | 338 | 290 |
| test | 144 | 652 | 144 | 403 | 105 | 304 | 348 |
| toplam | 870 | 3.687 | 870 | 2.220 | 597 | 1.845 | 1.842 |

Bölme parafraza göredir: her parafraz kümesinde dil başına bir parafraz `val`'e, bir
parafraz `test`'e ayrılır; bu yüzden `val` ve `test` hedeflenen %10 yerine yaklaşık
%17'şer sorudur.

**Senaryoya göre kayıt (train / val / test):** `SECTOR_LAGGARD` 391 / 181 / 141,
`CALENDAR_PATTERN` 394 / 125 / 72, `TECHNICAL_REVERSAL` 478 / 79 / 153,
`FUNDAMENTAL_REACTION` 497 / 95 / 123, `PRICE_SUMMARY` 199 / 42 / 62, `MACRO_CONTEXT`
160 / 40 / 40, `BACKTEST` 118 / 24 / 36, `NEWS_CONTEXT` 86 / 23 / 8, `OUT_OF_SCOPE`
45 / 8 / 7, `ADVICE_REQUEST` 21 / 4 / 5, `PREDICTION_REQUEST` 18 / 7 / 5.

**Etikete (koşu sonucu) göre kayıt (train / val / test):** `WATCH` 1.141 / 335 / 348,
`INVESTIGATE` 613 / 111 / 161, `REJECT_SIGNAL` 325 / 120 / 50, `HOLD` 140 / 28 / 60,
`ANALYSIS_UNSAFE` 74 / 15 / 10, `OUT_OF_SCOPE` 45 / 8 / 7, `REFUSED_ADVICE` 39 / 11 / 10,
`TECHNICAL_REVERSAL_CANDIDATE` 30 / 0 / 6.

## Kapsama (dört senaryo × sekiz etiket, tüm bölümler, kayıt)

| Senaryo | WATCH | INVESTIGATE | ANALYSIS_UNSAFE | REJECT_SIGNAL | Aday etiketi |
| --- | --- | --- | --- | --- | --- |
| `SECTOR_LAGGARD` | 612 | 91 | 10 | — | **0** |
| `CALENDAR_PATTERN` | 30 | 60 | 6 | 495 | — |
| `TECHNICAL_REVERSAL` | 606 | 66 | 2 | — | 36 |
| `FUNDAMENTAL_REACTION` | 84 | 627 | 4 | — | **0** |

Olumsuz ailelerin her biri 30 soruyla veride (tavsiye, tahmin, evren dışı, gelecek
tarih, selamlaşma, konu dışı, eksik bilgi).

Manifest 18 boş hücre listeler. 16'sı yapı gereğidir (`docs/finetune.md`, "Kapsama"):
dört senaryoda `HOLD` (öğretmen `WATCH`'u seçer), başka senaryonun aday etiketi,
takvim dışında `REJECT_SIGNAL`. Ulaşılabilir olup gerçek veride boş kalan iki hücre:

- **`SECTOR_LAGGARD` × `POTENTIAL_CATCH_UP_CANDIDATE`** ve
  **`FUNDAMENTAL_REACTION` × `FUNDAMENTAL_IMPROVEMENT_CANDIDATE`:** adayın şartı,
  backtest'in sınırlayıcı bayrak (`FEW_TRADES`, `UNDERPERFORMS_BUY_AND_HOLD`)
  taşımamasıdır. 2025 öncesi dönemlerde bu senaryoların kanonik backtest'i
  `B_TECH_SECTOR`'dür ve bir örneklem yoklamasında (bu iki senaryonun tarihli ve
  tarihsiz ailelerinden 120 soru) kanıtı tam olan her koşunun backtest'i
  `FEW_TRADES` ya da al-tut'un altında bayrağı taşıdı. Model bu iki aday etiketi
  eğitimde görmez; Task 9 karşılaştırmasında bu etiketler ayrıca okunmalıdır.

Ek gözlem: `FUNDAMENTAL_REACTION` kayıtlarının çoğu `INVESTIGATE`'tir (627 / 715); 2025
öncesi dönemlerde temel değişim ve fiyat tepkisi kanıtı çoğu zaman tamamlanmıyor.

## Dosyalar

| Dosya | Satır | Boyut (bayt) | SHA-256 |
| --- | --- | --- | --- |
| `train.jsonl` | 2.407 | 5.587.291 | `a57769d98ab8e712d06b48598948b167996c56f8de8c03f578a82b539ee792c6` |
| `val.jsonl` | 628 | 1.467.409 | `208cca2d8c333a7fd6afaf509a47165ce0f4698cd75e5a292993ba89365d66e0` |
| `test.jsonl` | 652 | 1.548.046 | `5e345c1869dd673a226e4561013d8166e02a3c7730ba86a78f924028c3f9108f` |
| `dev_questions.jsonl` | 144 | 79.131 | `3f88d881667d7a8565915ad91963081227bc239d2c8585953caf930e2fab94cf` |

## Kalite kontrolü ve tekrar temizliği (Task 4, EC-052)

Yukarıdaki sayılar tekrar temizliğinden önceki ilk üretimindir. Task 4, üretime bir
tekrar temizliği adımı (`qc.dedupe_report`, bölmeden önce) ekledi ve veri yeniden üretildi
(`git_commit` `d70c336`, aynı tohum ve komut, 244 s). Aşağıdaki sayılar son veridir.

**Tekrar temizliği** (soru düzeyinde; bir sorunun bütün turları birlikte kalır ya da gider,
`question_id` sırasında ilki kalır):

| Neden | Soru |
| --- | --- |
| Yakın kopya (katlanmış metin benzerliği ≥ 0,95, aynı turlar ve aynı hedefler) | 21 |
| Aynı metin, başka aile, farklı hedef | 10 |

On çakışan çiftin dağılımı: `macro_context` / `macro_context_hold` 5 (aynı metin biri WATCH,
biri HOLD'a götürüyordu), `*_undated` / `*_lowercase` aileleri 5. Toplam 31 soru, 69 kayıt
atıldı: 870 üretilen, 839 veride.

**Son kayıt sayıları:** train 2.361, val 618, test 639, toplam **3.618** (3.687'den
−69). Soru: 560 / 140 / 139. `intent` 839, `tool_call` 2.191, `explanation` 588.
`dev_questions.jsonl` 139 soru.

**Kalite kontrolü, 3.618 kayıt, bulgu 0.** İlk geçişte (tekrar temizliğinden önceki 3.687
kayıt) ve son veride her denetim için bulgu sayısı 0; şablon, üretici ya da öğretmen
düzeltmesi gerekmedi.

| Denetim | Bulgu |
| --- | --- |
| `numbers_in_tool_output` | 0 |
| `call_schema_valid` | 0 |
| `call_allowed_and_on_intent` | 0 |
| `label_in_eight` | 0 |
| `no_advice_language` | 0 |
| `validator_accepts` | 0 |
| `no_frozen_overlap` | 0 |
| `no_test_period_data` (2025 tarihi ya da tarihsiz "test döneminde" / "In the test period" ifadesi) | 0 |

QC temizlenmiş veride tekrar bulmuyor (0 yakın kopya, 0 çelişen hedef).

**Dosyalar (son):** `train.jsonl` 2.361 satır, SHA-256
`26a764d92f5c024b8f1e3056de4fa734281e7afe072ee7cd0038a520dffbe87c`; `val.jsonl` 618,
`23dd54999c0d33880d8c51537094845a9a21e2b6b4c54d2ff2cb98d39092aabb`; `test.jsonl` 639,
`e336429ddfd6dbb68085575a208b3b7e32445168a1898068e5707f40eb203d78`; `dev_questions.jsonl`
139, `72ee2224270c03db709f3c39fbe8f70d5d70a39b2bc0205fae8559417a5383d8`.

**Val ya da test sorusu olmayan aile × dil havuzları (manifest):** 9 havuz:
`calendar_pattern_undated` tr (test yok), `fundamental_reaction_undated` en (val yok),
`macro_context_hold` en (val yok), `missing_information` en (test yok), `out_of_universe`
tr (test yok), `sector_laggard_lowercase` tr (test yok), `technical_reversal_company` en
(val yok), `technical_reversal_lowercase` tr (val yok), `technical_reversal_undated` en
(test yok). Bunların bir kısmı küçük parafraz havuzu (bölme soru bazında), bir kısmı tekrar
temizliğinde sorunun elenmesidir; paraphrase bölmesi yine de bütün havuzlarda train ile
val/test'i ayırır.

**Elle okuma:** `data/finetune/review-sample.md` (50 kayıt, senaryo ve tur türüne göre
katmanlı) Burak'ın okuması içindir; okunmuş sayılmaz.
