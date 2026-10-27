"""The manual email command is gated, self-addressed and never retries."""
import importlib.util
import os
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    "alert_email_command", Path(__file__).resolve().parents[1] / "scripts/test_alert_email.py"
)
command = importlib.util.module_from_spec(spec)
spec.loader.exec_module(command)

class EmailCommandTests(unittest.TestCase):
    def test_missing_confirmation_never_sends(self):
        sender = Mock()
        with patch.dict(os.environ, {}, clear=True), patch.dict(
            "sys.modules", {"run_indexer": types.SimpleNamespace(send_email_alert=sender)}
        ):
            self.assertEqual(command.main(), 2)
        sender.assert_not_called()

    def test_missing_settings_never_sends(self):
        sender = Mock()
        with patch.dict(os.environ, {"CONFIRM_ALERT_EMAIL_TEST": "send-once"}, clear=True), patch.dict(
            "sys.modules", {"run_indexer": types.SimpleNamespace(send_email_alert=sender)}
        ):
            self.assertEqual(command.main(), 2)
        sender.assert_not_called()

    def test_one_attempt_to_sender_only_and_honest_exit_status(self):
        for accepted, exit_code in ((True, 0), (False, 1)):
            with self.subTest(accepted=accepted):
                sender = Mock(return_value=accepted)
                env = {"CONFIRM_ALERT_EMAIL_TEST": "send-once", "SMTP_USER": "sender@example.org",
                       "SMTP_PASSWORD": "fake-secret", "ALERT_EMAIL_RECIPIENT": "other@example.org"}
                with patch.dict(os.environ, env, clear=True), patch.dict(
                    "sys.modules", {"run_indexer": types.SimpleNamespace(send_email_alert=sender)}
                ):
                    self.assertEqual(command.main(), exit_code)
                    self.assertEqual(os.environ["ALERT_EMAIL_RECIPIENT"], env["SMTP_USER"])
                sender.assert_called_once()
                self.assertNotIn("fake-secret", " ".join(sender.call_args.args))
