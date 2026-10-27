"""Explicit, one-attempt SMTP self-test. Never runs the indexer or retries."""
import os
from pathlib import Path
import sys

def main():
    if os.getenv("CONFIRM_ALERT_EMAIL_TEST") != "send-once":
        print("Email test not authorized; nothing sent.")
        return 2
    sender = os.getenv("SMTP_USER")
    if not sender or not os.getenv("SMTP_PASSWORD"):
        print("Email test configuration missing; nothing sent.")
        return 2
    # The authorized destination is the configured sender, never an input address.
    os.environ["ALERT_EMAIL_RECIPIENT"] = sender
    os.environ["VERCEL_ENV"] = "email-test"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from run_indexer import send_email_alert
    accepted = send_email_alert(
        "[Chatbot] 알림 메일 수신 테스트",
        "운영 알림 연결 확인을 위한 승인된 테스트 메일입니다.\n"
        "실제 서비스 오류가 아닙니다.\n"
        "이 메일에는 대화 내용이나 서비스 데이터가 포함되어 있지 않습니다.",
    )
    if accepted:
        print("EMAIL_TEST_SMTP_ACCEPTED: one attempt; inbox receipt requires user confirmation.")
        return 0
    print("EMAIL_TEST_FAILED_OR_UNCERTAIN: no automatic retry; inspect before any resend.")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
