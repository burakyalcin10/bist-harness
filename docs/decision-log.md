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
