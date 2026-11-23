# Değişiklik geçmişi

## 0.3.0 — 23 Kasım 2026 — geliştirme/doğrulama

### Eklendi

- Windows'ta pywebview 6.2.1 / WebView2 ile tek masaüstü penceresi; yazılı ve sesli sohbet, profil/kalibrasyon ve plan kartları aynı arayüzde bulunur. `BASLAT.cmd` masaüstü başlatıcıyı kullanır; açık tarayıcı modu alternatif olarak kalır.
- Normal yanıtta seslendirme tercihi. Sessiz mod TTS'yi atlar ve yalnız tamamlanmış yanıtı oturum geçmişine ekler; tanışma/mikrofon yönergeleri sesli kalır.
- Oturum başında kapalı uygulama açma izni ve dört sabit Windows uygulaması: Hesap Makinesi, Not Defteri, Dosya Gezgini, Paint. Doğrudan kullanıcı komutu, güncel epoch, hız ve tekrar kontrolü gerekir; model/web çıktısı süreç başlatamaz.
- Yerel JSON şemasına bağlı plan taslağı, plan kartları ve açık kaydet/göster/iptal/sil komutları. Taslak RAM'de 600 saniye; açık kayıt tek planı `data/plan.json` içinde saklar. Plan adımları otomatik yürütülmez.
- `setup_local.py`: WebView2/Ollama denetimi, mevcut servisi başlatma ve yalnız açık kurulum modunda eksik sabit paket/modeli tamamlama. Mevcut GPT-OSS ve beğenilen EMA sesi korunur.
- Model indirmeyen tam test ortamı için `tests/install_check_dependencies.py`; sürümleri proje ve kilit dosyasından alır, çevrimdışı `--validate-only` seçeneği vardır.

### Değişti

- WebSocket protokolü **3** oldu; frontend/backend birlikte güncellenir. Protokol 2 arayüzü yeni backend tarafından kabul edilmez. Profil, mikrofon kalibrasyonu, akustik gözlem ve hatıra şemaları korunur; yeni plan şeması **1**'dir.
- Windows'a özel `desktop` ek bağımlılıkları eklendi. `GUNCELLE.cmd`, çevrimdışı kod aktarımından sonra hedef kurulumun `KUR.cmd` denetimini çalıştırır. Paket/servis kurulumunun geri alınması kod aktarımı rollback'inin kapsamı değildir.
- Normal `BASLAT.cmd` kurulum denetimi yapar; yazılım/model indirmez. Pencere kapanışında Jarvis'in sahip olduğu yerel sunucu kapatılır; ortak Ollama servisi korunur.
- Yanıt sınırında kesilen model akışı tamamlanmış yanıt gibi kaydedilmez. Plan alanları, geçersiz JSON, eski epoch ve yinelenen kayıt/açma istekleri için sınırlar/regresyonlar eklendi.

### Doğrulama durumu

0.3.0 native Windows/WebView2 CI ve kullanıcı masaüstü kabulü **henüz bekleniyor**. Güncel test sayıları ve ortamlar `docs/VALIDATION.md` içinde tutulur. Birim/sahte süreç testleri fiziksel ses, açılmış uygulama penceresi, gerçek GPT-OSS plan kalitesi veya performans artışı kanıtı değildir. Kullanıcının önceki sürümdeki olumlu konuşma/kalibrasyon geri bildirimi bu yeni sürümün kabulü yerine geçmez.

0.1.0/0.2.0/0.2.1/0.3.0 kurulumları için kod geçişi tanımlıdır; ayrıntılı sınırlar `docs/COMPATIBILITY.md` ve `docs/DESKTOP_0_3.md` içindedir.

## 0.2.1 — 23 Kasım 2026

### Düzeltildi

- Windows güncelleme ön kontrolü kısa TCP bağlantı yoklaması yerine `SO_EXCLUSIVEADDRUSE` ve geçici IPv4 wildcard bind kullanır. Probe dinleme/bağlanma yapmaz.
- Boş, kullanımda ve bilinmeyen durumları ayrılır; bilinmeyen durumda kod yazılmaz. Hata aşaması ve sayısal errno/winerror görünür, serbest OS hata metni gösterilmez.
- Ön kontrolün kendisini ve yazma kapılarını kapsayan regresyon testleri; gerçek Windows için üç geçici port testi eklendi.
- Windows geri alma testinde geçici dizin yolu kanonikleştirildi; hata benzetimi ve üretim kodu aynı dosyayı karşılaştırır, geri alma beklentileri korunur.

### Geliştirme

- Kaynak, test ve kanıt belgeleri GitHub `main` dalına alındı.
- `AGENTS.md`, `docs/PROJECT_STATE.md`, `docs/ROADMAP.md` ile çalışma devri ve gelişim takibi eklendi.
- Windows/Linux için model indirmeyen GitHub Actions kontrolleri eklendi; [doğrulanmış koşum](https://github.com/MchtMzffr/JarvisVoice/actions/runs/45194537357) ve kapsamı `docs/VALIDATION.md` içinde kayıtlıdır.
- `.gitignore` kişisel verileri, model/ortam klasörlerini, yedekleri ve kimlik bilgilerini kapsam dışında tutar.

Protokol 2 ve kalıcı şemalar 1 olarak kalır. Python bağımlılıkları, ses modeli ve ses üretim adaptörü değişmez. 0.1.0/0.2.0 kurulumlarına çevrimdışı kod güncellemesi uygulanabilir.

## 0.2.0 — 23 Kasım 2026

Sesli tanışma ve onaylı profil, mikrofon kalibrasyonu, isteğe bağlı akustik gözlem, gecikme panelleri, model ön yükleme, yönerge ses önbelleği ve çevrimdışı güncelleyici eklendi. Linux'ta 94 Python +25 JavaScript testi geçti. Sonraki kullanıcı denemesi Windows port kontrolünde durdu.

## 0.1.0 — 23 Kasım 2026

Mevcut Ollama/GPT-OSS ile yerel Türkçe sesli sohbet; Whisper small CPU/int8, Silero VAD, EMA TTS, isteğe bağlı internet araştırması ve açık komutla hatıra kaydı. Kullanıcı Windows kurulumunu başarıyla tamamladığını bildirdi.
