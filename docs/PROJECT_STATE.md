# JarvisVoice — çalışma durumu

Son güncelleme: 23 Kasım 2026. Bu kısa devir kaydıdır; ayrıntılı doğrulama [VALIDATION.md](VALIDATION.md), davranış sınırları [DESKTOP_0_3.md](DESKTOP_0_3.md), sözleşmeler [CONTRACT.md](CONTRACT.md) içindedir.

## Amaç ve depo

Mevcut yerel GPT-OSS ve beğenilen EMA Türkçe sesiyle, tek Windows masaüstü penceresinde yazışma ve sesli sohbet. Kullanıcı profilini ve açıkça kaydedilmiş notlarını kullanarak seçili uygulama açma ve kişisel plan hazırlama ekleniyor. Ses/model değişimi bu çalışmanın parçası değildir.

GitHub: [MchtMzffr/JarvisVoice](https://github.com/MchtMzffr/JarvisVoice). Ana dal `main`. Kaynak, test ve geliştirme kayıtları depodadır; model ağırlıkları, çalışma ortamları, anahtarlar ve kişisel veriler dışarıda kalır.

## Mevcut durum

| Konu | Kanıt / durum |
|---|---|
| Kullanıcıdaki önceki kurulum | İlk Windows kurulumu başarılıydı; kullanıcı EMA sesini beğendi. Son geri bildirimde kalibrasyonun olmuş gibi göründüğünü ve konuşmaların güzel olduğunu belirtti. Bu, 0.3.0 masaüstü kabulü değildir. |
| Aktif kaynak sürümü | 0.3.0 / protokol 3. Ürün kodu ve native test `4b8fc84` üzerinde doğrulandı; [CI](https://github.com/MchtMzffr/JarvisVoice/actions/runs/45206594006). |
| Yeni arayüz | `BASLAT.cmd` → pywebview 6.2.1 / WebView2 penceresi; aynı pencerede yazılı/sesli sohbet ve plan kartları. |
| Yerel doğrulama | Yeni eylem, plan, metin modu, kurulum ve masaüstü regresyonları eklendi. Son test sayıları ve ortam ayrımı `VALIDATION.md` içinde tutulur. |
| Native Windows 0.3.0 CI | **Geçti.** [Koşum 45206594006](https://github.com/MchtMzffr/JarvisVoice/actions/runs/45206594006); gerçek pencere, sessiz demo sohbeti, PNG ve OS listener kapanışı. Fiziksel mikrofon/canlı model kapsam dışı. |
| Kullanıcı Windows 0.3.0 kabulü | **Bekleniyor.** Yeni masaüstü sürümü kullanıcı tarafından henüz denenmedi. |

Sürümün yetkili kod değeri `jarvis/__init__.py::__version__`, protokolün yetkili değeri `jarvis/config.py::Settings.protocol_version` içindedir.

## Uygulanan 0.3.0 kapsamı

- Masaüstü pencere ve sahibi olduğu loopback sunucunun yaşam döngüsü eklendi. Açık tarayıcı alternatifi geliştirme seçeneği olarak durur; Ollama'nın resmî Chat arayüzü değiştirilmez.
- Normal yanıtta seslendirme açılıp kapatılabilir. Sessiz modda yalnız tamamlanmış yanıt geçmişe eklenir; tanışma ve mikrofon yönergeleri sesli kalır.
- Doğrudan kullanıcı komutlarıyla Hesap Makinesi, Not Defteri, Dosya Gezgini ve Paint başlatılabilir. İzin oturum başında kapalıdır; güncel epoch, hız ve tekrar denetimiyle açılır. Başlatma isteği, görünür pencere doğrulaması değildir.
- Yerel model şemaya bağlı plan taslağı üretir. Taslak RAM'de 600 saniye geçerlidir; “Planı kaydet” veya taslak kimliğine bağlı açık düğme işlemi tek planı `data/plan.json` içine yazar. Plan adımları uygulama/komut yürütmez ve hatırlatıcı kurmaz.
- Mevcut profil ve açık “Bunu hatırla: …” notları yanıta/plan önerisine katılır. Bütün geçmiş konuşmaları hatırlayan veya kullanıcının kişiliğini öğrenen yeni bir model eğitimi yapılmaz.
- `KUR.cmd`, kilitli masaüstü ek paketlerini kurar ve `setup_local --install-missing` ile eksik WebView2/Ollama/GPT-OSS bileşenlerini tamamlar. `BASLAT.cmd` mevcut kurulumu doğrular; yazılım/model indirmez. Mevcut Ollama ve ses modelleri korunur.

## Mimari ve sabit kararlar

| Katman | Seçim |
|---|---|
| Dil modeli | Mevcut Ollama `gpt-oss:20b`; think=low, context=4096 |
| Konuşma tanıma / sınır | Whisper small CPU/int8 + Silero V6 |
| Türkçe ses | EMA Lightning 1.1.2; aynı ses modeli/adaptörü |
| Arayüz | Windows pywebview/WebView2 + HTML/CSS/JavaScript + Python; 127.0.0.1:8765 |
| Profil / hatıra | Onaylı profil ve doğrudan kullanıcı komutuyla kaydedilmiş notlar |
| Eylemler | `actions.py` sabit dört uygulama; serbest shell/yol/argüman yok |
| Plan | `plans.py` şema 1; tek yerel kayıt, süreli RAM taslağı |
| Protokol / veri | Protokol 3; profil, kalibrasyon, gözlem, plan ve SQLite şemaları 1 |
| Parametreler | `jarvis/config.py::Settings`; [PARAMETER_INDEX.md](PARAMETER_INDEX.md) |

Ham ses ve normal sohbet geçmişi kalıcı kaydedilmez. Plan/ölçüm nesnesi web arama kararından ayrı tutulur; daha önce okunmuş metin normal oturum geçmişinde kalabilir. Bu yüzden tüm kişisel bilginin her durumda arama sorgusundan uzak kalacağı garanti edilmez. Akustik özellikler duygu/kimlik/hastalık etiketi üretmez; klinik etkinlik iddiası yoktur.

## Güncelleme ve uyumluluk

0.1.0/0.2.0/0.2.1/0.3.0 kurulumları güncelleyici tarafından 0.3.0 koduna taşınabilir. `GUNCELLE.cmd`, eski çalışan kurulumun `BASLAT.cmd` dosyasını seçtirir; kod aktarımından sonra hedef kurulumun `KUR.cmd` denetimini çağırır. Temel ses/LLM bağımlılıkları korunur, Windows `desktop` extra eklenir. Kod yedeği/rollback'i, sonraki paket veya sistem bileşeni kurulumunu geri alma taahhüdü taşımaz.

Protokol 2 frontend ile protokol 3 backend birlikte çalıştırılmaz; uygulama/statik dosyalar birlikte güncellenir. Mevcut profil/kalibrasyon/hatıra şemaları değişmez. Ayrıntı: [COMPATIBILITY.md](COMPATIBILITY.md).

## Dağıtım

[0.3.0 Windows kaynak paketi ve sürüm notları](https://github.com/MchtMzffr/JarvisVoice/releases/tag/v0.3.0). Release iş akışı, exact commit üzerinde Windows/Linux kontrolleri geçtikten sonra git archive ZIP ve SHA256SUMS.txt yayımlar. Model ağırlıkları pakete gömülmez.

## Bir sonraki somut işler

1. Kullanıcı Windows'ta güncelleme → masaüstü açılış → yazılı/sesli yanıt → tanışma/mikrofon akışını denesin; model/ses tercihi aynı kalsın.
2. Uygulama izni kapalı/açık durumunu, izinli bir uygulamayı açmayı ve plan oluştur → göster → açıkça kaydet → yeniden aç akışını kullanıcı bilgisayarında doğrula.
3. Ancak bu kabulün ardından aynı sistemde sıcak/soğuk model, internet ve analiz koşullarını ayırarak gecikme ölçümü al. Yeni sürüm için performans artışı henüz gösterilmedi.

## Tarihsel doğrulama

0.2.1 Windows port düzeltmesi ve test yolu düzeltmesi, [`574cdc4`](https://github.com/MchtMzffr/JarvisVoice/commit/574cdc462a10ad5bcc87afd6735aa21b504f5956) üzerinde [Windows/Linux koşumunda](https://github.com/MchtMzffr/JarvisVoice/actions/runs/45194537357) geçti. Bu eski koşum 0.3.0 masaüstü veya fiziksel ses akışının kanıtı değildir. İlk kaynak aktarımı `ab0d50c0f801d03a24560fd18d7de91938199716`; eski port hatasının ayrıntısı [PORT_CHECK_FIX.md](PORT_CHECK_FIX.md) içinde korunur.

Sıradaki özellikler ve kabul ölçütleri: [ROADMAP.md](ROADMAP.md). Bekleyen iş kullanıcıya tamamlanmış gibi aktarılmamalıdır.
