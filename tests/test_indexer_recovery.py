"""Offline indexing failure/recovery tests. Never run a real indexer against a service."""
import unittest
from copy import deepcopy
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch
import test_no_sql_contract as isolation


def setUpModule():
    global indexer
    isolation.setUpModule()
    import run_indexer as indexer


def tearDownModule():
    isolation.tearDownModule()


def complete_meta(pid="p1", category="돌봄/양육", edited="old"):
    meta = {"page_id": pid, "category": category, "last_edited_time": edited}
    for lang in ("en", "vi", "zh", "ja"):
        meta["title_" + lang] = "prepared title"
        meta["pre_summary_" + lang] = "prepared summary"
    return meta


def page(pid="p1", edited="new"):
    return {"id": pid, "last_edited_time": edited, "properties": {},
            "url": "https://example.org/" + str(pid)}


class MemoryDB:
    def __init__(self):
        self.rows = {}
        self.fail_save = set()
        self.fail_delete = set()
        self.fail_clear = False
        self.fail_read = False
        self.operations = []

    def table(self, name):
        if name != "site_pages":
            raise AssertionError("Unexpected table: " + name)
        return MemoryQuery(self)


class MemoryQuery:
    def __init__(self, db):
        self.db = db
        self.action = "read"
        self.payload = None
        self.pid = None
        self.bounds = (0, 499)

    def select(self, *args):
        return self

    def order(self, *args):
        return self

    def range(self, start, end):
        self.bounds = (start, end)
        return self

    def eq(self, name, pid):
        self.pid = pid
        return self

    def upsert(self, payload, **kwargs):
        self.action, self.payload = "save", deepcopy(payload)
        return self

    def update(self, payload):
        self.action, self.payload = "update", deepcopy(payload)
        return self

    def delete(self):
        self.action = "delete"
        return self

    def execute(self):
        self.db.operations.append((self.action, self.pid, self.bounds))
        if self.action == "read":
            if self.db.fail_read:
                raise RuntimeError("simulated state read failure")
            rows = [deepcopy(row) for _, row in sorted(self.db.rows.items())]
            return SimpleNamespace(data=rows[self.bounds[0]:self.bounds[1]+1])
        if self.action == "save":
            for row in self.payload:
                if row["page_id"] in self.db.fail_save:
                    raise RuntimeError("simulated upsert failure")
                self.db.rows[row["page_id"]] = deepcopy(row)
        elif self.action == "delete":
            if self.pid in self.db.fail_delete:
                raise RuntimeError("simulated deletion failure")
            self.db.rows.pop(self.pid, None)
        elif self.action == "update":
            if self.db.fail_clear and indexer.CACHE_PENDING_FIELD not in self.payload["metadata"]:
                raise RuntimeError("simulated marker cleanup failure")
            if self.pid in self.db.rows:
                self.db.rows[self.pid].update(deepcopy(self.payload))
                return SimpleNamespace(data=[deepcopy(self.db.rows[self.pid])])
        return SimpleNamespace(data=[])


class IndexerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.db = MemoryDB()
        self.pages = {"a": [page()], "b": []}
        self.fail_categories = set()
        self.post = self.stack.enter_context(patch.object(indexer.requests, "post", side_effect=self.notion_response))
        for name, value in (
            ("supabase", self.db), ("DATABASE_IDS", {"돌봄/양육": "a", "교육/보육": "b"}),
            ("RESPONSE_CACHE_ENABLED", True),
        ):
            self.stack.enter_context(patch.object(indexer, name, value))
        self.stack.enter_context(patch.object(indexer, "init_clients"))
        self.llm = self.stack.enter_context(patch.object(indexer, "get_llm_client", return_value=object()))
        self.stack.enter_context(patch.object(indexer, "_get_title", return_value="테스트 사업"))
        self.stack.enter_context(patch.object(indexer, "_get_rich_text", return_value="테스트 지원 안내"))
        self.stack.enter_context(patch.object(indexer, "_get_number", return_value=None))
        self.stack.enter_context(patch.object(indexer, "_get_multi_select", return_value=[]))
        self.summary = self.stack.enter_context(patch.object(indexer, "translate_content_simple", return_value="지원 내용: 테스트"))
        translations = {lang: {"title": "title", "content": "summary"} for lang in ("en", "zh", "vi", "ja")}
        self.translate = self.stack.enter_context(patch.object(indexer, "translate_content_multilingual_sync", return_value=translations))
        self.embedding = self.stack.enter_context(patch.object(indexer, "get_gemini_embedding", return_value=[0.1]))
        self.bump = self.stack.enter_context(patch.object(indexer, "bump_response_cache_scope_versions", return_value=True))
        self.purge = self.stack.enter_context(patch.object(indexer, "purge_expired_response_cache", return_value=True))
        self.stack.enter_context(patch.object(indexer, "send_email_alert"))
        self.stack.enter_context(patch.object(indexer.time, "sleep"))

    def notion_response(self, url, **kwargs):
        key = url.split("/")[-2]
        if key in self.fail_categories:
            raise RuntimeError("simulated Notion failure")
        result = Mock()
        result.json.return_value = {"results": deepcopy(self.pages[key]), "has_more": False}
        return result

    def add_old(self, pid, **kwargs):
        self.db.rows[pid] = {"page_id": pid, "metadata": complete_meta(pid, **kwargs)}

    def incomplete(self):
        with self.assertRaises(indexer.IndexingIncomplete) as caught:
            indexer.run_indexing()
        return caught.exception.report

    def test_partial_category_failure_still_refreshes_successful_writes_without_deletion(self):
        self.add_old("removed")
        self.fail_categories.add("b")
        report = self.incomplete()
        self.assertEqual((report.updated, report.failed_categories), (1, 1))
        self.assertIn("removed", self.db.rows)
        self.bump.assert_called_once_with(self.db, ["돌봄/양육"])
        self.assertNotIn(indexer.CACHE_PENDING_FIELD, self.db.rows["p1"]["metadata"])

    def test_partial_write_failure_is_counted_and_does_not_prevent_cache_refresh(self):
        self.pages["a"].append(page("p2"))
        self.db.fail_save.add("p2")
        report = self.incomplete()
        self.assertEqual((report.updated, report.failed_pages), (1, 1))
        self.bump.assert_called_once()
        self.assertNotIn("p2", self.db.rows)

    def test_parse_failure_is_not_a_successful_skip(self):
        with patch.object(indexer, "_get_title", side_effect=ValueError()):
            report = self.incomplete()
        self.assertEqual((report.failed_pages, report.skipped, report.updated), (1, 0, 0))
        self.summary.assert_not_called()

    def test_empty_embedding_is_reported_as_failure(self):
        self.embedding.return_value = None
        report = self.incomplete()
        self.assertEqual(report.failed_pages, 1)
        self.assertNotIn("p1", self.db.rows)

    def test_empty_summary_is_not_indexed(self):
        self.summary.return_value = ""
        self.assertEqual(self.incomplete().failed_pages, 1)
        self.embedding.assert_not_called()

    def test_translation_pending_is_saved_but_run_is_incomplete(self):
        self.translate.return_value = {}
        report = self.incomplete()
        self.assertEqual((report.updated, report.translations_pending), (1, 1))
        self.assertIn("p1", self.db.rows)
        self.bump.assert_called_once()

    def test_cache_failure_recovers_next_run_without_ai(self):
        self.bump.return_value = False
        self.assertTrue(self.incomplete().cache_refresh_failed)
        self.assertIn(indexer.CACHE_PENDING_FIELD, self.db.rows["p1"]["metadata"])
        self.summary.reset_mock()
        self.translate.reset_mock()
        self.embedding.reset_mock()
        self.bump.reset_mock()
        self.bump.return_value = True
        report = indexer.run_indexing()
        self.assertEqual((report.updated, report.skipped), (0, 1))
        for call in (self.summary, self.translate, self.embedding):
            call.assert_not_called()
        self.bump.assert_called_once()
        self.assertNotIn(indexer.CACHE_PENDING_FIELD, self.db.rows["p1"]["metadata"])

    def test_marker_cleanup_failure_retains_retry_state(self):
        self.db.fail_clear = True
        report = self.incomplete()
        self.assertEqual(report.cache_marker_failures, 1)
        self.assertIn(indexer.CACHE_PENDING_FIELD, self.db.rows["p1"]["metadata"])
        self.db.fail_clear = False
        self.summary.reset_mock()
        self.assertTrue(indexer.run_indexing().complete)
        self.summary.assert_not_called()

    def test_state_load_failure_stops_before_any_ai_or_source_scan(self):
        self.db.fail_read = True
        self.assertTrue(self.incomplete().setup_failed)
        self.llm.assert_not_called()
        self.post.assert_not_called()

    def test_state_load_reads_beyond_first_page(self):
        for i in range(501):
            self.add_old(str(i))
        state = indexer.load_state_from_db()
        self.assertEqual(len(state), 501)
        self.assertEqual([op[2] for op in self.db.operations], [(0, 499), (500, 999)])

    def test_category_move_refreshes_old_and_new_scopes_even_with_same_timestamp(self):
        self.add_old("p1", category="교육/보육", edited="new")
        report = indexer.run_indexing()
        self.assertEqual(report.updated, 1)
        self.assertEqual(set(self.bump.call_args.args[1]), {"교육/보육", "돌봄/양육"})

    def test_deletion_failure_is_not_counted_as_deleted(self):
        self.pages["a"] = []
        self.add_old("removed")
        self.db.fail_delete.add("removed")
        report = self.incomplete()
        self.assertEqual((report.deleted, report.failed_deletions), (0, 1))
        self.assertIn("removed", self.db.rows)

    def test_deletion_waits_for_cache_refresh_and_can_retry(self):
        self.pages["a"] = []
        self.add_old("removed")
        self.bump.return_value = False
        report = self.incomplete()
        self.assertEqual(report.deleted, 0)
        self.assertIn("removed", self.db.rows)
        self.bump.return_value = True
        self.assertEqual(indexer.run_indexing().deleted, 1)
        self.assertNotIn("removed", self.db.rows)

    def test_unchanged_run_uses_no_ai_and_preserves_cache(self):
        self.add_old("p1", edited="new")
        report = indexer.run_indexing()
        self.assertEqual((report.updated, report.skipped), (0, 1))
        self.summary.assert_not_called()
        self.embedding.assert_not_called()
        self.bump.assert_not_called()

    def test_invalid_source_response_cannot_delete_existing_documents(self):
        self.add_old("removed")
        self.post.side_effect = None
        self.post.return_value.json.return_value = {}
        report = self.incomplete()
        self.assertEqual(report.failed_categories, 2)
        self.assertIn("removed", self.db.rows)

    def test_missing_page_id_is_counted_and_blocks_deletion(self):
        self.add_old("removed")
        self.pages["a"] = [page(None)]
        report = self.incomplete()
        self.assertEqual(report.failed_pages, 1)
        self.assertIn("removed", self.db.rows)

    def test_expired_cache_cleanup_failure_marks_run_incomplete(self):
        self.purge.return_value = False
        self.assertTrue(self.incomplete().cleanup_failed)

    def test_cache_disabled_does_not_require_cache_tables(self):
        with patch.object(indexer, "RESPONSE_CACHE_ENABLED", False):
            self.assertTrue(indexer.run_indexing().complete)
        self.bump.assert_not_called()
        self.purge.assert_not_called()
        self.assertNotIn(indexer.CACHE_PENDING_FIELD, self.db.rows["p1"]["metadata"])

    def test_cli_returns_nonzero_for_pending_work_and_zero_for_complete(self):
        with patch.object(indexer, "run_indexing", side_effect=indexer.IndexingIncomplete(indexer.IndexingReport(translations_pending=1))):
            self.assertEqual(indexer.cli(), 1)
        with patch.object(indexer, "run_indexing", return_value=indexer.IndexingReport()):
            self.assertEqual(indexer.cli(), 0)

    def test_missing_pagination_state_is_not_a_complete_scan(self):
        self.add_old("removed")
        self.post.side_effect = None
        self.post.return_value.json.return_value = {"results": []}
        self.assertEqual(self.incomplete().failed_categories, 2)
        self.assertIn("removed", self.db.rows)

    def test_repeated_pagination_cursor_cannot_loop_or_delete(self):
        self.add_old("removed")
        self.post.side_effect = None
        self.post.return_value.json.return_value = {"results": [], "has_more": True, "next_cursor": "same"}
        self.assertEqual(self.incomplete().failed_categories, 2)
        self.assertEqual(self.post.call_count, 4)
        self.assertIn("removed", self.db.rows)

    def japanese_missing(self, pid="p1"):
        self.add_old(pid, edited="new")
        row = self.db.rows[pid]
        row.update(content="unchanged source", embedding=[0.2, 0.3])
        row["metadata"].update(title="한국 사업", pre_summary="한국 지원 요약")
        row["metadata"].pop("title_ja")
        row["metadata"].pop("pre_summary_ja")

    def test_japanese_backfill_reuses_original_embedding_and_other_translations(self):
        self.japanese_missing()
        before = deepcopy(self.db.rows["p1"])
        report = indexer.run_indexing()
        self.assertTrue(report.complete)
        self.assertEqual(report.updated, 1)
        self.translate.assert_called_once_with("한국 사업", "한국 지원 요약", languages=["ja"])
        self.embedding.assert_not_called()
        self.summary.assert_not_called()
        after = self.db.rows["p1"]
        for key in ("content", "embedding"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(after["metadata"]["title_en"], before["metadata"]["title_en"])
        self.assertTrue(indexer.has_complete_multilingual_metadata(after["metadata"]))
        self.bump.assert_called_once()
        self.translate.reset_mock()
        self.assertEqual(indexer.run_indexing().skipped, 1)
        self.translate.assert_not_called()

    def test_japanese_partial_translation_is_pending_then_resumes(self):
        self.japanese_missing()
        self.translate.return_value = {"ja": {"title": "日本語の題名", "content": ""}}
        self.assertEqual(self.incomplete().translations_pending, 1)
        self.translate.return_value = {"ja": {"title": "replacement", "content": "日本語の案内"}}
        self.assertTrue(indexer.run_indexing().complete)
        self.assertEqual(self.db.rows["p1"]["metadata"]["title_ja"], "日本語の題名")
        self.embedding.assert_not_called()

    def test_japanese_backfill_budget_defers_instead_of_silently_skipping(self):
        self.pages["a"].append(page("p2"))
        self.japanese_missing("p1")
        self.japanese_missing("p2")
        with patch.object(indexer, "TRANSLATION_BACKFILL_LIMIT", 1):
            report = indexer.run_indexing()
            self.assertEqual(report.status, "in_progress")
            self.assertFalse(report.complete)
            self.assertEqual((report.translations_failed, report.translations_deferred), (0, 1))
            self.assertEqual((report.updated, report.translations_pending), (1, 1))
            self.assertEqual(self.translate.call_count, 1)
            report = indexer.run_indexing()
            self.assertTrue(report.complete)
            self.assertEqual((report.updated, report.skipped), (1, 1))
        self.embedding.assert_not_called()

    def test_invalid_japanese_translation_never_marks_complete(self):
        for invalid in (None, [], {"ja": "wrong"}, {"ja": {"title": [], "content": 12}}):
            with self.subTest(invalid=invalid):
                self.japanese_missing()
                self.translate.return_value = invalid
                report = self.incomplete()
                self.assertEqual((report.updated, report.translations_pending), (0, 1))
                self.assertNotIn("title_ja", self.db.rows["p1"]["metadata"])
        self.embedding.assert_not_called()

    def test_japanese_update_without_returned_row_is_failure_and_can_retry(self):
        self.japanese_missing()
        execute=MemoryQuery.execute
        def no_write(query):
            if query.action=="update":
                return SimpleNamespace(data=[])
            return execute(query)
        with patch.object(MemoryQuery,"execute",no_write):
            report=self.incomplete()
        self.assertEqual((report.updated,report.failed_pages),(0,1))
        self.assertNotIn("title_ja",self.db.rows["p1"]["metadata"])
        self.assertTrue(indexer.run_indexing().complete)

    def test_japanese_cache_refresh_failure_recovers_without_retranslation(self):
        self.japanese_missing()
        self.bump.return_value=False
        self.assertTrue(self.incomplete().cache_refresh_failed)
        self.assertIn(indexer.CACHE_PENDING_FIELD,self.db.rows["p1"]["metadata"])
        self.translate.reset_mock()
        self.bump.return_value=True
        self.assertTrue(indexer.run_indexing().complete)
        self.translate.assert_not_called()
        self.assertNotIn(indexer.CACHE_PENDING_FIELD,self.db.rows["p1"]["metadata"])

    def test_one_failed_translation_and_batch_deferrals_are_distinct(self):
        self.pages["a"] = [page("p"+str(i)) for i in range(5)]
        for i in range(5):
            self.japanese_missing("p"+str(i))
        valid = self.translate.return_value
        self.translate.side_effect = [valid, {}]
        with patch.object(indexer,"TRANSLATION_BACKFILL_LIMIT",2):
            report=self.incomplete()
        self.assertEqual(report.status,"failed")
        self.assertEqual((report.translations_attempted,report.translations_completed,
                          report.translations_failed,report.translations_deferred,
                          report.translations_pending),(2,1,1,3,4))
        self.translate.side_effect=None
        self.assertTrue(indexer.run_indexing().complete)

    def test_logged_155_document_batch_has_exact_19_1_135_counts(self):
        self.pages["a"] = [page("p"+str(i)) for i in range(155)]
        for i in range(155):
            self.japanese_missing("p"+str(i))
        self.translate.side_effect = [self.translate.return_value] * 19 + [{}]
        with patch.object(indexer,"TRANSLATION_BACKFILL_LIMIT",20):
            report=self.incomplete()
        self.assertEqual((report.discovered,report.updated,report.translations_attempted,
                          report.translations_completed,report.translations_failed,
                          report.translations_deferred,report.translations_pending),
                         (155,19,20,19,1,135,136))
        self.assertEqual(report.status,"failed")
        self.assertEqual(report.failed_pages,0)
        self.embedding.assert_not_called()

    def test_only_scheduled_backlog_is_success_but_never_complete(self):
        report=indexer.IndexingReport(translations_pending=135,translations_deferred=135)
        self.assertEqual(indexer.finish_indexing(report).status,"in_progress")
        with patch.object(indexer,"run_indexing",return_value=report):
            self.assertEqual(indexer.cli(),0)

    def test_error_with_scheduled_backlog_still_fails(self):
        report=indexer.IndexingReport(translations_pending=135,translations_deferred=135,cache_refresh_failed=True)
        with self.assertRaises(indexer.IndexingIncomplete):
            indexer.finish_indexing(report)

    def test_github_summary_makes_partial_progress_explicit(self):
        import tempfile,os
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/"summary.md"
            with patch.dict(os.environ,{"GITHUB_STEP_SUMMARY":str(target)}):
                report=indexer.IndexingReport(translations_pending=4,translations_deferred=4)
                indexer.finish_indexing(report)
            text=target.read_text(encoding="utf-8")
            self.assertIn("진행 중",text)
            self.assertIn("| 처리량 제한으로 미시도 | 4 |",text)
            self.assertNotIn("## 인덱싱: 전체 완료",text)
