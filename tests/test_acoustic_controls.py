"""Opt-out must not strand guided flows that never use acoustic analysis."""
import asyncio
import unittest

import test_guided_runtime as guided
from jarvis.calibration import REFERENCE_TEXT


class AcousticControlTests(unittest.IsolatedAsyncioTestCase):
    # Reuse the actual Session/Runtime fixture, without inheriting and rerunning
    # the unrelated guided-flow test methods.
    asyncSetUp = guided.GuidedRuntimeTests.asyncSetUp
    until = guided.GuidedRuntimeTests.until
    drain_audio = guided.GuidedRuntimeTests.drain_audio
    get_to_phrase = guided.GuidedRuntimeTests.get_to_phrase

    async def asyncTearDown(self):
        await guided.GuidedRuntimeTests.asyncTearDown(self)
        self.runtime.analysis_cpu.close()

    async def test_analysis_opt_out_does_not_cancel_pending_calibration_prompt(self):
        await self.session.control({"type": "settings", "acoustic_enabled": True})
        await self.session.control({"type": "calibration_start", "request_id": "cal"})
        job = self.session.job
        marker = self.session.calibration
        await self.until(lambda: bool(self.session.pending))
        epoch = self.session.gate.epoch
        self.assertEqual(marker["stage"], "prompt")
        self.assertFalse(job.done())

        await self.session.control({"type": "settings", "acoustic_enabled": False})
        self.assertFalse(self.session.acoustic_enabled)
        self.assertEqual(self.session.gate.epoch, epoch)
        self.assertIs(self.session.calibration, marker)
        self.assertFalse(job.cancelling())
        await self.drain_audio(job)
        self.assertEqual(marker["stage"], "noise")
        self.assertIsNotNone(self.session.calibration_timer)

    async def test_analysis_opt_out_does_not_cancel_processing_calibration_phrase(self):
        await self.session.control({"type": "settings", "acoustic_enabled": True})
        await self.get_to_phrase()
        entered, release = asyncio.Event(), asyncio.Event()

        class PendingASR:
            async def call(self, function, *args):
                entered.set()
                await release.wait()
                return REFERENCE_TEXT

            def close(self):
                pass

        self.runtime.asr_cpu = PendingASR()
        for _ in range(12):
            await self.session.receive_audio(self.speech)
        for _ in range(self.session.segmenter.s.end_silence_frames):
            await self.session.receive_audio(self.silence)
        await asyncio.wait_for(entered.wait(), 1)
        job = self.session.job
        marker = self.session.calibration
        epoch = self.session.gate.epoch
        self.assertEqual(marker["stage"], "processing")

        try:
            await self.session.control({"type": "settings", "acoustic_enabled": False})
            self.assertEqual(self.session.gate.epoch, epoch)
            self.assertIs(self.session.calibration, marker)
            self.assertFalse(job.cancelling())
            release.set()
            await self.drain_audio(job)
        finally:
            release.set()
        self.assertIsNone(self.session.calibration)
        self.assertIsNotNone(self.session.calibration_result)
        self.assertTrue(any(m["type"] == "calibration" and m["stage"] == "result" for m in self.socket.messages))

    async def test_analysis_opt_out_preserves_pending_introduction(self):
        await self.session.control({"type": "settings", "acoustic_enabled": True})
        entered, release = asyncio.Event(), asyncio.Event()

        class PendingTTS:
            async def call(self, function, *args):
                entered.set()
                await release.wait()
                return function(*args)

            def close(self):
                pass

        self.runtime.tts_cpu = PendingTTS()
        await self.session.control({"type": "onboarding_start", "request_id": "intro"})
        await asyncio.wait_for(entered.wait(), 1)
        job = self.session.job
        epoch = self.session.gate.epoch
        try:
            await self.session.control({"type": "settings", "acoustic_enabled": False})
            self.assertEqual(self.session.gate.epoch, epoch)
            self.assertTrue(self.session.onboarding.active)
            self.assertFalse(job.cancelling())
            release.set()
            await self.drain_audio(job)
        finally:
            release.set()
        self.assertEqual(self.session.onboarding.stage, "user_name")
        self.assertTrue(self.session.onboarding.active)


if __name__ == "__main__":
    unittest.main()
