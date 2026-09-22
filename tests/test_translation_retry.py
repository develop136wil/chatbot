"""Offline provider responses; never loads credentials or calls real AI."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import test_no_sql_contract as isolation
from translation_retry import (TranslationRateGate, TranslationFailure, seconds,
                               translation_json, missing_languages)


def setUpModule():
    global utils
    isolation.setUpModule()
    import utils


def tearDownModule():
    isolation.tearDownModule()


class Clock:
    def __init__(self):
        self.now = 0
        self.waits = []
    def clock(self):
        return self.now
    def sleep(self, duration):
        self.waits.append(duration)
        self.now += duration


class ProviderError(Exception):
    def __init__(self, status, headers=None, message="simulated"):
        self.status_code = status
        self.code = status
        self.response = SimpleNamespace(headers=headers or {})
        super().__init__(message)


class RateTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.gate = TranslationRateGate(clock=self.clock.clock, sleep=self.clock.sleep)

    def test_spaces_requests_instead_of_bursting(self):
        self.gate.before(4000)
        self.gate.before(4000)
        self.assertEqual(self.clock.waits, [30])

    def test_remaining_tokens_and_reset_are_honored(self):
        self.gate.observe({"X-RateLimit-Remaining-Tokens":"100", "X-RateLimit-Reset-Tokens":"60s"})
        self.gate.before(3000)
        self.assertAlmostEqual(sum(self.clock.waits),60.25)
        self.assertTrue(all(t<=60 for t in self.clock.waits))

    def test_retry_after_is_never_shortened(self):
        error=ProviderError(429,{"retry-after":"23"})
        self.assertTrue(self.gate.on_error(error).retryable)
        self.gate.before(100)
        self.assertGreaterEqual(sum(self.clock.waits),23)

    def test_long_cooldown_stops_without_repeated_requests(self):
        failure=self.gate.on_error(ProviderError(429,{"retry-after":"3600"}))
        self.assertFalse(failure.retryable)
        with self.assertRaises(TranslationFailure):
            self.gate.before(100)
        self.assertEqual(self.clock.waits,[])

    def test_daily_limit_and_auth_failure_disable_provider_for_run(self):
        for error in (ProviderError(429,message="tokens per day (TPD)"),
                      ProviderError(401),ProviderError(429,{"x-ratelimit-remaining-requests":"0"})):
            gate=TranslationRateGate(clock=self.clock.clock,sleep=self.clock.sleep)
            self.assertFalse(gate.on_error(error).retryable)
            with self.assertRaises(TranslationFailure):
                gate.before(10)

    def test_error_message_timing_and_invalid_header(self):
        error=ProviderError(429,{"retry-after":"invalid"},"Please try again in 6.6525s")
        self.gate.on_error(error)
        self.gate.before(10)
        self.assertGreaterEqual(sum(self.clock.waits),6.6525)

    def test_duration_parser_and_nonfinite_values(self):
        self.assertEqual(seconds("2m3.5s"),123.5)
        self.assertEqual(seconds("250ms"),.25)
        for invalid in ("nan","inf","invalid",None):
            self.assertIsNone(seconds(invalid))


class ResponseTests(unittest.TestCase):
    def test_rejects_empty_invalid_and_wrong_schema(self):
        for text in ("","  ","{","[]",'{"ja":null}','{"ja":{"title":12,"content":[]}}'):
            with self.subTest(text=text),self.assertRaises(TranslationFailure):
                translation_json(text,["ja"])

    def test_complete_fence_and_partial_fields_are_validated(self):
        text='\u0060\u0060\u0060json\n{"ja":{"title":"題名","content":" 内容 "},"en":{"title":"Title"}}\n\u0060\u0060\u0060'
        value=translation_json(text,["ja","en"])
        self.assertEqual(value["ja"]["content"],"内容")
        self.assertEqual(missing_languages(value,["ja","en"]),["en"])

    def test_rejects_truncated_outer_object_instead_of_salvaging_substring(self):
        with self.assertRaises(TranslationFailure):
            translation_json('{"ja":{"title":"Title","content":"Body"}',["ja"])


class TranslationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.groq=patch.object(utils,"GROQ_SYNC_CLIENT",Mock()).start()
        patch.object(utils,"_translation_gemini_unavailable",False).start()
        patch.object(utils.time,"sleep").start()
        self.gemini=patch.object(utils,"get_llm_client",return_value=Mock()).start()
        self.call=patch.object(utils,"call_groq_sync_robust").start()
        self.generate=patch.object(utils,"generate_content_safe").start()

    def response(self,text,reason="STOP"):
        return SimpleNamespace(text=text,candidates=[SimpleNamespace(finish_reason=reason)])

    def test_invalid_json_retries_then_succeeds_without_fallback(self):
        self.call.side_effect=["{",'{"ja":{"title":"題名","content":"本文"}}']
        result=utils.translate_content_multilingual_sync("사업","조건",["ja"])
        self.assertEqual(result["ja"]["content"],"本文")
        self.assertEqual(self.call.call_count,2)
        self.generate.assert_not_called()

    def test_partial_fields_survive_and_retry_does_not_overwrite(self):
        self.call.side_effect=['{"ja":{"title":"original"}}','{"ja":{"title":"changed","content":"本文"}}']
        result=utils.translate_content_multilingual_sync("사업","조건",["ja"])
        self.assertEqual(result["ja"],{"title":"original","content":"本文"})

    def test_fallback_schema_empty_retry_and_success(self):
        self.call.side_effect=TranslationFailure("rate_limited")
        self.generate.side_effect=[self.response(""),self.response('{"ja":{"title":"題名","content":"本文"}}')]
        self.assertEqual(utils.translate_content_multilingual_sync("사업","조건",["ja"])["ja"]["title"],"題名")
        self.assertEqual(self.call.call_count,1)
        self.assertEqual(self.generate.call_count,2)
        config=self.generate.call_args.kwargs
        self.assertTrue(config["translation_once"])
        self.assertEqual(config["response_schema"]["required"],["ja"])

    def test_gemini_transient_failure_retries_once_then_succeeds(self):
        self.call.side_effect=TranslationFailure("rate_limited")
        self.generate.side_effect=[TranslationFailure("provider_transient",True),
                                   self.response('{"ja":{"title":"題名","content":"本文"}}')]
        self.assertEqual(utils.translate_content_multilingual_sync("사업","조건",["ja"])["ja"]["content"],"本文")
        self.assertEqual(self.generate.call_count,2)

    def test_gemini_configuration_failure_disables_provider_for_run(self):
        self.call.side_effect=TranslationFailure("rate_limited")
        self.generate.side_effect=TranslationFailure("provider_configuration")
        for _ in range(2):
            self.assertEqual(utils.translate_content_multilingual_sync("사업","조건",["ja"]),{})
        self.assertEqual(self.generate.call_count,1)

    def test_max_tokens_is_not_retried_or_accepted(self):
        self.call.side_effect=TranslationFailure("output_truncated")
        self.generate.return_value=self.response('{"ja":{"title":"題名","content":"partial"}}',"MAX_TOKENS")
        self.assertEqual(utils.translate_content_multilingual_sync("사업","조건",["ja"]),{})
        self.assertEqual(self.generate.call_count,1)

    def test_quota_disables_gemini_without_key_rotation_or_more_calls(self):
        self.call.side_effect=TranslationFailure("rate_limited")
        self.generate.side_effect=utils.FreeTierQuotaExceeded()
        for _ in range(2):
            self.assertEqual(utils.translate_content_multilingual_sync("사업","조건",["ja"]),{})
        self.assertEqual(self.generate.call_count,1)

    def test_all_invalid_responses_remain_incomplete_and_calls_bounded(self):
        self.call.return_value="{}"
        self.generate.return_value=self.response("{}")
        self.assertEqual(utils.translate_content_multilingual_sync("사업","조건",["ja"]),{})
        self.assertEqual(self.call.call_count,2)
        self.assertEqual(self.generate.call_count,2)


class ProviderWrapperTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.clock=Clock()
        patch.object(utils,"_translation_rate_gate",TranslationRateGate(
            clock=self.clock.clock,sleep=self.clock.sleep)).start()

    def test_groq_sdk_retries_disabled_and_429_bounded(self):
        client=Mock()
        create=client.with_options.return_value.chat.completions.with_raw_response.create
        create.side_effect=ProviderError(429,{"retry-after":"7"})
        with patch.object(utils,"GROQ_SYNC_CLIENT",client),self.assertRaises(TranslationFailure):
            utils.call_groq_sync_robust("prompt",max_tokens=100)
        self.assertEqual(create.call_count,2)
        client.with_options.assert_called_once_with(max_retries=0,timeout=40)
        self.assertGreaterEqual(sum(self.clock.waits),7)

    def test_groq_success_observes_headers_and_checks_finish_reason(self):
        client=Mock()
        raw=client.with_options.return_value.chat.completions.with_raw_response.create.return_value
        raw.headers={"x-ratelimit-remaining-tokens":"123","x-ratelimit-reset-tokens":"10s"}
        raw.parse.return_value=SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop",message=SimpleNamespace(content="{}"))])
        with patch.object(utils,"GROQ_SYNC_CLIENT",client):
            self.assertEqual(utils.call_groq_sync_robust("prompt",max_tokens=100),"{}")
        self.assertEqual(utils._translation_rate_gate.remaining,123)

    def test_gemini_single_attempt_keeps_free_cap_and_timeout(self):
        client=Mock()
        with patch.object(utils,"FREE_TIER_ONLY",True),patch.object(utils,"FREE_TIER_MAX_OUTPUT_TOKENS",400):
            utils.generate_content_safe(client,"prompt",timeout=40,translation_once=True,
                                        max_output_tokens=4096,response_schema={"type":"object"})
        config=client.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config.max_output_tokens,400)
        self.assertEqual(config.thinking_config.thinking_budget,0)
        self.assertTrue(config.automatic_function_calling.disable)
        self.assertEqual(config.http_options.timeout,40000)
        self.assertEqual(config.http_options.retry_options.attempts,1)

    def test_gemini_error_has_no_hidden_retry_or_rotation(self):
        client=Mock()
        client.models.generate_content.side_effect=ProviderError(500)
        with patch.object(utils,"rotate_api_key") as rotate,self.assertRaises(TranslationFailure):
            utils.generate_content_safe(client,"prompt",translation_once=True)
        self.assertEqual(client.models.generate_content.call_count,1)
        rotate.assert_not_called()
