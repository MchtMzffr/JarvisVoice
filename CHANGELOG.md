# Değişiklik geçmişi

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
