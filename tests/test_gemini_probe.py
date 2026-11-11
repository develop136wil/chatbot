"""Offline checks of the live probe's request/destination budget."""
import unittest
import httpx
from scripts.gemini_migration_probe import Budget, ProbeStopped, MODEL


def request(url=None):
    return httpx.Request("POST", url or f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent")


class ProbeBudgetTests(unittest.TestCase):
    def test_seven_calls_and_no_eighth(self):
        budget = Budget()
        for i in range(7):
            budget.stage = str(i)
            budget.before(request())
        budget.stage = "extra"
        with self.assertRaises(ProbeStopped):
            budget.before(request())
        self.assertEqual(len(budget.requests), 7)

    def test_no_retry_within_stage(self):
        budget = Budget()
        budget.stage = "intent"
        budget.before(request())
        with self.assertRaises(ProbeStopped):
            budget.before(request())
        self.assertEqual(len(budget.requests), 1)

    def test_only_target_model_endpoint_is_allowed(self):
        for url in ("https://example.com", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"):
            budget = Budget()
            budget.stage = "intent"
            with self.assertRaises(ProbeStopped):
                budget.before(request(url))
            self.assertEqual(budget.requests, [])

    def test_error_or_wrong_model_or_truncation_stops_run(self):
        for status, body in ((429, {}), (404, {}), (200, {"modelVersion": "wrong"}),
                             (200, {"modelVersion": MODEL, "candidates": [{"finishReason": "MAX_TOKENS"}]})):
            budget = Budget()
            budget.stage = "intent"
            budget.before(request())
            budget.after(httpx.Response(status, json=body))
            budget.stage = "next"
            with self.assertRaises(ProbeStopped):
                budget.before(request())

    def test_stop_on_complete_response_is_not_required(self):
        budget = Budget()
        budget.stage = "intent"
        budget.before(request())
        budget.after(httpx.Response(200, json={"modelVersion": MODEL, "candidates": [{"finishReason": "STOP"}]}))
        self.assertFalse(budget.stopped)
