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
