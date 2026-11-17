# Karar günlüğü

Bu dosya, Burak'ın yerine ya da onun yokluğunda alınan kararları tutar. Her karar onun
gözden geçirmesine açıktır; "Geri alma maliyeti" sütunu, karar değişirse neyin yeniden
yapılacağını söyler. Durum: `Bekliyor` (Burak henüz bakmadı), `Onaylandı`, `Değişti`.

## 17 Kasım 2026 — Sprint 1 gece vardiyası (Claude tek başına çalıştı)

Burak'ın talimatı: "5070 bu gece açılmayacak, açılmadan devam et. Hocaya soru
sormayacağız; hoca bunları bize bırakıyor. Sprint 1'i bitirene kadar devam et, kendi
aldığın kararları ayrı bir noktada not al. Bitirirsen Sprint 2 planını yap; eksik kalan
kısımları backlog'a at."

| No | Karar | Gerekçe | Geri alma maliyeti | Durum |
| --- | --- | --- | --- | --- |
| K-001 | Plan tek oturumda, alt agent açmadan yürütüldü. | Görevler birbirinin arayüzünü kullanıyor; Burak "sen devam et" dedi. | Yok. | Bekliyor |
| K-002 | Repo `C:\Users\burak\Projects\bist-harness` içinde kuruldu. | Diğer repolar da orada; OneDrive dışında olduğu için `.venv` ve git eşitleme sorunu çıkmaz. Ders belgeleri econproject klasöründe kaldı. | Klasörü taşımak yeterli; yol bağımlılığı yok. | Bekliyor |
| K-003 | Hocaya sorulacak soruların cevaplarını biz verdik (aşağıdaki tablo). | Burak'ın kararı: soru sorulmayacak. | Madde madde aşağıda. | Bekliyor |
| K-004 | Model ölçümü bu gece dizüstündeki Ollama ile, 4 GB'ye sığan modellerle yapıldı. RTX 5070 ölçümü ve nihai model seçimi ertelendi. | Uzak makine kapalı. | Seçim zaten Burak'ın; ölçüm betiği aynı komutla uzak adrese karşı çalışır. | Bekliyor |
| K-005 | Tasarım kararı K1: durum geçişlerini kod yönetir; model yalnız o durumun izinli araçlarından seçer ve açıklamayı yazar. | "Agent thinks. Harness controls." (2. hafta); hatalı araç çağrısını ve adım atlamayı azaltır; harness deneyi C'nin tanımı. | Sprint 4 başlamadan değişirse yalnız tasarım belgesi §6 değişir; sonra değişirse durum makinesi yeniden yazılır. | Bekliyor |
| K-006 | Tasarım kararı K2: sistem sorunun dilinde cevap verir (Türkçe ve İngilizce); etiketler ve araç adları İngilizce kalır. | Hocanın örnek sorusu Türkçe, istemdeki örnek İngilizce. | İnce ayar verisi iki dilde üretilir; tek dile inmek veriyi yarıya indirir, kod değişmez. | Bekliyor |
| K-007 | Tasarım kararı K3: araçlar ham seri değil özet istatistik ve `result_id` döndürür; yüzdeler araçta 2 ondalığa yuvarlanır. | Küçük modelin bağlamını korur; sayı denetimini birebir karşılaştırmaya indirir. | Araç çıktı biçimi değişirse ince ayar verisi yeniden üretilir. Sprint 5'ten önce kararlaştırılmalı. | Bekliyor |
| K-008 | `numbers_match` kuralı (Burak'ın katkı noktasıydı): iki sayı, 2 ondalığa yuvarlandığında eşitse aynıdır. Yüzde–kesir dönüşümü, tam sayıya yuvarlama ve işaret değiştirme kabul edilmez. | Araçlar 2 ondalık döndürüyor; katı kural uydurma sayıyı kaçırmaz. Bedeli "yaklaşık 63" diyen doğru cevabın reddi. | Tek fonksiyon ve test tablosu; kural değişirse sayısal halüsinasyon ölçümü yeniden koşulur. | Bekliyor |
| K-009 | Araç parametreleri (v0) `tools/schemas.py` içinde donduruldu; adlar istem §22'den. `log_decision` ve `replay_analysis` model aracı değil, harness servisi. | İstemde araç tablosu 15 satır; günlük ve replay §32'de fonksiyon olarak geçiyor ve modelin çağırması gerekmiyor. | Parametre adı değişirse ölçüm soruları ve ince ayar verisi güncellenir. | Bekliyor |
| K-010 | Dizüstündeki Ollama `winget` ile 0.15.2'den 0.40.16'ya güncellendi; `qwen3.5:0.8b`, `qwen3.5:2b`, `qwen3.5:4b` ve `llama3.2:3b` indirildi (yaklaşık 9,3 GB). | Uzak makine kapalıyken model ölçümü ve ince hat ancak dizüstünde yapılabilirdi; eski sürüm Qwen3.5'i çalıştıramıyordu. Sprint 1 planında bu adım Burak'a yazılmıştı. | Eski sürüm yeniden kurulabilir; modeller `ollama rm` ile silinir. Mevcut `qwen2.5:7b`, `mistral:7b` ve `nomic-embed-text` modellerine dokunulmadı. | Bekliyor |
| K-011 | Sektör medyanı için evren dışı referans hisseler kullanılacak; grup listesi Sprint 2 planı Task 2'de öneri olarak duruyor. | Yahoo'da BIST sektör endekslerinden yalnız XU100, XU030, XBANK ve XUSIN'in geçmişi var (17 Kasım'da 22 endeks denendi). Referans adaylarının 55'i 2020'den beri veriyle doğrulandı. | Grup listesi tek bir CSV; değişirse sektör sıralaması yeniden hesaplanır. | Bekliyor |
| K-012 | mcp SDK 2.3.0 kullanıldı; bu sürümde `FastMCP` adı `MCPServer` oldu ve üst düzey bir `Client` geldi. | `uv add mcp` güncel sürümü kurdu; plan metni eski adı kullanıyordu. Sunucu hem süreç içi hem stdio alt süreç olarak test edildi. | Sürüm `uv.lock` içinde sabit; 1.x'e dönmek sunucu ve çalıştırıcıda birkaç satır değiştirir. | Bekliyor |
| K-013 | Araçlar hisse başına tek bir tam geçmiş anlık görüntüsünden (2020-01-01'den bugüne) okur; istenen `end` tarihinde kesilir, olaylar `start` tarihinden itibaren sayılır. `end` tarihi dahildir; bugünden sonraki `end` reddedilir (`FUTURE_DATE`). | Her tarih aralığı için ayrı indirme yapılmaz; bantlar önceki günlerle ısınır; araç gelecekteki fiyatı hiçbir zaman görmez. | Pencerenin ilk 20 günündeki olay sayısı, yalnız pencere içinden hesaplayan hocanın betiğinden farklı olabilir; betik de 2020-01-01'den başladığı için tam dönem sonuçları aynıdır. | Bekliyor |
| K-014 | Takvim örüntülerinde koşul yalnız önceki günlere dayanacak. | Hocanın Senaryo 2 betiğinde `detect_pattern`, örüntüyü Pzt, Sal, Çar `< 0` **ve** Per, Cum `> 0` olarak tanımlıyor; `pattern_summary` de aynı haftaların Per–Cum getirisini "örüntü sonrası getiri" olarak raporluyor. Bu getiri tanım gereği pozitif ve pozitif oranı %100 çıkar (betik 17 Kasım'da okunarak doğrulandı). Betik örüntünün sıklığını doğru sayıyor; yalnız "sonrası getiri" ölçüsü koşuldan bağımsız değil. | Yok; bizim aracımız betiğin sıklık sayısını ayrıca raporlayabilir. Raporda bu fark açıklanmalı. | Bekliyor |
| K-015 | Sayı denetimi katılaştırıldı: yalnız araç çıktısının sayısal alanları bir sayıyı destekler; metin alanlarındaki, hata mesajlarındaki ve tarihlerdeki rakamlar desteklemez. Modelin seçtiği araç argümanları da muafiyet sayılmaz; yalnız sorudaki sayılar muaftır. Tarihler bütün olarak karşılaştırılır. | Kod incelemesi, gevşek sürümde uydurma bir sayının rastlantıyla geçebildiğini gösterdi ("getiri %20" tanım metnindeki 20 sayesinde geçiyordu). Kaçan uydurma sayı, yanlış alarmdan daha kötü. | Doğru bir cevap yanlışlıkla reddedilebilir (ör. "20 günlük bant" diyen cevap). Sprint 4'te reddedilen açıklama bir kez yeniden istenir. Kural tek modülde; gevşetmek kolay. | Bekliyor |
| K-016 | Araç çağrıları, araç çalışmadan önce şemaya göre denetlenir; bilinmeyen araç, eksik ya da fazla argüman, yanlış tip ve liste dışı değer `INVALID_ARGUMENT` olarak modele geri bildirilir. `event_type` zorunlu argümandır. | İncelemede `window: 50` gibi fazla bir argümanın sessizce yok sayıldığı görüldü. Hatalı araç çağrısı not ölçütlerinden biri; sayılabilmesi için yakalanması gerekir. | Model daha sık hata mesajı alır; ince ayar verisi şemaya tam uyan çağrılar içermeli. | Bekliyor |
| K-017 | Sprint 1 kodu bağımsız bir inceleyiciye (yeni bağlamlı alt agent) incelettirildi; 2 kritik ve 11 önemli bulgu tek geçişte, her biri önce kalan bir testle düzeltildi. Küçük bulgular ertelendi (aşağıda). | Yürütme yöntemi tek oturum olduğu için bu, kodun aldığı tek ikinci göz. | Yok. | Bekliyor |
| K-018 | Canlı ince hat denemesinin düzeltme sonrası tekrarında `qwen3.5:4b` kısmı, sistem dizüstünde bellek azaldığı için durduruldu; yeniden başlatmadım. | Araç, bellek darlığında arka plan işini kendisi durdurdu ve kendiliğimden yeniden başlatmamamı bildirdi. | Son iki düzeltme (ay adlı tarihler, kapsama toleransı) yalnız çevrimdışı testlerle doğrulandı. RTX 5070 açıldığında üç soru yeniden çalıştırılmalı. | Bekliyor |

### K-003 ayrıntısı: hocaya sorulmayan sorular ve verdiğimiz cevaplar

| Soru | Verdiğimiz cevap | Dayanak |
| --- | --- | --- |
| Model uzak makinede çalışabilir mi? | Evet. Sistem kendi RTX 5070'li makinemizde çalışır, dizüstü ona bağlanır; bulut servisi yok. | Burak: hoca bu düzeni biliyor ve takdir etti. |
| İnce ayar eğitimi nerede? | Kendi RTX 5070'li makinemizde. | Duyuru 3: tek GPU'da LoRA/QLoRA. |
| İnce ayar verisi nasıl üretilir? | Kendi şablonlarımız ve gerçek araç çıktılarıyla; başka bir model kullanılmaz. | Duyuru 3 madde 3; sayıların araçtan gelmesi halüsinasyonu önler. |
| Evren dışı hisseler kıyas için kullanılabilir mi? | Evet, yalnız sektör medyanı için referans olarak; analiz hedefi olmazlar. | İstem §11'deki banka örneği GARAN, ISCTR, YKBNK'yi kullanıyor. |
| Veri penceresi | Fiyat senaryolarında 2020–2024 keşif, 2025 – Kasım 2026 test. Temel veride TMS 29 sonrası. | Hocanın betikleri 2020'den başlıyor; Duyuru 1 test dönemini veriyor. |
| Onaylı video listesi | Yok; kendimiz seçeriz ve listeyi deneyden önce sabitleriz (Sprint 7). | İstem §16 örnek olarak Damodaran'ın kamuya açık derslerini veriyor. |
| Rapor dili | İngilizce rapor; plan ve tasarım belgeleri Türkçe. | İstem ve hocanın betikleri İngilizce. |
| Fintables erişimi | Yok varsayıldı; Sprint 3'te erişilebilir kaynak seçilecek, açıklama tarihleri KAP'tan. | Duyuru 1 madde 2: başka güvenilir kaynak serbest. |
| Weight-space programming | Yan deney olarak yapılır; raporda ve yapay zekâ kullanım ekinde açıkça belirtilir. | Burak'ın kararı (17 Kasım). |
| Canlı test dili | Sistem sorunun dilinde cevap verir; Türkçe ve İngilizce desteklenir. | Hocanın duyurudaki örnek sorusu Türkçe, istemdeki örnek İngilizce. |

### Ertelenen küçük bulgular (kod incelemesinden)

- `.env` dosyası BOM ya da UTF-16 ile kaydedilirse ilk anahtar okunmuyor (PowerShell 5 ile oluşturulan dosyalarda olabilir).
- Araç argümanında `20210101` biçimindeki tarih kabul ediliyor.
- Model ölçümünün puanlaması tarih biçimlerini normalleştirmiyor.
- Model ölçümünde ilk isteğin başarısız olması bütün modeli "ulaşılamaz" sayıyor.
- Bazı testler zayıf: ölçüm tablosu testi elle yazılmış satırlar kullanıyor; `run_slice` ve ölçümün `main()` fonksiyonları ile stdio üzerinden varsayılan yol yalnız canlı çalıştırmada deneniyor.
- Sayı denetimi, yazıyla yazılmış sayıları ("altmış") göremez. Bu bir sınırlamadır; raporun sınırlamalar bölümüne girmeli.

### Senin vermen gereken kararlar

1. Temel model seçimi (RTX 5070 ölçümünden sonra; Sprint 2 planı Task 11).
2. Tasarım belgesinin onayı ve K-005, K-006, K-007.
3. `numbers_match` kuralı (K-008) ve katı sayı denetimi (K-015): senin katkı noktandı; kuralı sen sahiplenmelisin.
4. Peer grubu listesi ve olay tanımları (Sprint 2 planı Task 2 ve Task 6).
5. `docs/ai_usage_log.md` içindeki "Verified by Burak" sütunu.

## 17 Kasım 2026 — Sprint 2 gece vardiyası (Claude tek başına çalıştı)

Burak'ın talimatı: "Sprint 2'ye geçelim, aynı işlemi Sprint 3 için de yapalım, ben yokum,
sabaha kadar aralıksız çalış." Yürütme yöntemi Sprint 1 ile aynı: tek oturum, sonunda
bağımsız inceleme (K-001).

| No | Karar | Gerekçe | Geri alma maliyeti | Durum |
| --- | --- | --- | --- | --- |
| K-019 | Çalışma `main` dalında sürdü; sprint sınırlarını `sprint-1`, `sprint-2` etiketleri gösteriyor. | Uzak deposu olmayan tek kişilik repo; inceleme aralığı etiketten alınıyor. | Etiketten dal açılabilir. | Bekliyor |
| K-020 | Construction grubuna ORGE ve ANELE referans hisse olarak eklendi. | ENKAI ve TKFEN ile grup 2 üyeydi; medyan için en az 3 üye gerekiyor. İkisinin de 2020'den beri verisi var. | CSV'de iki satır. | Bekliyor |
| K-021 | CCOLA'nın 11'e 1 bölünmesi `data/reference/price_adjustments.csv` ile okuma sırasında düzeltiliyor; ham anlık görüntü değişmiyor. Dosyanın özeti (`adjustments_id`) her araç çıktısında ve `result_id` içinde. | Yahoo bölünmeyi 13 Ağustos 2024'e kaydetmiş ama fiyatlara uygulamamış: 31 Temmuz kapanışı 846,00, 1 Ağustos 78,27 (sahte %−90,7). | CSV'de bir satır; CCOLA'nın Ağustos 2024 öncesi bütün sonuçları etkilenir. | Bekliyor |
| K-022 | Beş referans hissedeki fiyat sıçraması (AYGAZ, TATGD, HEKTS, INFO, OSMEN) düzeltilmedi; getiri penceresinde %40'tan büyük günlük hareket olan üye sektör medyanından çıkarılıyor ve uyarıda adı geçiyor. | Faktörleri tahmin etmek yerine veriyi kullanmamak daha güvenli; bu hisseler yalnız medyan için. | Düzeltme satırı eklenirse üye geri gelir. | Bekliyor |
| K-023 | Supertrend, ATR'nin ilk hesaplandığı günden başlatılıyor. | **Hocanın betiğindeki `add_supertrend` hiçbir gün değer üretmiyor** (ATR'nin ilk 9 günlük boşluğu bant özyinelemesinde sonsuza kadar taşınıyor; yön hep 1, dönüş olayı 0). Bir test bu davranışı sabitliyor, bir başka test bizim özyinelememizin betiğinkiyle aynı olduğunu gösteriyor. | Sonuçlarımız betiğin çıktısından farklı olur (betik 0 Supertrend olayı raporlar). Raporda açıklanmalı. | Bekliyor |
| K-024 | Gösterge listesine `VOLUME` eklendi; `detect_reversal_events` aracına isteğe bağlı `direction` (BULLISH/BEARISH) eklendi. | Hacim rejimi §8 piyasa durumunun parçası; dokuz olay ailesinin altısı iki yönlü. | Şema değişirse ince ayar verisi yeniden üretilir; henüz üretilmedi. | Bekliyor |
| K-025 | Destek/direnç gücünde "dönüş gücü" terimi: seviyeden ortalama uzaklaşmanın her %5'i için 1 puan, en çok 3 puan. "En yakın destek/direnç" bütün seviyelerden seçiliyor; listede en güçlü 6 seviye var. | Slayt formülü terimin birimini vermiyor. İlk hâlinde (yüzde olarak) tek dokunuşlu bir seviye dört dokunuşlu seviyeyi geçiyordu ve en yakın seviye 30 hissenin 27'sinde yanlış çıkıyordu (inceleme bulgusu). | Tek fonksiyon; seviye sıralaması değişir. | Bekliyor |
| K-026 | Olay tanımları: betikte olan dört yükseliş olayı birebir; düşüş karşılıkları ayna; `BOLLINGER_MIDDLE_TEST` ve `SUPPORT_RESISTANCE_TOUCH` bizim tanımımız (metinleri her araç çıktısında). Destek dokunuşu, son 250 günün bilinen pivotlarına %1,5 yaklaşmanın **ilk** günü. | İstem bu iki aileyi adlandırıyor ama tanımlamıyor. | Tanım değişirse o ailenin sayıları değişir; ön kayıt protokolünde sapma olarak yazılır. | Bekliyor |
| K-027 | Olay çıktısına `pending_events` (ileri penceresi dolmamış olaylar) ve `last_event_date` eklendi. | "Şu an sinyal var mı" sorusu ikinci bir araç gerektirmeden cevaplanabilsin; istatistiğe girmeyen olaylar gizlenmesin. | İki alan. | Bekliyor |
| K-028 | `THREE_DOWN_TWO_UP` haftaya bağlı tanımlandı: Pzt, Sal, Çar negatif → aynı haftanın Per–Cum bileşik getirisi. Betiğin tam örüntü sayısı ayrıca raporlanıyor. | Hocanın örüntüsünün, sonucu koşula katmayan hâli; betikle birebir karşılaştırılabiliyor. | Tek dal. | Bekliyor |
| K-029 | Takvim örüntülerinde anlamlılık: 2.000 karıştırmalı permütasyon testi (tohum 42), iki yönlü ve karıştırmaların kendi ortalamasına göre; koşullu örüntülerde Welch t istatistiği; beş örüntü için Bonferroni. | İlk hâli, koşulun oynak günleri seçtiği durumda (büyük düşüş sonrası) fazla sık "anlamlı" diyordu: etkisiz GARCH serilerinde %5 yerine %15–27 (inceleme bulgusu, yeniden üretildi). | İstatistik değişirse p değerleri değişir. | Bekliyor |
| K-030 | Göstergeler ısınma süresi dolmadan değer döndürmüyor: RSI 15, EMA 20, MACD 35, Ichimoku bulutu 78 bar. Bu barlardan önceki RSI ve Ichimoku olayları sayılmıyor. | Üstel ortalamalar ikinci bardan itibaren anlamsız bir sayı üretiyor (2 barda RSI 0,0). | Sabitler. | Bekliyor |
| K-031 | Sektör aracı: verisi olan üye 3'ten azsa lag skoru, lider ve geride kalan verilmez (Telecom böyle: TCELL ve TTKOM dışında üye yok); verisi eski üye çıkarılır; veri `as_of` tarihinden önce bitiyorsa uyarı. | İki üyeli grupta biri tanım gereği "lider", diğeri "geride kalan" olur. | Eşik sabiti. | Bekliyor |
| K-032 | SQLite şemasında `analyses` tablosuna plandakinden on sütun fazla kondu. | §28'deki her karar günlüğü alanının bir sütunu olsun; eşleme testle doğrulanıyor. | Şema sürümü artar. | Bekliyor |
| K-033 | Sprint 2 kodu bağımsız bir inceleyiciye incelettirildi: geleceğe bakma bulunmadı; 2 kritik, 9 önemli bulgu tek geçişte, her biri önce kalan bir testle düzeltildi. | Tek oturumda yürütmenin tek ikinci gözü. | Yok. | Bekliyor |
| K-034 | Anlık görüntü özet (hash) yöntemi değişti ve `20261117-0722` manifesti saklanan dosyalardan yeniden hesaplandı. | İlk yöntem Parquet'e yazıp okuyunca aynı sonucu vermiyordu; doğrulama bütün serileri "değişmiş" gösteriyordu. Dosyalara dokunulmadı. | Yok; `snapshot verify` komutu eşleşme bildiriyor. | Bekliyor |
| K-035 | Sprint 3 veri kaynakları: çeyreklik tablolar İş Yatırım'ın herkese açık mali tablo servisinden, açıklama zamanları KAP bildirim sorgusundan; TÜFE ve politika faizi TCMB sayfalarından; kur Yahoo'dan; Fed hedefi Federal Reserve sayfasından. | Fintables erişimi yok (K-003); EVDS anahtar istiyor. Hepsi 17 Kasım'da denendi ve cevap verdi. Duyuru 1 madde 2 başka güvenilir kaynağa izin veriyor. | Kaynak değişirse yalnız indirme katmanı değişir. | Bekliyor |
| K-036 | Ön kayıt protokolü (`docs/preregistration.md`) yazıldı: keşif 2020–2024, test 2025 – 13 Kasım 2026; strateji parametreleri (t+1 açılışında giriş, 10 gün tutma, tek yön %0,15 maliyet) hiçbir backtest çalıştırılmadan sabitlendi. | İstem §34 madde 5. THYAO'nun takvim sonuçları test dönemini de içerecek biçimde önceden görüldüğü için protokolde "ön kayıtlı değil" olarak işaretlendi. | Parametre değişirse protokolde sapma olarak yazılır. | Bekliyor |

### Sprint 2'de ortaya çıkan bulgular (raporda kullanılabilir)

- **Hocanın betiklerinde iki kusur doğrulandı.** Senaryo 2'de "örüntü sonrası getiri" tanım gereği pozitif (K-014); Senaryo 3'te Supertrend hiç değer üretmiyor (K-023).
- **Veri kusurları.** CCOLA'da uygulanmamış bölünme (düzeltildi); SASA'da 155 gün hacim yok (128'i 2026'da, fiyat hareket ediyor): SASA için hacme dayalı özellikler güvenilmez ve Sprint 4 kalite kapısı bunu uyarmalı.
- **Yanlış pozitif örneği.** THYAO'da "büyük düşüşten sonra toparlanma" ilk hesapta anlamlı görünüyordu (Bonferroni p 0,0075); düzeltilmiş testte keşif döneminde p 0,22. Sistem artık bunu "anlamlı değil" diye raporluyor.
- **Küçük model (qwen3.5:2b, ince ayarsız) yeni araçlarla.** Araç ve argümanlar doğru; ama başarı oranına "başarısız oranı" dedi, "26 başarılı olay" yazdı (doğrusu 26 olay, 16 başarılı), tavsiye sorusunu reddetmedi ve ASELS için uydurma bir şirket adı yazdı. Sayı denetimi bunların hiçbirini yakalayamaz; Sprint 4'te kanıt cümleleri şablondan üretilmeli, Sprint 5 verisi alan adlarını öğretmeli.

### Ertelenen küçük bulgular (Sprint 2 incelemesinden)

- Arka arkaya eşit yüksek/alçak günler ayrı pivot sayılıyor (gerçek veride yalnız tek tük hacimsiz barlarda görülüyor).
- `event_records` ileri penceresi dolmamış getirilerde NaN veriyor; veritabanına yazılmadan önce `None` yapılmalı (Sprint 4).
- MCP katmanı `forward_days="5"` gibi yanlış tipleri kendiliğinden çeviriyor; katı denetim `validate_tool_call` içinde ve harness onu çağırıyor (Sprint 4'te bütün çağrılar oradan geçecek).
- Sektör getirisinde pencere takvim gününe göre değil bar sayısına göre; barı eksik üyede pencere birkaç gün erken başlıyor.
- Anlık görüntü seans sırasında kurulursa bitmemiş bar günlük kapanış gibi saklanır; kurulum seans dışında yapılmalı.
- ECILC'de 12 Mart 2020'de hacimsiz bir barın ardından %+31,9: %40 sınırının altında kaldığı için işaretlenmiyor.

## 17 Kasım 2026 — Sprint 3 (aynı gece vardiyasının devamı; Claude tek başına çalıştı)

Plan (`docs/superpowers/plans/2026-11-18-sprint-3-backtest-ve-temel-veri.md`) Claude
tarafından yazıldı ve Burak görmeden yürütüldü; talimat "aynı işlemi Sprint 3 için de
yapalım" idi.

| No | Karar | Gerekçe | Geri alma maliyeti | Durum |
| --- | --- | --- | --- | --- |
| K-037 | Backtest kuralları: karar t gününün kapanışında, giriş **t+1 açılışında**, çıkış t+10 kapanışında; tek yön %0,15 maliyet; hisse başına tek açık işlem; açık işlemler eşit ağırlıklı, nakit getirisiz; tutma penceresi veride tamamlanmayan sinyal işlem açmaz. | İstem §18: karar, t+1'in bilgisini kullanamaz. Sinyali üreten barın fiyatıyla işlem yapmak sonucu iyimser gösterir. Kurallar ön kayıt protokolünde, hiçbir backtest çalışmadan önce sabitlendi. | Kural değişirse bütün backtest sonuçları yeniden üretilir ve protokolde sapma olarak yazılır. | Bekliyor |
| K-038 | Kıyaslar: aynı hisselerin günlük yeniden dengelenen eşit ağırlıklı sepeti ("al-tut"), XU100 ve (B–E için) peer gruplarının sepeti. Sharpe 252 gün, risksiz oran 0. | Basit ve tekrarlanabilir. Türkiye faizleriyle risksiz oran 0 varsayımı Sharpe'ı yüksek gösterir; çıktıda yazılı. | Kıyas tanımı değişirse "fark" alanları değişir. | Bekliyor |
| K-039 | Makro kaynakları: kur Yahoo'dan (EVDS anahtar istiyor; dört günde TCMB gösterge kuruyla karşılaştırıldı, fark yaklaşık %1 içinde); politika faizi ve TÜFE TCMB sayfalarından; Fed hedef aralığı Federal Reserve sayfasından. TÜFE'nin yayın günü kuraldır: izleyen ayın 3'ü, hafta sonuysa sonraki iş günü. | Duyuru 1 madde 2. Yayın tarihine hizalama istem §15'in şartı. | Yalnız `data/macro.py` değişir. | Bekliyor |
| K-040 | Temel veri: tablolar İş Yatırım'ın herkese açık servisinden, yayın zamanları KAP'tan. Bir tablo, yayın zaman damgasından sonraki ilk kapanıştan itibaren kullanılır (18:00'den önce yayımlandıysa o gün, değilse sonraki işlem günü). Düzeltme varsa ilk yayın geçerli. | 479 dönemin %88'i 18:00'den sonra yayımlanmış; dönem sonu ya da yayın gününe göre hizalama geleceğe bakmak olurdu. | Kural tek fonksiyon (`known_from`). | Bekliyor |
| K-041 | Metrik tanımları: FAVÖK = esas faaliyet kârı + amortisman; son 12 ay = dönem + önceki yıl sonu − önceki yılın aynı dönemi; reel büyüme TÜFE endeksiyle; banka ve sigorta için yalnız aktif, özkaynak, sermaye, gelir satırı ve net kâr eşlendi, sanayi oranları `None`. Pay sayısı dönemden sonra değiştiyse F/K, PD/DD ve FD/FAVÖK verilmez. Enflasyon muhasebesi 2023 yıl sonundan başlar; daha eski karşılaştırma uyarı alır. | İstem §14: banka analizinde sanayi oranları körü körüne kullanılmamalı. Anlık görüntüdeki fiyatlar bölünmeye göre düzeltilmiş olduğundan eski pay sayısıyla çarpmak yanlış piyasa değeri verir. | Tanım değişirse temel metrikler ve C–E varyantları yeniden hesaplanır. | Bekliyor |
| K-042 | `fundamental_trend`: uygulanabilen denetimlerin (hasılat, kâr, marj, özkaynak kârlılığı; sanayide ayrıca kaldıraç ve nakit akışı) en az üçte ikisi olumluysa "Improving", en çok üçte biri olumluysa "Deteriorating", arası "Mixed"; üçten az denetim varsa eğilim yok. | Tek sayıya indirgemek yerine sayılabilir bir kural; C varyantının süzgeci bu. | Eşik değişirse C–E sonuçları değişir (protokolde sapma). | Bekliyor |
| K-043 | Açıklama sonrası tepki: olay gününden önceki kapanıştan 1, 5 ve 20 işlem günü sonraki kapanışa; XU100'e ve hisse hariç peer sepetine göre anormal getiri. On altıncı bir araç açılmadı; tepki `calculate_fundamental_change` çıktısında. | Seans içi ve seans sonrası yayınları aynı pencereyle kapsar. İstem §22'de 15 araç var. | Pencere değişirse Senaryo 4 sonuçları değişir. | Bekliyor |
| K-044 | KAP olay katmanı: yalnız özel durum açıklamalarının üst verisi (metin saklanmıyor), anahtar sözcük kurallarıyla konu etiketi, duygu etiketi yok. Etiketler dosya okunurken atanıyor. Gerçek veri görüldükten sonra üç kural hatası düzeltildi; E varyantının kullandığı `regulation_legal` kümesi değişmedi. | Duyuru 1 madde 3: KAP uygun kaynak; metinsel kaynak sayısal verinin yerini tutamaz. | Kurallar tek tablo. | Bekliyor |
| K-045 | Özellik tablosu her katmanı bilginin kamuya açıldığı tarihe göre birleştirir. C–E varyantları temel veri gerektirdiği için 2025'ten itibaren çalışır ve bunu uyarıyla söyler. Faiz artışı penceresi 60 takvim günü, KAP penceresi 5 takvim günü. | Ön kayıt protokolündeki varyant tanımları. | Pencere sabitleri. | Bekliyor |
| K-046 | Her veri katmanının kendi kurulum komutu var ve etkin anlık görüntüye eklenir; fiyat verisi ve önceki sonuç kimlikleri değişmez. | Sprint 2 sonuçları aynı `snapshot_id` ile tekrarlanabilir kalsın. | Yok. | Bekliyor |
| K-047 | Sprint 3 kodu bağımsız bir inceleyiciye incelettirildi. Backtest zamanlaması, maliyet, çakışma kuralı, lag skoru ve özellik tablosunun geleceğe bakmadığı doğrulandı. 3 kritik ve 13 önemli bulgu çıktı; aşağıda hangilerinin düzeltildiği, hangilerinin geri çekildiği ve hangilerinin ertelendiği yazılı. | Tek oturumda yürütmenin tek ikinci gözü. | Yok. | Bekliyor |
| K-048 | **Temel veri katmanı "yeniden düzeltilmiş" değerler veriyor; bu yüzden reel büyüme ve değerleme oranları geri çekildi.** İş Yatırım, bir dönemin rakamlarını bir sonraki yılın raporundaki karşılaştırmalı (enflasyona göre yeniden düzeltilmiş) değerle değiştiriyor: TUPRS 2024 yıl sonu hasılatı kaynakta 1.060.733 mn TL, oran Aralık 2025 / Aralık 2024 TÜFE oranına eşit. Araç çıktıları artık `RESTATED_SOURCE` uyarısı taşıyor; `*_real_yoy_pct` alanları boş; F/K, PD/DD, FD/FAVÖK boş (anlık görüntüdeki fiyatlar temettüye göre de düzeltilmiş olduğundan geçmiş piyasa değeri eksik çıkıyordu). | Yanlış sayıyı uyarıyla göstermektense göstermemek. Kaynağın zamana göre doğru olmadığı ancak incelemede anlaşıldı; K-040'taki "geri alma maliyeti" tahminim yanlıştı. | Katman, yayımlandığı günkü rakamlardan yeniden kurulmalı (KAP'taki finansal rapor bildirimlerinin kendisinden ya da TÜFE oranıyla geri çevirerek); Sprint 4'ün ilk işi. | Bekliyor |
| K-049 | **Test dönemi (2025 – Kasım 2026) backtest'i ve Senaryo 4 olay çalışması çalıştırılmadı.** | Ön kayıt protokolü test döneminin bir kez çalıştırılmasını şart koşuyor; C–E varyantları ve Senaryo 4, kusurlu olduğu anlaşılan temel veriye dayanıyor. A ve B ayrı çalıştırılabilirdi; hepsinin birlikte ve bir kez çalışması için beklettim. | Yok; çalıştırma komutu hazır (`backtest/study.py`). | Bekliyor |
| K-050 | Backtest düzeltmeleri: portföy ve kıyas artık endeksin ya da hisselerden birinin barı olan her günü kapsıyor (XU100 dosyasında beş gerçek seans eksik); "al-tut" bir kez alınıp hiç yeniden dengelenmeyen sepet oldu (keşif döneminde %1.804,85 yerine %1.548,88); işlem yokken "geride kaldı" bayrağı konmuyor. Keşif dönemi sonuçları yeniden üretildi (A %244,98, B %225,02). | İnceleme bulguları. İşlemlerin kendisi değişmedi. | Yok. | Bekliyor |
| K-051 | Tarih düzeltmesi: bu gece yazdığım belgeleri "18 Kasım" diye tarihlemiştim; sistem saati ve commit'ler 17 Kasım 2026'yı gösteriyor. Metin içi tarihler 17 Kasım'a çevrildi; sonuç dosyalarının adları da. Sprint planlarının dosya adlarındaki tarihler planlanan sprint günleridir. | Ön kayıt protokolünün kanıtı commit sırası; belge tarihi commit tarihiyle tutmalı. | Yok. | Bekliyor |
| K-052 | Repo GitHub'da herkese açık yayımlandı (`burakyalcin10/bist-harness`). Hocanın iki örnek betiği yayımlanmadı: `reference/instructor/*.py` git dışına alındı ve commit geçmişinden de çıkarıldı. Bu yüzden 17 Kasım öncesi commit kimlikleri değişti; etiket adları aynı. Aynı gün commit'lerdeki ve `pyproject.toml` içindeki kişisel e-posta adresi GitHub'ın noreply adresiyle değiştirildi; kimlikler bir kez daha değişti. Betiklere dayanan 61 karşılaştırma testi dosyalar yoksa atlanır. | Betikler ders malzemesi; lisansı ve yayım izni yok. Yayımlamak geri alınamaz, yayımlamamak her zaman geri alınabilir. | Betikleri repoya geri eklemek tek commit. Eski geçmişin tam yedeği repo dışında (`bist-harness-backups/bist-harness-before-publish-2026-11-17.bundle`). | Burak'ın kararı (17 Kasım 2026) |

### Sprint 3 incelemesi: düzeltilenler

Her biri önce kalan bir testle (`tests/test_sprint3_review.py`): reel büyüme ve değerlemenin geri çekilmesi ve `RESTATED_SOURCE` uyarısı; C–E çıktılarında `FUNDAMENTALS_NOT_POINT_IN_TIME` uyarısı; portföy takvimi; gerçek al-tut kıyası; işlemsiz backtest'te bayrak; dönem verinin öncesinde başlıyorsa uyarı (backtest, kur, KAP); kurun dönem başındaki değeri; haber aracında konu listesi şemaya girdi; "ihracat" ve "yatırımcı" yanlış etiketleri.

### Sprint 3 incelemesi: ertelenenler (Sprint 4'ün başına)

- **Temel veri katmanının yeniden kurulması** (K-048): yayımlandığı günkü rakamlar; son 12 ay ve bilanço oranlarında fiyat düzeyi karışıklığı; `CASH_FLOW_UP` ve `PROFIT_UP` denetimlerinin tutarlılığı; aynı gün yayımlanan konsolide ve solo raporlardan hangisinin alındığı; MAVI'nin dönem sonları (mali yılı Ocak'ta bitiyor).
- **Anlık görüntüye düzeltilmemiş kapanış eklenmesi**: değerleme oranları için.
- **Anlık görüntü kimliği eklenen katmanları sabitlemiyor**: makro, temel ve KAP dosyaları aynı `snapshot_id` altında yeniden kurulabiliyor ve `snapshot verify` yalnız fiyat dosyalarına bakıyor. Katmanların özetleri sonuç kimliğine girmeli.
- **Kur verisinin saati**: Yahoo günlük kapanışı BIST kapanışından saatler sonra; özellik tablosunda bir gün gecikmeyle kullanılmalı. Hiçbir strateji varyantı bu sütunu kullanmıyor.
- **TÜFE yayın günü kuralı tatilleri bilmiyor** (ör. Haziran 2023 verisi 3 Temmuz yerine 5 Temmuz'da yayımlandı): yayın tarihleri kayıtlı bir tablodan alınmalı.
- **Motorun "bilgi tarihi" denetimi C–E için anlamsız**: tablo zaten o tarihe göre birleştiriliyor; denetim hiç tetiklenemez. Yeniden kurulan temel katmanla birlikte anlamlı bir denetime çevrilmeli.
- Rekabet Kurulu onayları `regulation_legal` sayılıyor (3 bildirim) ve E varyantında girişi engelliyor; protokoldeki tanım bu olduğu için dokunmadım.
- Politika faizi tablosundaki tarih kararın yürürlük günü (karardan bir gün sonra); alan adı `last_policy_decision_date`.
- Yarım gün seanslarda 13:00–18:00 arasındaki yayın, kendisinden önce kapanan seansa yazılıyor (4 bildirim).
- KAP ve temel veri kurulumunda üye kimliği bulunamazsa koruma yok.

### Ön kayıt protokolüyle uyumsuzluklar

İnceleme altı uyumsuzluk buldu; hepsi protokole "test dönemi çalıştırılmadan önceki düzeltmeler" başlığıyla işlendi: al-tut tanımı, A varyantında peer kıyası olmaması, temel verinin 2022 4. çeyrekten yüklenmesi, konu kurallarının protokolden sonra düzeltilmesi, temel verinin zamana göre doğru olmaması ve belge tarihi.

### Bu gecenin bulguları (raporda kullanılabilir)

- **Açıklama zamanı.** 479 finansal raporun %88'i 18:00'den sonra yayımlanmış; dönem sonundan ilk kullanılabilir güne medyan 41 gün. Dönem sonuna göre hizalanan bir backtest geleceğe bakar.
- **Keşif dönemi backtest'i.** A ve B varyantları 2020–2024'te hisseleri tutmanın çok gerisinde (yaklaşık %245 ve %225'e karşı %1.549); ortalama işlem getirisi, piyasada kalmanın aynı sürede kazandırdığına yakın. Sektör koşulu işlemleri iyileştirmiyor.
- **Kaynak tuzağı.** Herkese açık mali tablo servisi geçmiş dönemleri sonradan yeniden düzeltilmiş hâliyle veriyor; bu, enflasyon muhasebesi olan bir piyasada "zamana göre doğru" veri kurmanın neden zor olduğunu gösteren somut bir örnek.

## 17 Kasım 2026 — Sprint 4

Burak planı okudu ve onayladı. Yürütme: Task 0 ve Task 10 ana oturumda, Task 1–9 alt
ajanlarla (görev başına temiz bağlamlı uygulayıcı ve inceleme).

| No | Karar | Gerekçe | Geri alma maliyeti | Durum |
| --- | --- | --- | --- | --- |
| K-053 | Sprint 4 planı dört eklemeyle onaylandı: (1) Senaryo 1–3'ün test dönemi koşucuları `study.py`'ye eklenir ve test dönemi tek çalıştırmada A–E ve Senaryo 4 ile birlikte açılır; (2) konsolide/solo seçimi, MAVI dönem sonu ve yarım gün seansı yayınları Task 0'a; KAP üye kimliği koruması ve özellik tablosu önbelleği Task 1'e; (3) Task 0'a kalan testler listesi; (4) canlı deneme dosyasının adı gerçek çalıştırma günüyle. Yürütme karma düzende. | `study test` yalnız A–E ve Senaryo 4'ü çalıştırıyordu; ön kayıttaki Senaryo 1–3 sorularının test dönemi koşucusu yoktu. Ertelenen üç madde `known_from` ve dönem hizasını etkilediği için tek seferlik çalıştırmadan önce düzelmeli. | Plan metni. | Burak'ın kararı (17 Kasım 2026) |
| K-054 | Sprint 4 `main` yerine `.worktrees/sprint-4` altında `sprint-4-dev` dalında yürütülüyor; dal adı sprint sonundaki `sprint-4` etiketiyle karışmasın diye farklı. Git dışı veri ortak: worktree'nin `.env` dosyası `BIST_DATA_DIR` ile ana repodaki `data/` klasörünü gösteriyor; izlenen referans dosyaları (`data/reference/`) worktree'nin kendi kopyasından okunuyor. Yürütme defteri betiklerin açtığı `.superpowers/sdd/2026-11-19-sprint-4-mcp-ve-harness/` altında; sprint sonunda `.superpowers/sdd/sprint-4/` olarak ana repoya kopyalanır. | Burak'ın genel talimatı büyük planlarda worktree istiyor (K-019'daki `main` üzerinde çalışma bu sprintte değişti). Veri tek yerde kalmalı; anlık görüntü iki kopyaya bölünürse `snapshot_id` aynı, içerik farklı olabilir. | Dal `main`'e birleştirilir; worktree silinir. | Bekliyor |
| K-055 | **Temel veri katmanı KAP'taki finansal rapor bildirimlerinin kendisinden yeniden kurulur (yol a).** Kapsam mevcut dönem aralığı (2022Q4–2026Q3). Sayfalar `data/cache/kap_reports/` altında sıkıştırılmış saklanır; kalemler XBRL kavram adlarıyla okunur; birim ve konsolide/solo bilgisi sayfadan alınır. | Ölçüm (`docs/results/2026-11-17-fundamentals-source-measurement.md`): kaynak sanayi şirketlerinde rakamları sonraki raporun fiyat düzeyine taşıyor, THYAO'yu yanlış ölçekliyor; TÜFE oranıyla geri çevirme 2022Q4 ve 2023 dönemlerini kurtaramıyor. KAP raporu cari ve karşılaştırmalı dönemi aynı fiyat düzeyinde veriyor. | Yaklaşık üç saatlik indirme ve ayrıştırıcı; yol (b)'ye dönmek indirilen sayfaları boşa çıkarır, kodu değil. Kapsam kararını (tam aralık) Burak yanıtlamadı, önerilen seçenek uygulandı. | Burak'ın kararı (17 Kasım 2026); kapsam Bekliyor |
| K-056 | TÜFE yayın günleri kayıtlı tablodan (`data/reference/cpi_release_dates.csv`); tablo "izleyen ayın 3'ü ya da sonraki ilk BIST işlem günü" kuralıyla üretildi, her satır dayanağını taşıyor. | TÜİK'in yayın takvimi otomatik alınamadı (portal JavaScript uygulaması, bülten verisi başka kaynaktan geliyor); TCMB'nin aylık fiyat raporları tarih taşımıyor. BIST takvimi tatilleri biliyor: Nisan 2022 TÜFE'si 5 Mayıs (eski kural 3 Mayıs diyordu). | Sprint 3 incelemesindeki "Haziran 2023 → 5 Temmuz" doğrulanamadı; gerçekse o ay iki gün erken kullanılır. Satır elle düzeltilebilir. | Bekliyor |
| K-057 | Yarım gün seansları 12:30'da kapanır (`data/reference/half_day_sessions.csv`: 2429 sayılı Kanun'a göre bayram arifeleri ve 28 Ekim, hafta içine denk gelenler). 16 günün hepsi BIST takviminde işlem günü ve ertesi günü kapalı ya da hafta sonu. | Borsa İstanbul sayfası bağlantıyı kesti; yasal kural ve takvim denetimi birlikte kullanıldı. | Kapanış saati 12:40 olsa da 12:30 sonrası yayın ertesi güne yazılır; daha temkinli. | Bekliyor |
| K-058 | Katman özetleri (`layers_id`: makro, temel, KAP, ham fiyat dosyaları ve iki referans tablosu) her sonuç kimliğine girer; `snapshot seal` mühürler, `snapshot verify` denetler. Mühürleme kurulum komutlarına gömülmedi. | Katman yeniden kurulursa sonuç kimliği değişmeli. | Unutulursa `verify` "not sealed" der. | Bekliyor |
| K-059 | Temel katmanın ayrıntıları: kalemler XBRL kavramlarından (kısa vadeli borç = kısa vadeli borçlanmalar + uzun vadelilerin kısa vadeli kısmı; banka hasılatı = net faiz geliri; sigorta = hayat dışı ve hayat brüt yazılan prim); şirketin TMS 29 uygulayıp uygulamadığı, raporun karşılaştırmalı sütunu bir yıl önce yayımlanan rakamla karşılaştırılarak saptanır (%0,5 eşik); son 12 ay ve çeyreklik değerde önceki kümülatif rakam yalnız yeniden düzelten şirkette TÜFE oranıyla taşınır. | TMS 29'un kendi yöntemi; şirket politikası veriden okunur. | Eşik veya kavram değişirse katman yeniden kurulur. | Bekliyor |
| K-060 | Değerleme: piyasa değeri = Yahoo'nun `auto_adjust=False` kapanışından bölünmeler geri alınarak bulunan o günkü fiyat × ödenmiş sermaye (nominal 1 TL). Dönem sonundan sonra bölünme (bedelsiz) olduysa F/K, PD/DD, FD/FAVÖK verilmez. 26 bölünmenin hepsinde ham fiyat bölünme oranında düşüyor. | K-041'in kuralı; temettü düzeltmeli fiyat piyasa değerini küçültüyordu. | Bedelli artırımları Yahoo kaydetmez; o dönemde pay sayısı eskidir (belgelendi). | Bekliyor |
| K-061 | Motorun bilgi tarihi denetimi, özellik tablosunun kullandığı dönemin `known_from` gününü KAP yayın zamanından yeniden hesaplar. | Eski denetim kendi hizasını denetliyordu; hiç tetiklenemezdi. | Yok. | Bekliyor |
| K-062 | Senaryo 1–3 koşucularındaki açık noktalar (ön kayıt 6.1): sonuç penceresi dönem içinde biter, peer medyanı hisse hariç; `WEEKDAY_MEANS` için fark = keşifteki en iyi günün ortalaması eksi bütün günlerin ortalaması. | Protokol bu noktalarda sessizdi; test dönemi açılmadan karar verildi. | Keşif dönemi yeniden çalıştırılır. | Bekliyor |
| K-063 | **Süreç ihlali:** Task 3'ün uygulayıcı alt ajanı (niyet çıkarımı ve rotalar) kodu testlerden önce yazdı; kırmızı aşamayı modülleri geçici olarak kenara alarak üretti. Kod silinmedi; görev incelemesinde her test grubu için "hangi kod hatası bu testi düşürür" sorusu soruldu, zayıf testler düzeltme turuna alındı. | Devir notu bu sıranın bozulmamasını istiyordu; kodu silip yeniden yazmak ritüel olurdu, asıl risk testlerin uygulamayı yansıtması. Sonraki gönderimlerde test önceliği açıkça şart koşuldu. | İnceleme zayıf test bulmazsa yok; bulursa düzeltme turu. | Bekliyor |

## Senin vermen gereken kararlar (güncel)

1. Temel model seçimi ve QLoRA deneme eğitimi: RTX 5070 gerekiyor (EC-005, EC-006).
2. Tasarım belgesinin onayı ve K-005, K-006, K-007.
3. Sayı eşleştirme kuralı (K-008) ve katı sayı denetimi (K-015).
4. Peer grubu listesi (K-020, K-031) ve olay tanımları (K-026, K-028).
5. İstatistik seçimleri (K-029) ve ön kayıt protokolü (K-036, protokoldeki düzeltmeler bölümüyle birlikte).
6. Backtest kuralları (K-037, K-038). Temel veri katmanının yeniden kurulma yolu 17 Kasım'da verildi (K-055: KAP raporlarından).
7. Test dönemi çalıştırmasının zamanı (K-049).
8. `docs/ai_usage_log.md` içindeki "Verified by Burak" sütunu.
