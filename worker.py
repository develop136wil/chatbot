import os
import json
import time
import traceback
import gc
import logging
import asyncio
from typing import List, Dict, Any, Tuple, Optional
from supabase import create_client
from dotenv import load_dotenv
from runtime_policy import normalize_intent, apply_search_filters, visible_question

# [신규] PyRedis AsyncIO
import redis.asyncio as redis

# 기본 utils 임포트
try:
    from utils import (
        search_supabase_async,       # [Async]
        expand_search_query_async,   # [Async] 
        rerank_search_results_async, # [Async]
        format_search_results, 
        localize_result_pages_async,
        save_response_cache_async,
        build_response_cache_scopes,
        get_response_cache_scope_versions_async,
        CATEGORIES,
        GLOBAL_CACHE_SCOPE,
        resolve_language,
        LOCALIZED_UI,
        supabase,
        notion
    )
    print("✅ utils (Async) 임포트 성공")
except ImportError as e:
    print(f"❌ utils 임포트 실패: {e}")
    # Vercel 환경 대비 Fallback
    logging.getLogger(__name__).error("Utils import failed: %s", type(e).__name__)
    search_supabase_async = None
    expand_search_query_async = None
    rerank_search_results_async = None

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("[Worker] 설정 로드 중...")
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
JOB_QUEUE_KEY = "chatbot:job_queue"
JOB_RESULTS_KEY = "chatbot:job_results"
JOB_RESULT_KEY_PREFIX = "chatbot:job_result:"
NOTION_LOG_DB_ID = os.getenv("NOTION_LOG_DB_ID", "")
NOTION_QUERY_LOGS_ENABLED = os.getenv("ENABLE_NOTION_QUERY_LOGS", "false").lower() == "true"
JOB_RESULTS_TTL_SECONDS = int(os.getenv("JOB_RESULTS_TTL_SECONDS", "3600"))
MAX_CONCURRENT_JOBS = max(1, int(os.getenv("MAX_CONCURRENT_JOBS", "2")))

# Redis 연결 설정
REDIS_URL = os.getenv("REDIS_URL", "").strip()
REDIS_HOST = os.getenv("REDIS_HOST", "localhost").strip()
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

logger.info("[Worker] 클라이언트 초기화 중...")

# --- 메인 처리 함수 (Async) ---
async def process_job_async(job_data):
    started = time.monotonic()
    original = job_data.get("question", "")
    info = normalize_intent(job_data.get("extracted_info") or {}, original)
    question = info["search_query"]
    language = resolve_language(job_data.get("language"), original)
    ui = LOCALIZED_UI[language]
    allow_ai = job_data.get("allow_ai", True)
    can_cache = bool(job_data.get("cacheable") and allow_ai)
    snapshot = await get_response_cache_scope_versions_async([GLOBAL_CACHE_SCOPE, *CATEGORIES]) if can_cache else None
    try:
        keywords = info["keywords"]
        if allow_ai:
            expanded = await expand_search_query_async(question)
            keywords = list(dict.fromkeys(keywords + expanded))[:12]
        else:
            keywords = keywords or visible_question(question).split()[:8]
        rows = await search_supabase_async(question, info, keywords=keywords, allow_ai=allow_ai)
        limited = not allow_ai or not getattr(rows, "cacheable", True)
        # 검색 장애는 search_supabase_async가 예외로 전달합니다. 빈 결과는 저장하지 않습니다.
        if not rows:
            return {"status":"complete", "answer":ui["not_found"] + (ui["limited"] if limited else ""),
                    "last_result_ids":[], "total_found":0, "shown_count":0, "mode":"keyword" if limited else "ai"}
        scopes = build_response_cache_scopes(rows)
        seen = set()
        candidates = []
        for row in rows:
            pid = (row.get("metadata") or {}).get("page_id") or row.get("page_id")
            if pid and pid not in seen:
                seen.add(pid)
                candidates.append(row)
        can_cache = can_cache and not limited and snapshot is not None
        ranked = candidates
        if allow_ai and not limited:
            try:
                ranked = await rerank_search_results_async(question, candidates)
            except Exception as error:
                logger.warning("랭킹 대체(SQL 순서): %s", type(error).__name__)
                can_cache = False
        ranked = apply_search_filters(ranked, info)[:20]
        if not ranked:
            return {"status":"complete", "answer":ui["not_found"], "last_result_ids":[],
                    "total_found":0, "shown_count":0}
        display = await localize_result_pages_async(ranked[:2], language, allow_live=not limited)
        body = format_search_results([r.get("metadata",r) for r in display], language)
        ids = [(r.get("metadata") or {}).get("page_id") or r.get("page_id") for r in ranked]
        answer = f"{ui['header_found']}<hr>{body}"
        if len(ids)>2:
            answer += f"<hr>{ui['footer_more']}"
        if limited:
            answer += ui["limited"]
        response = {"status":"complete", "answer":answer, "last_result_ids":ids,
                    "total_found":len(ids), "shown_count":min(2,len(ids)),
                    "mode":"keyword" if limited else "ai"}
        if can_cache:
            await save_response_cache_async(original, language, response, scopes=scopes, expected_versions=snapshot)
        logger.info("답변 완료 (mode=%s, seconds=%.2f)", response["mode"], time.monotonic()-started)
        if NOTION_QUERY_LOGS_ENABLED and notion and NOTION_LOG_DB_ID:
            # 서버리스 종료 전에 제한 시간 내 완료하도록 기다립니다.
            try:
                await asyncio.wait_for(save_notion_log_async(original, info["category"], keywords), 3)
            except asyncio.TimeoutError:
                logger.warning("Notion 질문 로그 저장 시간 초과")
        return response
    except Exception as error:
        logger.error("검색 처리 실패: %s", type(error).__name__)
        return {"status":"error", "message":ui["system_error"]}

# Notion 로그 저장을 위한 Async Wrapper
async def save_notion_log_async(question, category, keywords):
    try:
        loop = asyncio.get_running_loop()
        final_category = category if category else "미분류"
        await loop.run_in_executor(
            None,
            lambda: notion.pages.create(
                parent={"database_id": NOTION_LOG_DB_ID},
                properties={
                    "질문": {"title": [{"text": {"content": question}}]},
                    "카테고리": {"select": {"name": final_category}},
                    "키워드": {"multi_select": [{"name": k} for k in keywords[:5]]}
                }
            )
        )
    except Exception as e:
        logger.warning(f"⚠️ Notion 로그 저장 실패: {e}")

# 작업 핸들러 (Redis 응답용)
async def handle_job(redis_client, queue_item, semaphore):
    job_id = None
    try:
        _, payload = queue_item
        job_data = json.loads(payload.decode("utf-8"))
        job_id = job_data.get("job_id")
        result = await asyncio.wait_for(process_job_async(job_data), 38)
        result["job_id"] = job_id
        await redis_client.setex(f"{JOB_RESULT_KEY_PREFIX}{job_id}", JOB_RESULTS_TTL_SECONDS,
            json.dumps(result,ensure_ascii=False).encode("utf-8"))
    except Exception as error:
        logger.error("작업 처리 실패: %s", type(error).__name__)
        if job_id:
            try:
                await redis_client.setex(f"{JOB_RESULT_KEY_PREFIX}{job_id}", JOB_RESULTS_TTL_SECONDS,
                    json.dumps({"status":"error","message":"처리 중 오류가 발생했습니다."},ensure_ascii=False).encode("utf-8"))
            except Exception:
                logger.error("작업 실패 상태 저장 불가")
    finally:
        semaphore.release()

# --- 메인 루프 (Async) ---
async def start_worker_async():
    logger.info(f"🚀 Worker (Async) 가동! (PID: {os.getpid()})")
    
    # Redis Async Connection
    if REDIS_URL:
        r = redis.from_url(REDIS_URL, decode_responses=False)
    else:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=False)

    worker_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    
    # Connection Check
    while True:
        try:
            await r.ping()
            logger.info("✅ Redis 연결 성공")
            break
        except Exception:
            logger.warning("⏳ Redis 연결 대기 중...")
            await asyncio.sleep(2)
            
    while True:
        await worker_semaphore.acquire()
        try:
            # Async BLPOP
            result = await r.blpop(JOB_QUEUE_KEY, timeout=1)
            if result:
                # Fire and Forget (Concurrency!)
                # 각 작업은 독립된 Task로 실행되어, 다음 BLPOP을 즉시 수행함
                asyncio.create_task(handle_job(r, result, worker_semaphore))
            else:
                worker_semaphore.release()
                
        except Exception as e:
            logger.error(f"🔥 Worker Loop Error: {e}")
            worker_semaphore.release()
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(start_worker_async())
