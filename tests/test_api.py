import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from jarvis.server import Runtime, create_app
from jarvis.config import SETTINGS


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.override = patch("jarvis.server.DATA_ROOT", Path(self.directory.name))
        self.override.start()
        self.runtime = Runtime(demo=True)
        self.client_context = TestClient(create_app(self.runtime))
        self.client = self.client_context.__enter__()
        self.origin = {"origin": "http://127.0.0.1:8765"}

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.override.stop()
        self.directory.cleanup()

    def test_other_site_cannot_open_microphone_session(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws", headers={"origin": "https://other.example"}):
                pass

    def test_wrong_token_is_rejected(self):
        with self.client.websocket_connect("/ws", headers=self.origin) as ws:
            ws.send_json({"type": "hello", "protocol": SETTINGS.protocol_version, "token": "incorrect"})
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()

    def test_stop_ack_echoes_request_id_and_never_echoes_api_key(self):
        with self.client.websocket_connect("/ws", headers=self.origin) as ws:
            ws.send_json({"type": "hello", "protocol": SETTINGS.protocol_version, "token": self.runtime.token})
            self.assertEqual(ws.receive_json()["type"], "hello")
            self.assertEqual(ws.receive_json()["type"], "ready")
            self.assertEqual(ws.receive_json()["type"], "profile")
            ws.send_json({"type": "settings", "api_key": "test-private-key", "web_enabled": False})
            settings = ws.receive_json()
            self.assertTrue(settings["has_api_key"])
            self.assertNotIn("test-private-key", str(settings))
            ws.receive_json()
            ws.send_json({"type": "stop", "request_id": "stop-42"})
            acknowledgement = ws.receive_json()
            self.assertEqual(acknowledgement["type"], "epoch")
            self.assertEqual(acknowledgement["request_id"], "stop-42")


class ContextTests(unittest.TestCase):
    def test_large_turkish_history_and_sources_fit_budget(self):
        from jarvis.context import valid_cache, fit_messages, count
        if not valid_cache():
            self.skipTest("Tokenizer is downloaded by KUR.cmd; network is not used by this test.")
        messages = [{"role": "system", "content": "Kısa Türkçe cevap ver."}]
        messages.extend({"role": "user", "content": "Uzun konuşma geçmişi. " * 1000} for _ in range(4))
        messages.append({"role": "user", "content": "Asıl soru. Kaynak metni: " + "Türkiye hakkında kaynak bilgisi. " * 2000})
        fitted = fit_messages(messages)
        self.assertEqual(fitted[0], messages[0])
        self.assertTrue(fitted[-1]["content"].startswith("Asıl soru."))
        self.assertLessEqual(sum(count(m["content"]) + 12 for m in fitted), SETTINGS.num_ctx - SETTINGS.num_predict - SETTINGS.context_framing_reserve)


if __name__ == "__main__":
    unittest.main()
