# main.py - Optimized Version
import os
import json
import uuid
import logging
import asyncio
import time
import hashlib
import hmac
from runtime_policy import fallback_intent, normalize_intent, visible_question
import secrets  # [추가] 보안 토큰 생성
import re
from typing import List, Dict, Optional, Literal
from fastapi import FastAPI, Query, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field, field_validator
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
    build_response_cache_key,
    get_response_cache_async,
    save_response_cache_async,
    reserve_ai_budget_async,
    invalidate_response_cache,
    RESPONSE_CACHE_USE_DIRECT_REST,
    RESPONSE_CACHE_TABLE,
    _secret_cache_rest_request_async,
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
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, https_only=bool(os.getenv("VERCEL_ENV")))

# --- 정적 파일 서빙 ---
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Redis 키 이름 ---
JOB_QUEUE_KEY = "chatbot:job_queue"
JOB_RESULTS_KEY = "chatbot:job_results"
JOB_RESULT_KEY_PREFIX = "chatbot:job_result:"

# 정확한 '더 보기' 문구는 LLM 의도 분석 전에 처리해 불필요한 API 호출을 줄입니다.
SHOW_MORE_EXACT_TERMS = {
    "더", "다음", "계속", "더보여줘", "다른거", "다른것", "또",
    "more", "next", "showmore", "continue",
    "xemthêm", "tiếp", "tiếptheo", "nữa", "tiếptục",
    "更多", "继续", "下一个", "还有吗",
}

# --- 요청 모델 ---
class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)

class ChatRequest(BaseModel):
    action: Literal["ask", "more"] = "ask"
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    language: str = Field(default="ko", pattern="^(ko|en|vi|zh)$")
    last_result_ids: List[str] = Field(default_factory=list, max_length=MAX_RESULT_IDS)
    shown_count: int = Field(default=0, ge=0, le=MAX_RESULT_IDS)
    chat_history: List[dict] = Field(default_factory=list, max_length=MAX_CHAT_HISTORY_ITEMS)

    @field_validator("chat_history")
    @classmethod
    def validate_history(cls, value):
        return [ChatTurn.model_validate(turn).model_dump() for turn in value]

    @field_validator("last_result_ids")
    @classmethod
    def validate_ids(cls, value):
        for item in value:
            uuid.UUID(item)
        return list(dict.fromkeys(value))


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


def is_initial_cacheable_request(chat_request: ChatRequest) -> bool:
    """이전 대화나 '더 보기' 상태에 의존하지 않는 질문만 공유 캐시합니다."""
    return chat_request.action == "ask" and not chat_request.chat_history


def is_response_cache_read_eligible(chat_request: ChatRequest, question: str, language: str) -> bool:
    """새 질문 또는 직전 질문을 그대로 반복한 경우에만 공유 캐시를 읽습니다."""
    if chat_request.action == "more":
        return False
    if not chat_request.chat_history:
        return True

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


async def build_show_more_response(chat_request, language):
    ui = LOCALIZED_UI[language]
    ids = chat_request.last_result_ids
    cursor = min(chat_request.shown_count, len(ids))
    selected = []
    try:
        # 삭제된 문서를 건너뛰며 최대 2개의 실제 문서를 찾습니다.
        while cursor < len(ids) and len(selected)<RESULTS_PER_PAGE:
            batch = ids[cursor:cursor+RESULTS_PER_PAGE-len(selected)]
            selected.extend(await get_supabase_pages_by_ids_async(batch))
            cursor += len(batch)
        if not selected:
            answer = ui["no_more"]
        else:
            selected = await localize_result_pages_async(selected, language, allow_live=False)
            answer = f"<p>{ui['more_header'].format(start=chat_request.shown_count+1,end=cursor)}</p><hr>"
            answer += format_search_results(selected,language)
            answer += "<hr>"+(ui["footer_more"] if cursor<len(ids) else ui["all_results"])
        return {"status":"complete","answer":answer,"last_result_ids":ids,
                "total_found":len(ids),"shown_count":cursor}
    except Exception as error:
        logger.error("더 보기 조회 실패: %s",type(error).__name__)
        return {"status":"error","message":ui["system_error"]}

# [main.py] 상단 함수 정의 부분에 추가

_memory_rate_limits: Dict[str, List[float]] = {}
_memory_rate_limit_lock = asyncio.Lock()


async def _check_memory_rate_limit(key, limit, window):
    now = time.monotonic()
    async with _memory_rate_limit_lock:
        for expired in [k for k,v in _memory_rate_limits.items() if not v or now-v[-1]>300]:
            del _memory_rate_limits[expired]
        if key not in _memory_rate_limits and len(_memory_rate_limits)>=10000:
            raise HTTPException(status_code=429,detail="Rate limit capacity reached")
        recent = [t for t in _memory_rate_limits.get(key,[]) if now-t<window]
        if len(recent)>=limit:
            raise HTTPException(status_code=429, detail="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.")
        _memory_rate_limits[key] = recent+[now]


async def check_rate_limit(request: Request, limit: int = RATE_LIMIT_MAX_REQUESTS, window: int = RATE_LIMIT_WINDOW_SECONDS):
    """
    [비동기] 도배 방지 (Rate Limiting) 함수
    """
    key = "rate_limit:unknown"
    try:
        # 1. 사용자 IP 가져오기
        client_ip = request.headers.get("X-Forwarded-For")
        if client_ip:
            client_ip = client_ip.split(",")[0]
        else:
            client_ip = request.client.host
            
        # 2. Redis 키 생성
        key = f"rate_limit:{request.url.path}:{client_ip}"
        
        # [수정] 비동기 Redis 사용
        if redis_async_client:
            current_count = await redis_async_client.get(key)
            
            if current_count and int(current_count) >= limit:
                logger.warning(f"🚫 [Rate Limit] 도배 감지! IP: {client_ip}")
                raise HTTPException(status_code=429, detail="요청이 너무 많습니다. 1분 뒤에 다시 시도해주세요. 😥")
                
            # 파이프라인도 비동기로
            pipe = redis_async_client.pipeline()
            await pipe.incr(key)
            if not current_count:
                await pipe.expire(key, window)
            await pipe.execute()
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
    # 프로세스 생존 확인용. DB/AI 준비 상태를 보장하지 않습니다.
    return {"status":"ok", "env":"vercel" if os.getenv("VERCEL_ENV") else "local",
            "revision":os.getenv("VERCEL_GIT_COMMIT_SHA", "local"), "check":"liveness"}

@app.get("/debug")
def debug_check(request: Request):
    """진단용 엔드포인트: 각 연결 상태를 개별적으로 테스트"""
    if not DEBUG_ENDPOINT_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")
    provided = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET_KEY or not secrets.compare_digest(provided, ADMIN_SECRET_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")
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
        from utils import KEY_POOL
        # 진단 조회가 공용 AI 예산을 우회하여 토큰을 쓰지 않도록 실제 호출하지 않습니다.
        results["gemini_embed"] = "Configured (not probed)" if KEY_POOL else "No API keys"
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
async def clear_all_caches(request: Request):
    if not ADMIN_SECRET_KEY:
        raise HTTPException(status_code=404, detail="Not Found")
    provided = request.headers.get("X-Admin-Secret", "")
    if not secrets.compare_digest(provided,ADMIN_SECRET_KEY):
        raise HTTPException(status_code=401,detail="Unauthorized")
    if RESPONSE_CACHE_USE_DIRECT_REST:
        await _secret_cache_rest_request_async("DELETE",RESPONSE_CACHE_TABLE,params={"cache_key":"neq."})
    elif not await asyncio.to_thread(invalidate_response_cache):
        raise HTTPException(status_code=503,detail="Response cache unavailable")
    if redis_async_client:
        for pattern in ("extract:*","extract_v2:*","rank:*","summary:*","summary_v*:*"):
            async for key in redis_async_client.scan_iter(match=pattern,count=100):
                await redis_async_client.delete(key)
        await redis_async_client.delete(MAIN_ANSWER_CACHE_KEY)
    return {"status":"응답 캐시 삭제 완료"}



# [main.py] chat_with_bot 함수 전체 교체

@app.post("/chat")
async def chat_with_bot(chat_request: ChatRequest, request: Request):
    try:
        return await asyncio.wait_for(_chat_with_bot(chat_request,request),40)
    except asyncio.TimeoutError:
        return {"status":"error","message":LOCALIZED_UI[chat_request.language]["system_error"]}

async def _chat_with_bot(chat_request: ChatRequest, request: Request):
    await check_rate_limit(request, limit=10, window=60)
    question = visible_question(chat_request.question)
    if not question:
        raise HTTPException(status_code=422, detail="질문을 입력해 주세요.")
    language = resolve_language(chat_request.language,question)
    ui = LOCALIZED_UI[language]
    history = chat_request.chat_history
    job_id = str(uuid.uuid4())
    def with_id(response):
        return {**response, "job_id":job_id}
    if fallback_intent(question)["intent"] == "reset":
        return with_id({"status":"complete","action":"reset","answer":ui["reset"],
                        "last_result_ids":[],"total_found":0,"shown_count":0})
    exact_more = re.sub(r"\s+","",question).lower() in SHOW_MORE_EXACT_TERMS
    if chat_request.action == "more" or exact_more:
        return with_id(await build_show_more_response(chat_request,language))
    if is_response_cache_read_eligible(chat_request,question,language):
        cached = await get_response_cache_async(question,language)
        if cached:
            logger.info("[Response Cache] Hit")
            return with_id(cached)
    allow_ai = True
    try:
        reserve_free_tier_request(request.session)
    except FreeTierDailyLimitExceeded:
        allow_ai = False
    if allow_ai:
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
        actor = hmac.new(SESSION_SECRET.encode(), ip.encode(), hashlib.sha256).hexdigest()
        allow_ai = await reserve_ai_budget_async(actor)
    # 사용량 확인 실패/한도 도달은 AI 없는 검색으로 전환합니다.
    info = await extract_info_from_question_async(question,history) if allow_ai else fallback_intent(question)
    info = normalize_intent(info,question)
    if not history:
        info["search_query"] = question
    if info["intent"] == "show_more":
        return with_id(await build_show_more_response(chat_request,language))
    if info["intent"] == "reset":
        return with_id({"status":"complete","action":"reset","answer":ui["reset"],
                        "last_result_ids":[],"total_found":0,"shown_count":0})
    if info["intent"] == "clarify_category":
        return with_id({"status":"clarify","answer":ui["clarify"],
            "options":[ui["cats"].get(c,c) for c in DATABASE_IDS],"last_result_ids":[],"total_found":0})
    if info["intent"] in ("safety_block","exit","out_of_scope","small_talk"):
        response={"status":"complete","answer":ui[info["intent"]],"last_result_ids":[],"total_found":0,"shown_count":0}
        return with_id(await cache_response_if_eligible(chat_request,question,language,response))
    job_data={"job_id":job_id,"question":question,"language":language,"chat_history":history,
              "extracted_info":info,"allow_ai":allow_ai,"cacheable":is_initial_cacheable_request(chat_request)}
    # Redis 선택 시 ping 성공한 경우에만 큐를 사용합니다.
    force_direct = bool(os.getenv("VERCEL_ENV")) or os.getenv("FORCE_SYNC_MODE","").lower()=="true"
    if redis_async_client and not force_direct:
        try:
            await asyncio.wait_for(redis_async_client.ping(),1)
        except Exception:
            logger.warning("Redis 연결 불가: 직접 실행")
        else:
            try:
                await redis_async_client.rpush(JOB_QUEUE_KEY,json.dumps(job_data,ensure_ascii=False).encode("utf-8"))
                request.session["job_ids"] = (request.session.get("job_ids", []) + [job_id])[-20:]
                return {"message":"요청 접수 완료.","job_id":job_id}
            except Exception:
                # 전송 성공 여부가 불명확할 수 있어 중복 AI 실행을 피합니다.
                return {"status":"error","message":ui["system_error"]}
    from worker import process_job_async
    try:
        response = await asyncio.wait_for(process_job_async(job_data), 30)
        return with_id(response)
    except asyncio.TimeoutError:
        logger.warning("작업 전체 제한 시간 초과")
        return {"status":"error","message":ui["system_error"]}

@app.get("/get_result/{job_id}")
def get_job_result(job_id: str, request: Request):
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not Found")
    if job_id not in request.session.get("job_ids", []):
        raise HTTPException(status_code=404, detail="Not Found")
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

# --- 피드백 DB ---
FEEDBACK_DB_ID = os.getenv("NOTION_FEEDBACK_DB_ID", "2c18ade5021080448ab8d304b4777fe5")

# [수정] FeedbackRequest 모델 확장
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
    await check_rate_limit(request,limit=5,window=300)
    if not notion:
        raise HTTPException(status_code=503,detail="Notion unavailable")
    props = {
        "질문":{"title":[{"text":{"content":feedback_data.question[:2000]}}]},
        "답변":{"rich_text":[{"text":{"content":feedback_data.answer[:2000]}}]},
        "평가":{"select":{"name":feedback_data.feedback}},
        "대화내역":{"rich_text":[{"text":{"content":(feedback_data.chat_history or "")[:2000]}}]},
        "상세의견":{"rich_text":[{"text":{"content":(feedback_data.comment or "")[:2000]}}]},
        "작업ID":{"rich_text":[{"text":{"content":feedback_data.job_id}}]},
    }
    if feedback_data.reason:
        props["사유"]={"select":{"name":feedback_data.reason}}
    try:
        await asyncio.wait_for(asyncio.to_thread(notion.pages.create,
            parent={"database_id":FEEDBACK_DB_ID}, properties=props),10)
        return {"status":"success"}
    except Exception as error:
        logger.error("피드백 저장 실패: %s",type(error).__name__)
        raise HTTPException(status_code=503,detail="저장 실패") from error
