# JarvisVoice — çalışma durumu

Son güncelleme: 23 Kasım 2026. Bu dosya kısa devir kaydıdır; ayrıntılı kanıt için [VALIDATION.md](VALIDATION.md), sözleşmeler için [CONTRACT.md](CONTRACT.md) kullanılır.

## Amaç ve depo

Yerel GPT-OSS ile doğal Türkçe sesli sohbet, sesli tanışma, mikrofon kontrolü ve isteğe bağlı akustik ölçüm. Kullanıcının beğendiği EMA sesi korunur.

GitHub: [MchtMzffr/JarvisVoice](https://github.com/MchtMzffr/JarvisVoice). Ana dal `main`. Depo herkese açıktır; model ağırlıkları, çalışma ortamları ve kişisel veriler kapsam dışındadır.

## Mevcut sürüm durumu

| Konu | Kanıt / durum |
|---|---|
| Kullanıcıdaki başarılı temel kurulum | 0.1.0; kullanıcı Windows kurulum çıktısını ve sesi beğendiğini paylaştı. |
| Son teslim edilen özellik paketi | 0.2.0: tanışma, profil, kalibrasyon, akustik ölçüm ve süre panelleri. |
| 0.2.0 otomatik testleri | Linux geliştirme ortamında 94 Python + 25 JavaScript testi geçti; [rapor](VALIDATION.md). |
| Güncel kaynak sürümü | 0.2.1 GitHub `main` üzerinde: Windows exclusive bind kontrolü ve hata ayrıntıları. |
| 0.2.1 yerel test sonucu | Linux: 107 Python geçti, 3 native Windows testi atlandı; 25 JavaScript geçti. |
| GitHub otomatik kontrolü | Windows ve Linux başarılı; [45194537357](https://github.com/MchtMzffr/JarvisVoice/actions/runs/45194537357), kod commit'i `574cdc462a10ad5bcc87afd6735aa21b504f5956`. Windows'ta 28 güncelleyici + 10 profil + 25 JavaScript testi geçti; native port testleri bu 28'e dahildir. |
| Kullanıcı Windows kabulü | Yeni port kontrolü ve güncellemenin başarıyla tamamlanması henüz bildirilmedi. |

Sürümün yetkili kod değeri `jarvis/__init__.py::__version__` içindedir; bu özet onun yerine geçmez.

## Düzeltilen sorun: güncelleyici 8765 kontrolünde duruyor

Kullanıcı 0.2.0 `GUNCELLE.cmd` çalıştırırken şu mesajı aldı:

```text
Guncelleme durduruldu: 8765 portu kontrol edilemedi. Jarvis'i kapatıp yeniden dene.
```

0.2.0 kodu 127.0.0.1:8765'e 0,5 saniye sınırıyla TCP bağlantısı deniyor; bağlantı reddi dışındaki `OSError` ayrıntılarını aynı genel mesaja indiriyor. Bu çıktı, gerçek nedenin timeout, erişim engeli veya başka bir hata olduğunu tek başına belirlemiyor. Port kontrolleri uygulama kodunun değiştirilmesinden önce çalışır.

0.2.1 uygulanan düzeltme: Windows'ta bağlantı denemesi yerine `SO_EXCLUSIVEADDRUSE` ile IPv4 wildcard adrese geçici bind kontrolü; listen/accept yok. Başarılı kontrol portun o anda alınabildiğini gösterir. Meşgul port ve sonucu bilinmeyen hatalar güncellemeyi durdurur; hata aşaması ve sayısal kod gösterilir. Bekleyen bağlantı/rezervasyon nedeniyle gereğinden sıkı engelleme mümkün olduğundan kontrol atlanmaz. Gerçek kullanıcı Windows sonucu ayrıca gereklidir.

İlk Windows CI koşumunda üç native port testi geçti; geri alma testindeki hata benzetimi yol temsili farkıyla tetiklenmedi. Testin geçici kök yolu `.resolve()` ile aynı temsile alındı; hata ve geri alma beklentileri korunarak sonraki Windows/Linux koşumu tamamen geçti. Ayrıntılar [VALIDATION.md](VALIDATION.md) içindedir.

## Mimari ve sabit kararlar

| Katman | Seçim |
|---|---|
| Dil modeli | Mevcut Ollama `gpt-oss:20b`; think=low, context=4096 |
| Konuşma tanıma / sınır | Whisper small CPU/int8 + Silero V6 |
| Türkçe ses | EMA Lightning 1.1.2; mevcut ses korunur |
| Arayüz | Yerel tarayıcı + Python, loopback 127.0.0.1:8765 |
| Akustik özellikler | İsteğe bağlı, oturum başında kapalı; NumPy ölçümü |
| Protokol / veri | Protokol 2; profil, kalibrasyon, gözlem ve SQLite şemaları 1 |
| Parametreler | `jarvis/config.py::Settings`; [PARAMETER_INDEX.md](PARAMETER_INDEX.md) |

Profil son onaydan önce yazılmaz. Mikrofon kalibrasyonu duygu modeli eğitimi değildir. Ses özellikleri duygu/kimlik/hastalık etiketi üretmez; klinik etkinlik iddiası yoktur. Ham ses ve normal sohbet geçmişi kalıcı kaydedilmez. İnternet açıkken ölçüm nesnesi araç kararından ayrı tutulur; bu ek yerel çağrı maliyeti doğurabilir.

## Bir sonraki somut işler

1. Kullanıcının Windows'ta güncelleme → başlatma → sesli tanışma → mikrofon kontrolü akışını tamamladığını teyit et. GitHub CI fiziksel mikrofon/hoparlör veya kullanıcının 8765 port koşulunu ölçmez.
2. Aynı Windows sisteminde sıcak/soğuk model ve internet açık/kapalı koşullarını ayrı ölçerek gecikme darboğazını belirle.
3. Sonraki değişiklikleri ayrı commit'lerde tut; önce ilgili sözleşme ve parametreleri, sonra dar test ve durum kaydını güncelle.

İlk kaynak aktarımı `ab0d50c0f801d03a24560fd18d7de91938199716`; port düzeltmesi `3595bed21e34beb5119561c2ed2466d09be08bd3`; Windows test yolu düzeltmesi `574cdc462a10ad5bcc87afd6735aa21b504f5956`. Mevcut kodun ve test geçmişinin başlangıcı bu commit'lerden izlenebilir.

Sonraki özellikler ve kabul ölçütleri: [ROADMAP.md](ROADMAP.md). Buradaki bekleyen işler kullanıcıya tamamlanmış gibi aktarılmamalıdır.
