# JarvisVoice 0.3.0

Türkçe sesli sohbet ve yazılı chat kutusu, yerel Ollama/GPT-OSS ile kendi Windows masaüstü penceresinde birleşir.

## Yeni

- pywebview + WebView2 masaüstü penceresi; normal başlatıcı tarayıcı sekmesi açmaz.
- Açılışta görünen sohbet kutusu ve normal yanıtları sessiz metin olarak alma seçeneği.
- Oturum izniyle Hesap Makinesi, Not Defteri, Dosya Gezgini ve Paint açma.
- Profil ve açıkça kaydedilmiş notlarla plan taslağı; açık kayıt isteği, gösterme ve silme.
- Yeni kullanıcının kurulumunda WebView2/Ollama kontrolü ve eksik GPT-OSS indirmesi.

## Kurulum

Kaynak ZIP'in tamamını çıkar, `KUR.cmd` çalıştır; tamamlanınca `BASLAT.cmd` aç. İlk kurulum model eksikse yaklaşık 13 GB GPT-OSS, yaklaşık 525 MB ses dosyası ve Python/paketleri indirir. Mevcut kurulum kullanılıyorsa yeni kaynak klasöründen `GUNCELLE.cmd` ile eski `BASLAT.cmd` seçilir; masaüstü paketleri için hedefte KUR kontrolü otomatik çalışır.

## Sınırlar

0.x deneysel sürümdür. Windows x64 hedeflenir. Model dosyaları ZIP'e gömülmez; kurulum resmî kaynaklardan alır. Planlar otomatik iş/takvim yürütmez. Uygulama açma dört sabit uygulamayla sınırlıdır ve izin her oturumda kapalı başlar. Duygu/hastalık tanısı veya klinik etkinlik iddiası yoktur.

Gerçek test sonuçları ve fiziksel Windows/mikrofon kabul sınırları `docs/VALIDATION.md` içinde yer alır. Model, API, ses ve paket lisansları kendi bileşenlerine aittir.

## Doğrulama ve kaynak

[Windows/Linux CI ve gerçek WebView2 kontrolü](https://github.com/MchtMzffr/JarvisVoice/actions/runs/45206594006) geçti. Windows'ta 180 Python testi ve 31 JavaScript testi geçti; tokenizer indirmeyen CI bir token testini atladı. Native pencerede 21 demo sohbet/görüntü/kapanış kontrolü geçti. Fiziksel mikrofon ve gerçek GPT-OSS yanıtı bu CI'nın kapsamında değildir.

[Kurulum ve kullanım](https://github.com/MchtMzffr/JarvisVoice#ilk-kurulum) · [Tam doğrulama kaydı](https://github.com/MchtMzffr/JarvisVoice/blob/main/docs/VALIDATION.md).

ZIP, testleri geçen release commit'inin `git archive` çıktısıdır; SHA256SUMS.txt indirme bütünlüğü için sağlanır. Bu bir kaynak/kurulum paketidir; tek dosya EXE veya model ağırlıklarını içeren paket değildir.
