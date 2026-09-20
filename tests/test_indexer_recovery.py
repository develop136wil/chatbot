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
    for lang in ("en", "vi", "zh"):
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
        translations = {lang: {"title": "title", "content": "summary"} for lang in ("en", "zh", "vi")}
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
