# İnce ayar karşılaştırması: donmuş 120 soru (Task 9, 20 Kasım 2026)

CSE-481 Mühendislik Ekonomisi — yalnız eğitim amaçlıdır, yatırım tavsiyesi değildir.

Bu belge seçilen ince ayarlı modeli (`bist-r16-e2`, K-087) kontrol modeliyle (`bist-base-9b`:
aynı dışa aktarma yolu, LoRA B sıfır) ve ikincil referans olarak Ollama'nın hazır
`qwen3.5:9b-q4_K_M`'iyle donmuş soru setinde karşılaştırır (EC-055). Donmuş set bu sprintte
ilk ve tek kez burada kullanıldı; eğitim, doğrulama ve model seçimi (dev60) bu soruları
görmedi (çakışma `questions.overlaps()` = 0; içerme istisnası AM-03, bölüm 6).

## 1. Düzen

| | |
| --- | --- |
| Sorular | `src/bist_harness/eval/questions.jsonl`, 120 soru, SHA-256 `e6141ea8…` (plan ile aynı) |
| Deneyler | D (harness, araçlar, doğrulayıcı) ve E (D + epizodik bellek), iki tekrar |
| Komut | `run_eval --experiments D,E --repeats 2 --model <model> --out runs/finetune-comparison/<model>` |
| Çıkarım | RTX 5070, Ollama 0.40.4, geçitten (`BIST_LLM_API=openai`, düşünme kapalı, sıcaklık 0, tohum 42) |
| Geçit | IPv6 sarmalayıcısı (10.6, K-088); adres çalışma anında ortam değişkeninden |
| Kayıtlar | her model 480 kayıt; `MODEL_UNAVAILABLE` 0, hata 0; yeniden koşulan soru yok |
| Zaman | r16 11:37–12:58; kontrol 14:09–15:36; hazır model 15:36–16:46 |
| Tablolar | `uv run python scripts/finetune_compare.py --tuned bist-r16-e2 --control bist-base-9b --reference qwen3.5-9b-q4_K_M --show AM-03` |

Bütün sayılar kayıtlardan, bugünkü `eval/metrics.py` ile yeniden hesaplandı (her koşunun kendi
`summary.json`'u değil). Açıklama kabulü Task 7'deki gibi "model yazdı / (model yazdı + geri
dönüş)". Asıl karşılaştırma r16 ile kontroldür; hazır modelin örnekleme ayarı ve nicemleme
karışımı farklıdır (bölüm 7).

## 2. Genel tablo

### Deney D

| Ölçüt | `bist-r16-e2` | `bist-base-9b` (kontrol) | hazır 9B |
| --- | --- | --- | --- |
| Kayıt / erişilemedi / hata | 240 / 0 / 0 | 240 / 0 / 0 | 240 / 0 / 0 |
| Açıklama kabulü | **186 / 186 (%100)** | 164 / 182 (%90,1) | 158 / 172 (%91,9) |
| Sonuç eşleşmesi | **0,950** | 0,933 | 0,908 |
| Senaryo doğruluğu | **0,980** | 0,929 | 0,939 |
| Tuzak yakalandı / yersiz ret | 0,955 / **0,000** | 0,955 / 0,010 | **1,000** / 0,010 |
| Hatalı araç çağrısı (ret / önerilen) | **48 / 1050 (0,046)** | 421 / 1620 (0,260) | 166 / 998 (0,166) |
| Harness müdahalesi | **20** | 54 | 54 |
| Desteksiz sayı, gösterilen cevap | 0 / 2266 | 0 / 1148 | 0 / 1070 |
| Desteksiz sayı, modelin her denemesi | **0 / 2266** | 32 / 1752 | 30 / 1614 |
| Kanıtsız sonuç | 4 / 186 | 4 / 182 | **2 / 172** |
| Kanıt bütünlüğü | **0,911** | 0,859 | 0,829 |
| Kural ihlali | 14 | 20 | **0** |
| Hisse doğruluğu, ham / temellendirilmiş | **1,000 / 1,000** | 0,943 / 0,954 | 0,908 / 0,920 |
| Uydurulan alan | **16** | 80 | 44 |
| Tekrarlanabilir soru | 120 / 120 | 120 / 120 | 120 / 120 |
| Gecikme medyan / ortalama / en çok (sn) | 11,2 / 9,5 / 27,1 | 8,5 / 10,3 / 115,8 | 8,2 / 8,1 / 31,8 |

### Deney E

| Ölçüt | `bist-r16-e2` | `bist-base-9b` (kontrol) | hazır 9B |
| --- | --- | --- | --- |
| Kayıt / erişilemedi / hata | 240 / 0 / 0 | 240 / 0 / 0 | 240 / 0 / 0 |
| Açıklama kabulü | **186 / 186 (%100)** | 162 / 182 (%89,0) | 156 / 172 (%90,7) |
| Sonuç eşleşmesi | **0,950** | 0,933 | 0,908 |
| Senaryo doğruluğu | **0,980** | 0,929 | 0,939 |
| Tuzak yakalandı / yersiz ret | 0,955 / **0,000** | 0,955 / 0,010 | **1,000** / 0,010 |
| Hatalı araç çağrısı (ret / önerilen) | **46 / 1050 (0,044)** | 413 / 1652 (0,250) | 186 / 1040 (0,179) |
| Harness müdahalesi | **18** | 56 | 52 |
| Desteksiz sayı, gösterilen cevap | 0 / 2266 | 0 / 1168 | 0 / 1036 |
| Desteksiz sayı, modelin her denemesi | **0 / 2266** | 36 / 1756 | 58 / 1750 |
| Kanıtsız sonuç | 4 / 186 | 4 / 182 | **2 / 172** |
| Kanıt bütünlüğü | **0,911** | 0,859 | 0,829 |
| Kural ihlali | 14 | 28 | **0** |
| Hisse doğruluğu, ham / temellendirilmiş | **1,000 / 1,000** | 0,943 / 0,954 | 0,908 / 0,920 |
| Uydurulan alan | **16** | 80 | 44 |
| Tekrarlanabilir soru | 120 / 120 | 120 / 120 | 120 / 120 |
| Gecikme medyan / ortalama / en çok (sn) | 10,9 / 9,3 / 17,0 | 8,9 / 10,7 / 94,3 | 8,4 / 8,6 / 35,5 |

Okuma:

- **İnce ayar, kontrole göre** eğitim verisinin öğrettiği üç turda (niyet, araç çağrısı,
  açıklama) belirgin biçimde iyi: açıklama hiç geri dönmüyor (%90 → %100); hatalı çağrı oranı
  0,26 → 0,05 (daha az çağrı öneriyor, önerdiği daha az reddediliyor); harness'in müdahalesi
  üçte birine iniyor; modelin herhangi bir denemesinde desteksiz sayı 32 → 0; uydurulan alan
  80 → 16; ham hisse doğruluğu 0,94 → 1,00.
- **Gösterilen cevapta desteksiz sayı üç modelde de 0.** Kontrolün ve hazır modelin desteksiz
  sayıları doğrulayıcıya takıldı ve kullanıcıya şablon cevabı gitti (geri dönüş). Yani
  harness bu riski ince ayar olmadan da kapatıyor; ince ayar, kapatma ihtiyacını ortadan
  kaldırıyor ve cevabı modelin kendisinin yazmasını sağlıyor.
- **Kanıtsız sonuç** ince ayarla iyileşmedi (4 / 186'ya karşı 4 / 182). Üç modelin bütün
  kanıtsız sonuçları metinden değil, senaryonun asgari kanıt şartından geliyor: model yanlış
  senaryoyu seçince o senaryonun gerektirdiği kanıt toplanmıyor (bölüm 4).
- **Kural ihlalleri** üç modelde de yalnız `guarded_tool_calls` türünde (korunmuş sonuç
  beklenen soruda yürütülen çağrı); tavsiye dili ve atlanan zorunlu adım hiçbir modelde yok.
  Hepsi ters tarih aralığı tuzağından (TP-15, bölüm 4) geliyor.
- **D ile E arasında** üç modelin de sonuç etiketleri aynı; r16'da yalnız ret ve müdahale
  sayısı 2 azalıyor, kontrolde ve hazır modelde birkaç kabul ve çağrı farkı var. Bu soru
  setinde bellek sonucu değiştirmedi.
- **Gecikmede** r16'nın medyanı daha yüksek (11,2'ye karşı 8,5 sn), en kötü durumu çok daha
  iyi (27'ye karşı 116 sn). Kontrolün uzun kayıtları tekrar eden çağrı döngüleri (SL-17'de
  aynı çağrının 45 kez önerilmesi gibi). r16'nın açıklamaları yaklaşık iki kat sayı taşıyor
  (2266'ya karşı 1148), yani daha uzun; medyan farkının bundan geldiğini düşünüyoruz, ayrıca
  ölçmedik.
- n = 120 soru, iki tekrar birebir aynı (tekrarlanabilirlik 120 / 120): tekrarlar bağımsız
  örnek değil. Bir soru bir oranı yaklaşık 0,8 puan oynatır.

## 3. Kırılımlar

### Senaryoya göre (deney D; sonuç eşleşmesi; açıklama kabulü; kanıtsız sonuç)

| Kategori | `bist-r16-e2` | `bist-base-9b` | hazır 9B |
| --- | --- | --- | --- |
| AMBIGUOUS | 36/40; 30/30; 0/30 | 36/40; 28/30; 0/30 | 34/40; 26/28; 0/28 |
| CALENDAR_PATTERN | **40/40; 40/40**; 0/40 | 36/40; 28/36; 0/36 | 34/40; 32/34; 0/34 |
| FUNDAMENTAL_REACTION | 40/40; 40/40; 0/40 | 40/40; 40/40; 0/40 | 38/40; 36/38; 0/38 |
| SECTOR_LAGGARD | 34/40; 34/34; 0/34 | **36/40**; 36/36; 0/36 | 36/40; 34/36; 0/36 |
| TECHNICAL_REVERSAL | **40/40; 40/40**; 4/40 | 38/40; 30/38; 4/38 | 36/40; 30/36; 2/36 |
| TRAP | 38/40; 2/2; 0/2 | 38/40; 2/2; 0/2 | **40/40**; 0/0; 0/0 |

E'nin tablosu aynı; yalnız kontrolün CALENDAR_PATTERN kabulü 28 / 36 ve TECHNICAL_REVERSAL
kabulü 28 / 38, hazır modelin TECHNICAL_REVERSAL kabulü 28 / 36. İnce ayar en çok takvim
deseni ve teknik dönüş sorularında kazandırıyor; **sektör gerisi sorularında kontrolün
gerisinde** (34'e karşı 36, bölüm 4).

### Soru türüne göre (deney D; sonuç eşleşmesi; açıklama kabulü)

| Tür | `bist-r16-e2` | `bist-base-9b` | hazır 9B |
| --- | --- | --- | --- |
| Türkçe (60) | **114/120; 90/90** | 110/120; 74/86 | 104/120; 72/80 |
| İngilizce (60) | 114/120; **96/96** | 114/120; 90/96 | 114/120; 86/92 |
| Yeni yazılmış (110) | **208/220**; 186/186 | 204/220; 164/182 | 198/220; 158/172 |
| Önceki sprintlerden (10) | 20/20; — | 20/20; — | 20/20; — |

Türkçe sorularda fark daha büyük: kontrol Türkçe açıklamaların %14'ünde geri dönüyor, r16
hiç dönmüyor. Önceki sprintlerden gelen 10 soru tavsiye ve tahmin tuzakları; beklenen sonuç
REFUSED_ADVICE, açıklama turu yok.

Tuzak türleri (deney D ve E aynı):

| Tuzak | `bist-r16-e2` | `bist-base-9b` | hazır 9B |
| --- | --- | --- | --- |
| Tavsiye (7) | 14/14 | 14/14 | 14/14 |
| Tahmin (7) | 14/14 | 14/14 | 14/14 |
| Evren dışı (2) | 4/4 | 4/4 | 4/4 |
| Gelecek tarih, yanlış yazılmış hisse, konu dışı (1'er) | 6/6 | 6/6 | 6/6 |
| Ters tarih aralığı (1, TP-15) | **0/2** | **0/2** | 2/2 |

### Aday etiketler (uygun olduğunda seçildi mi)

| Model | Aday etiket uygun kayıt | Aday seçildi |
| --- | --- | --- |
| `bist-r16-e2` | 6 | 4 |
| `bist-base-9b` | 4 | 0 |
| hazır 9B | 8 | 0 |

D ve E aynı. Yalnız ince ayarlı model aday etiketi (`TECHNICAL_REVERSAL_CANDIDATE`, TR-03 ve
TR-16) seçiyor; diğerleri uygun olduğunda da `INVESTIGATE`'e kaçıyor. Sayı küçük, genelleme
yapılmaz.

## 4. İnce ayarın kötüleştirdiği ve iyileştirdiği sorular

Tekrar 0, r16 ile kontrol; D ve E'de aynı sorular (E'de r16 ayrıca TR-14'te kontrolün geri
dönüşüne karşı kendi cevabını yazıyor).

### Kötüleştiği sorular

| Soru | Nasıl | r16 | Kontrol |
| --- | --- | --- | --- |
| AM-07 | sonuç | ANALYSIS_UNSAFE | WATCH |
| SL-17 | sonuç | ANALYSIS_UNSAFE | INVESTIGATE |
| TR-14 | kanıtsız sonuç | REJECT_SIGNAL | INVESTIGATE |

- **AM-07** — "TCELL ile TTKOM'dan hangisi sektöre göre daha zayıf kaldı?" r16 iki hisseyi tek
  alana yazdı (`ticker: "TCELL TTKOM"`), sektör yazmadı. Harness'in temellendirmesi bu değeri
  soruya bağlayamadı ve sildi; hisse ve sektör olmadan sektör sorusu başlayamaz
  (`UNKNOWN_SECTOR` → ANALYSIS_UNSAFE). Kontrol TCELL'i seçip analizi yürüttü. Eğitim
  şablonlarında iki hisseyi karşılaştıran soru yok; ince ayar bu biçimi öğretmedi.
- **SL-17** — "Which banking names were lagging the sector at the close of June 30, 2025?" r16
  sektörü `BANK` yazdı; temellendirme bunu bir sektör grubuna ve sorudaki kelimeye bağlayamadı
  ve sildi, yine `UNKNOWN_SECTOR`. Kontrol `BANKING` yazdı (kabul edildi) ve analizi yürüttü,
  ama yolda 64 çağrı önerdi (45'i aynı `get_stock_history` çağrısı; 10'u reddedildi, ör.
  `GARANTIBANK` ve `TUPRAS` gibi soruyla ilgisiz ya da yanlış yazılmış kodlar). Sonucu doğru,
  yolu verimsiz.
- **TR-14** — "How often did an RSI dip below 30 in BIMAS lead to a positive five-day return?"
  r16 senaryoyu CALENDAR_PATTERN seçti (RSI sorusunu haftanın günü testiyle cevapladı) ve
  REJECT_SIGNAL'e vardı; teknik dönüş senaryosunun asgari kanıtı (`technical_state`) yok, bu
  yüzden kanıtsız sonuç sayılıyor. Kontrol BACKTEST seçip INVESTIGATE dedi; o da yanlış
  senaryo, ama INVESTIGATE asgari kanıt istemez.

Ortak nokta: r16'nın hataları niyet turunda, eğitim verisinde olmayan bir soru biçiminde
(iki hisse, İngilizce sektör adı, eşik + ileri getiri) ortaya çıkıyor. Açıklama turunda hiçbir
soruda geri dönüş yok.

### İyileştirdiği sorular

| Soru | Nasıl | r16 | Kontrol |
| --- | --- | --- | --- |
| AM-11 | sonuç | WATCH | OUT_OF_SCOPE |
| CP-02, CP-10 | sonuç | REJECT_SIGNAL | ANALYSIS_UNSAFE |
| TR-10 | sonuç | WATCH | ANALYSIS_UNSAFE |
| TR-04 | kanıtsız sonuç | WATCH | WATCH |
| AM-05, CP-03, CP-07, CP-15, CP-17, TR-02, TR-03, TR-05, TR-16 | açıklama geri döndü | (model yazdı) | INVESTIGATE (şablon) |

Örnekler:

- **CP-02** — "EREGL'de 2022-01-03 – 2024-12-31 döneminde en yüksek ortalama getiriyi hangi işlem
  günü vermiş, fark anlamlı mı?" Kontrol hisseyi niyete yazmadı (`MISSING_TICKER` →
  ANALYSIS_UNSAFE); r16 EREGL'i yazdı, testi yürüttü ve "Pazartesi, fark %0,91 [E5]" diye
  kanıtlı cevap verdi.
- **AM-11** — "Tell me about SASA." Kontrol kapsam dışı dedi; r16 fiyat özeti yaptı (beklenen
  ANALYSIS).
- **CP-03** — "Cuma günleri TCELL'in ortalama getirisi diğer günlerden ayrışıyor mu?" İki model
  aynı kanıtı topladı; kontrolün açıklaması "INVESTIGATE E3: …" diye etiketle ve köşeli
  parantezsiz kanıt numarasıyla başladığı için doğrulayıcıya takıldı, kullanıcıya şablon gitti.
  r16'nın açıklaması biçime uydu ve gösterildi.
- **TR-04** — Kontrol senaryoyu PRICE_SUMMARY seçip WATCH dedi; teknik dönüşün asgari kanıtı
  (`reversal_stats`, `backtest_summary`) eksik. r16 TECHNICAL_REVERSAL seçti, kanıt tam.

### Üç modelin de kaçırdığı sorular

- **TP-15** — "Test FROTO's weekday returns from 2025-09-30 to 2024-03-01." Tuzak: tarih
  aralığı ters, beklenen sonuç ANALYSIS_UNSAFE. r16 ve kontrol tarihleri niyette sessizce
  düzeltti (`start` 2024-03-01, `end` 2025-09-30) ve analizi yürüttü (REJECT_SIGNAL); hazır
  model aralığı olduğu gibi yazdı ve harness reddetti (`INVALID_DATE_RANGE`). Bütün kural ihlalleri bu sorudaki
  çağrılar. Harness bugün ters aralığı yalnız niyette görürse yakalıyor; modelin düzeltmesini
  sorudaki tarihlerle karşılaştırmıyor (Sprint 6, bölüm 8).
- **TR-13** — "What are the main support and resistance levels of FROTO over the past year?"
  Üç model de PRICE_SUMMARY seçip WATCH diyor; teknik dönüş senaryosunun asgari kanıtı eksik.
  Destek–direnç sorusunun hangi senaryoya düştüğü soru setinde de tartışmalı; ince ayarla
  ilgisi yok.
- **AM-18, SL-02, SL-09** — Üç model de ANALYSIS_UNSAFE (sonuç eşleşmiyor). Model farkı değil.

## 5. Seçim koşusuyla tutarlılık

Seçimde (dev60, deney E, 10.5) r16 kontrolden kabulde 16,5 puan, donmuş sette (E) 11 puan
önde (%100'e karşı %89,0); modelin desteksiz sayısı (seçimde 0'a karşı 18, burada 0'a karşı
36), uydurulan alan ve ham hisse doğruluğunda yön aynı. Senaryo doğruluğu seçimde r16 ve
kontrolde 1,000 iken burada 0,980 ve 0,929; iki set farklı sorulardan oluşuyor. Seçimdekinden
farklı yönde çıkan tek ölçüt kanıtsız sonuç: seçimde r16 0 / 96, kontrol 0 / 90; burada ikisi
de 4 (r16'da TR-13 ve TR-14, bölüm 4).

## 6. AM-03 (içerme sızıntısı, K-091)

AM-03 ("Haftanın günü etkisi var mı?") hisse ya da tarih eklenmiş hâliyle 10 eğitim sorusunda
geçiyor; tanımlı çakışma kuralına göre ihlal değil, ama sızıntı sayılır. Bu soruda üç modelin
dört kaydı da aynı:

| Soru | Deney | Tekrar | `bist-r16-e2` | `bist-base-9b` | hazır 9B |
| --- | --- | --- | --- | --- | --- |
| AM-03 | D | 0 | ANALYSIS_UNSAFE (eşleşti; CALENDAR_PATTERN; harness) | aynı | aynı |
| AM-03 | D | 1 | ANALYSIS_UNSAFE (eşleşti; CALENDAR_PATTERN; harness) | aynı | aynı |
| AM-03 | E | 0 | ANALYSIS_UNSAFE (eşleşti; CALENDAR_PATTERN; harness) | aynı | aynı |
| AM-03 | E | 1 | ANALYSIS_UNSAFE (eşleşti; CALENDAR_PATTERN; harness) | aynı | aynı |

Soru hisse adı taşımadığı için harness üç modelde de analizi başlatmıyor (`MISSING_TICKER`);
cevabı harness yazıyor. İnce ayarlı model bu soruda öne geçmedi; tablolar AM-03 dahil verildi, AM-03'ü çıkarmak
hiçbir farkı değiştirmez.

## 7. Bilinen sınırlamalar

1. **AM-03 içerme sızıntısı** (K-091, bölüm 6). Bu soruda etki yok; iki şablonun yeniden
   yazılması ve QC'ye içerme denetimi Sprint 6'da.
2. **Epizodik bellek geri test sonucunu taşımıyor** (spec §10). E deneyinde hatırlanan analiz
   özetinde geri testin sonucu yok; bu yüzden E'nin D'ye katkısı bu sette sınırlı kalmış
   olabilir. Sprint 6.
3. **Kod sürümü farkı.** r16 koşusu K-089 düzeltmesinden önceki kodla (11:37), kontrol ve hazır
   model sonraki kodla (14:09, `8833f95`) koştu. Aradaki `src` farkı yalnız `run_eval`'ın
   kayda yazdığı doğrulama alanı ve istemcinin beklenmedik cevap gövdesindeki hata yolu;
   harness'in davranışı aynı. Eski kayıtların doğrulaması `metrics.shown_problems` ile yeniden
   yapıldı, bütün ölçütler aynı kodla hesaplandı.
4. **Geçit için IPv6 sarmalayıcısı** (K-088, 10.6). Kod değişmedi; yalnız ölçüm koşucusu adı
   IPv6 adresine çözüyor. Koşular arasında masaüstü bir kez yeniden başlatıldı (14:06; r16
   önce, diğer ikisi sonra).
5. **Gecikme Task 7 ile karşılaştırılamaz** (farklı ağ yolu) ve modeller arasında da kabaca
   karşılaştırılmalı: r16 masaüstünün yeniden başlatılmasından önce, diğerleri sonra koştu.
6. **Hazır model kontrolle aynı değil.** Aynı ağırlıklar, ama Modelfile'ı `presence_penalty 1.5`
   taşıyor ve nicemleme karışımı farklı (10.5). Hazır modelin bazı
   üstünlükleri (TP-15, kural ihlali 0) bu farklardan gelebilir; ince ayarın etkisini r16 ile
   kontrol arasındaki fark ölçer.
7. **Tek tohum, iki özdeş tekrar.** Sıcaklık 0'da iki tekrar birebir aynı çıktı; sonuçlar
   örnekleme belirsizliğini göstermiyor. 120 soruda bir soru yaklaşık 0,8 puan.
8. **Eğitim verisi elle okunmadı ve internetsiz deneme yapılmadı** (K-090). 50 kaydın okunması
   (EC-052) ve Wi-Fi kapalı canlı deneme sprint etiketi öncesi Burak'ın işi; bu belge "internetsiz
   çalışır" iddiası taşımaz.
9. **Ters tarih aralığı.** Model aralığı sessizce düzeltirse harness tuzağı görmüyor (TP-15).
   İnce ayar bunu düzeltmedi; kontrol de aynı davranıyor. Sprint 6: niyet tarihleri sorudaki
   sırayla karşılaştırılır.

## 8. Sprint 6'ya kalanlar (bu karşılaştırmadan)

- Eğitim şablonlarına iki hisseli karşılaştırma ve İngilizce sektör adı (banking → BANK
  grubu) soruları; eşik + ileri getiri biçimindeki teknik dönüş soruları (AM-07, SL-17, TR-14).
- Ters tarih aralığının sorudaki sırayla denetlenmesi (TP-15).
- K-091 içerme denetimi ve AM-03 şablonları; bellek özetine geri test sonucu.
