"""Bounded digital acoustic observations, without affect or identity inference.

Input is the browser-processed, resampled 16 kHz mono waveform. RMS/peak dBFS
are digital levels, never physical SPL. F0 uses normalized autocorrelation on
at most Settings.analysis_max_frames short frames; it is not a validated
speech-emotion model, a voice biometric, or a clinical assessment. No audio,
transcript, identifier, or observation is saved or logged by this module.
"""
from __future__ import annotations

import math
import re
import time
import numpy as np

from .config import SETTINGS
from .contracts import AcousticObservation


def sanitize_capture(capture: dict | None) -> dict:
    """Copy the protocol's numeric/boolean getSettings() allowlist.

    Browser identifiers, labels, arbitrary strings and nested objects are not
    retained. These settings describe capture before this app's resampling.
    """
    if capture is None:
        capture = {}
    if not isinstance(capture, dict):
        raise ValueError("Capture settings must be an object")
    clean = {}
    for key in ("echo_cancellation", "noise_suppression", "auto_gain_control"):
        value = capture.get(key)
        clean[key] = value if type(value) is bool else None
    for key, low, high in (
        ("sample_rate", 8_000, 384_000),
        ("channel_count", 1, 8),
    ):
        value = capture.get(key)
        clean[key] = value if type(value) is int and low <= value <= high else None
    return clean


def _dbfs(value: float) -> float:
    # A finite -120 dBFS display floor avoids infinities in protocol JSON.
    return round(20.0 * math.log10(max(value, 1e-6)), 3)


def _frame_pitch(frame: np.ndarray, lag_min: int, lag_max: int) -> float | None:
    centered = frame - float(np.mean(frame))
    energy = float(np.dot(centered, centered))
    if energy / centered.size < SETTINGS.analysis_min_rms ** 2:
        return None
    # For each lag k, r[k] = dot(x[:-k], x[k:]) /
    # sqrt(sum(x[:-k]^2) * sum(x[k:]^2)). Both overlap energies are explicit;
    # this avoids treating decreasing overlap as lower periodicity by itself.
    correlations = np.correlate(centered, centered, mode="full")[centered.size - 1:]
    squares = np.concatenate(([0.0], np.cumsum(centered * centered)))
    lags = np.arange(lag_min - 1, lag_max + 2)
    left = squares[centered.size - lags]
    right = squares[-1] - squares[lags]
    denominator = np.sqrt(np.maximum(left * right, 0.0))
    scores = np.divide(correlations[lags], denominator, out=np.zeros(lags.size), where=denominator > 1e-18)
    # The first sufficiently periodic local maximum is used, not the global
    # maximum at 2x/3x period. Harmonic/octave ambiguity still exists in speech.
    candidates = np.flatnonzero(
        (scores[1:-1] >= SETTINGS.analysis_periodicity_min)
        & (scores[1:-1] >= scores[:-2])
        & (scores[1:-1] > scores[2:])
    ) + 1
    for index in candidates:
        lag = float(lags[index])
        a, b, c = scores[index - 1:index + 2]
        curvature = float(a - 2 * b + c)
        if abs(curvature) > 1e-12:
            lag += float(np.clip(0.5 * (a - c) / curvature, -0.5, 0.5))
        frequency = SETTINGS.sample_rate / lag
        if (SETTINGS.analysis_pitch_min_hz * (1 - 1e-6) <= frequency
                <= SETTINGS.analysis_pitch_max_hz * (1 + 1e-6)):
            return float(np.clip(frequency, SETTINGS.analysis_pitch_min_hz, SETTINGS.analysis_pitch_max_hz))
    return None


def analyze(audio: np.ndarray, text: str = "", speech_fraction: float | None = None,
            capture: dict | None = None) -> AcousticObservation:
    """Measure a bounded waveform without changing or retaining the input.

    ``signal_valid`` means there is enough varying digital signal to analyze;
    it does not assert that a human spoke. ``f0_coverage`` is the fraction of
    examined frames with a periodic candidate, not a calibrated probability.
    Words/minute uses the supplied ASR text divided by the entire utterance
    duration (including its pauses); it is not articulation rate.
    """
    began = time.perf_counter()
    if not isinstance(audio, np.ndarray) or audio.ndim != 1 or audio.dtype.kind != "f" or not audio.size:
        raise ValueError("Audio must be a non-empty mono normalized float array")
    if audio.size > int(SETTINGS.sample_rate * SETTINGS.analysis_max_duration_s):
        raise ValueError("Audio exceeds the analysis duration limit")
    if not np.isfinite(audio).all() or np.any(np.abs(audio) > 1.0):
        raise ValueError("Audio contains nonfinite or non-normalized samples")
    if not isinstance(text, str) or len(text) > SETTINGS.max_text_chars:
        raise ValueError("ASR text exceeds the analysis input contract")
    if speech_fraction is not None:
        if (type(speech_fraction) not in (int, float) or not math.isfinite(speech_fraction)
                or not 0 <= speech_fraction <= 1):
            raise ValueError("Speech fraction must be in [0, 1]")
        speech_fraction = round(float(speech_fraction), 6)
    clean_capture = sanitize_capture(capture)

    frame_size = int(round(SETTINGS.sample_rate * SETTINGS.analysis_frame_ms / 1000))
    lag_min = int(math.floor(SETTINGS.sample_rate / SETTINGS.analysis_pitch_max_hz))
    lag_max = int(math.ceil(SETTINGS.sample_rate / SETTINGS.analysis_pitch_min_hz))
    if (frame_size < 4 or lag_min < 2 or lag_max + 1 >= frame_size
            or lag_min >= lag_max or SETTINGS.analysis_max_frames < 1
            or not 0 < SETTINGS.analysis_periodicity_min <= 1):
        raise ValueError("Invalid acoustic analysis settings")

    # No operation writes through the caller's array, including read-only views.
    samples = audio.astype(np.float64, copy=False)
    power = float(np.mean(samples * samples))
    rms = math.sqrt(power)
    peak = float(np.max(np.abs(samples)))
    ac_rms = math.sqrt(max(0.0, power - float(np.mean(samples)) ** 2))
    duration = samples.size / SETTINGS.sample_rate
    signal_valid = samples.size >= frame_size and ac_rms >= SETTINGS.analysis_min_rms
    clipping = 100.0 * int(np.count_nonzero(np.abs(samples) >= 0.999)) / samples.size
    pause_fraction = None if speech_fraction is None else round(1.0 - speech_fraction, 6)

    words = re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text, flags=re.UNICODE)
    words_per_minute = None
    if signal_valid and words and speech_fraction != 0.0:
        words_per_minute = round(60.0 * len(words) / duration, 2)

    pitches = []
    coverage = None
    if signal_valid:
        # Start with 50% overlap, then uniformly subsample the candidate frame
        # positions if necessary. Work is bounded independently of clip length.
        positions = np.arange(0, samples.size - frame_size + 1, max(1, frame_size // 2))
        if positions.size > SETTINGS.analysis_max_frames:
            indices = np.linspace(0, positions.size - 1, SETTINGS.analysis_max_frames, dtype=np.int64)
            positions = positions[indices]
        for start in positions:
            pitch = _frame_pitch(samples[start:start + frame_size], lag_min, lag_max)
            if pitch is not None:
                pitches.append(pitch)
        coverage = round(len(pitches) / positions.size, 4) if positions.size else None

    median = round(float(np.median(pitches)), 2) if pitches else None
    iqr = round(float(np.percentile(pitches, 75) - np.percentile(pitches, 25)), 2) if pitches else None
    limitations = [
        "dBFS dijital sinyal düzeyidir; fiziksel ses basıncı (SPL) veya gerçek ses yüksekliği değildir.",
        "Mikrofon, mesafe ve tarayıcının kazanç/yankı/gürültü işlemleri ölçümleri etkiler.",
        "F0, sınırlı sayıda kısa kareden hesaplanan yaklaşık periyodiklik ölçümüdür; harmonik ve oktav hataları olabilir.",
        "F0 kapsaması örneklenen karelerin oranıdır; güven olasılığı veya konuşma doğrulaması değildir.",
        "Duygu, kişilik, cinsiyet, kimlik veya sağlık değerlendirmesi yapılmaz.",
        "Clipping oranı tam ölçeğe çok yakın dijital örnekleri sayar; donanımda kırpılmayı tek başına kanıtlamaz.",
    ]
    if words_per_minute is not None:
        limitations.append("Kelime hızı ASR metni ve duraklamaları içeren süreyle hesaplanır; tanıma hataları sonucu değiştirir.")
    if speech_fraction is not None:
        limitations.append("Konuşma/duraklama oranı çağıranın VAD ölçümüdür; bu modül yeniden konuşma sınıflandırması yapmaz.")
    if not signal_valid:
        limitations.append("Sinyal çok kısa, sessiz veya çok zayıf; F0 ve kelime hızı bilinmiyor.")
    elif not pitches:
        limitations.append("Yeterli periyodiklik gösteren kare bulunamadı; F0 bilinmiyor.")

    return AcousticObservation(
        schema_version=1, duration_s=round(duration, 6), rms_dbfs=_dbfs(rms), peak_dbfs=_dbfs(peak),
        clipping_pct=round(clipping, 4), speech_fraction=speech_fraction, pause_fraction=pause_fraction,
        words_per_minute=words_per_minute, f0_median_hz=median, f0_iqr_hz=iqr, f0_coverage=coverage,
        analysis_ms=round((time.perf_counter() - began) * 1000, 3), signal_valid=bool(signal_valid),
        limitations=limitations, capture=clean_capture,
    )
