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
  `configs/qlora/r32-e3.toml` (rank 32, alpha 64, 3 tur, lr 1e-4); ikisinde de toplu boyut
  1 × gradyan biriktirme 16 (Qwen3.5'in 248 bin belirteçlik sözlüğünde logit belleği toplu
  boyutla büyür), `max_seq_len` 3072, `eval_steps` 50, sabır 3; ve dizüstü denemesi
  `configs/qlora/laptop-trial.toml` (Qwen3.5 0.8B, 20 adım, 80 eğitim + 16 doğrulama
  kaydı). Her ayar dosyada yazılıdır; eksik ya da bilinmeyen ayar reddedilir. 5070
  ayarlarının `base_model`/`revision` değeri Task 7'ye kadar yer tutucudur
  (`TASK-7-CHOOSES-THE-BASE-MODEL`) ve eğitim yer tutucuyu reddeder.
- **Şablon:** her kayıt temel modelin kendi sohbet şablonuyla (`apply_chat_template`,
  `tools=` ile, düşünme kapalı) işlenir. Ollama araç şemasını olduğu gibi geçirmez: Go
  yapılarına çözüp yeniden yazar (alan sırası `required` → `properties`;
  `additionalProperties` gibi yapıda olmayan alanlar düşer). `ollama_tools` aynı dönüşümü
  yapar; böylece eğitim metni Ollama'nın çıkarımda modele verdiği metnin aynısıdır.
  Denetim (dizüstü, `qwen3.5:0.8b`): her tur türü ve araç birleşimi için 10 kayıtta
  belirteç sayısı ve UTF-8 bayt uzunluğu Ollama'nınkiyle aynı
  (`docs/results/2026-11-18-finetune-training.md`).
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
  örnek sayıları, veri setindeki en uzun tur, adım sayısı, en iyi adım ve kaybı, süre,
  en yüksek VRAM, GPU, kütüphane sürümleri, git commit'i), `checkpoints/`.

### Dışa aktarma (`finetune/export.py`)

1. Adaptör temel modelle birleştirilir (bf16, CPU'da).
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
5. `ollama create <ad> -f Modelfile`. Kayıt: `export.json`.

### RTX 5070'te çalıştırma (Burak)

Masaüstünde, deponun kökünde (Git Bash). Uzak makinenin adresi hiçbir dosyaya yazılmaz;
harness modele yalnız `BIST_LLM_BASE_URL` (ortam ya da git dışı `.env`) ile ulaşır.

```bash
# 1. Depo ve kütüphaneler
git clone <depo> bist-harness   # ilk kez; sonra: git pull
cd bist-harness
git checkout sprint-5-dev && git pull
uv sync --group train
uv run --group train python -c "import torch; print(torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))"
#   beklenen: NVIDIA GeForce RTX 5070 (12, 0)

# 2. Paketi dizüstünde hazırla ve masaüstüne kopyala (veri git dışıdır)
#    dizüstünde:
uv run python -m bist_harness.finetune.train bundle --data data/finetune \
  --config configs/qlora/r16-e2.toml --config configs/qlora/r32-e3.toml \
  --out runs/finetune-bundle-<gün>.zip
#    masaüstünde, deponun kökünde:
unzip runs/finetune-bundle-<gün>.zip -d .   # data/finetune/ ve configs/qlora/ gelir

# 3. Task 7'nin seçtiği modeli iki ayar dosyasına yaz (base_model, revision; Qwen3.5
#    dışı bir aile seçildiyse target_modules da)

# 4. Önce 20 adımlık deneme (EC-006): boru hattı masaüstünde de uçtan uca çalışıyor mu
uv run --group train python -m bist_harness.finetune.train run \
  --config configs/qlora/laptop-trial.toml --data data/finetune --out runs/finetune-laptop-trial

# 5. İki ayar
uv run --group train python -m bist_harness.finetune.train run \
  --config configs/qlora/r16-e2.toml --data data/finetune --out runs/finetune-r16-e2
uv run --group train python -m bist_harness.finetune.train run \
  --config configs/qlora/r32-e3.toml --data data/finetune --out runs/finetune-r32-e3

# 6. llama.cpp (bir kez), Ollama'nın çalıştırdığı commit'te; <taban> Task 7'nin Ollama
#    etiketi (ör. qwen3.5:4b)
"$LOCALAPPDATA/Programs/Ollama/lib/ollama/llama-server.exe" --version   # commit <c>
git init tools/llama.cpp && cd tools/llama.cpp
git remote add origin https://github.com/ggml-org/llama.cpp
git fetch --depth 1 origin <c'nin tam hali>   # 0.40.16: 6c01da6278ab6c69ed67d9124806b50d2b299ba7
git checkout FETCH_HEAD && cd ../..
uv run --group train python -m bist_harness.finetune.export \
  --adapter runs/finetune-r16-e2/adapter --name bist-r16-e2 --template-from <taban>
uv run --group train python -m bist_harness.finetune.export \
  --adapter runs/finetune-r32-e3/adapter --name bist-r32-e3 --template-from <taban>
ollama list   # bist-r16-e2 ve bist-r32-e3 görünmeli

# 7. Dizüstüne geri getir: her koşudan adapter/, loss.csv, run.json (checkpoints/ gerekmez)
#    runs/finetune-r16-e2/ ve runs/finetune-r32-e3/ altına aynı yollarla koy
```

Dizüstünde aynı modeli kurmak için 6. adımdaki `export` komutu getirilen adaptörle
dizüstünde de çalışır (temel model Hugging Face'ten iner, f16 GGUF yerelde üretilir).

Seçim: doğrulama kaybı (`run.json` → `best_eval_loss`) ve geliştirme sorularında açıklama
kabul oranı (`run_eval --questions-file data/finetune/dev_questions.jsonl --experiments E
--model bist-<ayar>`); gerekçe `docs/results/<gün>-finetune-training.md`'de.

Not: Qwen3.5'in doğrusal dikkat katmanları için `flash-linear-attention` ve
`causal-conv1d` kurulu değilse transformers PyTorch başvuru uygulamasına düşer (doğru ama
yavaş; dizüstünde adım başına yaklaşık 20 sn). Masaüstünde süre uzun gelirse bu
çekirdekler ayrıca kurulabilir; `train` grubuna eklenmedi.
