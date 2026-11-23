# Uyumluluk ve kaynaklar — 0.3.0

| Bileşen | Sabit sürüm / sözleşme | Doğrulama kapsamı |
|---|---|---|
| Uygulama | 0.3.0 / protokol 3 | Sonuç ve koşum kimlikleri [VALIDATION.md](VALIDATION.md) içinde |
| Python | 3.11.18; proje Python 3.11 minor sürümüyle sınırlı | Windows kurulumu yönetilen Python ister; CI Python 3.11 kullanır |
| Ollama | Kullanıcının bildirdiği sürüm 0.40.17 | Var olan kurulum korunur; eksikse KUR.cmd resmî winget paketini kurar |
| Model | gpt-oss:20b / think low / 4096 | Kullanıcının mevcut modeli; eksikse yalnız açık kurulum aşamasında indirilir |
| Masaüstü pencere | pywebview 6.2.1 + pythonnet 3.2.1 | Windows için desktop extra; test kapsamı ayrıca kaydedilir |
| Web motoru | Microsoft Edge WebView2 Runtime | Evergreen runtime sürümü işletim sistemi tarafından güncellenir; Python lock dosyası runtime'ı sabitlemez |
| faster-whisper / CTranslate2 | 1.2.1 / 4.9.1 | Önceki sürümde gerçek CPU int8 yükleme/ASR; adaptör korunur |
| ONNX Runtime / PyAV | 1.32.0 / 16.1.0 | CPU; ONNX telemetri opt-out native importtan önce |
| EMA Lightning | 1.1.2 | Önceki sürümde gerçek Türkçe CPU sentezi; ses adaptörü değişmedi |
| PyTorch | 2.10.0+cpu | CPU wheel; CUDA Python paketi kurulmaz |
| normalizer-tr | 0.8.1 | Windows x64 wheel |
| tiktoken | 0.12.0 / o200k_harmony | Yerel doğrulanmış tokenizer dosyası |
| uv | 0.13.9 | Windows indirmesi SHA256 ile sabit |
| Geliştirici tarayıcı modu | --browser; Chrome / Edge WebAudio + AudioWorklet | Windows'ta varsayılan değildir; yalnız açık seçenekle kullanılır |

15 ana Python requirement korunmuştur. 0.3.0 yalnız Windows `desktop` optional dependency grubunu ekler; `uv.lock` onun geçişli paketlerini de sabitler. `KUR.cmd`, `uv sync --frozen --extra desktop` kullanır. Paket değişikliği uyumluluk/telemetri incelemesi gerektirir. Ollama ve WebView2 işletim sistemi paketleri bu lock'un kapsamında değildir.

## Geçiş ve veri matrisi

| Kaynak → hedef | Destek / işlem |
|---|---|
| Tamamlanmış 0.1.0 / 0.2.0 / 0.2.1 → 0.3.0 | Ayrı yeni kaynak klasöründe GUNCELLE.cmd; eski BASLAT.cmd seçilir. Kod yedeğinden sonra hedef KUR.cmd masaüstü bileşenlerini tamamlar. |
| 0.3.0 → 0.3.0 | Aynı güncelleyici yeniden uygulamayı destekler. |
| Doğrudan Git klonu içinde kurulmuş uygulama | Jarvis'i kapat → git pull --ff-only → KUR.cmd → BASLAT.cmd. Aynı klasöre GUNCELLE.cmd uygulanmaz. |
| Yeni kurulum | ZIP çıkar → KUR.cmd → BASLAT.cmd. Ollama/WebView2/model varsa yeniden kurulmaz/indirilmez. |
| Protokol 1 veya 2 arayüz → protokol 3 sunucu | Bağlantı reddedilir; bütün kaynak/statik dosyalar birlikte güncellenmeli. |
| SQLite user_version 1 / profil 1 / kalibrasyon 1 | Şemalar korunur; migration gerekmez. |
| Akustik gözlem 1 | Oturumluk; ham ses/ölçüm geçmişi kaydedilmez. |
| Plan 1 | Yeni isteğe bağlı data/plan.json; yokluğu normaldir. Eski sürümler dosyayı kullanmaz. |
| Bozuk veya gelecekteki kalıcı şema | Sessiz sıfırlama yok; dosya korunur ve ilgili işlem durur. |
| 0.3.0 kod geri alma | GUNCELLE'nin doğrulanmış kod yedeğiyle manuel. data korunur; plan eski sürümde kullanılmaz. |

**Kod geri alma ile paket geri alma ayrıdır.** Güncelleyici `.venv`, model veya kullanıcı verisini kopyalamaz. Ardından çalışan KUR.cmd bağımlılıkları senkronlar ve eksik işletim sistemi bileşenini kurabilir. Bu aşama başarısız olursa kod yedeği bu dış kurulumları geri almaz; hata açıkça gösterilir ve KUR.cmd yeniden çalıştırılabilir. Git pull da güncelleyicinin yedekleme protokolünü kullanmaz.

Protokol 1 desteği 0.2.0 ile sonlandırıldı; protokol 2 desteği 0.3.0 yayımlandığında (23 Kasım 2026) sonlandırılır. İki taraf aynı yerel paketle taşınır. Kalıcı şema kırılması gelecekte açık migration, uyumluluk matrisi ve geri alma tarifi gerektirir. 0.x sürümleri deneysel geliştirmedir.

Akustik ölçüm NumPy kullanır; duygu veya hastalık sınıflandırıcısı içermez. Beğenilen EMA adaptörü ve örnek WAV korunur. Otomatik Windows pencere testi ile kullanıcının fiziksel mikrofon/hoparlör ve canlı model deneyimi farklı kabul aşamalarıdır.

## Birincil kaynaklar

- GPT-OSS/Ollama: https://developers.openai.com/cookbook/articles/gpt-oss/run-locally-ollama
- Ollama yerel konuşma API'si: https://docs.ollama.com/capabilities/speech
- Mikrofonun gerçek ayarları: https://developer.mozilla.org/en-US/docs/Web/API/MediaStreamTrack/getSettings
- GPT-OSS giriş/çıkış türleri: https://developers.openai.com/api/docs/models/gpt-oss-20b
- Ollama API: https://docs.ollama.com/api/chat
- Ollama Windows: https://docs.ollama.com/windows
- Ollama JSON schema: https://docs.ollama.com/capabilities/structured-outputs
- pywebview kurulum: https://pywebview.flowrl.com/guide/installation
- pywebview native pencere: https://pywebview.flowrl.com/api/
- WebView2 dağıtımı: https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution
- Düşünme alanı: https://docs.ollama.com/capabilities/thinking
- Web API: https://docs.ollama.com/capabilities/web-search
- faster-whisper: https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1
- Whisper small revision: https://huggingface.co/Systran/faster-whisper-small/tree/536b0662742c02347bc0e980a01041f333bce120
- EMA paketi: https://pypi.org/project/ema-lightning/1.1.2/
- EMA revision: https://huggingface.co/canberkkkkkk/ema-lightning/tree/e7c96f2fc0ba843cd0f86e02786655bb56f50df8
- EMA API: https://github.com/canberk7/ema-lightning
- ONNX gizlilik ayarları: https://github.com/microsoft/onnxruntime/blob/main/docs/Privacy.md
- uv kurulum: https://docs.astral.sh/uv/getting-started/installation/
- tiktoken formatı: https://github.com/openai/tiktoken/blob/0.12.0/tiktoken_ext/openai_public.py
- Tarayıcı yankı isteği: https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints/echoCancellation

## Lisans bilgisi

Bu ZIP model ağırlıklarını veya üçüncü taraf paket ikililerini dağıtmaz; kurulum bunları ilgili resmî kaynaklardan alır. GPT-OSS ve EMA model/kodları Apache-2.0; faster-whisper ve Whisper/Silero bileşenleri MIT; PyTorch BSD türü lisans; normalizer-tr Apache-2.0; uv MIT/Apache-2.0; tiktoken MIT lisanslıdır. Bağımlılıkların tam lisans/notice dosyaları kurulan paketlerin içindedir. Uygulama kaynak kodu bu kullanıcı için oluşturulmuştur; ticari bir ürünün tamamına yönelik lisans denetimi yapılmış sayılmaz.

Bu depoda uygulama kaynak kodu için ayrıca bir açık kaynak lisansı seçilmiş değildir. Herkese açık indirme ile üçüncü taraflara lisans hakları verme aynı şey değildir; mevcut üçüncü taraf lisansları kurulu paketlerde korunur.
