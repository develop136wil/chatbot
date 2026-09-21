# main.py - Optimized Version
import os
import json
import uuid
import analytics
import logging
import asyncio
import time
from observability import ChatTimingMiddleware, current_request_id
import secrets  # [추가] 보안 토큰 생성
import re
from typing import List, Dict, Optional, Literal
from fastapi import FastAPI, Query, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
# [수정] run_indexing은 사용하는 곳에서 import (startup crash 방지)
# from index import run_indexing 
import pytz
from datetime import datetime

# utils에서 필요한 것만 딱 가져옵니다.
from utils import (
    redis_client,
    redis_async_client, # [신규]
    MAIN_ANSWER_CACHE_KEY,
    extract_info_from_question_async, # [신규]
    LOCALIZED_UI,
    resolve_language,
    localize_result_pages_async,
    get_supabase_pages_by_ids_async,
    format_search_results,
    FreeTierQuotaExceeded,
    SearchUnavailable,
    build_response_cache_key,
    get_response_cache_async,
    save_response_cache_async,
    notion,   
    supabase, 
    # 임시: 비동기 함수들 import 오류 방지
    # supabase_async, search_supabase_async, check_semantic_cache_async
    # save_semantic_cache_async, get_gemini_embedding_async
    DATABASE_IDS                   
)

# ------------------------------------
# [최적화] 설정 상수 정의
# ------------------------------------
RATE_LIMIT_MAX_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60
LLM_TIMEOUT_SECONDS = 8
INITIAL_RESULT_DISPLAY_COUNT = 2
SUPABASE_KEEPALIVE_INTERVAL_HOURS = 12
CACHE_TTL_SECONDS = 3600
RESULTS_PER_PAGE = 2
MAX_QUESTION_LENGTH = 2000
MAX_CHAT_HISTORY_ITEMS = 4
MAX_RESULT_IDS = 20
FREE_TIER_DAILY_REQUESTS_PER_SESSION = max(
    1, min(int(os.getenv("FREE_TIER_DAILY_REQUESTS_PER_SESSION", "30")), 200)
)
FREE_TIER_ONLY = os.getenv("FREE_TIER_ONLY", "true").strip().lower() in {"1", "true", "yes", "on"}

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY")
DEBUG_ENDPOINT_ENABLED = os.getenv("ENABLE_DEBUG_ENDPOINT", "false").lower() == "true"
if not ADMIN_SECRET_KEY:
    logger.warning("⚠️ [Security] ADMIN_SECRET_KEY가 없어 캐시 삭제 엔드포인트를 비활성화합니다.")

# --- 스케줄러 설정 ---
def scheduled_job():
    """매일 자동 인덱싱 작업"""
    logger.info("⏰ [Scheduler] 자동 인덱싱 작업 시작...")
    try:
        from run_indexer import run_indexing # [이동] Lazy Import
        run_indexing()
        logger.info("⏰ [Scheduler] 자동 인덱싱 작업 완료!")
    except Exception as e:
        logger.error(f"⚠️ [Scheduler] 인덱싱 실패: {e}")

def wake_up_supabase():
    """Supabase Free Tier 대기 상태 방지"""
    try:
        response = supabase.table("site_pages").select("id").limit(1).execute()
        logger.info("⏰ [Keep-Alive] Supabase 핑 성공")
    except Exception as e:
        logger.warning(f"⚠️ [Keep-Alive] 핑 전송 실패: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 수명 주기 관리: 시작/종료 시 스케줄러 제어"""
    # Vercel 환경에서는 스케줄러 비활성화
    if os.getenv("VERCEL_ENV") or os.getenv("FORCE_SYNC_MODE"):
        logger.info("🔄 [Vercel] 스케줄러 비활성화 (서버리스 환경)")
        yield
        return
    
    # 로컬 환경에서만 스케줄러 활성화
    scheduler = BackgroundScheduler()
    korea_tz = pytz.timezone('Asia/Seoul')
    
    scheduler.add_job(scheduled_job, 'cron', hour=0, minute=0, timezone=korea_tz)
    scheduler.add_job(wake_up_supabase, 'interval', hours=SUPABASE_KEEPALIVE_INTERVAL_HOURS)
    
    scheduler.start()
    logger.info("✅ [System] 스케줄러 시작 (매일 00:00 인덱싱, %s시간마다 Keep-Alive)", SUPABASE_KEEPALIVE_INTERVAL_HOURS)
    
    yield
    
    # 서버 종료 시
    scheduler.shutdown()
    logger.info("🛑 [System] 스케줄러 종료")

# app 생성 시 lifespan 적용
app = FastAPI(lifespan=lifespan)
app.add_middleware(ChatTimingMiddleware)

# --- CORS 설정 ---
# [보안 강화] 실제 도메인만 명시적 허용
origins = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "https://bluchany-dobong-welfare-bot.hf.space",
    "https://huggingface.co",
    "https://chatbot-tau-bay.vercel.app"
]
# 환경 변수로 추가 도메인 설정 가능
if additional_origin := os.getenv("ADDITIONAL_CORS_ORIGIN"):
    origins.append(additional_origin)

app.add_middleware(
    CORSMiddleware, 
    allow_origins=origins, 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# [보안 강화] Session Secret Key 환경 변수화
SESSION_SECRET = os.getenv("SESSION_SECRET_KEY", secrets.token_hex(32))
if not os.getenv("SESSION_SECRET_KEY"):
    logger.warning("⚠️ [Security] SESSION_SECRET_KEY가 없어 재시작 시 세션이 초기화됩니다.")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# --- 정적 파일 서빙 ---
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Redis 키 이름 ---
JOB_QUEUE_KEY = "chatbot:job_queue"
JOB_RESULTS_KEY = "chatbot:job_results"
JOB_RESULT_KEY_PREFIX = "chatbot:job_result:"

# 정확한 '더 보기' 문구는 LLM 의도 분석 전에 처리해 불필요한 API 호출을 줄입니다.
SHOW_MORE_EXACT_TERMS = {
    "結果をもっと見る", "もっと見る", "次へ", "続き", "ほかの結果",
    "더보여주세요", "다른결과도보여줘", "다음결과를보여줘",
    "showmemore", "pleaseshowmore", "xemthêmkếtquả", "请显示更多",
    "더", "다음", "계속", "더보여줘", "다른거", "다른것", "또",
    "more", "next", "showmore", "continue",
    "xemthêm", "tiếp", "tiếptheo", "thêm", "nữa", "tiếptục",
    "更多", "继续", "下一个", "还有吗",
}

# --- 요청 모델 ---
class ChatRequest(BaseModel):
    analytics_id: Optional[uuid.UUID] = None
    entry_source: Literal["direct", "website", "qr", "partner", "unknown"] = "unknown"
    input_method: Literal["typed", "suggestion", "clarification", "unknown"] = "unknown"
    action: Literal["ask", "more"] = "ask"
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    language: str = Field(default="ko", pattern="^(ko|en|vi|zh|ja)$")
    last_result_ids: List[str] = Field(default_factory=list, max_length=MAX_RESULT_IDS)
    shown_count: int = Field(default=0, ge=0, le=MAX_RESULT_IDS)
    chat_history: List[dict] = Field(default_factory=list, max_length=MAX_CHAT_HISTORY_ITEMS)


class FreeTierDailyLimitExceeded(RuntimeError):
    """세션별 무료 일일 사용량 상한을 넘었을 때 사용합니다."""


def reserve_free_tier_request(session: dict) -> None:
    """AI 호출 전에 무료 전용 세션의 일일 사용량을 예약합니다."""
    if not FREE_TIER_ONLY:
        return
    today = datetime.now(pytz.timezone("Asia/Seoul")).date().isoformat()
    if session.get("free_tier_usage_date") != today:
        session["free_tier_usage_date"] = today
        session["free_tier_usage_count"] = 0
    used = int(session.get("free_tier_usage_count", 0))
    if used >= FREE_TIER_DAILY_REQUESTS_PER_SESSION:
        raise FreeTierDailyLimitExceeded()
    session["free_tier_usage_count"] = used + 1


def remember_last_question(session: dict, question: str) -> None:
    """Clear conversation state without erasing the reserved daily allowance."""
    usage = {key: session[key] for key in ("free_tier_usage_date", "free_tier_usage_count", "analytics_session", "analytics_seen")
             if key in session}
    session.clear()
    session.update(usage)
    session["last_question"] = question


def is_initial_cacheable_request(chat_request: ChatRequest) -> bool:
    """이전 대화나 '더 보기' 상태에 의존하지 않는 질문만 공유 캐시합니다."""
    return chat_request.action == "ask" and not chat_request.chat_history and not chat_request.last_result_ids and chat_request.shown_count == 0


def is_response_cache_read_eligible(chat_request: ChatRequest, question: str, language: str) -> bool:
    """새 질문 또는 직전 질문을 그대로 반복한 경우에만 공유 캐시를 읽습니다."""
    if chat_request.action == "more":
        return False
    if not chat_request.chat_history:
        return is_initial_cacheable_request(chat_request)

    # 대화 문맥은 보존하되, 바로 직전 사용자 질문을 완전히 반복한 경우는
    # 같은 독립 답변을 재사용해 토큰을 절약합니다.
    history = chat_request.chat_history
    last_user_index = next(
        (index for index in range(len(history) - 1, -1, -1) if history[index].get("role") == "user"),
        None,
    )
    if last_user_index is None or last_user_index != len(history) - 2:
        return False
    if history[-1].get("role") != "assistant":
        return False
    previous_question = history[last_user_index].get("content")
    if not isinstance(previous_question, str) or not previous_question.strip():
        return False
    return build_response_cache_key(previous_question, language) == build_response_cache_key(question, language)


async def cache_response_if_eligible(
    chat_request: ChatRequest, question: str, language: str, response: dict
) -> dict:
    if is_initial_cacheable_request(chat_request):
        await save_response_cache_async(question, language, response)
    return response


async def build_show_more_response(chat_request: ChatRequest, language: str) -> dict:
    """이전 검색 결과의 다음 카드만 조회하는 빠른 경로입니다."""
    ui_text = LOCALIZED_UI[language]
    start = chat_request.shown_count
    end = start + RESULTS_PER_PAGE
    target_ids = chat_request.last_result_ids[start:end]

    if not target_ids:
        return {
            "status": "complete",
            "answer": ui_text["no_more"],
            "last_result_ids": chat_request.last_result_ids,
            "total_found": len(chat_request.last_result_ids),
            "shown_count": start,
        }

    try:
        next_pages = await get_supabase_pages_by_ids_async(target_ids)
        if not next_pages:
            return {"status": "error", "code": "results_changed", "retryable": False,
                    "message": ui_text["results_changed"]}
        next_pages = await localize_result_pages_async(next_pages, language)
        formatted_body = format_search_results(next_pages, language)
        shown_end = start + len(next_pages)
        remaining = len(chat_request.last_result_ids) - end
        header = f"<p>{ui_text['more_header'].format(start=start + 1, end=shown_end)}</p>"
        answer_text = f"{header}<hr>{formatted_body}<p class=\"service-notice\">{ui_text['eligibility_notice']}</p>"
        answer_text += f"<hr>{ui_text['footer_more']}" if remaining > 0 else f"<hr><p>{ui_text['all_results']}</p>"

        return {
            "status": "complete",
            "answer": answer_text,
            "last_result_ids": chat_request.last_result_ids,
            "total_found": len(chat_request.last_result_ids),
            "shown_count": min(end, len(chat_request.last_result_ids)),
        }
    except Exception as e:
        logger.error("더 보기 처리 오류: %s", type(e).__name__)
        return {
            "status": "error",
            "message": ui_text["system_error"], "code": "search_unavailable", "retryable": True,
            "last_result_ids": chat_request.last_result_ids,
            "total_found": len(chat_request.last_result_ids),
        }

# [main.py] 상단 함수 정의 부분에 추가

_memory_rate_limits: Dict[str, List[float]] = {}
_memory_rate_limit_lock = asyncio.Lock()
_memory_rate_limit_expirations: Dict[str, float] = {}
_memory_rate_limit_next_cleanup = 0.0
MEMORY_RATE_LIMIT_CLEANUP_SECONDS = 60
MEMORY_RATE_LIMIT_MAX_KEYS = 10000


async def _check_memory_rate_limit(key: str, limit: int, window: int):
    """Redis가 없는 서버리스 환경에서도 최소한의 요청 제한을 유지합니다."""
    global _memory_rate_limit_next_cleanup
    now = time.monotonic()
    async with _memory_rate_limit_lock:
        at_capacity = key not in _memory_rate_limits and len(_memory_rate_limits) >= MEMORY_RATE_LIMIT_MAX_KEYS
        if now >= _memory_rate_limit_next_cleanup or at_capacity:
            expired = [entry for entry, deadline in _memory_rate_limit_expirations.items() if deadline <= now]
            for entry in expired:
                _memory_rate_limits.pop(entry, None)
                _memory_rate_limit_expirations.pop(entry, None)
            _memory_rate_limit_next_cleanup = now + MEMORY_RATE_LIMIT_CLEANUP_SECONDS
        if key not in _memory_rate_limits and len(_memory_rate_limits) >= MEMORY_RATE_LIMIT_MAX_KEYS:
            # Never evict active counters: that would permit rate-limit bypass.
            raise HTTPException(status_code=429, detail="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                                headers={"Retry-After": str(MEMORY_RATE_LIMIT_CLEANUP_SECONDS)})
        recent = [timestamp for timestamp in _memory_rate_limits.get(key, []) if now - timestamp < window]
        if len(recent) >= limit:
            raise HTTPException(status_code=429, detail="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.")
        recent.append(now)
        _memory_rate_limits[key] = recent
        _memory_rate_limit_expirations[key] = now + window


# Redis executes this read/check/increment/expiry as one atomic operation.
RATE_LIMIT_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current > 0 and redis.call('TTL', KEYS[1]) < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
end
if current >= tonumber(ARGV[1]) then return 0 end
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
return 1
"""


async def check_rate_limit(request: Request, limit: int = RATE_LIMIT_MAX_REQUESTS, window: int = RATE_LIMIT_WINDOW_SECONDS, *, scope: str = "chat"):
    """
    [비동기] 도배 방지 (Rate Limiting) 함수
    """
    key = f"rate_limit:{scope}:unknown"
    try:
        # 1. 사용자 IP 가져오기
        client_ip = request.headers.get("X-Forwarded-For")
        if client_ip:
            client_ip = client_ip.split(",")[0]
        else:
            client_ip = request.client.host
            
        # 2. Redis 키 생성
        key = f"rate_limit:{scope}:{client_ip}"
        
        # [수정] 비동기 Redis 사용
        if redis_async_client:
            allowed = await redis_async_client.eval(RATE_LIMIT_LUA, 1, key, limit, window)
            if int(allowed) != 1:
                raise HTTPException(status_code=429, detail="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                                    headers={"Retry-After": str(window)})
            return
        
    except HTTPException:
        raise 
    except Exception as e:
        logger.warning(f"⚠️ Redis Rate Limit 오류. 메모리 제한으로 전환: {e}")

    await _check_memory_rate_limit(key, limit, window)

# --- API 엔드포인트 ---

@app.get("/", response_class=FileResponse)
async def read_root():
    return FileResponse("static/index.html")

@app.get("/robots.txt", response_class=FileResponse)
async def read_robots():
    return FileResponse("static/robots.txt")

@app.get("/health")
def health_check():
    return {"status": "ok", "env": "vercel"}

@app.get("/debug")
def debug_check():
    """진단용 엔드포인트: 각 연결 상태를 개별적으로 테스트"""
    if not DEBUG_ENDPOINT_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")
    results = {}
    
    # 1. Supabase 연결 테스트
    try:
        if supabase:
            resp = supabase.table("site_pages").select("id").limit(1).execute()
            results["supabase"] = f"✅ OK (rows: {len(resp.data) if resp.data else 0})"
        else:
            results["supabase"] = "❌ Client not initialized"
    except Exception as e:
        results["supabase"] = f"❌ Error: {type(e).__name__}: {str(e)[:100]}"
    
    # 2. Gemini 임베딩 테스트
    try:
        from utils import get_gemini_embedding, KEY_POOL
        if KEY_POOL:
            embedding = get_gemini_embedding("테스트")
            if embedding:
                results["gemini_embed"] = f"✅ OK (dim: {len(embedding)})"
            else:
                results["gemini_embed"] = "❌ Returned None"
        else:
            results["gemini_embed"] = "❌ No API keys"
    except Exception as e:
        results["gemini_embed"] = f"❌ Error: {type(e).__name__}: {str(e)[:100]}"
    
    # 3. Redis 연결 테스트
    try:
        if redis_client:
            redis_client.ping()
            results["redis"] = "✅ OK"
        else:
            results["redis"] = "⚠️ Not configured (fallback mode active)"
    except Exception as e:
        results["redis"] = f"⚠️ Error: {type(e).__name__}: {str(e)[:50]}"
    
    return results

@app.post("/admin/clear_cache")
def clear_all_caches(request: Request, secret: Optional[str] = Query(None)):
    if not ADMIN_SECRET_KEY:
        raise HTTPException(status_code=404, detail="Not Found")
    secret = request.headers.get("X-Admin-Secret") or secret
    if not secret or not secrets.compare_digest(secret, ADMIN_SECRET_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis cache is not enabled")
    try:
        logger.warning("--- 🔒 관리자 요청: Redis 캐시 초기화 ---")
        keys_to_delete = []
        for key_pattern in ["extract:*", "rank:*", "summary:*", f"{JOB_RESULT_KEY_PREFIX}*"]:
            keys_to_delete.extend(redis_client.scan_iter(match=key_pattern, count=100))
        if keys_to_delete:
            redis_client.delete(*keys_to_delete)
        redis_client.delete(MAIN_ANSWER_CACHE_KEY) 
        redis_client.delete(JOB_RESULTS_KEY)
        return {"status": "Redis 캐시 삭제 완료"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"오류: {e}")



# [main.py] chat_with_bot 함수 전체 교체

analytics.install(app, check_rate_limit)

@app.post("/chat")
async def chat_with_bot(chat_request: ChatRequest, request: Request):
    # Invalid schemas and rate-limited HTTP requests are excluded from usage statistics.
    await check_rate_limit(request, limit=10, window=60, scope="chat")
    if not chat_request.question.strip():
        raise HTTPException(422, detail="질문을 입력해 주세요.")
    state = await analytics.begin(chat_request, request)
    try:
        response = await _chat_with_bot(chat_request, request)
    except Exception:
        await analytics.finish(state, {"status": "error"})
        raise
    if state:
        # Old cached responses may not have category metadata; classify displayed badges only.
        if state["category"] == "미분류":
            import html as html_module
            labels = re.findall(r'class="card-header-badge"[^>]*>([^<]*)<', response.get("answer", ""))
            mapping = {label: name for ui in LOCALIZED_UI.values() for name, label in ui.get("cats", {}).items()}
            categories = {analytics.category(mapping.get(html_module.unescape(x), html_module.unescape(x))) for x in labels}
            categories.discard("미분류")
            state["category"] = next(iter(categories)) if len(categories)==1 else "복합" if categories else "미분류"
        click = await analytics.finish(state, response)
        if click:
            response = dict(response, analytics_token=click)
    return response

async def _chat_with_bot(chat_request: ChatRequest, request: Request):

    session = request.session
    question = chat_request.question.strip()
    chat_history = chat_request.chat_history
    language = resolve_language(chat_request.language, question)
    ui_text = LOCALIZED_UI[language]
    logger.info("질문 수신 (글자 수=%s, 언어=%s)", len(question), language)

    if not question:
        raise HTTPException(status_code=422, detail="질문을 입력해 주세요.")

    visible_question = re.sub(r'\s*\(System[\s\S]*?\)', '', question, flags=re.IGNORECASE).strip()
    normalized_input = visible_question.lower()
    input_no_spaces = normalized_input.replace(" ", "")

    # [수정] Redis 상태 확인 (Vercel 환경에서는 강제로 동기 모드)
    # Vercel 환경 변수가 있거나 Redis 클라이언트가 없으면 동기 모드로 강제 전환
    force_sync_mode = os.getenv("VERCEL_ENV") == "production" or os.getenv("FORCE_SYNC_MODE") == "true"
    is_redis_down = force_sync_mode or (redis_async_client is None)
    
    if force_sync_mode:
        logger.info("🔄 Vercel 환경 감지: 동기 모드로 강제 전환")

    # 2. 정확한 '더 보기'는 즉시 처리합니다. (LLM 호출·대기 불필요)
    if chat_request.action == "more" or input_no_spaces in SHOW_MORE_EXACT_TERMS:
        logger.info("더 보기 빠른 경로 처리")
        analytics.note(request, kind="more")
        return await build_show_more_response(chat_request, language)

    # 정확 일치 캐시는 의도 분석·임베딩·LLM 호출보다 먼저 확인합니다.
    if is_response_cache_read_eligible(chat_request, question, language):
        analytics.note(request, cache_eligible=True)
        cached_response = await get_response_cache_async(question, language)
        if cached_response:
            logger.info("♻️ [Response Cache] Hit")
            analytics.note(request, cache_hit=True)
            cached_response = dict(cached_response)
            if any(cached_response.get("answer") == ui_text.get(key) for key in
                   ("reset","exit","out_of_scope","small_talk","thanks","safety_block")):
                analytics.note(request, kind="other")
            if cached_response.get("answer") == ui_text["reset"]:
                cached_response["action"] = "reset"
            cached_response["job_id"] = str(uuid.uuid4())
            return cached_response

    try:
        reserve_free_tier_request(session)
    except FreeTierDailyLimitExceeded:
        return {"status": "error", "message": ui_text["free_tier_daily_limit"], "code": "daily_limit", "retryable": False}

    # 3. AI 의도 분석 (비동기 호출)
    try:
        extracted_info = await extract_info_from_question_async(question, chat_history)
        if isinstance(extracted_info, dict) and "error" in extracted_info:
            if "free_tier_quota_exceeded" in extracted_info["error"]:
                return {"status": "error", "message": ui_text["free_tier_quota"], "code": "provider_limit", "retryable": False}
            raise RuntimeError(extracted_info["error"])
    except FreeTierQuotaExceeded:
        return {"status": "error", "message": ui_text["free_tier_quota"], "code": "provider_limit", "retryable": False}
    except Exception as e:
        logger.error("질문 분석 오류: %s", type(e).__name__)
        return {"status": "error", "message": ui_text["system_error"]}


    # Only an explicit action or an exact continuation phrase may page results.
    # An LLM guess must never turn a new service question into pagination.
    if extracted_info.get("intent") == "show_more":
        logger.warning("[Intent Guard] ignored AI show_more for new question (request_id=%s)",
                       current_request_id())
        extracted_info = dict(extracted_info, intent=None)

    if extracted_info.get("intent") in {"reset","exit","out_of_scope","small_talk","safety_block"}:
        analytics.note(request, kind="other")
    analytics.note(request, category=analytics.category(extracted_info.get("category")))

    # 4. 의도별 분기 (Small talk 등)
    if extracted_info.get("intent") == "safety_block":
        return await cache_response_if_eligible(chat_request, question, language, {
            "status": "complete", "answer": ui_text["safety_block"], "last_result_ids": [], "total_found": 0
        })
    
    if extracted_info.get("intent") == "exit":
        return await cache_response_if_eligible(chat_request, question, language, {
            "status": "complete", "answer": ui_text["exit"], "last_result_ids": [], "total_found": 0
        })
    
    if extracted_info.get("intent") == "reset":
        return {
            "status": "complete", "action": "reset", "answer": ui_text["reset"],
            "last_result_ids": [], "total_found": 0, "shown_count": 0,
        }

    if extracted_info.get("intent") == "out_of_scope":
        return await cache_response_if_eligible(chat_request, question, language, {
            "status": "complete", "answer": ui_text["out_of_scope"], "last_result_ids": [], "total_found": 0
        })

    if extracted_info.get("intent") == "small_talk":
        answer = ui_text["small_talk"]
        thanks_keywords = {
            "ko": ("고마", "감사"),
            "en": ("thank",),
            "vi": ("cảm ơn", "cam on"),
            "zh": ("谢谢", "感謝", "感谢"),
            "ja": ("ありがとう", "感謝"),
        }
        if any(keyword in normalized_input for keyword in thanks_keywords[language]):
            answer = ui_text["thanks"]
        return await cache_response_if_eligible(chat_request, question, language, {
            "status": "complete", "answer": answer, "last_result_ids": [], "total_found": 0
        })

    if extracted_info.get("intent") == "clarify_category":
        category_options = [ui_text["cats"].get(category, category) for category in DATABASE_IDS]
        return await cache_response_if_eligible(chat_request, question, language, {
            "status": "clarify", "answer": ui_text["clarify"], "options": category_options,
            "last_result_ids": [], "total_found": 0
        })

    # Only the language/version-aware Supabase answer cache is used.
    # The legacy Redis hash does not validate language or document versions.

    # 6. 작업 처리 (비상 모드 포함)
    logger.info("[API] Job 생성 및 처리 시작.")
    
    job_id = str(uuid.uuid4())
    ai_category = extracted_info.get("category") if isinstance(extracted_info, dict) else None
    
    job_data = {
        "job_id": job_id,
        "trace_id": current_request_id(),
        "_analytics": getattr(request.state, "analytics", None),
        "question": question, 
        "language": language,
        "chat_history": chat_history,
        "ai_category": ai_category,
        # 직접 실행과 Redis 작업 경로 모두 worker가 결과의 카테고리 범위까지 저장합니다.
        "cacheable": is_initial_cacheable_request(chat_request),
    }

    # [핵심 수정] Redis가 죽었으면 -> Async 직접 실행 (Vercel 최적화)
    if is_redis_down:
        logger.info(f"⚡️ [Direct Async] Worker 직접 실행 (Redis Bypass)")
        try:
            from worker import process_job_async
            
            # Async 함수 직접 호출 (이제 process_job_async는 진짜 async임)
            # result는 (final_answer, all_page_ids, total_found) 튜플
            result = await process_job_async(job_data)
            
            if isinstance(result, tuple) and len(result) == 3:
                final_answer, page_ids, total_found = result
                response = {
                    "status": "complete", 
                    "job_id": job_id,
                    "answer": final_answer,
                    "last_result_ids": page_ids,
                    "total_found": total_found
                }
                return response
            else:
                # 예기치 않은 결과 형식
                logger.error("Async Worker 결과 형식 오류: %s", type(result).__name__)
                return {"status": "error", "message": ui_text["system_error"]}
            
        except FreeTierQuotaExceeded:
            return {"status": "error", "message": ui_text["free_tier_quota"],
                    "code": "provider_limit", "retryable": False}
        except Exception as e:
            logger.error("Async Worker 처리 실패: %s", type(e).__name__)
            return {"status": "error", "message": ui_text["system_error"],
                    "code": "search_unavailable" if isinstance(e, SearchUnavailable) else "answer_unavailable",
                    "retryable": True}

    # Redis가 살아있으면 -> 큐에 넣기 (Async)
    try: 
        await redis_async_client.rpush(JOB_QUEUE_KEY, json.dumps(job_data, ensure_ascii=False).encode('utf-8'))
        remember_last_question(session, question)
        return {"message": "요청 접수 완료.", "job_id": job_id}
    except Exception as e: 
        logger.error("Redis Push 실패: %s", type(e).__name__)
        return {"status": "error", "message": ui_text["system_error"]}

@app.get("/get_result/{job_id}")
def get_job_result(job_id: str):
    try:
        if not redis_client:
            raise HTTPException(status_code=503, detail="결과 저장소를 사용할 수 없습니다.")
        result_bytes = redis_client.get(f"{JOB_RESULT_KEY_PREFIX}{job_id}")
        # 이전 배포에서 생성된 작업 결과도 만료 전까지는 읽을 수 있게 유지합니다.
        if not result_bytes:
            result_bytes = redis_client.hget(JOB_RESULTS_KEY, job_id)
        if result_bytes:
            return json.loads(result_bytes.decode('utf-8'))
        else:
            return {"status": "pending"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("작업 결과 조회 오류: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="작업 결과를 조회할 수 없습니다.")

# --- Retired feedback endpoint: old browser tabs must not write to Notion. ---

# Keep validation and rate limiting for stale browser clients.
class FeedbackRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=12000)
    feedback: Literal["👍", "👎"]
    reason: Optional[str] = Field(default="", max_length=200)
    comment: Optional[str] = Field(default="", max_length=2000)
    chat_history: Optional[str] = Field(default="", max_length=20000)

@app.post("/feedback")
async def handle_feedback(feedback_data: FeedbackRequest, request: Request):
    await check_rate_limit(request, limit=5, window=300, scope="feedback")
    raise HTTPException(status_code=410, detail="Feedback moved to email. Refresh the page and use Contact.")
