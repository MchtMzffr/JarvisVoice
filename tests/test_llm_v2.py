"""Local adapter regressions using MockTransport; no model or internet needed."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from jarvis import llm


async def nothing(*args, **kwargs):
    pass


def ndjson(*frames):
    return httpx.Response(200, content="\n".join(json.dumps(f) for f in frames) + "\n")


def completed(text="Merhaba.", **counters):
    return ndjson(
        {"message": {"content": text}, "done": False},
        {"message": {"content": ""}, "done": True, "done_reason": "stop", **counters},
    )


class LLMv2Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Tests isolate transport/protocol behavior from the optional local
        # tokenizer asset. The real token-budget test lives in test_api.py.
        self.fit = patch.object(llm, "fit_messages", side_effect=lambda messages, *args: messages)
        self.fit.start()

    def tearDown(self):
        self.fit.stop()

    async def collect(self, client, **kwargs):
        return [s async for s in llm.answer(
            "Merhaba", [], [], kwargs.pop("api_key", ""), kwargs.pop("web_enabled", False),
            nothing, nothing, client=client, **kwargs,
        )]

    async def test_shared_client_survives_two_turns_and_warmup(self):
        requests = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            self.assertEqual(str(request.url), llm.SETTINGS.ollama_url + "/api/chat")
            if body["messages"] == []:
                return httpx.Response(200, json={"done": True, "done_reason": "load"})
            return completed()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            self.assertEqual(await llm.warmup(client), {})
            self.assertEqual(await self.collect(client), ["Merhaba."])
            self.assertEqual(await self.collect(client), ["Merhaba."])
            self.assertFalse(client.is_closed)
        self.assertEqual(len(requests), 3)
        self.assertTrue(client.is_closed)

    async def test_adapter_closes_only_its_own_client(self):
        real_client = httpx.AsyncClient
        created = []

        def factory(*args, **kwargs):
            client = real_client(*args, **kwargs, transport=httpx.MockTransport(lambda req: completed()))
            created.append(client)
            return client

        with patch.object(llm.httpx, "AsyncClient", side_effect=factory):
            self.assertEqual(await self.collect(None), ["Merhaba."])
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].is_closed)

    async def test_cancelled_answer_closes_response_but_keeps_shared_client(self):
        waiting = asyncio.Event()

        class WaitingStream(httpx.AsyncByteStream):
            def __init__(self):
                self.closed = False

            async def __aiter__(self):
                yield b'{"message":{"content":""},"done":false}\n'
                waiting.set()
                await asyncio.Event().wait()

            async def aclose(self):
                self.closed = True

        stream = WaitingStream()
        transport = httpx.MockTransport(lambda req: httpx.Response(200, stream=stream))
        async with httpx.AsyncClient(transport=transport) as client:
            job = asyncio.create_task(self.collect(client))
            await asyncio.wait_for(waiting.wait(), 1)
            job.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await job
            self.assertTrue(stream.closed)
            self.assertFalse(client.is_closed)

    async def test_warmup_is_empty_local_model_request_with_current_context(self):
        captured = []

        def handler(request):
            captured.append(json.loads(request.content))
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(200, json={"done": True, "load_duration": 123_000_000})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch.object(llm, "fit_messages", side_effect=AssertionError("No prompt for warmup")):
                self.assertEqual(await llm.warmup(client), {"ollama_load_ms": 123.0})
        self.assertEqual(captured, [{
            "model": llm.SETTINGS.model, "messages": [], "stream": False,
            "keep_alive": llm.SETTINGS.keep_alive,
            "options": {"num_ctx": llm.SETTINGS.num_ctx},
        }])

    async def test_warmup_failure_is_safe_and_does_not_close_shared_client(self):
        transport = httpx.MockTransport(lambda req: httpx.Response(503, text="private server detail"))
        async with httpx.AsyncClient(transport=transport) as client:
            with self.assertRaises(llm.ModelUnavailable) as raised:
                await llm.warmup(client)
            self.assertNotIn("private", str(raised.exception))
            self.assertFalse(client.is_closed)

    async def test_final_metrics_are_numeric_and_use_documented_units(self):
        counters = {
            "load_duration": 120_000_000, "prompt_eval_duration": 50_000_000,
            "eval_duration": 2_000_000_000, "eval_count": 40, "prompt_eval_cached_count": 17,
        }
        callback = AsyncMock()
        transport = httpx.MockTransport(lambda req: completed("Tamam.", **counters))
        async with httpx.AsyncClient(transport=transport) as client:
            self.assertEqual(await self.collect(client, metrics_callback=callback), ["Tamam."])
        callback.assert_awaited_once_with({
            "ollama_load_ms": 120.0, "prompt_eval_ms": 50.0, "eval_ms": 2000.0,
            "eval_tokens": 40, "eval_tokens_per_s": 20.0, "cache_tokens": 17,
        })

    async def test_malformed_metrics_stay_missing(self):
        self.assertEqual(llm._metrics({
            "load_duration": True, "prompt_eval_duration": -1, "eval_duration": float("nan"),
            "eval_count": "20", "prompt_eval_cached_count": False,
        }), {})
        self.assertEqual(llm._metrics({"eval_count": 3, "eval_duration": 0}), {
            "eval_tokens": 3, "eval_ms": 0.0,
        })

    async def test_thinking_does_not_enter_content_or_metrics(self):
        callback = AsyncMock()
        transport = httpx.MockTransport(lambda req: ndjson(
            {"message": {"thinking": "hidden reasoning", "content": ""}, "done": False},
            {"message": {"thinking": "still hidden", "content": "Cevap."}, "done": False},
            {"message": {"content": "", "thinking": "last hidden"}, "done": True, "eval_count": 4},
        ))
        async with httpx.AsyncClient(transport=transport) as client:
            self.assertEqual(await self.collect(client, metrics_callback=callback), ["Cevap."])
        callback.assert_awaited_once_with({"eval_tokens": 4})

    async def test_eof_without_done_is_not_completed(self):
        callback = AsyncMock()
        transport = httpx.MockTransport(lambda req: ndjson({"message": {"content": "Yarım"}, "done": False}))
        async with httpx.AsyncClient(transport=transport) as client:
            with self.assertRaises(llm.ModelUnavailable):
                await self.collect(client, metrics_callback=callback)
        callback.assert_not_awaited()

    async def test_length_termination_is_not_success(self):
        callback = AsyncMock()
        transport = httpx.MockTransport(lambda req: ndjson(
            {"message": {"content": "Yarım"}, "done": False},
            {"message": {"content": ""}, "done": True, "done_reason": "length"},
        ))
        async with httpx.AsyncClient(transport=transport) as client:
            with self.assertRaises(llm.ModelUnavailable):
                await self.collect(client, metrics_callback=callback)
        callback.assert_not_awaited()

    async def test_nonstream_web_decision_must_be_complete(self):
        for done, reason in ((False, "stop"), (True, "length")):
            with self.subTest(done=done, reason=reason):
                transport = httpx.MockTransport(lambda req: httpx.Response(200, json={
                    "message": {"content": "Tamamlanmamış cevap"}, "done": done, "done_reason": reason,
                }))
                async with httpx.AsyncClient(transport=transport) as client:
                    with self.assertRaises(llm.ModelUnavailable):
                        await self.collect(client, api_key="synthetic-key", web_enabled=True)

    async def test_nonstream_answer_skips_thinking_and_reports_metrics(self):
        callback = AsyncMock()
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json={
            "message": {"content": "Merhaba.", "thinking": "hidden", "tool_calls": []},
            "done": True, "eval_count": 3,
        }))
        async with httpx.AsyncClient(transport=transport) as client:
            self.assertEqual(await self.collect(
                client, api_key="synthetic-key", web_enabled=True, metrics_callback=callback,
            ), ["Merhaba."])
        callback.assert_awaited_once_with({"eval_tokens": 3})

    async def test_profile_reaches_both_research_requests(self):
        from jarvis.profile import Profile, profile_prompt
        profile = Profile(user_name="Deniz", assistant_name="Atlas", style="formal", verbosity="medium")
        expected = profile_prompt(profile)
        requests = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            self.assertIn(expected, body["messages"][0]["content"])
            self.assertNotIn("authorization", request.headers)
            if len(requests) == 1:
                return httpx.Response(200, json={"done": True, "message": {"content": "", "tool_calls": [{
                    "function": {"name": "search_web", "arguments": {"query": "güncel örnek"}},
                }]}})
            return completed("Kaynağa göre cevap.")

        research = AsyncMock(return_value=([], "Kaynak verisi"))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch.object(llm, "research", new=research):
                result = await self.collect(client, api_key="synthetic-key", web_enabled=True, profile=profile)
        self.assertEqual(result, ["Kaynağa göre cevap."])
        self.assertEqual(len(requests), 2)
        research.assert_awaited_once_with("güncel örnek", "synthetic-key")


if __name__ == "__main__":
    unittest.main()
