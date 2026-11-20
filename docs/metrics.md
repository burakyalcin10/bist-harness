# Değerlendirme metrikleri

Bu belge, `src/bist_harness/eval/metrics.py` içindeki metriklerin rapora aynen girecek tanımlarıdır (kart EC-061; Sprint 4 K-074 tanımları ve son düzeltme dalgasındaki notlarla birleşik). Metrikler, `eval.run_eval`'in her soru ve tekrar için yazdığı kayıtların (`runs/eval-*/records.jsonl`) saf fonksiyonlarıdır; model ya da veri klasörü gerekmez. Kod ile bu belge çelişmemelidir; sayımlar `tests/fixtures/labelled_records.jsonl` içindeki 12 elle etiketlenmiş kayıt ve `tests/fixtures/labelled_expected.json` içindeki elle yazılmış beklenen değerlerle sınanır (`tests/test_metrics_labelled.py`).

## Deneyler ve yapısal olarak gösterebildikleri

| Deney | Araç çağrısı | Durum makinesi ve kapı | Kanıt etiketi | Cevabı denetleyen |
| --- | --- | --- | --- | --- |
| A | yok (veri metin olarak verilir) | yok | yok | yok |
| B | modelin seçtiği, yalnızca şema denetimli | yok | yok | yok |
| C | durum makinesinde | kapı var ama hiç engellemez | var | yok |
| D | durum makinesinde | gerçek kapı | var | doğrulayıcı (validator) |
| E | D gibi | D gibi | D gibi | D gibi, artı geçmiş analiz belleği |

Tanım gereği sabit kalan değerler, ilgili metriğin altında yazılıdır; bunlar bir bulgu değil, yapının sonucudur ve raporda öyle okunmalıdır.

Kayıttaki "gösterilen cevap", kullanıcıya ulaşan metindir. Metni modelin yazdığı kayıtlarda (`answer_by = "model"`) sayımlar, sabit satırlar (yasal uyarı, dönem notu) ve E'de harness'in eklediği bellek bölümü çıkarıldıktan sonra yapılır. "Girişim" (`attempts`), modelin açıklama adımında yazdığı her cevaptır; reddedilenler dahil.

## Sayı ve tarih metrikleri

Ortak sayım (model metni için): **yazılan** = ayırt edilebilir sayılar (K-008 kuralına göre eşit olanlar bir sayılır) artı ayırt edilebilir tarihler. **Desteksiz** (halüsinasyon) = modelin görmediği değer: A–C'de (`data_shown = tool_outputs`) izin verilen tüm araç çıktılarının sayısal alanları ve tarihleri, D–E'de (`committed_evidence`) doğrulayıcının 5. kuralı (taahhüt edilmiş kanıt kümesi ya da sorunun kendisi; kaynak etiketi anılan cümlede yalnızca anılan kalemler). Sorudaki sayılar ve tarihler her zaman "görülmüş" sayılır. **Atıfsız** = modelin ne gördüğüne bakılmaksızın taahhüt edilmiş kanıt kümesi tarafından desteklenmeyen değer (D–E'de desteksiz ile aynıdır).

### `numeric_hallucination_rate` (gösterilen cevapta sayısal halüsinasyon oranı)

**Tanım:** Kullanıcıya gösterilen, modelin yazdığı metindeki sayı ve tarihlerin, modelin görmediği değerlere düşen payı.
**Payı:** gösterilen model metinlerindeki desteksiz sayı ve tarih toplamı (`numbers_unsupported`).
**Paydası:** aynı metinlerde yazılan sayı ve tarih toplamı (`numbers_written`); sıfırsa oran boştur (None).
**Deneylerde:** A–C'de ölçülen gerçek orandır. D ve E'de gösterilen metin doğrulayıcıdan geçtiği için bu oran **yapı gereği 0'dır**; kullanıcıya ulaşanı ölçer, modeli ölçmez. Modelin kendi oranı için bir sonraki metriğe bakın.
**Sınırlar:** Sayısı olmayan iddialar denetlenmez (yalnızca sayı ve tarih sayılır). Harness'in sabit cevapları ve kanıt kümesi geri dönüşü (`answer_by = "harness"`) sayıma girmez. Bellek bölümü yalnızca harness onu eklemişse (izdeki kayıttan yeniden kurulabiliyorsa) çıkarılır.

### `model_numeric_hallucination_rate` (model düzeyinde halüsinasyon oranı)

**Tanım:** Aynı sayım, modelin yazdığı her girişim üzerinde: doğrulayıcı reddettikleri dahil. Doğrulayıcıdan önceki model davranışını ölçer.
**Payı:** tüm girişimlerdeki desteksiz sayı ve tarih toplamı (`model_numbers_unsupported`).
**Paydası:** tüm girişimlerde yazılan sayı ve tarih toplamı (`model_numbers_written`).
**Deneylerde:** D–E'de gösterilen cevaptaki oran 0 iken bu oran sıfırdan büyük olabilir; iki oran ayrı raporlanır. A–C'de tek bir serbest cevap vardır, iki oran eşittir.
**Sınırlar:** Reddedilen girişimin hepsi sayılır; aynı soruda yeniden yazılan metin tekrar sayılır. Sayısı olmayan iddialar denetlenmez.

### `uncited_number_rate` (atıfsız sayı oranı)

**Tanım:** Gösterilen model metnindeki sayı ve tarihlerden taahhüt edilmiş kanıt kümesi tarafından desteklenmeyenlerin payı.
**Payı:** atıfsız sayı ve tarih toplamı (`numbers_uncited`).
**Paydası:** gösterilen model metinlerinde yazılan sayı ve tarih toplamı (`numbers_written`).
**Deneylerde:** A ve B'de kanıt etiketi olmadığından değer yüksektir (kanıt kümesi boş); D–E'de desteksiz sayıya eşittir, dolayısıyla 0'dır.
**Sınırlar:** Sayı olmayan iddialar denetlenmez; harness metni dışarıda kalır.

## Araç ve sonuç metrikleri

### `wrong_tool_call_rate` (yanlış araç çağrısı oranı)

**Tanım:** Modelin önerdiği çağrılardan reddedilenlerin payı (şema, izin, niyet; bozuk çağrılar dahil). Niyet reddi (`INTENT_MISMATCH`) sorunun adlandırdığı hisse, sektör, tarihler ve dönüş olayı ailesi ile yönünü kapsar.
**Payı:** reddedilen model çağrıları (`rejected_calls`).
**Paydası:** modelin önerdiği tüm çağrılar (`proposed_calls`); harness'in çağrıları öneri değildir.
**Deneylerde:** A'da model çağrı yapamaz (harness verir), payda 0'dır ve oran boştur. B'de yalnızca şema ve izin reddi vardır; niyet denetimi D–E'dedir.
**Sınırlar:** Reddedilmeyen ama gereksiz çağrı "yanlış" sayılmaz.

### `unsupported_conclusion_rate` (desteksiz sonuç oranı)

**Tanım:** Sonuç üreten kayıtlardan (etiketi `ANALYSIS_UNSAFE` dışındaki bir eylem) desteksiz olanların payı. Desteksiz: etiket `INVESTIGATE` değilken puanlama senaryosunun asgari kanıtı karşılanmıyorsa ya da doğrulamayı geçemeyen model metni gösterilmişse. E'de harness'in doğrulamadan sonra eklediği bellek bölümü doğrulanmaz; 20 Kasım 2026'dan önce yazılmış kayıtlar ölçülürken `shown_problems` ile bölümsüz olarak yeniden doğrulanır (K-089).
**Payı:** desteksiz sonuçlar (`unsupported_conclusions`).
**Paydası:** sonuç üreten kayıtlar (`conclusions`).
**Deneylerde:** A–C'de her sonuç **tanım gereği desteksizdir** (serbest cevaplarında atıf ve yasal uyarı satırı yoktur; A'da kalite denetimi çalışmadığı için kapı yalnızca `ANALYSIS_UNSAFE`'e izin verir); oran 1'dir. D–E'de ölçülen bir orandır.
**Sınırlar:** Yalnızca asgari kanıtın var olup olmadığına ve doğrulamaya bakar; kanıtın iddiayı yeterince desteklediğine dair anlamsal bir yargı yoktur.

### `evidence_completeness` (kanıt tamlığı)

**Tanım:** Analiz bekleyen sorularda, puanlama senaryosunun asgari kanıt gereksinimlerinden (`evidence.MINIMUM`) kaydın kanıtının karşıladığı payın ortalaması; reddedilen soru 0 puan alır (reddedilmesi gereken sorular puanlanmaz).
**Payı:** karşılanan gereksinim sayısı (kayıt başına).
**Paydası:** senaryonun gereksinim sayısı (kayıt başına); özet, kayıt puanlarının ortalamasıdır.
**Deneylerde:** A ve B'de kanıt etiketi olmadığından düşüktür. D–E'de kapı kanıt eksikse zaten engeller.
**Sınırlar:** `ANALYSIS_UNSAFE`'i de kabul eden bir soru (AM-10) o noktada biterse sonuç eşleşir ama eksik kanıtı puanlanır; bu yüzden `outcome_match_rate` ile birlikte okunur.

### `reproducibility_rate` (tekrarlanabilirlik)

**Tanım:** Bir deneyde en az iki kez çalıştırılan sorulardan, tüm çalıştırmalarda aynı sonuç etiketini ve aynı taahhüt edilmiş kanıt kümesini (araç, sonuç kimliği, alan, değer) veren soruların payı.
**Payı:** tekrarlanabilir sorular (`reproducible_questions`).
**Paydası:** en az iki kez çalışan ve hatasız sorular (`repeated_questions`); hatalı koşu içeren soru dışarıda bırakılır ve `reproducibility_excluded` olarak ayrıca sayılır.
**Deneylerde:** Metin farkı sayılmaz, yalnızca sonuç ve kanıt kümesi; A'da kanıt kümesi boş olduğundan yalnızca etiket karşılaştırılır.
**Sınırlar:** Hata veren iki koşu "yeniden üretilmiş sonuç" sayılmaz, bu yüzden dışarıda bırakılır.

## Kural ihlalleri ve harness davranışı

### `rule_violations` (kural ihlali sayıları)

**Tanım:** Üç sayaç ve toplamları. `guarded_tool_calls`: yalnızca korunmuş bir sonucun (ret, kapsam dışı, güvensiz) beklendiği soruda yürütülen çağrılar. `advice_shown`: gösterilen model metninin tavsiye ya da tahmin dili içermesi (doğrulayıcı 6. kural) için 1. `skipped_mandatory`: sonuç üreten kayıtta gerçekleşmeyen zorunlu adımlar: kalite denetimi (yürütülmüş `check_data_quality` çağrısı yok), kapı (gerçek bir kapı ile çalışan `RISK_GATE` yok) ve aday rotada geri test (yürütülmüş `run_backtest` yok).
**Payı:** ihlal sayıları (kayıtlar toplanır; `records_with_violation` ihlalli kayıt sayısıdır).
**Paydası:** yok; bu bir sayıdır, oran değildir.
**Deneylerde:** A en az iki adımı atlar (kalite denetimi ve kapı); B ve C en az kapıyı atlar. A geri test ile anılır: veri çağrıları (geri test dahil) modelin seçimi değil, kodun kanonik çağrılarıdır.
**Sınırlar:** Tavsiye dili yalnızca kural tabanlı bir kalıp listesiyle bulunur; kalıba girmeyen örtük tavsiye kaçar.

### `tool_calls_total` (araç çağrısı sayısı)

**Tanım:** Yürütülen (izin verilen) çağrılar, modelin ve harness'in.
**Payı:** yürütülen çağrılar (`tool_calls_mean` kayıt başına ortalamasıdır).
**Paydası:** yok (sayı; ortalama için kayıt sayısı).
**Deneylerde:** A'da yalnızca harness çağrılarıdır.
**Sınırlar:** Reddedilen çağrılar sayılmaz (onlar `wrong_tool_call_rate`'dedir).

### `harness_interventions` (harness müdahaleleri)

**Tanım:** Harness'in modelin araç durumunda yaptığı çağrılar (`max_attempts` sonrası geçerli çağrı yoksa geri dönüş ve modelin geçerli çağrılarından sonra senaryonun asgari kanıtını tamamlama), artı çağrı yapacak kanonik çağrısı olmayan geri dönüşlerin her biri için bir.
**Payı:** müdahale sayısı.
**Paydası:** yok (sayı).
**Deneylerde:** A'da araç durumu yoktur. Açıklama geri dönüşü ayrı sayılır.
**Sınırlar:** Müdahalenin gereksiz olup olmadığı değerlendirilmez.

### `explanation_fallbacks` (açıklama geri dönüşü)

**Tanım:** Açıklama adımında model geçerli bir cevap yazamadığı için kanıt kümesinin `INVESTIGATE` altında gösterildiği kayıtlar (izde `GENERATE_EXPLANATION` için `fallback = true`).
**Payı:** geri dönüş kullanan kayıtlar.
**Paydası:** yok (sayı; bir oran gerekirse kayıt sayısına bölünür).
**Deneylerde:** Yalnızca D–E'de anlamlıdır; A–C'de açıklama adımı yoktur.
**Sınırlar:** Geri dönüş metni harness'indir, bu yüzden sayısal halüsinasyon sayımına girmez.

## Niyet doğruluğu

Soru niyeti, modelin çıkardığı senaryo, hisse, sektör, tarihler ve dil alanlarından oluşur. Metrikler, soruyu bir analiz bekleyen ve alanı adlandıran kayıtlarda ölçülür.

### `scenario_accuracy` (senaryo doğruluğu)

**Tanım:** Modelin senaryo etiketinin sorunun kabul ettiği senaryolardan biri olduğu kayıtların payı; dayandırma (grounding) uygulanmaz.
**Payı:** senaryosu doğru olan kayıtlar.
**Paydası:** korunmuş sonuç beklemeyen ve niyeti olan kayıtlar.
**Deneylerde:** B'nin niyeti olmadığından boştur.
**Sınırlar:** Bir senaryo etiketi doğru olup alanlar yanlış olabilir; alanlar aşağıda ayrıca ölçülür.

### `ticker_accuracy_grounded` ve `ticker_accuracy_raw` (hisse doğruluğu)

**Tanım:** Sorunun hisse beklediği kayıtlarda niyetteki hissenin beklenene eşit olduğu kayıtların payı. `ticker_accuracy_grounded` saklanan niyeti (harness'in dayandırmadan sonra analiz ettiği; model artı dayandırma) ölçer; `ticker_accuracy_raw` modelin kendi hissesini (her `intent.grounded` çiftinin ilk öğesi) ölçer.
**Payı:** hissesi beklenene eşit olan kayıtlar (her iki sürüm için ayrı).
**Paydası:** hisse bekleyen, korunmuş sonuç beklemeyen ve niyeti olan kayıtlar.
**Deneylerde:** A'da dayandırma yoktur, iki oran eşittir; B'nin niyeti olmadığından boştur. D–E'de aradaki fark, dayandırmanın düzelttiği hatadır.
**Sınırlar:** Yalnızca hisse alanıdır; tarih ve sektör ayrıca değerlendirilmez.

### `invented_fields` (uydurulan alanlar)

**Tanım:** Modelin doldurduğu ama sorunun adlandırmadığı, dayandırmanın geri aldığı alanlar (kayıt başına `intent.grounded` anahtarları, `sector_unworded` ve `language` hariç), toplanır. `sector_unworded` (sektörü yalnızca adı geçen bir hissenin grubu olarak tutulan kayıtlar) ve `language_grounded` (dil etiketini soru metninin düzelttiği kayıtlar) ayrı sayılır.
**Payı:** dayandırılan alan anahtarları.
**Paydası:** yok (sayı).
**Deneylerde:** A'da dayandırma yok, değer 0'dır; B'de niyet yok.
**Sınırlar:** Dayandırılan her anahtar sayılır; bir hissenin yanlış yazılıp düzeltilmesi de bir anahtardır.

## Gecikme

### `latency_s_median`, `latency_s_mean`, `latency_s_max`

**Tanım:** Bir çalıştırmanın süresi (saniye, `latency_s`): ortanca, ortalama ve en büyük değer.
**Payı:** süreler toplamı (ortalama için); ortanca ve en büyük doğrudan değerdir.
**Paydası:** süresi kayıtlı çalıştırma sayısı.
**Deneylerde:** Model yanıt süresine ve uzak uç noktaya bağlıdır; deneyler arası karşılaştırma aynı donanımda yapılmalıdır.
**Sınırlar:** Hata veren koşuların süresi kaydı varsa dahildir.

## Geri test doğruluğu

### `backtest_accuracy` (geri test doğruluğu)

**Tanım:** Raporlanan geri test değerlerinin bağımsız yeniden hesapla eşleşmesi. Kayıtlardaki her yürütülmüş `run_backtest` çağrısı (izin verilmiş, çıktısında `error` olmayan) aynı araç, aynı argümanlar ve aynı veri sürümüyle yeniden çalıştırılır; raporlanan `cumulative_return_pct`, `win_rate_pct`, `max_drawdown_pct` ve işlem sayısı (`trades`) alanlarının hepsi yeniden hesaplananla birebir eşitse çağrı eşleşir.
**Payı:** eşleşen çağrılar (`matched`).
**Paydası:** yeniden çalıştırılan çağrılar (`compared`); hiç çağrı yoksa oran boştur (None). Uyuşmazlıklar çağrı kimliği (`deney/soru/tekrar#sıra`) ve alanla listelenir (`mismatches`); yeniden çalıştırması hata veren çağrı `rerun` alanıyla bir uyuşmazlıktır.
**Deneylerde:** Geri test çağrısı yalnızca aday rotalarda (ve B'de modelin seçtiği yerde) vardır; A'da çağrılar harness'indir ama aynı biçimde sayılır. Hesap, yalnızca `--backtest-accuracy` ile (yavaş olduğu için varsayılan kapalı) çalıştırılır ve özetin her deneyinin `backtest_accuracy` bloğuna yazılır.
**Sınırlar:** "Bağımsız" burada şudur: aynı veri sürümüyle aracın yeniden çalıştırılması, saklanan çıktıdan değil motorun yeni bir çalışmasından gelir; ayrı bir uygulamayla yazılmış ikinci bir motor değildir, dolayısıyla motorun kendi hatasını yakalamaz, yalnızca raporlanan değerin motorun ürettiğiyle ya da veri sürümü değişimiyle bozulmadığını gösterir. Değerler tam eşitlikle karşılaştırılır (yuvarlanmış çıktılar aynı yuvarlamayla gelir); tolerans yoktur.

## Diğer sayaçlar

`outcome_match_rate` (sonucu beklenenle eşleşen kayıtların payı), `trap_handling_rate` (yalnızca korunmuş sonuç beklenen sorularda eşleşme), `false_refusal_rate` (analiz beklenirken reddedilen ya da kapsam dışı sayılan kayıtlar) ve `errors` (hata ya da etiketsiz sonuç) kod ve test düzeyinde tanımlıdır; ayrıntı `src/bist_harness/eval/metrics.py` içindeki `summarize_experiment` fonksiyonundadır.
