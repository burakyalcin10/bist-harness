# İnce ayar (fine-tuning)

CSE-481 Mühendislik Ekonomisi — yalnız eğitim amaçlıdır, yatırım tavsiyesi değildir.

## Veri tasarımı ve kapsama

### Kayıtlar harness'ten toplanır

Eğitim verisi elle yazılmaz. Üretilen her soru gerçek harness'ten (`machine.run_analysis`)
geçer; modelin yerinde öğretmen istemci (`finetune/teacher.py`, `TeacherClient`) durur.
Araçlar gerçek veriyle çalışır. Harness'in her model turunda gönderdiği mesajlar ve araç
şemaları olduğu gibi, öğretmenin o turdaki doğru cevabı da hedef olarak kaydedilir.
Böylece model eğitimde, çıkarımda göreceği istemlerin aynısını görür: istem metni,
durum adları, kanıt listesi ve araç şemaları bayt bayt aynıdır. Harness'in istemleri
değişirse veri yeniden üretilir.

### Kayıt biçimi

Her satır bir `TrainingRecord`'dur (`finetune/record.py`, JSON Lines, satır sonu
`\n`). Anahtarlar sıralanmaz: mesajlar ve araç şemaları harness'in kurduğu sırayla
yazılır, çünkü sohbet şablonu onları bu sırayla işler. Aynı kayıtlar aynı baytları ve
aynı SHA-256'yı verir.

| Alan | İçerik |
| --- | --- |
| `record_id`, `question_id`, `family` | kaydın, sorunun ve soru şablonu ailesinin kimliği |
| `language`, `scenario` | cevabın dili (`tr`/`en`) ve sorunun senaryosu |
| `turn`, `state` | tur türü; araç turunda durum adı |
| `messages`, `tools` | harness'in o turda gönderdiği mesajlar ve sunduğu araç şemaları |
| `target` | doğru cevap: metin (`content`) ya da araç çağrıları (`tool_calls`) |
| `meta` | tur düzeyi (öğretmen yazar): araç turunda `state`, açıklama turunda `action` ve `eligible`; koşu düzeyi (Task 3'ün üretim hattı ekler): `outcome`, `snapshot_id`, `layers_id`, `today` |

### Üç tur türü

| Tur | Harness'in istemi | Hedef |
| --- | --- | --- |
| `intent` | `INTENT_SYSTEM_PROMPT` + soru | `INTENT_SCHEMA`'ya uyan doğru niyet (JSON) |
| `tool_call` | `TOOL_STATE_PROMPT` ile başlayan durum istemi + soru | o durumun kanonik çağrıları (`canonical_calls`), metin yok |
| `explanation` | uygun etiketler, kurallar, committed kanıt listesi | `{"action", "explanation"}`: her committed madde için bir satır, sayısı işaretiyle, `[En]` atfıyla; gerekiyorsa dönem notu; uyarı satırı |

Öğretmen her hedefi kodun denetiminden geçirir: niyet sorudan temellenmiş olmalı
(`ground_intent` hiçbir alanı değiştirmemeli), araç çağrıları `check_call`'dan,
açıklama `validate_explanation`'dan geçmeli. Geçmeyen hedef yazılmaz (`TeacherError`);
harness bir cevabı reddedip aynı turu yeniden sorarsa da öğretmen durur ve o soru veriden
çıkar.

Altın etiket verilmemişse uygun etiketler arasından sabit bir öncelikle seçilir: herhangi
bir `*_CANDIDATE` > `REJECT_SIGNAL` > `WATCH` > `HOLD` > `INVESTIGATE`. Öğretmen
`ANALYSIS_UNSAFE`'i kendiliğinden seçmez. Verilen altın etiket uygunsa her zaman o kullanılır.

Kanonik çağrısı olmayan bir araç durumunda (ör. hisse adı geçmeyen bir sektör sorusunda
hisse isteyen durum) öğretmen boş cevap verir ve o tur için kayıt yazmaz: öğretilecek
doğru bir çağrı yoktur. Harness kendi geri dönüşünü çalıştırır, soru veride kalır.

### Kapsama

Kapsama tablosu dört boyutludur:

- **Senaryo (4):** `SECTOR_LAGGARD`, `CALENDAR_PATTERN`, `TECHNICAL_REVERSAL`,
  `FUNDAMENTAL_REACTION`; ek olarak `BACKTEST`, `PRICE_SUMMARY`, `MACRO_CONTEXT`,
  `NEWS_CONTEXT`.
- **Etiket (8):** `HOLD`, `WATCH`, `INVESTIGATE`, `POTENTIAL_CATCH_UP_CANDIDATE`,
  `TECHNICAL_REVERSAL_CANDIDATE`, `FUNDAMENTAL_IMPROVEMENT_CANDIDATE`, `REJECT_SIGNAL`,
  `ANALYSIS_UNSAFE`.
- **Olumsuz örnekler:** tavsiye isteği, fiyat tahmini, evren dışı hisse, gelecek tarih,
  araç gerektirmeyen soru, eksik bilgi. Bunlarda yalnız `intent` turu vardır (ya da
  analiz `ANALYSIS_UNSAFE` ile kapanır); model reddetmeyi niyet turunda öğrenir.
- **Dil (2):** her aile Türkçe ve İngilizce.

Senaryo × etiket tablosunun her hücresi dolu olmayabilir (ör. bir senaryonun aday
etiketi başka senaryoda çıkmaz). Ulaşılamayan hücreler gerekçesiyle bu bölüme yazılır ve
sayılmaz; sayılar üretim manifestinden gelir.

Temel veri kullanan C–E stratejileri yalnız ön kayıtlı test dönemi (2025-01-01 ve
sonrası) için tanımlıdır. 2025'ten önce biten dönemlerde `FUNDAMENTAL_REACTION`
sorularının kanonik backtest'i `B_TECH_SECTOR`'dür (`machine.canonical_calls`); eğitim
tarihleri 2025'ten önce kaldığı için eğitim verisinde aday etiketi bu backtest'le
değerlendirilir. Bu hücrenin
gerçek veride dolup dolmadığı üretim manifestinden okunur.
