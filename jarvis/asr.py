"""Local CPU speech recognition and streaming voice activity detection.

Runtime contract: mono, 16,000 Hz, normalized floating-point PCM.  The VAD
consumes exactly 512 samples per call; each instance belongs to one audio stream.
Heavy imports happen only when their component is constructed or used.

Verified dependency candidates: faster-whisper==1.2.1, ctranslate2==4.9.1,
onnxruntime==1.32.0 (CPU package), av==16.1.0; all have Windows x64 / Python
3.11 wheels.  No torch, CUDA, cuDNN, or system FFmpeg installation is needed.

Sources checked 2026-11-23:
https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1
https://raw.githubusercontent.com/SYSTRAN/faster-whisper/v1.2.1/faster_whisper/vad.py
https://huggingface.co/Systran/faster-whisper-small/commit/536b0662742c02347bc0e980a01041f333bce120

The bundled V6 ONNX graph uses input/h/c, unlike upstream Silero's other
input/state/sr export.  Its wrapper must retain h, c and 64 context samples;
calling faster_whisper.vad.get_vad_model()(frame) would reset its recurrent
state on every call.  This module uses that bundled graph directly.

Small is the first CPU prototype's latency-oriented default.  Turbo can be
evaluated later on the user's hardware; no Turkish accuracy or latency claim
is implied by this choice.  VAD is neither acoustic echo cancellation nor an
absolute guarantee against transcription hallucinations.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import numpy as np


SAMPLE_RATE = 16_000
VAD_FRAME_SAMPLES = 512
ASR_MODEL_ID = "Systran/faster-whisper-small"
ASR_MODEL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"
ASR_MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


def _mono_audio(audio: np.ndarray) -> np.ndarray:
    """Validate normalized PCM without modifying the caller's array."""
    import numpy as np

    data = np.asarray(audio)
    if data.ndim != 1:
        raise ValueError("Ses tek kanallı, bir boyutlu PCM olmalı.")
    if not np.issubdtype(data.dtype, np.floating):
        raise ValueError("PCM float32/float64 olmalı; int16 ses önce 32768'e bölünmeli.")
    if not np.isfinite(data).all():
        raise ValueError("Ses verisi NaN veya sonsuz değer içeriyor.")
    if data.size and float(np.max(np.abs(data))) > 1.5:
        raise ValueError("PCM [-1, 1] aralığına normalize edilmeli.")
    # A resampler may slightly overshoot full scale; contain that overshoot.
    return np.ascontiguousarray(np.clip(data, -1.0, 1.0), dtype=np.float32)


class VoiceActivityDetector:
    """Silero V6 on CPU, retaining recurrent state between 32 ms frames."""

    def __init__(self) -> None:
        from importlib import resources

        import numpy as np
        import onnxruntime as ort

        self._np = np
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.log_severity_level = 3
        ort.disable_telemetry_events()
        asset = resources.files("faster_whisper.assets").joinpath("silero_vad_v6.onnx")
        self._session = ort.InferenceSession(
            asset.read_bytes(),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        inputs = {item.name: item for item in self._session.get_inputs()}
        if set(inputs) != {"input", "h", "c"}:
            raise RuntimeError("Silero VAD model sözleşmesi değişmiş; faster-whisper 1.2.1 gerekiyor.")
        for name, expected_shape in (
            ("input", (1, 576)), ("h", (1, 1, 128)), ("c", (1, 1, 128))
        ):
            item = inputs[name]
            if item.type != "tensor(float)" or len(item.shape) != len(expected_shape):
                raise RuntimeError(f"Silero VAD '{name}' girdisi beklenen biçimde değil.")
            if any(isinstance(got, int) and got != want for got, want in zip(item.shape, expected_shape)):
                raise RuntimeError(f"Silero VAD '{name}' boyutları beklenen biçimde değil.")
        self.reset()

    def reset(self) -> None:
        """Reset on a new stream or capture discontinuity, never per frame."""
        self._h = self._np.zeros((1, 1, 128), dtype=self._np.float32)
        self._c = self._np.zeros((1, 1, 128), dtype=self._np.float32)
        self._context = self._np.zeros((1, 64), dtype=self._np.float32)

    def probability(self, frame: np.ndarray) -> float:
        samples = _mono_audio(frame)
        if samples.size != VAD_FRAME_SAMPLES:
            raise ValueError("VAD her çağrıda 16 kHz hızında tam 512 örnek bekliyor.")
        window = self._np.empty((1, 576), dtype=self._np.float32)
        window[:, :64] = self._context
        window[0, 64:] = samples
        output, next_h, next_c = self._session.run(
            None, {"input": window, "h": self._h, "c": self._c}
        )
        probability = float(self._np.asarray(output).reshape(-1)[0])
        if (
            not math.isfinite(probability)
            or next_h.shape != (1, 1, 128)
            or next_c.shape != (1, 1, 128)
            or not self._np.isfinite(next_h).all()
            or not self._np.isfinite(next_c).all()
        ):
            self.reset()
            raise RuntimeError("Silero VAD geçersiz çıktı üretti; akış durumu sıfırlandı.")
        self._h, self._c = next_h, next_c
        self._context = samples[-64:].reshape(1, 64).copy()
        return min(1.0, max(0.0, probability))


def _validate_model_files(model_path: Path) -> None:
    for name in ASR_MODEL_FILES:
        path = model_path / name
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Ses tanıma modeli eksik: {name}. Önce kurulumu çalıştırın.")
    for name in ("config.json", "tokenizer.json"):
        with (model_path / name).open("r", encoding="utf-8") as handle:
            if not isinstance(json.load(handle), dict):
                raise ValueError(f"Ses tanıma modelinin {name} dosyası geçersiz.")


def prepare_asr(destination: Path, progress: Callable[[str], None]) -> Path:
    """Setup-only download of a fixed, multilingual model revision.

    Hugging Face's revision-addressed download/cache performs the transfer;
    runtime inference never calls this function or downloads missing weights.
    Only the four inference files are requested, not an entire model family.
    """
    from huggingface_hub import snapshot_download

    destination = Path(destination).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    progress("Türkçe ses tanıma modeli hazırlanıyor (ilk indirme yaklaşık 486 MB).")
    snapshot_download(
        repo_id=ASR_MODEL_ID,
        revision=ASR_MODEL_REVISION,
        local_dir=str(destination),
        allow_patterns=list(ASR_MODEL_FILES),
        max_workers=4,
    )
    _validate_model_files(destination)
    progress("Yerel ses tanıma modeli hazır.")
    return destination


class Transcriber:
    """Whisper small on CPU; complete utterances in, Turkish text out."""

    def __init__(self, model_path: str, cpu_threads: int = 6) -> None:
        from faster_whisper import WhisperModel

        if not isinstance(cpu_threads, int) or isinstance(cpu_threads, bool) or cpu_threads < 1:
            raise ValueError("cpu_threads pozitif bir tam sayı olmalı.")
        local_path = Path(model_path).expanduser().resolve()
        _validate_model_files(local_path)
        self._model = WhisperModel(
            str(local_path),
            device="cpu",
            compute_type="int8",
            cpu_threads=cpu_threads,
            num_workers=1,
            local_files_only=True,
        )
        self._lock = threading.Lock()

    def transcribe(self, audio: np.ndarray) -> str:
        import numpy as np

        samples = _mono_audio(audio)
        if samples.size < 1280:  # Less than 80 ms cannot form this prototype's turn.
            return ""
        peak = float(np.max(np.abs(samples)))
        rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
        if peak < 0.003 and rms < 0.0005:
            return ""
        with self._lock:
            segments, _ = self._model.transcribe(
                samples,
                language="tr",
                task="transcribe",
                beam_size=1,
                best_of=1,
                temperature=0.0,
                condition_on_previous_text=False,
                without_timestamps=True,
                word_timestamps=False,
                vad_filter=True,
                vad_parameters={
                    "threshold": 0.5,
                    "min_speech_duration_ms": 100,
                    "min_silence_duration_ms": 300,
                    "speech_pad_ms": 200,
                },
                no_speech_threshold=0.6,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4,
            )
            parts: list[str] = []
            # faster-whisper returns a lazy generator; consume it inside the
            # lock so a second request cannot interleave model execution.
            for segment in segments:
                no_speech = float(segment.no_speech_prob)
                log_prob = float(segment.avg_logprob)
                if not math.isfinite(no_speech) or not math.isfinite(log_prob):
                    continue
                if no_speech >= 0.6 and log_prob < -1.0:
                    continue
                if segment.compression_ratio > 2.4 and log_prob < -1.0:
                    continue
                text = segment.text.strip()
                if text:
                    parts.append(text)
            return " ".join(parts).strip()
