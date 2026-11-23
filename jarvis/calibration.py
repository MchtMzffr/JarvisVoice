"""Short local microphone check; raw PCM and recognized phrases stay in RAM.

This is a diagnostic heuristic, not a speech-recognition benchmark or model
training. dBFS describes the browser-processed digital signal, not acoustic SPL.
"""
from dataclasses import replace
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import unicodedata
import numpy as np
from .config import SETTINGS

REFERENCE_TEXT = "Bugün seninle sakin ve doğal bir şekilde konuşmak istiyorum."
NOISE_PROMPT = "Mikrofonunu birlikte kontrol edelim. Ben sustuktan sonra üç saniye sessiz kal. Sesin kaydedilmeyecek."
PHRASE_PROMPT = "Şimdi şu cümleyi söyle: " + REFERENCE_TEXT


def dbfs(rms):
    return round(20 * math.log10(max(float(rms), 1e-6)), 1)


def words(text):
    # Case and punctuation do not count as recognition errors. This intentionally
    # does not 'correct' actual different words to improve the displayed score.
    text = unicodedata.normalize("NFKC", text).replace("İ", "i").replace("I", "ı").lower()
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)?", text, flags=re.UNICODE)


def word_error_rate(reference, hypothesis):
    expected, actual = words(reference), words(hypothesis)
    if not expected:
        raise ValueError("Reference phrase cannot be empty")
    previous = list(range(len(actual) + 1))
    for i, left in enumerate(expected, 1):
        current = [i]
        for j, right in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j-1] + (left != right)))
        previous = current
    return round(previous[-1] / len(expected), 4)


class NoiseMeter:
    def __init__(self):
        self.frames = 0
        self.count = 0
        self.sum_squares = 0.0
        self.peak = 0.0
        self.clipped = 0
        self.probabilities = []

    def add(self, frame, probability):
        if self.done:
            return
        samples = np.asarray(frame, dtype=np.float32)
        if samples.shape != (SETTINGS.frame_samples,) or not np.isfinite(samples).all():
            raise ValueError("Invalid calibration audio")
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("Invalid calibration VAD probability")
        self.frames += 1
        self.count += samples.size
        self.sum_squares += float(np.dot(samples.astype(np.float64), samples.astype(np.float64)))
        self.peak = max(self.peak, float(np.max(np.abs(samples))))
        self.clipped += int(np.count_nonzero(np.abs(samples) >= 0.999))
        self.probabilities.append(float(probability))

    @property
    def done(self):
        return self.frames >= SETTINGS.calibration_noise_frames

    def result(self):
        if not self.done:
            raise ValueError("Noise sample is incomplete")
        return {
            "noise_dbfs": dbfs(math.sqrt(self.sum_squares / self.count)),
            "noise_peak_dbfs": dbfs(self.peak),
            "noise_clipping_pct": round(100 * self.clipped / self.count, 4),
            "noise_vad_peak": round(max(self.probabilities), 4),
            "noise_vad_p95": round(float(np.percentile(self.probabilities, 95)), 4),
            "noise_speech_fraction": round(sum(p >= SETTINGS.vad_threshold for p in self.probabilities) / self.frames, 4),
            "noise_seconds": round(self.count / SETTINGS.sample_rate, 3),
        }


def evaluate(noise, audio, recognized):
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all():
        raise ValueError("Invalid phrase sample")
    voiced_db = dbfs(float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))))
    clipped = int(np.count_nonzero(np.abs(samples) >= 0.999))
    clipping = 100 * clipped / samples.size
    wer = word_error_rate(REFERENCE_TEXT, recognized)
    snr = round(voiced_db - noise["noise_dbfs"], 1)
    threshold = round(min(SETTINGS.calibration_vad_max, max(
        SETTINGS.vad_threshold, noise["noise_vad_p95"] + SETTINGS.calibration_vad_margin
    )), 2)
    problems = []
    if noise["noise_speech_fraction"] > SETTINGS.calibration_max_noise_speech_fraction:
        problems.append("Sessizlik bölümünde konuşmaya benzeyen ses vardı; sessiz kısmı tekrarla.")
    if clipping > SETTINGS.calibration_max_clipping_pct or noise["noise_clipping_pct"] > SETTINGS.calibration_max_clipping_pct:
        problems.append("Seste kesilme var; mikrofon giriş seviyesini azaltıp yeniden dene.")
    if voiced_db < SETTINGS.calibration_min_signal_dbfs:
        problems.append("Mikrofon sesi çok zayıf; mikrofonu yaklaştırıp yeniden dene.")
    if snr < SETTINGS.calibration_min_snr_db:
        problems.append("Konuşman arka plandan yeterince ayrışmıyor; gürültüyü azaltıp yeniden dene.")
    if wer > SETTINGS.calibration_max_wer:
        problems.append("Örnek cümlede fazla kelime farkı var; ekrandaki cümleyi yeniden söyle.")
    measurements = {
        **noise, "reference_text": REFERENCE_TEXT, "phrase_text": recognized[:400],
        "word_error_rate": wer, "voiced_dbfs": voiced_db, "snr_db": snr,
        "clipping_pct": round(clipping, 4), "clipped_samples": clipped,
        "suggested_vad_threshold": threshold, "can_apply": not problems,
    }
    message = " ".join(problems) if problems else "Bu kısa kontrolde sesin yeterince belirgin. İstersen mikrofon ayarını uygula; normal sohbetle de deneyelim."
    return measurements, message


class CalibrationError(RuntimeError):
    pass


class CalibrationStore:
    """Only a bounded scalar threshold is persisted; audio/transcripts are not."""
    def __init__(self, path: Path):
        self.path = Path(path)

    def load_threshold(self):
        if not self.path.exists():
            return SETTINGS.vad_threshold
        try:
            if self.path.stat().st_size > 4096:
                raise ValueError("oversized")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            value = data["vad_threshold"]
            if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
                raise ValueError("schema")
            if type(value) not in (int, float) or not math.isfinite(value) or not SETTINGS.vad_threshold <= value <= SETTINGS.calibration_vad_max:
                raise ValueError("threshold")
            return float(value)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise CalibrationError("Mikrofon ayarı okunamadı. data/audio_calibration.json dosyasını yedekleyip kaldırarak varsayılana dönebilirsin.") from exc

    def save(self, result):
        if result.get("can_apply") is not True:
            raise CalibrationError("Önce başarılı bir mikrofon kontrolü yap.")
        value = result.get("suggested_vad_threshold")
        if type(value) not in (int, float) or not math.isfinite(value) or not SETTINGS.vad_threshold <= value <= SETTINGS.calibration_vad_max:
            raise CalibrationError("Mikrofon ayarı geçersiz.")
        self.load_threshold()  # Do not silently replace a future/corrupt schema.
        data = {"schema_version": 1, "vad_threshold": float(value), "saved_at": datetime.now(timezone.utc).isoformat()}
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix=".calibration-", suffix=".tmp", dir=self.path.parent)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            raise CalibrationError("Mikrofon ayarı kaydedilemedi; önceki ayar korundu.") from exc
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


def segment_settings(profile, vad_threshold):
    frames = {"quick": SETTINGS.pause_frames_quick, "balanced": SETTINGS.pause_frames_balanced, "relaxed": SETTINGS.pause_frames_relaxed}
    return replace(SETTINGS, end_silence_frames=frames[profile.pause], vad_threshold=vad_threshold)
