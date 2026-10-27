"""Operations regression tests: no real SMTP, provider or database traffic."""
import json
import os
import unittest
from unittest.mock import Mock, patch
import test_no_sql_contract as isolation

def setUpModule():
    global indexer, main
    isolation.setUpModule()
    import run_indexer as indexer
    import main

def tearDownModule():
    isolation.tearDownModule()

class AlertTests(unittest.TestCase):
    def test_every_final_failure_alerts_once(self):
        reports=[
            indexer.IndexingReport(translations_pending=1,translations_failed=1),
            indexer.IndexingReport(cache_refresh_failed=True),
            indexer.IndexingReport(setup_failed=True),
            indexer.IndexingReport(failed_pages=1),
            indexer.IndexingReport(failed_categories=2),
            indexer.IndexingReport(cleanup_failed=True),
        ]
        for report in reports:
            with self.subTest(report=report):
                with patch.object(indexer,"run_indexing",side_effect=indexer.IndexingIncomplete(report)), patch.object(indexer,"send_email_alert") as send:
                    self.assertEqual(indexer.cli(),1)
                    send.assert_called_once()
                    self.assertEqual(json.loads(send.call_args.args[1])["status"],"failed")

    def test_complete_and_planned_backlog_do_not_send_failure_email(self):
        for report in (indexer.IndexingReport(),indexer.IndexingReport(translations_pending=5,translations_deferred=5)):
            with patch.object(indexer,"run_indexing",return_value=report), patch.object(indexer,"send_email_alert") as send:
                self.assertEqual(indexer.cli(),0);send.assert_not_called()

    def test_unexpected_failure_alert_contains_only_type(self):
        with patch.object(indexer,"run_indexing",side_effect=RuntimeError("secret-body")), patch.object(indexer,"send_email_alert") as send:
            self.assertEqual(indexer.cli(),1)
            send.assert_called_once()
            self.assertNotIn("secret-body",send.call_args.args[1])

    def test_smtp_has_timeout_and_no_sensitive_error_log(self):
        with patch.dict(os.environ,{"SMTP_USER":"test@example.org","SMTP_PASSWORD":"fake-secret"}):
            with patch.object(indexer.smtplib,"SMTP",side_effect=TimeoutError("fake-secret")) as smtp:
                with self.assertLogs(indexer.logger,level="ERROR") as logs:
                    indexer.send_email_alert("Test","Counts only")
                smtp.assert_called_once_with("smtp.gmail.com",587,timeout=10)
                self.assertNotIn("fake-secret"," ".join(logs.output))

    def test_category_failure_no_longer_sends_per_category_email(self):
        # Guard the once-per-run policy; actual recovery tests exercise category errors.
        import inspect
        self.assertNotIn("send_email_alert(",inspect.getsource(indexer.run_indexing))

class AdminTests(unittest.TestCase):
    def test_query_secret_is_rejected_and_header_is_accepted(self):
        from fastapi.testclient import TestClient
        redis=Mock();redis.scan_iter.return_value=[]
        with patch.object(main,"ADMIN_SECRET_KEY","offline-secret"),patch.object(main,"redis_client",redis):
            with TestClient(main.app) as client:
                self.assertEqual(client.post("/admin/clear_cache?secret=offline-secret").status_code,401)
                redis.delete.assert_not_called()
                self.assertEqual(client.post("/admin/clear_cache",headers={"X-Admin-Secret":"offline-secret"}).status_code,200)
                self.assertTrue(redis.delete.called)
