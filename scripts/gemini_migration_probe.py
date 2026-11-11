"""Explicit, bounded Gemini-only probe. Synthetic data; no DB/cache/indexer writes."""
import argparse
import asyncio
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import logging
import os
from pathlib import Path
import sys
from unittest.mock import patch

import httpx

MODEL = "gemini-3.5-flash-lite"
LIMIT = 7


class ProbeStopped(RuntimeError):
    pass


class Budget:
    def __init__(self):
        self.stage = None
        self.requests = []
        self.stopped = False

    def before(self, request):
        if (self.stopped or not self.stage or len(self.requests) >= LIMIT
                or any(item["stage"] == self.stage for item in self.requests)
                or request.method != "POST" or request.url.scheme != "https"
                or request.url.host != "generativelanguage.googleapis.com"
                or request.url.path != f"/v1beta/models/{MODEL}:generateContent"
                or request.url.port not in (None, 443)):
            self.stopped = True
            raise ProbeStopped("probe_budget_or_destination")
        self.requests.append({"stage": self.stage})

    def after(self, response):
        self.requests[-1]["http_status"] = response.status_code
        if response.status_code != 200:
            self.stopped = True
        else:
            body = response.json()
            self.requests[-1]["model_version"] = body.get("modelVersion")
            reason = (body.get("candidates") or [{}])[0].get("finishReason")
            self.requests[-1]["finish_reason"] = reason
            if not str(body.get("modelVersion", "")).startswith(MODEL) or reason != "STOP":
                self.stopped = True


class SyncTransport(httpx.BaseTransport):
    def __init__(self, budget):
        self.budget = budget
        self.inner = httpx.HTTPTransport(retries=0)

    def handle_request(self, request):
        self.budget.before(request)
        try:
            response = self.inner.handle_request(request)
            response.read()
            self.budget.after(response)
            return response
        except Exception:
            self.budget.stopped = True
            raise ProbeStopped("probe_transport_failed") from None

    def close(self):
        self.inner.close()


class AsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, budget):
        self.budget = budget
        self.inner = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request):
        self.budget.before(request)
        try:
            response = await self.inner.handle_async_request(request)
            await response.aread()
            self.budget.after(response)
            return response
        except Exception:
            self.budget.stopped = True
            raise ProbeStopped("probe_transport_failed") from None

    async def aclose(self):
        await self.inner.aclose()


async def probe(key, report):
    import utils
    budget = Budget()
    report["requests"] = budget.requests
    with httpx.Client(transport=SyncTransport(budget), follow_redirects=False) as sync_http:
        async with httpx.AsyncClient(transport=AsyncTransport(budget), follow_redirects=False) as async_http:
            client = utils.genai.Client(api_key=key, http_options=utils.types.HttpOptions(
                httpx_client=sync_http, httpx_async_client=async_http,
                retry_options=utils.types.HttpRetryOptions(attempts=1), timeout=15000))
            try:
                with patch.object(utils, "LLM_CLIENT", client), \
                     patch.object(utils, "get_llm_client", return_value=client):
                    questions = {
                        "ko": "24개월 아이의 아동수당이 궁금해요",
                        "en": "What child allowance is available for my 24-month-old child?",
                        "vi": "Tôi muốn biết về trợ cấp trẻ em cho con 24 tháng tuổi.",
                        "zh": "我想了解24个月孩子的儿童津贴。",
                        "ja": "24か月の子どもの児童手当について知りたいです。",
                    }
                    for lang, question in questions.items():
                        budget.stage = "intent_" + lang
                        info = await utils.extract_info_from_question_async(question)
                        if (budget.stopped or info.get("age") != 24
                                or info.get("intent") not in (None, "search") or not info.get("keywords")
                                or info.get("category") is not None):
                            report["failed_stage"] = budget.stage
                            return 1
                        report["checks"][budget.stage] = info
                    docs = [{"page_id": str(i), "metadata": {"title": title, "pre_summary": content}}
                            for i, (title, content) in enumerate([
                                ("가상 노인 지원", "65세 이상만 대상"),
                                ("가상 학생 지원", "18세 이상 대학생만 대상"),
                                ("가상 영유아 양육지원", "도봉구 거주 24~35개월 아동만 대상. 월 123,456원."),
                                ("가상 초등학교 지원", "7~12세만 대상"),
                                ("가상 출산 준비 지원", "임신 중인 경우만 대상"),
                                ("가상 기타 지원", "기타 자료"),
                            ])]
                    budget.stage = "ranking"
                    ranked = await utils.rerank_search_results_async("도봉구 24개월 아이의 양육지원", docs)
                    if budget.stopped or ranked[0]["page_id"] != "2" or sorted(d["page_id"] for d in ranked) != [str(i) for i in range(6)]:
                        report["failed_stage"] = budget.stage
                        return 1
                    report["checks"]["ranking"] = [doc["page_id"] for doc in ranked]
                    budget.stage = "translation"
                    translated = utils.translate_content_multilingual_sync(
                        "가상 영유아 양육지원 (실제 정책 아님)",
                        "도봉구에 거주하는 24~35개월 아동만 대상입니다. 월 123,456원을 지급합니다. "
                        "신청 비용은 0원입니다. 36개월 이상은 대상에서 제외됩니다. "
                        "신청 기간은 2026-11-01부터 2026-11-30까지입니다.")
                    report["checks"]["translation"] = translated
                    if budget.stopped or utils.missing_languages(translated, ["en", "vi", "zh", "ja"]):
                        report["failed_stage"] = budget.stage
                        return 1
                    report["status"] = "response_checks_passed_semantic_review_required"
                    return 0
            finally:
                await client.aio.aclose()
                client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicit authorization for at most 7 requests")
    args = parser.parse_args()
    if not args.live:
        print("No network calls. Use --live only after approval of the bounded probe.")
        return 2
    from dotenv import dotenv_values
    root = Path(__file__).resolve().parents[1]
    values = dotenv_values(root / ".env", interpolate=False)
    # Match the application's first-key selection; never rotate or print it.
    combined = os.environ.get("GEMINI_API_KEYS") or values.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY") or values.get("GEMINI_API_KEY") or ""
    keys = [value.strip() for value in combined.split(",") if value.strip()]
    if not keys:
        print("Missing Gemini key; no request sent.")
        return 2
    env = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP") if name in os.environ}
    env.update(VERCEL_ENV="production", FREE_TIER_ONLY="true", ALLOW_FREE_TIER_GROQ_FALLBACK="false",
               ALLOW_LIVE_TRANSLATION="false", GEMINI_GENERATION_MODEL=MODEL,
               ENABLE_RESPONSE_CACHE="false", ENABLE_CHAT_ANALYTICS="false")
    report = {"status": "failed_or_incomplete", "model": MODEL, "checks": {},
              "credential_source": "existing_local_configuration", "production_key_match": "unverified"}
    sys.path.insert(0, str(root))
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with patch.dict(os.environ, env, clear=True), patch("dotenv.load_dotenv", return_value=False), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            try:
                code = asyncio.run(probe(keys[0], report))
            except Exception as error:
                report["error_type"] = type(error).__name__  # Never print provider errors/keys.
                code = 1
    finally:
        logging.disable(previous_logging)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
