"""Opt-in CI-only real Redis tests. Never read .env or operational REDIS_URL."""
import asyncio
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_no_sql_contract as isolation


def setUpModule():
    global main, redis_port
    # Validate before isolation clears the environment. Missing service is a failure,
    # never a silently skipped/passing integration run.
    if os.environ.get("CHATBOT_REDIS_INTEGRATION") != "1":
        raise RuntimeError("Run only with the dedicated disposable CI Redis service")
    redis_port = int(os.environ["CHATBOT_TEST_REDIS_PORT"])
    if not 1024 <= redis_port <= 65535:
        raise ValueError("Expected a mapped, non-privileged test port")
    isolation.setUpModule()
    main = isolation.main


def tearDownModule():
    isolation.tearDownModule()


class RealRedisTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from redis.asyncio import Redis
        # Host and DB are fixed; cannot be redirected to a remote operational URL.
        self.redis = Redis(host="127.0.0.1", port=redis_port, db=15,
                           socket_connect_timeout=3, socket_timeout=3)
        self.addAsyncCleanup(self.redis.aclose)
        await self.redis.ping()  # hard failure if CI service is unavailable
        self.client_id = "ci-" + uuid.uuid4().hex
        self.request = SimpleNamespace(headers={}, client=SimpleNamespace(host=self.client_id))
        self.keys = {scope: f"rate_limit:{scope}:{self.client_id}" for scope in ("chat", "feedback")}
        self.addAsyncCleanup(self.redis.delete, *self.keys.values())
        self.memory = AsyncMock(side_effect=AssertionError("Unexpected memory fallback"))
        self.patches = [
            patch.object(main, "redis_async_client", self.redis),
            patch.object(main, "_check_memory_rate_limit", self.memory),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def request_limit(self, scope="chat", limit=10, window=60):
        return await main.check_rate_limit(self.request, limit=limit, window=window, scope=scope)

    async def test_lua_concurrent_admission_is_atomic(self):
        results = await asyncio.gather(*(self.request_limit() for _ in range(50)),
                                       return_exceptions=True)
        self.assertEqual(sum(result is None for result in results), 10)
        rejected = [result for result in results if result is not None]
        self.assertEqual(len(rejected), 40)
        self.assertTrue(all(isinstance(result, main.HTTPException) and result.status_code == 429
                            for result in rejected))
        self.assertEqual(await self.redis.get(self.keys["chat"]), b"10")
        self.assertGreater(await self.redis.ttl(self.keys["chat"]), 0)
        self.memory.assert_not_awaited()

    async def test_chat_and_feedback_have_independent_budgets_and_ttl(self):
        for _ in range(5):
            await self.request_limit()
        for _ in range(5):
            await self.request_limit("feedback", 5, 300)
        with self.assertRaises(main.HTTPException):
            await self.request_limit("feedback", 5, 300)
        for _ in range(5):
            await self.request_limit()
        with self.assertRaises(main.HTTPException):
            await self.request_limit()
        self.assertEqual(await self.redis.get(self.keys["chat"]), b"10")
        self.assertEqual(await self.redis.get(self.keys["feedback"]), b"5")
        self.assertTrue(0 < await self.redis.ttl(self.keys["chat"]) <= 60)
        self.assertTrue(60 < await self.redis.ttl(self.keys["feedback"]) <= 300)

    async def test_expired_window_admits_next_request(self):
        await self.request_limit(limit=1)
        with self.assertRaises(main.HTTPException):
            await self.request_limit(limit=1)
        await self.redis.pexpire(self.keys["chat"], 100)
        for _ in range(100):
            if not await self.redis.exists(self.keys["chat"]):
                break
            await asyncio.sleep(0.02)
        self.assertFalse(await self.redis.exists(self.keys["chat"]))
        await self.request_limit(limit=1)
        self.assertEqual(await self.redis.get(self.keys["chat"]), b"1")
        self.assertGreater(await self.redis.ttl(self.keys["chat"]), 0)

    async def test_subsequent_request_does_not_extend_window(self):
        await self.request_limit()
        await self.redis.pexpire(self.keys["chat"], 5000)
        before = await self.redis.pttl(self.keys["chat"])
        await self.request_limit()
        after = await self.redis.pttl(self.keys["chat"])
        self.assertTrue(0 < after <= before <= 5000)

    async def test_missing_ttl_is_repaired_when_admitted(self):
        await self.redis.set(self.keys["chat"], 1)
        await self.request_limit(limit=3)
        self.assertEqual(await self.redis.get(self.keys["chat"]), b"2")
        self.assertTrue(0 < await self.redis.ttl(self.keys["chat"]) <= 60)

    async def test_missing_ttl_is_repaired_even_when_rejected(self):
        await self.redis.set(self.keys["chat"], 3)
        with self.assertRaises(main.HTTPException) as caught:
            await self.request_limit(limit=3)
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.headers["Retry-After"], "60")
        self.assertTrue(0 < await self.redis.ttl(self.keys["chat"]) <= 60)
        self.memory.assert_not_awaited()
