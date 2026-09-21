"""Statistics tests use no production credentials or network."""
import asyncio
import os
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
import analytics as a

ENV={"ENABLE_CHAT_ANALYTICS":"true","VERCEL_ENV":"production","SESSION_SECRET_KEY":"test-session",
     "ADMIN_SECRET_KEY":"test-admin","SUPABASE_URL":"https://example.invalid","SUPABASE_KEY":"sb_secret_test"}

class AnalyticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,ENV,clear=True);self.env.start();self.addCleanup(self.env.stop)

    async def test_disabled_outside_production_or_without_secret(self):
        for name,value in [("ENABLE_CHAT_ANALYTICS","false"),("VERCEL_ENV","preview"),("SESSION_SECRET_KEY","")]:
            with patch.dict(os.environ,{name:value}):
                self.assertFalse(a.enabled())
                with patch.object(a.httpx,"AsyncClient") as client:
                    self.assertIsNone(await a.rpc("unused",{}))
                    client.assert_not_called()

    async def test_begin_has_no_text_and_same_session_request_has_stable_id(self):
        async def saved(name,payload,**kwargs): return payload["p_attempt"]
        req=SimpleNamespace(session={},state=SimpleNamespace())
        chat=SimpleNamespace(analytics_id=uuid.uuid4(),action="ask",language="ko",entry_source="qr",
                             input_method="typed",question="PRIVATE_QUESTION")
        with patch.object(a,"rpc",AsyncMock(side_effect=saved)) as rpc:
            first=await a.begin(chat,req);second=await a.begin(chat,req)
        self.assertEqual(first["id"],second["id"])
        self.assertNotEqual(first["attempt"],second["attempt"])
        self.assertNotIn("PRIVATE",str(rpc.call_args_list))
        self.assertEqual(len(rpc.call_args.args[1]["p_session"]),64)

    async def test_failed_start_does_not_pretend_collection_succeeded(self):
        req=SimpleNamespace(session={},state=SimpleNamespace())
        chat=SimpleNamespace(action="ask",language="ko")
        with patch.object(a,"rpc",AsyncMock(return_value=None)):
            self.assertIsNone(await a.begin(chat,req))

    async def test_completion_uses_business_outcome_not_http_200(self):
        state={"id":str(uuid.uuid4()),"attempt":str(uuid.uuid4()),"started":time.time()-1,
               "kind":"question","category":"의료/재활","cache_hit":True,"cache_eligible":True}
        cases=[({"status":"complete","total_found":2},"answered"),
               ({"status":"complete","total_found":0},"empty"),
               ({"status":"error","code":"provider_limit"},"limited"),
               ({"status":"error"},"error"),({"status":"clarify"},"clarify")]
        for response,expected in cases:
            with patch.object(a,"rpc",AsyncMock(return_value=True)) as rpc:
                token=await a.finish(state,response)
                self.assertEqual(rpc.call_args.args[1]["p_outcome"],expected)
                self.assertEqual(bool(token),expected=="answered")
        with patch.object(a,"rpc",AsyncMock()) as rpc:
            await a.finish(state,{"job_id":"queued"});rpc.assert_not_awaited()

    async def test_storage_failure_never_exposes_secret_or_breaks_chat(self):
        with patch.object(a,"credentials",side_effect=RuntimeError("PRIVATE_KEY")):
            with self.assertLogs(a.logger,level="WARNING") as logs:
                self.assertIsNone(await a.rpc("test",{}))
            self.assertNotIn("PRIVATE_KEY",str(logs.output))

    async def test_key_headers_secret_vs_legacy(self):
        for key in ("sb_secret_test","eyJlegacy"):
            seen=[]
            def handler(request):
                seen.append(request);return httpx.Response(200,json=True)
            real=httpx.AsyncClient
            with patch.dict(os.environ,{"SUPABASE_KEY":key}), patch.object(a.httpx,"AsyncClient",
                side_effect=lambda **kw:real(transport=httpx.MockTransport(handler),**kw)):
                self.assertTrue(await a.rpc("test",{}))
            self.assertEqual(seen[0].headers["apikey"],key)
            self.assertEqual(seen[0].headers.get("authorization"),"Bearer "+key if key.startswith("eyJ") else None)

    def test_tokens_expire_and_cannot_be_forged(self):
        record=str(uuid.uuid4());token=a.click_token(record)
        self.assertEqual(a.verify_click_token(token),record)
        self.assertIsNone(a.verify_click_token(token[:-1]+("0" if token[-1]!="0" else "1")))
        with patch.object(a.time,"time",return_value=time.time()+86401):
            self.assertIsNone(a.verify_click_token(token))
        for bad in ("","not.a.token","x"*200):
            self.assertIsNone(a.verify_click_token(bad))

    def test_category_only_allows_known_labels(self):
        for value in (None,{},[], "PRIVATE_TEXT","welfare"):
            self.assertEqual(a.category(value),"미분류")
        self.assertEqual(a.category("health"),"의료/재활")
        self.assertEqual(a.category_from_results([{"metadata":{"category":"의료/재활"}}]),"의료/재활")

class AdminTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,ENV,clear=True);self.env.start();self.addCleanup(self.env.stop)
        app=FastAPI();self.rate=AsyncMock();a.install(app,self.rate)
        self.client=TestClient(app);self.addCleanup(self.client.close)

    def test_report_requires_header_not_query_password(self):
        for suffix,headers in [("",{}),("&secret=test-admin",{}),("",{"X-Admin-Secret":"wrong"})]:
            with patch.object(a,"rpc",AsyncMock()) as rpc:
                result=self.client.get("/admin/analytics/data?start=2026-09-01&end=2026-09-21"+suffix,headers=headers)
            self.assertEqual(result.status_code,401);rpc.assert_not_awaited()

    def test_valid_report_no_cache_and_date_validation(self):
        with patch.object(a,"rpc",AsyncMock(return_value={"days":[]})) as rpc:
            result=self.client.get("/admin/analytics/data?start=2026-09-01&end=2026-09-21",headers={"X-Admin-Secret":"test-admin"})
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.headers["cache-control"],"no-store")
            self.assertNotIn("test-admin",result.text)
        for period in ("start=2026-10-01&end=2026-09-01","start=2020-01-01&end=2026-09-01"):
            self.assertEqual(self.client.get("/admin/analytics/data?"+period,headers={"X-Admin-Secret":"test-admin"}).status_code,422)

    def test_cross_site_and_invalid_click_are_rejected(self):
        with patch.object(a,"rpc",AsyncMock()) as rpc:
            result=self.client.post("/analytics/source-click",json={"token":"invalid"})
            self.assertEqual(result.status_code,422)
            result=self.client.post("/analytics/source-click",json={"token":a.click_token(str(uuid.uuid4()))},
                                    headers={"sec-fetch-site":"cross-site"})
            self.assertEqual(result.status_code,403);rpc.assert_not_awaited()

    def test_valid_click_has_no_body_and_only_sends_id(self):
        record=str(uuid.uuid4())
        with patch.object(a,"rpc",AsyncMock(return_value=True)) as rpc:
            result=self.client.post("/analytics/source-click",json={"token":a.click_token(record)})
        self.assertEqual(result.status_code,204);self.assertEqual(result.content,b"")
        self.assertEqual(rpc.call_args.args,("chatbot_analytics_click",{"p_id":record}))
