# İnce ayar (fine-tuning)

CSE-481 Mühendislik Ekonomisi — yalnız eğitim amaçlıdır, yatırım tavsiyesi değildir.

## Veri tasarımı ve kapsama

### Kayıtlar harness'ten toplanır

Eğitim verisi elle yazılmaz. Üretilen her soru gerçek harness'ten (`machine.run_analysis`)
geçer; modelin yerinde öğretmen istemci (`finetune/teacher.py`, `TeacherClient`) durur.
Araçlar gerçek veriyle çalışır. Harness'in her model turunda gönderdiği mesajlar ve araç
şemaları olduğu gibi, öğretmenin o turdaki doğru cevabı da hedef olarak kaydedilir.
Böylece model eğitimde, çıkarımda göreceği istemlerin aynısını görür: istem metni,
durum adları, kanıt listesi ve araç şemaları bayt bayt aynıdır. Harness'in istemleri
değişirse veri yeniden üretilir.

### Kayıt biçimi

Her satır bir `TrainingRecord`'dur (`finetune/record.py`, JSON Lines, satır sonu
`\n`). Anahtarlar sıralanmaz: mesajlar ve araç şemaları harness'in kurduğu sırayla
yazılır, çünkü sohbet şablonu onları bu sırayla işler. Aynı kayıtlar aynı baytları ve
aynı SHA-256'yı verir.

| Alan | İçerik |
| --- | --- |
| `record_id`, `question_id`, `family` | kaydın, sorunun ve soru şablonu ailesinin kimliği |
| `language`, `scenario` | cevabın dili (`tr`/`en`) ve sorunun senaryosu |
| `turn`, `state` | tur türü; araç turunda durum adı |
| `messages`, `tools` | harness'in o turda gönderdiği mesajlar ve sunduğu araç şemaları |
| `target` | doğru cevap: metin (`content`) ya da araç çağrıları (`tool_calls`) |
| `meta` | tur düzeyi (öğretmen yazar): araç turunda `state`, açıklama turunda `action` ve `eligible`; koşu düzeyi (Task 3'ün üretim hattı ekler): `outcome`, `snapshot_id`, `layers_id`, `today`, `template` |

### Üç tur türü

| Tur | Harness'in istemi | Hedef |
| --- | --- | --- |
| `intent` | `INTENT_SYSTEM_PROMPT` + soru | `INTENT_SCHEMA`'ya uyan doğru niyet (JSON) |
| `tool_call` | `TOOL_STATE_PROMPT` ile başlayan durum istemi + soru | o durumun kanonik çağrıları (`canonical_calls`), metin yok |
| `explanation` | uygun etiketler, kurallar, committed kanıt listesi | `{"action", "explanation"}`: her committed madde için bir satır, sayısı işaretiyle, `[En]` atfıyla; gerekiyorsa dönem notu; uyarı satırı |

Öğretmen her hedefi kodun denetiminden geçirir: niyet sorudan temellenmiş olmalı
(`ground_intent` hiçbir alanı değiştirmemeli), araç çağrıları `check_call`'dan,
açıklama `validate_explanation`'dan geçmeli. Geçmeyen hedef yazılmaz (`TeacherError`);
harness bir cevabı reddedip aynı turu yeniden sorarsa da öğretmen durur ve o soru veriden
çıkar.

Altın etiket verilmemişse uygun etiketler arasından sabit bir öncelikle seçilir: herhangi
bir `*_CANDIDATE` > `REJECT_SIGNAL` > `WATCH` > `HOLD` > `INVESTIGATE`. Öğretmen
`ANALYSIS_UNSAFE`'i kendiliğinden seçmez. Verilen altın etiket uygunsa her zaman o kullanılır.

Kanonik çağrısı olmayan bir araç durumunda (ör. hisse adı geçmeyen bir sektör sorusunda
hisse isteyen durum) öğretmen boş cevap verir ve o tur için kayıt yazmaz: öğretilecek
doğru bir çağrı yoktur. Harness kendi geri dönüşünü çalıştırır, soru veride kalır.

### Kapsama

Kapsama tablosu dört boyutludur:

- **Senaryo (4):** `SECTOR_LAGGARD`, `CALENDAR_PATTERN`, `TECHNICAL_REVERSAL`,
  `FUNDAMENTAL_REACTION`; ek olarak `BACKTEST`, `PRICE_SUMMARY`, `MACRO_CONTEXT`,
  `NEWS_CONTEXT`.
- **Etiket (8):** `HOLD`, `WATCH`, `INVESTIGATE`, `POTENTIAL_CATCH_UP_CANDIDATE`,
  `TECHNICAL_REVERSAL_CANDIDATE`, `FUNDAMENTAL_IMPROVEMENT_CANDIDATE`, `REJECT_SIGNAL`,
  `ANALYSIS_UNSAFE`.
- **Olumsuz örnekler:** tavsiye isteği, fiyat tahmini, evren dışı hisse, gelecek tarih,
  araç gerektirmeyen soru, eksik bilgi. Bunlarda yalnız `intent` turu vardır (ya da
  analiz `ANALYSIS_UNSAFE` ile kapanır); model reddetmeyi niyet turunda öğrenir.
- **Dil (2):** her aile Türkçe ve İngilizce.

Senaryo × etiket tablosunun her hücresi dolu olmayabilir (ör. bir senaryonun aday
etiketi başka senaryoda çıkmaz). Ulaşılamayan hücreler gerekçesiyle bu bölüme yazılır ve
sayılmaz; sayılar üretim manifestinden gelir.

Temel veri kullanan C–E stratejileri yalnız ön kayıtlı test dönemi (2025-01-01 ve
sonrası) için tanımlıdır. 2025'ten önce biten dönemlerde `FUNDAMENTAL_REACTION`
sorularının kanonik backtest'i `B_TECH_SECTOR`'dür (`machine.canonical_calls`); eğitim
tarihleri 2025'ten önce kaldığı için eğitim verisinde aday etiketi bu backtest'le
değerlendirilir. Bu hücrenin
gerçek veride dolup dolmadığı üretim manifestinden okunur.

#### Ulaşılabilir ve ulaşılamaz hücreler

Bir hücrenin etiketi sorunun koşu sonucudur (`meta.outcome`); sayılar kayıt (tur)
sayısıdır. Harness'in uygun etiket kuralına (`harness.actions.eligible_actions`) ve
öğretmenin önceliğine göre dört senaryoda ulaşılabilir hücreler:

| Senaryo | Ulaşılabilir etiketler |
| --- | --- |
| `SECTOR_LAGGARD` | `WATCH`, `INVESTIGATE`, `ANALYSIS_UNSAFE`, `POTENTIAL_CATCH_UP_CANDIDATE` |
| `CALENDAR_PATTERN` | `WATCH`, `INVESTIGATE`, `ANALYSIS_UNSAFE`, `REJECT_SIGNAL` |
| `TECHNICAL_REVERSAL` | `WATCH`, `INVESTIGATE`, `ANALYSIS_UNSAFE`, `TECHNICAL_REVERSAL_CANDIDATE` |
| `FUNDAMENTAL_REACTION` | `WATCH`, `INVESTIGATE`, `ANALYSIS_UNSAFE`, `FUNDAMENTAL_IMPROVEMENT_CANDIDATE` |

Yapı gereği boş kalan hücreler (sayılmaz):

- **Başka senaryonun aday etiketi:** aday etiketi senaryoya bağlıdır
  (`CANDIDATE_LABEL`); ör. `CALENDAR_PATTERN` × `TECHNICAL_REVERSAL_CANDIDATE` çıkmaz.
- **`REJECT_SIGNAL`, takvim dışı:** yalnız anlamsız haftanın günü sonucunda uygun olur.
- **`HOLD`, dört senaryoda:** `HOLD` uygun olduğunda `WATCH` da uygundur ve öğretmen
  `WATCH`'u seçer; açık `HOLD` gold'u yalnız `price_summary_hold` ve
  `macro_context_hold` ailelerinde vardır. Dört senaryoda `HOLD` öğretilmez.

**Kapsama (sentetik ve gerçek veri):** `tests/test_finetune_build.py`
(`test_coverage_has_no_empty_cell`) üretimi sentetik anlık görüntüde çalıştırır ve
ulaşılabilir her hücrenin dolu olduğunu, yalnız aşağıdaki hücrelerin sentetik veride boş
kaldığını denetler (liste testte gerekçesiyle durur; dolan hücre listeden çıkarılır):

| Hücre | Sentetik veride neden boş |
| --- | --- |
| `CALENDAR_PATTERN` × `WATCH` | rastgele yürüyüş fiyatlarında haftanın günü etkisi anlamlı çıkmaz; tam koşu hep `REJECT_SIGNAL` |
| `FUNDAMENTAL_REACTION` × `WATCH`, `FUNDAMENTAL_IMPROVEMENT_CANDIDATE` | sentetik temel veride 2025'ten önce tek rapor (2024 3. çeyrek) var; temel değişim kanıtı tamamlanmaz |
| `SECTOR_LAGGARD` × `POTENTIAL_CATCH_UP_CANDIDATE` | sentetik sektör backtest'leri sınırlı (az işlem ya da al-tut'un altında); aday uygun olmaz |

Gerçek verideki kapsama için yetkili kaynak üretim manifestidir (`manifest.json`,
`coverage`); boş hücreler ve nedenleri `docs/results/` altındaki üretim sonucunda yazılır.

## Üretim hattı ve bölme

Tek komut veri setini aynı baytlarla yeniden üretir (tohum 42):

```
uv run python -m bist_harness.finetune.build --n-per-family 30 --out data/finetune/
```

`finetune/build.py` (`build`, `split_by_family`):

1. `generate(n, seed)` soruları üretir; `drop_overlaps` donmuş sete benzeyenleri atar.
2. Her soru gerçek harness'ten (`machine.run_analysis`) öğretmenle geçer; araçlar süreç
   içinde, etkin anlık görüntüde çalışır (`run_eval._server_call_tool`). Model ve ağ
   yoktur. Koşudan sonra her kayda koşu düzeyi `meta` eklenir: `outcome`,
   `snapshot_id`, `layers_id`, `today`, `template` (sorunun parafraz şablonu).
3. Atılan sorular manifestte nedenleriyle sayılır:
   - `overlap`: donmuş setle çakışma (`text_overlap`, `expected_triple`);
   - `teacher_errors`: öğretmen bir turu cevaplayamadı (`TeacherError` ya da
     `ValueError`, mesajıyla); üretim sürer;
   - `test_period_date`: sorunun bir kaydında (mesajlar, araç şemaları, hedef)
     2025-01-01 ya da sonrasına ait bir tarih var (`YYYY-MM-DD`, `YYYY-MM`,
     `YYYYQn`). Ön kayıtlı test dönemi eğitime girmez. Araç çıktıları kayda yalnız
     açıklama turunun kanıt cümleleriyle girer; bu yüzden denetim kayıt metnindedir.
4. Bölme parafraza göre yapılır: aynı parafraz kümesini paylaşan aileler (ör. dört
   `sector_laggard_*` ailesi) tek bir küme sayılır; her dilde en az 3 parafrazı olan
   her kümeden `val` ve `test` için `max(1, round(0,1 × boyut))` parafraz tohum 42 ile
   ayrılır (6 parafrazda birer tane). Bu parafrazlarla yazılmış sorular yalnız
   `val`/`test`'te görünür; `train` onları hiç görmez. Bir sorunun bütün turları aynı
   bölümdedir. Daha az parafrazlı bir kümenin soruları tek tek kurayla bölünür.
5. Dosyalar: `train.jsonl`, `val.jsonl`, `test.jsonl` (`TrainingRecord` satırları),
   `dev_questions.jsonl` ve `manifest.json`.

**`dev_questions.jsonl`:** `test` bölümündeki her soru için bir satır, donmuş setin
biçiminde (`id`, `category`, `lang`, `question`, `source`, `trap`, `expected`) ve ek
olarak `family`, `today`. `expected` gold'dan ve gözlenen koşudan kurulur: `scenarios`
gold senaryo; `outcomes` koşu sonucunun sınıfı (`metrics.outcome_class`); `ticker`,
`sector`, `start`, `end`, `as_of` gold niyetten; `reason` kapının `check_intent`
kodu; `tools` öğretmenin çağırdığı araçlar. Task 7 bunu
`run_eval --questions-file data/finetune/dev_questions.jsonl` ile koşar; `verify_frozen`
yalnız donmuş dosyaya uygulanır. Kendi `today`'i olan soru o günle koşar.

**Manifest** (`manifest.json`, anahtarlar sıralı, girintili; eğitim kaydı değildir):
`counts.cells` bölüm × tur × senaryo × etiket × dil × aile kayıt sayıları (anahtar
`split|turn|scenario|label|language|family`) ve bölüm başına kenar toplamları; `records`,
`questions`; `dropped`, `teacher_errors`, `dropped_counts`; `coverage` (dört senaryo ×
sekiz etiket, boş hücreler, olumsuz aileler); `snapshot_id`, `layers_id`, `git_commit`
(`git` yoksa `unknown`); her dosyanın `sha256`, kayıt sayısı ve boyutu; `seed`,
`n_per_family`, `today_range`; `wall_time_s`. Yeniden üretim karşılaştırmasında yalnız
`wall_time_s` farklı olabilir (`test_build_twice_gives_identical_files`).

## Soru üretimi

Sorular şablonlardan üretilir (`finetune/questions.py`, `generate(n, seed=42)`); her
aile Türkçe ve İngilizce, resmî ve günlük en az 6 parafraz taşır, Türkçe günlük
biçimlerin bir kısmı aksansızdır (ayrıca üretimde Türkçe sorunun yaklaşık beşte biri
aksansız yazılır). Aile başına `n` soru, diller dönüşümlü. Gold niyet yalnız sorunun
adlandırdığını taşır: hisse kodla, şirket adıyla ya da küçük harfli kodla; tarih yalnız
metinde yazılıysa; sektör yok. `ground_intent` bir gold'u değiştirirse soru yeniden çekilir.

| Aile | Gold senaryo | Not |
| --- | --- | --- |
| `{sector_laggard, calendar_pattern, technical_reversal, fundamental_reaction}_{dated, undated, company, lowercase}` | ilgili senaryo | 16 aile: tarihli, tarihsiz (varsayılan dönem), şirket adıyla, küçük harfli kodla |
| `backtest`, `price_summary`, `macro_context`, `news_context` | `BACKTEST`, `PRICE_SUMMARY`, `MACRO_CONTEXT`, `NEWS_CONTEXT` | tarihli ya da tarihsiz |
| `price_summary_hold`, `macro_context_hold` | `PRICE_SUMMARY`, `MACRO_CONTEXT` | gold etiketi açıkça `HOLD` (varsayılan öncelikte `HOLD` hiç seçilmez) |
| `advice_request`, `prediction_request` | `ADVICE_REQUEST`, `PREDICTION_REQUEST` | anahtar sözcük koruması aynı etiketi verir |
| `out_of_universe` | `PRICE_SUMMARY`, evren dışı kod | harness `UNKNOWN_TICKER` ile kapatır |
| `future_date` | `PRICE_SUMMARY` | dönem `today`'den sonra, yine de 2025'ten önce |
| `no_tool_greeting`, `no_tool_off_topic` | `OUT_OF_SCOPE` | araç gerekmez |
| `missing_information` | senaryo, `ticker` boş | hisse adı geçmez |

**Tarih kuralı:** her gold tarihi ve her `today` 2025-01-01'den öncedir; üretilen dönem
`today`'de ya da öncesinde biter (`future_date` bunun tek istisnasıdır).
`ANALYSIS_UNSAFE` kapıdan gerçek veride çıkar, soru ailesiyle seçilmez; `HOLD` yalnız
açık gold'la; kapsama Task 3'te gerçek çıktıyla doğrulanır.

**Çakışma kuralı:** `drop_overlaps`, donmuş sete `eval.questions.overlaps` eşiğiyle
benzeyen soruyu ya da gold (hisse, başlangıç, bitiş) üçlüsü donmuş bir sorunun beklenen
üçlüsüne eşit olan soruyu atar; atılanlar nedenle (`text_overlap`, `expected_triple`)
ve donmuş soru kimliğiyle döner.

