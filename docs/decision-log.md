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
