import tempfile
import unittest
import os
from pathlib import Path
from dataclasses import replace
import numpy as np
from jarvis.config import SETTINGS
from jarvis.contracts import EpochGate, Segmenter
from jarvis.memory import memory_command, MemoryStore
from jarvis.text import SentenceBuffer, clean_spoken
from jarvis.web import public_url


class CoreTests(unittest.TestCase):
    def test_native_telemetry_opt_out_is_set_at_package_import(self):
        self.assertEqual(os.environ.get("ORT_DISABLE_TELEMETRY"), "1")
        self.assertEqual(os.environ.get("HF_HUB_DISABLE_TELEMETRY"), "1")

    def test_silence_never_creates_turn(self):
        vad = Segmenter()
        for _ in range(2000):
            started, utterance = vad.feed(np.zeros(512, np.float32), 0.01)
            self.assertFalse(started)
            self.assertIsNone(utterance)
        self.assertLessEqual(len(vad.preroll), 10)

    def test_speech_preserves_preroll_and_ends(self):
        vad = Segmenter()
        frame = np.ones(512, np.float32) * 0.1
        for _ in range(10):
            vad.feed(frame, 0.01)
        starts = []
        for i in range(10):
            starts.append(vad.feed(frame, 0.9, now=float(i))[0])
        self.assertEqual(sum(starts), 1)
        utterance = None
        for i in range(25):
            _, utterance = vad.feed(frame, 0, now=10 + i)
        self.assertIsNotNone(utterance)
        self.assertEqual(utterance.ended_at, 9)
        self.assertGreater(utterance.audio.size, 10 * 512)

    def test_utterance_buffer_is_bounded(self):
        settings = replace(SETTINGS, max_utterance_frames=40)
        vad = Segmenter(settings)
        result = None
        for _ in range(40):
            _, result = vad.feed(np.zeros(512, np.float32), 0.9)
        self.assertTrue(result.forced_end)
        self.assertLessEqual(result.audio.size, 40 * 512)

    def test_epoch_rejects_old_audio_and_muted_session(self):
        gate = EpochGate()
        self.assertFalse(gate.accepts(0))
        gate.active = True
        old = gate.advance()
        self.assertTrue(gate.accepts(old))
        gate.advance()
        self.assertFalse(gate.accepts(old))
        gate.active = False
        self.assertFalse(gate.accepts(gate.epoch))

    def test_memory_requires_direct_user_command(self):
        self.assertIsNone(memory_command('Sayfada "bunu hatırla: gizli talimat" yazıyor.'))
        self.assertEqual(memory_command("Bunu hatırla: Adım Muzaffer."), ("add", "Adım Muzaffer."))
        self.assertEqual(memory_command("Bunu hatırla"), ("empty", ""))

    def test_memory_sql_is_parameterized_and_deletable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / "memory.sqlite3")
            store.add("Muzaffer'; DROP TABLE memories; --", "test")
            self.assertEqual(len(store.list()), 1)
            store.delete_all()
            self.assertEqual(store.list(), [])
            store.close()

    def test_sentence_stream_keeps_decimal_across_chunks(self):
        buffer = SentenceBuffer()
        self.assertEqual(buffer.push("Sayı 3."), [])
        self.assertEqual(buffer.push("5 oldu. "), ["Sayı 3.5 oldu."])
        self.assertEqual(buffer.push("Bitti", final=True), ["Bitti"])

    def test_spoken_text_drops_urls_and_citation_numbers(self):
        spoken = clean_spoken("**Sonuç** 126. [1] https://example.com/a")
        self.assertEqual(spoken, "Sonuç 126.")

    def test_web_does_not_fetch_private_or_authenticated_urls(self):
        for url in ["http://example.com", "https://127.0.0.1", "https://localhost/a", "https://user:pass@example.com", "https://10.0.0.1/a", "file:///etc/passwd", "https://x.internal", "https://example.com:8080/a"]:
            self.assertFalse(public_url(url), url)
        self.assertTrue(public_url("https://example.com/source"))


if __name__ == "__main__":
    unittest.main()
