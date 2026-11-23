import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from jarvis.calibration import NoiseMeter, evaluate, REFERENCE_TEXT, word_error_rate, CalibrationStore, CalibrationError, segment_settings
from jarvis.config import SETTINGS
from jarvis.profile import Profile


def noise(level=0.002, probability=0.02):
    meter = NoiseMeter()
    for _ in range(SETTINGS.calibration_noise_frames):
        meter.add(np.full(512, level, np.float32), probability)
    return meter.result()


class CalibrationTests(unittest.TestCase):
    def test_noise_window_is_bounded_and_does_not_retain_raw_samples(self):
        meter = NoiseMeter()
        frame = np.full(512, 0.01, np.float32)
        for _ in range(1000):
            meter.add(frame, 0.1)
        self.assertEqual(meter.frames, 94)
        self.assertEqual(meter.result()["noise_seconds"], 3.008)
        self.assertEqual(meter.result()["noise_dbfs"], -40)
        self.assertFalse(any(isinstance(value, np.ndarray) for value in vars(meter).values()))

    def test_word_errors_ignore_case_and_punctuation_but_count_real_words(self):
        self.assertEqual(word_error_rate("Işık İyi.", "ışık iyi"), 0)
        self.assertEqual(word_error_rate("bir iki üç", "bir dört üç"), 0.3333)
        self.assertEqual(word_error_rate("bir iki üç", ""), 1)
        self.assertEqual(word_error_rate("bir", "bir iki üç"), 2)

    def test_clear_phrase_can_offer_a_bounded_setting(self):
        result, _ = evaluate(noise(), np.full(16000, 0.08, np.float32), REFERENCE_TEXT)
        self.assertTrue(result["can_apply"])
        self.assertEqual(result["word_error_rate"], 0)
        self.assertGreater(result["snr_db"], 10)
        self.assertGreaterEqual(result["suggested_vad_threshold"], SETTINGS.vad_threshold)
        self.assertLessEqual(result["suggested_vad_threshold"], SETTINGS.calibration_vad_max)

    def test_silence_wrong_phrase_clipping_and_contaminated_noise_are_rejected(self):
        cases = [
            (noise(), np.zeros(16000, np.float32), ""),
            (noise(), np.full(16000, 0.08, np.float32), "başka bir konu"),
            (noise(), np.ones(16000, np.float32), REFERENCE_TEXT),
            (noise(probability=0.95), np.full(16000, 0.08, np.float32), REFERENCE_TEXT),
            (noise(level=0.04), np.full(16000, 0.05, np.float32), REFERENCE_TEXT),
        ]
        for baseline, sample, text in cases:
            with self.subTest(text=text):
                result, message = evaluate(baseline, sample, text)
                self.assertFalse(result["can_apply"])
                self.assertTrue(message)

    def test_only_scalar_confirmed_setting_is_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "audio_calibration.json"
            store = CalibrationStore(file)
            self.assertEqual(store.load_threshold(), SETTINGS.vad_threshold)
            with self.assertRaises(CalibrationError):
                store.save({"can_apply": False, "suggested_vad_threshold": 0.7})
            self.assertFalse(file.exists())
            result, _ = evaluate(noise(), np.full(16000, 0.08, np.float32), REFERENCE_TEXT)
            store.save(result)
            content = file.read_text(encoding="utf-8")
            self.assertNotIn(REFERENCE_TEXT, content)
            self.assertNotIn("phrase_text", content)
            self.assertEqual(store.load_threshold(), result["suggested_vad_threshold"])
            file.write_text(json.dumps({"schema_version": 99, "vad_threshold": 0.7}))
            original = file.read_bytes()
            with self.assertRaises(CalibrationError):
                store.save(result)
            self.assertEqual(file.read_bytes(), original)

    def test_pause_preferences_change_only_endpoint_frames(self):
        for pause, expected in [("quick", 17), ("balanced", 25), ("relaxed", 38)]:
            settings = segment_settings(Profile(pause=pause), 0.7)
            self.assertEqual(settings.end_silence_frames, expected)
            self.assertEqual(settings.vad_threshold, 0.7)
            self.assertEqual(settings.sample_rate, 16000)
            self.assertEqual(settings.max_utterance_frames, SETTINGS.max_utterance_frames)


if __name__ == "__main__":
    unittest.main()
