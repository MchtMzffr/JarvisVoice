import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from jarvis import llm
from jarvis.plans import draft_from_model
from jarvis.profile import Profile, profile_prompt


class PlanAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fit = patch.object(llm, "fit_messages", side_effect=lambda messages, *args: messages)
        self.fit.start()

    def tearDown(self):
        self.fit.stop()

    async def test_plan_uses_local_schema_profile_notes_but_no_tools(self):
        profile = Profile(user_name="Deniz", assistant_name="Atlas")
        value = {"title": "Çalışma", "steps": [{"text": "Bir örnek çöz.", "minutes": 20}], "assumptions": []}
        captured = []
        def handler(request):
            self.assertEqual(str(request.url), llm.SETTINGS.ollama_url + "/api/chat")
            self.assertNotIn("authorization", request.headers)
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"done": True, "message": {"content": json.dumps(value), "thinking": "hidden"}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await llm.make_plan("Python çalışacağım", [], [{"text": "Akşam 20 dakikam var."}], profile=profile, client=client)
            self.assertFalse(client.is_closed)
        body = captured[0]
        self.assertNotIn("tools", body)
        self.assertFalse(body["stream"])
        self.assertEqual(body["format"]["type"], "object")
        self.assertIn(profile_prompt(profile), body["messages"][0]["content"])
        self.assertIn("Akşam 20 dakikam var.", body["messages"][0]["content"])
        self.assertEqual(result.title, "Çalışma")

    async def test_incomplete_or_invalid_plan_fails_without_using_thinking(self):
        for frame in (
            {"done": False, "message": {"content": "{}"}},
            {"done": True, "done_reason": "length", "message": {"content": "{}"}},
            {"done": True, "message": {"content": "{}", "thinking": "hidden"}},
            {"done": True, "message": {"content": "not json", "tool_calls": [{"function": {"name": "open_app"}}]}},
            {"done": True, "message": {"content": '{"title":"Bir","title":"İki","steps":[],"assumptions":[]}'}},
            {"done": True, "message": {"content": '[' * 1200 + '0' + ']' * 1200}},
        ):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=frame))) as client:
                with self.assertRaises(llm.ModelUnavailable) as raised:
                    await llm.make_plan("Bir hedef", [], [], client=client)
                self.assertNotIn("hidden", str(raised.exception))

    async def test_saved_plan_is_not_sent_to_web_decision(self):
        saved = draft_from_model({"title": "private-plan-marker", "steps": [{"text": "Yerel adım.", "minutes": None}], "assumptions": []})
        requests = []
        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:
                return httpx.Response(200, json={"done": True, "message": {"content": "Merhaba"}})
            return httpx.Response(200, content='{"done":true,"message":{"content":"Son cevap"}}\n')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            output = [part async for part in llm.answer("Merhaba", [], [], "test-key", True, AsyncMock(), AsyncMock(),
                                                       client=client, saved_plan=saved)]
        self.assertNotIn("private-plan-marker", json.dumps(requests[0], ensure_ascii=False))
        self.assertIn("private-plan-marker", json.dumps(requests[1], ensure_ascii=False))
        self.assertEqual(output, ["Son cevap"])


if __name__ == "__main__":
    unittest.main()
