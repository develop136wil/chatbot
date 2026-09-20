"""Cache-store and rate-limit boundary tests; all service calls are simulated."""
import asyncio
import unittest
from copy import deepcopy
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import test_no_sql_contract as isolation


def setUpModule():
    global main, utils
    isolation.setUpModule()
    main, utils = isolation.main, isolation.utils


def tearDownModule():
    isolation.tearDownModule()


def chain(data):
    q = Mock()
    for name in ("select", "eq", "gt", "limit", "in_", "upsert"):
        getattr(q, name).return_value = q
    q.execute.return_value = SimpleNamespace(data=data)
    return q


class CacheStoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.response = {"status": "complete", "answer": "정상 답변", "last_result_ids": ["p1"]}
        self.row = {"response": self.response, "cache_version": utils.RESPONSE_CACHE_SCHEMA_VERSION,
                    "scope_versions": {"돌봄/양육": 2}}
        self.cache_query = chain([self.row])
        self.scope_query = chain([{"scope": "돌봄/양육", "version": 2}])
        self.db = Mock()
        self.db.table.side_effect = lambda name: self.cache_query if name == utils.RESPONSE_CACHE_TABLE else self.scope_query
        for name, value in (("RESPONSE_CACHE_ENABLED", True), ("RESPONSE_CACHE_USE_DIRECT_REST", False),
                            ("response_cache_client", self.db)):
            self.stack.enter_context(patch.object(utils, name, value))

    async def test_valid_cache_uses_expiry_filter_and_matching_scope(self):
        before = datetime.now(timezone.utc)
        result = await utils.get_response_cache_async("지원", "ko")
        self.assertEqual(result, self.response)
        column, cutoff = self.cache_query.gt.call_args.args
        self.assertEqual(column, "expires_at")
        self.assertGreaterEqual(datetime.fromisoformat(cutoff), before)
        self.assertLessEqual(datetime.fromisoformat(cutoff), datetime.now(timezone.utc))
        self.scope_query.in_.assert_called_once_with("scope", ["돌봄/양육"])

    async def test_no_unexpired_rows_means_cache_miss(self):
        self.cache_query.execute.return_value.data = []
        self.assertIsNone(await utils.get_response_cache_async("지원", "ko"))
        self.scope_query.execute.assert_not_called()

    async def test_changed_scope_never_reuses_old_answer(self):
        self.scope_query.execute.return_value.data = [{"scope": "돌봄/양육", "version": 3}]
        self.assertIsNone(await utils.get_response_cache_async("지원", "ko"))

    async def test_schema_version_mismatch_skips_cache(self):
        self.row["cache_version"] = "old"
        self.assertIsNone(await utils.get_response_cache_async("지원", "ko"))
        self.scope_query.execute.assert_not_called()

    async def test_scope_lookup_failure_never_uses_unverified_answer(self):
        self.scope_query.execute.side_effect = RuntimeError("simulated 401")
        self.assertIsNone(await utils.get_response_cache_async("지원", "ko"))

    async def test_store_read_failure_degrades_to_miss(self):
        self.cache_query.execute.side_effect = TimeoutError()
        self.assertIsNone(await utils.get_response_cache_async("지원", "ko"))

    async def test_invalid_scope_version_is_rejected(self):
        self.row["scope_versions"] = {"돌봄/양육": "not-an-integer"}
        self.assertIsNone(await utils.get_response_cache_async("지원", "ko"))

    async def test_empty_and_error_responses_are_not_written(self):
        for response in ({"status": "error", "answer": "error"},
                         {"status": "complete", "answer": utils.LOCALIZED_UI["ko"]["not_found"]}):
            await utils.save_response_cache_async("지원", "ko", response)
        self.db.table.assert_not_called()

    async def test_save_uses_current_versions_and_ttl_without_mutating_answer(self):
        original = deepcopy(self.response)
        before = datetime.now(timezone.utc)
        await utils.save_response_cache_async("지원", "ko", self.response, scopes=["돌봄/양육"])
        record = self.cache_query.upsert.call_args.args[0]
        self.assertEqual(record["scope_versions"], {"돌봄/양육": 2})
        self.assertEqual(record["response"], original)
        self.assertEqual(self.response, original)
        seconds = (datetime.fromisoformat(record["expires_at"]) - before).total_seconds()
        self.assertGreaterEqual(seconds, utils.RESPONSE_CACHE_TTL_SECONDS)
        self.assertLess(seconds, utils.RESPONSE_CACHE_TTL_SECONDS + 10)

    async def test_version_lookup_failure_prevents_unverifiable_write(self):
        self.scope_query.execute.side_effect = TimeoutError()
        await utils.save_response_cache_async("지원", "ko", self.response, scopes=["돌봄/양육"])
        self.cache_query.upsert.assert_not_called()

    async def test_cache_write_failure_does_not_fail_answer(self):
        self.cache_query.execute.side_effect = RuntimeError("simulated upsert failure")
        await utils.save_response_cache_async("지원", "ko", self.response, scopes=["돌봄/양육"])
        self.cache_query.upsert.assert_called_once()

    async def test_rest_key_path_checks_expiry_and_versions_too(self):
        rest = AsyncMock(side_effect=[[self.row], [{"scope": "돌봄/양육", "version": 2}]])
        with patch.object(utils, "RESPONSE_CACHE_USE_DIRECT_REST", True), patch.object(utils, "_secret_cache_rest_request_async", rest):
            self.assertEqual(await utils.get_response_cache_async("지원", "ko"), self.response)
        self.assertEqual(rest.await_count, 2)
        params = rest.await_args_list[0].kwargs["params"]
        self.assertTrue(params["expires_at"].startswith("gt."))
        self.db.table.assert_not_called()

    async def test_rest_write_uses_version_snapshot(self):
        rest = AsyncMock(side_effect=[[{"scope": "돌봄/양육", "version": 4}], []])
        with patch.object(utils, "RESPONSE_CACHE_USE_DIRECT_REST", True), patch.object(utils, "_secret_cache_rest_request_async", rest):
            await utils.save_response_cache_async("지원", "ko", self.response, scopes=["돌봄/양육"])
        write = rest.await_args_list[-1]
        self.assertEqual(write.args[:2], ("POST", utils.RESPONSE_CACHE_TABLE))
        self.assertEqual(write.kwargs["payload"]["scope_versions"], {"돌봄/양육": 4})


class RequestLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(main, "_memory_rate_limits", {}))
        self.stack.enter_context(patch.object(main, "_memory_rate_limit_lock", asyncio.Lock()))
        self.request = SimpleNamespace(headers={}, client=SimpleNamespace(host="test-client"))

    async def test_simultaneous_memory_requests_never_exceed_limit(self):
        results = await asyncio.gather(*(main._check_memory_rate_limit("client", 3, 60) for _ in range(20)), return_exceptions=True)
        self.assertEqual(sum(r is None for r in results), 3)
        self.assertTrue(all(r is None or r.status_code == 429 for r in results))

    async def test_memory_window_expiry_allows_requests_again(self):
        with patch.object(main.time, "monotonic", return_value=10):
            await main._check_memory_rate_limit("client", 1, 60)
        with patch.object(main.time, "monotonic", return_value=69):
            with self.assertRaises(main.HTTPException):
                await main._check_memory_rate_limit("client", 1, 60)
        with patch.object(main.time, "monotonic", return_value=70):
            await main._check_memory_rate_limit("client", 1, 60)

    async def test_redis_failure_still_enforces_memory_limit(self):
        redis = SimpleNamespace(eval=AsyncMock(side_effect=RuntimeError("unavailable")))
        with patch.object(main, "redis_async_client", redis):
            await main.check_rate_limit(self.request, limit=1)
            with self.assertRaises(main.HTTPException) as caught:
                await main.check_rate_limit(self.request, limit=1)
        self.assertEqual(caught.exception.status_code, 429)

    async def test_redis_rejection_is_not_bypassed_by_memory_fallback(self):
        redis = SimpleNamespace(eval=AsyncMock(return_value=0))
        with patch.object(main, "redis_async_client", redis), patch.object(main, "_check_memory_rate_limit", AsyncMock()) as memory:
            with self.assertRaises(main.HTTPException) as caught:
                await main.check_rate_limit(self.request, limit=3, window=60)
            self.assertEqual(caught.exception.status_code, 429)
            memory.assert_not_awaited()
        redis.eval.assert_awaited_once_with(main.RATE_LIMIT_LUA, 1, "rate_limit:test-client", 3, 60)

    async def test_redis_admission_is_one_atomic_call_per_request(self):
        # Models the Redis atomic admission result; does not execute a Redis server.
        count = 0
        async def evaluate(script, numkeys, key, limit, window):
            nonlocal count
            await asyncio.sleep(0)
            if count >= limit:
                return 0
            count += 1
            return 1
        redis = SimpleNamespace(eval=AsyncMock(side_effect=evaluate))
        with patch.object(main, "redis_async_client", redis):
            results = await asyncio.gather(*(main.check_rate_limit(self.request, limit=3) for _ in range(20)), return_exceptions=True)
        self.assertEqual(sum(r is None for r in results), 3)
        self.assertEqual(redis.eval.await_count, 20)

    async def test_daily_counter_stops_at_limit_and_resets_on_new_day(self):
        with patch.object(main, "FREE_TIER_ONLY", True), patch.object(main, "FREE_TIER_DAILY_REQUESTS_PER_SESSION", 1):
            session = {}
            main.reserve_free_tier_request(session)
            with self.assertRaises(main.FreeTierDailyLimitExceeded):
                main.reserve_free_tier_request(session)
            self.assertEqual(session["free_tier_usage_count"], 1)
            session["free_tier_usage_date"] = "1900-01-01"
            main.reserve_free_tier_request(session)
            self.assertEqual(session["free_tier_usage_count"], 1)
