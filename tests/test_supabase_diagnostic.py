import base64
import importlib.util
import io
import json
from pathlib import Path
import unittest
from urllib.error import HTTPError

spec=importlib.util.spec_from_file_location("supabase_diagnostic",Path(__file__).resolve().parents[1]/"scripts/supabase_diagnostic.py")
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

class DiagnosticTests(unittest.TestCase):
    def env(self,key="sb_secret_test"):
        return {"SUPABASE_URL":"https://example.supabase.co","SUPABASE_KEY":key,"EXPECTED_SUPABASE_HOST":"example.supabase.co"}
    def response(self,count):
        class Response(io.BytesIO):
            status=200
            headers={"Content-Range":"0-0/"+str(count)}
        return Response(b'[{"page_id":"private-id"}]' if count else b"[]")
    def test_read_only_count_and_no_secrets_or_data(self):
        def open_request(req,timeout):
            self.assertEqual(req.method,"GET");self.assertEqual(timeout,15)
            self.assertNotIn("Authorization",req.headers)
            return self.response(155)
        result,code=d.diagnose(self.env(),open_request)
        self.assertEqual(code,0);self.assertEqual(result["visible_rows"],155)
        self.assertNotIn("sb_secret_test",json.dumps(result));self.assertNotIn("private-id",json.dumps(result))
    def test_zero_and_wrong_project_are_not_ready(self):
        for count,expected in ((0,"example.supabase.co"),(155,"another.supabase.co")):
            env=self.env();env["EXPECTED_SUPABASE_HOST"]=expected
            result,code=d.diagnose(env,lambda *a,**k:self.response(count))
            self.assertEqual(code,1);self.assertIn("error",result)
    def test_jwt_role_is_only_a_hint(self):
        payload=base64.urlsafe_b64encode(b'{"role":"anon"}').decode().rstrip("=")
        key="eyJ."+payload+".fake-signature"
        def open_request(req,**kwargs):
            self.assertEqual(req.headers["Authorization"],"Bearer "+key)
            return self.response(0)
        result,code=d.diagnose(self.env(key),open_request)
        self.assertEqual(result["declared_role"],"anon");self.assertEqual(code,1)
    def test_invalid_configuration_and_errors_do_not_leak_secrets(self):
        env=self.env();env["SUPABASE_URL"]="http://example.supabase.co"
        result,code=d.diagnose(env,lambda *a,**k:self.fail("network should not run"))
        self.assertEqual(code,1)
        def fail(*args,**kwargs):raise HTTPError("url",401,"sb_secret_test",{},None)
        result,code=d.diagnose(self.env(),fail)
        self.assertEqual(result["http_status"],401);self.assertNotIn("sb_secret_test",json.dumps(result))
