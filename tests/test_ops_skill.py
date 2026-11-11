"""Offline behavioral tests of the local skill's summary verifier."""
import ast
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from scripts import check_skill_install as installation


SCRIPT = Path(__file__).resolve().parents[1] / "skills/chatbot-ops-verification/scripts/check_indexer_summary.py"
spec = importlib.util.spec_from_file_location("ops_skill_summary", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def complete(**changes):
    value = {key: 0 for key in checker.COUNTS}
    value.update({key: False for key in checker.FLAGS})
    value.update(status="complete", discovered=155, skipped=155)
    value.update(changes)
    return value


class OpsSkillTests(unittest.TestCase):
    def test_install_comparison_detects_missing_extra_and_changed(self):
        with tempfile.TemporaryDirectory(prefix="skill-copy-check-") as folder:
            source, installed = Path(folder) / "source", Path(folder) / "installed"
            source.mkdir()
            installed.mkdir()
            for path in (source, installed):
                (path / "SKILL.md").write_text("same", encoding="utf-8")
            self.assertTrue(installation.compare(source, installed)["identical"])
            (source / "missing.md").write_text("needed", encoding="utf-8")
            (installed / "extra.md").write_text("unexpected", encoding="utf-8")
            (installed / "SKILL.md").write_text("outdated", encoding="utf-8")
            result = installation.compare(source, installed)
            self.assertFalse(result["identical"])
            self.assertEqual(result["missing"], ["missing.md"])
            self.assertEqual(result["extra"], ["extra.md"])
            self.assertEqual(result["changed"], ["SKILL.md"])

    def test_install_comparison_ignores_bytecode_only(self):
        with tempfile.TemporaryDirectory(prefix="skill-copy-check-") as folder:
            source, installed = Path(folder) / "source", Path(folder) / "installed"
            for path in (source, installed):
                path.mkdir()
                (path / "SKILL.md").write_text("same", encoding="utf-8")
            (installed / "__pycache__").mkdir()
            (installed / "__pycache__/cached.pyc").write_bytes(b"not-a-source-file")
            self.assertTrue(installation.compare(source, installed)["identical"])

    def test_install_comparison_requires_skill_directories(self):
        with tempfile.TemporaryDirectory(prefix="skill-copy-check-") as folder:
            with self.assertRaises(ValueError):
                installation.compare(Path(folder), Path(folder))

    def test_inconsistent_translation_counts_never_pass(self):
        for changes in (
            {"translations_completed": 1},
            {"translations_attempted": 1},
            {"updated": 1, "skipped": 154, "translations_attempted": 1},
            {"updated": 1, "skipped": 154, "translations_attempted": 2, "translations_completed": 2},
        ):
            with self.subTest(changes=changes):
                result = checker.assess(complete(**changes))
                self.assertEqual(result["summary_verdict"], "unverified")
                self.assertIn("translation_counts_inconsistent", result["notes"])

    def test_attempts_need_not_equal_completed_documents(self):
        # Attempts can be per chunk; completed/updated are counted per page.
        result = checker.assess(complete(updated=1, skipped=154,
                                         translations_attempted=2, translations_completed=1))
        self.assertEqual(result["summary_verdict"], "complete")

    def test_real_failure_is_not_downgraded_to_unverified(self):
        result = checker.assess(complete(status="failed", failed_pages=1,
                                         translations_completed=2))
        self.assertEqual(result["summary_verdict"], "failed")

    def test_unknown_schema_cannot_silently_pass(self):
        result = checker.assess(complete(new_provider_failed=True))
        self.assertEqual(result["summary_verdict"], "unverified")
        self.assertIn("unknown_summary_fields", result["notes"])

    def test_summary_schema_matches_production_without_importing_app(self):
        tree = ast.parse((SCRIPT.parents[3] / "run_indexer.py").read_text(encoding="utf-8-sig"))
        report = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == "IndexingReport")
        fields = {node.target.id: node.annotation.id for node in report.body
                  if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}
        self.assertEqual(set(checker.COUNTS), {name for name, kind in fields.items() if kind == "int"})
        self.assertEqual(set(checker.FLAGS), {name for name, kind in fields.items() if kind == "bool"})
        self.assertEqual(set(fields), set(checker.COUNTS + checker.FLAGS))

    def test_all_skipped_is_not_translation_quality_evidence(self):
        result = checker.assess(complete())
        self.assertEqual(result["summary_verdict"], "complete")
        self.assertIn("all_skipped_no_new_translation_evidence", result["notes"])
        self.assertFalse(result["translation_quality_verified"])
        self.assertFalse(result["run_identity_verified"])

    def test_updated_summary_still_does_not_verify_semantic_quality(self):
        result = checker.assess(complete(updated=1, skipped=154,
                                       translations_attempted=1, translations_completed=1))
        self.assertEqual(result["summary_verdict"], "complete")
        self.assertFalse(result["translation_quality_verified"])

    def test_legitimate_document_count_change_is_not_failure(self):
        for count in (154, 156):
            self.assertEqual(checker.assess(complete(discovered=count, skipped=count))["summary_verdict"], "complete")

    def test_empty_discovery_needs_baseline_review(self):
        self.assertIn("empty_discovery_requires_baseline_review",
                      checker.assess(complete(discovered=0, skipped=0))["notes"])

    def test_planned_backlog_is_not_complete(self):
        result = checker.assess(complete(status="in_progress", skipped=150,
                                         translations_pending=5, translations_deferred=5))
        self.assertEqual(result["summary_verdict"], "in_progress")

    def test_each_error_overrides_claimed_complete(self):
        for key in checker.ERROR_COUNTS + checker.FLAGS:
            with self.subTest(key=key):
                value = True if key in checker.FLAGS else 1
                self.assertEqual(checker.assess(complete(**{key: value}))["summary_verdict"], "failed")

    def test_unclassified_pending_is_failure(self):
        result = checker.assess(complete(translations_pending=1))
        self.assertEqual(result["summary_verdict"], "failed")
        self.assertIn("pending_counts_inconsistent", result["notes"])

    def test_contradictory_status_never_passes(self):
        self.assertEqual(checker.assess(complete(status="failed"))["summary_verdict"], "unverified")

    def test_missing_or_invalid_fields_never_pass(self):
        for key in ("status",) + checker.COUNTS + checker.FLAGS:
            value = complete()
            del value[key]
            self.assertEqual(checker.assess(value)["summary_verdict"], "unverified")
        for changes in ({"discovered": -1}, {"failed_pages": False},
                        {"failed_pages": "0"}, {"cache_refresh_failed": 0}, {"status": "secret"}):
            self.assertEqual(checker.assess(complete(**changes))["summary_verdict"], "unverified")

    def test_document_count_mismatch_never_passes(self):
        self.assertEqual(checker.assess(complete(skipped=154))["summary_verdict"], "unverified")

    def test_unknown_sensitive_fields_are_not_forwarded(self):
        output = json.dumps(checker.assess(complete(question="private-test-content", token="private-test-token")))
        self.assertNotIn("private-test", output)

    def test_one_log_summary_and_pure_json_supported(self):
        payload = json.dumps(complete())
        self.assertEqual(checker.parse_summary(payload), complete())
        self.assertEqual(checker.parse_summary("INFO start\nINFO [Indexer Summary] " + payload + "\nINFO done"), complete())

    def test_multiple_truncated_duplicate_and_missing_summaries_rejected(self):
        marker = "[Indexer Summary] " + json.dumps(complete())
        for text in (marker + "\n" + marker, '{"status":', '{"status":"failed","status":"complete"}', "INFO only"):
            with self.assertRaises(ValueError):
                checker.parse_summary(text)

    def test_cli_exit_codes_and_sanitized_failure(self):
        with tempfile.TemporaryDirectory(prefix="chatbot-skill-test-") as folder:
            path = Path(folder) / "summary.json"
            for payload, expected in ((json.dumps(complete()), 0),
                                      (json.dumps(complete(status="in_progress", translations_pending=2, translations_deferred=2)), 1),
                                      (json.dumps(complete(status="failed", setup_failed=True)), 1),
                                      ("private-test-invalid-input", 2)):
                path.write_text(payload, encoding="utf-8")
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(checker.main([str(path)]), expected)
                self.assertNotIn("private-test", output.getvalue())


if __name__ == "__main__":
    unittest.main()
