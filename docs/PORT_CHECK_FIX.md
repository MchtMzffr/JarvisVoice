# 0.2.1 — Windows güncelleme port kontrolü

## Gözlenen hata ve belirsizlik

0.2.0 kullanıcı çıktısı: `8765 portu kontrol edilemedi. Jarvis'i kapatıp yeniden dene.` Kodda `socket.create_connection(("127.0.0.1", 8765), timeout=0.5)` kullanılıyordu. ConnectionRefused dışındaki OS hataları aynı mesaja çevrildiği için bu tek çıktı gerçek nedeni belirlemiyor. Timeout olası bir açıklamadır; doğrulanmış teşhis değildir. Her iki kontrol de uygulama kodunu değiştirmeden önce çalışır.

## Dar değişiklik

`update_jarvis.py::jarvis_port_in_use`, Windows'ta AF_INET/SOCK_STREAM socket açar; SO_EXCLUSIVEADDRUSE seçeneğini bind'den önce ayarlar ve 0.0.0.0:8765'e geçici bind dener. Socket hemen kapatılır. listen/accept/connect veya SO_REUSEADDR kullanılmaz. Uygulamanın gerçek sunucusu 127.0.0.1 üzerinde kalır.

| Sonuç | Güncelleme davranışı |
|---|---|
| Başarılı exclusive bind ve kapanış | Port o anda alınabildi; devam edebilir. |
| Bind aşamasında EADDRINUSE / WSAEADDRINUSE10048 | Kullanımda; yazma durur. |
| WSAEACCES10013, seçenek/oluşturma/kapanış hatası veya başka sonuç | Bilinmiyor; yazma durur, aşama ve sayısal kod verilir. |

10013 yalnız “Jarvis açık” anlamına gelmez; erişim, rezervasyon veya bind çakışması olabilir. Windows'un wildcard/belirli IP davranışları farklı olduğundan probe wildcard kullanır. Önceki TCP bağlantılarının kapanması tamamlanmadıysa muhafazakâr biçimde engelleyebilir. Kontrolün anlık olduğu ve iki kontrol arasındaki sürenin sıfır olmadığı kabul edilir; güncelleme kilidi ve başlatıcı kontrolü de korunur.

`UPDATER_PORT=8765`, uygulamayı import etmeden kullanılan güncelleyici sabitidir. Asıl uygulama portu `jarvis/config.py::Settings.port`; bunlar değişirse birlikte uyumluluk değerlendirmesi gerekir. Model/Python/veri klasörleri güncelleme kapsamına girmez.

## Kanıt

`tests/test_update_port.py`: boş/kullanımda/bilinmiyor, doğru hata aşaması, redaction, socket kapanması, yalnız bind, yazma öncesi iki kontrol. Üç native Windows testi geçici port kullanır: boş port, loopback listener, aynı kullanıcı/default seçenekli wildcard listener. Linux'ta bu üçü atlanır; fake testler native Windows kanıtı sayılmaz. Güncel çalıştırma sonucu `VALIDATION.md` ve GitHub Actions'ta izlenir.

## Birincil kaynaklar

- [Microsoft: SO_REUSEADDR ve SO_EXCLUSIVEADDRUSE](https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse)
- [Microsoft: bind](https://learn.microsoft.com/en-us/windows/win32/api/winsock2/nf-winsock2-bind)
- [Python 3.11: socket](https://docs.python.org/3.11/library/socket.html)

Bu düzeltme Windows güvenlik duvarını, ExecutionPolicy'yi veya yönetici izinlerini değiştirmez; süreç öldürmez ve belirsiz kontrolü atlamaz.
