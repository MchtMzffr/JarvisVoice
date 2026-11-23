"""Installer smoke check: real speech adapters, no microphone or external API."""
import os
import json
from datetime import datetime, timezone
from .config import ASR_PATH, TTS_CACHE, SETTINGS, DATA_ROOT
from . import __version__


def main():
    os.environ["HF_HOME"] = str(TTS_CACHE)
    os.environ["HF_HUB_CACHE"] = str(TTS_CACHE / "hub")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    from .asr import VoiceActivityDetector, Transcriber
    from .tts import Speaker
    from .context import encoder
    import numpy as np
    print("Yerel baglam sayaci kontrol ediliyor...", flush=True)
    encoder()
    print("Ses algilayici ve Turkce tanima modeli aciliyor...", flush=True)
    vad = VoiceActivityDetector()
    assert vad.probability(np.zeros(512, np.float32)) < 0.5
    transcriber = Transcriber(str(ASR_PATH), SETTINGS.asr_threads)
    assert transcriber.transcribe(np.zeros(16000, np.float32)) == ""
    print("Turkce ses modeli aciliyor...", flush=True)
    speaker = Speaker(TTS_CACHE, SETTINGS.tts_threads)
    samples, rate = speaker.synthesize("Merhaba, konuşmaya hazırım.")
    assert samples.ndim == 1 and samples.size > rate // 4 and rate == 24000
    temporary = DATA_ROOT / "verified.tmp"
    temporary.write_text(json.dumps({"version": __version__, "verified_at": datetime.now(timezone.utc).isoformat(), "speech_device": "cpu", "ort_telemetry_disabled": os.environ.get("ORT_DISABLE_TELEMETRY") == "1"}, indent=2), encoding="utf-8")
    temporary.replace(DATA_ROOT / "prepared.json")
    print("Ses bilesenlerinin kurulum kontrolu tamamlandi.", flush=True)


if __name__ == "__main__":
    main()
