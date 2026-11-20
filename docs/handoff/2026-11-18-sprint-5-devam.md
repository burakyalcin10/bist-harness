# Sprint 5 devam notu (18 Kasım 2026 akşamı)

Bu not, 18 Kasım 2026 akşamından sonra Burak'ın yapacaklarını ve yeni sohbette ajanın yapacaklarını sıralar.

## Durum

- **Yer:**
  - Worktree: `C:\Users\burak\Projects\bist-harness\.worktrees\sprint-5`
  - Dal: `sprint-5-dev`, son commit `87ff0f6`. GitHub'a push'landı.
  - `main` ve etiketler değişmedi.
- **Yürütme:**
  - Plan: `docs/superpowers/plans/2026-11-18-sprint-5-ince-ayar.md`
  - Defter: `.superpowers/sdd/2026-11-18-sprint-5-ince-ayar/progress.md` (git dışı)
  - Yöntem: alt ajanlarla (superpowers subagent-driven-development); her görev bağımsız incelemeden geçer.
- **Biten görevler:** Task 1–8 ve controller'ın eklediği Task 8b. Her birinin incelemesi temiz.
  - Task 7, temel model ölçümü: `docs/results/2026-11-18-base-model-selection.md`.
  - Task 8, dizüstü denemesi: `docs/results/2026-11-18-finetune-training.md`.
  - Task 8b, 9B için bellek dostu yol ve dosya dosya birleştirme: aynı belgenin 9. bölümü.
- **Burak'ın kararı (18 Kasım 2026):** "sonuç olarak 9b daha iyiyse 9b yi dene".
  - Hedef temel model `Qwen/Qwen3.5-9B`, revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`.
  - Bellek denemesi geçmezse `qwen3.5:4b` kullanılır.
- **9B bellek tahmini:** tepe ayrılan bellek r16 için ~8,99 GB, r32 için ~9,29 GB; en kötü durumda ~9,6 GB. Kesin sonucu masaüstü denemesi verecek.
- **Testler:** 2.036 geçti, 3 atlandı. `ruff` temiz.
- **Masaüstü:**
  - Ollama 0.40.4, `C:\AI-Server\ollama` içinde; PATH'te değil.
  - Geçit yalnız `/v1/chat/completions` ve listeleme yollarını geçiriyor. Bu yüzden ölçümler `BIST_LLM_API=openai` ile yapılıyor.
  - Geçit adresi yalnız worktree'nin git dışı `.env` dosyasında. Adres hiçbir dosyaya yazılmaz.
- **Eğitim verisi paketi:** `runs/finetune-bundle-20261118-9b.zip`. Taildrop ile masaüstüne gönderildi; masaüstünde İndirilenler klasöründe olmalı.

## Burak'ın yapacakları (bu akşam ve sabah, masaüstünde)

Bütün komutlar `docs/finetune.md` içindeki "RTX 5070'te çalıştırma" bölümünde PowerShell olarak yazılı.

0. **Ollama'yı PATH'e ekle** (adım 0).
1. **Önkoşullar ve repo** (adım 1):
   - `git` ve `uv` denetimi.
   - `git clone` ile repoyu `C:\AI-Server\bist-harness` klasörüne indir. Yaklaşık 65 GB boş yer gerekir; yoksa başka sürücü seç.
   - `git checkout sprint-5-dev`, ardından `uv sync --group train`.
2. **Veri paketi** (adım 2): zip yolu `$env:USERPROFILE\Downloads\finetune-bundle-20261118-9b.zip`. Paketi geçici bir klasöre aç, yalnız `data\finetune` içeriğini kopyala.
3. **9B ağırlıkları** (adım 3): 19,3 GB, tek seferlik indirme.
4. **Bellek denemesi `trial-9b`** (adım 4): 20 adım.
5. **Karar kuralı** (adım 5):
   - `max_trained_tokens` 1475 değilse dur ve haber ver.
   - Ayrılan bellek 10,5 GB'yi aşarsa, rezerve bellek 11,5 GB'ye ulaşırsa ya da paylaşılan belleğe 1000 MB ve üstü taşma olursa 4B'ye geç. Adımlar belgede hazır.
6. **Gece koşuları** (adım 6). Denemede ölçülen adım başına süreye göre:

   | Adım başına süre | Bu gece |
   |---|---|
   | 50 sn ya da altı | r16 ve r32 |
   | 50–130 sn | yalnız r16 |
   | 130 sn üstü | başlatma, haber ver |

   Belge 20:00 başlangıcını varsayar; daha geç başlanırsa eşikler belgedeki formülle küçültülür.
7. **Sabah: dışa aktarma** (adım 7).
   - Ollama sürüm denetimi, llama.cpp dönüştürücüsünün 0.40.4'e sabitlenmesi, `template_check`, `ollama create`, yükleme testi.
   - `llama-server.exe` ya da `llama-quantize.exe` bulunmazsa veya `template_check` çalışmazsa dur ve haber ver.
8. **Sonuçları dizüstüne getir** (adım 8): her koşunun `adapter\`, `loss.csv` ve `run.json` dosyaları, denemenin günlüğü.
9. **Okuma:** `data\finetune\review-sample.md` içindeki 50 kaydı oku. EC-052'nin kabul ölçütü bu.

Denemede ya da koşularda hata çıkarsa şunları getir:
- günlüğün son 60 satırı (`runs\finetune-trial-9b.log`);
- `nvidia-smi` çıktısı;
- izleme penceresinin son satırları.

## Yeni sohbette ajanın yapacakları

1. **Önce oku:**
   - bu not;
   - defter `progress.md`: rulings, ertelenen 30 küçük bulgu, push kayıtları;
   - `docs/finetune.md`, adım 5–8.
2. **Burak'ın getirdiklerini oku:** denemenin ve koşuların `run.json` dosyaları.
   - Karar kuralını birlikte uygula.
   - Ölçülen tepe belleği, adım başına süreyi ve kayıpları `docs/results/2026-11-18-finetune-training.md` belgesine yeni bir bölüm olarak yaz. Belgeyi o günün tarihiyle güncelle; tarih yazmadan önce `date` ile bak.
   - Ölçülen bellek tahmini aşarsa nedenini incele (superpowers:systematic-debugging). Tahmin aracını gerçek ölçüme göre düzelt.
3. **Hangi koşu kullanılacak:** r16-e2 mi r32-e3 mü? Doğrulama kaybına ve geliştirme sorularındaki kısa bir ölçüme göre seç. Ruling olarak deftere yaz.
4. **Dışa aktarma** Burak'ta yapıldıysa ince ayarlı modelin Ollama'da göründüğünü geçitten `/api/tags` ile doğrula. Python urllib kullan; curl bir hook tarafından engelleniyor.
5. **Task 9, karşılaştırma ve kapanış (EC-055):** plandaki Task 9 metni geçerli.
   - **20 Kasım notu: bu madde K-086 ile değişti.** Asıl karşılaştırma ince ayarlı model ile aynı hattan çıkan `bist-base-9b` arasında (ikisi de `presence_penalty`'siz); `qwen3.5:9b-q4_K_M` ikincil referans.
   - Temel model `qwen3.5:9b-q4_K_M` ile ince ayarlı model, donmuş 120 soruda; deney D ve E, iki tekrar.
   - İki model de **aynı yoldan** (`BIST_LLM_API=openai`, geçit) ve aynı örnekleme ayarlarıyla koşmalı (Task 7 I3).
   - Dışa aktarılan modelin Modelfile'ı temel modelin `presence_penalty`, top_k/top_p ayarlarını taşımıyor (Task 8 notu). Karşılaştırmadan önce bunu eşitle ve belgeye yaz.
   - Sonuçlar `docs/results/<gün>-finetune-comparison.md` belgesine.
6. **Doğrulama:** `uv run pytest -q`, hem normal hem boş veri klasörüyle; `uv run ruff check .`.
7. **Bütün dal incelemesi:** en yetenekli modelle, superpowers final-review referansına göre. Tek düzeltme dalgası. Ertelenen küçük bulgular defterde; incelemeye o listeyi ver.
8. **Karar günlüğü, K-076'dan devam:**
   - Sprint 5 planının onayı.
   - R1–R5 rulingleri.
   - Task 1–8b rulingleri:
     - FUNDAMENTAL_REACTION'da tarih eşiği, aralığın başlangıcına değil sonuna bakar;
     - Task 8'i Task 7'den önce koşma;
     - üç adayı aynı makinede ölçme;
     - 8b'yi Task 7'nin yeniden incelemesiyle paralel başlatma;
     - 9B'yi dosya dosya birleştirme;
     - küçük bulguların düzeltme turuna alınması.
   - Burak'ın 9B kararı.
   - OpenAI yolu (`BIST_LLM_API`).
   - Task 4 ve 5'teki test-önce ihlalleri (K-063 ile birlikte).
9. **`docs/ai_usage_log.md`:** 17–18 Kasım satırları.
   - Controller ve alt ajanlar.
   - Model indirmeleri: masaüstüne `qwen3.5:2b` ve `4b`, Hugging Face'ten 0.8B ve 9B.
   - Eğitim koşuları.
10. **Notion güncellemeleri:**
    - kartlar: "QLoRA eğitimi", "Yerel model fizibilitesi ve temel model seçimi", "Eğitim ortamı: uzak RTX 5070'te deneme koşusu" (EC-006);
    - Sprint 5'in durumu;
    - EC-052 hâlâ Burak'ın 50 kaydı okumasını bekliyor.
11. **Kapanış:** `git tag sprint-5`, `main`'e birleştirme ve push **yalnız Burak isterse**. Sonra Sprint 6 planı:
    - harness deneyleri A–E iki modelle;
    - senaryo raporları;
    - weight-space programming yan deneyi (EC-057);
    - K-075'te ertelenenler.

## Unutulmayacaklar

- **Uzak makine:** bulut yapay zekâ çağrısı yok. Uzak makinenin adresi, tailnet adı ve IP'leri hiçbir dosyaya, commit'e, Notion'a ya da günlüğe yazılmaz.
- **Test dönemi:** bir kez çalıştırıldı (K-064), yeniden çalıştırılmaz. Donmuş 120 soru yalnız Task 9'da kullanılır.
- **Push:** Burak istemeden yapılmaz.
- **Kapsam ve hoca:** kapsam kısaltılmaz. Hocaya soruyu Burak kendisi soruyor (weight-space programming). Cevap gelirse karar günlüğüne yazılır ve Sprint 6 planına yansıtılır.
- **Saat:** masaüstü ve dizüstü Türkiye saatiyle (UTC+3) çalışır. Tarih yazmadan önce `date` ile bak.
