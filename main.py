# main.py - Optimized Version
import os
import json
import uuid
import logging
import asyncio
import secrets  # [추가] 보안 토큰 생성
from typing import List, Dict, Optional, Literal
from fastapi import FastAPI, Query, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
# [수정] run_indexing은 사용하는 곳에서 import (startup crash 방지)
# from index import run_indexing 
import pytz

# utils에서 필요한 것만 딱 가져옵니다.
from utils import (
    redis_client,
    redis_async_client, # [신규]
    MAIN_ANSWER_CACHE_KEY,
    extract_info_from_question,
    extract_info_from_question_async, # [신규]
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

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "your_strong_admin_password_here")

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
    "https://huggingface.co"
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
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# --- 정적 파일 서빙 ---
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Redis 키 이름 ---
JOB_QUEUE_KEY = "chatbot:job_queue"
JOB_RESULTS_KEY = "chatbot:job_results"

# --- 요청 모델 ---
class ChatRequest(BaseModel):
    question: str
    last_result_ids: List[str] = [] # [수정] List 사용 (상단 import 덕분에 에러 없음)
    shown_count: int = 0
    chat_history: List[dict] = []   # [수정] List 사용

# [main.py] 상단 함수 정의 부분에 추가

async def check_rate_limit(request: Request, limit: int = RATE_LIMIT_MAX_REQUESTS, window: int = RATE_LIMIT_WINDOW_SECONDS):
    """
    [비동기] 도배 방지 (Rate Limiting) 함수
    """
    try:
        # 1. 사용자 IP 가져오기
        client_ip = request.headers.get("X-Forwarded-For")
        if client_ip:
            client_ip = client_ip.split(",")[0]
        else:
            client_ip = request.client.host
            
        # 2. Redis 키 생성
        key = f"rate_limit:{client_ip}"
        
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
        
    except HTTPException:
        raise 
    except Exception as e:
        logger.error(f"⚠️ Rate Limit 오류 (서버는 계속 작동): {e}")

# --- API 엔드포인트 ---

@app.get("/", response_class=HTMLResponse)
async def read_root():
    # [수정] 파일 읽기 문제를 배제하기 위해 하드코딩된 HTML 반환
    return """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <title>도봉구 영유아 복지톡</title>
        <style>
            body { font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #f0f2f5; }
            .loader { border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; }
            @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        </style>
        <script>
            // 1초 뒤 실제 메인 페이지 리소스 로드 시도
            setTimeout(() => {
                // static 파일이 잘 서빙되는지 확인하기 위해 redirection
                window.location.href = '/static/index.html'; 
            }, 1000);
        </script>
    </head>
    <body>
        <div style="text-align:center">
            <h1>챗봇 로딩 중...</h1>
            <div class="loader" style="margin: 20px auto;"></div>
            <p>잠시만 기다려주세요.</p>
        </div>
    </body>
    </html>
    """

@app.get("/health")
def health_check():
    return {"status": "ok", "env": "vercel"}

@app.get("/debug")
def debug_check():
    """진단용 엔드포인트: 각 연결 상태를 개별적으로 테스트"""
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
def clear_all_caches(secret: str = Query(None)):
    if secret != ADMIN_SECRET_KEY: raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        logger.warning("--- 🔒 관리자 요청: Redis 캐시 초기화 ---")
        keys_to_delete = []
        for key_pattern in ["extract:*", "rank:*", "summary:*"]:
            keys_to_delete.extend(redis_client.keys(key_pattern))
        if keys_to_delete:
            redis_client.delete(*keys_to_delete)
        redis_client.delete(MAIN_ANSWER_CACHE_KEY) 
        redis_client.delete(JOB_RESULTS_KEY)
        return {"status": "Redis 캐시 삭제 완료"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"오류: {e}")



# [main.py] chat_with_bot 함수 전체 교체

@app.post("/chat")
async def chat_with_bot(chat_request: ChatRequest, request: Request):
    # 1. 도배 방지 (비동기 호출)
    await check_rate_limit(request, limit=10, window=60) 

    session = request.session
    question = chat_request.question.strip()
    chat_history = chat_request.chat_history
    logger.info(f"받은 질문: {question}")

    if not notion: raise HTTPException(status_code=503, detail="Notion API Key 설정 오류")

    normalized_input = question.strip().lower()
    input_no_spaces = normalized_input.replace(" ", "")

    # [수정] Redis 상태 확인 (Vercel 환경에서는 강제로 동기 모드)
    # Vercel 환경 변수가 있거나 Redis 클라이언트가 없으면 동기 모드로 강제 전환
    force_sync_mode = os.getenv("VERCEL_ENV") == "production" or os.getenv("FORCE_SYNC_MODE") == "true"
    is_redis_down = force_sync_mode or (redis_async_client is None)
    
    if force_sync_mode:
        logger.info("🔄 Vercel 환경 감지: 동기 모드로 강제 전환")

    # 2. AI 의도 분석 (비동기 호출)
    try:
        extracted_info = await extract_info_from_question_async(question, chat_history)
        if isinstance(extracted_info, dict) and "error" in extracted_info:
             raise HTTPException(status_code=500, detail=extracted_info["error"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"질문 분석 중 오류: {e}")


    # 3. '더 보기' 감지
    show_more_keywords = ["더", "다음", "계속", "more", "next", "다른", "또"]
    is_keyword_match = any(k in input_no_spaces for k in show_more_keywords)
    is_ai_match = extracted_info.get("intent") == "show_more"
    is_show_more = (is_keyword_match or is_ai_match)
    
    # '더 보기' 실행 (Redis가 죽어도 Supabase는 살아있으므로 작동 가능)
    if is_show_more and chat_request.last_result_ids:
        logger.info("[API] '더 보기' 요청 처리")
        try:
            start = chat_request.shown_count
            end = start + 2
            target_ids = chat_request.last_result_ids[start:end]
            
            if not target_ids:
                return {"status": "complete", "answer": "더 이상 표시할 결과가 없습니다.", "last_result_ids": chat_request.last_result_ids, "total_found": len(chat_request.last_result_ids)}

            from utils import get_supabase_pages_by_ids_async, format_search_results
            
            # 비동기 버전으로 Supabase 조회
            next_pages = await get_supabase_pages_by_ids_async(target_ids)
            formatted_body = format_search_results(next_pages)
            
            remaining = len(chat_request.last_result_ids) - end

            header = f"<p>🔎 <b>추가 정보 ({start+1}~{start+len(next_pages)}번째)</b></p>"
            answer_text = f"{header}<hr>{formatted_body}"
            
            if remaining > 0:
                answer_text += f"<hr><p>🔍 <b>아직 결과가 더 남아있습니다.</b> '더 보여줘' 또는 '다음'을 입력해 보세요.</p>"
            else:
                answer_text += "<hr><p>✅ <b>모든 결과를 확인했습니다.</b></p>"

            return {
                "status": "complete", 
                "answer": answer_text, 
                "last_result_ids": chat_request.last_result_ids, 
                "total_found": len(chat_request.last_result_ids),
                "shown_count": end 
            }
        except Exception as e:
            logger.error(f"❌ 더 보기 처리 오류: {e}")

    # 4. 의도별 분기 (Small talk 등)
    if extracted_info.get("intent") == "safety_block":
        return {"status": "complete", "answer": "비속어는 삼가주세요. 😥 복지 정보에 대해 질문해 주세요.", "last_result_ids": [], "total_found": 0}
    
    if extracted_info.get("intent") == "exit":
        return {"status": "complete", "answer": "네, 알겠습니다. 언제든 다시 찾아주세요! 😊", "last_result_ids": [], "total_found": 0}
    
    if extracted_info.get("intent") == "reset":
        return {"status": "complete", "answer": "대화를 초기화했습니다. 무엇이 궁금하신가요? 🤖", "last_result_ids": [], "total_found": 0}

    if extracted_info.get("intent") == "out_of_scope":
        return {"status": "complete", "answer": "저는 영유아 복지 정보만 알려드릴 수 있어요. 😅", "last_result_ids": [], "total_found": 0}

    if extracted_info.get("intent") == "small_talk":
        answer = "안녕하세요! 도봉구 영유아 복지 챗봇입니다. 무엇을 도와드릴까요?"
        if "고마" in normalized_input: answer = "도움이 되어 기쁩니다! 😊"
        return {"status": "complete", "answer": answer, "last_result_ids": [], "total_found": 0}

    if extracted_info.get("intent") == "clarify_category":
        age_info = extracted_info.get("age")
        age_text = f"{age_info}개월 아기" if age_info else "자녀"
        return {"status": "clarify", "answer": f"{age_text}를 위한 어떤 정보가 궁금하신가요?", "options": list(DATABASE_IDS.keys()), "last_result_ids": [], "total_found": 0}

    # 5. 캐시 확인 (Redis Async)
    if not is_redis_down:
        try:
            cached_data = await redis_async_client.hget(MAIN_ANSWER_CACHE_KEY, question)
            if cached_data:
                logger.info(f"✅ [API] Cache Hit!")
                session.clear(); session["last_question"] = question
                return json.loads(cached_data.decode('utf-8'))
        except Exception: pass

    # 6. 작업 처리 (비상 모드 포함)
    logger.info("[API] Job 생성 및 처리 시작.")
    
    job_id = str(uuid.uuid4())
    ai_category = extracted_info.get("category") if isinstance(extracted_info, dict) else None
    
    job_data = {
        "job_id": job_id, 
        "question": question, 
        "chat_history": chat_history,
        "ai_category": ai_category
    }

    # [핵심 수정] Redis가 죽었으면 -> 동기 모드(직접 실행)
    if is_redis_down:
        logger.warning(f"⚠️ [Fallback] Redis 연결 불가. Worker를 우회하여 직접 처리합니다.")
        try:
            from worker import process_job 
            
            # 비동기 실행 (ThreadPoolExecutor에 위임하여 블로킹 방지)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, process_job, job_data)
            
            # result는 (final_answer, all_page_ids, total_found) 튜플
            if isinstance(result, tuple) and len(result) == 3:
                final_answer, page_ids, total_found = result
                return {
                    "status": "complete", 
                    "answer": final_answer,
                    "last_result_ids": page_ids,
                    "total_found": total_found
                }
            else:
                # 예기치 않은 결과 형식
                logger.error(f"❌ Fallback 결과 형식 오류: {type(result)} - {result}")
                return {"error": "처리 결과 형식 오류가 발생했습니다."}
            
        except Exception as e:
            logger.error(f"❌ Fallback 처리 실패: {e}")
            return {"error": "일시적인 서비스 장애입니다."}

    # Redis가 살아있으면 -> 큐에 넣기 (Async)
    try: 
        await redis_async_client.rpush(JOB_QUEUE_KEY, json.dumps(job_data, ensure_ascii=False).encode('utf-8'))
        session.clear(); session["last_question"] = question
        return {"message": "요청 접수 완료.", "job_id": job_id}
    except Exception as e: 
        logger.error(f"❌ Redis Push 실패: {e}")
        return {"error": "대기열 등록에 실패했습니다. 잠시 후 다시 시도해 주세요."}

@app.get("/get_result/{job_id}")
def get_job_result(job_id: str):
    try:
        result_bytes = redis_client.hget(JOB_RESULTS_KEY, job_id)
        if result_bytes:
            return json.loads(result_bytes.decode('utf-8'))
        else:
            return {"status": "pending"}
    except Exception as e: raise HTTPException(status_code=500, detail=f"오류: {e}")

# --- 피드백 DB ---
FEEDBACK_DB_ID = os.getenv("NOTION_FEEDBACK_DB_ID", "2c18ade5021080448ab8d304b4777fe5")

# [수정] FeedbackRequest 모델 확장
class FeedbackRequest(BaseModel):
    job_id: str
    question: str
    answer: str
    feedback: Literal["👍", "👎"]
    reason: Optional[str] = ""     # [신규] 통계용 사유 (예: 정보부족)
    comment: Optional[str] = ""    # 상세 의견
    chat_history: Optional[str] = "" # [신규] 이전 대화 내역 (텍스트로 저장)

@app.post("/feedback")
async def handle_feedback(feedback_data: FeedbackRequest):
    if not notion: raise HTTPException(status_code=503, detail="Notion API 오류")
    
    try:
        notion.pages.create(
            parent={"database_id": "2c18ade5021080448ab8d304b4777fe5"}, # 따옴표 확인!
            properties={
                "질문": {"title": [{"text": {"content": feedback_data.question[:2000]}}]},
                "답변": {"rich_text": [{"text": {"content": feedback_data.answer[:2000]}}]},
                "평가": {"select": {"name": feedback_data.feedback}},
                
                # [신규] 사유 (선택 속성으로 저장 -> 통계 가능)
                "사유": {"select": {"name": feedback_data.reason}} if feedback_data.reason else None,
                
                # [신규] 대화내역 (문맥 파악용)
                "대화내역": {"rich_text": [{"text": {"content": feedback_data.chat_history[:2000]}}]},
                
                "상세의견": {"rich_text": [{"text": {"content": feedback_data.comment[:2000] if feedback_data.comment else ""}}]},
                "작업ID": {"rich_text": [{"text": {"content": feedback_data.job_id}}]}
            }
        )
        return {"status": "success"}
    except Exception as e:
        logger.error(f"❌ 피드백 저장 실패: {e}")
        raise HTTPException(status_code=500, detail="저장 실패")