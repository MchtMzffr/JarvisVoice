# JarvisVoice geliştirme rehberi

## İşe başlama

1. `docs/PROJECT_STATE.md` dosyasından güncel hedefi, bilinen sorunu ve doğrulama durumunu oku.
2. `git status` ve ilgili son commit'leri kontrol et; kullanıcı değişikliklerini koru.
3. Yapılacak işle ilgili kaynak kodunu ve `docs/CONTRACT.md` sözleşmesini incele.
4. Dar değişikliği uygula, ilgili davranışı doğrula ve çalışma durumunu güncelle.

Depodaki durum kaydı sohbet sürekliliğine yardımcı olur; kaynak kodu veya test sonucunun yerine geçmez. Eksik bir sonuç için başarı varsayma.

## Ürün hedefi ve sınırlar

- Windows üzerinde, mevcut yerel Ollama `gpt-oss:20b` ile doğal Türkçe sesli sohbet.
- Kullanıcının beğendiği EMA Lightning Türkçe sesini koru; ses/model değişikliğini ayrı ve ölçülebilir bir çalışma olarak ele al.
- Tanışma, profil, mikrofon kontrolü ve isteğe bağlı ses ölçümü kendi yerel arayüzümüzde çalışır.
- GPT-OSS'a metin ve isteğe bağlı ölçüm nesnesi verilir; modelin ham sesi doğrudan duyduğunu iddia etme.
- Akustik ölçüm, duygu tahmini ve klinik iddia ayrı konulardır. Mevcut uygulama duygu/hastalık sınıflandırıcısı veya doğrulanmış terapi değildir.
- Bu depo bağımsızdır; başka projelerin core'larına veya Decision Ecosystem depolarına yeni bağımlılık ekleme.

## Sözleşmeler ve tek yetkili kaynak

- Ayarlanabilir çalışma parametreleri: `jarvis/config.py::Settings`.
- Parametre değişince `docs/PARAMETER_INDEX.md` tablosunu aynı tanımdan güncelle.
- Ses/epoch/gözlem sözleşmeleri: `jarvis/contracts.py`; profil: `jarvis/profile.py`; mikrofon kalibrasyonu: `jarvis/calibration.py`.
- Sağlayıcı ayrıntılarını `asr.py`, `tts.py`, `llm.py`, `web.py` adaptörlerinde tut.
- Protokol veya kalıcı şema değişikliğinde sürüm, uyumluluk ve migration/geri alma etkisini `docs/CONTRACT.md` ve `docs/COMPATIBILITY.md` içinde açıkla.
- Uygulama SemVer sürümünü `jarvis/__init__.py`, `pyproject.toml`, kilit dosyasındaki proje girdisi, başlatıcılar ve ilgili dağıtım bilgileriyle tutarlı tut.

## Korunacak davranışlar

- Eski epoch'a ait ses veya ölçüm yeni turda yayımlanamaz. Stop/interrupt/disconnect oynatmayı durdurmalıdır.
- Başlamış native CPU işi async iptalle bitmiş varsayılamaz; iş slotu gerçekten tamamlanana kadar korunur.
- Son açık onaydan önce profil taslağı kaydedilmez. Kalibrasyon yalnız uygun sunucu sonucu ve açık uygulama isteğiyle kalıcı olur.
- Akustik inceleme varsayılan kapalıdır; uygun olmayan ölçüm için değer veya duygu uydurulmaz.
- API anahtarı yalnız oturum RAM'inde kalır. Ham kullanıcı sesi, transkript, profil, hatıra ve ölçüm kayıtlarını loglara veya depoya taşıma.
- `data/`, model ağırlıkları, `.venv/`, `.runtime/`, `backups/`, `.env*`, kimlik bilgileri ve güncelleme kilitlerini commit etme. Paketteki `SES_ORNEGI.wav` sentetik, bilerek dağıtılan ses örneğidir.
- Sunucunun loopback sınırını, oturum/origin kontrolünü, kuyruk ve hız sınırlarını koru.
- Güncelleyici portun uygunluğunu belirleyemiyorsa yazmaya devam etmez. Kullanıcı verilerini koruyan yedek/geri alma davranışını veya port kontrolünü atlama.
- ONNX Runtime telemetri opt-out'unu native importtan önce uygula; mevcut giriş noktalarındaki ayarları koru.

## Doğrulama

Güncelleyiciye odaklı testler Python 3.11 standart kütüphanesiyle çalışır; model veya internet indirmesi gerektirmez:

```text
python -m unittest discover -s tests -p "test_update*.py" -v
```

Tam Python paketi için uygulama bağımlılıkları ve yerel tokenizer önbelleği hazırlanmış olmalıdır. Gerekirse `JARVIS_DATA_DIR`, mevcut kurulumun `data` klasörünü gösterebilir; kullanıcı verilerini test girdisi olarak değiştirme.

```text
python -m unittest discover -s tests -v
node --test tests/test_frontend.js tests/test_resampler.js
```

Gerçek ASR/TTS yüklemesi ayrı kontroldür: `python -m jarvis.verify`; önceden indirilmiş ses modellerini gerektirir. Birim/sahte socket testini gerçek Windows mikrofonu, Winsock veya canlı Ollama testi gibi sunma. Yalnız değişikliğin somut riskini karşılayan testleri çalıştır; yeni bir risk olmadan aynı kontrolleri çoğaltma.

## Çalışmayı devretme

Tamamlanan işte ne değiştiğini, hangi komutların hangi ortamda çalıştığını ve kalan sınırı kaydet. `docs/PROJECT_STATE.md` kısa kalsın; ayrıntılı kanıt `docs/VALIDATION.md`, değişiklik geçmişi ve ilgili testlerde bulunsun. Commit/PR açıklaması problem → değişiklik → sonuç → doğrulama sırasını izlesin. Çalıştırılmamış testleri ve henüz görülmemiş kullanıcı sonuçlarını açıkça bekliyor olarak belirt.
