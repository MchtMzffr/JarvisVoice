# Doğrulama — Jarvis Voice 0.2.0

Tarih: 23 Kasım 2026. Aşağıdaki sonuçlar kapsamlarına göre ayrılmıştır; geçen yazılım testleri insan duygu sınıflandırması veya klinik etkinlik ölçümü değildir.

## 1. Kullanıcının Windows bilgisayarından gelen kanıt

Paylaşılan terminal çıktısında Windows PowerShell 5.1, Ollama 0.40.17, `gpt-oss:20b` model kimliği `f38aa0c53da5`, 12 GB, %100 GPU, context 4096 ve llamacpp runner görünüyordu. Basit hesap ve düşük düşünme ayarıyla Türkçe yanıt çalıştı.

Ardından kullanıcı 0.1.0 kurulumunun paket/model indirmelerini ve gerçek model yükleme kontrolünü başarıyla bitirdiğini paylaştı; EMA sesini beğendiğini bildirdi. Bu, 0.2.0'ın Windows güncelleyicisi veya yeni fiziksel mikrofon akışının doğrulanmış olduğu anlamına gelmez.

## 2. Otomatik test sonucu

**94/94 Python ve 25/25 JavaScript testi geçti.** Atlanan, başarısız veya iptal edilen test yok. Python testleri yaklaşık 1,4 saniye, JavaScript testleri yaklaşık 1,2 saniye sürdü; bunlar sohbet performansı metriği değildir.

| Alan | Doğrulanan davranış |
|---|---|
| Protokol ve erişim | Loopback/origin/açılış anahtarı; protokol 2 kabul, 1 ret; session/epoch kuralları. |
| İptal ve oynatma | Geç cevap/ACK sonrası eski sesin başlamaması; native CPU işi bitmeden slotun bırakılmaması; TTS hata yayılımı ve sınırlı kuyruklar. |
| Profil ve tanışma | İsim/enum/şema doğrulaması; sesli/yazılı karışık tanışma; son onaydan önce dosya yazmama; iptal/dur/devam; atomik dosya. |
| Mikrofon kontrolü | Yönergenin bütün ACK'lerini bekleme; tam 94 gürültü karesi; sessiz/yanlış/kırpılmış örneği reddetme; klavyeyi ölçüm saymama; sunucu sonucunu açıkça uygulama. |
| Akustik çekirdek | Mono/float/süre/sonluluk sınırları; sinüs/noise/sessizlik; girişin değişmezliği; 160 kare sınırı; sayısal metadata izin listesi. |
| Akustik entegrasyon | Kapalıyken çağrı yok; açıkken aynı gözlem UI/LLM'de; kapatıp açma veya epoch değişiminde geç sonucu düşürme. |
| Analiz + rehberli akış | Pending kalibrasyon yönergesi, ASR işlemi ve tanışma TTS'si sırasında analiz kapatmanın rehberi bozmaması. |
| Arama gizliliği | Ölçümsüz araç kararı; ölçümlü araçsız son yerel yanıt; arama gerekmeyince de ilk ölçümsüz cevabı yayımlamama. |
| Ollama | Shared client ömrü; preload; content/thinking ayrımı; final done/length kontrolü; sayısal süre dönüşümü; iptal. |
| Güncelleme | Yedek/manifest, rollback, değişen kullanıcı dosyasını koruma, port/şema/bağımlılık/yol kontrolleri; veri/env kapsam dışında. |
| Frontend | Sahte DOM/WebAudio ile izin, stop, profil, kalibrasyon, ölçüm panelleri, gerçek ayar izin listesi, API anahtarının depolanmaması. |
| Örnekleme | 16/44,1/48 kHz girişte 10 saniye → 160.000 örnek; tam 512 örnekli PCM16 kareler; 12 kHz ton bastırma. |

Akustik F0 testleri 100/220/300 Hz sinüsler için ±0,6 Hz toleransla geçti. Bu, insan sesinde harmonik/oktav hatasının olmayacağını kanıtlamaz. “Duygu” veya “hastalık” doğruluğu testi yapılmadı; paket bu tür bir sınıflandırıcı içermez.

## 3. Gerçek model ve ses kontrolleri

0.1.0 aşamasında Python 3.11.18 Linux ortamında sabit paketler kuruldu; Whisper small ve EMA CPU modelleri gerçek dosyalarla açıldı. Silero V6'nın kare akışı resmî toplu uygulamayla karşılaştırıldığında maksimum fark 0,0 idi. Üç EMA Türkçe örneğinin Whisper çıktıları `speech_check.json` içinde bulunur; bunlar benchmark değildir.

0.2.0 gerçek model kontrolü `VOICE_V2_CHECK.json`:

- İlk tanışma yönergesinin üç parçası EMA ile üretildi; tekrardaki önbellek PCM'i bit düzeyinde aynıydı.
- Ölçülen önbellek 503.040 bayt; sınır 8.388.608 bayt ve en fazla 24 giriş.
- Kalibrasyon referansı EMA ile üretildi; Whisper aynı cümleyi verdi, bu tek örnekte WER=0.
- Bu örnekte TTS 371,41 ms; ASR 1.841,79 ms; üretilen ses 3,16 saniye. Süreler Linux test ortamına ait ve uçtan uca mikrofon gecikmesi değil.
- TTS kaynak dosyası 0.1.0 ile aynı; ses modeli/adaptörünün değişmediği kontrol edildi.

`ACOUSTIC_SAMPLE_CHECK.json`, paketteki gerçek EMA çıktısı olan 1,96 saniyelik `SES_ORNEGI.wav` üzerinde sonlu/sınırlı akustik sonuç üretildiğini kaydeder. Bu örnekte analiz 19,317 ms sürdü; Windows beklentisi veya insan F0/duygu doğruluğu değildir. WPM için verilen metin örneğin bilinen cümlesidir, bu kontrolde yeniden ASR yapılmadı.

## 4. Yakalanan somut birleşim hataları

- Tanışma önbelleğinin bütün paragraf yerine gerçek cümle parçalarıyla eşleşmesi düzeltildi.
- Tanışma profilini yazma başarısızlığında taslağın onay aşamasında kalması sağlandı.
- Kalibrasyon yönergesi oynarken veya ölçüm ASR'si beklerken analiz kapatmanın işi iptal edip ölçüm işaretini bırakması düzeltildi; üç regresyon testi eklendi.
- İnternet açık, araç çağrısı yok durumunda akustik verinin normal yanıta ulaşmaması düzeltildi. Ölçümsüz araç kararı korunarak ayrı yerel son çağrı eklendi; ek gecikme README'de açıklanır.
- İstemcinin eski ölçüm/süre olaylarını daha yeni kontrol ACK'inden önce kabul etmesi engellendi.
- Önceki sürümde bulunan CPU iptali, TTS hata yayılımı, eksik Ollama akışı, konuşma üst sınırı ve ondalık cümle bölme regresyonları korunur.

## 5. Ağ/telemetri ve test sınırı

ONNX Runtime telemetri opt-out'u native importtan önce uygulanır. İlk sürümde telemetri bağlantısı nedeniyle engellenen deneme başarılı sayılmadı; belgelenmiş opt-out eklendikten sonra model kontrolü tamamlandı. Son ses kontrolünde UCX'in yerel VFS socket açamama mesajı görüldü; süreç exit 0 ile ölçümü üretti. Bu mesaj bir duygu/mikrofon başarısı metriği değildir.

Bu ortamda **doğrulanmayanlar**: Windows CMD/PowerShell dosya seçicisinin gerçek çalışması; 0.2.0 fiziksel mikrofon/hoparlör yankısı; gerçek tarayıcı oynatması; kullanıcının işlemci/GPU'sundaki gecikme; canlı GPT-OSS ile yeni akışın tamamı; kullanıcı anahtarlı canlı web servisi. Önceki Chromium girişimi ortamın socket kısıtı nedeniyle açılamadı; sahte DOM testleri bunun yerine uçtan uca tarayıcı testi gibi sunulmaz.

Profil isteminin her zaman uygulanacağı, tüm yanıtların güvenli/doğru olacağı, duygu çıkarımı veya terapi yararı kanıtlanmadı. Bu uygulama mevcut haliyle konuşma/ölçüm prototipidir.

## 6. Tekrarlama

Kurulum klasöründe:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m jarvis.verify
```

Geliştirme ortamında:

```text
node --test tests/test_frontend.js tests/test_resampler.js
```

`jarvis.verify` kurulumda indirilmiş yerel modelleri gerektirir; mikrofon açmaz ve web araştırması yapmaz. Geçici Linux geliştirme ortamında testler, hazır tokenizer/model önbelleğini `JARVIS_DATA_DIR` ile mevcut model klasöründen okudu; kalıcı kayıt testleri geçici klasörler kullandı.

## 7. İlk Windows kabulü

GUNCELLE.cmd → eski BASLAT.cmd seçimi → eski BASLAT.cmd ile açılış → sesli tanışma → mikrofon ölçümü → kısa normal sohbet. Sonra analiz seçeneğini aç/kapat ve panelin güncel tur davranışını gözle. Sorun halinde hata mesajını, son yanıt sürelerini ve yanlış duyulan cümleyi paylaş; ham ses veya API anahtarını paylaşmak gerekmez.
