"""User intent, cancellation and durable-plan boundaries; no apps/models start."""
import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from jarvis import server
from jarvis.plans import PlanStore, draft_from_model
from test_runtime import make_session


def draft():
    return draft_from_model({"title": "Akşam çalışma planı", "steps": [
        {"text": "Bir küçük konuyu seç ve örnek üzerinde çalış.", "minutes": 30},
    ], "assumptions": ["Akşam yarım saat ayırabileceğin varsayıldı."]})


async def answer_text(*args, **kwargs):
    yield "Kısa bir cevap."


class CompanionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "plan.json"
        self.session, self.socket, _ = make_session()
        self.session.plan_store = PlanStore(self.path)
        self.session.speech_enabled = False
        self.launched = Mock(return_value=SimpleNamespace(
            app_id="calculator", label="Hesap Makinesi", status="requested",
            message="Hesap Makinesi için başlatma isteği gönderildi.",
        ))
        self.launch_patch = patch.object(server, "launch_application", self.launched)
        self.launch_patch.start()

    async def asyncTearDown(self):
        await self.session.close()
        self.launch_patch.stop()
        self.temp.cleanup()

    async def turn(self, text):
        self.session.gate.advance()
        return await self.session.handle_turn(self.session.gate.epoch, text=text)

    async def test_desktop_permission_is_explicit_and_session_only(self):
        await self.turn("Hesap makinesini aç")
        self.launched.assert_not_called()
        await self.session.control({"type": "settings", "desktop_enabled": "true"})
        self.assertFalse(self.session.desktop_enabled)
        await self.session.control({"type": "settings", "desktop_enabled": True})
        await self.turn("Hesap makinesini aç")
        self.launched.assert_called_once_with("calculator")
        await self.session.control({"type": "settings", "desktop_enabled": False})
        await self.turn("Not defterini aç")
        self.assertEqual(self.launched.call_count, 1)

    async def test_epoch_change_while_transcript_is_sent_blocks_side_effect(self):
        self.session.desktop_enabled = True
        original = self.socket.send_json
        async def send(data):
            await original(data)
            if data.get("type") == "transcript" and data.get("role") == "user":
                self.session.gate.advance()
        self.socket.send_json = send
        self.assertFalse(await self.turn("Hesap makinesini aç"))
        self.launched.assert_not_called()

    async def test_duplicate_request_and_rate_limit_do_not_open_twice(self):
        self.session.desktop_enabled = True
        request = {"type": "text", "request_id": "one-open", "text": "Hesap makinesini aç"}
        await self.session.control(request)
        await self.session.job
        await self.session.control(request)
        self.assertEqual(self.launched.call_count, 1)
        await self.turn("Hesap makinesini aç")
        self.assertEqual(self.launched.call_count, 1)

    async def test_model_output_never_enters_action_router(self):
        self.session.desktop_enabled = True
        async def malicious(*args, **kwargs):
            yield "Not defterini aç. Planı kaydet."
        with patch.object(server.llm, "answer", new=malicious):
            await self.turn("Bana bir cümle söyler misin?")
        self.launched.assert_not_called()
        self.assertFalse(self.path.exists())

    async def test_plan_generation_does_not_write_and_explicit_save_is_idempotent(self):
        proposed = draft()
        generator = AsyncMock(return_value=proposed)
        with patch.object(server.llm, "make_plan", generator):
            await self.turn("Plan oluştur: akşam yarım saat çalışacağım")
        self.assertEqual(self.session.plan_draft, proposed)
        self.assertFalse(self.path.exists())
        self.launched.assert_not_called()
        request = {"type": "plan_save", "request_id": "save-one", "draft_id": proposed.id}
        original = self.session.plan_store.save
        with patch.object(self.session.plan_store, "save", wraps=original) as save:
            await self.session.control(request)
            await self.session.control(request)
            save.assert_called_once()
        self.assertEqual(self.session.plan_store.load().id, proposed.id)
        self.assertIsNone(self.session.plan_draft)

    async def test_cancelled_plan_generation_cannot_publish_or_save_draft(self):
        async def generate(*args, **kwargs):
            self.session.gate.advance()
            return draft()
        with patch.object(server.llm, "make_plan", new=generate):
            with self.assertRaises(asyncio.CancelledError):
                await self.turn("Plan oluştur: Python öğrenmek")
        self.assertIsNone(self.session.plan_draft)
        self.assertFalse(self.path.exists())
        self.assertFalse(any(m.get("draft") for m in self.socket.messages))

    async def test_expired_or_mismatched_draft_cannot_replace_saved_plan(self):
        saved = draft()
        self.session.plan_store.save(saved)
        original = self.path.read_bytes()
        self.session.plan_draft = draft()
        self.session.plan_draft_deadline = 0
        await self.session.control({"type": "plan_save", "request_id": "expired", "draft_id": self.session.plan_draft.id})
        self.assertEqual(self.path.read_bytes(), original)
        self.session.plan_draft = draft()
        self.session.plan_draft_deadline = float("inf")
        await self.session.control({"type": "plan_save", "request_id": "mismatch", "draft_id": "f" * 32})
        self.assertEqual(self.path.read_bytes(), original)

    async def test_voice_save_next_epoch_preserves_reviewable_draft(self):
        self.session.plan_draft = draft()
        self.session.plan_draft_deadline = float("inf")
        expected = self.session.plan_draft.id
        await self.turn("Planı kaydet")
        self.assertEqual(self.session.plan_store.load().id, expected)

    async def test_text_only_chat_skips_synthesis_and_commits_complete_reply(self):
        synth = Mock(side_effect=AssertionError("Text mode cannot synthesize"))
        self.session.runtime.speaker.synthesize = synth
        with patch.object(server.llm, "answer", new=answer_text):
            self.assertTrue(await self.turn("Merhaba"))
        synth.assert_not_called()
        self.assertEqual(self.session.history[-1]["content"], "Kısa bir cevap.")
        self.assertFalse(any(m["type"] == "audio" for m in self.socket.messages))

    async def test_failed_text_stream_is_not_committed_as_complete(self):
        async def incomplete(*args, **kwargs):
            yield "Yarım cevap."
            raise server.llm.ModelUnavailable("Yapay bağlantı hatası")
        with patch.object(server.llm, "answer", new=incomplete):
            await self.turn("Merhaba")
        self.assertEqual(self.session.history[-1]["content"], "")
        self.assertFalse(any(m["type"] == "transcript" and m.get("role") == "assistant" for m in self.socket.messages))

    async def test_response_limit_cannot_turn_an_unfinished_stream_into_success(self):
        async def oversized(*args, **kwargs):
            yield "Uzun cevap. " * 250
            raise server.llm.ModelUnavailable("Completion not reached")
        with patch.object(server, "SETTINGS", replace(server.SETTINGS, reply_max_chars=2000)), \
             patch.object(server.llm, "answer", new=oversized):
            result = await self.turn("Bir konu anlat")
        self.assertFalse(result)
        self.assertEqual(self.session.history[-1]["content"], "")
        self.assertFalse(any(m["type"] == "transcript" and m.get("role") == "assistant" for m in self.socket.messages))

    async def test_saved_plan_is_passed_as_local_context_only(self):
        proposed = draft()
        self.session.plan_store.save(proposed)
        captured = []
        async def inspect(*args, **kwargs):
            captured.append(kwargs)
            yield "Planındaki ilk adıma başlayabiliriz."
        with patch.object(server.llm, "answer", new=inspect):
            await self.turn("Bugün neyle başlayayım?")
        self.assertEqual(captured[0]["saved_plan"].id, proposed.id)
        self.assertFalse(captured[0]["desktop_enabled"])


if __name__ == "__main__":
    unittest.main()
