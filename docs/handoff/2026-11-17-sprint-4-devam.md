# Sprint 4 devam notu (17 Kasım 2026, 15:07'de duraklatıldı)

Bu not, duraklatılan Sprint 4'ü yeni bir oturumda sürdürecek olan için. Önceki not
`docs/handoff/2026-11-17-sprint-4.md` hâlâ geçerli (kurallar, belgeler, ortam); bu not
ondan sonra olanları ve kaldığımız yeri anlatır.

## Nerede çalışılıyor

- Sprint 4 `main` üzerinde değil: worktree `C:\Users\burak\Projects\bist-harness\.worktrees\sprint-4`,
  dal `sprint-4-dev` (K-054). Kabuk komutları `cd /c/Users/burak/Projects/bist-harness/.worktrees/sprint-4 && ...`
  ile başlamalı. `main` yalnız `.gitignore` commit'iyle ilerledi (`5f688c2`).
- Veri tek yerde: worktree'nin `.env` dosyasındaki `BIST_DATA_DIR`, ana repodaki
  `data/` klasörünü gösteriyor. Hocanın betikleri worktree'ye de kopyalandı (git dışı).
- Yürütme defteri: `.superpowers/sdd/2026-11-19-sprint-4-mcp-ve-harness/progress.md`
  (worktree içinde, git dışı). Kararlar (`Ruling:`), ertelenen küçük bulgular ve her
  görevin commit aralığı orada. Önce onu oku. Sprint sonunda ana repoya
  `.superpowers/sdd/sprint-4/progress.md` olarak kopyalanacak.
- Plan dört eklemeyle onaylandı (K-053); yürütme karma: Task 0 ve Task 10 ana oturumda,
  Task 1–9 alt ajanlarla (görev başına uygulayıcı + inceleme).
- Son commit `718a3c5`; testler 842 geçiyor, ruff temiz.

## Task 0 (EC-014, EC-025, EC-012): kod bitti, veri ve tek çalıştırma kaldı

Bitenler (commit sırasıyla): ölçüm belgesi `docs/results/2026-11-17-fundamentals-source-measurement.md`
(K-048 ölçüldü, Burak (a) yolunu seçti, K-055); KAP rapor indiricisi ve ayrıştırıcısı;
TÜFE yayın tablosu ve kurun bir gün gecikmesi (K-056); yarım gün 12:30 (K-057);
`layers_id` ve `snapshot seal/verify` (K-058); Senaryo 1–3 koşucuları (K-062, keşif
dönemi denendi); KAP'tan temel katman kurulumu ve araç katmanı (K-059: karşılaştırmalı
sütun, TMS 29 saptaması, reel büyüme, tutarlı artış denetimleri); motorun bilgi tarihi
denetimi (K-061); ham kapanış katmanı ve değerleme (K-060, katman kuruldu: `prices_raw/`);
ön kayıt 6.1, veri kaynakları, veri sözlüğü.

Kalan adımlar, bu sırayla:

1. **KAP sayfalarını bitir.** Liste tamam (30 hisse, 534 bildirim, `data/cache/kap_reports/reports.parquet`);
   duraklatıldığında 534 sayfanın 76'sı inmişti. İndirme arka planda sürüyor olabilir;
   durduysa aynı komut kaldığı yerden sürer:
   `uv run python -m bist_harness.data.kap_reports download 15` → sonunda `failed: []` görülmeli.
   Sayfa başına 15–20 sn; kalan yaklaşık 2–2,5 saat.
2. **Katmanı kur:** `uv run python -m bist_harness.data.fundamentals build-kap`. Eski İş Yatırım
   katmanı `fundamentals_isyatirim/` adıyla kenara alınır.
3. **Ölçümle karşılaştır** (KAP'taki rakamlar): TUPRS 2024Q4 hasılat 810.385.588 bin TL
   (karşılaştırmalı 991.202.993); AKBNK 2024Q3 toplam aktif 2.404.289.929 bin TL (TP+YP);
   THYAO 2024Q3 hasılat 551.928 mn TL (birim milyon); MAVI 2024Q4 `period_end` 2025-01-31;
   hisse başına 16 dönem (MAVI 15); bankada ve sigortada konsolide rapor seçilmiş olmalı.
   Ayrıştırıcının görmediği bir şablon çıkarsa önce kalan test, sonra düzeltme.
4. `uv run pytest -q` ve `uv run ruff check .`; sonra
   `uv run python -m bist_harness.data.snapshot seal` ve `... snapshot verify` (temiz olmalı).
5. **Tek seferlik test dönemi çalıştırması (K-049, yalnız bir kez).** Task 1+ değişiklikleri
   karışmasın diye Task 0'ın son commit'inden ayrı bir kopya:
   `git worktree add --detach .worktrees/study-run <Task 0'ın son commit'i>`, `.env` dosyasını kopyala,
   `uv sync`, sonra o kopyada `uv run python -m bist_harness.backtest.study test`.
   Sonuç `runs/study-test-*.json`; `docs/results/<gün>-test-period.md` içine protokoldeki
   tanımlar değiştirilmeden yazılır (commit kimliği ve `layers_id` belgede).
   Yeniden çalıştırma yok; sorun çıkarsa ön kayıt sapma kuralı.
6. Defter: `Task 0: complete (...)`. Notion: EC-014, EC-025 (Sprint 4'e taşındı, 03 Yapılıyor)
   ve EC-012 kartları; merkez sayfadaki Sprint 4 bölümü.

## Task 1 (EC-040): tamam

`beb5650..718a3c5`: oturum kaydı (`harness/session.py`), kalan üç araç, ortak katı argüman
sarmalayıcısı, KAP üye kimliği koruması, NaN yerine `None`, özellik tablosu önbelleği.
İnceleme bir düzeltme turunda temizlendi. Notion EC-040: 04 İnceleme.

## Task 2 (EC-041): yarıda kaldı

Uygulayıcı alt ajan durduruldu. Commit'lenmemiş, yarım dosyalar worktree'de duruyor:
`tests/test_contracts.py`, `tests/golden_snapshot.py`, `tests/golden/` (30 dosya). Son notu:
sentetik anlık görüntü için makro serilerin (fx, policy_rate, fed_target) sütunlarını arıyordu.
Görev özeti `.superpowers/sdd/.../task-2-brief.md`. Devam ederken yeni bir uygulayıcıya özet,
bu üç dosyanın var olduğu ve gönderim notları (defterdeki "Task 2" satırları ve önceki
gönderimdeki dört madde: 15 araç kayıtlı, hata nesnesi yalnız `error`, temel veri yeni KAP
biçiminde, referans çıktılarda sürüm kimlikleri testte sabitlenir) verilir. Dosyaları
silmek ya da kullanmak uygulayıcının kararı olsun; silme işini kendiliğinden yapma.
Notion EC-041: 03 Yapılıyor.

## Sonra

Task 3–9 alt ajanlarla, Task 10 (canlı deneme) ana oturumda; sonra temiz bağlamlı
bütün dal incelemesi, tek düzeltme turu, `sprint-4` etiketi, `main`'e birleştirme (push
yalnız Burak isteyince), `docs/ai_usage_log.md`, Notion, Sprint 5 planı.

## Burak'ın vermesi gereken kararlar

- K-055'in kapsam kısmı: tam aralık (2022Q4–2026Q3) uygulandı, yanıtlanmadı.
- K-056 – K-062 (bu oturumda verilenler, "Bekliyor"). En önemlisi K-056: TÜFE yayın
  günleri resmî takvimden değil, BIST takvimine dayanan kuralla üretildi.
- Önceki listedeki diğerleri (`docs/decision-log.md` sonu).

## Bu oturumda öğrenilenler

- Windows'ta Python `write_text` satır sonlarını CRLF yazar: betikle dosya yazarken
  `newline="\n"` ver.
- Testler gerçek veri klasörünü okumamalı: araç testlerinde yükleyicileri yamala
  (ör. `load_raw` gerçek ham fiyat katmanı kurulunca iki testi bozmuştu).
- TÜİK veri portalı JavaScript uygulaması (bülten listesi otomatik alınamadı);
  Borsa İstanbul sitesi bağlantıyı kesiyor.
- KAP listesi hisse başına 1–4,5 dk sürdü (yeniden denemelerle); sayfalar 15–20 sn.
- Pyright'ın "import could not be resolved" uyarıları sanal ortamı görmediğinden; yok say.
