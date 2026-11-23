"""Voice protocol v2. Epoch ownership belongs exclusively to the server."""
from dataclasses import dataclass, asdict
from collections import deque
from typing import Any
import time
import numpy as np
from .config import SETTINGS, Settings


@dataclass(frozen=True)
class Utterance:
    audio: np.ndarray
    ended_at: float
    forced_end: bool = False
    speech_fraction: float | None = None


@dataclass(frozen=True)
class AcousticObservation:
    """Measured signal features only. No affect, identity or diagnosis field."""
    schema_version: int
    duration_s: float
    rms_dbfs: float
    peak_dbfs: float
    clipping_pct: float
    speech_fraction: float | None
    pause_fraction: float | None
    words_per_minute: float | None
    f0_median_hz: float | None
    f0_iqr_hz: float | None
    f0_coverage: float | None
    analysis_ms: float
    signal_valid: bool
    limitations: list[str]
    capture: dict

    def to_dict(self):
        return asdict(self)


class Segmenter:
    """Bounded VAD segmenter; probabilities are supplied by the VAD adapter."""
    def __init__(self, settings: Settings = SETTINGS):
        self.s = settings
        self.reset()

    def reset(self):
        self.preroll = deque(maxlen=self.s.preroll_frames)
        self.frames = []
        self.active = False
        self.onset = self.speech_frames = self.silence = 0
        self.last_voice = 0.0

    def feed(self, frame: np.ndarray, probability: float, now: float | None = None):
        if frame.shape != (self.s.frame_samples,):
            raise ValueError("Invalid audio frame size")
        now = time.perf_counter() if now is None else now
        spoken = probability >= self.s.vad_threshold
        started = False
        if not self.active:
            self.preroll.append(frame.copy())
            self.onset = self.onset + 1 if spoken else 0
            if self.onset < self.s.onset_frames:
                return False, None
            self.active = started = True
            self.frames = list(self.preroll)
            self.speech_frames = self.onset
            self.last_voice = now
        else:
            self.frames.append(frame.copy())
            self.speech_frames += int(spoken)
        if spoken:
            self.last_voice, self.silence = now, 0
        else:
            self.silence += 1
        forced = len(self.frames) >= self.s.max_utterance_frames
        if self.silence < self.s.end_silence_frames and not forced:
            return started, None
        result = None
        if self.speech_frames >= self.s.min_speech_frames:
            # Keep a small speech tail, not the entire endpoint silence.
            trim = max(0, self.silence - 5)
            frames = self.frames[:-trim] if trim else self.frames
            result = Utterance(np.concatenate(frames).astype(np.float32), self.last_voice, forced,
                               min(1.0, self.speech_frames / len(frames)))
        self.reset()
        return started, result


class EpochGate:
    def __init__(self):
        self.epoch = 0
        self.active = False

    def advance(self) -> int:
        self.epoch += 1
        return self.epoch

    def accepts(self, epoch: int) -> bool:
        return self.active and epoch == self.epoch


def event(kind: str, **data: Any) -> dict:
    return {"type": kind, **data}
