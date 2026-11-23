# PARAMETER_INDEX — 0.2.1

Ayarlanabilir çalışma parametreleri için tek yetkili tanım `jarvis/config.py::Settings`. Tablo bu tanımdan üretilmiştir; çalışma sırasında Markdown okunmaz. Format/şema sabitlerinin konumları aşağıdadır.

| Parametre | Varsayılan |
|---|---|
| `protocol_version` | `2` |
| `host` | `127.0.0.1` |
| `port` | `8765` |
| `ollama_url` | `http://127.0.0.1:11434` |
| `model` | `gpt-oss:20b` |
| `num_ctx` | `4096` |
| `think` | `low` |
| `num_predict` | `1024` |
| `keep_alive` | `30m` |
| `warmup_timeout_s` | `45` |
| `sample_rate` | `16000` |
| `frame_samples` | `512` |
| `vad_threshold` | `0.6` |
| `onset_frames` | `3` |
| `end_silence_frames` | `25` |
| `preroll_frames` | `10` |
| `min_speech_frames` | `7` |
| `max_utterance_frames` | `937` |
| `asr_threads` | `6` |
| `tts_threads` | `4` |
| `max_text_chars` | `1600` |
| `max_sentence_chars` | `180` |
| `history_max_chars` | `2400` |
| `memory_max_chars` | `800` |
| `web_page_max_chars` | `1400` |
| `web_max_fetches` | `2` |
| `web_query_max_chars` | `240` |
| `turn_limit_per_minute` | `20` |
| `max_pending_audio` | `2` |
| `ollama_timeout_s` | `120` |
| `web_timeout_s` | `20` |
| `playback_ack_timeout_s` | `45` |
| `context_framing_reserve` | `320` |
| `pause_frames_quick` | `17` |
| `pause_frames_balanced` | `25` |
| `pause_frames_relaxed` | `38` |
| `calibration_noise_frames` | `94` |
| `calibration_max_noise_speech_fraction` | `0.1` |
| `calibration_timeout_s` | `30` |
| `calibration_max_wer` | `0.35` |
| `calibration_min_snr_db` | `10.0` |
| `calibration_max_clipping_pct` | `0.1` |
| `calibration_min_signal_dbfs` | `-55.0` |
| `calibration_vad_margin` | `0.1` |
| `calibration_vad_max` | `0.8` |
| `prompt_cache_entries` | `24` |
| `prompt_cache_max_bytes` | `8388608` |
| `analysis_max_frames` | `160` |
| `analysis_pitch_min_hz` | `60.0` |
| `analysis_pitch_max_hz` | `500.0` |
| `analysis_periodicity_min` | `0.8` |
| `analysis_frame_ms` | `40` |
| `analysis_min_rms` | `0.001` |
| `analysis_max_duration_s` | `30` |

## Format ve veri sınırlarının yetkili konumları

- Profil şeması `1`, isim en fazla `40` karakter, profil dosyası en fazla `8192` bayt: `jarvis/profile.py`.
- Profil enum'ları ve sesli tanışma durumları: `jarvis/profile.py`.
- Akustik gözlem sözleşmesi: `jarvis/contracts.py::AcousticObservation`; üretici şeması 1.
- Mikrofon kalibrasyonunun sabit referans cümlesi ve disk şeması 1: `jarvis/calibration.py`.
- Giriş PCM16 mono 16 kHz/512 örnek: protokol 2; frontend `capture-worklet.js` sabitleri bu sözleşmeyle birlikte değişmelidir.
- TTS çıkış hızı ses envelope'unda taşınır; EMA adaptörü 24 kHz.
- Browser oynatma sonrası mikrofon kuyruğu 350 ms: `jarvis/static/app.js::OUTPUT_TAIL_MS`.
- ASR revision/dosya listesi: `jarvis/asr.py`; EMA revision/boyut/SHA256: `jarvis/tts.py`; tokenizer URL/SHA256: `jarvis/context.py`.
- Hatıra şeması SQLite user_version 1: `jarvis/memory.py`.
- Akustik inceleme varsayılan kapalı ve oturumluk: `server.Session` / frontend checkbox.
- Güncelleme izin listesi ve dosya üst sınırı 16 MiB: `update_jarvis.py`.

## Yorumlama

`keep_alive` modelin boşta tutulma isteğidir; GPU yerleşim garantisi değildir. `asr_threads` ve `tts_threads` varsayılanları kullanıcının Windows işlemcisinde en iyi sonucu verdiği kanıtlanmış değerler değildir. Kalibrasyon eşikleri bir kısa kontrolün sezgileridir. F0 periyodiklik eşiği ve kapsaması duygu güven skoru değildir. Kullanıcı API anahtarı, ham ses ve ölçüm geçmişi bu parametre dosyalarına yazılmaz.

- Güncelleyicinin uygulama import etmeden kullandığı `UPDATER_PORT=8765`: `update_jarvis.py`; `Settings.port` ile uyumlu tutulmalıdır.
