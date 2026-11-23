# Jarvis Voice sözleşmeleri — uygulama 0.2.1 / protokol 2

Bu uygulama bağımsız bir prototiptir; Decision Ecosystem depolarını/core bağımlılıklarını değiştirmez. Çalışma parametreleri için tek yetkili tanım `jarvis/config.py::Settings`, veri sözleşmeleri için `jarvis/contracts.py` ve `jarvis/profile.py` esas alınır. `PARAMETER_INDEX.md` bu kaynaklardan üretilir. ASR, TTS, LLM ve web çağrıları ayrı adaptörlerdir.

## Ses ve bağlantı

Giriş: mono 16 kHz, little-endian PCM16, tam 512 örnek / 1024 bayt kare. Python VAD/ASR/analiz girişi float32 [-1,1]. TTS çıkışı PCM16; örnekleme hızı envelope içindedir (EMA 24 kHz). Tarayıcı aygıtı farklı hızda çalışabilir; frontend 16 kHz'e dönüştürür.

WebSocket yalnız izin verilen localhost origin'lerinden, açılış anahtarıyla kabul edilir. İlk mesaj `{type:"hello", protocol:2, token:"..."}` olmalıdır. Aynı anda tek aktif oturum vardır; sunucu `session_id` üretir. Protokol 1 arayüzü reddedilir; uygulama ve statik dosyalar birlikte güncellenir.

| Yön | Olay | Alanlar / anlam |
|---|---|---|
| İstemci → sunucu | start / stop / interrupt / text | `request_id`; text ayrıca `text` taşır. |
| İstemci → sunucu | onboarding_start / onboarding_cancel | Sesli tanışma; eşleşen epoch ACK'i. |
| İstemci → sunucu | profile_save | `request_id`, doğrulanacak `profile`; açık kullanıcı kaydı. |
| İstemci → sunucu | calibration_start / calibration_cancel / calibration_apply | İstemci eşik belirlemez; yalnız sunucunun son uygun sonucu uygulanabilir. |
| İstemci → sunucu | settings | web_enabled, barge_in, acoustic_enabled; isteğe bağlı api_key. |
| İstemci → sunucu | capture_info | sample_rate, channel_count, echo_cancellation, noise_suppression, auto_gain_control. |
| İstemci → sunucu | binary / played | PCM16 karesi; `played`: epoch, segment_id, tamamlanmış oynatma ACK'i. |
| Sunucu → istemci | hello / ready / status / epoch | Kimlik, hazır olma, durum; epoch sunucunun tekelindedir. |
| Sunucu → istemci | audio / audio_end | epoch, turn_id, segment_id, sample_rate, base64 PCM16, text. audio_end yeni sesin bittiğini bildirir; planlanmış sesi kesmez. |
| Sunucu → istemci | profile / onboarding | Onaylı profil; rehberin active/stage/message bilgisi. |
| Sunucu → istemci | calibration | prompt/noise/phrase/result/cancelled/error/applied aşaması ve varsa ölçümler. |
| Sunucu → istemci | acoustics | epoch ve AcousticObservation şema 1. |
| Sunucu → istemci | transcript / sources / memories | Metin; gerçek araç kaynakları; kullanıcının açıkça kaydettiği notlar. |
| Sunucu → istemci | metrics / capture_stop / error | Süreler; mikrofonu açıkça durdurma; sınırlı anlaşılır hata. |

## Profil — şema 1

`Profile`: assistant_name, user_name, style, verbosity, pause, output, onboarding_complete, schema_version. İsimler en fazla 40 karakter/dört sözcük; sınırlı Unicode karakterleri kabul edilir. Tercihler enum'lardan seçilir. Bu doğrulama model düzeyinde prompt enjeksiyonunu bütünüyle çözdüğü iddiasını taşımaz.

`Onboarding` bir durum makinesidir: kullanıcı adı → yardımcı adı → tarz → uzunluk → duraklama → çıkış aygıtı → onay. Taslak RAM'de kalır. Son açık onay veya form kaydı yoksa `ProfileStore.save` çağrılmaz. İptal mevcut onaylı profili değiştirmez. Yazma, aynı dizinde geçici dosya + flush/fsync + atomik replace ile yapılır. Bozuk veya gelecekteki şema sessizce sıfırlanmaz.

## Mikrofon kontrolü

Yönergeye ait bütün oynatma ACK'leri gelmeden ölçüm başlamaz. Ortam örneği 94 × 512 / 16000 = **3,008 saniyedir**. Sonra sabit Türkçe cümle gerçek ASR'den geçirilir. Klavye metni bu ölçümün yerine kabul edilmez.

- WER = kelime düzeyinde Levenshtein uzaklığı / referans kelime sayısı. Harf büyüklüğü ve noktalama normalize edilir; farklı kelimeler düzeltilmiş sayılmaz. WER 1'den büyük olabilir.
- Yaklaşık seviye farkı = konuşma RMS dBFS − ortam RMS dBFS. Ayrı segmentler ve tarayıcı işlemleri nedeniyle fiziksel SNR ölçümü değildir.
- Önerilen VAD eşiği = min(0,80; max(0,60; ortam VAD p95 + 0,10)).
- Sessizlikte konuşma benzeri kare oranı > 0,10; kırpılma > %0,1; sinyal < −55 dBFS; seviye farkı < 10 dB veya WER > 0,35 ise uygulama engellenir.

Eşikler ilk mühendislik sezgileridir; Türkçe doğruluk veya klinik karar eşiği olarak kalibre edilmemiştir. `CalibrationStore`, yalnız schema_version=1, vad_threshold ve saved_at alanlarını saklar. Ham ses, örnek cümle veya ölçüm geçmişi kalıcı dosyaya yazılmaz. Aşama beklemesi 30 saniye, oynatma ACK beklemesi 45 saniye ile sınırlıdır.

## Akustik gözlem — şema 1

`AcousticObservation` alanları:

```text
schema_version, duration_s, rms_dbfs, peak_dbfs, clipping_pct,
speech_fraction, pause_fraction, words_per_minute,
f0_median_hz, f0_iqr_hz, f0_coverage, analysis_ms,
signal_valid, limitations, capture
```

`analyze` mono, sonlu, normalize float ve en fazla 30 saniyelik veri kabul eder. Giriş dizisini değiştirmez. Analiz 40 ms'lik en fazla 160 karede F0 arar; 60–500 Hz aralığı ve 0,8 normalize otokorelasyon eşiği kullanılır. **Eşik ve kapsama güven olasılığı değildir.** F0 bulunamazsa `null` olur. `signal_valid` yalnız yeterli değişken dijital sinyal anlamına gelir; insan konuşması veya bir ruh hâli kanıtı değildir.

RMS = sqrt(sum(x²)/N); dBFS = 20 log10(max(RMS, 10^-6)). dBFS tabanı −120'dir; JSON'a sonsuz/NaN yazılmaz. Yaklaşık WPM = 60 × ASR kelime sayısı / süre; geçersiz sinyal veya sıfır konuşma oranında üretilmez. VAD oranı kırpılmış turdaki ön/son paylardan etkilenir; gerçek fonetik duraklama etiketlemesi değildir.

Akustik inceleme oturum başında kapalıdır. Açıkken ASR ile ayrı sınırlı CPU işi olarak başlar; tanışma ve kalibrasyonda çalışmaz. Ham PCM LLM'ye verilmez. Güncel tur için ölçüm JSON'u yalnız yerel araçsız yanıt üretiminde kullanılabilir. Web arama kararına ölçüm nesnesi eklenmez; gerekiyorsa ikinci yerel çağrı yapılır. Modelin önceki sözlü yanıtında açıkladığı sayılar normal oturum metninde kalabilir; tüm konuşmanın kusursuz gizliliği iddia edilmez.

## İptal, kayıt ve güvenlik invariantları

1. Sesin kabulü `session_id`, güncel epoch, oynatma izni ve bekleyen kontrol ACK'iyle sınırlıdır. Eski epoch veya gecikmiş ses yeni turda çalmaz.
2. Epoch'u yalnız sunucu artırır. Başka bir epoch olayı, daha yeni kullanıcı kontrolünün `request_id` ACK'i yerine geçmez.
3. Stop/interrupt/disconnect mevcut ve planlanmış tarayıcı ses kaynaklarını durdurur. Mikrofon izin isteği geç sonuçlanırsa durdurulmuş oturumu tekrar açamaz.
4. Her CPU adaptörü için tek çalışan iş vardır. Async iptal, native hesabın durduğunu varsaymaz; hesap bitene kadar slot korunur. Sonuç artık güncel değilse yayımlanmaz.
5. PCM, analiz kareleri, ses kuyruğu, oynatma ACK'leri, metin ve web istekleri sınırlıdır. Tur limiti dakikada 20'dir; tek konuşmanın zorunlu sınırında eksik soru yanıtlanmaz.
6. Yalnız Ollama `message.content` seslendirilir; `thinking` alanı TTS'ye girmez. Eksik/uzunluk sınırında kesilen akış tamamlanmış yanıt sayılmaz.
7. Kalıcı hatıra kaydı yalnız doğrudan kullanıcı komutuyla olur. Web/model çıktısı dosya yazma yetkisi vermez.
8. Profil taslağı onaysız yazılmaz; başarılı ölçüm ve açık uygulama isteği olmadan mikrofon eşiği değişmez. Bilinmeyen şema korunur ve işlem durur.
9. Analiz kapatılması normal turu keser; önceki native analiz geç bitse veya hemen yeniden açılsa bile eski gözlem LLM/UI'a sızmaz. Rehberli akışlar analiz almadığından bu ayar onları kesmez.
10. Ölçüm sözleşmesi duygu, tanı, kimlik veya kişilik alanı içermez. Model davranışı için ayrıca istem kuralları vardır; bunlar klinik doğrulama veya tam güvenlik garantisi değildir.
11. Capture metadata izin listesi cihaz kimliği/etiketi/serbest metni atar. API anahtarı yalnız RAM'dedir; geri gönderilmez/loglanmaz.
12. Kaynak URL'leri gerçek araç sonuçlarından gelir. Bu bağlantılar her iddianın doğruluğunu kanıtlamaz.
13. 4096 token bağlamdan 1024 çıktı + 320 format payı ayrılır. `o200k_harmony` sayımıyla eski turlar ve kaynaklar gerektiğinde düşürülür. Yalnız oynatma ACK'i gelmiş cevap cümleleri sohbet geçmişine eklenir.
14. Çalışma anında eksik ses modeli otomatik indirilmez. Başlangıçta yerel Ollama ön yüklemesi başarısızsa model değiştirilmez; normal istekte yeniden denenir.
15. Güncelleme öncesinde kod yedeği doğrulanır; kullanıcı verileri izin listesi dışındadır. Değişen bir kullanıcı dosyası, geri almada körlemesine ezilmez.

## Sürelerin anlamı

- `endpoint_ms`: son VAD konuşma karesinden tur işleme başlangıcına kadar geçen süre.
- `asr_ms`: ASR işi/slot beklemesi dâhil ölçülen çağrı süresi.
- `analysis_ms`: ölçüm fonksiyonunun kendi çalışma süresi; kuyruk beklemesi içermez.
- `llm_first_ms`: yanıt üretimini başlatmadan ilk kullanıcıya dönük metne kadar; web kararı/araştırma varsa onları da içerir. Hazır yönergede null.
- `first_audio_ms` ve `server_audio_ready_ms`: son VAD konuşma anından ilk PCM'in gönderime hazır olmasına kadar. Yazılı/rehberli turda tur başlangıcı esas alınır.
- `tts_first_ms`: ilk cümlenin TTS/önbellek dönüş süresi; `tts_rtf` = bu süre / üretilen sesin süresi.
- Ollama sayaçları başarılı son yanıt isteğinin verdiği sayısal alanlardan alınır; ns→ms çevrilir. Eksik sayaç uydurulmaz.

Yaklaşık gecikme ayrışımı: T_endpoint + max(T_ASR, T_analiz) + T_ilk_seslendirilebilir_metin + T_TTS + aktarım/planlama. Bu bir zamanlama modeli, ölçülmüş Windows sonucu değildir. İlk metin tokenı ile ilk tamamlanmış cümle aynı an değildir. Hoparlörden gerçekten duyulma zamanı henüz ölçülmez.

## Sürümleme ve değişiklik kapısı

Uygulama SemVer **0.2.1**; dağıtım öncesi deneysel 0.x aşamasıdır. Protokol **2**; profil/kalibrasyon/gözlem şemaları **1**; SQLite user_version **1**. 0.1.0 verisi korunur, 0.1 frontend desteği 0.2.0 ile biter; bütün dosyaları birlikte taşıyan güncelleyici geçiş yoludur. Gelecekte protokol kırılması yeni numarayla, kalıcı şema kırılması açık migration ve yedek/geri alma tarifiyle yayımlanmalıdır. Yeni deprecation tarihleri o sürümün değişiklik kaydında duyurulur; burada verilmemiş takvim taahhüdü yoktur.

## 0.2.1 düzeltmesi

Port kontrolünün Windows uygulaması ve hata görünürlüğü değişti; protokol/şema/bağımlılık değişimi yok. Karar tablosu ve kalan sınır [PORT_CHECK_FIX.md](PORT_CHECK_FIX.md) içinde.
