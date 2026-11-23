# JarvisVoice geliştirme rehberi

## İşe başlama

1. `docs/PROJECT_STATE.md` dosyasından güncel hedefi, bilinen sorunu ve doğrulama durumunu oku.
2. `git status` ve ilgili son commit'leri kontrol et; kullanıcı değişikliklerini koru.
3. Yapılacak işle ilgili kaynak kodunu ve `docs/CONTRACT.md` sözleşmesini incele.
4. Dar değişikliği uygula, ilgili davranışı doğrula ve çalışma durumunu güncelle.

Depodaki durum kaydı sohbet sürekliliğine yardımcı olur; kaynak kodu veya test sonucunun yerine geçmez. Eksik bir sonuç için başarı varsayma.

## Ürün hedefi ve sınırlar

- Windows üzerinde, mevcut yerel Ollama `gpt-oss:20b` ile tek masaüstü penceresinde yazışma ve doğal Türkçe sesli sohbet.
- Kullanıcının beğendiği EMA Lightning Türkçe sesini koru; ses/model değişikliğini ayrı ve ölçülebilir bir çalışma olarak ele al.
- `BASLAT.cmd` kendi WebView2 penceresini açar. HTML/CSS/JavaScript arayüzü ve loopback Python sunucusu korunur; bu bir Ollama Chat eklentisi değildir. Tarayıcı modu yalnız açık geliştirme/alternatif başlatma seçeneğidir.
- Tanışma, profil, mikrofon kontrolü, isteğe bağlı ses ölçümü, seçili uygulama açma ve açık istekle kaydedilen plan kendi yerel arayüzümüzde çalışır.
- Kişiselleştirme onaylı profil ve doğrudan kullanıcı isteğiyle kaydedilmiş notlara dayanır; otomatik kişilik öğrenimi, sınırsız geçmiş veya model eğitimi iddiası kurma.
- GPT-OSS'a metin ve isteğe bağlı ölçüm nesnesi verilir; modelin ham sesi doğrudan duyduğunu iddia etme.
- Akustik ölçüm, duygu tahmini ve klinik iddia ayrı konulardır. Mevcut uygulama duygu/hastalık sınıflandırıcısı veya doğrulanmış terapi değildir.
- Bu depo bağımsızdır; başka projelerin core'larına veya Decision Ecosystem depolarına yeni bağımlılık ekleme.

## Sözleşmeler ve tek yetkili kaynak

- Ayarlanabilir çalışma parametreleri: `jarvis/config.py::Settings`.
- Parametre değişince `docs/PARAMETER_INDEX.md` tablosunu aynı tanımdan güncelle.
- Ses/epoch/gözlem sözleşmeleri: `jarvis/contracts.py`; profil: `jarvis/profile.py`; mikrofon kalibrasyonu: `jarvis/calibration.py`.
- Plan şeması ve saklama: `jarvis/plans.py`; sabit uygulama kataloğu ve Windows başlatma adaptörü: `jarvis/actions.py`.
- Masaüstü pencere/sunucu ömrü: `jarvis/desktop.py`; kurulum denetimi ve açık eksik bileşen kurulumu: `jarvis/setup_local.py`.
- Sağlayıcı ayrıntılarını `asr.py`, `tts.py`, `llm.py`, `web.py` adaptörlerinde tut.
- Protokol veya kalıcı şema değişikliğinde sürüm, uyumluluk ve migration/geri alma etkisini `docs/CONTRACT.md` ve `docs/COMPATIBILITY.md` içinde açıkla.
- Uygulama SemVer sürümünü `jarvis/__init__.py`, `pyproject.toml`, kilit dosyasındaki proje girdisi, başlatıcılar ve ilgili dağıtım bilgileriyle tutarlı tut.
- 0.3.0 WebSocket protokolü 3'tür; frontend ve backend birlikte dağıtılır. Profil, mikrofon, gözlem, hatıra ve yeni plan şemaları 1'dir. Eski protokolü sessizce kabul etme; uyumluluk değişimini belgeleyip test et.

## Korunacak davranışlar

- Eski epoch'a ait ses veya ölçüm yeni turda yayımlanamaz. Stop/interrupt/disconnect oynatmayı durdurmalıdır.
- Başlamış native CPU işi async iptalle bitmiş varsayılamaz; iş slotu gerçekten tamamlanana kadar korunur.
- Son açık onaydan önce profil taslağı kaydedilmez. Kalibrasyon yalnız uygun sunucu sonucu ve açık uygulama isteğiyle kalıcı olur.
- Normal yazılı modda `speech_enabled=false` TTS'yi atlar; yalnız tamamlanan yanıt arayüze gönderildikten sonra oturum geçmişine eklenir. Sesli modda oynatma ACK'i kuralı korunur. Tanışma ve mikrofon yönergeleri ayrı `guided` akışta sesli kalır.
- Uygulama açma izni her oturumda kapalı başlar. Yalnız doğrudan kullanıcı girdisi, izinli uygulama kimliği, güncel epoch, hız sınırı ve tüketilmemiş istek birlikte geçerse başlatma yapılır. Model/web çıktısı, dosya yolu, URI veya serbest shell komutu bu yetkiyi vermez.
- Dört sabit uygulama için kabuksuz başlatma korunur. Süreç isteğinin başarıyla gönderilmesi pencerenin görüldüğünü kanıtlamaz. Stop önceden açılmış uygulamayı kapatmış sayılmaz.
- Plan taslağı RAM'de süreli kalır; yalnız güncel taslağa açık kayıt isteği `data/plan.json` yazar. Modelin plan adımları otomatik çalıştırılmaz. Bozuk/gelecekteki şema ve gözlenen dosya değişimi korunur; kayıt/silme kapılarını atlama.
- Akustik inceleme varsayılan kapalıdır; uygun olmayan ölçüm için değer veya duygu uydurulmaz.
- API anahtarı yalnız oturum RAM'inde kalır. Ham kullanıcı sesi, transkript, profil, hatıra, plan ve ölçüm kayıtlarını loglara veya depoya taşıma.
- `data/`, model ağırlıkları, `.venv/`, `.runtime/`, `backups/`, `.env*`, kimlik bilgileri ve güncelleme kilitlerini commit etme. Paketteki `SES_ORNEGI.wav` sentetik, bilerek dağıtılan ses örneğidir.
- Sunucunun loopback sınırını, oturum/origin kontrolünü, kuyruk ve hız sınırlarını koru.
- Masaüstü sayfasına Python `js_api` yetkisi açma. WebView2 gezinme/popup sınırlarını, geçici pencere depolamasını ve pencere kapanışında uygulamanın sahip olduğu sunucunun kapanmasını koru; ortak Ollama servisini öldürme.
- Normal başlatma yazılım/model kurmaz veya indirmez. Eksik bileşen kurulumu yalnız açık `KUR.cmd` / `setup_local --install-missing` akışındadır. Mevcut model ve ses dosyalarını koru.
- Güncelleyici portun uygunluğunu belirleyemiyorsa yazmaya devam etmez. Kullanıcı verilerini koruyan yedek/geri alma davranışını veya port kontrolünü atlama.
- Kod aktarımı rollback'i ile sonraki `KUR.cmd` paket/servis kurulumu ayrı işlemlerdir. Paket kurulumu başarısızlığını kodun veya sistem paketlerinin geri alındığı şeklinde sunma.
- ONNX Runtime telemetri opt-out'unu native importtan önce uygula; mevcut giriş noktalarındaki ayarları koru.

## Doğrulama

Güncelleyiciye odaklı testler Python 3.11 standart kütüphanesiyle çalışır; model veya internet indirmesi gerektirmez:

```text
python -m unittest discover -s tests -p "test_update*.py" -v
```

Model indirmeyen tam birim/regresyon paketi için `tests/install_check_dependencies.py`, seçili hafif paketleri `pyproject.toml` ve `uv.lock` sürümleriyle kurar; Windows'ta masaüstü ek paketlerini de seçer. Paket kurulumu ağ gerektirir; `--validate-only` yalnız yerel bağımlılık planını okur. Önce ortamın amacını belirle; test için uygulamanın büyük ses/model bağımlılıklarını indirme.

```text
python tests/install_check_dependencies.py --validate-only
python tests/install_check_dependencies.py
python -m unittest discover -s tests -v
node --test tests/test_frontend.js tests/test_resampler.js
```

Tokenizer önbelleği yoksa ilgili gerçek token bütçesi testi açıklamalı atlanır; test bunu indirmez. Tam token kontrolü için `JARVIS_DATA_DIR` mevcut hazırlanmış model klasörünü gösterebilir; kullanıcı verilerini test girdisi olarak değiştirme. Platform veya symlink yetkisi nedeniyle atlanan kontrolleri ayrıca say.

Gerçek ASR/TTS yüklemesi ayrı kontroldür: `python -m jarvis.verify`; önceden indirilmiş ses modellerini gerektirir. Native WebView2 pencere kontrolü, sahte pencere testinden ve fiziksel mikrofon/oynatma kabulünden ayrıdır. Birim/sahte socket/Popen testini gerçek Windows mikrofonu, Winsock, açılmış uygulama penceresi veya canlı Ollama testi gibi sunma. Yalnız değişikliğin somut riskini karşılayan testleri çalıştır; yeni bir risk olmadan aynı kontrolleri çoğaltma.

## Çalışmayı devretme

Tamamlanan işte ne değiştiğini, hangi komutların hangi ortamda çalıştığını ve kalan sınırı kaydet. `docs/PROJECT_STATE.md` kısa kalsın; ayrıntılı kanıt `docs/VALIDATION.md`, değişiklik geçmişi ve ilgili testlerde bulunsun. Commit/PR açıklaması problem → değişiklik → sonuç → doğrulama sırasını izlesin. Çalıştırılmamış testleri ve henüz görülmemiş kullanıcı sonuçlarını açıkça bekliyor olarak belirt.
