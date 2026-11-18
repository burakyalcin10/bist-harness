# İnce ayar eğitimi: dizüstü denemesi (Task 8, 18 Kasım 2026)

CSE-481 Mühendislik Ekonomisi — yalnız eğitim amaçlıdır, yatırım tavsiyesi değildir.

Bu belge dizüstündeki 20 adımlık QLoRA denemesini (EC-006) kaydeder: eğitim → dışa aktarma
→ Ollama → harness boru hattının uçtan uca çalıştığını gösterir. Amaç kalite değildir.
RTX 5070'teki iki ayarın (`r16-e2`, `r32-e3`) koşuları ve model seçimi Task 7'den sonra
bu belgeye eklenecek.

## Ortam

| | |
| --- | --- |
| GPU | NVIDIA GeForce RTX 3050 Ti Laptop, 4 GB, sürücü 621.24 |
| RAM | 16 GB |
| Python | 3.12.0 (uv 0.10.2) |
| `train` grubu | torch 2.11.0+cu128 (CUDA 12.8), transformers 5.23.0, peft 0.21.3, bitsandbytes 0.50.2, accelerate 1.16.0 (`uv.lock`) |
| Ollama | 0.40.16 (çalışma zamanı llama.cpp commit `6c01da627`) |
| llama.cpp (dönüştürücü) | commit `6c01da6278ab6c69ed67d9124806b50d2b299ba7`, `tools/llama.cpp/` (git dışı) |
| Temel model | `Qwen/Qwen3.5-0.8B`, revizyon `2fc06364715b967f1860aea9cf38778875588b17` |
| Veri | `data/finetune/` (`manifest.json` SHA-256 `92c11980…`, `snapshot_id` `20261117-0722`) |

**Temel modelin Hugging Face deposu.** Ollama'daki `qwen3.5:0.8b` GGUF'unun metaverisi
(`ollama show -v`) `general.license.link = https://huggingface.co/Qwen/Qwen3.5-0.8B/blob/main/LICENSE`,
`general.base_model.0.repo_url = https://huggingface.co/Qwen/Qwen3.5-0.8B-Base` ve
`general.parameter_count = 752.393.024` (dil modeli) taşır; Ollama modeli araç ve düşünme
yetenekli sohbet modelidir. Bu yüzden eşleşen depo `Qwen/Qwen3.5-0.8B`'dir (sohbet modeli,
tabanı `-Base`); `-Base` depo sohbet şablonu eğitilmemiş ön eğitim modelidir. Ollama modeli
Q8_0 nicemli ve bir görüntü projektörü ile bir taslak (MTP) bloğu taşır; HF modeli
`Qwen3_5ForConditionalGeneration` (dil modeli 24 katman: 6 tam dikkat + 18 Gated DeltaNet,
görüntü kulesi).

## 1. `uv sync --group train`

`uv sync --group train` 2 dk 43 sn'de kurdu; torch CUDA 12.8 indeksinden geldi.
`torch.cuda.is_available()` → `True`, aygıt `NVIDIA GeForce RTX 3050 Ti Laptop GPU`,
yetenek `(8, 6)`, bf16 destekli; bitsandbytes 4 bit nicemleme GPU'da çalıştı.

## 2. Sohbet şablonu denetimi (Review Focus 5)

Ollama 0.40.16 `qwen3.5:0.8b` için Go şablonu değil, yerleşik bir işleyici kullanır:
`ollama show --modelfile` → `TEMPLATE {{ .Prompt }}`, `RENDERER qwen3.5`,
`PARSER qwen3.5`. İşleyici (Ollama `model/renderers/qwen35.go`) HF şablonunun
(`chat_template.jinja`) metnini üretir; tek fark araç şemalarındadır: Ollama şemayı
`api.Tool` Go yapılarına çözüp yeniden yazar. Bu yüzden:

- alan sırası yapı sırasıdır (`type`, `required`, `properties`);
- yapıda olmayan alanlar düşer (harness şemalarında `additionalProperties: false`);
- `items`/`enum` gibi `any` değerlerde anahtarlar alfabetik sıralanır.

`train.ollama_tools` aynı dönüşümü yapar; eğitim metni şemayı modelin çıkarımda gördüğü
gibi gösterir. Denetim: her tur türü ve her araç birleşimi için bir kayıt (10 kayıt) HF
şablonuyla (`apply_chat_template`, `tools=`, düşünme kapalı) işlendi ve aynı mesajlar
Ollama'ya gönderildi (`/api/chat`, `think: false`, `num_predict: 1`):

| Kayıt (tur, araçlar) | Ham şema ile belirteç | `ollama_tools` ile | Ollama `prompt_eval_count` | Bayt (biz / Ollama) |
| --- | --- | --- | --- | --- |
| intent | 222 | 222 | 222 | 888 / 888 |
| explanation | 583 | 583 | 583 | 1854 / 1854 |
| tool_call `rank_sector_relative_strength` | 540 | 534 | 534 | 2082 / 2082 |
| tool_call `run_backtest` | 605 | 600 | 600 | 2297 / 2297 |
| tool_call `get_stock_history`, `get_index_history` | 650 | 640 | 640 | 2423 / 2423 |
| tool_call `calculate_indicators`, `find_support_resistance` | 769 | 757 | 757 | 2846 / 2846 |
| tool_call `detect_reversal_events`, `test_weekday_pattern` | 936 | 925 | 925 | 3431 / 3431 |
| tool_call `get_fundamental_metrics`, `calculate_fundamental_change` | 655 | 644 | 644 | 2514 / 2514 |
| tool_call `get_macro_context` | 448 | 443 | 443 | 1781 / 1781 |
| tool_call `get_news_events`, `get_speech_features` | 653 | 643 | 643 | 2555 / 2555 |

Ollama'nın sunucu günlüğündeki `prompt_len` istem metninin UTF-8 bayt uzunluğudur; 10
kayıtta da hem belirteç sayısı hem bayt uzunluğu eşit. Ham şemayla (dönüşümsüz) araç
turlarında 5–12 belirteç fark vardı. Hedef tur HF şablonuyla şöyle işlenir (araç turu):

```
<|im_start|>assistant
<think>

</think>

<tool_call>
<function=rank_sector_relative_strength>
<parameter=sector>
Telecom
</parameter>
...
</function>
</tool_call><|im_end|>
```

İstem `<think>\n\n</think>\n\n` ile biter (Ollama `think: false` ile aynı); hedef
`<tool_call>`'dan `<|im_end|>\n`'e kadardır ve yalnız o kısım kayba girer. İstem ve hedef
ayrı belirteçlenir; 302 kayıtlık örneklemde ayrı ve birlikte belirteçleme aynı diziyi verdi.

**Belirteç uzunlukları** (3.618 kayıt, Qwen3.5 belirteçleyici): en uzun 1.475 belirteç
(açıklama turu); `intent` medyan 254 / en çok 308, `tool_call` 762 / 1.042, `explanation`
845 / 1.475. Dışa aktarılan modelin `num_ctx`'i 1.475 + 1.024 → 4.096.

## 3. 20 adımlık QLoRA denemesi

```
uv run --group train python -m bist_harness.finetune.train run \
  --config configs/qlora/laptop-trial.toml --data data/finetune --out runs/finetune-laptop-trial
```

Ayarlar (`configs/qlora/laptop-trial.toml`): rank 8, alpha 16, dropout 0,05, hedef
katmanlar dil modelinin `q/k/v/o_proj`, `in_proj_qkv`, `in_proj_z`, `out_proj`,
`gate/up/down_proj` (görüntü kulesi dondurulmuş), lr 2e-4 kosinüs, ısınma %3, toplu boyut
1 × biriktirme 4, 20 adım, `max_seq_len` 2048, 4 bit NF4 + çift nicemleme, bf16,
`paged_adamw_8bit`, gradient checkpointing, tohum 42. Tohumlu örneklem: 80 eğitim kaydı
(17 intent, 47 tool_call, 16 explanation), 16 doğrulama kaydı (8 intent, 8 tool_call).
Eğitilen parametre 5.111.808 / 858.097.728 (%0,6).

| | |
| --- | --- |
| Süre | 396,8 sn (eğitim 378 sn, adım başına ≈ 19 sn) |
| En yüksek VRAM (PyTorch) | ayrılan 5,36 GB, rezerve 9,92 GB |
| Eğitim kaybı | adım 1: 0,736 → adım 20: 0,016 (20 adım ortalaması 0,110) |
| Doğrulama kaybı | adım 10: 0,0849 → adım 20: 0,0433 (en iyi: adım 20) |
| Erken durma | yok (20/20 adım) |

Çıktılar: `runs/finetune-laptop-trial/adapter/` (20 MB), `loss.csv`, `run.json` (git dışı).

Notlar:

- **VRAM 4 GB'ı aşıyor.** PyTorch'un ayırdığı en yüksek bellek 5,36 GB; Windows sürücüsü
  aşan kısmı paylaşılan sistem belleğine taşıdı (WDDM). Deneme bu yüzden yavaş ama
  çalıştı. Belleğin büyük kısmı Qwen3.5'in 248.320 belirteçlik sözlüğündeki logitlerdir
  (1.475 belirteçlik bir örnekte fp32 ≈ 1,4 GB) ve `prepare_model_for_kbit_training`'in
  fp32'ye yükselttiği gömme katmanıdır. 5070 ayarları bu yüzden toplu boyut 1 × biriktirme
  16 kullanır.
- **Yavaş çekirdekler.** `flash-linear-attention` ve `causal-conv1d` kurulu değil;
  transformers Gated DeltaNet için PyTorch başvuru uygulamasına düştü (doğru, yavaş).
- **Kayıp başta zaten düşük.** Harness'in istemleri doğru çağrıyı neredeyse dikte ettiği
  için temel model hedef belirteçlerin çoğunu zaten bekliyor; 20 adımlık düşüş kaliteye
  dair bir şey söylemez.
- `run.json`'daki `base_model.resolved_commit` bu koşuda `null` kaldı (transformers 5'te
  `config._commit_hash` yok); kod koşudan sonra önbellek klasöründen okuyacak biçimde
  düzeltildi. Revizyon tam commit olarak ayarlarda yazılı olduğundan bilgi kaybı yok.

## 4. Dışa aktarma ve Ollama

```
uv run --group train python -m bist_harness.finetune.export \
  --adapter runs/finetune-laptop-trial/adapter --name bist-trial-0.8b \
  --template-from qwen3.5:0.8b --llama-cpp tools/llama.cpp --out runs/finetune-laptop-trial/export-q4
uv run --group train python -m bist_harness.finetune.export \
  --adapter runs/finetune-laptop-trial/adapter --name bist-trial-0.8b-f16 --quant none \
  --template-from qwen3.5:0.8b --llama-cpp tools/llama.cpp --out runs/finetune-laptop-trial/export-f16
```

Birleştirme (bf16, CPU) + dönüştürme + nicemleme + `ollama create`: q4_K_M 56 sn, f16 50 sn.
f16 GGUF 1,52 GB, q4_K_M GGUF 0,53 GB; `ollama list`: `bist-trial-0.8b` (529 MB),
`bist-trial-0.8b-f16` (1,5 GB). İki dışa aktarmanın f16 GGUF'u bayt bayt aynıdır.
Üretilen Modelfile:

```
FROM ./model-q4_K_M.gguf
TEMPLATE {{ .Prompt }}
RENDERER qwen3.5
PARSER qwen3.5
PARAMETER temperature 0
PARAMETER seed 42
PARAMETER num_ctx 4096
```

Yolda çıkan üç sorun ve çözümü:

1. **`ollama create --quantize` GGUF'ta çalışmıyor.** Ollama 0.40.16: "create-time
   quantization is only supported for safetensors imports; quantize GGUF models before
   importing". Nicemleme llama.cpp'nin `llama-quantize`'ına geçti; varsayılan olarak
   Ollama'nın kendi `lib/ollama/llama-quantize.exe`'si kullanılır.
2. **Yeni dönüştürücünün GGUF'u Ollama'da açılmıyor.** llama.cpp `b12499`
   (18 Kasım) Qwen3.5 tensörlerini birleştiriyor (`attn_qkv_gate`, `ssm_beta_alpha`);
   Ollama'nın çalışma zamanı (llama.cpp `6c01da627`, 6 Kasım) ayrı tensör bekliyor:
   `check_tensor_dims: tensor 'blk.0.ssm_beta.weight' not found`, harness'te
   `MODEL_UNAVAILABLE`. Dönüştürücü Ollama'nın çalıştırdığı commit'e sabitlendi;
   tensör adları Ollama'nın kendi `qwen3.5:0.8b` GGUF'uyla aynı oldu ve model yüklendi.
3. Bu makinede Python'un `PATH`'inde Ollama klasörü yok (Git Bash'inkinde var);
   `export` Ollama'yı Windows kurulum klasöründe de arar.

Dışa aktarılan modelde temel modelin `presence_penalty 1.5`, `top_k`, `top_p` ayarları
ve taslak (MTP) bloğu yoktur (Modelfile yalnız şablonu taşır). Harness her istekte
`temperature 0` ve `seed 42` gönderir; `presence_penalty` ise temel modelde açık kalır.
Bu, temel model ile ince ayarlı model karşılaştırmasında bir farktır; f16 ile q4_K_M
karşılaştırmasında yoktur.

## 5. Uçtan uca bir harness sorusu

```
uv run python -m bist_harness.eval.run_eval --questions-file data/finetune/dev_questions.jsonl \
  --ids price_summary-0006 --experiments E --repeats 1 --model bist-trial-0.8b \
  --out runs/finetune-laptop-trial/eval-one
```

"TURSG hissesinin fiyat özetini ver." → niyet `PRICE_SUMMARY`/`TURSG`, iki araç durumu
(`LOAD_MARKET_DATA`, `CALCULATE_TECHNICALS`) ilk denemede reddedilmeden çağrıldı, risk
kapısı `PASS_WITH_WARNINGS`, açıklama ilk denemede doğrulandı, sonuç `INVESTIGATE`
(beklenen sınıf `ANALYSIS`), 4 sayının 4'ü kanıtta, süre 8,2 sn. Eğitim → dışa aktarma →
Ollama → harness zinciri uçtan uca çalıştı.

## 6. Nicemleme öncesi ve sonrası (Review Focus 5)

12 geliştirme sorusu (`dev_questions.jsonl`, tohum 42 ile senaryo dengeli seçildi: dört ana
senaryodan ikişer (biri Türkçe, biri İngilizce), `PRICE_SUMMARY`, `MACRO_CONTEXT`,
`BACKTEST` ve bir tuzaktan birer), deney E, 1 tekrar:

```
uv run python -m bist_harness.eval.run_eval --questions-file data/finetune/dev_questions.jsonl \
  --ids sector_laggard_dated-0010,sector_laggard_dated-0007,calendar_pattern_company-0008,calendar_pattern_undated-0027,technical_reversal_dated-0006,technical_reversal_dated-0027,fundamental_reaction_dated-0016,fundamental_reaction_lowercase-0011,price_summary-0006,macro_context_hold-0021,backtest-0000,advice_request-0009 \
  --experiments E --repeats 1 --model <model> --out runs/finetune-laptop-trial/eval12-<model>
```

Dört model: (a) temel `qwen3.5:0.8b` (Ollama'nın Q8_0'ı, `presence_penalty 1.5` ile);
(a′) aynı temel model `presence_penalty 0`, `num_ctx 4096` ile (`qwen3.5-0.8b-ctl`; dışa
aktarılan modelle ayar farkını ayırmak için); (b) ince ayarlı f16 (`bist-trial-0.8b-f16`,
nicemleme öncesi); (c) ince ayarlı q4_K_M (`bist-trial-0.8b`, nicemleme sonrası). f16
0,8B modeli 4 GB'a sığdığı için nicemlenmemiş karşılaştırma yapılabildi.

| | (a) temel Q8_0 | (a′) temel, pp 0 | (b) deneme f16 | (c) deneme q4_K_M |
| --- | --- | --- | --- | --- |
| Temiz araç turu (ilk denemede, ret ve metin yok, geri dönüş yok) | 25/33 (%76) | 25/33 (%76) | 29/31 (%94) | 28/30 (%93) |
| Reddedilen çağrı / önerilen (`wrong_tool_call_rate`) | 13/38 (0,342) | 13/42 (0,310) | 3/53 (0,057) | 3/40 (0,075) |
| Araç yerine metin cevabı | 3 | 3 | 0 | 0 |
| Harness'in kanonik geri dönüşü | 8 | 8 | 1 | 1 |
| Modelin çağırdığı araç kümesi = beklenen | 1/12 | 2/12 | 5/12 | 2/12 |
| Senaryo doğruluğu (`scenario_accuracy`) | 5/11 (0,45) | 5/11 (0,45) | 7/11 (0,64) | 6/11 (0,55) |
| Sonuç eşleşmesi (`outcome_match_rate`) | 11/12 | 11/12 | 11/12 | 11/12 |
| Açıklama ilk denemede kabul | 1/10 | 0/10 | 4/10 | 3/10 |
| Açıklama geri dönüşü (`explanation_fallbacks`) | 7 | 10 | 6 | 7 |
| Harness müdahalesi (`harness_interventions`) | 12 | 12 | 3 | 4 |
| Yazılan sayı / kanıtsız | 11 / 0 | 0 / 0 | 29 / 0 | 17 / 0 |
| Tuzak (`advice_request`) | reddedildi | reddedildi | reddedildi | reddedildi |
| Gecikme medyanı | 7,6 sn | 11,5 sn | 14,2 sn | 6,0 sn |

Okuma (12 soru, 1 tekrar: tek bir sorunun değişmesi oranı 8 puan oynatır; sonuçlar
yönlüdür, kesin değildir):

- **Nicemleme öncesi/sonrası (b → c):** araç çağrısı doğruluğu korunuyor: temiz araç turu
  %94 → %93, reddedilen çağrı 3 → 3 (oran 0,057 → 0,075, önerilen çağrı sayısı düştüğü
  için), metin cevabı 0 → 0, geri dönüş 1 → 1. Fark niyet turunda: senaryo doğruluğu
  7/11 → 6/11; bu da sonraki araç durumlarını değiştirdiği için "araç kümesi = beklenen"
  5/12 → 2/12'ye iniyor. Açıklama ilk denemede kabul 4 → 3. q4_K_M bu örneklemde
  araç çağrısı biçimini bozmuyor; niyet ve açıklama turlarında bir sorunluk kayıp var.
- **Temel → deneme:** 20 adım (80 kayıt) araç turlarında belirgin bir değişiklik yaptı:
  reddedilen çağrı 13 → 3, metin cevabı 3 → 0, geri dönüş 8 → 1. Bu iyileşme
  `presence_penalty` farkından gelmiyor: (a′) temel modelde de 13 ret ve 8 geri dönüş var.
  Yine de bu bir kalite iddiası değildir: örneklem küçük, eğitim 20 adım, sonuç
  eşleşmesi (11/12) dört modelde de aynı ve sonuç sınıfı kaba (`ANALYSIS` dört etiketi
  birlikte sayar). Kalite karşılaştırması 5070'teki tam koşuların ve Task 9'un işidir.
- Dört modelde de tek uyuşmayan soru `macro_context_hold-0021`: niyet turunda senaryo
  yanlış (`PRICE_SUMMARY` ya da `CALENDAR_PATTERN`), kapı `ANALYSIS_UNSAFE` ile kapattı.
- f16 modelin gecikmesi en yüksek (1,5 GB ağırlık 4 GB GPU'da, 4.096 bağlam); q4_K_M en
  hızlı. Temel modeldeki taslak (MTP) bloğu dışa aktarılan modelde yok.

## 7. İnternetsiz çalışma

`tests/test_offline.py`: soket düzeyinde bir yama yerel olmayan her bağlantıyı ve ad
çözümlemesini reddederken iki tam harness koşusu (öğretmen sahte model, araçlar sentetik
anlık görüntüde süreç içinde) sonuca ulaşır; hiçbir bağlantı denemesi olmaz. Ayrıca
`src/` altında bulut yapay zekâ SDK'sı (`openai`, `anthropic`, `google.generativeai`,
`google.genai`, `cohere`, `mistralai`) içe aktarılmaz. Wi-Fi kapalı canlı deneme Burak'ın
işidir (süre kayda geçecek).

## 8. Masaüstü paketi

```
uv run python -m bist_harness.finetune.train bundle --data data/finetune \
  --config configs/qlora/r16-e2.toml --config configs/qlora/r32-e3.toml \
  --config configs/qlora/laptop-trial.toml --out runs/finetune-bundle-20261118.zip
```

Paket (359 KB, git dışı): `data/finetune/` altında `train/val/test.jsonl`,
`dev_questions.jsonl`, `manifest.json`; `configs/qlora/` altında üç ayar dosyası;
`README.md` (masaüstü adımları); `BUNDLE.json` (her dosyanın SHA-256'sı). Veri dosyaları
manifestteki SHA-256'larla eşleşmezse paket yazılmaz. Masaüstü adımları:
`docs/finetune.md`, "Eğitim ve dışa aktarma (RTX 5070)".
