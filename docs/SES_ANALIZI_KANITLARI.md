# Yerel ses analizi ve destekleyici sohbet — kanıt ve uygulama kararı

Tarih: 23 Kasım 2026. Kapsam: gönderilen teknik önerinin Jarvis Voice kodu ve seçilmiş birincil kaynaklarla incelenmesi. Bu belge klinik kullanım izni, bütün literatürün sistematik taraması veya bir duygu modelinin Türkçe doğrulama raporu değildir.

## 1. Teknik sonuç

**Python sesi alabilir ve inceleyebilir; mevcut uygulama zaten PCM sesi Python'a gönderiyor.** Eksik parça, bu dalgadan ölçüm çıkarıp yanıt üretimine kontrollü biçimde katmaktı. 0.2.0 bu parçayı isteğe bağlı olarak ekler. Güncel GPT-OSS-20B model belgesi metin giriş/çıkışı ve desteklenmeyen ses girişini açıkça ayırır. Ölçümleri metne çevirerek modele vermek onu doğrudan ses modeli yapmaz. [OpenAI model belgesi](https://developers.openai.com/api/docs/models/gpt-oss-20b).

Python'ın mikrofonu tarayıcısız açması da mümkündür: `sounddevice.InputStream/RawInputStream` ses giriş akışları sağlar. Bu sürümde ikinci bir mikrofon yakalama katmanı eklenmedi; tarayıcıdan mevcut gelen PCM analiz için yeterli. Doğrudan giriş tercih edilirse aygıt seçimi, callback iş yükü, yankı kontrolü, örnekleme ve kapatma davranışı yeniden doğrulanmalıdır. [sounddevice akış API'si](https://python-sounddevice.readthedocs.io/en/latest/api/streams.html).

Ollama v0.40.9 ve sonrasının belgelenen konuşma üretim desteği, Gradium'un İngilizce Phonon modelini kullanır. Bu, mevcut EMA Türkçe sesini veya Jarvis'in tanışma/analiz panelini masaüstü arayüzüne yükleyen belgelenmiş bir eklenti arayüzü değildir. İncelenen belgelerde böyle bir EMA entegrasyon yolu bulunmadığından yerel UI + mevcut Ollama API'si kararı alındı. [Ollama Speech](https://docs.ollama.com/capabilities/speech), [Modelfile](https://docs.ollama.com/modelfile).

## 2. Ölçüm, duygu tahmini ve hastalık ayrı iddialardır

| Katman | Kanıtlanabilecek örnek | Bunun tek başına kanıtlamadığı şey |
|---|---|---|
| Dijital sinyal | RMS, tepe, süre, kırpılma, periyodiklik | Kullanıcının gerçek ortam ses basıncı veya iç duygusu |
| Konuşma çıkarımı | ASR kelime dizisi, VAD kare oranı | Eksiksiz anlama, dilbilimsel duraklama/ritim doğruluğu |
| Duygu sınıflandırma | Belirli veri/etiket protokolündeki model hatası | Her yeni insanın gerçek hissini kesin bilmek |
| Kişisel değişim | Aynı aygıt/koşulda önceki örneğe göre fark | Değişimin nedeni, kişilik veya tanı |
| Klinik sonuç | Belirli hasta grubu ve çalışma tasarımındaki sonuç | Başka bir yerel modelin tedavi etkisi |

Yüksek RMS mikrofon mesafesinden; F0 değişimi vurgu, konuşma biçimi veya ölçüm hatasından; yavaş tempo metin zorluğu ya da ASR hatasından etkilenebilir. Bu gözlemleri doğrudan kızgınlık/utanç/korku/hastalık etiketlerine çevirecek tekil bir invariant yoktur. Bu nedenle paket bir eşik tablosuyla duygu üretmez.

`MediaStreamTrack.getSettings()` gerçekten uygulanmış ayarları verir. Tarayıcıya bir constraint istemek, her aygıtta aynı değerin uygulandığını göstermez. 0.2.0 yalnız beş sayısal/boolean ayarı taşır; cihaz kimliklerini çıkarır. Kazanç/yankı/gürültü işlemleri altında ölçülen seviye, laboratuvar mikrofon ölçümü gibi yorumlanmamalıdır. [MDN getSettings](https://developer.mozilla.org/en-US/docs/Web/API/MediaStreamTrack/getSettings).

## 3. İncelenen duygu modeli ve Türkçe kanıt

**emotion2vec+ large** model kartı yaklaşık 300M parametre, 16 kHz giriş ve dokuz sınıf bildirir: angry, disgusted, fearful, happy, neutral, other, sad, surprised, unknown. Utanç, heyecan ve hastalık ayrı çıktı sınıfları değildir. Kartta Türkçe için ayrılmış doğrulama sonucu bulunmadı; lisans `other/model-license` olarak işaretli. Bu sürüme indirilmedi. [Resmî model kartı](https://huggingface.co/emotion2vec/emotion2vec_plus_large/blob/main/README.md).

Orijinal emotion2vec ACL 2024 çalışması on dilde değerlendirme sunar; Tablo 1/Ek B.3'te Türkçe yoktur. Makaledeki temsiller ve hedef veriyle eğitilen sınıflandırıcı sonuçlarını sonradan yayımlanan `+large` modelinin Türkçe sıfır örnek başarısı gibi kullanmak doğru değildir. [Birincil makale](https://aclanthology.org/2024.findings-acl.931.pdf).

**TURK-SER (2026)** 90 konuşmacı/beş sınıfla %85,44 doğruluk bildirir. Ancak veri bölme örnek düzeyindedir; konuşmacı bağımsız değerlendirme gelecekteki çalışma olarak belirtilir. Kontrollü kayıt ve sınırlı cümle/yaş kapsamı da vardır. Bu yüzde yeni bir Jarvis kullanıcısının doğruluğu değildir. [Birincil PDF](https://dergipark.org.tr/en/download/article-file/5711339).

Mühendislik sonucu: model adayları araştırmaya değer; kendi Türkçe, konuşmacı/oturum ayrılmış değerlendirmemiz olmadan doğruluk veya güven yüzdesi vaat etmek için kanıt yok. Yalnız kullanıcının ses kaydını modele çalıştırıp ekranda bir sınıf görmek doğrulama sayılmaz.

## 4. Hastalık ve terapi iddiaları için kanıtın sınırı

Coppock ve arkadaşlarının COVID-19 ses çalışmasında 67.842 kişinin verisi kullanıldı; ROC-AUC, karıştırıcılar eşleştirildiğinde 0,846'dan 0,619'a geriledi. Bu COVID'e özgü sonuç bütün ses biyobelirteçlerini geçersiz kılmaz; gözlemsel yüksek skorun klinik yarar olarak sunulamayacağını gösteren somut bir örnektir. [Yazar kurumundaki birincil kayıt](https://kclpure.kcl.ac.uk/portal/en/publications/audio-based-ai-classifiers-show-no-evidence-of-improved-covid-19-/).

Therabot'un 210 yetişkinli randomize çalışması, uzmanlarca uyarlanmış metin tabanlı sistem için bekleme listesine göre belirtilerde iyileşme bildirdi. Dört haftalık müdahale ve sekiz haftaya kadar değerlendirmede 15 güvenlik müdahalesi, 13 uygunsuz yanıt düzeltmesi de raporlandı. Bu sonuç hazır GPT-OSS veya sesli Jarvis için etkinlik kanıtı değildir; terapistle eşdeğerlik deneyi de değildir. [Çalışmayı yürüten merkezin özeti](https://www.c4tbh.org/research-brief/randomized-trial-of-a-generative-ai-chatbot-for-mental-health-treatment/), [makale DOI](https://doi.org/10.1056/AIoa2400802).

Jarvis için mevcut ürün hedefi dinlemek, kullanıcının açıkça söylediği duyguyu dikkate almak, tercih ettiği destek biçimini sormak ve kısa uygulanabilir adımları birlikte düşünmektir. Örnek: “Zor bir gün olmuş. Biraz anlatmak mı istersin, yoksa seni rahatlatabilecek küçük bir şey mi düşünelim?” Bu, tasarlanan davranış örneğidir; ölçülmüş tedavi sonucu değildir.

Ses perdesinden kriz niyeti tahmin edilmez. Kullanıcı açıkça acil tehlike anlatırsa insan desteğine yönlendiren sistem yönergeleri vardır. Yerel model için klinik bir kriz taraması veya hatasız güvenlik katmanı doğrulanmamıştır.

## 5. Bu sürümde gerçekten eklenenler

- `jarvis/profile.py`: son onaya kadar RAM'de kalan sesli tanışma ve doğrulanan yerel profil.
- `jarvis/calibration.py`: üç saniye ortam + tek cümle testi; ölçüm uygun ve kullanıcı açıkça uygulamak istediğinde sınırlı VAD eşiği.
- `jarvis/audio_analysis.py`: süre/dBFS/kırpılma, yaklaşık VAD ve kelime temposu, sınırlı F0; sonuçlar gözlem sözleşmesinde.
- `jarvis/contracts.py::AcousticObservation`: duygu/kimlik/tanı alanı bulunmaz; uygun ölçüm yoksa null.
- `jarvis/server.py`: varsayılan kapalı analiz; ASR ile paralel sınırlı iş; güncel epoch kontrolü; kapatma sonrası geç sonuçları bırakma.
- `jarvis/llm.py`: onaylı profil ve isteğe bağlı yerel gözlem; arama kararı ölçümsüz, son yanıt araçsız. İki özellik birlikte açıkken ek yerel tur maliyeti olabilir.
- `jarvis/static/`: sesli rehber, ayarlar, gerçek capture bilgisi, ölçüm ve süre panelleri.
- `GUNCELLE.cmd` / `update_jarvis.py`: mevcut model/Python/veriyi koruyan çevrimdışı kod güncellemesi.

Çıktı belirli bir insanın duygusuna göre otomatik ses rengi değiştirmez; beğenilen tek EMA sesi korunur. “Sakin/samimi konuş” tercihi esasen metin üslubuna uygulanır. Çoklu kişi tanıma, ses klonlama, kısmi akış ASR ve duygu modeli eğitimi eklenmedi.

Mikrofon kalibrasyonu ile istatistiksel model kalibrasyonu farklı işlemlerdir. Üç saniye sessizlik ve tek cümle, duygu modelini o kişiye göre eğitmiş veya skorlarını olasılık olarak kalibre etmiş olmaz.

## 6. Sonraki duygu modeli için somut kabul planı

Bu bölüm gelecek çalışma önerisidir; mevcut paketin tamamladığı testler değildir.

### Sözleşme önce

Akustik gözlem korunur; deneysel duygu sonucu ayrı, sürümlü bir sözleşme olur: model kimliği/revision, dil, etiket kümesi, ham skorlar, belirsizlik/abstain nedeni, kalite durumu ve zaman aralığı. Model skoru kalibrasyon kanıtı olmadan yüzde güven diye gösterilmez. Kullanıcı beyanı, model tahmininden ayrı tutulur. Hastalık veya terapi kararı bu sözleşmeye otomatik eklenmez.

### Veri ve değerlendirme

Gönüllü açık katılım, kayıt amacı ve silme süreci belirlenir. Türkçe doğal konuşma, farklı oturum/mikrofon/gürültü koşulları ve çeşitli konuşmacılar gerekir. Aynı kişinin örnekleri train/test'e karışmaz. Kişisel uyarlama düşünülürse ayrı günlerde tutulmuş test gerekir. “Kişi ne hissetti?” öz bildirimi ile “dinleyici ne algıladı?” etiketi farklı hedeflerdir; birini diğerinin kesin gerçeği saymayız.

Sınıf dengesizliği için yalnız doğruluk yerine:

- UAR = sınıf başına recall değerlerinin ortalaması.
- Macro-F1 = sınıf başına F1 değerlerinin ortalaması.
- Sınıf bazlı hata matrisi ve konuşmacı düzeyinde bootstrap belirsizlik aralıkları.
- Kalibrasyon için Brier/ECE; uygun olmayan dil/sinyalde abstain oranı ve kabul edilen örneklerde hata.
- Mikrofon/gürültü/oturum bazında sonuç; ses+metin, yalnız metin ve yalnız akustik karşılaştırması.
- CPU yükü, bellek, ek ilk ses gecikmesi p50/p95; kapatma ve eski sonuç sızıntısı testleri.

Kabul eşiği test verisine bakılarak sonradan seçilmez. Önceden ayrılmış doğrulama verisinde seçilir, tutulmuş testte raporlanır. Türkçe değerlendirmede metin tabanlı karşılaştırmaya ölçülebilir yarar eklemiyorsa sohbet kararlarında kullanılmaz. Yalnız “%90 güven” eşiği koymak bu değerlendirmelerin yerini tutmaz.

### Konuşma davranışı ve klinik iddia

Düşük kaliteli/uygunsuz ses çıktısı bilinmiyor olur. Yararlı bir tahmin varsa bile “Kesin korkuyorsun” yerine kişinin kendi duygusunu soran kısa bir soru tercih edilir. Gereksiz teşhis, yargılayıcı dil ve sürekli duygu soruları ayrı senaryolarla değerlendirilir. İstenmeyen davranışta özellik kapatılabilir; sesli/yazılı stop yolunun çalışması korunur.

Bir gün “tedavi eder” gibi bir iddia hedeflenirse, tanımlı hedef grup/sonuç ölçütü, uygun karşılaştırma, uzman gözetimi, olumsuz olay izlemi ve bağımsız klinik çalışma gerekir. Bu, SER doğruluk testinden veya yerel kurulum başarısından çıkmaz.

## 7. Kendi bilgisayarında ilk kabul denemesi

Güncellemeden sonra önce sesli tanışmayı tamamla, mikrofon kontrolünü uygula ve gündelik üç kısa konuşma yap. Dökümde duyulan kelimeleri, sözünün erken kesilip kesilmediğini ve ses doğallığını kontrol et. Sonra isteğe bağlı analizi açıp ölçüm panelini incele; kapatınca yeni ölçüm gelmemeli. Kısa/rahat duraklama arasında bekleme farkını gözle.

Hız değerlendirmesinde aynı soru/benzer uzunluk, internet açık/kapalı ve model sıcak/soğuk durumları ayrı tutulmalıdır. İlk ses sunucuda hazır metriğini gerçek duyulma süresi diye raporlama. Bu deneme tek kişilik kullanım kontrolüdür; duygu veya hastalık doğruluğu çalışması değildir.
