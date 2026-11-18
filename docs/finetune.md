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

## Kalite kontrolü

`uv run python -m bist_harness.finetune.qc data/finetune/` her kaydı harness'in kendi
koduyla yeniden denetler ve `qc.json` (bulgular, denetim başına sayılar, tekrar sayıları)
ile `review-sample.md` yazar; veri dosyalarına dokunmaz. Sekiz denetim: açıklamadaki her
sayı kullanıcı mesajındaki kanıt maddelerinde var (`numbers_in_tool_output`); araç çağrıları
şemaya ve kayıttaki `tools` listesine uyuyor (`call_schema_valid`); çağrı durumda izinli ve
sorunun niyetine uygun (`call_allowed_and_on_intent`); etiket sekiz etiketten biri
(`label_in_eight`); sabit satırlar (uyarı ve dönem notu) çıkarıldıktan sonra tavsiye dili
yok (`no_advice_language`); `validate_explanation` kabul ediyor (`validator_accepts`);
donmuş setle çakışma yok (`no_frozen_overlap`); 2025-01-01 ve sonrası tarih ya da tarihsiz
test dönemi cümlesi yok (`no_test_period_data`). Hedef: 0 bulgu; bulgu çıkarsa denetim
gevşetilmez, şablon, üretici ya da öğretmen düzeltilip veri yeniden üretilir.

Tekrar temizliği üretimde (`build`, bölmeden önce) uygulanır: aynı metinli ve aynı hedefli
yakın kopya sorular ile aynı metni farklı hedefle öğreten başka aile soruları atılır
(`question_id` sırasında ilki kalır, bir sorunun bütün turları birlikte gider). Elle okuma
örneklemi 50 kayıttır; okumayı Burak yapar, bulduğu sorunlar şablonlara geri yazılır ve veri
yeniden üretilir. `data/finetune/` türetilmiştir ve git dışıdır.

## Eğitim ve dışa aktarma (RTX 5070)

### Eğitim (`finetune/train.py`)

Eğitim kütüphaneleri (`torch` 2.11.0 CUDA 12.8, `transformers`, `peft`, `bitsandbytes`,
`accelerate`) `train` bağımlılık grubundadır: `uv sync --group train`. torch CUDA 12.8
indeksinden gelir (`[[tool.uv.index]] pytorch-cu128`); RTX 5070 (Blackwell, sm_120) için
CUDA 12.8 ya da sonrası gerekir. Harness bu kütüphaneleri hiç içe aktarmaz
(`tests/test_finetune_train_config.py`); grup kurulu değilse `train` açık bir hatayla durur.

- **Ayar dosyaları:** `configs/qlora/r16-e2.toml` (rank 16, alpha 32, 2 tur, lr 2e-4),
  `configs/qlora/r32-e3.toml` (rank 32, alpha 64, 3 tur, lr 1e-4); ikisinde de temel model
  `Qwen/Qwen3.5-9B`, revizyon `c202236235762e1c871ad0ccb60c8ee5ba337b9a` (masaüstündeki
  Ollama `qwen3.5:9b-q4_K_M`'nin deposu; doğrulama
  `docs/results/2026-11-18-finetune-training.md` 9. bölüm), toplu boyut 1 × gradyan
  biriktirme 16 (Qwen3.5'in 248 bin belirteçlik sözlüğünde logit belleği toplu boyutla
  büyür), `max_seq_len` 3072, `eval_steps` 50, sabır 3, bellek-yalın yol. Bellek denemesi
  `configs/qlora/trial-9b.toml`: r32'nin bellek ayarlarıyla, veri setinin en uzun 80 eğitim
  ve 16 doğrulama kaydında 20 adım. Dizüstü denemeleri `configs/qlora/laptop-trial.toml`
  (Task 8, Qwen3.5 0.8B, PEFT yolu) ve `configs/qlora/laptop-trial-lean.toml` (aynı koşu,
  bellek-yalın yol). `train_limit`/`val_limit` bir örneklem seçer: `sample = "seeded"`
  tohumla rastgele, `sample = "longest"` belirteç sayısına göre en uzun kayıtları.
  `run.json`: `max_trained_tokens` koşunun eğitip doğruladığı en uzun tur,
  `max_train_val_tokens` train + val'in en uzun turu (bellek denemesi bununla
  karşılaştırılır; test bölümü hiç eğitilmez), `max_example_tokens` üç bölümün en uzunu
  (dışa aktarmanın `num_ctx`'i). Bu veride üçü de 1.475 belirteçtir ve en uzun tur train'dedir
  (`sector_laggard_company-0000-05`; val'in en uzunu 1.473, test'inki 1.467). Her ayar
  dosyada yazılıdır; eksik ya da bilinmeyen ayar reddedilir.
- **Bellek-yalın yol** (`lean_memory`, `target_only_logits`, `logits_chunk`; 9B'yi 12 GB'ye
  sığdırmak için): PEFT'in `prepare_model_for_kbit_training`'i 4 bit olmayan her
  parametreyi fp32'ye yükseltir; 9B'de bu, ayrı gömme ve çıkış katmanı (ikisi ≈ 1 milyar
  parametre) için 4 GB yerine 8 GB demektir. `prepare_lean` bunun yerine her parametreyi
  dondurur, yalnız tek boyutlu olanları (norm ağırlıkları, `A_log`, `dt_bias`) fp32'ye
  alır, gömme ve çıkış katmanını bf16 bırakır, gradient checkpointing ve giriş gradyanını
  kendisi açar. `target_only_logits` çıkış katmanını yalnız etiketli (hedef) konumlarda
  uygular (`target_only_loss`, özel `compute_loss`); `logits_chunk` bu konumları 128'lik
  parçalara böler ve her parçanın logitlerini geri yayılımda yeniden hesaplar. Kayıp,
  standart maskeli çapraz entropiyle aynıdır (birim testi: küçük bir Qwen3.5 modelinde aynı
  kayıp ve aynı LoRA gradyanları, `tests/test_finetune_lean.py`). Beklenen en yüksek bellek:
  `uv run --group train python -m bist_harness.finetune.memory --config <ayar>`
  (`finetune/memory.py`; dizüstünde kalibre edildi).
- **Şablon:** her kayıt temel modelin kendi sohbet şablonuyla (`apply_chat_template`,
  `tools=` ile, düşünme kapalı) işlenir. Ollama araç şemasını olduğu gibi geçirmez: Go
  yapılarına çözüp yeniden yazar (alan sırası `required` → `properties`;
  `additionalProperties` gibi yapıda olmayan alanlar düşer). `ollama_tools` aynı dönüşümü
  yapar. Denetim `finetune/template_check.py` ile: eğitim isteminin metni, yerel Ollama'nın
  aynı mesaj ve araçlar için işlediği istemle (`/api/chat`, `"_debug_render_only": true`)
  bayt bayt karşılaştırılır. Dizüstünde (Ollama 0.40.16, `qwen3.5:0.8b` ve
  `bist-trial-0.8b`) denetlenen 40 kayıdın 40'ı bayt bayt aynı; ham şemayla 12'si
  (`docs/results/2026-11-18-finetune-training.md`). Bu, yalnız denetlenen sürüm, model ve
  kayıtlar için geçerlidir: Ollama sürümü ya da temel model değişince denetim yeniden
  koşulur (aşağıda 6. adım). Hedef turun biçimi (araç çağrısı XML'i) bu denetime girmez;
  onu çıkarımda Ollama'nın ayrıştırıcısı okur.
- **Kayıp:** yalnız hedef asistan turunda; istem belirteçleri `-100` ile maskelenir
  (`to_chat_examples`). İstem ve hedef ayrı belirteçlenir (çıkarımdaki gibi). `max_seq_len`'i
  aşan kayıt kesilmez, dışarıda bırakılır ve `run.json`'da sayılır.
- **QLoRA:** 4 bit NF4 temel (çift nicemleme), LoRA yalnız dil modelinin katmanlarında
  (görüntü kulesi dondurulur), gradient checkpointing, `paged_adamw_8bit`, kosinüs
  öğrenme hızı. Doğrulama kaybı her `eval_steps`'te ölçülür; `early_stop_patience` ölçüm
  iyileşmezse eğitim durur ve en iyi adaptör kaydedilir.
- **Çıktılar** (`runs/finetune-<ayar>/`, git dışı): `adapter/` (en iyi adaptör ve
  tokenizer), `loss.csv` (adım, tur, eğitim ve doğrulama kaybı, öğrenme hızı),
  `run.json` (bütün ayarlar, temel model deposu ve commit'i, veri dosyalarının SHA-256'sı,
  örnek sayıları, en uzun turlar, adım sayısı, en iyi adım ve kaybı, süre ve
  `seconds_per_step`, en yüksek VRAM, GPU, kütüphane sürümleri, git commit'i),
  `checkpoints/`. Komut sonunda tek satırlık özet: adım, en iyi kayıp, adım süresi, en yüksek
  ayrılmış/rezerve bellek, eğitilen en uzun tur / train + val'in en uzunu.

### Dışa aktarma (`finetune/export.py`)

1. Adaptör temel modele **parça parça** birleştirilir (`stream_merge`): her safetensors
   parçası bellek eşlemeli açılır, her tensör tek başına okunur, LoRA hedeflerine
   PEFT'in aritmetiğiyle `W + ölçek · (B @ A)` eklenir (çarpım fp32'de, toplam bir kez
   ağırlığın tipine yuvarlanır) ve en çok 2 GiB'lık yeni parçalar yazılır. 9B'yi bütün
   olarak birleştirmek bf16'da ≈ 18 GB RAM ister, masaüstünde 16 GB vardır; parça parça
   birleştirme ≈ 4–5 GB ile yetinir. Sonuç PEFT'in `merge_and_unload`'ıyla aynıdır (birim
   testi bit bit; gerçek 0.8B adaptöründe 473 tensörün 437'si bit bit aynı, kalan 36'sı
   denetim noktasının fp32 tutulan `A_log`/norm ağırlıkları: PEFT yolu bunları bf16'ya
   yuvarlıyordu, yeni yol özgün fp32 değeri korur). Transformers'ın yüklemediği `mtp.*`
   (taslak) tensörleri PEFT yolunda olduğu gibi yazılmaz.
2. llama.cpp'nin `convert_hf_to_gguf.py`'si f16 GGUF yazar. llama.cpp depoya girmez:
   `tools/llama.cpp/` git dışıdır. **Dönüştürücü, kurulu Ollama'nın çalıştırdığı llama.cpp
   commit'inde olmalıdır**: Ollama'nın `lib/ollama/llama-server.exe --version` çıktısındaki
   commit (Ollama 0.40.16: `6c01da6278ab6c69ed67d9124806b50d2b299ba7`). Daha yeni bir
   dönüştürücü (ör. `b12499`) Qwen3.5 tensörlerini birleştirir (`attn_qkv_gate`,
   `ssm_beta_alpha`) ve Ollama modeli yükleyemez
   (`check_tensor_dims: tensor 'blk.0.ssm_beta.weight' not found`).
3. Modelfile: temel Ollama modelinin şablonu olduğu gibi (`TEMPLATE`, ya da Qwen3.5'teki
   gibi yerleşik `RENDERER`/`PARSER`, ve `stop` sözcükleri), `temperature 0`, `seed 42`,
   `num_ctx` = veri setindeki en uzun tur + 1024, 1024'ün katına yuvarlanmış, en az 4096.
   Temel modelin örnekleme ayarları (ör. `presence_penalty`) ve taslak modeli taşınmaz.
4. Nicemleme `llama-quantize` ile (q4_K_M; `--quant none` f16 bırakır). Ollama 0.40 yalnız
   safetensors içe aktarımında nicemler (`ollama create --quantize` GGUF'ta "create-time
   quantization is only supported for safetensors imports" ile durur). Varsayılan
   nicemleyici Ollama'nın kendi `lib/ollama/llama-quantize.exe`'sidir (çalışma zamanıyla
   aynı commit); başka biri `--llama-quantize` ile verilir.
5. `ollama create <ad> -f Modelfile`.
6. **Yükleme denemesi:** `ollama create` ağırlıkları yüklemez; bilinmeyen tensörlü bir GGUF
   sorunsuz oluşturulur ve ilk istekte düşer. `export` bu yüzden en sonda yerel Ollama'dan
   tek belirteç üretir (`/api/generate`, `num_predict` 1, `OLLAMA_HOST` ya da
   `127.0.0.1:11434`); model yüklenmezse açık bir hatayla durur. Ayrıca birleştirmeden önce
   llama.cpp kopyasının commit'ini Ollama'nın çalışma zamanı commit'iyle karşılaştırır
   (`llama-server --version`); uyuşmazsa hiç başlamaz. Kayıt: `export.json` (Ollama sürümü,
   çalışma zamanı ve dönüştürücü commit'i, yükleme denemesi).

### RTX 5070'te çalıştırma (Burak, PowerShell)

Masaüstünde, deponun kökünde, **PowerShell**'de (Windows PowerShell 5.1 yeter; komutlar
satır satır kopyalanır). Uzak makinenin adresi hiçbir dosyaya yazılmaz; harness modele
yalnız `BIST_LLM_BASE_URL` (ortam ya da git dışı `.env`) ile ulaşır. Dizüstünden geçitle
ölçerken `BIST_LLM_API=openai` gerekir: geçit yalnız `/v1/chat/completions`'ı geçirir,
`/api/chat`'i değil (`docs/results/2026-11-18-base-model-selection.md`). Masaüstünde
yerel Ollama'yla gerekmez.

Hedef model `qwen3.5:9b` (Burak'ın kararı, 18 Kasım 2026); sığmazsa yedek `qwen3.5:4b`.
Sıra: kurulum → `trial-9b` bellek denemesi (20 adım) → karar kuralı → iki gece koşusu →
dışa aktarma.

Masaüstündeki Ollama 0.40.4, resmî Windows ZIP'inden `C:\AI-Server\ollama` klasörüne
kurulmuştur, oturum açılışında zamanlanmış görevle başlar ve **PATH'te değildir**
(`%LOCALAPPDATA%\Programs\Ollama`'da da değildir). `export` Ollama'yı (sürüm,
`llama-server` commit'i, `ollama create`, yükleme denemesi) PATH'te arar; bu yüzden 0. adım
klasörü o pencerenin PATH'ine ekler. Her yeni PowerShell penceresinde 0. adım yeniden
yapılır.

**0. Ollama'nın yolu**

```powershell
$OllamaDir = "C:\AI-Server\ollama"
$Ollama = "$OllamaDir\ollama.exe"
$env:Path = "$env:Path;$OllamaDir"
& $Ollama --version
(Get-Command ollama).Source
```

Beklenen: `ollama version is 0.40.4` ve `C:\AI-Server\ollama\ollama.exe`.

**1. Önkoşullar, depo ve kütüphaneler.** `sprint-5-dev` dizüstünden push edilmiş olmalı.
Önce `git` ve `uv` kurulu mu:

```powershell
git --version
uv --version
```

Biri "tanınmıyor" (`is not recognized`) derse resmî kurulumla kur, sonra **yeni bir
PowerShell penceresi** aç ve 0. adımı yeniden yap:

```powershell
winget install --id Git.Git -e
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

(Birincisi Git'i, ikincisi uv'yi kurar: yalnız eksik olanı çalıştır. Python'u ayrıca kurmak gerekmez, `uv` deponun
istediği Python 3.12'yi kendisi indirir.) Depo `C:\AI-Server\bist-harness` klasörüne
alınır (başka bir sürücü seçilecekse 3. adımdaki ≈ 65 GB boş yeri olan bir yer seçilir ve
aşağıdaki `C:\AI-Server\bist-harness` yolları buna göre değiştirilir). **Masaüstünde depo yoksa** (ilk kez):

```powershell
git clone https://github.com/burakyalcin10/bist-harness.git C:\AI-Server\bist-harness
Set-Location C:\AI-Server\bist-harness
```

**Depo zaten varsa** (eski bir kopya):

```powershell
Set-Location C:\AI-Server\bist-harness
git status --short
```

`git status --short` boş olmalı; değişmiş dosya listelenirse (ör. eski bir paket açılışında
üzerine yazılmış `README.md`) önce `git checkout -- README.md` ya da listelenen dosya için
aynısı. Sonra iki durumda da aynı komutlar (deponun kökünde):

```powershell
git fetch origin
git checkout sprint-5-dev
git pull --ff-only
git log --oneline -1
uv sync --group train
uv run --group train python -c "import torch; print(torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))"
```

Beklenen: `git log` dizüstündeki son commit'i gösterir; son satır
`NVIDIA GeForce RTX 5070 (12, 0)`. Bundan sonraki bütün komutlar deponun kökünde
(`C:\AI-Server\bist-harness`) çalışır; yeni bir pencerede önce `Set-Location
C:\AI-Server\bist-harness` ve 0. adım.

**2. Veri paketi.** Veri git dışıdır; paket dizüstünde hazırlanır (Git Bash):

```bash
uv run python -m bist_harness.finetune.train bundle --data data/finetune \
  --config configs/qlora/trial-9b.toml --config configs/qlora/r16-e2.toml \
  --config configs/qlora/r32-e3.toml --out runs/finetune-bundle-20261118-9b.zip
```

Masaüstünde önce klasörler oluşturulur, sonra paket deponun kökündeki `runs\` klasörüne
kopyalanır. Paket deponun köküne **açılmaz**: kökünde kendi `README.md`'si vardır ve
deponun `README.md`'sinin üzerine yazar. Geçici bir klasöre (`runs\bundle-9b\`) açılır ve
yalnız veri `data\finetune\`'a kopyalanır (eğitim veriyi oradan okur; paketteki ayar
dosyaları git'tekilerle aynıdır, kopyalanmaz):

```powershell
New-Item -ItemType Directory -Force runs, data\finetune | Out-Null
```

Şimdi `finetune-bundle-20261118-9b.zip`'i `runs\` klasörüne kopyala, sonra:

```powershell
Expand-Archive -Path runs\finetune-bundle-20261118-9b.zip -DestinationPath runs\bundle-9b -Force
Copy-Item runs\bundle-9b\data\finetune\* data\finetune\ -Force
git status --short
(Get-FileHash data\finetune\train.jsonl -Algorithm SHA256).Hash.ToLower()
(Get-FileHash data\finetune\val.jsonl -Algorithm SHA256).Hash.ToLower()
```

`git status --short` boş kalmalı (`data\finetune\` ve `runs\` git dışıdır). Hash'ler için
beklenen: `26a764d92f5c024b8f1e3056de4fa734281e7afe072ee7cd0038a520dffbe87c` ve
`23dd54999c0d33880d8c51537094845a9a21e2b6b4c54d2ff2cb98d39092aabb` (manifestteki değerler).

**3. 9B ağırlıkları** (bir kez, 19,3 GB; Hugging Face önbelleğine). Disk: önbellek 19,3 GB,
dışa aktarmada birleştirilmiş model ≈ 19 GB, f16 GGUF ≈ 18 GB, q4_K_M ≈ 5,6 GB: en az
≈ 65 GB boş yer.

```powershell
uv run --group train python -c "from huggingface_hub import snapshot_download; print(snapshot_download('Qwen/Qwen3.5-9B', revision='c202236235762e1c871ad0ccb60c8ee5ba337b9a'))"
uv run --group train python -m bist_harness.finetune.memory --config configs\qlora\trial-9b.toml --rank 16 --rank 32
```

İkinci komut beklenen en yüksek ayrılmış belleği yazar (ağırlık indirmez, Hub
üstverisinden): r16 için ≈ 8,99 GB, r32 için ≈ 9,29 GB (1.475 belirteçlik en uzun tur,
622 belirteç hedef). Dizüstü ölçümlerinde tahmin gerçeğin %2–4 altında kaldı; r32 için
≈ 9,6 GB beklenir.

**4. Bellek denemesi: `trial-9b`** (20 adım, r32'nin bellek ayarları, train ve val'in en
uzun kayıtları). Eğitim sırasında Ollama 5070'te model tutmamalı ve geçitten istek
gelmemelidir (12 GB'ın tamamı gerekir):

```powershell
& $Ollama ps
& $Ollama stop qwen3.5:9b-q4_K_M
```

(`ps` boşsa `stop` gerekmez; listede başka model varsa onun adıyla `stop`.) İkinci bir
PowerShell penceresinde GPU belleğini ve paylaşılan belleğe taşmayı izle (Ctrl+C durdurur;
Windows aşan belleği sessizce sistem RAM'ine taşır, koşu düşmez ama çok yavaşlar):

```powershell
$maxShared = 0
while ($true) {
  $pids = (Get-Process python -ErrorAction SilentlyContinue).Id
  $rows = Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory | Where-Object { $pids -contains [int]($_.Name -replace '^pid_(\d+)_.*', '$1') }
  $dedicated = [math]::Round((($rows | Measure-Object DedicatedUsage -Sum).Sum) / 1MB)
  $shared = [math]::Round((($rows | Measure-Object SharedUsage -Sum).Sum) / 1MB)
  if ($shared -gt $maxShared) { $maxShared = $shared }
  "{0:HH:mm:ss}  GPU {1} MB, paylasilan {2} MB (en cok {3} MB)" -f (Get-Date), $dedicated, $shared, $maxShared
  Start-Sleep -Seconds 10
}
```

Birinci pencerede deneme (çıktı `runs\finetune-trial-9b.log`'a da yazılır):

```powershell
uv run --group train python -m bist_harness.finetune.train run --config configs\qlora\trial-9b.toml --data data\finetune --out runs\finetune-trial-9b 2>&1 | Tee-Object -FilePath runs\finetune-trial-9b.log
```

Sonunda tek satırlık özet yazılır, ör. `[train] 20 steps, ... (<s> s/step), peak VRAM
allocated <a> GB / reserved <r> GB; longest trained turn 1475 of 1475 tokens (train + val)`.
Aynı değerler `runs\finetune-trial-9b\run.json`'dadır:

```powershell
Get-Content runs\finetune-trial-9b\run.json | Select-String '"max_trained_tokens"|"max_train_val_tokens"|"allocated"|"reserved"|"seconds_per_step"|"best_eval_loss"'
```

**Deneme `run.json` yazmadan düşerse** (hata ile biter, ör. `CUDA out of memory`, ya da
pencere kapanır): 4B'ye geçme. Günlüğün sonunu ve GPU durumunu topla, dur ve haber ver:

```powershell
Get-Content runs\finetune-trial-9b.log -Tail 60
nvidia-smi
```

(İkisinin çıktısını ve izleme penceresinin son satırlarını olduğu gibi gönder.)

**5. Karar kuralı.** Deneme **geçer** (9B ile devam), dördü birden tutarsa:

1. `max_trained_tokens` = `max_train_val_tokens` (= 1475: deneme en uzun turu gördü);
2. `peak_vram_gb.allocated` ≤ 10,5 (CUDA bağlamı ve ekran için ≈ 1,5 GB pay);
3. `peak_vram_gb.reserved` < 11,5;
4. izleme penceresindeki "en cok" paylaşılan bellek < 1000 MB (taşma yok; normalde
   birkaç yüz MB'tır; dizüstünde taşmasız 0.8B koşusu 80 MB gösterdi).

- **1. tutmazsa** (deneme en uzun turu görmedi): bu bellekle ilgili değildir, veri ya da
  paket uyuşmazlığıdır; 4B bunu düzeltmez. **Dur ve haber ver** (`run.json`'u gönder).
- **1. tutar, 2–4'ten biri tutmazsa:** 9B bu kartta güvenli değildir, **4B'ye geç**
  (aşağıda).
- **Dördü tutarsa:** `seconds_per_step` 6. adımdaki süre kuralına girer.

**4B'ye geçiş** (yalnız 2–4. ölçütlerden biri tutmazsa; Burak'ın kararı). `Qwen/Qwen3.5-4B` masaüstündeki
`qwen3.5:4b`'nin deposudur (aynı mimari ailesi, aynı belirteçleyici ve sohbet işleyişi;
`docs/results/2026-11-18-finetune-training.md`, 9. bölüm). Üç ayar dosyasında yalnız iki
satır değişir; `target_modules` ve öteki ayarlar aynı kalır:

```powershell
foreach ($name in "r16-e2", "r32-e3", "trial-9b") {
  $path = (Resolve-Path "configs\qlora\$name.toml").Path
  $text = [IO.File]::ReadAllText($path)
  $text = $text -replace '(?m)^base_model = .*$', 'base_model = "Qwen/Qwen3.5-4B"'
  $text = $text -replace '(?m)^revision = .*$', 'revision = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"'
  [IO.File]::WriteAllText($path, $text)
}
Select-String -Path configs\qlora\r16-e2.toml, configs\qlora\r32-e3.toml, configs\qlora\trial-9b.toml -Pattern '^base_model|^revision'
uv run --group train python -m bist_harness.finetune.memory --config configs\qlora\trial-9b.toml --rank 16 --rank 32
uv run --group train python -m bist_harness.finetune.train run --config configs\qlora\trial-9b.toml --data data\finetune --out runs\finetune-trial-4b
```

(`[IO.File]::WriteAllText` UTF-8'i BOM'suz yazar; `Set-Content -Encoding utf8` PowerShell
5.1'de BOM ekler ve ayar dosyası okunmaz. Dosya adı `trial-9b` kalır, içerik 4B'dir.)
4B tahmini ≈ 4,35 / 4,58 GB (r16 / r32); deneme aynı kuralla okunur. Sonra 6. adım aynı
komutlarla çalışır; 7. adımda `Qwen/Qwen3.5-9B` yerine `Qwen/Qwen3.5-4B`,
`c202236235762e1c871ad0ccb60c8ee5ba337b9a` yerine
`851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` ve `qwen3.5:9b-q4_K_M` yerine `qwen3.5:4b`
yazılır. Masaüstünde commit edilmez (`run.json` ayarları zaten kaydeder); sonraki
`git pull`'dan önce `git checkout -- configs/qlora` ile geri alınır. Kalıcı geçişi dizüstünde
ayrı bir commit yapar.

**6. İki gece koşusu.** Arka arkaya; ilki başarısız olursa ikincisi başlamaz. Çıktı
`runs\` altındaki günlüklere de yazılır:

```powershell
uv run --group train python -m bist_harness.finetune.train run --config configs\qlora\r16-e2.toml --data data\finetune --out runs\finetune-r16-e2 2>&1 | Tee-Object -FilePath runs\finetune-r16-e2.log
if ($LASTEXITCODE -eq 0) { uv run --group train python -m bist_harness.finetune.train run --config configs\qlora\r32-e3.toml --data data\finetune --out runs\finetune-r32-e3 2>&1 | Tee-Object -FilePath runs\finetune-r32-e3.log }
```

Beklenen süre (denemenin `seconds_per_step`'inden; adım = 16 örnek). Deneme veri setinin
en uzun turlarında koştuğu için (ortalama ≈ 1.175 belirteç) gerçek adımlar daha kısadır
(train ortalaması ≈ 673 belirteç): gerçek adım ≈ 0,57 × denemenin `seconds_per_step`'i.
`r16-e2` 296 adım (2 tur × 148), her 50 adımda 618 kayıtlık doğrulama (her biri ≈ 13
adımlık süre); `r32-e3` 444 adım. Eğitim döngüsünün kaba süresi, `X` = denemenin
`seconds_per_step`'i:

| | eğitim döngüsü (saat) | X = 30 sn | X = 50 sn | X = 90 sn | X = 130 sn |
| --- | --- | --- | --- | --- | --- |
| `r16-e2` | ≈ 0,057 × X | ≈ 1,7 | ≈ 2,9 | ≈ 5,1 | ≈ 7,4 |
| `r32-e3` | ≈ 0,087 × X | ≈ 2,6 | ≈ 4,4 | ≈ 7,8 | ≈ 11,3 |
| ikisi | ≈ 0,144 × X | ≈ 4,3 | ≈ 7,2 | ≈ 13 | ≈ 18,7 |

Buna her koşunun açılış payı eklenir: 9B'nin yüklenip 4 bit'e çevrilmesi ve 3.618 kaydın
belirteçlenmesi. Denemede bu pay `run.json`'daki `wall_time_s` − `train_runtime_s`'tir;
≈ 15 dk (0,25 sa) alınır, ölçülen daha büyükse o kullanılır. Tahmin kabadır (± %30), bu
yüzden plan × 1,3 ile yapılır. Koşular akşam ≈ 20:00'de başlarsa sabah 06:00'ya, yani
**10 saate** bitmelidir:

- **X ≤ 50 sn:** ikisi bu gece, arka arkaya (yukarıdaki iki satır): 1,3 × 0,144 × 50 +
  2 × 0,25 ≈ 9,9 sa.
- **50 < X ≤ 130 sn:** bu gece **yalnız `r16-e2`** (yalnız ilk satır; 1,3 × 0,057 × 130 +
  0,25 ≈ 9,9 sa); `r32-e3` ertesi gece ya da gündüz, aynı komutla.
- **X > 130 sn:** `r16-e2` bile 10 saate sığmaz; başlatma, `run.json`'u gönder ve haber ver.

Başlama saati 20:00'den geçse, 10 saat yerine sabaha kalan saat kullanılır (eşikler onunla
orantılı küçülür). Erken durma koşuları kısaltabilir, uzatmaz. Hızlı Gated DeltaNet
çekirdekleri (`flash-linear-attention`) Triton ister; Triton'un resmî Windows paketi yoktur
(dizüstünde de kurulu değil), bu yüzden PyTorch başvuru uygulaması kullanılır.

**7. Dışa aktarma** (koşular bittikten sonra; Ollama sürümü, llama.cpp ve şablon denetimi).
Masaüstündeki Ollama 0.40.4'tür, dizüstününki 0.40.16 (llama.cpp `6c01da627`). Dizüstünün
commit'i masaüstünde **geçersizdir**: dönüştürücü 0.40.4'ün kendi commit'ine sabitlenir ve
şablon denetimi 0.40.4'te yeniden koşulur. ZIP kurulumu kendini güncellemez.

```powershell
(Get-Command ollama).Source
Get-ChildItem "$OllamaDir\lib\ollama" -Filter "llama-*.exe"
& "$OllamaDir\lib\ollama\llama-server.exe" --version
```

İlki `C:\AI-Server\ollama\ollama.exe`'yi göstermeli (0. adım bu pencerede yapılmış olmalı);
ikincisi `llama-server.exe` ve `llama-quantize.exe`'yi listelemeli; üçüncüsü
`commit <kısa>` yazar. `llama-server.exe` ya da `llama-quantize.exe` yoksa dur ve haber ver:
`export` commit'i okuyamaz ve başlamaz (bu dosyalar yalnız 0.40.16'da doğrulandı). Kısa
hash'ten tam commit'e (GitHub yalnız tam adla getirir; `<kısa>` yerine yukarıdaki değer):

```powershell
git clone -c core.longpaths=true --filter=blob:none https://github.com/ggml-org/llama.cpp tools/llama.cpp
git -C tools/llama.cpp fetch origin
$full = git -C tools/llama.cpp rev-parse "<kısa>^{commit}"
git -C tools/llama.cpp checkout $full
git -C tools/llama.cpp rev-parse HEAD
```

(`clone` yalnız ilk kez; sonraki dışa aktarmalarda `fetch` yeter. Son satır `<kısa>` ile
başlamalı.) Şablon denetimi 9B ve bu Ollama ile (çıkış kodu 0 = hepsi bayt bayt aynı;
`BIST_LLM_BASE_URL` boş ya da yerel Ollama olmalı; 0.40.4 `_debug_render_only`'yi
tanımıyorsa denetim bunu açıkça söyler ve durur: sonucu haber ver, dışa aktarmaya geçme):

```powershell
uv run --group train python -m bist_harness.finetune.template_check --data data\finetune --base-model Qwen/Qwen3.5-9B --revision c202236235762e1c871ad0ccb60c8ee5ba337b9a --ollama-model qwen3.5:9b-q4_K_M --out runs\template-check-9b.json
```

Dışa aktarma (parça parça birleştirme, f16 GGUF, `llama-quantize` ile q4_K_M,
`ollama create`, yükleme denemesi; commit uyuşmazsa başlamaz, model yüklenmezse sonda hata
verir; her biri ≈ 43 GB disk ister: birleştirilmiş model ≈ 19 GB, GGUF'a çevrilince
silinir (`--keep-merged` verilmezse); f16 GGUF ≈ 18 GB ve q4_K_M ≈ 5,6 GB kalır):

```powershell
uv run --group train python -m bist_harness.finetune.export --adapter runs\finetune-r16-e2\adapter --name bist-r16-e2 --template-from qwen3.5:9b-q4_K_M --llama-quantize "$OllamaDir\lib\ollama\llama-quantize.exe"
uv run --group train python -m bist_harness.finetune.export --adapter runs\finetune-r32-e3\adapter --name bist-r32-e3 --template-from qwen3.5:9b-q4_K_M --llama-quantize "$OllamaDir\lib\ollama\llama-quantize.exe"
& $Ollama list
```

`bist-r16-e2` ve `bist-r32-e3` listede görünmeli; her dışa aktarmanın `export.json`'unda
`"load_check": "passed"`.

**8. Dizüstüne geri getir:** her koşudan `adapter\`, `loss.csv`, `run.json` (ve deneme için
`runs\finetune-trial-9b\run.json`); `checkpoints\` gerekmez. Dizüstünde
`runs/finetune-r16-e2/` ve `runs/finetune-r32-e3/` altına aynı yollarla konur.

Dizüstünde aynı modeli kurmak için 7. adımdaki `export` komutu getirilen adaptörle
dizüstünde de çalışır (temel model Hugging Face'ten iner, f16 GGUF yerelde üretilir).

Seçim: doğrulama kaybı (`run.json` → `best_eval_loss`) ve geliştirme sorularında açıklama
kabul oranı (`run_eval --questions-file data/finetune/dev_questions.jsonl --experiments E
--model bist-<ayar>`); gerekçe `docs/results/<gün>-finetune-training.md`'de.

Not: Qwen3.5'in doğrusal dikkat katmanları için `flash-linear-attention` ve
`causal-conv1d` kurulu değilse transformers PyTorch başvuru uygulamasına düşer (doğru ama
yavaş; dizüstünde 0.8B'de adım başına 14–19 sn). Bu çekirdekler Triton ister; Triton'un resmî
Windows paketi olmadığı için masaüstünde de denenmedi, `train` grubuna eklenmedi.
