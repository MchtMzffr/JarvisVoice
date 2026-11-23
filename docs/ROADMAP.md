# JarvisVoice — gelişim sırası

Bu liste geliştirme sırasını ve kabul kanıtlarını tanımlar; tarih veya başarı taahhüdü değildir. Güncel sonuç [PROJECT_STATE.md](PROJECT_STATE.md), ayrıntılı doğrulama [VALIDATION.md](VALIDATION.md) içindedir.

## 1. 0.3.0 birleşik masaüstü — kod hazır, doğrulama/kullanıcı kabulü sürüyor

- `desktop.py` ve `__main__.py`: Windows WebView2 penceresi, loopback sunucu ömrü, kapanış, gezinme ve popup sınırları.
- `static/*` ve `server.py`: aynı pencerede yazılı/sesli sohbet, seslendirme tercihi, profil/kalibrasyon ve plan kartları. Normal metin yanıtı tamamlanmadan geçmişe yazılmaz; rehberli yönergeler sesli kalır.
- `setup_local.py`, `KUR.cmd`, `BASLAT.cmd`: açık ilk kurulum eksik bileşenleri tamamlar; günlük başlatma mevcut kurulumu kullanır. Beğenilen EMA sesi ve mevcut GPT-OSS modeli korunur.
- `update_jarvis.py`, `GUNCELLE.cmd`: eski kurulumun verilerini ve model konumlarını koruyan kod aktarımı, ardından kilitli masaüstü paketlerinin kurulumu. İki aşamanın hata/geri alma kapsamı ayrı gösterilir.

**Kabul:** Windows ve Linux otomatik sonuçları, gerçek Windows WebView2 pencere kontrolü ve kullanıcının fiziksel ses/LLM kabulü ayrı kaydedilir. Native Windows 0.3.0 sonucu henüz bekleniyor; birim testleri bunun yerine geçirilmez.

## 2. Kişisel bağlam, seçili uygulamalar ve plan — ilk sürüm eklendi

- Kişisel bağlam mevcut onaylı profil ve “Bunu hatırla: …” notlarından gelir. Kullanıcının açıklamadığı kişilik, duygu, uygunluk veya alışkanlıklar gerçek gibi kaydedilmez.
- `actions.py`: Hesap Makinesi, Not Defteri, Dosya Gezgini ve Paint için sabit katalog. Oturum izni, doğrudan kullanıcı isteği, güncel epoch, hız ve tekrar denetimi birlikte geçmelidir. Serbest yol/argüman/shell yürütme açılmaz.
- `plans.py` ve `llm.make_plan`: yerel modelin şemalı planı önce RAM taslağıdır; sonlu süre, adım ve metin sınırları vardır. Tek kayıt yalnız açık istekte `data/plan.json` içine yazılır.
- Plan kartındaki kayıt, iptal ve silme ilgili plan kimliğine bağlıdır. Sesle kayıt genel “evet” yerine açık “Planı kaydet” komutuyla yapılır. Plan bir öneridir; takvim, hatırlatıcı veya otomatik eylem zinciri içermez.

**Kabul:** kapalı izinle sıfır uygulama başlatma; eski epoch/model/web çıktısından sıfır eylem; açık kayıt öncesi sıfır plan yazımı; geçersiz/bozuk/gelecekteki plan şemasının korunması. Gerçek uygulama penceresinin görünmesi ve planın kişiye uygunluğu ayrıca kullanıcıyla doğrulanır.

## 3. Gerçek konuşma ve gecikme kabulü

- Masaüstü penceresinde yazışma, seslendirmeyi kapatma/açma, mikrofon izni, tanışma, son onay, iptal ve yeniden başlatma yollarını dene.
- Kulaklık ve hoparlörü ayrı değerlendir; yankı ve cümleyi erken bitirme olaylarını say.
- ASR kelime hatası, endpoint süresi, ilk metin ve sunucuda ilk ses hazırlığı için aynı koşullarda ölçüm al.
- Sıcak/soğuk model, internet açık/kapalı, analiz açık/kapalı koşullarını ayır; p50/p95 ve örnek sayısını birlikte raporla.
- CPU/GPU ASR veya başka optimizasyonu ancak bu ölçümler somut darboğaz gösterirse karşılaştır; VRAM ve toplam ilk yanıt gecikmesini birlikte değerlendir. Ses/model değişikliğini kullanıcı tercihinden bağımsız varsayma.

**Kabul:** bir değişiklik gecikmeyi azaltırken kelime hatasını, erken kesilmeyi veya iptal davranışını bozuyorsa bu bedel açıkça gösterilir. Sunucuda hazır ses zamanı gerçek hoparlör gecikmesi diye adlandırılmaz. 0.3.0 için yeni performans artışı henüz doğrulanmadı.

## 4. Daha geniş uygulama ve plan yetenekleri — sonraki kapsam

- Yeni uygulamalar için önce isim/kimlik, sabit başlatma şekli, kullanılabilirlik ve hata sonucu tanımlanır; sonra katalog ve testler genişletilir.
- Belirsiz “onu aç” veya çok adımlı isteklerde yanlış eylem yerine açıklama/inceleme akışı tasarlanır. Dört uygulamalık mevcut izin, genel bilgisayar kontrolü yetkisi sayılmaz.
- Plan düzenleme, adım tamamlanma durumu, birden fazla plan ve gerçek takvim/hatırlatıcı gereksinimleri ayrı sözleşme ve kalıcı şema kararıyla ele alınır.
- Kullanıcının notlarını seçme/unutma deneyimi ve bağlama sığmayan bilgi görünürlüğü iyileştirilirken açık kayıt ve veri silme davranışı korunur.

**Kabul:** ek yetki ve kalıcılık değişimi için somut kullanıcı ihtiyacı, izin sınırı, iptal/hata senaryosu ve ölçülebilir test gerekir. Bu yetenekler 0.3.0'da varmış gibi gösterilmez.

## 5. İsteğe bağlı duygu araştırması — ürün özelliği olarak doğrulanmadı

- Akustik ölçüm sözleşmesi korunur; model tahmini ayrı, sürümlü ve belirsizlik taşıyan bir sözleşmeyle ele alınır.
- Önce hedef tanımlanır: kişinin kendi bildirdiği duygu ile dinleyicinin algıladığı duygu aynı etiket değildir.
- Türkçe konuşmacı ve oturum ayrılmış test; sınıf bazlı hatalar, macro-F1/UAR, kalibrasyon ve bilinmiyor oranı gerekir.
- Yalnız metin, yalnız ses ve ses+metin karşılaştırmasıyla sesin ek yararı ölçülür.
- Model/etiket/lisans uygunluğu ve ek CPU, bellek, gecikme maliyeti incelenir.

**Kabul:** ayrılmış testte yarar gösterilmeden tahminler sohbet kararını yönetmez. Bir modelin skor vermesi, duygunun kesin bilindiği veya skorun güven olasılığı olduğu anlamına gelmez. Kaynak ve sınırlar: [SES_ANALIZI_KANITLARI.md](SES_ANALIZI_KANITLARI.md).

## 6. Destekleyici sohbet davranışı

- Kullanıcının söylediği duyguyu ve istediği yardım biçimini esas alan konuşma senaryoları oluştur.
- Yanlış duygu atfetme, gereksiz teşhis, yargılayıcı yanıt ve sürekli soru sorma gibi istenmeyen davranışları ayrı değerlendir.
- Konuşmayı kesme, mikrofonu kapatma, analizden çıkma ve açık kayıtları silme yolları korunur.

**Kabul:** davranış testleri ve kullanıcı geri bildirimi raporlanır. Tedavi veya hastalık tespiti iddiası bu prototipin yazılım testlerinden çıkarılamaz; böyle bir hedef ayrı klinik çalışma ve uzman değerlendirmesi gerektirir.

## Her değişiklikte: depodan izlenebilir çalışma

Kaynak, test, sürüm ve dağıtım bilgileri aynı değişiklikte tutulur. Kısa çalışma durumu ve bilinen sorunlar güncellenir; başarısız veya atlanan CI kontrolleri başarı gibi sunulmaz. Kişisel veriler, anahtarlar, ağırlıklar, sanal ortamlar ve yedekler commit/dağıtım kapsamına girmez. Son commit'ten sürümün, değişen davranışın ve doğrulama kapsamının anlaşılması gerekir.
