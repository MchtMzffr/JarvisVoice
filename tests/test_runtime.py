"""Concurrency/protocol regressions; no models, microphone or network needed."""

import asyncio
import json
import threading
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import numpy as np

from jarvis import llm, server


class MemoryStub:
    def __init__(self):
        self.closed = False

    def list(self):
        return []

    def close(self):
        self.closed = True


class SocketStub:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    async def send_json(self, data):
        if self.fail:
            raise RuntimeError("Socket is already disconnected")
        self.messages.append(data)


class ImmediateCPU:
    async def call(self, function, *args):
        return function(*args)


def make_session(synthesize=None, fail_socket=False):
    memory = MemoryStub()
    socket = SocketStub(fail_socket)
    if synthesize is None:
        synthesize = lambda text: (np.zeros(32, dtype=np.float32), 24_000)
    runtime = SimpleNamespace(
        ready=True,
        demo=False,
        tts_cpu=ImmediateCPU(),
        speaker=SimpleNamespace(synthesize=synthesize),
    )
    with patch.object(server, "MemoryStore", return_value=memory):
        session = server.Session(socket, runtime)
    session.gate.active = True
    return session, socket, memory


async def many_sentences(*args, **kwargs):
    yield "Birinci cümle. İkinci cümle. Üçüncü cümle. Dördüncü cümle. Beşinci cümle."


async def no_callback(*args, **kwargs):
    pass


class SerialCPUTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_cancellation_does_not_release_running_worker_slot(self):
        cpu = server.SerialCPU("test-cancellation")
        started, release = threading.Event(), threading.Event()
        second_started = threading.Event()

        def blocking_worker():
            started.set()
            release.wait(2)
            return "finished"

        running = asyncio.create_task(cpu.call(blocking_worker))
        second = None
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            running.cancel()
            await asyncio.sleep(0)
            self.assertTrue(cpu.lock.locked())
            running.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertTrue(cpu.lock.locked(), "A repeated cancel released a running CPU operation's slot")
            second = asyncio.create_task(cpu.call(second_started.set))
            await asyncio.sleep(0)
            self.assertFalse(second_started.is_set())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await running
            await asyncio.wait_for(second, 1)
            self.assertTrue(second_started.is_set())
        finally:
            release.set()
            if second is not None:
                second.cancel()
            running.cancel()
            await asyncio.gather(running, *([second] if second is not None else []), return_exceptions=True)
            cpu.close()


class SessionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_forced_utterance_limit_stops_capture_without_answering_a_prefix(self):
        session, socket, _ = make_session()

        class SpeakingVAD:
            def probability(self, frame):
                return 1.0

            def reset(self):
                pass

        session.runtime.vad_factory = SpeakingVAD
        session.segmenter = server.Segmenter(replace(
            server.SETTINGS, max_utterance_frames=8, preroll_frames=1,
            onset_frames=1, min_speech_frames=1,
        ))
        frame = np.full(server.SETTINGS.frame_samples, 1000, dtype="<i2").tobytes()
        try:
            for _ in range(10):
                await session.receive_audio(frame)
            self.assertFalse(session.gate.active)
            self.assertIsNone(session.job)
            self.assertFalse(session.history)
            stops = [message for message in socket.messages if message["type"] == "capture_stop"]
            self.assertEqual(len(stops), 1)
            self.assertIn("30 saniye", stops[0]["message"])
            self.assertEqual(stops[0]["epoch"], session.gate.epoch)
            self.assertFalse(any(message["type"] == "audio" for message in socket.messages))
        finally:
            await session.close()

    async def test_failed_tts_consumer_unblocks_a_full_producer_queue(self):
        def fail_synthesis(text):
            raise RuntimeError("Synthetic TTS failure")

        session, socket, _ = make_session(fail_synthesis)
        try:
            with patch.object(server.llm, "answer", new=many_sentences):
                job = session.spawn(session.handle_turn(session.gate.epoch, text="Bir şey anlat."))
                session.job = job
                completed, _ = await asyncio.wait({job}, timeout=1)
                self.assertIn(job, completed, "Producer hung after its TTS consumer failed")
                await job
            self.assertTrue(any(m["type"] == "error" for m in socket.messages))
            self.assertFalse(any(m["type"] == "audio" for m in socket.messages))
        finally:
            await session.close()

    async def test_failed_tts_interrupts_producer_waiting_for_next_llm_chunk(self):
        producer_waiting = asyncio.Event()
        failure_triggered = asyncio.Event()
        session, socket, _ = make_session()

        class DelayedFailureCPU:
            async def call(self, function, *args):
                await producer_waiting.wait()
                failure_triggered.set()
                raise RuntimeError("TTS failed while upstream stopped producing")

        async def stalled_answer(*args, **kwargs):
            # Explicit whitespace commits this sentence even when the buffer
            # conservatively holds punctuation at the end of a stream chunk.
            yield "İlk cümle. "
            producer_waiting.set()
            await asyncio.Event().wait()

        session.runtime.tts_cpu = DelayedFailureCPU()
        try:
            with patch.object(server.llm, "answer", new=stalled_answer):
                job = session.spawn(session.handle_turn(session.gate.epoch, text="Bir şey anlat."))
                session.job = job
                completed, _ = await asyncio.wait({job}, timeout=1)
                self.assertTrue(failure_triggered.is_set(), "The fixture did not reach the TTS failure")
                self.assertIn(job, completed, "TTS failure waited indefinitely for another LLM network chunk")
                await job
            self.assertTrue(any(m["type"] == "error" for m in socket.messages))
        finally:
            await session.close()

    async def test_missing_playback_ack_cannot_deadlock_production(self):
        session, socket, _ = make_session()
        settings = replace(server.SETTINGS, max_pending_audio=1, playback_ack_timeout_s=0.02)
        try:
            with patch.object(server, "SETTINGS", settings), patch.object(server.llm, "answer", new=many_sentences):
                job = session.spawn(session.handle_turn(session.gate.epoch, text="Bir şey anlat."))
                session.job = job
                completed, _ = await asyncio.wait({job}, timeout=1)
                self.assertIn(job, completed, "Missing playback acknowledgement stalled the producer forever")
                await job
            self.assertEqual(sum(m["type"] == "audio" for m in socket.messages), 1)
            self.assertTrue(any(m["type"] == "error" for m in socket.messages))
            self.assertFalse(any(m["content"] for m in session.history if m["role"] == "assistant"))
        finally:
            await session.close()

    async def test_history_commits_only_once_for_current_epoch_playback_ack(self):
        session, _, _ = make_session()
        entry = {"role": "assistant", "content": ""}
        acknowledged = asyncio.get_running_loop().create_future()
        unheard = asyncio.get_running_loop().create_future()
        session.pending["heard"] = {"ack": acknowledged, "history": entry, "text": "Duyulan cümle."}
        session.pending["unheard"] = {"ack": unheard, "history": entry, "text": "Duyulmayan cümle."}
        old_epoch = session.gate.epoch
        try:
            await session.control({"type": "played", "epoch": old_epoch - 1, "segment_id": "heard"})
            self.assertFalse(acknowledged.done())
            self.assertEqual(entry["content"], "")
            ack = {"type": "played", "epoch": old_epoch, "segment_id": "heard"}
            await session.control(ack)
            await session.control(ack)
            self.assertEqual(entry["content"], "Duyulan cümle.")
            self.assertTrue(acknowledged.result())
            await session.interrupt()
            await session.control({"type": "played", "epoch": old_epoch, "segment_id": "unheard"})
            self.assertTrue(unheard.cancelled())
            self.assertEqual(entry["content"], "Duyulan cümle.")
            self.assertFalse(session.pending)
        finally:
            await session.close()

    async def test_close_cleans_resources_even_when_socket_is_disconnected(self):
        session, socket, memory = make_session(fail_socket=True)
        session.api_key = "synthetic-test-key"
        ack = asyncio.get_running_loop().create_future()
        session.pending["p"] = {"ack": ack, "history": {"content": ""}, "text": "Bekleyen."}
        stopped = asyncio.Event()

        async def waiting_job():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        job = session.spawn(waiting_job())
        session.job = job
        await asyncio.sleep(0)
        try:
            await asyncio.wait_for(session.close(), 1)
            self.assertTrue(session.closed)
            self.assertFalse(session.gate.active)
            self.assertEqual(session.api_key, "")
            self.assertTrue(memory.closed)
            self.assertTrue(ack.cancelled())
            self.assertTrue(stopped.is_set())
            self.assertFalse(socket.messages)
        finally:
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
            if not memory.closed:
                memory.close()

    async def test_sender_waiting_for_lock_does_not_send_after_close(self):
        session, socket, _ = make_session()
        await session.send_lock.acquire()
        waiting = asyncio.create_task(session.send({"type": "status", "message": "stale"}))
        try:
            await asyncio.sleep(0)
            await asyncio.wait_for(session.close(), 1)
            session.send_lock.release()
            await asyncio.wait_for(waiting, 1)
            self.assertFalse(socket.messages, "A sender passed the closed check before waiting on send_lock")
        finally:
            if session.send_lock.locked():
                session.send_lock.release()
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
            await session.close()


class OllamaStreamTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, frames):
        body = "\n".join(json.dumps(frame) for frame in frames) + "\n"
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
        real_client = httpx.AsyncClient

        def client(*args, **kwargs):
            return real_client(*args, transport=transport, **kwargs)

        with patch.object(llm.httpx, "AsyncClient", new=client), patch.object(
            llm, "fit_messages", side_effect=lambda messages, *args: messages
        ):
            return [part async for part in llm.answer("Merhaba", [], [], "", False, no_callback, no_callback)]

    async def test_clean_eof_without_done_is_not_reported_as_completed_answer(self):
        with self.assertRaises(llm.ModelUnavailable):
            await self.collect([{"message": {"content": "Yarım kalan cevap"}, "done": False}])

    async def test_thinking_never_enters_spoken_content(self):
        result = await self.collect([
            {"message": {"thinking": "internal-only", "content": ""}, "done": False},
            {"message": {"content": "Merhaba."}, "done": False},
            {"message": {"content": ""}, "done": True},
        ])
        self.assertEqual(result, ["Merhaba."])


if __name__ == "__main__":
    unittest.main()
