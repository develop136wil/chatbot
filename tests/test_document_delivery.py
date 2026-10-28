"""Synthetic documents only: real indexing/formatting with in-memory storage.

This proves data delivery, not live model translation or retrieval quality.
Every external dependency is supplied by the existing offline harness.
"""
import asyncio
import unittest
from copy import deepcopy
import html
import re
from unittest.mock import AsyncMock, patch

import test_indexer_recovery as recovery
import test_no_sql_contract as isolation


def setUpModule():
    recovery.setUpModule()


def tearDownModule():
    recovery.tearDownModule()


LANGUAGES = ("ko", "en", "vi", "zh", "ja")
# These deliberately fictional values must never be used as benefit guidance.
SUMMARIES = {
    "ko": "지원 내용\n- 123,456 KRW 지급 (가상 테스트)\n대상\n- 24~35개월 도봉구 거주 아동만 (가상 조건)",
    "en": "Support Content\n- 123,456 KRW payment (fictional test)\nTarget\n- 24~35 months; Dobong residents only (fictional condition)",
    "vi": "Nội dung hỗ trợ\n- 123,456 KRW (dữ liệu thử nghiệm)\nĐối tượng\n- 24~35 tháng; chỉ cư dân Dobong (điều kiện giả định)",
    "zh": "支持内容\n- 123,456 KRW（虚构测试）\n对象\n- 24~35个月；仅限道峰区居民（虚构条件）",
    "ja": "支援内容\n- 123,456 KRW（架空のテスト）\n対象\n- 24~35か月；道峰区の住民のみ（架空の条件）",
}


class DocumentDeliveryTests(unittest.TestCase):
    setUp = recovery.IndexerRecoveryTests.setUp
    notion_response = recovery.IndexerRecoveryTests.notion_response

    def index_document(self):
        self.summary.return_value = SUMMARIES["ko"]
        self.translate.return_value = {
            lang: {"title": f"TEST ONLY {lang}", "content": SUMMARIES[lang]}
            for lang in LANGUAGES if lang != "ko"
        }
        report = recovery.indexer.run_indexing()
        self.assertEqual(report.status, "complete")
        self.assertEqual((report.discovered, report.updated, report.skipped), (1, 1, 0))
        self.assertEqual(report.translations_pending, 0)
        self.assertTrue(self.db.rows["p1"]["metadata"]["translations_complete"])
        return deepcopy(self.db.rows["p1"])

    def test_new_document_reaches_five_languages_without_live_translation_or_writes(self):
        row = self.index_document()
        snapshot = deepcopy(self.db.rows)
        worker, utils = isolation.worker, isolation.utils
        with patch.object(worker, "expand_search_query_async", AsyncMock(return_value=["테스트"])), \
                patch.object(worker, "search_supabase_async", AsyncMock(return_value=[row])), \
                patch.object(worker, "rerank_search_results_async", AsyncMock(side_effect=lambda q, rows: rows)), \
                patch.object(worker, "save_response_cache_async", AsyncMock()) as save, \
                patch.object(worker, "NOTION_QUERY_LOGS_ENABLED", False), \
                patch.object(utils, "LIVE_TRANSLATION_ENABLED", False), \
                patch.object(utils, "translate_content_simple_async", AsyncMock()) as translate:
            for lang in LANGUAGES:
                with self.subTest(language=lang):
                    answer, ids, count = asyncio.run(worker.process_job_async({
                        "question": "가상 테스트 지원", "language": lang, "cacheable": False,
                    }))
                    self.assertEqual((ids, count), (["p1"], 1))
                    self.assertEqual(answer.count('class="result-card"'), 1)
                    self.assertIn('https://example.org/p1', answer)
                    expected_title = "테스트 사업" if lang == "ko" else f"TEST ONLY {lang}"
                    self.assertIn(expected_title, answer)
                    self.assertIn(utils.LOCALIZED_UI[lang]["header_found"], answer)
            save.assert_not_awaited()
            translate.assert_not_awaited()
        self.assertEqual(self.db.rows, snapshot)
        self.summary.reset_mock()
        self.translate.reset_mock()
        self.embedding.reset_mock()
        again = recovery.indexer.run_indexing()
        self.assertEqual((again.updated, again.skipped), (0, 1))
        for call in (self.summary, self.translate, self.embedding):
            call.assert_not_called()

    def test_stored_amount_and_age_survive_card_formatting_in_every_language(self):
        row = self.index_document()
        for lang in LANGUAGES:
            with self.subTest(language=lang):
                localized = asyncio.run(isolation.utils.localize_result_pages_async([row], lang))
                metadata = localized[0]["metadata"]
                self.assertEqual(metadata["pre_summary"], SUMMARIES[lang])
                answer = isolation.utils.format_search_results([metadata], lang)
                for required in ("123,456", "24~35", "KRW"):
                    self.assertIn(required, answer, f"{lang}: source fact lost: {required}")


class SummaryFactPreservationTests(unittest.TestCase):
    def assert_facts(self, summary, facts, language="ko"):
        cleaned = isolation.utils.clean_summary_text(summary, language)
        answer = isolation.utils.format_search_results([{
            "title": "TEST ONLY", "pre_summary": summary,
            "page_url": "https://example.org/test", "category": "돌봄/양육",
        }], language)
        body = re.search(r'<div class="card-body">(.*?)</div>', answer, re.S).group(1)
        visible = html.unescape(re.sub(r'<[^>]+>', '', body))
        shared = html.unescape(re.search(r'data-copy="([^"]*)"', answer, re.S).group(1))
        for fact in facts:
            self.assertIn(fact, cleaned)
            self.assertIn(fact, visible)
            self.assertIn(fact, shared)
        return cleaned, answer

    def test_bare_and_bulleted_numbers_ranges_and_signs_are_not_list_markers(self):
        facts = ("15,340원", "24~35개월", "0~71개월", "1.5%", "-3.5%", "24-35개월", "0원", "무료")
        for prefix in ("", "- ", "* ", "• ", "•", "1. ", "2) ", "① "):
            for fact in facts:
                with self.subTest(prefix=prefix, fact=fact):
                    self.assert_facts("지원 내용\n" + prefix + fact, [fact])

    def test_short_inline_facts_and_negative_signs_survive(self):
        for fact in ("0원", "무료", "-3.5%", "24~35개월"):
            with self.subTest(fact=fact):
                self.assert_facts("**비용**: " + fact, [fact])

    def test_conditions_after_fourth_line_are_not_truncated(self):
        facts = ["가상 조건 " + str(i) for i in range(1, 5)] + ["도봉구 거주자만", "중복 불가", "0원"]
        self.assert_facts("대상\n" + "\n".join("- " + fact for fact in facts), facts)

    def test_ordinary_list_markers_are_removed_without_empty_noise(self):
        cleaned, _ = self.assert_facts("대상\n1. 도봉구 주민\n2) 24~35개월\n① 중복 불가\n- \n•\n***", ["도봉구 주민", "24~35개월", "중복 불가"])
        self.assertEqual(cleaned.splitlines(), ["**대상**", "• 도봉구 주민", "• 24~35개월", "• 중복 불가"])

    def test_short_values_and_tail_conditions_in_five_languages(self):
        headings = {"ko": "대상", "en": "Target", "vi": "Đối tượng", "zh": "对象", "ja": "対象"}
        for lang, heading in headings.items():
            with self.subTest(language=lang):
                facts = [f"{n},000 KRW" for n in range(1, 6)] + ["24~35", "0", "1.5%", "-3.5%"]
                self.assert_facts(heading + "\n" + "\n".join("- " + x for x in facts), facts, lang)


if __name__ == "__main__":
    unittest.main()
