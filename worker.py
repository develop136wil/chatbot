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
        resolve_language,
        LOCALIZED_UI,
        supabase,
        notion
    )
    print("✅ utils (Async) 임포트 성공")
except ImportError as e:
    print(f"❌ utils 임포트 실패: {e}")
    # Vercel 환경 대비 Fallback
    logger.error(f"Utils import failed: {e}")
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
NOTION_LOG_DB_ID = "2bf8ade502108000b6d6f4ad4d4d52b2"
NOTION_QUERY_LOGS_ENABLED = os.getenv("ENABLE_NOTION_QUERY_LOGS", "false").lower() == "true"
JOB_RESULTS_TTL_SECONDS = int(os.getenv("JOB_RESULTS_TTL_SECONDS", "3600"))
MAX_CONCURRENT_JOBS = max(1, int(os.getenv("MAX_CONCURRENT_JOBS", "2")))

# Redis 연결 설정
REDIS_URL = os.getenv("REDIS_URL", "").strip()
REDIS_HOST = os.getenv("REDIS_HOST", "localhost").strip()
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

logger.info("[Worker] 클라이언트 초기화 중...")

# --- 메인 처리 함수 (Async) ---
async def process_job_async(job_data: Dict[str, Any]) -> Tuple[str, List[str], int]:
    start_time = time.time()
    question = job_data.get("question", "")
    ai_category = job_data.get("ai_category")
    target_lang_code = resolve_language(job_data.get("language"), question)
    ui_text = LOCALIZED_UI[target_lang_code]
    
    logger.info("Worker 작업 시작 (질문 글자 수=%s, 언어=%s)", len(question), target_lang_code)

    try:
        # [Step 1] 키워드 추출 (Async)
        try:
            print("[Worker] keyword expansion started")
            target_keywords = await expand_search_query_async(question)
            print("[Worker] keyword expansion completed")
        except Exception as e:
            logger.error(f"❌ 키워드 확장 실패: {e}")
            target_keywords = []

        # 원본 보완
        for word in question.split():
            if len(word) > 1 and word not in target_keywords:
                target_keywords.append(word)
        logger.info("검색 키워드 추출 완료 (개수=%s)", len(target_keywords))

        # [Step 2] 검색 (Async)
        extracted_info_mock = {"category": ai_category}
        try:
            print("[Worker] Supabase search started")
            raw_results = await search_supabase_async(question, extracted_info_mock, keywords=target_keywords)
            print(f"[Worker] Supabase search completed (results={len(raw_results or [])})")
        except Exception as e:
            logger.error(f"❌ Supabase 검색 실패: {e}")
            return ui_text["system_error"], [], 0

        if not raw_results: 
            if job_data.get("cacheable"):
                await save_response_cache_async(
                    question,
                    target_lang_code,
                    {"status": "complete", "answer": ui_text["not_found"], "last_result_ids": [], "total_found": 0},
                    scopes=["__all__"],
                )
            return ui_text["not_found"], [], 0

        # [Step 3] 중복 제거 (CPU Bound - Fast enough)
        seen_ids = set()
        unique_results = []
        for doc in raw_results:
            meta = doc.get("metadata", {})
            pid = meta.get("page_id") or meta.get("page_url") or meta.get("title")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                unique_results.append(doc)
        candidates = unique_results

        # [Step 4] AI 랭킹 (Async)
        logger.info(f"🤖 Gemini에게 {len(candidates)}개 문서의 랭킹을 요청합니다.")
        try:
            reranked_results = await rerank_search_results_async(question, candidates)
            if not reranked_results:
                reranked_results = candidates
        except Exception as e:
            logger.error(f"❌ AI 랭킹 중 오류: {e}")
            reranked_results = candidates

        # [Step 5] 최종 결과 조립
        display_count = min(len(reranked_results), 2)
        display_results = reranked_results[:display_count]
        # 화면 현지화가 원본 카테고리명을 바꾸기 전에 캐시 무효화 범위를 고정합니다.
        cache_scopes = build_response_cache_scopes(reranked_results, ai_category)
        
        display_results = await localize_result_pages_async(display_results, target_lang_code)

        all_page_ids = [r.get("metadata", {}).get("page_id") for r in reranked_results]
        final_display_metadata = [res.get("metadata", {}) for res in display_results]
        
        try:
            body = format_search_results(final_display_metadata, target_lang_code)
        except Exception as e:
            logger.error(f"❌ 결과 포맷팅 실패: {e}")
            body = ui_text["system_error"]
        
        header = ui_text["header_found"]
        final_answer = f"{header}<hr>{body}"

        if len(reranked_results) > display_count:
            final_answer += f"<hr>{ui_text['footer_more']}"

        if job_data.get("cacheable"):
            await save_response_cache_async(
                question,
                target_lang_code,
                {
                    "status": "complete",
                    "answer": final_answer,
                    "last_result_ids": all_page_ids,
                    "total_found": len(all_page_ids),
                },
                scopes=cache_scopes,
            )

        elapsed = time.time() - start_time
        logger.info(f"✅ [Async] 답변 조립 완료 (소요시간: {elapsed:.2f}초)")
        
        # 로그 저장 (Notion은 Sync이므로 run_in_executor 사용 권장하나, 여기선 생략하고 Fire & Forget 흉내)
        # 실제로는 별도 Task로 띄울 수 있음
        if NOTION_QUERY_LOGS_ENABLED and notion and NOTION_LOG_DB_ID:
            asyncio.create_task(save_notion_log_async(question, ai_category, target_keywords))
                
        return final_answer, all_page_ids, len(all_page_ids)

    except Exception as e:
        logger.error(f"🔥 작업 처리 중 치명적 오류: {e}")
        traceback.print_exc()
        return ui_text["system_error"], [], 0

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
        _, job_json = queue_item
        job_data = json.loads(job_json.decode('utf-8'))
        job_id = job_data.get("job_id")
        
        # Async Job Execution
        answer_text, all_ids, total_found = await process_job_async(job_data)
        
        final_result = {
            "status": "complete",
            "answer": answer_text,
            "last_result_ids": all_ids, 
            "total_found": total_found 
        }
        
        # 결과 저장
        await redis_client.setex(
            f"{JOB_RESULT_KEY_PREFIX}{job_id}",
            JOB_RESULTS_TTL_SECONDS,
            json.dumps(final_result, ensure_ascii=False).encode("utf-8"),
        )
        
        logger.info("작업 결과 저장 완료 (job_id=%s)", job_id)
        
    except Exception as e:
        logger.error(f"Handler Error: {e}")
        if job_id:
            error_result = {
                "status": "error",
                "message": "처리 중 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
            }
            try:
                await redis_client.setex(
                    f"{JOB_RESULT_KEY_PREFIX}{job_id}",
                    JOB_RESULTS_TTL_SECONDS,
                    json.dumps(error_result, ensure_ascii=False).encode("utf-8"),
                )
            except Exception as store_error:
                logger.error(f"Failed to save job error result: {store_error}")
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
