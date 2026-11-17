# Sprint 4 devam notu (17 Kasım 2026, 22:13'te ikinci kez duraklatıldı)

Bu not, duraklatılan Sprint 4'ü yeni bir oturumda sürdürecek olan için. İlk not
`docs/handoff/2026-11-17-sprint-4.md` hâlâ geçerli (kurallar, belgeler, ortam).

## Nerede çalışılıyor

- Worktree `C:\Users\burak\Projects\bist-harness\.worktrees\sprint-4`, dal `sprint-4-dev`
  (K-054). Kabuk komutları `cd /c/Users/burak/Projects/bist-harness/.worktrees/sprint-4 && ...`
  ile başlar. `main` yalnız `.gitignore` commit'iyle ilerledi (`5f688c2`); push yapılmadı.
- Veri ortak: worktree `.env` dosyasındaki `BIST_DATA_DIR` ana repodaki `data/` klasörünü
  gösterir. Uzak model adresi hiçbir dosyada yok; dizüstündeki Ollama varsayılan.
- Yürütme defteri: `.superpowers/sdd/2026-11-19-sprint-4-mcp-ve-harness/progress.md`
  (worktree içinde, git dışı). Her görevin commit aralığı, bütün `Ruling:` satırları ve
  ertelenen küçük bulgular orada; önce onu oku.
- Son commit `aca1523`; 1631 test geçiyor, ruff temiz.
- Yürütme karma: Task 0 ve 10 ana oturumda, Task 1–9 alt ajanlarla (her görevde
  uygulayıcı, inceleme, gerekirse düzeltme turu). Şablonlar ve betikler superpowers
  `subagent-driven-development` skill'inde.

## Durum

- **Task 0 tamam.** Temel veri katmanı KAP rapor sayfalarından kuruldu ve doğrulandı
  (534 sayfa, 30 hisse, 479 dönem), anlık görüntü mühürlü (`layers_id` `21b3a428`).
  **Test dönemi bir kez çalıştırıldı** (commit `beb5650`, ayrı kopya
  `.worktrees/study-run`); sonuçlar `docs/results/2026-11-17-test-period.md`, kayıt
  K-064. Yeniden çalıştırılmaz.
- **Task 1–9 tamam**, her biri bağımsız incelemeden geçti (ayrıntı defterde). Soru seti
  donduruldu (K-065, SHA-256 testte sabit).
- **Task 10 sürüyor.** Canlı deneme (`qwen3.5:2b`, dizüstü, deney E, SL-01, CP-01, TR-01,
  FR-01, TP-01, TP-02; kayıtlar `runs/eval-20261117T185317Z/`): tuzaklar doğru
  (`REFUSED_ADVICE`, sıfır araç), dört analiz sorusu START'ta `UNKNOWN_SECTOR` ile
  düştü. Kök neden: ince ayarsız model niyette soruda olmayan hisse, sektör ve tarih
  uyduruyordu; harness uydurma sektörde duruyor, uydurma `as_of`'tan varsayılan dönem
  kuruyordu. Düzeltme (`aca1523`, test önce): niyet alanları sorunun metnine karşı
  temellendiriliyor, uydurulan alanlar kayda geçiyor. **Bu düzeltme henüz incelenmedi.**

## Kalan adımlar, bu sırayla

1. `aca1523` için kapsamlı inceleme (`review-package` 546e16e..aca1523; inceleyici en
   yetenekli model). Uygulayıcı raporu:
   `.superpowers/sdd/.../task-10-intent-fix-report.md`. Notları: `check_intent`'e yeni
   kural (ticker ve sektör yoksa SECTOR_LAGGARD → UNKNOWN_SECTOR); deney A ham niyeti
   korur; bazı eski test fikstürleri sorularında geçmeyen hisse/tarih kullanıyordu ve
   güncellendi; "son 20 işlem günü" gibi göreli dönemler tarih sayılmıyor.
2. Ollama açık değilse `ollama serve` (dizüstü). Canlı denemeyi tekrarla:
   `uv run python -m bist_harness.eval.run_eval --experiments E --ids SL-01,CP-01,TR-01,FR-01,TP-01,TP-02 --model qwen3.5:2b`.
   RTX 5070 açılırsa seçilen modelle de. Sonuç `docs/results/<gün>-harness-live.md`
   (iki denemeyi de, düzeltmeden önce ve sonra, yaz).
3. Bütün dal incelemesi (`review-package` merge-base..HEAD; `requesting-code-review`
   şablonu, en yetenekli model; defterdeki ertelenmiş küçük bulgular ve tuzak listeleri
   verilir), tek düzeltme dalgası, tek yeniden inceleme.
4. `docs/ai_usage_log.md`, karar günlüğü (K-066'dan devam), `sprint-4` etiketi, `main`'e
   birleştirme (push yalnız Burak isteyince), defteri ana repoya
   `.superpowers/sdd/sprint-4/progress.md` olarak kopyala, `.worktrees/study-run`'ı kaldır,
   Notion kartları (EC-040…060), Sprint 5 planı (ince ayar verisi harness kayıtlarından;
   soru setinin 120 sorusu dışarıda kalır, `questions.overlaps()`).

## Burak'ın vermesi gereken kararlar

- K-055 kapsamı ve K-056 – K-065 ("Bekliyor"). En önemlileri: K-056 (TÜFE yayın günleri
  kuralla), K-063 (Task 3'te test-önce ihlali), K-064 (test dönemi sonucu).
- Defterdeki `Ruling:` satırları (Task 0–10), özellikle niyetin soruya temellendirilmesi.

## Öğrenilenler

- Ollama tepsi uygulaması açıkken sunucu dinlemeyebilir; `ollama serve` gerekir.
- İnce ayarsız küçük model niyet JSON'unda alan uyduruyor; harness her alanı soruya
  karşı denetlemeli. Sprint 5 verisi için "uydurulan alan" sayısı artık kayıtta.
- Testler gerçek veri klasörünü okumamalı; Windows'ta Python ile dosya yazarken
  `newline="\n"`; KAP istekleri yavaş (sayfa başına 15–20 sn).
