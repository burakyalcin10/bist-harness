# İnce ayar eğitimi: dizüstü denemesi (Task 8, 18 Kasım 2026)

CSE-481 Mühendislik Ekonomisi — yalnız eğitim amaçlıdır, yatırım tavsiyesi değildir.

Bu belge dizüstündeki 20 adımlık QLoRA denemesini (EC-006) kaydeder: eğitim → dışa aktarma
→ Ollama → harness boru hattının uçtan uca çalıştığını gösterir. Amaç kalite değildir.
RTX 5070'teki iki ayarın (`r16-e2`, `r32-e3`) koşuları ve model seçimi sonra bu belgeye
eklenecek; 9B'yi 12 GB'ye sığdıran bellek çalışması (Task 8b) 9. bölümdedir.

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

`train.ollama_tools` aynı dönüşümü yapar.

**Bayt bayt denetim (düzeltme turu 1).** Ollama, sohbet isteğinde
`"_debug_render_only": true` verilince modeli çalıştırmadan işlediği istemin metnini
döndürür (`_debug_info.rendered_template`). `finetune/template_check.py` eğitim isteminin
metnini (HF şablonu, `ollama_tools`, düşünme kapalı) bu metinle bayt bayt karşılaştırır;
anahtar sırası ya da boşluk farkı, uzunluk aynı kalsa da bulunur (birim testi:
`test_reordered_keys_of_equal_length_are_caught`).

```
uv run --group train python -m bist_harness.finetune.template_check --data data/finetune \
  --base-model Qwen/Qwen3.5-0.8B --revision 2fc06364715b967f1860aea9cf38778875588b17 \
  --ollama-model qwen3.5:0.8b --n 40 --out runs/finetune-laptop-trial/template-check.json
[template-check] 40/40 identical byte for byte (raw schemas: 12/40)
```

40 kayıt: her (tur, araç kümesi) birleşiminin ilk kaydı (10) ve train/val/test'ten eşit
aralıkla 30 kayıt. 40'ının 40'ı bayt bayt aynı. Ham şemayla (dönüşümsüz) yalnız araçsız 12
tur (intent, explanation) aynı; araçlı 28 turun hepsi farklı. Aynı komut dışa aktarılan
`bist-trial-0.8b` ile de 40/40 verdi (Modelfile aynı işleyiciyi taşır). Kapsam: Ollama
0.40.16 ve `qwen3.5` işleyicisi, 40 kayıt; başka bir Ollama sürümünde ya da Task 7'nin
modelinde denetim yeniden koşulur. Hedef tur (araç çağrısı XML'i) bu denetime girmez:
çıkarımda o metni model üretir, Ollama'nın ayrıştırıcısı okur (5. bölümdeki harness
koşusunda çağrılar ayrıştırıldı).

**İlk, dolaylı denetim** (düzeltme turundan önce; uzunluk ölçer, anahtar sırasını göremez):
her tur türü ve her araç birleşimi için bir kayıt (10 kayıt) HF şablonuyla işlendi ve aynı
mesajlar Ollama'ya gönderildi (`/api/chat`, `think: false`, `num_predict: 1`):

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
turlarında 5–12 belirteç fark vardı. Bu ölçü alan düşmesini gösterir ama anahtar sırasını
göremez; sıranın kanıtı yukarıdaki bayt bayt denetimdir. Hedef tur HF şablonuyla şöyle
işlenir (araç turu):

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
Düzeltme turu 1'den sonra `export` birleştirmeden önce llama.cpp kopyasının commit'ini
Ollama'nın çalışma zamanı commit'iyle karşılaştırır ve en sonda modeli yükleyip tek
belirteç üretir; q4_K_M dışa aktarma yeniden koşuldu (60 sn) ve `export.json`:
`"ollama_version": "0.40.16"`, `"runtime_commit": "6c01da627"`,
`"converter_commit": "6c01da6278ab6c69ed67d9124806b50d2b299ba7"`, `"load_check": "passed"`.
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

## 9. 9B'yi 12 GB'ye sığdırmak: bellek-yalın yol ve parça parça birleştirme (Task 8b)

Burak'ın kararı (18 Kasım 2026): hedef `qwen3.5:9b`, sığmazsa yedek `qwen3.5:4b`. Task 7'nin
tahmini, Task 8'in eğitim koduyla 9B için ≈ 17–18 GB idi
(`docs/results/2026-11-18-base-model-selection.md`). Bu bölüm kod değişikliğini, dizüstü
ölçümlerini ve 9B tahminini kaydeder. 9B dizüstüne (4 GB) yüklenemediği için eşdeğerlik ve
bellek denemeleri 0.8B ile, katman bellek ölçümleri 9B genişliğinde rastgele katmanlarla
yapıldı. Masaüstü adımları: `docs/finetune.md`, "RTX 5070'te çalıştırma".

### 9.1 Temel modelin Hugging Face deposu

| | 9B (hedef) | 4B (yedek) |
| --- | --- | --- |
| Ollama etiketi (masaüstü) | `qwen3.5:9b-q4_K_M` | `qwen3.5:4b` |
| Masaüstünün manifest özeti (`/api/tags`, geçitten) ve Ollama kütüğündeki | ikisi de `56671c2a…` | ikisi de `d8b0f5e9…` |
| GGUF üstverisi (kütükteki model katmanının ilk 16 MB'ı) | `general.license.link` → `Qwen/Qwen3.5-9B`, taban `Qwen3.5-9B-Base` | `Qwen/Qwen3.5-4B`, taban `Qwen3.5-4B-Base` |
| Hugging Face deposu, revizyon | `Qwen/Qwen3.5-9B` @ `c202236235762e1c871ad0ccb60c8ee5ba337b9a` | `Qwen/Qwen3.5-4B` @ `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` |
| Mimari (HF `config.json` = GGUF) | `Qwen3_5ForConditionalGeneration`; 32 katman (24 Gated DeltaNet + 8 tam dikkat), gizli 4096, MLP 12288, dikkat 16/4 baş × 256, DeltaNet 16 anahtar / 32 değer başı × 128 | 32 katman, gizli 2560, MLP 9216 |
| Gömme ve çıkış katmanı | **ayrı** (`tie_word_embeddings: false`; GGUF'ta `output.weight` var) | paylaşılan (GGUF'ta `output.weight` yok) |
| Sözlük | 248.320 satır; HF belirteçleyicinin 248.077 belirteci GGUF listesinde aynı numarada, kalan 243 satır `[PAD…]`; eos 248046, pad 248044 aynı | 9B ile aynı belirteç listesi |

- **Belirteçleyici:** `tokenizer.json`, `vocab.json`, `merges.txt` 0.8B, 4B ve 9B'de bayt
  bayt aynı (SHA-256).
- **Sohbet şablonu:** 9B'nin (ve 4B'nin) `chat_template.jinja`'sı 0.8B'ninkinden tek yerde
  ayrılır: düşünme bayrağı verilmediğinde 9B düşünmeyi açar, 0.8B kapatır. Eğitim
  `enable_thinking=False` geçtiği için fark yoktur: 3.618 kaydın 3.618'i (istem ve hedef)
  9B ve 0.8B şablonuyla aynı metni verir. Ollama'da üç model aynı yerleşik işleyiciyi taşır
  (`renderer`/`parser` `qwen3.5`, aynı `template` katmanı `b507b9c2…`); 0.8B'de bayt bayt
  denetim 40/40 geçti (2. bölüm). Masaüstünde 0.40.4 ve 9B ile `template_check` yeniden
  koşulur (`docs/finetune.md`, 7. adım).
- **LoRA hedefleri:** 9B'nin dil modelindeki doğrusal katman adları 0.8B'ninkilerle aynı:
  DeltaNet `in_proj_qkv`, `in_proj_z`, `in_proj_a`, `in_proj_b`, `out_proj`; tam dikkat
  `q_proj`, `k_proj`, `v_proj`, `o_proj`; MLP `gate_proj`, `up_proj`, `down_proj`. Ayarlar
  Task 8'in on hedefini korur (`in_proj_a`/`in_proj_b` 32 çıkışlı küçük kapı katmanlarıdır,
  hedef değildir). Eğitilen parametre: r16 40.108.032, r32 80.216.064.
- Ollama'nın 9B modelinde taslak (MTP) katmanı yoktur (0.8B'de vardı); HF deposunda `mtp.*`
  tensörleri vardır, transformers onları yüklemez.

### 9.2 Bellek-yalın yol (`finetune/train.py`)

Üç ayar, hepsi ayar dosyasında yazılı (`laptop-trial.toml` `false`/`0` ile eski yolu korur):

- `lean_memory = true` → `prepare_lean`: PEFT'in `prepare_model_for_kbit_training`'i yerine
  her parametre dondurulur; yalnız tek boyutlu olanlar (norm, `A_log`, `dt_bias`) fp32'ye
  alınır; gömme ve çıkış katmanı bf16 kalır; gradient checkpointing (`use_reentrant=False`)
  ve giriş gradyanı açılır.
- `target_only_logits = true` → `target_only_loss` (özel `compute_loss`): modelin gövdesi
  (`model.model`) gizli durumları verir; çıkış katmanı yalnız kaydırılmış etiketi -100
  olmayan konumlara uygulanır; kayıp etiketli belirteçler üzerinde ortalama (gradyan
  biriktirmede Trainer'ın `num_items_in_batch`'iyle toplam / sayı): modelin kendi
  kaybıyla aynı ölçekleme.
- `logits_chunk = 128` → hedef konumlar 128'lik parçalarda; her parçanın logitleri geri
  yayılımda yeniden hesaplanır (`torch.utils.checkpoint`).

**Eşdeğerlik testi** (`tests/test_finetune_lean.py`, CPU, küçük rastgele Qwen3.5: 3 DeltaNet
+ 1 tam dikkat katmanı, 211 belirteç, LoRA on hedefte): iki satırlık, dolgulu, istemi
maskeli bir toplu işte standart yolun kaybı ve bütün LoRA gradyanları yeni yolunkiyle eşit
(kayıpta `rtol` 1e-5, gradyanda 1e-4); parça boyu 0, 1, 5 ve 64'te; `num_items_in_batch`
ile; paylaşılan gömmeli modelde. Çıkış katmanı tek çağrıda yalnız hedef satır sayısı kadar
satır görür. Hazırlık testi: gömme ve çıkış katmanı bf16 ve donuk, norm/`A_log`/`dt_bias`
fp32, matrisler yüklendiği gibi, checkpointing açık.

### 9.3 0.8B dizüstü denemesi: eski yol ve yeni yol

Aynı ayarlar, aynı tohum ve aynı 80 + 16 kayıt (`laptop-trial.toml` ve yalnız üç bellek
ayarıyla ayrılan `laptop-trial-lean.toml`); ayrıca yeni yol, veri setinin en uzun 80 + 16
kaydında (`sample = "longest"`; `runs/` altındaki kopya).

| | Task 8 (PEFT yolu) | Task 8b (yalın yol) | Task 8b, en uzun kayıtlar |
| --- | --- | --- | --- |
| En uzun eğitilen tur / hedefi | 1.241 / 501 belirteç | 1.241 / 501 | **1.475 / 622** (= train + val'in en uzunu) |
| En yüksek bellek, ayrılmış | 5,36 GB | **1,26 GB** | 1,33 GB |
| En yüksek bellek, rezerve | 9,92 GB | 1,75 GB | 1,74 GB |
| Paylaşılan belleğe taşma (4 GB kart) | var (WDDM) | yok (GPU 1.755 MB, paylaşılan 80 MB) | yok |
| Adım süresi (4 örnek, doğrulamalar dahil) | ≈ 18,9 sn (378 sn / 20) | 13,7 sn | 17,3 sn |
| Eğitim kaybı, adım 1 → 20 | 0,7357 → 0,0155 | 0,7335 → 0,0158 | 0,0666 → 0,0007 |
| 20 adım ortalaması | 0,1103 | 0,1122 | 0,0113 |
| Doğrulama kaybı, adım 10 / 20 | 0,0849 / 0,0433 | 0,0890 / 0,0447 | 0,0010 / 0,0006 |

Kayıplar adım adım yakın. İlk adımda (henüz güncelleme yok) fark %0,3'tür ve sayısal
yoldan gelir: eski yolda fp32'ye yükseltilen gömmenin çıktısı artık akışını (residual
stream) fp32 yapıyordu, yeni yolda bf16'dır. 20 adım sonunda doğrulama kaybı farkı %3.
Bellek %76 düştü; 4 GB kartta artık taşma olmadığından adım da kısaldı. En uzun kayıtlar
yalnız açıklama turlarıdır (1.068–1.475 belirteç); kayıpları bu yüzden çok düşüktür.

### 9.4 Bellek tahmini (`finetune/memory.py`) ve kalibrasyonu

`uv run --group train python -m bist_harness.finetune.memory --config <ayar> [--rank …]`
modelin tensör boyutlarını Hub'ın safetensors başlıklarından okur (ağırlık indirmez) ve
PyTorch'un en yüksek ayrılmış belleğini (GiB; `run.json` gibi "GB") terim terim yazar:
4 bit NF4 ağırlıklar (çift nicemleme, 0,516 bayt/parametre), gömme ve çıkış katmanı,
küçük parametreler, LoRA ağırlığı ve gradyanı (8 bayt/parametre; 8 bit Adam durumları
sayfalı bellektedir, PyTorch sayacına girmez), katman başına checkpoint edilen gizli durum,
ve yeniden hesaplanan tek katmanın çalışma alanı ile bir logit parçasının büyüğü (çıkış
katmanının geri yayılımı katmanlarınkinden önce biter; ikisi aynı anda yaşamaz).

Ölçümler (dizüstü, RTX 3050 Ti, 18 Kasım 2026):

| Ölçüm | Sonuç |
| --- | --- |
| 0.8B 4 bit yükleme (`_load_base`) | 0,775 GB; 4 bit parametre 595.132.416 (dil 497,6 M + görüntü 97,5 M), tahmindeki sayının aynısı |
| Katman çalışma alanı: 4 katmanlık 4 bit yığın, LoRA r32, hedef-yalnız kayıp (rastgele ağırlık, küçük sözlük); 9B genişliği, 737 / 1.475 / 2.200 belirteç | 0,54 / 0,97 / 1,43 GB → belirteç başına 651.760 bayt + sabit 0,096 GB (en büyük 4 bit ağırlığın bf16 açılımı ≈ 0,094 GB) |
| Aynısı, 8 katman, 1.475 belirteç | katman başına ek 0,0115 GB: bir bf16 gizli durum (1.475 × 4096 × 2 bayt) |
| Aynısı, 4B genişliği (737 / 1.475) | belirteç başına 564.790 bayt + 0,059 GB |
| Aynısı, 0.8B genişliği (737 / 1.475) | belirteç başına 284.760 bayt + 0,017 GB |
| Hedef-yalnız logit parçası, 248.320 sütun × 64 / 128 / 256 satır | 12,1 / 12,7 / 12,0 bayt/öğe (128 satır: 0,375 GB) |
| Tam dizi logiti (eski yol), aynı kayıp tek başına | 16,0 bayt/öğe; Task 8 denemesinin tepe noktasından geriye: 13,8 |

Tahminin 0.8B denemeleriyle karşılaştırması: eski yol 5,36 GB (tam logit katsayısı bu
denemeden geldiği için tanım gereği), yalın yol 1,24 GB (ölçülen 1,26; %−1,6), en uzun
kayıtlarla 1,28 GB (ölçülen 1,33; %−3,4). Tahmin gerçeğin biraz altında kalıyor.

**9B tahmini** (yalın yol; 1.475 belirteçlik en uzun tur, 622 belirteçlik hedef,
`logits_chunk` 128; GB = GiB):

| Terim | r16 | r32 |
| --- | --- | --- |
| 4 bit ağırlıklar (dil + görüntü, 7,37 B parametre) | 3,54 | 3,54 |
| Gömme + ayrı çıkış katmanı, bf16 (2 × 1,017 B) | 3,79 | 3,79 |
| Küçük parametreler | 0,01 | 0,01 |
| LoRA ağırlık + gradyan | 0,30 | 0,60 |
| Checkpoint edilen gizli durumlar (32 katman) | 0,36 | 0,36 |
| Katman çalışma alanı (0,99) ile logit parçasının (0,38) büyüğü | 0,99 | 0,99 |
| **Toplam (ayrılmış)** | **8,99** | **9,29** |
| 0.8B'deki en kötü sapmayla (%3,4) | ≈ 9,3 | ≈ 9,6 |

Aynı tahmin eski yolla 9B için 16,9 / 17,2 GB verir (Task 7'nin ≈ 18'ini doğrular); yalın
yolla 4B için 4,35 / 4,58 GB. Dizüstünde rezerve ayrılmışın ≈ 0,4–0,5 GB üstünde kaldı;
r32 için rezerve ≈ 10,0–10,1 GB, üstüne CUDA bağlamı (≈ 0,5 GB), sayfalı Adam durumları
(r32: ≈ 0,16 GB) ve Windows'un ekran belleği gelir. Tahmin 12 GB'ye sığar, ama pay
≈ 1–1,5 GB'dir: kesin söz masaüstü denemesinindir (`trial-9b`). Tahminin zayıf yanı:
katman çalışma alanı 9B genişliğinde ölçüldü, ama gerçek 9B ağırlıklarıyla değil, ve
dizüstünün çekirdekleri (sm_86) 5070'inkilerle (sm_120) aynı bellek düzenini kullanmayabilir.

**İsteğe bağlı iki kaldıraç** (eklenmedi): tahmin r32 için deneme eşiğinin (ayrılmış
≤ 10,5 GB) altında kaldığından brief'in kuralına göre koda girmedi. Kazançları tensör
boyutlarından kesin olarak hesaplandı (GPU'da ölçülmedi): gömmeyi CPU'da tutmak (yalnız
arama) 1,89 GB; çıkış katmanını 4 bit yüklemek (`llm_int8_skip_modules`) 1,89 − 0,49 =
1,41 GB (o zaman eğitimde logitler nicemlenmiş ağırlıkla hesaplanır, dışa aktarılan model
bf16 ağırlığı taşır: küçük bir eğitim/çıkarım farkı). Masaüstü denemesi geçmezse karar
Burak'ındır: 4B'ye geçiş (`docs/finetune.md`, 5. adım) ya da ayrı bir iş olarak gömmeyi
CPU'da tutma kaldıracı.

### 9.5 Parça parça birleştirme (`finetune/export.py`, `stream_merge`)

9B'yi PEFT'in `merge_and_unload`'ıyla birleştirmek bütün bf16 modeli RAM'de ister (≈ 18 GB;
masaüstünde 16 GB). `stream_merge` her safetensors parçasını bellek eşlemeli açar, her
tensörü tek tek okur, hedef katmanlara `W + (alpha/r) · (B @ A)` ekler (PEFT'in
aritmetiği: çarpım fp32, toplam bir kez ağırlığın tipine yuvarlanır; rsLoRA'da `alpha/√r`)
ve en çok 2 GiB'lık yeni parçalar yazar; bellek ≈ bir çıkış parçası ve bir tensör. DoRA,
örüntülü rank/alpha, LoRA biası, `modules_to_save` gibi uygulanmayan ayarlar ve tabanda
karşılığı olmayan adaptör katmanı açık hatayla reddedilir. Yapılandırma, belirteçleyici ve
şablon dosyaları tabandan olduğu gibi kopyalanır; `mtp.*` (transformers'ın yüklemediği
taslak) PEFT yolunda olduğu gibi yazılmaz.

| Denetim | Sonuç |
| --- | --- |
| Birim testi (`tests/test_finetune_stream_merge.py`; küçük Qwen3.5, birkaç parça, düz LoRA ve rsLoRA) | PEFT'in `merge_and_unload`'ıyla bütün tensörler bit bit aynı; yalnız hedef katmanlar değişir |
| Gerçek 0.8B + Task 8 adaptörü: PEFT birleştirmesi ve `stream_merge` | 473 / 473 tensör; 437'si bit bit aynı; 36'sı (`A_log`, DeltaNet `norm.weight`) denetim noktasında fp32: PEFT yolu bunları bf16'ya yuvarlıyor, yeni yol özgün fp32'yi koruyor (bf16'ya yuvarlanınca aynı) |
| İkisinden f16 GGUF (sabitlenmiş dönüştürücü `6c01da627`) | 320 / 320 tensör; 302'si aynı; 18 `ssm_norm` en çok 0,0039 farklı (PEFT yolunun bf16 yuvarlaması); yeni GGUF'ta README'den gelen lisans ve taban model üstverisi de var |
| Süre (0.8B, CPU) | PEFT 31,7 sn, parça parça 10,7 sn |
| Uçtan uca `export` (parça parça → f16 → q4_K_M → `ollama create` → yükleme denemesi), Ollama 0.40.16 | 73 sn, `"load_check": "passed"`; harness sorusu `price_summary-0006`: `INVESTIGATE`, 2 araç çağrısı reddedilmeden, 4/4 sayı kanıtta, 9,8 sn (Task 8 ile aynı sonuç); deneme modeli sonra silindi |

9B'de disk: birleştirilmiş klasör ≈ 19 GB (GGUF'tan sonra silinir), f16 GGUF ≈ 18 GB,
q4_K_M ≈ 5,6 GB.

### 9.6 Deneme ölçütü düzeltmesi

Task 7'nin masaüstü deneme ölçütü `max_trained_tokens == max_example_tokens` idi;
`max_example_tokens` test bölümünü de kapsar, test ise hiç eğitilmez: en uzun tur test'te
olsaydı ölçüt hiç tutmazdı. `run.json` artık `max_train_val_tokens`'ı (train + val'in en
uzunu) ve `max_trained_target_tokens`'ı da yazar; ölçüt
`max_trained_tokens == max_train_val_tokens`. Bu veride en uzun tur train'dedir
(`sector_laggard_company-0000-05`, 1.475 belirteç; val'in en uzunu 1.473, test'inki 1.467),
yani üç değer de 1.475'tir; dizüstündeki en uzun kayıt denemesi 1.475'i gördü.

## 10. RTX 5070'te 9B eğitimi ve dışa aktarma (19–20 Kasım 2026)

Burak masaüstünde `docs/finetune.md`'nin "RTX 5070'te çalıştırma" adımlarını uyguladı
(commit `87ff0f6`; torch 2.11.0+cu128, transformers 5.23.0, peft 0.21.3, bitsandbytes 0.50.2).
Saatler Türkiye saatidir. Çıktılar dizüstünde `runs/finetune-{trial-9b,r16-e2,r32-e3}/`
ve `runs/desktop-logs-9b/` altındadır (git dışı).

### 10.1 Bellek denemesi `trial-9b` (19 Kasım, 01:30–01:42)

| Ölçüt | Ölçülen | Eşik | |
| --- | --- | --- | --- |
| `max_trained_tokens` / `max_train_val_tokens` | 1.475 / 1.475 | eşit | geçti |
| Ayrılmış tepe (`allocated`) | 9,408 GB | ≤ 10,5 | geçti |
| Rezerve tepe (`reserved`) | 10,689 GB | < 11,5 | geçti |
| Paylaşılan belleğe taşma (izleme penceresi, en çok) | 196 MB | < 1.000 | geçti |
| Adım başına süre | 35,42 sn | süre kuralı | ikisi bir gecede |

Tahmin (9.4) r32 için 9,29 GB'tı; ölçüm %1,3 üstünde. İzleme penceresi süreç başına
11.243 MB adanmış GPU belleği gösterdi (CUDA bağlamı dahil). 20 adım 708 sn;
`wall_time_s` − `train_runtime_s` 31 sn. `started_at` ile `finished_at` arası da 740 sn
olduğundan bu fark modelin yüklenmesini içermiyor gibi görünüyor; yükleme süresi ayrıca
ölçülmedi. Denemenin 96 kaydı (train 80, val 16) en
uzun kayıtlar olduğu için hepsi açıklama turudur.

### 10.2 Gece koşuları (19 Kasım)

Tek komutla arka arkaya (`r16-e2` başarıyla bitince `r32-e3`):

| | `r16-e2` | `r32-e3` |
| --- | --- | --- |
| Başlangıç – bitiş | 01:45 – 03:42 | 03:42 – 06:37 |
| Adım (planlanan) | 296 (296) | 444 (444) |
| Erken durma | yok | yok |
| Eğitilen parametre | 40,1 M | 80,2 M |
| İlk / en iyi doğrulama kaybı | 0,00605 (adım 50) / **0,001672** (adım 296) | 0,00614 (adım 50) / 0,001684 (adım 444) |
| Son eğitim kaybı | 0,0000535 | 0,000298 |
| Adım başına süre | 23,59 sn | 23,59 sn |
| Duvar saati | 1 sa 57 dk | 2 sa 55 dk |
| Tepe bellek (allocated / reserved) | 9,092 / 9,430 GB | 9,407 / 9,836 GB |
| En uzun tur | 1.475 / 1.475 | 1.475 / 1.475 |

Örnekler: train 2.361 (niyet 560, araç 1.421, açıklama 380), val 618 (140 / 373 / 105);
uzunluk yüzünden atılan yok. Gerçek adım süresi denemenin 0,67 katı oldu (belgedeki
varsayım 0,57); 618 kayıtlık doğrulama her seferinde 207 sn sürdü. İki koşunun doğrulama
eğrisi:

| Adım | 50 | 100 | 150 | 200 | 250 | 296 / 300 | 350 | 400 | 444 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `r16-e2` | 0,00605 | 0,00409 | 0,00205 | 0,00178 | 0,00171 | 0,00167 | | | |
| `r32-e3` | 0,00614 | 0,00407 | 0,00226 | 0,00235 | 0,00228 | 0,00198 | 0,00173 | 0,00170 | 0,00168 |

Makine 06:37'den sonra kapandı; koşuların ikisi de `run.json`'unu yazmıştı.

### 10.3 Doğrulama kaybı neden bu kadar düşük

İlk eğitim adımlarının kaybı 0,13–0,29'dur; 30 adımda ≈ 0,001'e iner. Üç olasılık denetlendi:

- **Etiket maskesi doğru.** 9B belirteçleyicisiyle val kayıtlarının etiketli belirteçleri metne
  çevrildi: yalnız asistanın cevabı ve `<|im_end|>\n`; boş `<think>\n\n</think>\n\n` bloğu
  istemdedir. Etiketli belirteç ortalaması: niyet 56, araç çağrısı 114, açıklama 320.
- **Sızıntı yok.** Train ve val soru düzeyinde ayrıktır (ortak soru 0; 560 ve 140 soru); 29
  soru ailesi (şablon) iki tarafta da vardır. Val hedeflerinin 34 / 618'i train'de birebir
  geçer (niyet 32, araç 2: kısa, standart niyetler).
- **Hedefler büyük ölçüde istemden kopyadır.** Öğretmen deterministik bir programdır
  (`finetune/teacher.py`): niyet sorudaki hisse ve tarihleri JSON'a yazar, araç turu aynı
  değerleri çağrıya taşır, açıklama istemdeki kanıt satırlarını sabit bir kalıpla yeniden
  yazar ("EKGYO için 2023-01-27 tarihinde RSI değeri 47,08. [E4]").

Sonuç: belirteç ortalamalı kayıp, karar taşıyan az sayıdaki belirteci (etiket, ret)
neredeyse hiç göstermez; iki koşuyu ayırmaz ve model kalitesi hakkında bilgi vermez. Seçim
geliştirme sorularında (10.5), karşılaştırma donmuş sorularda (Task 9) yapılır.

### 10.4 Dışa aktarma (20 Kasım, Ollama 0.40.4)

- `llama-server.exe` ve `llama-quantize.exe` 0.40.4'ün `lib\ollama` klasöründe var;
  `llama-server --version` → `version: 0.6.0-dev (build 1, commit b42b7e6d3)`. Dönüştürücü
  `tools/llama.cpp` `b42b7e6d3059503dd4bed6ca5dcf342bb6379f67`'ye sabitlendi.
- `template_check` 9B ve 0.40.4 ile: **40 / 40 bayt bayt aynı** (ham araç şemalarıyla 12 / 40;
  `ollama_tools` gerekli). 0.40.4 `_debug_render_only`'yi destekliyor.
- Üç model aynı komutla dışa aktarıldı; hepsinde `"load_check": "passed"`,
  `runtime_commit` = `converter_commit` öneki `b42b7e6d3`:

| Model | Adaptör | Süre | Ollama boyutu |
| --- | --- | --- | --- |
| `bist-r16-e2` | `r16-e2` | ≈ 5,5 dk (02:42–02:47) | 5,6 GB |
| `bist-r32-e3` | `r32-e3` | ≈ 6 dk | 5,6 GB |
| `bist-base-9b` | `r16-e2`'nin bütün `lora_B`'leri sıfır (kontrol) | ≈ 5 dk | 5,6 GB |

f16 GGUF 16,7 GB çıktı (9.5'teki ≈ 18 GB tahmini fazla); q4_K_M 5,2 GB dosya. Birleştirme
sürecinin çalışma belleği 6,5 GB'a çıktı (`docs/finetune.md`'deki 4–5 GB tahmini düşük);
16 GB'de sorun olmadı. Ollama'nın hazır `qwen3.5:9b-q4_K_M`'i 6,55 GB'tır (Task 7'de
belirtildiği gibi görüntü projektörü dahil); dönüştürücü yalnız dil modelini alır.

**Kontrol modeli `bist-base-9b`.** Karşılaştırmada fark yalnız ince ayardan gelsin diye temel
model de aynı hattan geçirildi (Burak'ın onayı, 20 Kasım): `lora_B` sıfır olunca
`W + (alpha/r)·(B @ A) = W`, birleştirme temel ağırlıkları değiştirmez; dönüştürücü,
nicemleme ve Modelfile (örnekleme ayarları, şablon) ince ayarlı modellerle aynıdır.
Ollama'nın hazır modeli (farklı nicemleme karışımı ve projektör) ikincil referanstır.

Geçit: dizüstünden TLS `internal_error` alındı; `tailscale cert`'ten sonra geçit yeniden
çalıştı, ama asıl neden sertifika değildi (10.6). Üç model geçidin `/api/tags`'ında
görünüyor (Q4_K_M, 9,0B, 5,63 GB).

### 10.5 Seçim: `bist-r16-e2` (20 Kasım)

Geliştirme soruları (`data/finetune/dev60.jsonl`, 60 soru), deney E, iki tekrar, Task 7 ile
aynı yol (`BIST_LLM_API=openai`, geçitten, 5070). r32'de 6 kayıt (3 soru) geçit kopukluğuyla
`MODEL_UNAVAILABLE` bitti (10.6); bu üç soru IPv6 yolundan iki tekrarla yeniden koşuldu ve
tabloda onların kayıtları kullanıldı (`runs/finetune-selection/bist-r32-e3-rerun/`). Ölçütler
`eval/metrics.py`'den; açıklama kabulü Task 7'deki gibi "model yazdı / (model yazdı + geri
dönüş)". "Hazır 9B" Task 7'nin `qwen3.5:9b-q4_K_M` koşusudur (18 Kasım).

| Ölçüt | `bist-r16-e2` | `bist-r32-e3` | `bist-base-9b` (kontrol) | hazır 9B |
| --- | --- | --- | --- | --- |
| Açıklama kabulü | **82 / 96 (%85,4)** | 80 / 94 (%85,1) | 62 / 90 (%68,9) | 72 / 88 (%81,8) |
| Sonuç eşleşmesi | **1,000** | 0,983 | 0,950 | 0,933 |
| Senaryo doğruluğu | **1,000** | 0,958 | **1,000** | **1,000** |
| Hatalı çağrı (ret / önerilen) | 12 / 498 (0,024) | **6 / 480 (0,013)** | 18 / 610 (0,030) | 16 / 378 (0,042) |
| Modelin yazdığı desteksiz sayı | **0 / 726** | **0 / 692** | 18 / 708 | 4 / 734 |
| Uydurulan alan | **8** | 10 | 30 | 24 |
| Hisse doğruluğu, ham / temellendirilmiş | **0,930 / 1,000** | 0,907 / 0,977 | 0,767 / 0,930 | 0,767 / 0,907 |
| Kanıtsız sonuç (düzeltilmiş ölçüt, aşağıda) | **0 / 96** | 4 / 94 | **0 / 90** | **0 / 88** |
| Harness müdahalesi | 48 | **42** | 50 | 48 |
| Tekrarlanabilirlik | 60 / 60 | 60 / 60 | 60 / 60 | 60 / 60 |

**Karar: `bist-r16-e2`.** Hatalı çağrı (6 ret fark) ve müdahale dışında her ölçütte r32'ye eşit
ya da önde; rank'ı ve epoch sayısı küçük. Doğrulama kaybı (10.3) ikisini ayırmıyordu.

Okuma:

- **İnce ayar, kontrole göre:** açıklama kabulü %68,9 → %85,4; modelin desteksiz sayısı
  18 → 0; uydurulan alan 30 → 8; ham hisse doğruluğu 0,77 → 0,93; daha az çağrı önerip daha az
  ret alıyor. Bunlar eğitim verisinin öğrettiği turlar (niyet, araç çağrısı, açıklama).
- **Kanıtsız sonuç: ölçüm hatası bulundu ve düzeltildi.** İlk hesapta oran ince ayarlı
  modellerde yüksek görünüyordu (r16 20 / 96, r32 22 / 94, kontrol 14 / 90, hazır 16 / 88).
  Bu kayıtların hepsinde doğrulayıcının itirazları, E deneyinde harness'in model cevabının
  sonuna doğrulamadan *sonra* eklediği bellek bölümüne ("Önceki analizler: M1 …") aitti:
  bu satırlar kanıt etiketi taşımıyor, içindeki sıra numaraları ve tarihler kanıtta yok.
  `run_eval` cevabı bu bölümle birlikte doğruluyordu (`eval/metrics.py` sayı sayarken bölümü
  zaten çıkarıyordu). Model ne kadar sık kendi açıklamasını yazarsa o kadar çok sayılıyordu;
  ince ayarlı model daha sık yazdığı için gerileme gibi görünüyordu. Düzeltme (test önce):
  `run_eval` bölümü çıkarıp doğrular; eski kayıtlar için `metrics.shown_problems` aynı metni
  kaydın kendi kanıtı ve uygun etiketleriyle yeniden doğrular. Düzeltilmiş ölçütle r16, kontrol
  ve hazır model 0; r32'nin 4'ü bellekten değil (asgari kanıtı eksik etiket). Task 7 belgesi bu
  ölçütü raporlamamıştı.
- **Kontrol ile hazır model aynı değil:** aynı ağırlıklar, ama `bist-base-9b`'nin açıklama
  kabulü 13 puan düşük, desteksiz sayısı 18'e karşı 4 ve %60 fazla çağrı öneriyor. Farklar:
  hazır modelin Modelfile'ı `presence_penalty 1.5`, `top_k 20`, `top_p 0.95` taşıyor (sıcaklık
  0'da yalnız `presence_penalty` etkili); dışa aktarma yalnız şablonu ve `stop`'u alır (Task 8
  raporu, madde 4). Nicemleme karışımı da farklı (5,6 GB / 6,6 GB). İki modelin yetenekleri
  (`completion`, `tools`, `thinking`) aynı; `template_check` `bist-base-9b` ile de 40 / 40
  (`runs/template-check-bist-base-9b.json`, masaüstü). Asıl karşılaştırma bu yüzden ince ayarlı
  model ile `bist-base-9b` arasındadır; hazır model ikincil referanstır.
- n = 60 soru; iki tekrar birebir aynı (tekrarlanabilirlik 60 / 60), tekrarlar bağımsız örnek
  değil. Bir soru bir oranı yaklaşık 1,7 puan oynatır.

### 10.6 Geçit: Tailscale Serve uzak IPv4 bağlantısını reddediyor (20 Kasım)

Seçim koşusu beklenenin (≈ 50 dk) dört katı sürdü (04:25–08:01; kayıt başına gecikme medyanı
31–38 sn; Task 7'de hazır modelle 6,5 sn) ve r32'de 5 kayıt `LLMUnavailableError` ile bitti
(4 `ConnectError` kaydın başında, 1 `RemoteProtocolError` açıklama turunda). 08:01'den sonra
geçide hiç ulaşılamadı (TLS `internal_error`).

İnceleme:

- Ağ sağlam (`tailscale ping` doğrudan, 14 ms); ad masaüstünün Tailscale adresine çözülüyor;
  sertifika geçerli (`tailscale cert`: "unchanged"); `CertDomains` ve Serve ayarı
  (`TCP 443 HTTPS`, `Web <ad>:443 → / proxy http://127.0.0.1:11435`) doğru. Servisi yeniden
  başlatmak ve Serve'ü sıfırlayıp yeniden kurmak düzeltmedi.
- Masaüstünün Tailscale günlüğü (1.104.7): dizüstünden gelen her bağlantı için
  `TLS handshake error ...: no webserver configured for name/port`; aynı satırlar 05:44'te
  (r32'nin hataları) ve 08:01'den sonra.
- Masaüstünün kendinden testi (ad kendi IPv4 Tailscale adresine yönlendirilerek) `HTTP 200`.
- Dizüstünden doğrudan el sıkışma: **IPv4'te TLS 1.3 `internal_error`, TLS 1.2 zaman aşımı;
  IPv6'da TLS 1.3 ve 1.2 `HTTP 200`.** Windows'un çözücüsü bu ad için IPv6 adresi döndürmüyor,
  bu yüzden harness hep IPv4'ü kullanıyordu.

Sonuç: Serve, uzaktan gelen IPv4 bağlantısında ad/port eşleşmesini ara ara (gece) ve 08:01'den
sonra sürekli kaybediyor; IPv6 etkilenmiyor. Kök neden Tailscale'in içinde, bulunmadı.

Geçici çözüm (yalnız ölçüm koşucusu, kod değişmedi): ölçüm, geçidin adını çözümlerken
masaüstünün Tailscale IPv6 adresini kullanan küçük bir sarmalayıcıyla başlatılıyor
(`socket.getaddrinfo` yalnız bu ad için `AF_INET6`). Adres çalışma anında `tailscale ip -6`'dan
ortam değişkeniyle gelir, hiçbir dosyaya yazılmaz; TLS aynı adla (SNI ve sertifika doğrulaması
değişmeden) kurulur. Bu yolla aynı istek (`max_tokens` 200, sıcaklık 0) üç modelde de
≈ 74 token/sn, düşünme metni yok:

| Model | İlk istek (yükleme dahil) | İkinci istek |
| --- | --- | --- |
| hazır 9B | 14,0 sn | 2,1 sn |
| `bist-base-9b` | 9,3 sn | 1,4 sn |
| `bist-r16-e2` | 9,7 sn | 1,3 sn |

Gece 40–55 sn süren üç kayıt bu yoldan 12–21 sn sürdü ve aynı sonuçları verdi. Yani gecenin
yavaşlığı IPv4 yolundandı, modelden ya da dışa aktarmadan değil; sonuç etiketleri etkilenmedi
(bağlantı kopan 6 kayıt hariç, onlar yeniden koşuldu). Gecikme sütunları bu yüzden Task 7 ile
karşılaştırılamaz.
