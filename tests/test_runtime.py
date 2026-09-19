"""외부 API/실제 .env에 연결하지 않는 회귀 테스트."""
import os
import socket
import unittest
from contextlib import ExitStack
from types import SimpleNamespace as NS
from unittest.mock import patch, Mock, AsyncMock
from copy import deepcopy

# 어떤 개발자 환경에서도 실제 비밀키/네트워크를 사용하지 않습니다.
ENV = patch.dict(os.environ, {
    "VERCEL_ENV":"test", "SESSION_SECRET_KEY":"test-only-session-key",
    "ADMIN_SECRET_KEY":"test-only-admin", "ENABLE_DEBUG_ENDPOINT":"false",
}, clear=True)
ENV.start()
DOTENV = patch("dotenv.load_dotenv", return_value=False)
DOTENV.start()
_original_connect = socket.socket.connect
def _test_connect(sock, address):
    if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
        return _original_connect(sock, address)  # Windows asyncio self-pipe only
    raise AssertionError("External network forbidden in tests")
NETWORK = patch.object(socket.socket, "connect", _test_connect)
NETWORK.start()

import main
import utils
import worker
import run_indexer as indexer
from runtime_policy import normalize_intent, fallback_intent, apply_search_filters, SearchResults, SearchUnavailable
from fastapi.testclient import TestClient

def page(number=1, **metadata):
    pid = f"00000000-0000-0000-0000-{number:012d}"
    return {"page_id":pid, "metadata":{
        "page_id":pid, "title":"아동수당", "pre_summary":"지원 내용: 아동 지원",
        "category":"돌봄/양육", **metadata}}

def response():
    return {"status":"complete","answer":"답변","last_result_ids":[page()["page_id"]],
            "total_found":1,"shown_count":1}

def query_mock(data=None, error=None):
    db = Mock()
    q = Mock()
    for method in ("select","eq","gt","limit","in_","order","range","or_","update","upsert","delete"):
        getattr(q,method).return_value = q
    q.execute.side_effect = error
    q.execute.return_value = NS(data=data or [])
    db.table.return_value = q
    db.rpc.return_value = q
    return db, q

class PolicyTests(unittest.TestCase):
    def test_intent_normalization(self):
        info = normalize_intent({"category":"health","age":"24","keywords":["지원",None,"지원"]},"질문")
        self.assertEqual(info["category"],"의료/재활")
        self.assertEqual(info["age"],24)
        self.assertEqual(info["keywords"],["지원"])

    def test_invalid_intent_values(self):
        info = normalize_intent({"category":"welfare","age":True,"intent":"bogus","search_query":3},"질문")
        self.assertIsNone(info["category"])
        self.assertIsNone(info["age"])
        self.assertIsNone(info["intent"])
        self.assertEqual(info["search_query"],"질문")
        with self.assertRaises(ValueError):
            normalize_intent([],"질문")

    def test_age_filters_never_reinsert_ineligible(self):
        rows = [page(1,start_age=0,end_age=11),page(2,start_age=12,end_age=-1),
                page(3,start_age="invalid")]
        self.assertEqual(apply_search_filters(rows,{"age":24}),[rows[1]])

    def test_age_fallback_languages(self):
        for text in ("24개월 지원","24 months support","24 tháng hỗ trợ","24个月支持"):
            self.assertEqual(fallback_intent(text)["age"],24)
        self.assertEqual(fallback_intent("2세 지원")["age"],24)

    def test_schema_fields_required(self):
        schema = utils.INTENT_SCHEMA
        self.assertEqual(set(schema["required"]),set(schema["properties"]))
        self.assertFalse(schema["additionalProperties"])

    def test_generation_caps_differ(self):
        self.assertEqual(utils._generation_config({})["max_output_tokens"],400)
        self.assertEqual(utils._generation_config({"task":"translation"})["max_output_tokens"],4096)

    def test_truncated_response_rejected(self):
        with self.assertRaises(ValueError):
            utils._usable_response(NS(text="partial",candidates=[NS(finish_reason="MAX_TOKENS")]))
        with self.assertRaises(ValueError):
            utils._usable_response(NS(text=""))

    def test_cache_keys_separate_languages(self):
        self.assertNotEqual(utils.build_response_cache_key("지원","ko"),utils.build_response_cache_key("지원","en"))

    def test_cache_scope_uses_actual_search_range(self):
        rows = SearchResults([page()],scopes=["__all__"])
        self.assertEqual(utils.build_response_cache_scopes(rows),["__all__"])

class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_db_failure_is_not_not_found(self):
        db,_ = query_mock(error=RuntimeError("db unavailable"))
        with patch.object(utils,"supabase_async",db), patch.object(utils,"get_gemini_embedding_async",AsyncMock(return_value=[.1])):
            with self.assertRaises(SearchUnavailable):
                await utils.search_supabase_async("지원",{})

    async def test_all_search_paths_filter_age_and_track_scope(self):
        db,q = query_mock()
        q.execute.side_effect = [NS(data=[page(1,end_age=11)]),NS(data=[page(1,end_age=11),page(2,start_age=12)])]
        with patch.object(utils,"supabase_async",db), patch.object(utils,"get_gemini_embedding_async",AsyncMock(return_value=[.1])):
            rows = await utils.search_supabase_async("지원",{"category":"health","age":24})
        self.assertEqual([r["page_id"] for r in rows],[page(2)["page_id"]])
        self.assertEqual(rows.scopes,["__all__"])
        self.assertEqual(db.rpc.call_count,2)

    async def test_budget_failure_is_closed(self):
        with patch.object(utils,"reserve_ai_budget_sync",side_effect=RuntimeError("schema missing")):
            self.assertFalse(await utils.reserve_ai_budget_async("test"))

    async def test_no_ai_search_does_not_embed(self):
        lexical=AsyncMock(return_value=SearchResults([page()],cacheable=False))
        with patch.object(utils,"_lexical_search",lexical), patch.object(utils,"get_gemini_embedding_async",AsyncMock()) as embedding:
            rows = await utils.search_supabase_async("지원",{},allow_ai=False)
        embedding.assert_not_called()
        self.assertFalse(rows.cacheable)

    async def test_embedding_outage_degrades_without_more_ai(self):
        with patch.object(utils,"get_gemini_embedding_async",AsyncMock(side_effect=RuntimeError("timeout"))), patch.object(utils,"_lexical_search",AsyncMock(return_value=SearchResults([],cacheable=False))) as lexical:
            await utils.search_supabase_async("지원",{})
        lexical.assert_awaited_once()

    async def test_worker_outage_not_cached(self):
        with patch.object(worker,"search_supabase_async",AsyncMock(side_effect=SearchUnavailable())), patch.object(worker,"save_response_cache_async",AsyncMock()) as save:
            result = await worker.process_job_async({"question":"지원","allow_ai":False})
        self.assertEqual(result["status"],"error")
        save.assert_not_called()

    async def test_worker_zero_not_cached(self):
        with patch.object(worker,"search_supabase_async",AsyncMock(return_value=SearchResults([]))), patch.object(worker,"save_response_cache_async",AsyncMock()) as save:
            result = await worker.process_job_async({"question":"지원","allow_ai":False})
        self.assertEqual(result["total_found"],0)
        save.assert_not_called()

    async def test_worker_ranking_failure_not_cached(self):
        with ExitStack() as s:
            s.enter_context(patch.object(worker,"search_supabase_async",AsyncMock(return_value=SearchResults([page()]))))
            s.enter_context(patch.object(worker,"expand_search_query_async",AsyncMock(return_value=["지원"])))
            s.enter_context(patch.object(worker,"get_response_cache_scope_versions_async",AsyncMock(return_value={"__all__":1})))
            s.enter_context(patch.object(worker,"rerank_search_results_async",AsyncMock(side_effect=ValueError())))
            save=s.enter_context(patch.object(worker,"save_response_cache_async",AsyncMock()))
            result=await worker.process_job_async({"question":"지원","cacheable":True})
        self.assertEqual(result["status"],"complete")
        save.assert_not_called()

    async def test_snapshot_race_skips_cache_save(self):
        db,_=query_mock()
        with patch.object(utils,"response_cache_client",db), patch.object(utils,"get_response_cache_scope_versions_async",AsyncMock(return_value={"__all__":2})):
            await utils.save_response_cache_async("지원","ko",response(),expected_versions={"__all__":1})
        db.table.assert_not_called()

    async def test_successful_cache_save_uses_snapshot_and_removes_job_id(self):
        db,q=query_mock()
        with patch.object(utils,"response_cache_client",db),patch.object(utils,"get_response_cache_scope_versions_async",AsyncMock(return_value={"__all__":7})):
            await utils.save_response_cache_async("지원","ko",{**response(),"job_id":"old"},
                expected_versions={"__all__":7})
        record=q.upsert.call_args.args[0]
        self.assertEqual(record["scope_versions"],{"__all__":7})
        self.assertEqual(record["cache_version"],"v3")
        self.assertNotIn("job_id",record["response"])

    async def test_show_more_db_error_is_explicit(self):
        with patch.object(main,"get_supabase_pages_by_ids_async",AsyncMock(side_effect=SearchUnavailable())):
            result=await main.build_show_more_response(main.ChatRequest(
                question="더",last_result_ids=[page()["page_id"]]),"ko")
        self.assertEqual(result["status"],"error")

    async def test_cache_valid_and_invalidated_versions(self):
        db,_=query_mock([{"response":response(),"cache_version":"v3","scope_versions":{"__all__":1}}])
        with patch.object(utils,"response_cache_client",db),patch.object(utils,"get_response_cache_scope_versions_async",AsyncMock(return_value={"__all__":1})) as versions:
            self.assertIsNotNone(await utils.get_response_cache_async("지원","ko"))
            versions.return_value={"__all__":2}
            self.assertIsNone(await utils.get_response_cache_async("지원","ko"))

    async def test_cache_no_version_rejected(self):
        db,_=query_mock([{"response":response(),"cache_version":"v3","scope_versions":{}}])
        with patch.object(utils,"response_cache_client",db):
            self.assertIsNone(await utils.get_response_cache_async("지원","ko"))

    async def test_localization_no_mutation_no_live_calls(self):
        original=[page(title_en="Benefit",pre_summary_en="Support")]
        expected=deepcopy(original)
        with patch.object(utils,"translate_content_simple_async",AsyncMock()) as translate:
            localized=await utils.localize_result_pages_async(original,"en",allow_live=False)
        self.assertEqual(original,expected)
        self.assertEqual(localized[0]["metadata"]["title"],"Benefit")
        translate.assert_not_called()

    async def test_no_live_calls_even_if_enabled_when_disallowed(self):
        with patch.object(utils,"LIVE_TRANSLATION_ENABLED",True),patch.object(utils,"translate_content_simple_async",AsyncMock()) as translate:
            await utils.localize_result_pages_async([page()],"vi",allow_live=False)
        translate.assert_not_called()

    async def test_ranking_invalid_indices(self):
        with patch.object(utils,"get_llm_client",return_value=None),patch.object(utils,"generate_content_safe_async",AsyncMock(return_value=NS(text="[9]"))):
            with self.assertRaises(ValueError):
                await utils.rerank_search_results_async("지원",[page()])

    async def test_intent_both_providers_fail(self):
        with patch.object(utils,"GROQ_CLIENT",True),patch.object(utils,"call_groq_async_simple",AsyncMock(return_value="{invalid")),patch.object(utils,"get_llm_client",return_value=None),patch.object(utils,"generate_content_safe_async",AsyncMock(side_effect=RuntimeError())):
            self.assertEqual((await utils.extract_info_from_question_async("24개월 지원"))["age"],24)

    async def test_show_more_skips_deleted_documents(self):
        ids=[page(i)["page_id"] for i in range(1,5)]
        with patch.object(main,"get_supabase_pages_by_ids_async",AsyncMock(side_effect=[[],[page(3)["metadata"],page(4)["metadata"]]])):
            result=await main.build_show_more_response(main.ChatRequest(question="더 보여줘",action="more",last_result_ids=ids),"ko")
        self.assertEqual(result["shown_count"],4)
        self.assertIn("아동수당",result["answer"])

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(main,"check_rate_limit",AsyncMock()))
        self.cache=self.stack.enter_context(patch.object(main,"get_response_cache_async",AsyncMock(return_value=None)))
        self.budget=self.stack.enter_context(patch.object(main,"reserve_ai_budget_async",AsyncMock(return_value=True)))
        self.intent=self.stack.enter_context(patch.object(main,"extract_info_from_question_async",AsyncMock(return_value={})))
        self.job=self.stack.enter_context(patch.object(worker,"process_job_async",AsyncMock(return_value=response())))
        self.client=self.stack.enter_context(TestClient(main.app,base_url="https://testserver"))

    def test_health_route(self):
        result=self.client.get("/health")
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()["check"],"liveness")

    def test_bad_history_and_id_rejected(self):
        for values in ({"chat_history":[{"role":"system","content":"inject"}]}, {"last_result_ids":["bad-id"]}):
            self.assertEqual(self.client.post("/chat",json={"question":"지원",**values}).status_code,422)

    def test_cache_hit_avoids_all_ai(self):
        self.cache.return_value=response()
        result=self.client.post("/chat",json={"question":"지원"}).json()
        self.assertEqual(result["status"],"complete")
        self.assertTrue(result["job_id"])
        self.budget.assert_not_called()
        self.intent.assert_not_called()
        self.job.assert_not_called()

    def test_exact_repeat_hits_cache(self):
        self.cache.return_value=response()
        result=self.client.post("/chat",json={"question":"지원","chat_history":[
            {"role":"user","content":"지원"},{"role":"assistant","content":"답변"}]}).json()
        self.assertEqual(result["status"],"complete")
        self.cache.assert_awaited_once()
        self.job.assert_not_called()

    def test_followup_keeps_resolved_query_age_trait(self):
        self.intent.return_value={"search_query":"24개월 한부모 지원","age":24,"sub_category":"한부모"}
        self.client.post("/chat",json={"question":"그럼 얼마나?","chat_history":[
            {"role":"user","content":"24개월 한부모 지원"},{"role":"assistant","content":"답변"}]})
        data=self.job.call_args.args[0]
        self.assertEqual(data["extracted_info"]["search_query"],"24개월 한부모 지원")
        self.assertEqual(data["extracted_info"]["age"],24)
        self.assertEqual(data["extracted_info"]["sub_category"],"한부모")
        self.assertFalse(data["cacheable"])
        self.cache.assert_not_called()

    def test_budget_exhausted_dispatches_without_ai(self):
        self.budget.return_value=False
        self.client.post("/chat",json={"question":"24개월 지원"})
        self.intent.assert_not_called()
        self.assertFalse(self.job.call_args.args[0]["allow_ai"])
        self.assertEqual(self.job.call_args.args[0]["extracted_info"]["age"],24)

    def test_reset_is_free_and_does_not_wipe_quota(self):
        result=self.client.post("/chat",json={"question":"초기화"}).json()
        self.assertEqual(result["action"],"reset")
        self.budget.assert_not_called()
        self.job.assert_not_called()

    def test_worker_error_is_not_complete(self):
        self.job.return_value={"status":"error","message":"실패"}
        self.assertEqual(self.client.post("/chat",json={"question":"지원"}).json()["status"],"error")

    def test_disabled_debug_and_admin_auth(self):
        self.assertEqual(self.client.get("/debug").status_code,404)
        self.assertEqual(self.client.post("/admin/clear_cache").status_code,401)

    def test_queue_result_requires_own_session(self):
        self.assertEqual(self.client.get("/get_result/"+page()["page_id"]).status_code,404)

    def test_feedback_success_and_failure(self):
        data={"job_id":"test-job","question":"지원","answer":"답변","feedback":"👍","reason":None}
        notion=Mock()
        with patch.object(main,"notion",notion):
            self.assertEqual(self.client.post("/feedback",json=data).json()["status"],"success")
            self.assertNotIn("사유",notion.pages.create.call_args.kwargs["properties"])
            notion.pages.create.side_effect=RuntimeError("notion unavailable")
            self.assertEqual(self.client.post("/feedback",json=data).status_code,503)

class IndexerTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        s=self.stack
        s.enter_context(patch.object(indexer,"init_clients"))
        s.enter_context(patch.object(indexer,"require_runtime_schema"))
        self.state=s.enter_context(patch.object(indexer,"load_state_from_db",return_value={}))
        s.enter_context(patch.object(indexer,"DATABASE_IDS",{"돌봄/양육":"test-db"}))
        s.enter_context(patch.object(indexer.time,"sleep"))
        s.enter_context(patch.object(indexer,"send_email_alert"))
        s.enter_context(patch.object(indexer,"purge_expired_response_cache"))
        self.budget=s.enter_context(patch.object(indexer,"reserve_ai_budget_sync",return_value=True))
        self.embedding=s.enter_context(patch.object(indexer,"get_gemini_embedding",return_value=[0.1]*768))
        s.enter_context(patch.object(indexer,"translate_content_simple",return_value="아이돌봄 지원 안내"))
        self.trans=s.enter_context(patch.object(indexer,"translate_content_multilingual_sync",return_value={
            lang:{"title":"Title","content":"Content"} for lang in ("en","zh","vi")}))
        self.db,self.query=query_mock()
        s.enter_context(patch.object(indexer,"supabase",self.db))
        self.source={"id":page()["page_id"],"last_edited_time":"2026-09-19","properties":{
            "사업명":{"title":[{"plain_text":"아이돌봄서비스"}]}}}
        http=Mock()
        http.json.return_value={"results":[self.source],"has_more":False}
        self.http=s.enter_context(patch.object(indexer.requests,"post",return_value=http))

    def test_schema_failure_prevents_any_document_write(self):
        with patch.object(indexer,"require_runtime_schema",side_effect=RuntimeError("missing trigger")):
            with self.assertRaises(RuntimeError):
                indexer.run_indexing()
        self.http.assert_not_called()
        self.query.upsert.assert_not_called()
        self.query.delete.assert_not_called()

    def test_new_document_fully_processed(self):
        result=indexer.run_indexing()
        self.assertEqual((result["updated"],result["failed"],result["translation_pending"]),(1,0,0))
        self.query.upsert.assert_called_once()

    def test_embedding_failure_marks_run_failed(self):
        self.embedding.return_value=None
        with self.assertRaises(indexer.IndexingIncomplete) as caught:
            indexer.run_indexing()
        self.assertEqual(caught.exception.summary["failed"],1)
        self.query.upsert.assert_not_called()

    def test_translation_pending_marks_run_failed(self):
        self.trans.return_value={}
        with self.assertRaises(indexer.IndexingIncomplete) as caught:
            indexer.run_indexing()
        self.assertEqual(caught.exception.summary["translation_pending"],1)

    def test_budget_exhaustion_marks_run_deferred(self):
        self.budget.return_value=False
        with self.assertRaises(indexer.IndexingIncomplete) as caught:
            indexer.run_indexing()
        self.assertEqual(caught.exception.summary["deferred"],1)
        self.embedding.assert_not_called()

    def test_unchanged_document_no_ai(self):
        self.state.return_value={self.source["id"]:{"last_edited_time":self.source["last_edited_time"],
            "category":"돌봄/양육","translations_complete":True}}
        result=indexer.run_indexing()
        self.assertEqual(result["skipped"],1)
        self.budget.assert_not_called()
        self.embedding.assert_not_called()

    def test_translation_only_preserves_embedding_and_existing_language(self):
        meta={"title_en":"Existing English","pre_summary_en":"Existing English content"}
        self.state.return_value={self.source["id"]:{"last_edited_time":self.source["last_edited_time"],
            "category":"돌봄/양육","translations_complete":False,"metadata":meta}}
        indexer.run_indexing()
        self.embedding.assert_not_called()
        self.query.upsert.assert_not_called()
        self.assertEqual(self.trans.call_args.args[2],["zh","vi"])
        self.assertEqual(self.query.update.call_args.args[0]["metadata"]["title_en"],"Existing English")

    def test_malformed_notion_response_blocks_deletion(self):
        self.http.return_value.json.return_value={}
        with self.assertRaises(indexer.IndexingIncomplete):
            indexer.run_indexing()
        self.query.delete.assert_not_called()

    def test_empty_all_source_blocks_mass_delete(self):
        self.state.return_value={"existing":{}}
        self.http.return_value.json.return_value={"results":[],"has_more":False}
        with self.assertRaises(indexer.IndexingIncomplete):
            indexer.run_indexing()
        self.query.delete.assert_not_called()

    def test_upsert_failure_marks_run_failed(self):
        self.query.execute.side_effect=RuntimeError("write failed")
        with self.assertRaises(indexer.IndexingIncomplete) as caught:
            indexer.run_indexing()
        self.assertTrue(caught.exception.summary["critical_error"])

if __name__ == "__main__":
    unittest.main()
