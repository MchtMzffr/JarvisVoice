"""Guided voice integration regressions: no real models, microphone or network."""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from jarvis import server
from jarvis.calibration import REFERENCE_TEXT
from jarvis.profile import Profile


class Socket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


class ImmediateCPU:
    async def call(self, function, *args):
        return function(*args)

    def close(self):
        pass


class EnergyVAD:
    def __init__(self):
        self.calls = 0

    def probability(self, frame):
        self.calls += 1
        return 0.95 if np.max(np.abs(frame)) > 0.02 else 0.02

    def reset(self):
        pass


class Transcriber:
    def __init__(self):
        self.text = ""
        self.calls = 0

    def transcribe(self, audio):
        self.calls += 1
        return self.text


async def ordinary_answer(*args, **kwargs):
    yield "Bu test yanıtı."


async def forbidden_answer(*args, **kwargs):
    raise AssertionError("Guided introduction/calibration called the LLM")
    yield ""  # async generator contract


class GuidedRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.data_override = patch.object(server, "DATA_ROOT", self.root)
        self.data_override.start()
        self.runtime = server.Runtime(demo=True)
        await self.runtime.initialize()
        # Keep actual runtime/session code, replacing only CPU adapters so
        # receive_audio exercises VAD/segmenting instead of the demo shortcut.
        self.runtime.demo = False
        self.runtime.asr_cpu.close()
        self.runtime.tts_cpu.close()
        self.runtime.asr_cpu = ImmediateCPU()
        self.runtime.tts_cpu = ImmediateCPU()
        self.runtime.transcriber = Transcriber()
        self.runtime.speaker = SimpleNamespace(synthesize=lambda text: (np.zeros(64, np.float32), 24000))
        self.runtime.vad_factory = EnergyVAD
        self.socket = Socket()
        self.session = server.Session(self.socket, self.runtime)
        self.runtime.session = self.session
        self.llm_override = patch.object(server.llm, "answer", new=forbidden_answer)
        self.llm_override.start()
        self.noise = np.full(512, 30, dtype="<i2").tobytes()
        self.speech = np.full(512, 3000, dtype="<i2").tobytes()
        self.silence = bytes(1024)

    async def asyncTearDown(self):
        await self.session.close()
        self.runtime.asr_cpu.close()
        self.runtime.tts_cpu.close()
        self.llm_override.stop()
        self.data_override.stop()
        self.directory.cleanup()

    async def until(self, condition):
        async def wait():
            while not condition():
                await asyncio.sleep(0)
        await asyncio.wait_for(wait(), 1)

    async def drain_audio(self, job=None):
        job = job or self.session.job
        async def play_all():
            while True:
                for segment_id in list(self.session.pending):
                    await self.session.control({"type": "played", "epoch": self.session.gate.epoch, "segment_id": segment_id})
                await asyncio.sleep(0)
                if (job is None or job.done()) and not self.session.pending:
                    if job is not None:
                        await job
                    return
        await asyncio.wait_for(play_all(), 1)

    def assert_ack(self, request_id):
        self.assertTrue(any(message["type"] == "epoch" and message.get("request_id") == request_id for message in self.socket.messages))

    async def say(self, text):
        self.runtime.transcriber.text = text
        for _ in range(12):
            await self.session.receive_audio(self.speech)
        for _ in range(self.session.segmenter.s.end_silence_frames):
            await self.session.receive_audio(self.silence)
        await self.drain_audio()

    async def get_to_phrase(self):
        await self.session.control({"type": "calibration_start", "request_id": "cal-start"})
        await self.drain_audio()
        self.assertEqual(self.session.calibration["stage"], "noise")
        for _ in range(94):
            await self.session.receive_audio(self.noise)
        await self.drain_audio()
        self.assertEqual(self.session.calibration["stage"], "phrase")

    async def test_first_start_runs_spoken_introduction_without_llm_or_writes(self):
        await self.session.control({"type": "start", "request_id": "first-start"})
        await self.drain_audio()
        self.assert_ack("first-start")
        self.assertTrue(self.session.onboarding.active)
        self.assertEqual(self.session.onboarding.stage, "user_name")
        self.assertTrue(any(message["type"] == "audio" and "tanışalım" in message["text"] for message in self.socket.messages))
        self.assertFalse((self.root / "profile.json").exists())
        self.assertFalse(self.session.history)
        self.assertFalse(any(message["type"] == "error" for message in self.socket.messages))

    async def test_mixed_voice_and_text_intro_saves_only_on_final_confirmation(self):
        await self.session.control({"type": "start", "request_id": "start"})
        await self.drain_audio()
        answers = ["Adım Muzaffer.", "Sana Atlas diyeyim.", "Samimi konuş.", "Kısa olsun.", "Rahat olsun.", "Kulaklıkla."]
        for index, answer in enumerate(answers):
            if index % 2:
                await self.say(answer)
            else:
                await self.session.control({"type": "text", "text": answer, "request_id": f"answer-{index}"})
                await self.drain_audio()
            self.assertFalse((self.root / "profile.json").exists(), answer)
        self.assertEqual(self.session.onboarding.stage, "confirmation")
        await self.say("Evet kaydet.")
        saved = self.runtime.profile_store.load()
        self.assertTrue(saved.onboarding_complete)
        self.assertEqual(saved.user_name, "Muzaffer")
        self.assertEqual(saved.assistant_name, "Atlas")
        self.assertEqual(saved.output, "headphones")
        self.assertEqual(saved.pause, "relaxed")
        self.assertEqual(self.session.segmenter.s.end_silence_frames, 38)
        self.assertFalse(self.session.onboarding.active)
        self.assertFalse(self.session.history)
        self.assertFalse(any(message["type"] == "error" for message in self.socket.messages))

    async def test_stop_then_cancel_introduction_preserves_saved_profile(self):
        previous = Profile(user_name="Ayşe", assistant_name="Dost", onboarding_complete=True)
        self.runtime.profile_store.save(previous)
        self.session.use_profile(previous)
        before = (self.root / "profile.json").read_bytes()
        await self.session.control({"type": "onboarding_start", "request_id": "redo"})
        await self.drain_audio()
        await self.session.control({"type": "text", "text": "Mehmet", "request_id": "draft"})
        await self.drain_audio()
        await self.session.control({"type": "stop", "request_id": "stop-intro"})
        self.assert_ack("stop-intro")
        self.assertFalse(self.session.gate.active)
        self.assertEqual((self.root / "profile.json").read_bytes(), before)
        await self.session.control({"type": "onboarding_cancel", "request_id": "cancel-intro"})
        self.assert_ack("cancel-intro")
        self.assertFalse(self.session.onboarding.active)
        self.assertEqual(self.session.profile, previous)
        self.assertEqual((self.root / "profile.json").read_bytes(), before)

    async def test_calibration_waits_for_all_prompt_acks_and_exactly_94_noise_frames(self):
        await self.session.control({"type": "calibration_start", "request_id": "cal"})
        self.assert_ack("cal")
        marker = self.session.calibration
        await self.until(lambda: len(self.session.pending) == 2)
        first = next(iter(self.session.pending))
        await self.session.control({"type": "played", "epoch": self.session.gate.epoch, "segment_id": first})
        await asyncio.sleep(0)
        for _ in range(100):
            await self.session.receive_audio(self.noise)
        self.assertEqual(marker["stage"], "prompt")
        self.assertEqual(marker["meter"].frames, 0)
        self.assertEqual(self.session.vad.calls, 0)
        await self.drain_audio()
        self.assertEqual(marker["stage"], "noise")
        for _ in range(93):
            await self.session.receive_audio(self.noise)
        self.assertEqual(marker["stage"], "noise")
        self.assertEqual(marker["meter"].frames, 93)
        await self.session.receive_audio(self.noise)
        self.assertEqual(marker["stage"], "prompt")
        self.assertEqual(marker["meter"].frames, 94)
        self.assertEqual(marker["noise"]["noise_seconds"], 3.008)
        for _ in range(20):
            await self.session.receive_audio(self.speech)
        self.assertEqual(marker["meter"].frames, 94)
        self.assertEqual(self.runtime.transcriber.calls, 0)
        await self.drain_audio()
        self.assertEqual(marker["stage"], "phrase")

    async def test_silence_and_typed_reference_cannot_pass_microphone_check(self):
        await self.get_to_phrase()
        for _ in range(150):
            await self.session.receive_audio(self.silence)
        self.assertEqual(self.session.calibration["stage"], "phrase")
        self.assertIsNone(self.session.calibration_result)
        self.assertEqual(self.runtime.transcriber.calls, 0)
        with patch.object(server.llm, "answer", new=ordinary_answer):
            await self.session.control({"type": "text", "text": REFERENCE_TEXT, "request_id": "typed-phrase"})
            await self.drain_audio()
        self.assertIsNone(self.session.calibration)
        self.assertIsNone(self.session.calibration_result)
        self.assertFalse((self.root / "audio_calibration.json").exists())
        self.assertTrue(any(message["type"] == "calibration" and message["stage"] == "cancelled" for message in self.socket.messages))

    async def test_stop_or_cancel_during_prompt_cannot_restart_sampling_on_late_ack(self):
        for operation in ("stop", "calibration_cancel"):
            with self.subTest(operation=operation):
                await self.session.control({"type": "calibration_start", "request_id": "begin"})
                job = self.session.job
                await self.until(lambda: bool(self.session.pending))
                old_epoch = self.session.gate.epoch
                ids = list(self.session.pending)
                mark = len(self.socket.messages)
                await self.session.control({"type": operation, "request_id": operation})
                await asyncio.gather(job, return_exceptions=True)
                self.assert_ack(operation)
                for segment_id in ids:
                    await self.session.control({"type": "played", "epoch": old_epoch, "segment_id": segment_id})
                for _ in range(100):
                    await self.session.receive_audio(self.noise)
                self.assertIsNone(self.session.calibration)
                self.assertFalse(any(message["type"] == "calibration" and message["stage"] in {"noise", "phrase"} for message in self.socket.messages[mark:]))
                self.assertFalse((self.root / "audio_calibration.json").exists())

    async def test_apply_requires_server_measurement_and_ignores_client_threshold(self):
        await self.session.control({"type": "calibration_apply", "request_id": "fake", "suggested_vad_threshold": 0.82, "can_apply": True})
        self.assert_ack("fake")
        self.assertFalse((self.root / "audio_calibration.json").exists())
        await self.get_to_phrase()
        await self.say(REFERENCE_TEXT)
        result = self.session.calibration_result
        self.assertTrue(result["can_apply"])
        self.assertFalse((self.root / "audio_calibration.json").exists())
        await self.session.control({"type": "calibration_apply", "request_id": "apply", "suggested_vad_threshold": 0.82, "vad_threshold": 0.82})
        self.assert_ack("apply")
        saved = json.loads((self.root / "audio_calibration.json").read_text())
        self.assertEqual(saved["vad_threshold"], result["suggested_vad_threshold"])
        self.assertNotEqual(saved["vad_threshold"], 0.82)
        self.assertNotIn("phrase_text", saved)
        self.assertNotIn("reference_text", saved)
        self.assertEqual(self.session.segmenter.s.vad_threshold, saved["vad_threshold"])

    async def test_profile_save_cancels_old_response_and_unheard_audio_before_applying(self):
        previous = Profile(user_name="Muzaffer", onboarding_complete=True)
        self.session.use_profile(previous)
        blocked = asyncio.Event()

        async def delayed_answer(*args, **kwargs):
            yield "Eski yanıtın ilk cümlesi. "
            await blocked.wait()
            yield "Eski yanıtın devamı."

        with patch.object(server.llm, "answer", new=delayed_answer):
            await self.session.control({"type": "text", "text": "Bir şey anlat.", "request_id": "old"})
            old_job = self.session.job
            await self.until(lambda: bool(self.session.pending))
            old_epoch = self.session.gate.epoch
            old_ack = next(iter(self.session.pending.values()))["ack"]
            next_profile = Profile(user_name="Muzaffer", assistant_name="Atlas", style="balanced", onboarding_complete=True)
            await self.session.control({"type": "profile_save", "request_id": "new-profile", "profile": next_profile.to_dict()})
            await asyncio.gather(old_job, return_exceptions=True)
            blocked.set()
        self.assert_ack("new-profile")
        self.assertGreater(self.session.gate.epoch, old_epoch)
        self.assertTrue(old_ack.cancelled())
        self.assertFalse(self.session.pending)
        self.assertEqual(self.runtime.profile_store.load(), next_profile)
        self.assertEqual(self.session.profile, next_profile)
        self.assertFalse(any(message["type"] == "audio" and "devamı" in message["text"] for message in self.socket.messages))


class GuidedProtocolTests(unittest.TestCase):
    def test_protocol_three_is_accepted_and_older_protocols_are_rejected(self):
        self.assertEqual(server.SETTINGS.protocol_version, 3)
        with tempfile.TemporaryDirectory() as directory, patch.object(server, "DATA_ROOT", Path(directory)):
            runtime = server.Runtime(demo=True)
            with TestClient(server.create_app(runtime)) as client:
                headers = {"origin": f"http://127.0.0.1:{server.SETTINGS.port}"}
                for old_protocol in (1, 2):
                    with client.websocket_connect("/ws", headers=headers) as ws:
                        ws.send_json({"type": "hello", "protocol": old_protocol, "token": runtime.token})
                        with self.assertRaises(WebSocketDisconnect):
                            ws.receive_json()
                with client.websocket_connect("/ws", headers=headers) as ws:
                    ws.send_json({"type": "hello", "protocol": 3, "token": runtime.token})
                    self.assertEqual(ws.receive_json()["type"], "hello")
                    self.assertEqual(ws.receive_json()["type"], "ready")
                    self.assertEqual(ws.receive_json()["type"], "profile")
                    ws.send_json({"type": "ping"})
                    self.assertEqual(ws.receive_json()["type"], "pong")


if __name__ == "__main__":
    unittest.main()
