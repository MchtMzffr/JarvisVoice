"""Digital acoustic measurements on synthetic signals, not human affect data."""
from dataclasses import replace
import json
import math
import unittest
from unittest.mock import patch

import numpy as np

from jarvis import audio_analysis as analysis


def sine(frequency, seconds=1.0, amplitude=0.5):
    time = np.arange(round(analysis.SETTINGS.sample_rate * seconds)) / analysis.SETTINGS.sample_rate
    return (amplitude * np.sin(2 * np.pi * frequency * time)).astype(np.float32)


class AcousticAnalysisTests(unittest.TestCase):
    def test_sines_have_expected_digital_rms_and_pitch(self):
        expected_rms = 20 * math.log10(0.5 / math.sqrt(2))
        for frequency in (100, 220, 300):
            with self.subTest(frequency=frequency):
                result = analysis.analyze(sine(frequency))
                self.assertTrue(result.signal_valid)
                self.assertAlmostEqual(result.rms_dbfs, expected_rms, delta=0.005)
                self.assertAlmostEqual(result.peak_dbfs, 20 * math.log10(0.5), delta=0.005)
                self.assertAlmostEqual(result.f0_median_hz, frequency, delta=0.6)
                self.assertLessEqual(result.f0_iqr_hz, 0.6)
                self.assertGreater(result.f0_coverage, 0.95)
                self.assertEqual(result.clipping_pct, 0)

    def test_silence_does_not_invent_pitch_speed_or_affect(self):
        result = analysis.analyze(np.zeros(16000, np.float32), "ASR böyle bir cümle uydurmuş olabilir")
        self.assertFalse(result.signal_valid)
        self.assertIsNone(result.f0_median_hz)
        self.assertIsNone(result.f0_iqr_hz)
        self.assertIsNone(result.f0_coverage)
        self.assertIsNone(result.words_per_minute)
        self.assertEqual(result.rms_dbfs, -120.0)
        self.assertEqual(result.peak_dbfs, -120.0)
        data = result.to_dict()
        for prohibited in ("emotion", "gender", "diagnosis", "speaker_identity", "confidence", "audio", "transcript"):
            self.assertNotIn(prohibited, data)
        json.dumps(data, allow_nan=False)

    def test_deterministic_noise_has_unknown_pitch(self):
        noise = np.random.default_rng(21).normal(0, 0.05, 32000).astype(np.float32)
        result = analysis.analyze(noise)
        self.assertTrue(result.signal_valid)
        self.assertIsNone(result.f0_median_hz)
        self.assertIsNone(result.f0_iqr_hz)
        self.assertEqual(result.f0_coverage, 0.0)

    def test_words_per_minute_uses_asr_words_and_full_duration(self):
        result = analysis.analyze(sine(220, seconds=2), "Bugün seninle doğal konuşmak istiyorum.", speech_fraction=0.75)
        self.assertEqual(result.words_per_minute, 150.0)
        self.assertEqual(result.duration_s, 2.0)
        self.assertEqual(result.speech_fraction, 0.75)
        self.assertEqual(result.pause_fraction, 0.25)
        self.assertAlmostEqual(result.speech_fraction + result.pause_fraction, 1.0)
        no_vad_speech = analysis.analyze(sine(220), "bir iki", speech_fraction=0)
        self.assertIsNone(no_vad_speech.words_per_minute)

    def test_short_or_constant_signal_has_no_invented_pitch(self):
        for signal in (sine(220, seconds=0.01), np.full(16000, 0.1, np.float32)):
            with self.subTest(length=signal.size):
                result = analysis.analyze(signal, "bir iki")
                self.assertFalse(result.signal_valid)
                self.assertIsNone(result.f0_median_hz)
                self.assertIsNone(result.words_per_minute)

    def test_digital_full_scale_percentage_is_measured(self):
        signal = np.tile(np.array([-1.0, 1.0, 0.0, 0.0], np.float32), 4000)
        result = analysis.analyze(signal)
        self.assertEqual(result.clipping_pct, 50.0)
        self.assertEqual(result.peak_dbfs, 0.0)

    def test_input_and_capture_are_not_mutated(self):
        original = sine(220)
        saved = original.copy()
        original.flags.writeable = False
        capture = {"sample_rate": 48000, "echo_cancellation": True, "deviceId": "private identifier"}
        result = analysis.analyze(original, capture=capture)
        np.testing.assert_array_equal(original, saved)
        self.assertEqual(capture["deviceId"], "private identifier")
        self.assertIsNot(result.capture, capture)
        self.assertNotIn("deviceId", result.capture)

    def test_capture_allowlist_drops_identifiers_strings_and_invalid_values(self):
        result = analysis.analyze(sine(100), capture={
            "sample_rate": 48000, "channel_count": 1,
            "echo_cancellation": True, "noise_suppression": False, "auto_gain_control": True,
            "deviceId": "private", "groupId": "private", "label": "private",
            "extra": {"private": "value"},
        })
        self.assertEqual(result.capture, {
            "sample_rate": 48000, "channel_count": 1,
            "echo_cancellation": True, "noise_suppression": False, "auto_gain_control": True,
        })
        self.assertEqual(analysis.sanitize_capture({
            "sample_rate": True, "channel_count": -1, "sampleSize": "private",
            "latency": float("nan"), "echo_cancellation": "private",
        }), {"sample_rate": None, "channel_count": None, "echo_cancellation": None,
             "noise_suppression": None, "auto_gain_control": None})

    def test_invalid_audio_shape_range_and_nonfinite_values_are_rejected(self):
        values = [np.array([], np.float32), np.zeros((3, 2), np.float32), np.zeros(100, np.int16),
                  np.array([0.0, np.nan], np.float32), np.array([0.0, np.inf], np.float32),
                  np.array([1.1], np.float32), [0.0, 0.1]]
        for invalid in values:
            with self.subTest(value=repr(invalid)[:50]):
                with self.assertRaises(ValueError):
                    analysis.analyze(invalid)
        for fraction in (True, -0.1, 1.1, float("nan"), "0.5"):
            with self.subTest(fraction=fraction):
                with self.assertRaises(ValueError):
                    analysis.analyze(sine(220), speech_fraction=fraction)

    def test_duration_and_analysis_work_are_bounded(self):
        rate = analysis.SETTINGS.sample_rate
        maximum = analysis.SETTINGS.analysis_max_duration_s
        with self.assertRaises(ValueError):
            analysis.analyze(np.zeros(int(rate * maximum) + 1, np.float32))
        real_pitch = analysis._frame_pitch
        with patch.object(analysis, "_frame_pitch", wraps=real_pitch) as measured:
            result = analysis.analyze(sine(220, seconds=maximum))
        self.assertEqual(measured.call_count, analysis.SETTINGS.analysis_max_frames)
        self.assertAlmostEqual(result.f0_median_hz, 220.0, delta=0.6)
        self.assertGreaterEqual(result.analysis_ms, 0)
        self.assertTrue(math.isfinite(result.analysis_ms))


if __name__ == "__main__":
    unittest.main()
