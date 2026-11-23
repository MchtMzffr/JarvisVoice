# JarvisVoice — gelişim sırası

Bu liste geliştirme sırasını ve kabul kanıtlarını tanımlar; tarih veya başarı taahhüdü değildir. Güncel sonuç [PROJECT_STATE.md](PROJECT_STATE.md) içinde tutulur.

## 1. Windows güncellemeyi çalışır duruma getirme — aktif

- `update_jarvis.py`: port kontrolünde serbest/meşgul/bilinmeyen durumlarını ayır; Windows'ta kısa TCP connect yoklamasına bağımlılığı kaldır.
- `tests/test_update_port.py`: Windows socket sahte nesneleriyle seçenek sırası, kapatma, hata kodları, belirsizlikte durma ve bağlantı kurulmamasını doğrula.
- `tests/test_update.py`: veri/ortam koruma, yedek ve geri alma invariantlarını sürdür.
- Gerçek Windows kabulü: güncelleme 0.1.0/0.2.0 kurulumundan tamamlanmalı; mevcut modeller yeniden indirilmeden `BASLAT.cmd` açılmalı. Gerçek port meşgulse dosya yazılmamalı.

**Kabul:** ilgili otomatik testler ve kullanıcı Windows sonucu ayrı kaydedilir. Test sayısı gerçek Windows başarısının yerine geçmez.

## 2. Depodan izlenebilir çalışma — aktif

- Kaynak, test, sürüm ve dağıtım bilgilerini aynı değişiklikte tut.
- Kısa çalışma durumu, kararlar ve bilinen sorunları commit'lerle güncelle.
- GitHub üzerinden odaklı Windows test otomasyonu için uygun iş akışını kur; çalışmayan veya atlanan kontrolleri yeşil sonuç gibi raporlama.
- Sürüm paketlerinin içerik izin listesini koru; kişisel veriler, ağırlıklar, sanal ortamlar ve yedekler dağıtıma karışmamalı.

**Kabul:** son commit'ten hangi sürümün üretildiği, neyin değiştiği ve hangi doğrulamanın yapıldığı anlaşılabilir olmalı.

## 3. Gerçek konuşma ve gecikme kabulü

- Sesli tanışma, son onay, iptal ve yeniden başlatma yollarını gerçek mikrofonla dene.
- Kulaklık ve hoparlörü ayrı değerlendir; yankı ve cümleyi erken bitirme olaylarını say.
- ASR kelime hatası, endpoint süresi, ilk metin ve sunucuda ilk ses hazırlığı için aynı koşullarda ölçüm al.
- Sıcak/soğuk model, internet açık/kapalı, analiz açık/kapalı koşullarını ayır; p50/p95 ve örnek sayısını birlikte raporla.
- CPU/GPU ASR alternatifini ancak bu ölçümler somut darboğaz gösterirse karşılaştır; VRAM ve toplam ilk yanıt gecikmesini birlikte değerlendir.

**Kabul:** bir değişiklik gecikmeyi azaltırken kelime hatasını, erken kesilmeyi veya iptal davranışını bozuyorsa bu bedel açıkça gösterilir. Sunucuda hazır ses zamanı gerçek hoparlör gecikmesi diye adlandırılmaz.

## 4. İsteğe bağlı duygu araştırması — ürün özelliği olarak doğrulanmadı

- Akustik ölçüm sözleşmesi korunur; model tahmini ayrı, sürümlü ve belirsizlik taşıyan bir sözleşmeyle ele alınır.
- Önce hedef tanımlanır: kişinin kendi bildirdiği duygu ile dinleyicinin algıladığı duygu aynı etiket değildir.
- Türkçe konuşmacı ve oturum ayrılmış test; sınıf bazlı hatalar, macro-F1/UAR, kalibrasyon ve bilinmiyor oranı gerekir.
- Yalnız metin, yalnız ses ve ses+metin karşılaştırmasıyla sesin ek yararı ölçülür.
- Model/etiket/lisans uygunluğu ve ek CPU, bellek, gecikme maliyeti incelenir.

**Kabul:** ayrılmış testte yarar gösterilmeden tahminler sohbet kararını yönetmez. Bir modelin skor vermesi, duygunun kesin bilindiği veya skorun güven olasılığı olduğu anlamına gelmez. Kaynak ve sınırlar: [SES_ANALIZI_KANITLARI.md](SES_ANALIZI_KANITLARI.md).

## 5. Destekleyici sohbet davranışı

- Kullanıcının söylediği duyguyu ve istediği yardım biçimini esas alan konuşma senaryoları oluştur.
- Yanlış duygu atfetme, gereksiz teşhis, yargılayıcı yanıt ve sürekli soru sorma gibi istenmeyen davranışları ayrı değerlendir.
- Konuşmayı kesme, mikrofonu kapatma, analizden çıkma ve açık kayıtları silme yolları korunur.

**Kabul:** davranış testleri ve kullanıcı geri bildirimi raporlanır. Tedavi veya hastalık tespiti iddiası, bu prototipin yazılım testlerinden çıkarılamaz; böyle bir hedef ayrı klinik çalışma ve uzman değerlendirmesi gerektirir.
