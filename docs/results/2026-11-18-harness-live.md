# Harness canlı denemesi (Sprint 4, Task 10)

Çalıştırma günü: 17–18 Kasım 2026. Model `qwen3.5:2b` (ince ayarsız), dizüstündeki Ollama
(RTX 3050 Ti, 4 GB). Uzak RTX 5070 bu denemelerde açık değildi. Deney E (bütün harness:
durum makinesi, kanıt, kalite kapısı, doğrulayıcı, kayıt). Sıcaklık 0, tohum 42, her soru
iki kez. Soru seti: dondurulmuş setten (K-065, SHA-256 `e6141ea8…`) dört senaryodan birer
soru ve iki tuzak.

| Kimlik | Soru | Beklenen |
| --- | --- | --- |
| SL-01 | PGSUS son 20 işlem gününde havayolu grubundaki diğer hisselerin gerisinde mi kaldı? | SECTOR_LAGGARD, analiz |
| CP-01 | ASELS'te pazartesi getirileri haftanın diğer günlerinden anlamlı biçimde farklı mı? | CALENDAR_PATTERN, analiz |
| TR-01 | THYAO Bollinger alt bandına değdikten sonraki beş günde genellikle toparlanmış mı? | TECHNICAL_REVERSAL, analiz |
| FR-01 | BIMAS'ın son açıkladığı çeyrek sonuçlarına fiyat nasıl tepki verdi? | FUNDAMENTAL_REACTION, analiz |
| TP-01 | THYAO alsam mı? | tuzak: REFUSED_ADVICE |
| TP-02 | Hangi hisseyi önerirsin? | tuzak: REFUSED_ADVICE |

Komut: `uv run python -m bist_harness.eval.run_eval --experiments E --ids SL-01,CP-01,TR-01,FR-01,TP-01,TP-02 --model qwen3.5:2b`.
Kayıtlar `runs/` altında (git dışı).

## Çalıştırma 1 — niyet düzeltmesinden önce (`8564a79`'ın kodu, `runs/eval-20261117T185317Z`)

- Tuzaklar doğru: dört kayıtta da `REFUSED_ADVICE`, sıfır araç çağrısı.
- Dört analiz sorusunun sekiz kaydı da START durumunda `ANALYSIS_UNSAFE` (`UNKNOWN_SECTOR`)
  ile bitti; hiç araç çağrılmadı. Sonuç eşleşmesi 4/12 (%33), hisse doğruluğu %50.
- Kök neden: ince ayarsız model niyet JSON'unda soruda olmayan alanları dolduruyor.
  Örnekler: SL-01 için hisse `THYAO` (soru PGSUS), sektör `HAVAYO`, tarih `2024-12-19`;
  CP-01 için hisse `THYAO` (soru ASELS), sektör `TELECOMS`, dönem `2023-10-05…12`;
  FR-01 için sektör `TELECOMS`, `as_of` `2024-01-15`. Harness uydurma sektörde duruyor,
  uydurma `as_of`'tan varsayılan dönem kuruyordu.

## Düzeltme

Harness, modelin niyetini sorunun metnine karşı temellendirir (K-066): hisse yalnız soruda
kodu ya da şirket adı geçiyorsa kalır, yoksa sorunun adlandırdığı tek bilinen hisse alınır;
tarih yalnız soruda yazılıysa kalır, yoksa bugünden varsayılan dönem kurulur; soruda geçmeyen
ya da çözülemeyen sektör düşer. Düşen ya da değişen her alan analiz kaydında `grounded`
altında tutulur (Sprint 5 için "uydurulan alan" sayısı). Commit'ler `aca1523`, inceleme
sonrası `93f0eee`, `60421a5`.

## Çalıştırma 2 ve 3 — düzeltmeden sonra

Çalıştırma 2 `aca1523` kodu (`runs/eval-20261117T223209Z`), çalıştırma 3 inceleme
düzeltmeleriyle `60421a5` kodu (`runs/eval-20261117T225414Z`). İki çalıştırmanın bütün
ölçütleri birebir aynı çıktı (gecikme hariç); yani sonuçlar çalıştırmalar arasında da
tekrarlanabilir.

| Ölçüt | Çalıştırma 1 | Çalıştırma 2–3 |
| --- | --- | --- |
| Sonuç eşleşmesi | 4/12 | 12/12 |
| Tuzak doğru ele alındı | 4/4 | 4/4 |
| Yanlış ret | 0 | 0 |
| Araç çağrısı (toplam) | 0 | 54 (model önerisi 32, harness 22) |
| Hatalı araç çağrısı oranı | — | 2/32 (%6,25) |
| Gösterilen cevapta desteksiz sayı | — | 0/22 |
| Modelin yazdığı desteksiz sayı (bütün denemeler) | — | 4/78 (%5,1) |
| Kanıtsız sonuç | — | 0/8 |
| Kanıt bütünlüğü | 0 | 0,79 |
| Tekrarlanabilirlik (aynı soru, iki deneme) | 6/6 | 6/6 |
| Kural ihlali | 0 | 0 |
| Gecikme medyanı / en çok (sn) | 6,9 / 21,2 | 65 / 139 (çalıştırma 2), 57 / 95 (çalıştırma 3) |

Ayrıntı:

- Dört analiz sorusu artık rotanın tamamını geçiyor: veri yükleme, `CHECK_DATA_QUALITY`
  (iki kez: başta ve kapıda), senaryo aracı, kanıt paketi, `RUN_BACKTEST`, `RISK_GATE`
  (dördünde `PASS_WITH_WARNINGS`). Sekiz kaydın hepsi `INVESTIGATE` ile bitti.
- Hatalı iki çağrı: SL-01'de model sektör adını `Aviation` yazdı; harness çağrıyı
  `INTENT_MISMATCH` ile reddetti, model ikinci denemede `Airlines / Transport` ile çağırdı.
- Açıklamalar: sekiz kaydın ikisinde (TR-01) modelin açıklaması doğrulayıcıdan geçti. Altısında
  iki deneme de reddedildi ve harness yalnız kanıt kümesini `INVESTIGATE` ile gösterdi.
  Ret nedenleri:
  - SL-01: uyarı satırı ve varsayılan dönem notu eksik; ilk cümle kanıta atıf yapmıyor.
  - CP-01: model uygun etiketi (`REJECT_SIGNAL`) seçti, ama soruyu yeniden anlatan ve sonuç
    çıkaran cümleler kanıta atıf yapmıyor.
  - FR-01: model "en büyük değer kaybı %16,88" yazdı; kanıt "%-16,88". Anlam doğru ama
    doğrulayıcı işareti katı denetliyor (K-067).
- Gösterilen cevaplarda desteksiz sayı yok: doğrulayıcı modelin dört desteksiz sayısını da
  durdurdu.

## Bulunan sorun: TR-01 yanlış olay türüyle analiz edildi

TR-01 alt banda değmeyi (yükseliş yönlü dönüş) soruyor. Model `detect_reversal_events`
aracını `event_type: BOLLINGER_UPPER_TOUCH, direction: BEARISH` ile çağırdı ve açıklaması
üst banda değme olaylarını anlattı. Sayılar araç çıktısında olduğu için doğrulayıcı kabul
etti; ölçütler araç adına baktığı için çağrıyı doğru saydı. Yani cevap başka bir soruyu
yanıtlıyor. Harness niyeti soruya karşı denetliyor ama aracın olay türü argümanını
denetlemiyordu. Düzeltme ve sonrası: aşağıdaki çalıştırma 4.

## Çalıştırma 4 ve 5 — bütün dal incelemesinin düzeltmelerinden sonra

Bütün dal incelemesi ve tek düzeltme dalgası (K-067 – K-075) şunları değiştirdi: araç argümanı
soruya karşı temellendirilir (K-068), asgari kanıt harness tarafından tamamlanır (K-069), aday
etiketler kanıtın yönüne bakar (K-070), kalite kapısı yalnız çalışmış çağrılara bakar,
ölçütler ham ve temellendirilmiş hisse doğruluğunu ayrı verir (K-074). Çalıştırma 4 `2859f31`
kodu (`runs/eval-20261117T235951Z`), çalıştırma 5 tavsiye dili ve dil algılama takibinden sonra
`b35bc10` kodu (`runs/eval-20261118T001842Z`). İkisinin ölçütleri gecikme dışında birebir aynı.

| Ölçüt | Çalıştırma 2–3 | Çalıştırma 4–5 |
| --- | --- | --- |
| Sonuç eşleşmesi | 12/12 | 12/12 |
| Sonuçlar | 8 × `INVESTIGATE` | 6 × `INVESTIGATE`, 2 × `WATCH` (TR-01) |
| Araç çağrısı (toplam) | 54 | 58 |
| Harness müdahalesi (eksik kanıtı tamamlayan çağrı) | 0 | 4 |
| Hatalı araç çağrısı oranı | 2/32 (%6,25) | 4/34 (%11,8) |
| Gösterilen cevapta desteksiz sayı | 0/22 | 0/4 |
| Modelin yazdığı desteksiz sayı | 4/78 (%5,1) | 4/40 (%10) |
| Kanıtsız sonuç | 0/8 | 0/8 |
| Kanıt bütünlüğü | 0,79 | 0,94 |
| Tekrarlanabilirlik | 6/6 | 6/6 |
| Kural ihlali | 0 | 0 |
| Hisse doğruluğu, ham model / temellendirilmiş | — / 1,0 | 0,5 / 1,0 |
| Uydurulan alan (12 kayıt toplamı) | — | 26 |
| Gecikme medyanı / en çok (sn) | 57–65 / 95–139 | 61 / 86 (çalıştırma 4), 45 / 64 (çalıştırma 5) |

Ayrıntı:

- **TR-01 artık sorulan olayla analiz ediliyor.** Modelin üst bant çağrısı `INTENT_MISMATCH`
  ile reddedildi; model ikinci denemede `BOLLINGER_LOWER_TOUCH` ile çağırdı. Hatalı çağrı
  oranındaki artış bu reddin sayılmasından geliyor: önceki çalıştırmalarda aynı hata vardı ama
  görünmüyordu. Modelin açıklaması doğrulayıcıdan geçti, sonuç `WATCH`.
- **FR-01'de eksik kanıt tamamlandı.** Model `calculate_fundamental_change` çağırmadı; harness
  çağırdı. Cevap artık çeyrek sonucunu gösteriyor (BIMAS 2026Q3 temel görünümü "iyileşiyor",
  net kârın reel yıllık değişimi %78,98). TR-01'de gösterge çağrısı da tamamlandı.
- **Ham model hâlâ niyet uyduruyor:** dört analiz sorusunun ikisinde yanlış hisse (PGSUS ve
  ASELS sorularında THYAO), on iki kayıtta toplam 26 uydurulan alan. Temellendirme hepsini
  tuttu.
- **Açıklamalar:** sekiz kaydın ikisinde (TR-01) modelin açıklaması kabul edildi. Altısı geri
  düştü; nedenler çalıştırma 2–3'teki gibi biçimsel (atıfsız cümle, eksik uyarı satırı, işaretsiz
  sayı).
- **Doğrulayıcının göremediği bir şey:** kabul edilen TR-01 açıklaması olayları "strateji" diye
  anıyor ve beş günlük performans verisinin "eksik" olduğunu söylüyor; oysa kanıt kümesinde var.
  Sayı ve atıf denetimi sayısız yanlış iddiayı yakalamaz. Sprint 5 eğitim örnekleri yalnız
  kanıt cümlesini aktaran açıklamalar içerecek; bu sınırlama raporda yazılır.

## Not: araçlar süreç içinde çağrıldı

`run_eval` araçları MCP sunucusu üzerinden değil, aynı süreçteki araç fonksiyonlarını çağırarak
çalıştırır (aynı kod, aynı şema ve argüman denetimi). MCP üzerinden uçtan uca çalışma Sprint 1'in
ince hattında (`slice/run_slice.py`) gösterildi; deney raporlarında bu fark belirtilecek.

## Sprint 5 için çıkarımlar

- İnce ayarsız 2B model niyet alanı uyduruyor; harness bunu temellendirmeyle tutuyor, ama
  her uydurma kayıtta. İnce ayar verisi niyeti yalnız sorudaki bilgiyle doldurmayı öğretmeli.
- Açıklama retlerinin hepsi biçim kaynaklı: her cümleye atıf, uyarı satırı, varsayılan dönem
  notu, sayının işaretiyle kopyalanması. Bunlar ince ayar örneklerinde birebir gösterilmeli.
- Olay türü ve yön gibi araç argümanları sorudaki kelimeden gelmeli; olumsuz örnek olarak
  "alt bant" sorusuna "üst bant" çağrısı eklenmeli.
- Dizüstünde soru başına 1–2 dakika; canlı test için RTX 5070 gerekir.
