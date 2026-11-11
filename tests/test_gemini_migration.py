"""Offline Gemini migration contracts; credentials/network are disabled."""
import json
import unittest
import httpx
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import test_no_sql_contract as isolation


def setUpModule():
    global utils
    isolation.setUpModule()
    import utils


def tearDownModule():
    isolation.tearDownModule()


class GenerationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = Mock()
        self.client.aio.models.generate_content = AsyncMock(
            return_value=SimpleNamespace(text="[0, 1]"))
        self.addCleanup(patch.stopall)
        patch.object(utils, "LLM_CLIENT", self.client).start()
        patch.object(utils, "FREE_TIER_ONLY", True).start()
        patch.object(utils, "FREE_TIER_MAX_OUTPUT_TOKENS", 400).start()
        patch.object(utils.time, "sleep").start()

    def assert_migrated(self, call, cap):
        self.assertEqual(call.kwargs["model"], "gemini-3.5-flash-lite")
        config = call.kwargs["config"]
        self.assertEqual(config.max_output_tokens, cap)
        self.assertEqual(config.thinking_config.thinking_level, "MINIMAL")
        self.assertIsNone(config.thinking_config.thinking_budget)
        for field in ("temperature", "top_p", "top_k", "candidate_count"):
            self.assertIsNone(getattr(config, field))
            self.assertNotIn(field, call.kwargs)
        self.assertTrue(config.automatic_function_calling.disable)

    def test_sync_uses_new_model_without_sampling_parameters(self):
        utils.generate_content_safe(self.client, "test", temperature=0, top_p=.9,
                                    top_k=20, candidate_count=1, max_output_tokens=4096)
        self.assert_migrated(self.client.models.generate_content.call_args, 400)

    async def test_async_uses_same_config_and_preserves_schema(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        await utils.generate_content_safe_async(self.client, "test", temperature=0,
            top_p=.9, top_k=20, candidate_count=1, max_output_tokens=4096,
            response_mime_type="application/json", response_schema=schema)
        call = self.client.aio.models.generate_content.call_args
        self.assert_migrated(call, 400)
        self.assertEqual(call.kwargs["config"].response_mime_type, "application/json")
        self.assertIsNotNone(call.kwargs["config"].response_schema)

    def test_translation_has_independent_bounded_output_budget(self):
        with patch.object(utils, "FREE_TIER_TRANSLATION_MAX_OUTPUT_TOKENS", 4096):
            utils.generate_content_safe(self.client, "test", translation_once=True,
                                        max_output_tokens=65000, timeout=40)
        call = self.client.models.generate_content.call_args
        self.assert_migrated(call, 4096)
        self.assertEqual(call.kwargs["config"].http_options.retry_options.attempts, 1)
        self.assertEqual(call.kwargs["config"].http_options.timeout, 40000)
        self.client.models.generate_content.assert_called_once()

    async def test_quota_uses_groq_once_without_key_rotation(self):
        self.client.aio.models.generate_content.side_effect = RuntimeError("429 RESOURCE_EXHAUSTED")
        with patch.object(utils, "GROQ_FALLBACK_ENABLED", True), \
             patch.object(utils, "call_groq_backup", AsyncMock(return_value="backup")) as backup, \
             patch.object(utils, "rotate_api_key") as rotate:
            self.assertEqual(await utils.generate_content_safe_async(self.client, "test"), "backup")
        backup.assert_awaited_once_with("test")
        self.client.aio.models.generate_content.assert_awaited_once()
        rotate.assert_not_called()

    async def test_quota_without_fallback_raises(self):
        self.client.aio.models.generate_content.side_effect = RuntimeError("429 RESOURCE_EXHAUSTED")
        with patch.object(utils, "GROQ_FALLBACK_ENABLED", False), \
             self.assertRaises(utils.FreeTierQuotaExceeded):
            await utils.generate_content_safe_async(self.client, "test")
        self.client.aio.models.generate_content.assert_awaited_once()

    async def test_model_setting_reaches_both_wrappers(self):
        with patch.object(utils, "GEMINI_GENERATION_MODEL", "configured-model"):
            utils.generate_content_safe(self.client, "test")
            await utils.generate_content_safe_async(self.client, "test")
        for call in (self.client.models.generate_content.call_args,
                     self.client.aio.models.generate_content.call_args):
            self.assertEqual(call.kwargs["model"], "configured-model")

    async def test_invalid_rankings_do_not_drop_or_duplicate_results(self):
        docs = [{"metadata": {"title": str(i), "pre_summary": "test"}} for i in range(7)]
        for text in ("[-1, 0]", "[0, 0]", "[true, 1]", '["1"]', "[99]", "[]", "not json"):
            self.client.aio.models.generate_content.return_value = SimpleNamespace(text=text)
            with self.subTest(text=text), patch.object(utils, "get_llm_client", return_value=self.client):
                self.assertEqual(await utils.rerank_search_results_async("test", docs), docs)

    async def test_valid_ranking_preserves_unselected_and_remaining_documents(self):
        docs = [{"metadata": {"title": str(i), "pre_summary": "test"}} for i in range(7)]
        self.client.aio.models.generate_content.return_value = SimpleNamespace(text="[2, 0]")
        with patch.object(utils, "get_llm_client", return_value=self.client):
            result = await utils.rerank_search_results_async("test", docs)
        self.assertEqual(result, [docs[i] for i in (2, 0, 1, 3, 4, 5, 6)])

    async def test_missing_client_keeps_all_results(self):
        docs = [{"metadata": {"title": str(i), "pre_summary": "test"}} for i in range(7)]
        with patch.object(utils, "get_llm_client", return_value=None):
            self.assertEqual(await utils.rerank_search_results_async("test", docs), docs)

    async def test_observed_multilingual_categories_are_not_sent_as_db_filters(self):
        # Values observed in the bounded live probe, replayed offline.
        for category in ("childcare", "trợ cấp trẻ em", "아동수당", "null", ["돌봄/양육"]):
            response = SimpleNamespace(text=json.dumps({
                "age": 24, "intent": None, "category": category, "keywords": ["아동수당"]}))
            with self.subTest(category=category), \
                 patch.object(utils, "get_llm_client", return_value=self.client), \
                 patch.object(utils, "redis_async_client", None), \
                 patch.object(utils, "GROQ_FALLBACK_ENABLED", False), \
                 patch.object(utils, "generate_content_safe_async", AsyncMock(return_value=response)):
                info = await utils.extract_info_from_question_async("24개월 아동수당")
                self.assertIsNone(info["category"])
                self.assertEqual(info["age"], 24)
                self.assertEqual(info["keywords"], ["아동수당"])

    async def test_real_db_categories_remain_valid(self):
        for category in utils.DATABASE_IDS:
            response = SimpleNamespace(text=json.dumps({"category": " " + category + " ", "keywords": ["지원"]}))
            with self.subTest(category=category), \
                 patch.object(utils, "get_llm_client", return_value=self.client), \
                 patch.object(utils, "redis_async_client", None), \
                 patch.object(utils, "GROQ_FALLBACK_ENABLED", False), \
                 patch.object(utils, "generate_content_safe_async", AsyncMock(return_value=response)):
                self.assertEqual((await utils.extract_info_from_question_async("지원"))["category"], category)


class SDKWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_serializes_sync_async_and_translation_without_network(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"candidates": [{"content": {
                "role": "model", "parts": [{"text": "[0]"}]}, "finishReason": "STOP"}]})

        transport = httpx.MockTransport(respond)
        with httpx.Client(transport=transport) as sync_http:
            async with httpx.AsyncClient(transport=transport) as async_http:
                client = utils.genai.Client(api_key="offline-test-only", http_options=utils.types.HttpOptions(
                    httpx_client=sync_http, httpx_async_client=async_http))
                try:
                    with patch.object(utils, "LLM_CLIENT", client), patch.object(utils.time, "sleep"), \
                         patch.object(utils, "FREE_TIER_ONLY", True), \
                         patch.object(utils, "FREE_TIER_MAX_OUTPUT_TOKENS", 400), \
                         patch.object(utils, "FREE_TIER_TRANSLATION_MAX_OUTPUT_TOKENS", 4096):
                        self.assertEqual(utils.generate_content_safe(client, "test", temperature=0).text, "[0]")
                        result = await utils.generate_content_safe_async(client, "test", top_p=.9)
                        self.assertEqual(result.text, "[0]")
                        utils.generate_content_safe(client, "test", translation_once=True,
                            response_mime_type="application/json", response_schema={
                                "type": "array", "items": {"type": "integer"}}, max_output_tokens=4096)
                finally:
                    await client.aio.aclose()
                    client.close()
        self.assertEqual(len(requests), 3)
        for request, cap in zip(requests, (400, 400, 4096)):
            self.assertIn("/models/gemini-3.5-flash-lite:generateContent", request.url.path)
            body = json.loads(request.content)
            config = body["generationConfig"]
            self.assertEqual(config["maxOutputTokens"], cap)
            # ProtoJSON accepts both the original proto name and lowerCamelCase.
            self.assertIn(config["thinkingConfig"], (
                {"thinkingLevel": "MINIMAL"}, {"thinking_level": "MINIMAL"}))
            for field in ("temperature", "topP", "topK", "candidateCount"):
                self.assertNotIn(field, config)
            self.assertEqual(body["contents"][-1]["role"], "user")
        self.assertIn("responseSchema", json.loads(requests[-1].content)["generationConfig"])
