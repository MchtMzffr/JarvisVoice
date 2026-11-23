"""Explicit online setup phase, executed separately from offline speech runtime."""
import json
import os
from datetime import datetime, timezone
from .config import DATA_ROOT, ASR_PATH, TTS_CACHE
from . import __version__


def main():
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(TTS_CACHE)
    os.environ["HF_HUB_CACHE"] = str(TTS_CACHE / "hub")
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    from .asr import prepare_asr
    from .tts import prepare_tts
    from .context import prepare_tokenizer
    progress = lambda text: print(text, flush=True)
    progress("Türkçe ses bileşenleri hazırlanıyor. İlk kurulum internet gerektirir.")
    prepare_asr(ASR_PATH, progress)
    prepare_tts(TTS_CACHE, progress)
    prepare_tokenizer(progress)
    marker = {"prepared_at": datetime.now(timezone.utc).isoformat(), "version": __version__, "asr": "faster-whisper-small", "tts": "ema-lightning-1.1.2", "runtime": "cpu"}
    temporary = DATA_ROOT / "prepared.tmp"
    temporary.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(DATA_ROOT / "downloaded.json")
    progress("Ses dosyaları hazır. Kurulumun model yükleme kontrolü yapılacak.")


if __name__ == "__main__":
    main()
