"""Run ONLY against the disposable localhost CI database, never Supabase."""
import os
import unittest
import uuid
from pathlib import Path

@unittest.skipUnless(os.getenv("CHATBOT_ANALYTICS_SQL_TEST")=="1","Disposable Postgres test only")
class SQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.db=psycopg.connect(host="127.0.0.1",port=int(os.environ["CHATBOT_TEST_PG_PORT"]),
            dbname="chatbot_analytics_test",user="postgres",password="test-only",autocommit=True)
        cls.db.execute("do $$ begin create role anon; create role authenticated; create role service_role bypassrls; end $$;")
        sql=Path("supabase/20260921_analytics.sql").read_text(encoding="utf-8")
        cls.db.execute(sql);cls.db.execute(sql)  # reapplication must be safe
        ja_sql=Path("supabase/20260921_japanese_language.sql").read_text(encoding="utf-8")
        cls.db.execute(ja_sql);cls.db.execute(ja_sql)
        cls.db.execute("grant usage on schema public to anon,authenticated,service_role")

    @classmethod
    def tearDownClass(cls): cls.db.close()

    def setUp(self):
        self.db.execute("truncate public.chatbot_analytics_requests,public.chatbot_analytics_daily")
        self.id=uuid.uuid4();self.attempt=uuid.uuid4()

    def begin(self,record=None,attempt=None):
        return self.db.execute("select public.chatbot_analytics_begin(%s,%s,%s,'question','ko','qr','typed')",
            (record or self.id,attempt or self.attempt,"a"*64)).fetchone()[0]

    def finish(self,outcome="answered",attempt=None):
        return self.db.execute("select public.chatbot_analytics_finish(%s,%s,'question',%s,'의료/재활',true,true,1400)",
            (self.id,attempt or self.attempt,outcome)).fetchone()[0]

    def stats(self):
        return self.db.execute("select public.chatbot_analytics_report(current_date-1,current_date+1)").fetchone()[0]

    def test_japanese_record_survives_migration_reapplication_and_is_reported(self):
        self.db.execute("select public.chatbot_analytics_begin(%s,%s,%s,'question','ja','qr','typed')",
            (self.id,self.attempt,"a"*64))
        self.finish()
        self.db.execute(Path("supabase/20260921_japanese_language.sql").read_text(encoding="utf-8"))
        stats=self.stats()["days"][0]["stats"]
        self.assertEqual(stats["languages"]["ja"],1)
        self.assertEqual(stats["questions"],1)

    def test_terminal_duplicate_does_not_increase_questions(self):
        self.assertEqual(self.begin(),self.attempt);self.assertTrue(self.finish())
        self.assertIsNone(self.begin(attempt=uuid.uuid4()))
        self.assertFalse(self.finish())
        stats=self.stats()["days"][0]["stats"]
        self.assertEqual(stats["questions"],1);self.assertEqual(stats["answered"],1)

    def test_retry_and_late_completion_are_idempotent(self):
        self.begin();self.finish("error")
        latest=uuid.uuid4();self.begin(attempt=latest)
        self.assertFalse(self.finish(attempt=self.attempt));self.assertTrue(self.finish(attempt=latest))
        stats=self.stats()["days"][0]["stats"]
        self.assertEqual(stats["questions"],1);self.assertEqual(stats["retry_attempts"],1)
        self.assertEqual(stats["errors"],0);self.assertEqual(stats["answered"],1)

    def test_click_only_for_answered_and_only_once(self):
        self.begin()
        call=lambda:self.db.execute("select public.chatbot_analytics_click(%s)",(self.id,)).fetchone()[0]
        self.assertFalse(call());self.finish();self.assertTrue(call());self.assertFalse(call())
        self.assertEqual(self.stats()["days"][0]["stats"]["source_clicks"],1)

    def test_anon_cannot_read_or_execute(self):
        import psycopg
        self.db.execute("set role anon")
        try:
            for sql in ("select * from public.chatbot_analytics_requests",
                        "select public.chatbot_analytics_report(current_date,current_date)",
                        "select public.chatbot_analytics_maintain()"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): self.db.execute(sql)
        finally: self.db.execute("reset role")

    def test_service_role_can_write_and_read(self):
        self.db.execute("set role service_role")
        try: self.begin();self.finish();self.assertEqual(self.stats()["days"][0]["stats"]["questions"],1)
        finally:self.db.execute("reset role")

    def test_retention_keeps_rollup_after_raw_removal(self):
        self.begin();self.finish()
        self.db.execute("update public.chatbot_analytics_requests set day=current_date-100")
        self.db.execute("select public.chatbot_analytics_maintain()")
        self.assertEqual(self.db.execute("select count(*) from public.chatbot_analytics_requests").fetchone()[0],0)
        self.db.execute("select public.chatbot_analytics_maintain()")
        saved=self.db.execute("select stats from public.chatbot_analytics_daily").fetchone()[0]
        self.assertEqual(saved["questions"],1)

    def test_more_not_counted_as_new_question(self):
        self.begin()
        self.db.execute("select public.chatbot_analytics_finish(%s,%s,'more','answered','의료/재활',false,false,100)",
                        (self.id,self.attempt))
        stats=self.stats()["days"][0]["stats"]
        self.assertEqual(stats["questions"],0);self.assertEqual(stats["more"],1)

    def test_report_refreshes_pending_to_finished_and_does_not_double_count(self):
        self.begin();self.assertEqual(self.stats()["days"][0]["stats"]["pending"],1)
        self.finish();s=self.stats()["days"][0]["stats"]
        self.assertEqual(s["pending"],0);self.assertEqual(s["answered"],1)
        self.assertEqual(self.stats()["days"][0]["stats"]["answered"],1)

if __name__=="__main__":unittest.main()
