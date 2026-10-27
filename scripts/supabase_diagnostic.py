"""Read-only configuration check. Never prints keys, tokens or document contents."""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


def key_info(key):
    if key.startswith("sb_secret_"):
        return {"key_type": "secret", "declared_role": "server_key"}
    if key.startswith("sb_publishable_"):
        return {"key_type": "publishable", "declared_role": "public_key"}
    try:
        segment = key.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        role = payload.get("role")
        return {"key_type": "jwt", "declared_role": role if role in ("anon", "authenticated", "service_role") else "unknown"}
    except (ValueError, IndexError, TypeError, AttributeError):
        return {"key_type": "unknown", "declared_role": "unknown"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None  # Never forward credentials to another URL.


def diagnose(env=None, opener=None):
    env = os.environ if env is None else env
    url, key = env.get("SUPABASE_URL", "").strip(), env.get("SUPABASE_KEY", "").strip()
    parsed = urllib.parse.urlsplit(url)
    result = {"project_match": False, "visible_rows": None}
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not re.fullmatch(r"[a-z0-9-]+\.supabase\.co", host) or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment or parsed.path not in ("", "/") or not key:
        result["error"] = "invalid_configuration"
        return result, 1
    expected = env.get("EXPECTED_SUPABASE_HOST", "").strip().lower()
    result.update(project_host=host, project_match=(host == expected), **key_info(key))
    # JWT role is only a decoded hint; the server decides actual authorization.
    headers = {"apikey": key, "Prefer": "count=exact", "Accept": "application/json"}
    if result["key_type"] == "jwt":
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request("https://" + host + "/rest/v1/site_pages?select=page_id&limit=1", headers=headers, method="GET")
    try:
        open_request = opener or urllib.request.build_opener(NoRedirect).open
        with open_request(req, timeout=15) as response:
            result["http_status"] = response.status
            data = json.loads(response.read(65536))
            if not isinstance(data, list):
                raise ValueError("Unexpected response")
            total = response.headers.get("Content-Range", "").rsplit("/", 1)[-1]
            result["visible_rows"] = int(total) if total.isdigit() else len(data)
    except urllib.error.HTTPError as error:
        result.update(http_status=error.code, error="http_error")
        error.close()
        return result, 1
    except Exception as error:
        result["error"] = "request_failed"
        return result, 1
    if not result["project_match"]:
        result["error"] = "project_mismatch"
    elif result["visible_rows"] == 0:
        result["error"] = "no_visible_index_rows"
    return result, int("error" in result)


def main():
    try:
        result, code = diagnose()
    except Exception:
        result, code = {"error": "invalid_configuration"}, 1
    print("[Supabase Diagnostic] " + json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
