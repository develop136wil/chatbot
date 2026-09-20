"""No .env, no external network, no provider tokens or DB mutations."""
import os
import socket
import unittest
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

_scope = ExitStack()


def setUpModule():
    global main, utils, worker, TestClient
    _scope.enter_context(patch.dict(os.environ, {
        "VERCEL_ENV": "production", "SESSION_SECRET_KEY": "offline-test-only",
        "ADMIN_SECRET_KEY": "offline-admin-only", "ENABLE_DEBUG_ENDPOINT": "false",
    }, clear=True))
    _scope.enter_context(patch("dotenv.load_dotenv", return_value=False))
    original_connect = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)  # Windows asyncio self-pipe
        raise AssertionError("External network forbidden")
    _scope.enter_context(patch.object(socket.socket, "connect", connect))
    import main
    import utils
    import worker
    from fastapi.testclient import TestClient


def tearDownModule():
    _scope.close()


def cached():
    return {"status": "complete", "answer": "저장된 답변",
            "last_result_ids": ["p1", "p2", "p3"], "total_found": 3}


class CacheContractTests(unittest.TestCase):
    def test_repeat_with_result_ids_remains_cache_eligible(self):
        for lang in ("ko", "en", "vi", "zh"):
            req = main.ChatRequest(question="아동수당 지급", language=lang,
                last_result_ids=["p1"], shown_count=1,
                chat_history=[{"role": "user", "content": "아동수당 지급"},
                              {"role": "assistant", "content": "답변"}])
            self.assertTrue(main.is_response_cache_read_eligible(req, req.question, lang))
            self.assertFalse(main.is_initial_cacheable_request(req))
            req.action = "more"
            self.assertFalse(main.is_response_cache_read_eligible(req, req.question, lang))

    def test_contextual_followup_does_not_read_shared_cache(self):
        req = main.ChatRequest(question="그 조건은?",
            chat_history=[{"role": "user", "content": "아동수당"},
                          {"role": "assistant", "content": "답변"}])
        self.assertFalse(main.is_response_cache_read_eligible(req, req.question, "ko"))

    def test_language_system_suffix_preserves_repeat_cache_key(self):
        for lang, name in (("en", "English"), ("vi", "Vietnamese"), ("zh", "Chinese")):
            text = "지원 (System: Please answer strictly in " + name + ".)"
            req = main.ChatRequest(question=text, language=lang,
                last_result_ids=["p1"], shown_count=1,
                chat_history=[{"role": "user", "content": "지원"},
                              {"role": "assistant", "content": "answer"}])
            self.assertTrue(main.is_response_cache_read_eligible(req, text, lang))

    def test_languages_still_have_distinct_cache_keys(self):
        keys = {utils.build_response_cache_key("지원", lang) for lang in ("ko","en","vi","zh")}
        self.assertEqual(len(keys), 4)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.rate_limit = self.patches.enter_context(patch.object(main, "check_rate_limit", AsyncMock()))
        self.read = self.patches.enter_context(patch.object(main, "get_response_cache_async", AsyncMock(return_value=None)))
        self.intent = self.patches.enter_context(patch.object(main, "extract_info_from_question_async", AsyncMock(return_value={"intent": "search", "category": None})))
        self.save = self.patches.enter_context(patch.object(main, "save_response_cache_async", AsyncMock()))
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def test_routes_choose_distinct_rate_limit_scopes(self):
        self.read.return_value = cached()
        self.assertEqual(self.client.post("/chat", json={"question": "지원"}).status_code, 200)
        self.assertEqual(self.rate_limit.await_args.kwargs, {"limit": 10, "window": 60, "scope": "chat"})
        with patch.object(main, "notion", None):
            result = self.client.post("/feedback", json={"question": "질문", "answer": "답변",
                                      "job_id": "test-id", "feedback": "👍"})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(self.rate_limit.await_args.kwargs, {"limit": 5, "window": 300, "scope": "feedback"})

    def test_question_limit_accepts_unicode_codepoints_at_boundary(self):
        self.read.return_value = cached()
        for text in ("가" * 2000, "😀" * 2000):
            self.assertEqual(self.client.post("/chat", json={"question": text}).status_code, 200)
        self.intent.assert_not_awaited()

    def test_question_limit_rejects_oversize_before_rate_limit_or_ai(self):
        for text in ("가" * 2001, "😀" * 2001):
            self.assertEqual(self.client.post("/chat", json={"question": text}).status_code, 422)
        self.rate_limit.assert_not_awaited()
        self.intent.assert_not_awaited()

    def test_cache_hit_does_not_call_ai_or_mutate_cached_object(self):
        stored = cached()
        original = deepcopy(stored)
        self.read.return_value = stored
        body = {"question": "지원", "last_result_ids": ["old"], "shown_count": 1,
                "chat_history": [{"role": "user", "content": "지원"},
                                 {"role": "assistant", "content": "이전 답변"}]}
        first = self.client.post("/chat", json=body)
        second = self.client.post("/chat", json=body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["answer"], stored["answer"])
        self.assertNotEqual(first.json()["job_id"], second.json()["job_id"])
        self.assertRegex(first.headers["x-request-id"], r"^[0-9a-f]{32}$")
        self.assertEqual(stored, original)
        self.intent.assert_not_awaited()
        self.save.assert_not_awaited()

    def test_more_without_ids_needs_no_ai_or_cache(self):
        for lang in ("ko", "en", "vi", "zh"):
            result = self.client.post("/chat", json={"question": "next", "action": "more", "language": lang})
            self.assertEqual(result.json()["answer"], utils.LOCALIZED_UI[lang]["no_more"])
        self.intent.assert_not_awaited()
        self.read.assert_not_awaited()

    def test_more_with_ids_uses_existing_paging_contract(self):
        more = {"status": "complete", "answer": "다음 두 개", "last_result_ids": ["a","b","c"], "shown_count": 3}
        with patch.object(main, "build_show_more_response", AsyncMock(return_value=more)) as build:
            response = self.client.post("/chat", json={"question": "더 보여줘", "action": "more",
                "last_result_ids": ["a","b","c"], "shown_count": 2})
        self.assertEqual(response.json(), more)
        self.assertEqual(build.await_args.args[0].shown_count, 2)
        self.intent.assert_not_awaited()

    def test_legacy_client_more_term_needs_no_action_field(self):
        result = self.client.post("/chat", json={"question": "tiếp theo", "language": "vi"})
        self.assertEqual(result.json()["answer"], utils.LOCALIZED_UI["vi"]["no_more"])
        self.intent.assert_not_awaited()

    def test_reset_returns_action_and_is_not_saved(self):
        self.intent.return_value = {"intent": "reset"}
        response = self.client.post("/chat", json={"question": "초기화"})
        self.assertEqual(response.json()["action"], "reset")
        self.assertEqual(response.json()["shown_count"], 0)
        self.save.assert_not_awaited()

    def test_old_cached_reset_still_resets_ui(self):
        self.read.return_value = {"status": "complete", "answer": utils.LOCALIZED_UI["ko"]["reset"]}
        response = self.client.post("/chat", json={"question": "초기화"})
        self.assertEqual(response.json()["action"], "reset")
        self.intent.assert_not_awaited()

    def test_direct_worker_tuple_and_trace_contract_unchanged(self):
        job = AsyncMock(return_value=("정상 답변", ["p1"], 1))
        with patch.object(worker, "process_job_async", job):
            result = self.client.post("/chat", json={"question": "지원"})
        self.assertEqual(result.json()["answer"], "정상 답변")
        self.assertEqual(result.json()["total_found"], 1)
        self.assertEqual(result.json()["job_id"], job.await_args.args[0]["job_id"])
        self.assertEqual(job.await_args.args[0]["trace_id"], result.headers["x-request-id"])
        self.assertTrue(job.await_args.args[0]["cacheable"])
        self.intent.assert_awaited_once()

    def test_error_response_still_has_trace_header(self):
        self.intent.side_effect = RuntimeError("secret failure")
        result = self.client.post("/chat", json={"question": "지원"})
        self.assertEqual(result.json()["status"], "error")
        self.assertRegex(result.headers["x-request-id"], r"^[0-9a-f]{32}$")
        self.assertNotIn("secret failure", result.text)

    def test_feedback_omits_empty_reason_and_handles_null_history(self):
        pages = Mock()
        with patch.object(main, "notion", SimpleNamespace(pages=pages)):
            result = self.client.post("/feedback", json={"question": "질문", "answer": "답변",
                "job_id": "test-id", "feedback": "👍", "chat_history": None, "comment": None})
        self.assertEqual(result.json()["status"], "success")
        props = pages.create.call_args.kwargs["properties"]
        self.assertNotIn("사유", props)
        self.assertEqual(props["대화내역"]["rich_text"][0]["text"]["content"], "")

    def test_feedback_failure_is_not_success(self):
        pages = Mock()
        pages.create.side_effect = RuntimeError("do not expose")
        with patch.object(main, "notion", SimpleNamespace(pages=pages)):
            result = self.client.post("/feedback", json={"question": "질문", "answer": "답변",
                "job_id": "test-id", "feedback": "👎"})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("do not expose", result.text)

class WorkerContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_keeps_tuple_and_existing_calls_with_trace(self):
        from observability import timed_async, current_request_id
        row = {"metadata": {"page_id": "p1", "title": "제목", "category": "돌봄/양육"}}
        expansion = AsyncMock(return_value=["지원"])
        search = AsyncMock(return_value=[row])
        rerank = AsyncMock(return_value=[row])
        localize = AsyncMock(return_value=[row])
        save = AsyncMock()
        with ExitStack() as patches:
            for name, stage, target in (
                ("expand_search_query_async", "keyword_expansion", expansion),
                ("search_supabase_async", "search", search),
                ("rerank_search_results_async", "rerank", rerank),
                ("localize_result_pages_async", "localization", localize),
                ("save_response_cache_async", "cache_write", save)):
                patches.enter_context(patch.object(worker, name, timed_async(stage)(target)))
            patches.enter_context(patch.object(worker, "format_search_results", return_value="카드"))
            with self.assertLogs("chatbot.performance", level="INFO") as logs:
                result = await worker.process_job_async({"question":"지원","language":"ko",
                    "trace_id":"c"*32,"cacheable":True})
        self.assertIsInstance(result, tuple)
        self.assertEqual(result[1:], (["p1"], 1))
        for call in (expansion, search, rerank, localize, save):
            call.assert_awaited_once()
        self.assertEqual(len(logs.records), 6)
        self.assertTrue(all("c"*32 in record.getMessage() for record in logs.records))
        self.assertIsNone(current_request_id())

class UXFailureTests(unittest.IsolatedAsyncioTestCase):
    def db(self, data=None, error=None):
        query = Mock()
        query.execute.return_value = SimpleNamespace(data=data or [])
        query.execute.side_effect = error
        db = Mock()
        db.rpc.return_value = query
        return db

    async def test_failed_search_is_not_empty_results(self):
        db = self.db(error=RuntimeError("offline"))
        with patch.object(utils,"supabase_async",db), patch.object(utils,"get_gemini_embedding_async",AsyncMock(return_value=[0.1])):
            with self.assertRaises(utils.SearchUnavailable):
                await utils.search_supabase_async("지원", {}, keywords=["지원"])

    async def test_missing_embedding_is_search_failure(self):
        db = self.db()
        with patch.object(utils,"supabase_async",db), patch.object(utils,"get_gemini_embedding_async",AsyncMock(return_value=None)):
            with self.assertRaises(utils.SearchUnavailable):
                await utils.search_supabase_async("지원", {}, keywords=["지원"])
        db.rpc.assert_not_called()

    async def test_category_failure_can_recover_with_global_search(self):
        row = {"id":1,"metadata":{"page_id":"p1","title":"지원"}}
        db = self.db()
        db.rpc.return_value.execute.side_effect = [RuntimeError("category failed"),SimpleNamespace(data=[row])]
        with patch.object(utils,"supabase_async",db), patch.object(utils,"get_gemini_embedding_async",AsyncMock(return_value=[0.1])):
            result = await utils.search_supabase_async("지원", {"category":"돌봄/양육"}, keywords=["지원"])
        self.assertEqual(result,[row])
        self.assertEqual(db.rpc.call_count,2)

    async def test_successful_empty_search_remains_empty(self):
        with patch.object(utils,"supabase_async",self.db()), patch.object(utils,"get_gemini_embedding_async",AsyncMock(return_value=[0.1])):
            self.assertEqual(await utils.search_supabase_async("지원", {}, keywords=["지원"]),[])

    async def test_failed_fallback_does_not_cache_partial_result_as_complete(self):
        db = self.db()
        db.rpc.return_value.execute.side_effect = [SimpleNamespace(data=[{"id":1}]),RuntimeError("fallback failed")]
        with patch.object(utils,"supabase_async",db), patch.object(utils,"get_gemini_embedding_async",AsyncMock(return_value=[0.1])):
            with self.assertRaises(utils.SearchUnavailable):
                await utils.search_supabase_async("지원", {"category":"돌봄/양육"}, keywords=["지원"])

    async def test_worker_failure_is_not_saved_as_not_found(self):
        with patch.object(worker,"expand_search_query_async",AsyncMock(return_value=["지원"])), patch.object(worker,"search_supabase_async",AsyncMock(side_effect=utils.SearchUnavailable())), patch.object(worker,"save_response_cache_async",AsyncMock()) as save:
            with self.assertRaises(utils.SearchUnavailable):
                await worker.process_job_async({"question":"지원","language":"ko","cacheable":True})
        save.assert_not_awaited()

    async def test_worker_empty_result_is_not_cached(self):
        with patch.object(worker,"expand_search_query_async",AsyncMock(return_value=["지원"])), patch.object(worker,"search_supabase_async",AsyncMock(return_value=[])), patch.object(worker,"save_response_cache_async",AsyncMock()) as save:
            result = await worker.process_job_async({"question":"지원","language":"ko","cacheable":True})
        self.assertEqual(result,(utils.LOCALIZED_UI["ko"]["not_found"],[],0))
        save.assert_not_awaited()

    async def test_more_lookup_failure_propagates(self):
        with patch.object(utils,"supabase",None):
            with self.assertRaises(utils.SearchUnavailable):
                await utils.get_supabase_pages_by_ids_async(["p1"])

    async def test_missing_more_documents_preserve_error_not_empty_success(self):
        req=main.ChatRequest(question="more",action="more",last_result_ids=["p1"],shown_count=0)
        with patch.object(main,"get_supabase_pages_by_ids_async",AsyncMock(return_value=[])):
            result=await main.build_show_more_response(req,"en")
        self.assertEqual(result["status"],"error")
        self.assertEqual(result["code"],"results_changed")
        self.assertFalse(result["retryable"])

    async def test_translation_fallback_has_notice_without_ai_or_mutation(self):
        source=[{"metadata":{"title":"원문","pre_summary":"원문 요약","category":"돌봄/양육"}}]
        original=deepcopy(source)
        with patch.object(utils,"LIVE_TRANSLATION_ENABLED",False), patch.object(utils,"translate_content_simple_async",AsyncMock()) as translate:
            for lang in ("en","vi","zh"):
                result=await utils.localize_result_pages_async(source,lang)
                self.assertTrue(result[0]["metadata"]["_translation_missing"])
                rendered=utils.format_search_results([result[0]["metadata"]],lang)
                self.assertIn(utils.LOCALIZED_UI[lang]["translation_notice"],rendered)
        translate.assert_not_called()
        self.assertEqual(source,original)

    async def test_pretranslated_content_needs_no_fallback_notice(self):
        rows=[{"metadata":{"title":"원문","title_en":"Title","pre_summary":"원문","pre_summary_en":"Summary","category":"돌봄/양육"}}]
        with patch.object(utils,"LIVE_TRANSLATION_ENABLED",False):
            result=await utils.localize_result_pages_async(rows,"en")
        self.assertEqual(result[0]["metadata"]["title"],"Title")
        self.assertNotIn("_translation_missing",result[0]["metadata"])

    async def test_queued_failure_is_localized_error(self):
        import asyncio, json
        redis=SimpleNamespace(setex=AsyncMock())
        semaphore=asyncio.Semaphore(1)
        await semaphore.acquire()
        payload=json.dumps({"job_id":"job","question":"q","language":"vi"}).encode()
        with patch.object(worker,"process_job_async",AsyncMock(side_effect=utils.SearchUnavailable())):
            await worker.handle_job(redis,("queue",payload),semaphore)
        stored=json.loads(redis.setex.await_args.args[2])
        self.assertEqual(stored["status"],"error")
        self.assertEqual(stored["code"],"search_unavailable")
        self.assertEqual(stored["message"],utils.LOCALIZED_UI["vi"]["system_error"])
        self.assertEqual(semaphore._value,1)


class UXContentTests(unittest.TestCase):
    def test_legacy_empty_and_error_caches_are_rejected(self):
        for answer in utils.LEGACY_EMPTY_ANSWERS + utils.LEGACY_ERROR_ANSWERS:
            self.assertFalse(utils._is_valid_cached_response({"status":"complete","answer":answer}))
        self.assertTrue(utils._is_valid_cached_response(cached()))

    def test_source_and_real_date_labels_in_all_languages(self):
        meta={"title":"자료","category":"분류","pre_summary":"대상: 아이","page_url":"https://example.test/source","last_edited_time":"2026-08-02T10:00:00Z"}
        for lang in ("ko","en","vi","zh"):
            html=utils.format_search_results([meta],lang)
            self.assertIn(utils.LOCALIZED_UI[lang]["source_label"],html)
            self.assertIn("2026-08-02",html)
            self.assertIn(utils.LOCALIZED_UI[lang]["date_note"],html)

    def test_missing_or_invalid_dates_are_not_invented(self):
        for date in (None,"bad","<script>evil</script>"):
            html=utils.format_search_results([{"title":"title","pre_summary":"body","last_edited_time":date}],"ko")
            self.assertNotIn("자료 수정:",html)
            self.assertNotIn("<script>",html)

    def test_unsafe_card_text_and_url_are_not_executable(self):
        html=utils.format_search_results([{"title":"<script>evil</script>","pre_summary":"body","page_url":"javascript:alert(1)"}],"ko")
        self.assertNotIn("<script>",html)
        self.assertNotIn('href="javascript:',html)


class UXRouteTests(unittest.TestCase):
    setUp = RouteTests.setUp
    def test_direct_failure_is_error_not_complete(self):
        with patch.object(worker,"process_job_async",AsyncMock(side_effect=utils.SearchUnavailable())):
            result=self.client.post("/chat",json={"question":"지원","language":"zh"})
        self.assertEqual(result.json()["status"],"error")
        self.assertEqual(result.json()["code"],"search_unavailable")
        self.assertEqual(result.json()["message"],utils.LOCALIZED_UI["zh"]["system_error"])

    def test_worker_provider_limit_has_no_immediate_retry(self):
        with patch.object(worker,"process_job_async",AsyncMock(side_effect=utils.FreeTierQuotaExceeded())):
            result=self.client.post("/chat",json={"question":"지원","language":"en"})
        self.assertEqual(result.json()["code"],"provider_limit")
        self.assertFalse(result.json()["retryable"])
        self.assertNotIn("Today's",result.json()["message"])

    def test_static_copy_is_served_without_database_access(self):
        result=self.client.get("/static/ui-text.js")
        self.assertEqual(result.status_code,200)
        self.assertIn("CHAT_UI_TEXT",result.text)
        self.intent.assert_not_awaited()
        self.read.assert_not_awaited()

class UXWorkerAdditionalTests(unittest.IsolatedAsyncioTestCase):
    async def test_format_failure_is_not_cached_as_success(self):
        row={"metadata":{"page_id":"p1","title":"지원","category":"돌봄/양육"}}
        with ExitStack() as patches:
            for name,value in (("expand_search_query_async",["지원"]),("search_supabase_async",[row]),
                               ("rerank_search_results_async",[row]),("localize_result_pages_async",[row])):
                patches.enter_context(patch.object(worker,name,AsyncMock(return_value=value)))
            patches.enter_context(patch.object(worker,"format_search_results",side_effect=ValueError("bad format")))
            save=patches.enter_context(patch.object(worker,"save_response_cache_async",AsyncMock()))
            with self.assertRaises(utils.JobProcessingError):
                await worker.process_job_async({"question":"지원","language":"ko","cacheable":True})
        save.assert_not_awaited()

    async def test_embedding_quota_stays_quota_error(self):
        with patch.object(worker,"expand_search_query_async",AsyncMock(return_value=["지원"])), patch.object(worker,"search_supabase_async",AsyncMock(side_effect=utils.FreeTierQuotaExceeded())):
            with self.assertRaises(utils.FreeTierQuotaExceeded):
                await worker.process_job_async({"question":"지원","language":"ko"})


class DeploymentIntegrationTests(unittest.TestCase):
    setUp = RouteTests.setUp

    def test_vercel_entrypoint_startup_and_page_assets(self):
        import importlib
        import re
        from urllib.parse import quote, urljoin
        entry = importlib.import_module("api.index")
        self.assertIs(entry.app, main.app)
        with patch.object(main, "BackgroundScheduler", side_effect=AssertionError("No scheduler")), \
                TestClient(entry.app) as client:
            self.assertEqual(client.get("/health").json()["status"], "ok")
            self.assertEqual(client.get("/debug").status_code, 404)
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn('content="only light"', home.text)
            assets = set(re.findall(r'(?:src|href)="(/static/[^"]+)"', home.text))
            css = client.get("/static/style.css").text
            for asset in re.findall(r'url\(["\']?([^)"\']+)["\']?\)', css):
                if not asset.startswith(("https:", "http:", "data:")):
                    assets.add(urljoin("/static/style.css", asset))
            manifest = client.get("/static/manifest.json").json()
            assets.update(icon["src"] for icon in manifest["icons"])
            for asset in assets:
                with self.subTest(asset=asset):
                    response = client.get(quote(asset, safe="/?=&%."))
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.content)
        self.intent.assert_not_awaited()
        self.read.assert_not_awaited()

    def test_four_language_first_repeat_cache_and_more_without_extra_ai(self):
        rows = []
        for i in range(3):
            meta = {"page_id": f"p{i}", "title": f"자료 {i}",
                    "category": "돌봄/양육", "pre_summary": "지원 내용: 테스트 안내",
                    "page_url": f"https://example.org/p{i}"}
            for lang in ("en", "vi", "zh"):
                meta[f"title_{lang}"] = f"{lang} document {i}"
                meta[f"pre_summary_{lang}"] = f"{lang} prepared summary"
            rows.append({"metadata": meta})

        for lang in ("ko", "en", "vi", "zh"):
            with self.subTest(language=lang), ExitStack() as patches:
                self.client.cookies.clear()
                self.intent.reset_mock()
                memory = {}
                async def read(question, language):
                    return deepcopy(memory.get(utils.build_response_cache_key(question, language)))
                async def save(question, language, response, **kwargs):
                    memory[utils.build_response_cache_key(question, language)] = deepcopy(response)
                self.read.side_effect = read
                saved = patches.enter_context(patch.object(worker, "save_response_cache_async", AsyncMock(side_effect=save)))
                expansion = patches.enter_context(patch.object(worker, "expand_search_query_async", AsyncMock(return_value=["지원"])))
                search = patches.enter_context(patch.object(worker, "search_supabase_async", AsyncMock(return_value=deepcopy(rows))))
                ranking = patches.enter_context(patch.object(worker, "rerank_search_results_async", AsyncMock(return_value=deepcopy(rows))))
                lookup = patches.enter_context(patch.object(main, "get_supabase_pages_by_ids_async", AsyncMock(return_value=[deepcopy(rows[2]["metadata"])])))
                patches.enter_context(patch.object(worker, "NOTION_QUERY_LOGS_ENABLED", False))
                patches.enter_context(patch.object(utils, "LIVE_TRANSLATION_ENABLED", False))
                patches.enter_context(patch.object(main, "FREE_TIER_DAILY_REQUESTS_PER_SESSION", 1))
                patches.enter_context(patch.object(main, "FREE_TIER_ONLY", True))
                first = self.client.post("/chat", json={"question": "지원", "language": lang})
                self.assertEqual(first.status_code, 200)
                initial = first.json()
                self.assertEqual(initial["status"], "complete")
                self.assertEqual(initial["total_found"], 3)
                self.assertEqual(initial["answer"].count('class="result-card"'), 2)
                repeat = self.client.post("/chat", json={
                    "question": "지원", "language": lang,
                    "last_result_ids": initial["last_result_ids"], "shown_count": 2,
                    "chat_history": [{"role": "user", "content": "지원"},
                                     {"role": "assistant", "content": initial["answer"]}]})
                repeated = repeat.json()
                self.assertEqual(repeated["answer"], initial["answer"])
                self.assertNotEqual(repeated["job_id"], initial["job_id"])
                more = self.client.post("/chat", json={
                    "question": "next", "action": "more", "language": lang,
                    "last_result_ids": initial["last_result_ids"], "shown_count": 2}).json()
                self.assertEqual(more["status"], "complete")
                self.assertEqual(more["shown_count"], 3)
                expected = "자료 2" if lang == "ko" else f"{lang} document 2"
                self.assertIn(expected, more["answer"])
                self.assertEqual(more["answer"].count('class="result-card"'), 1)
                lookup.assert_awaited_once_with(["p2"])
                for call in (self.intent, expansion, search, ranking, saved):
                    call.assert_awaited_once()
                self.assertEqual(len(memory), 1)
                exhausted = self.client.post("/chat", json={"question": "다른 지원", "language": lang}).json()
                self.assertEqual(exhausted["code"], "daily_limit")
                self.intent.assert_awaited_once()

    def test_actual_worker_search_error_and_empty_result_are_distinct(self):
        with patch.object(worker, "expand_search_query_async", AsyncMock(return_value=["지원"])), \
                patch.object(worker, "search_supabase_async", AsyncMock(side_effect=[utils.SearchUnavailable(), []])), \
                patch.object(worker, "save_response_cache_async", AsyncMock()) as save:
            failed = self.client.post("/chat", json={"question": "지원"}).json()
            empty = self.client.post("/chat", json={"question": "지원"}).json()
        self.assertEqual(failed["status"], "error")
        self.assertEqual(failed["code"], "search_unavailable")
        self.assertEqual(empty["status"], "complete")
        self.assertEqual(empty["answer"], utils.LOCALIZED_UI["ko"]["not_found"])
        self.assertEqual(empty["total_found"], 0)
        save.assert_not_awaited()
