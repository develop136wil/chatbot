"""Offline tests: instrumentation must not change outputs or leak request content."""
import asyncio
import json
import unittest
from unittest.mock import patch
import observability as obs


class TimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_value_and_no_sensitive_arguments_logged(self):
        @obs.timed_async("unit")
        async def call(secret):
            return {"secret": secret}
        with self.assertLogs(obs.logger, level="INFO") as logs:
            result = await call("PRIVATE_QUESTION_AND_KEY")
        self.assertEqual(result, {"secret": "PRIVATE_QUESTION_AND_KEY"})
        self.assertNotIn("PRIVATE_QUESTION_AND_KEY", str(logs.output))
        record = json.loads(logs.records[0].getMessage().split(" ", 1)[1])
        self.assertEqual(record["outcome"], "returned")
        self.assertGreaterEqual(record["duration_ms"], 0)

    async def test_exception_is_unchanged_and_message_not_logged(self):
        error = RuntimeError("PRIVATE_EXCEPTION")
        @obs.timed_async("unit")
        async def call():
            raise error
        with self.assertLogs(obs.logger, level="INFO") as logs:
            with self.assertRaises(RuntimeError) as raised:
                await call()
        self.assertIs(raised.exception, error)
        self.assertIn("raised", str(logs.output))
        self.assertNotIn("PRIVATE_EXCEPTION", str(logs.output))

    async def test_cancellation_propagates(self):
        @obs.timed_async("unit")
        async def call():
            raise asyncio.CancelledError()
        with self.assertLogs(obs.logger, level="INFO") as logs:
            with self.assertRaises(asyncio.CancelledError):
                await call()
        self.assertIn("cancelled", str(logs.output))

    async def test_logging_failure_does_not_change_return(self):
        @obs.timed_async("unit")
        async def call():
            return 7
        with patch.object(obs.logger, "info", side_effect=RuntimeError("logging broken")):
            self.assertEqual(await call(), 7)

    async def test_parallel_jobs_keep_separate_ids_and_restore_context(self):
        @obs.traced_job
        @obs.timed_async("worker_total")
        async def job(data):
            before = obs.current_request_id()
            await asyncio.sleep(0)
            return before, obs.current_request_id()
        with self.assertLogs(obs.logger, level="INFO"):
            results = await asyncio.gather(job({"trace_id": "a"*32}), job({"trace_id": "b"*32}))
        self.assertEqual(results, [("a"*32, "a"*32), ("b"*32, "b"*32)])
        self.assertIsNone(obs.current_request_id())

    async def test_job_invalid_id_replaced_and_context_reset_after_error(self):
        @obs.traced_job
        async def job(data):
            self.assertRegex(obs.current_request_id(), r"^[0-9a-f]{32}$")
            raise ValueError()
        with self.assertRaises(ValueError):
            await job({"trace_id": "PRIVATE\nINJECTION"})
        self.assertIsNone(obs.current_request_id())

    async def test_middleware_preserves_body_status_and_connects_trace(self):
        seen = []
        sent = []
        async def app(scope, receive, send):
            seen.append(obs.current_request_id())
            await send({"type": "http.response.start", "status": 429,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"error":"limited"}'})
        async def send(event):
            sent.append(event)
        with self.assertLogs(obs.logger, level="INFO") as logs:
            await obs.ChatTimingMiddleware(app)({"type": "http", "path": "/chat",
                "headers": [(b"x-request-id", b"USER_SECRET")]}, None, send)
        headers = dict(sent[0]["headers"])
        self.assertEqual(sent[0]["status"], 429)
        self.assertEqual(sent[1]["body"], b'{"error":"limited"}')
        self.assertEqual(headers[b"x-request-id"].decode(), seen[0])
        self.assertIn(b"chat_headers;dur=", headers[b"server-timing"])
        self.assertNotIn("USER_SECRET", str(logs.output))
        self.assertIn(seen[0], str(logs.output))
        self.assertIsNone(obs.current_request_id())

    async def test_non_chat_requests_bypass_logging(self):
        async def app(scope, receive, send):
            return "unchanged"
        with patch.object(obs.logger, "info") as log:
            result = await obs.ChatTimingMiddleware(app)({"type": "http", "path": "/static/style.css"}, None, None)
        self.assertEqual(result, "unchanged")
        log.assert_not_called()

    async def test_middleware_exception_resets_context(self):
        async def app(scope, receive, send):
            raise RuntimeError("PRIVATE_FAILURE")
        with self.assertLogs(obs.logger, level="INFO") as logs:
            with self.assertRaises(RuntimeError):
                await obs.ChatTimingMiddleware(app)({"type": "http", "path": "/chat"}, None, None)
        self.assertNotIn("PRIVATE_FAILURE", str(logs.output))
        self.assertIsNone(obs.current_request_id())
