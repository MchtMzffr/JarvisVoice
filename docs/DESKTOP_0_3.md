# JarvisVoice 0.3.0 — birleşik yerel masaüstü

## Ürün sınırı

Tek Jarvis penceresinde yazışma, sesli sohbet, tanışma/profil, mikrofon kontrolü, isteğe bağlı akustik ölçüm, dört uygulama komutu ve kişisel plan bulunur. Yanıt motoru mevcut yerel `gpt-oss:20b` modelidir. Model eğitimi veya Ollama'nın resmî Chat penceresine eklenti yapılmaz.

Ollama'nın desteklediği [yerel API](https://docs.ollama.com/api/introduction) kullanılır. Windows penceresi [pywebview](https://pywebview.flowrl.com/api/) ve [Microsoft WebView2 Runtime](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution) ile açılır. WebView2 bir masaüstü web görüntüleme bileşenidir; arayüz hâlâ HTML/CSS/JavaScript ve yerel Python sunucusuyla çalışır. `BASLAT.cmd` tarayıcı sekmesi açmaz.

## Bileşenler

| Dosya | Sorumluluk |
|---|---|
| `jarvis/desktop.py`, `__main__.py` | Masaüstü pencere, yerel sunucu ömrü, kapanış ve açık tarayıcı alternatifi. |
| `jarvis/setup_local.py` | Sabit kurulum paketleri, WebView2/Ollama kontrolü, eksik yerel modelin açık kurulum adımında indirilmesi. |
| `jarvis/server.py` | Oturum, doğrudan kullanıcı komutları, yetki/epoch/hız denetimi, ses ve metin cevap akışı. |
| `jarvis/actions.py` | Dört sabit Windows uygulaması ve kabuksuz başlatma adaptörü. |
| `jarvis/plans.py` | Şema 1 plan/taslak, komut ayrıştırma, doğrulama ve atomik kayıt. |
| `jarvis/llm.py` | Yerel metin yanıtı ve JSON şemasına bağlı plan önerisi; süreç başlatma yetkisi yok. |
| `jarvis/static/*` | Sohbet kutusu, ses kontrolleri, plan kartları, izinler ve ölçümler. |

## Uygulama açma sözleşmesi

Bir başlatma isteği ancak şu koşulların birlikte sağlanmasıyla uygulanır:

`direct_user_input AND session_permission AND known_app_id AND current_epoch AND rate_ok AND not_consumed`

- İzin oturum başında kapalıdır. Kullanıcı Ayarlar'dan açar; kapatması sonraki başlatmaları engeller.
- İzinli kimlikler: `calculator`, `notepad`, `explorer`, `paint`.
- İsimler doğal Türkçe doğrudan cümleden ayrıştırılır; olumsuz, alıntı, belirsiz işaret zamiri veya zincir komut yürütülmez.
- İşletim sistemi yolu Windows'un kendi dizininden ve sabit katalogdan gelir. Model/user/web bir yürütülebilir yol, argüman veya shell komutu veremez.
- Başlatma `shell=False`; dakikada en fazla 6, iki istek arasında en az 2 saniye. İşletim sistemine başarılı süreç isteği, pencerenin gerçekten görüldüğünü kanıtlamaz.
- Son 128 mutasyon request_id'si oturumda tekilleştirilir. Aynı epoch'ta uygulama başlatma tekrar tüketilemez. Bu, kalıcı dağıtık exactly-once garantisi değildir.
- Epoch ve izin kontrolü ile süreç başlatma arasına `await` girmez. Başlamış uygulama sonradan Stop ile kapatılmış sayılmaz; Stop gelecekteki tur işini iptal eder.

## Plan sözleşmesi

Plan üretimi yerel `/api/chat` çağrısında [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs) kullanır. Model yalnız `title`, `steps[{text,minutes}]`, `assumptions` önerir. Sunucu kimlik, UTC tarih ve `schema_version=1` ekler.

- En fazla 6 adım; başlık 100, adım ve varsayım 200 karakter; en fazla 3 varsayım.
- Süre `null` veya 1–480 arasında tam sayı; sayı modelin önerisidir, ölçülmüş iş süresi değildir.
- Tamamlanmamış/uzunlukta kesilmiş akış, şema dışı alan, bozuk JSON veya hedefin bağlamdan kırpılması başarı sayılmaz.
- Taslak RAM'de 600 saniye geçerlidir. Plan üretimi ve gösterimi dosya yazmaz.
- Açık `plan_save` + güncel `draft_id`, ya da doğrudan “Planı kaydet” ifadesi kaydeder. Genel “evet” kayıt yetkisi değildir.
- Tek kayıt `data/plan.json`; yeni açık kayıt öncekinin yerini alır. Kaydetmeden önce bozuk/gelecekteki şema korunur. Yazma aynı dizinde geçici dosya + fsync + atomik replace ile yapılır.
- Taslak veya kayıtlı plan uygulama komutu çalıştırmaz, takvim/hatırlatıcı oluşturmaz. Tarih/uygunluk varsayımları kullanıcı tarafından gözden geçirilmelidir.

Kayıtlı plan nesnesi web arama kararına eklenmez; gerekli son yerel yanıta sınırlı bağlam olarak katılır. Plan daha önce konuşmada okunmuşsa o metin normal oturum geçmişinde kalabilir. Web açıkken kişisel bilginin modelin oluşturduğu sorguya hiçbir koşulda girmeyeceği garanti edilmez.

## Sohbet ve kişisel bilgiler

Mikrofon kalibrasyonu ses/ortam kontrolüdür; kullanıcının kişiliğini veya duygusunu öğrenen bir model eğitimi değildir. Profil tercihleri ve “Bunu hatırla: …” komutuyla kaydedilen notlar yerel yanıta katılır. Bağlam 4096 token ile sınırlıdır; bütün eski sohbetleri hatırlama iddiası yoktur.

Normal sohbet için `speech_enabled=false` olduğunda TTS çağrılmaz. Tamamlanan yanıt arayüze gönderildikten sonra oturum geçmişine eklenir. Sesli modda oynatma ACK'i gelmiş cümleler geçmişe eklenir. Tanışma ve mikrofon yönergeleri `audio.guided=true` ile sesli kalır. Mod değişiminde normal tur kesilir; eski modun gecikmiş sesi yeni turda oynatılamaz.

## Kurulum ve dağıtım

GitHub kaynak paketi model ağırlıklarını taşımaz. `KUR.cmd` uygulamaya özel Python'u ve kilitli `desktop` ek paketlerini kurar; `setup_local --install-missing` eksik WebView2/Ollama için yalnız sabit WinGet kimliklerini kullanır. Eksik GPT-OSS, yerel Ollama üzerinden indirilir. Mevcut modeller tekrar indirilmez.

Normal `BASLAT.cmd`, kurulumu doğrulayıp mevcut Ollama servisini gerektiğinde başlatır; yazılım/model indirme yetkisi verilmez. Kullanıcı veri klasörü ve model konumu değiştirilmez. Ollama ortak servis olduğu için Jarvis pencere kapanışında öldürülmez.

0.3.0 yeni `desktop` ek bağımlılığı içerir. GUNCELLE kodu çevrimdışı yedekler/aktarır; ardından hedefte KUR ile paket kontrolü yapılır. Paket kurulumunun başarısızlığı kod aktarımı rollback'iyle aynı işlem değildir. KUR tekrar çalıştırılabilir. Detaylı matris [COMPATIBILITY.md](COMPATIBILITY.md).

## Doğrulama sınırı

Mock transport/model testleri gerçek GPT-OSS çıktısı veya plan kalitesi ölçümü değildir. Fake Popen testleri gerçek uygulama penceresinin açıldığını göstermez. Native WebView2 testi varsa ayrı raporlanır; fiziksel mikrofon, kullanıcı cihazındaki gecikme ve yeni masaüstü penceresinde tam ses/LLM akışı kullanıcı kabulü gerektirir. Son durum [VALIDATION.md](VALIDATION.md).
