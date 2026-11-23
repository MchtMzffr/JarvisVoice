# Uyumluluk ve kaynaklar

| Bileşen | Sabit sürüm / sözleşme | Doğrulama |
|---|---|---|
| Uygulama | 0.2.0 / protokol 2 | 94 Python + 25 JavaScript testi |
| Python | 3.11.18 | Linux kurulum ve gerçek ses kontrolü; Windows için yönetilen sürüm isteği |
| Ollama | Kullanıcıda 0.40.17 | Kullanıcının model/GPU testi; paket değiştirmez |
| Model | gpt-oss:20b / think low / 4096 | Kullanıcının mevcut kurulumu |
| faster-whisper | 1.2.1 | Gerçek CPU yükleme/ASR |
| CTranslate2 | 4.9.1 | CPU int8 |
| ONNX Runtime | 1.32.0 | CPU + importtan önce telemetri opt-out |
| PyAV | 16.1.0 | Python 3.11 uyumlu sabit sürüm |
| EMA Lightning | 1.1.2 | Gerçek CPU sentezi |
| PyTorch | 2.10.0+cpu | CPU wheel; CUDA paketi kullanılmaz |
| normalizer-tr | 0.8.1 | Hazır Windows x64 wheel |
| tiktoken | 0.12.0 / o200k_harmony | Yerel doğrulanmış tokenizer dosyası |
| uv | 0.13.9 | Windows dağıtımı SHA256 ile sabitlenmiş |
| Tarayıcı | Güncel Chrome / Edge, WebAudio + AudioWorklet | Gerçek Windows tarayıcı testi bekliyor |

Bağımlılıklar `pyproject.toml` ve `uv.lock` içinde sabitlenmiştir. Bunları güncellemek, yeni uyumluluk ve telemetri kontrolü gerektirir. 0.2.0, 0.1.0 ile aynı Python bağımlılıklarını kullanır; yalnız uygulama sürümü ve kaynak dosyaları güncellenir.

## Geçiş ve veri matrisi

| Kaynak → hedef | Destek / işlem |
|---|---|
| Tamamlanmış 0.1.0 → 0.2.0 | GUNCELLE.cmd; mevcut Python/model/veri korunur, değişen kod yedeklenir. |
| 0.2.0 → 0.2.0 | Aynı çevrimdışı güncelleyici yeniden uygulamayı destekler. |
| Yeni kurulum | KUR.cmd; mevcut Ollama modeli kullanılır. |
| Protokol 1 arayüz → protokol 2 sunucu | Reddedilir; arayüz ve sunucu birlikte güncellenmeli. |
| SQLite user_version 1 | Aynı şema; migration gerekmez. |
| Profil / mikrofon eşiği / akustik gözlem | Yeni şemalar 1; profil ve kalibrasyon dosyası yoksa varsayılanlarla başlar. |
| Bozuk veya gelecekteki kalıcı şema | Sessiz sıfırlama yok; dosya korunur, başlatma/kayıt durur. |
| 0.2.0 → 0.1.0 kod geri alma | Güncelleyicinin doğrulanmış kod yedeğiyle manuel; data korunur, yeni profil/kalibrasyon 0.1 tarafından kullanılmaz. |

Protokol 1 desteği 0.2.0 yayımlandığında sonlandırılır; ayrı geçiş süresi uygulanmaz çünkü aynı yerel paket iki tarafı birlikte taşır. Gelecekte kalıcı şema kırılması için açık migration ve geri alma planı gerekir. 0.x sürümleri deneysel geliştirmedir; klinik/üretim sertifikasyonu anlamı taşımaz.

Akustik ölçüm ek NumPy dışı bağımlılık gerektirmez. emotion2vec veya başka duygu modeli bu pakete kurulmaz. Beğenilen EMA adaptörü ve örnek WAV, 0.1.0 ile aynı baytlardır. Windows güncelleme seçicisi, fiziksel mikrofon ve gerçek tarayıcı uçtan uca doğrulaması beklemektedir.

## Birincil kaynaklar

- GPT-OSS/Ollama: https://developers.openai.com/cookbook/articles/gpt-oss/run-locally-ollama
- Ollama yerel konuşma API'si: https://docs.ollama.com/capabilities/speech
- Mikrofonun gerçek ayarları: https://developer.mozilla.org/en-US/docs/Web/API/MediaStreamTrack/getSettings
- GPT-OSS giriş/çıkış türleri: https://developers.openai.com/api/docs/models/gpt-oss-20b
- Ollama API: https://docs.ollama.com/api/chat
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
