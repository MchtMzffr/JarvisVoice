# Jarvis Voice 0.2.0

Windows'taki mevcut **Ollama + gpt-oss:20b** kurulumuyla çalışan Türkçe sesli sohbet uygulaması. Beğendiğin **EMA Lightning sesi korunuyor**. Bu sürüm sesli tanışma, mikrofon kontrolü, tercihlerin kalıcı kaydı, süre ölçümleri ve isteğe bağlı yerel akustik inceleme ekler.

**Duygu veya hastalık sınıflandırıcısı içermez.** Sesin ölçülebilir özelliklerini çıkarır; kişinin ne hissettiğini onun anlatımından öğrenmeye çalışır. Destekleyici sohbet hedeflenir; klinik etkinlik veya terapi hizmeti doğrulanmış değildir. Teknik kanıtlar ve geliştirme sınırları: `docs/SES_ANALIZI_KANITLARI.md`.

## Zaten çalışan 0.1.0 kurulumu varsa

1. Açık Jarvis terminalini **Ctrl+C** ile kapat. Ollama açık kalabilir.
2. Yeni ZIP'i **eski kurulumdan ayrı, onun içine girmeyen bir klasöre** çıkar. ZIP içinden çalıştırma.
3. **Yeni klasördeki GUNCELLE.cmd** dosyasını aç. Dosya seçicide **çalışan eski kurulum klasörünün BASLAT.cmd** dosyasını seç.
4. Başarı mesajından sonra **eski kurulum klasöründeki BASLAT.cmd** ile devam et. Sayfa açıksa yeniden yükle.

Güncelleyici mevcut uygulamaya özel Python'u kullanır. Bağımlılık listesi değişmediği için paketleri, GPT-OSS'u ve yaklaşık 525 MB ses dosyasını yeniden indirmez. `data`, `.venv` ve `.runtime` klasörlerini değiştirmez. Değişen eski kodu `backups` altında SHA256 bilgileriyle yedekler; normal yazma hatasında değişiklikleri geri almaya çalışır. Windows dosya seçicisinin gerçek Windows çalışması bu geliştirme ortamında sınanmadı; taşınabilir güncelleme mantığının testleri pakettedir.

Bu yol yalnız tamamlanmış 0.1.0 veya 0.2.0 kurulumu içindir. **Yeni boş klasörde BASLAT.cmd açmak yerine eski kurulum üzerinden devam et.** Güncelleme sonrası yeni paketin ayrı klasörü çalışma için gerekli değildir; ZIP'i yedek tutabilirsin.

## İlk kez kuruyorsan

1. ZIP'i kalıcı bir klasöre çıkar.
2. Ollama'yı aç; `ollama list` içinde `gpt-oss:20b` bulunduğunu kontrol et.
3. **KUR.cmd** dosyasını aç. Python 3.11, sabit CPU paketleri ve ses dosyaları ilk kurulumda internetten indirilir.
4. Kurulum tamamlanınca **BASLAT.cmd** dosyasını aç.
5. Yerel sayfada **Konuşmaya başla** düğmesine basıp mikrofon izni ver. Terminal penceresi açık kalmalı.

Kurulum genel Python ortamını değiştirmez. Uygulamanın Python'u `.runtime`, paketleri `.venv`, modelleri ve onaylı kişisel ayarları `data` altında tutulur. `SES_ORNEGI.wav`, aynı EMA sesinin önceki sürümde oluşturulmuş örneğidir.

## İlk konuşma: sesli tanışma

İlk başlangıçta Jarvis sırasıyla şunları sorar:

- Sana nasıl hitap edeceği.
- Kendisine hangi ismi vereceğin.
- Samimi, dengeli veya resmî konuşma tercihin.
- Kısa, orta veya ayrıntılı yanıt tercihin.
- Sözünü bitirmen için kısa, dengeli veya rahat bekleme süresi.
- Kulaklık mı hoparlör mü kullandığın.

Örneğin “Adım Muzaffer”, “Sana Atlas diyeyim”, “Samimi konuş”, “Kısa cevap ver” diyebilirsin. Sonunda tercihleri okuyup onay ister; **son onaydan önce profil dosyası yazılmaz**. “Tekrar”, “iptal” veya “baştan başla” diyebilirsin. Mikrofonu kapatıp aynı oturumda açınca yarım kalan adıma dönülür; sekmeyi kapatmak kaydedilmemiş taslağı siler.

Yeniden değiştirmek için **“Yeniden tanışalım”** de veya **Tanışma ve sana göre ayarlar** bölümünü aç. Formdaki değişiklikler yalnız **Tercihleri kaydet** düğmesiyle uygulanır. Bu sürüm tek yerel profil kullanır; sesinden kim olduğunu tanımaz ve farklı kişileri otomatik ayırmaz.

Duraklama tercihleri 16 kHz / 512 örnek kareleri üzerinden yaklaşık **544 / 800 / 1216 ms** sessizlik bekler. Bunlar toplam yanıt gecikmesi değildir. Daha kısa bekleme, doğal duraksamalarını sözün bitişi sanma riskini artırır. Kulaklık tercihi sesli araya girmeyi kendiliğinden açmaz.

## Mikrofonu birlikte ayarlama

**“Mikrofonu ölç”** de veya aynı adlı düğmeye bas:

1. Jarvis yönergesini tamamen bitirir.
2. Yaklaşık üç saniye sessiz kalmanı ister; ortamın dijital ses seviyesini ve VAD davranışını ölçer.
3. Şu cümleyi söylemeni ister: “Bugün seninle sakin ve doğal bir şekilde konuşmak istiyorum.”
4. Duyulan cümleyi, kelime farkını, yaklaşık konuşma/ortam seviye farkını ve kırpılmayı gösterir.
5. Kontrol uygunsa **Mikrofon ayarını uygula** seçeneği görünür. Aynı ifadeyi sesle de söyleyebilirsin.

Bu işlem model eğitimi, ses kimliği kaydı veya duygu kalibrasyonu değildir. Tarayıcı işleme etkileri altında kısa bir mikrofon kontrolüdür. Kalıcı olarak yalnız sınırlandırılmış VAD eşiği saklanır. Ham ses ve örnek cümle diske yazılmaz. Kötü örnekte ayar uygulanmaz; mikrofon mesafesini/giriş seviyesini düzeltip tekrar dene.

## İsteğe bağlı ses özellikleri

**Ayarlar → Ses özelliklerini incele (deneysel)** varsayılan olarak kapalıdır. Açınca, tamamladığın her normal sesli tur için yerel Python şu ölçümleri üretir:

| Ölçüm | Ne anlatır? |
|---|---|
| Süre, RMS/tepe dBFS | Tarayıcının işlemiş olduğu dijital ses; fiziksel desibel/SPL değildir. |
| Kırpılma yüzdesi | Tam dijital ölçeğe yaklaşan örneklerin oranı. |
| Konuşma/duraklama oranı | VAD karelerinden yaklaşık oran; dilbilimsel duraklama etiketi değildir. |
| Kelime/dakika | ASR'nin tanıdığı kelimeler / duraklamalar dâhil kayıt süresi; ASR hatasından etkilenir. |
| Temel frekans medyanı/aralığı | Yeterli periyodiklik bulunan karelerde yaklaşık F0; uygun sinyal yoksa değer üretilmez. |
| Mikrofon işleme ayarları | Gerçek `getSettings()` çıktısından örnekleme, kanal, yankı/gürültü giderme ve otomatik kazanç bilgisi. |

Ölçümler yerel modele metin olarak aktarılabilir; GPT-OSS ses dalgasını doğrudan duymaz. Bu değerlerden “öfkelisin”, “utandın”, “hastasın” gibi sonuçlar çıkarmaması istenir. **İstem kuralı, modelin her yanıtının doğru veya güvenli olacağını matematiksel olarak garanti etmez.** Duygu sınıflandırma başarısı iddia edilmez.

Ölçümler normal sohbet sırasında RAM'dedir; ayrı dosyaya/loga yazılmaz ve profilin parçası yapılmaz. Kapatınca önceki tur iptal edilir; gecikmiş ölçüm yeni yanıta taşınmaz. Tanışma ve mikrofon kontrolü zaten bu analizi kullanmadığından kapatma bu rehberleri kesmez. Bağlantı yeniden kurulunca seçenek kapalı başlar. Aygıt kimliği, grup kimliği ve cihaz etiketi alınan ölçüm sözleşmesine konmaz.

İnternet açıkken arama kararı ses ölçümü nesnesini almaz. Ölçüm gerekiyorsa araçsız ayrı bir yerel yanıt çağrısı yapılır; arama gerekmeyen turda bile bu **ek gecikme** yaratabilir. Arama servisine gönderilen sorgu yine model tarafından üretilir; konuşma içeriğindeki kişisel bilgilerin hiçbir koşulda sorguya girmeyeceği garanti edilmez. İnternet kapalıyken bu ek araç-kararı çağrısı yoktur.

## Günlük sohbet

- **Mikrofonu kapat:** mikrofon akışını ve o anki yanıtı durdurur.
- **Sesi kes:** yanıtı keser; mikrofon açıksa dinleme sürer.
- **Konuşma dökümünü göster:** transkript ve varsa gerçek arama kaynaklarını açar.
- **Yazarak dene:** mikrofon kullanmadan aynı dil modeli ve sesi dener.
- **Son yanıtın süreleri:** ASR, model ilk metni, ilk ses hazırlığı ve TTS gerçek zaman oranını gösterir.

Varsayılan olarak Jarvis konuşurken mikrofon aktarımı duraklar. Kulaklıkla **Konuşurken de beni dinle** seçeneğini açabilirsin. Hoparlör yankısı tarayıcı/cihaz düzenine bağlıdır. Tek konuşma yaklaşık **30 saniye** ile sınırlıdır; sınır dolarsa eksik düşünceye cevap üretmek yerine mikrofon durur. Bu sürüm kısmi metni konuşurken akıtan bir ASR kullanmaz.

## İnternet araştırması ve hafıza

Yerel sohbet için API anahtarı gerekmez. İnternet araştırması için [Ollama anahtar sayfasından](https://ollama.com/settings/keys) bir anahtar oluşturup uygulamadaki parola alanıyla bağla; ardından **Güncel bilgi için internete bak** seçeneğini aç. Güncel kota ve koşullar servise aittir: [resmî belge](https://docs.ollama.com/capabilities/web-search).

Anahtar yalnız oturum RAM'inde tutulur; giriş alanı temizlenir, dosyaya veya tarayıcı depolamasına yazılmaz. Her tur en fazla bir arama ve iki sayfa getirme yapılır. Sorgular ve URL'ler Ollama'nın internet servisine gider; yanıt modeli yerel kalır. Kaynak göstermek, her cümleyi otomatik doğrulamış olmak değildir. Bu ortamda canlı web anahtarıyla uçtan uca test yapılmadı.

Kalıcı kısa notlar yalnız doğrudan kullanıcı komutuyla kaydedilir:

- “Bunu hatırla: Yürüyüş yapmayı severim.”
- “Neleri hatırlıyorsun?”
- “Tüm hatıralarımı sil.”

Profil `data/profile.json`, mikrofon eşiği `data/audio_calibration.json`, açıkça kaydedilmiş notlar `data/memories.sqlite3` içindedir. Bu dosyalar şifrelenmiş değildir. Son komut yalnız hatıraları siler; profil ve mikrofon ayarları ayrı tutulur. Normal sohbet, ses ve ölçümler kalıcı kayda alınmaz. Model bir ölçümü sözlü yanıtta açıklarsa o metin normal oturum geçmişinde bulunabilir. 4096 token bağlam doldukça eski turlar düşürülür; yalnız tamamen oynatılan yanıt cümleleri geçmişe işlenir.

## Mimari ve performans kararı

| İş | Bileşen / yer |
|---|---|
| Yanıt | Mevcut gpt-oss:20b, think=low, ctx4096 / yerel Ollama |
| Konuşma sınırı | Silero V6 / CPU |
| Türkçe ASR | Whisper small, CTranslate2 int8 / CPU |
| Ses üretimi | Aynı EMA Lightning 1.1.2 / CPU |
| Akustik ölçüm | NumPy, sınırlı kare analizi / ayrı CPU işi |
| Arayüz | Yerel tarayıcı, WebAudio / 127.0.0.1:8765 |

Ollama'nın güncel resmî belgelerinde kendi konuşma üretim API'si vardır; belgelenen Phonon modeli İngilizcedir. İncelenen belgelerde bu EMA sesini, tanışmayı ve ölçüm panelini mevcut masaüstü arayüzüne eklenti olarak takmanın desteklenen yolu bulunamadı. Bu nedenle kendi yerel arayüzümüz mevcut Ollama API'sine bağlanır. Bu uygulama Ollama'nın bir fork'u değildir. [Ollama Speech](https://docs.ollama.com/capabilities/speech).

0.2.0 mevcut modeli başlangıçta yüklemeyi dener, isteklerde `keep_alive=30m` kullanır, HTTP bağlantısını yeniden kullanır, sabit yönergelerin sesini RAM'de en fazla 24 giriş/8 MiB ile önbellekler ve isteğe bağlı ses analizini ASR ile paralel başlatır. Bunlar belirli bir Windows gecikmesi garanti etmez. Uzun `keep_alive` modelin bellekte daha uzun kalmasına yol açabilir. GPU/CPU ASR karşılaştırması ve gerçek mikrofon gecikmesi ayrıca ölçülmelidir.

## Gizlilik, sınırlar ve sorun giderme

Sunucu yalnız loopback üzerinde çalışır; WebSocket origin, rastgele açılış anahtarı, tek oturum ve protokol sürümü denetlenir. Yüksek hızda tur oluşumu sınırlandırılır. Ses/model işlerindeki iptal eski çıktıyı düşürür; başlamış native CPU hesabını zorla öldürdüğünü varsaymaz.

Ses modelleri normal çalıştırmada yerel dosyalardan açılır. ONNX Runtime telemetrisi native importtan önce `ORT_DISABLE_TELEMETRY=1` ile kapatılır; Hugging Face çevrimdışı/telemetri ayarları da uygulanır. Bu, Windows/tarayıcı/Ollama'nın bütün ağ trafiğinin sistem düzeyinde denetlendiği anlamına gelmez.

| Durum | İşlem |
|---|---|
| Model/bağlantı hatası | Ollama'yı aç; `ollama list` içinde gpt-oss:20b'yi kontrol et. |
| Eski arayüz / protokol uyuşmazlığı | Eski sekmeyi kapat; güncellenmiş BASLAT.cmd ile aç. |
| Mikrofon reddedildi | Tarayıcı site izni ve Windows mikrofon gizlilik ayarını kontrol et. |
| Kendi sesine cevap veriyor | Kulaklık kullan; konuşurken dinleme seçeneğini kapat. |
| Kelimeler yanlış | Mikrofon kontrolünü çalıştır; ASR transkriptini incele. |
| Cümlem yarıda kesiliyor | Duraklamayı “Rahat” seç; bu toplam yanıt süresini uzatır. |
| Profil/kalibrasyon dosyası bozuk | Hata mesajındaki dosyayı yedekleyip kaldır; uygulama varsayılana döner. |
| 8765 portu dolu | Önceki Jarvis terminalini kapat; başka süreci otomatik sonlandırmaz. |
| DLL yüklenmiyor | [Microsoft Visual C++ x64 Runtime](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) gereksinimini kontrol et. |

### Güncelleme kurtarma

Güncelleme yazma hatasında otomatik geri alma sonucunu bildirir. İşlem zorla kapatılırsa veya elektrik kesilirse `backups/<zaman-kimlik>/manifest.json` ve `files/` kalır. Jarvis ve güncelleyici kapalıyken yedekteki eski dosyalar aynı göreli yollara geri konabilir. Yeni eklenen dosyalar ancak manifestte `old_sha256=null` olması ve mevcut SHA256 değerinin `new_sha256` ile eşleşmesi durumunda kaldırılmalıdır; kullanıcı değişikliklerini silme. `.jarvis-update.lock` dosyasını yalnız çalışan güncelleme olmadığını ve kodun tutarlı biçimde geri alındığını/güncellendiğini doğruladıktan sonra kaldır. Emin değilsen hata ve manifesti incelet; modeli/veri klasörünü silme.

## Kanıt ve geliştirme

`docs/VALIDATION.md` yapılan ve yapılamayan testleri; `docs/CONTRACT.md` protokol/invariantları; `docs/PARAMETER_INDEX.md` tek parametre kaynağını; `docs/COMPATIBILITY.md` sürüm ve şema uyumluluğunu açıklar. Kaynak kodları ve testler pakette bulunur.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Geliştirme için JavaScript testleri (kullanıcı kurulumunda Node gerekmez):

```text
node --test tests/test_frontend.js tests/test_resampler.js
```

Kullanıcının 0.1.0 Windows kurulumu başarıyla tamamlandı ve ses beğenildi. Bu yeni sürümün fiziksel Windows mikrofonu, gerçek tarayıcı oynatması, canlı Ollama birleşimi ve güncelleme dosya seçicisi burada uçtan uca çalıştırılmadı. Ses kontrolünde tek bir örnekte WER=0 veya çok sayıda geçen birim testi, genel Türkçe/duygu/klinik başarı oranı değildir.
