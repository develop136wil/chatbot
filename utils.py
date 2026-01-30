import sys
# UTF-8 출력 설정 (Windows 인코딩 오류 방지)
# UTF-8 출력 설정 (Windows 인코딩 오류 방지)
try:
    if hasattr(sys.stdout, 'reconfigure') and sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass # Vercel 등 일부 환경에서는 stdout 설정 변경 불가

# [버전 마커] 배포 확인용
# [버전 마커] 배포 확인용
_UTILS_VERSION = "2026.01.29-v6"
print(f"📦 Utils 모듈 로드 (버전: {_UTILS_VERSION})")

try:
    import redis
except ImportError:
    redis = None
    
import os
import json
import time
import hashlib
import asyncio
import itertools
import re  # [긴급 수정] 정규식 모듈 추가 (expand_search_query에서 사용)
import secrets  # [추가] 보안 토큰 생성용
# redis는 위에서 이미 import됨 (중복 제거)
import warnings

# [설정] 구글 라이브러리 Deprecation 경고 숨김 (기능상 문제 없음)
warnings.filterwarnings("ignore", category=UserWarning, module="google.genai") # 신규 라이브러리 경고 방지

from dotenv import load_dotenv
try:
    from google import genai
    from google.genai import types
    print("✅ Using google.genai package")
except ImportError:
    print("❌ google.genai package not found. Please install it.")
    genai = None
    print("❌ google.genai is required for this application")
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from notion_client import Client as NotionClient
from supabase import create_client, create_async_client
from functools import lru_cache
from typing import Optional, List

# Groq import (사용 가능한 경우에만)
try:
    from groq import AsyncGroq, Groq
except ImportError:
    AsyncGroq = None
    Groq = None
    print("⚠️ Groq library not found. pip install groq")

# --- 1. 설정 로드 ---
load_dotenv()
# [Vercel 호환성] NOTION_API_KEY를 우선 확인하고, 로컬용 NOTION_KEY를 Fallback으로 사용
NOTION_KEY = os.getenv("NOTION_API_KEY", os.getenv("NOTION_KEY"))

# [수정] 설정값 로드 시 공백(.strip)을 제거하여 에러 방지
REDIS_HOST = os.getenv("REDIS_HOST", "localhost").strip()

# Supabase 설정 로드 (혹시 모를 공백 제거)
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

# [핵심] API 키 로테이션 로직
_keys_env = os.getenv("GEMINI_API_KEYS", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY") # [신규] Groq 키 로드

# 콤마로 구분된 키를 리스트로 변환 (공백 제거)
KEY_POOL = [k.strip() for k in _keys_env.split(",") if k.strip()]

# [★신규] 키를 순서대로 무한 반복해서 제공하는 이터레이터 (Round Robin)
# 랜덤이 아니므로, 1번->2번->3번... 순서가 보장되어 429 에러를 최소화합니다.
KEY_CYCLE = itertools.cycle(KEY_POOL) if KEY_POOL else None

print(f"💳 [System] 로드된 Gemini API 키 개수: {len(KEY_POOL)}개")

# --- 2. 전역 변수 ---
# [최적화] Database IDs를 환경 변수로 관리 (Fallback 값 유지)
DATABASE_IDS = {
    "의료/재활": os.getenv("NOTION_DB_MEDICAL", "2738ade50210801f9ef8ca93c1ee1f08"),
    "교육/보육": os.getenv("NOTION_DB_EDUCATION", "2738ade5021080339203d7148d7d943b"),
    "가족 지원": os.getenv("NOTION_DB_FAMILY", "2738ade502108041a4c7f5ec4c3b8413"),
    "돌봄/양육": os.getenv("NOTION_DB_CARE", "2738ade5021080cf842df820fdbeb709"),
    "생활 지원": os.getenv("NOTION_DB_LIFE", "2738ade5021080579e5be527ff1e80b2")
}
NOTION_PROPERTY_NAMES = {
    "title": "사업명", "category": "분류", "sub_category": "대상 특성",
    "start_age": "시작 월령(개월)", "end_age": "종료 월령(개월)", "support_detail": "상세 지원 내용",
    "contact": "문의처", "url1": "관련 홈페이지 1", "url2": "관련 홈페이지 2",
    "url3": "관련 홈페이지 3", "extra_req": "추가 자격요건",
    # [신규] 비용/주의사항 필드 추가 (Notion DB에 필드가 생성되어야 함)
    "cost_info": "비용 부담", "notes": "주의사항"
}

# ============================================
# [NEW] 확정적 키워드 → 카테고리 매핑 (LLM 의존성 제거)
# ============================================
KEYWORD_CATEGORY_MAP = {
    # 의료/재활 카테고리
    "검사": "의료재활", "진단": "의료재활", "치료": "의료재활", "재활": "의료재활",
    "바우처": "의료재활", "발달": "의료재활", "언어치료": "의료재활", "정밀검사": "의료재활",
    
    # 경제적 지원 카테고리 -> 생활 지원으로 통합
    "수당": "생활 지원", "급여": "의료재활", "지원금": "생활 지원", "비용": "생활 지원",
    "기저귀": "생활 지원", "분유": "생활 지원", "교통비": "생활 지원",
    
    # 돌봄/양육 카테고리
    "돌봄": "돌봄양육", "어린이집": "돌봄양육", "보육": "돌봄양육", "아이돌봄": "돌봄양육",
    "양육": "돌봄양육", "시간제": "돌봄양육",
    
    # 교육/보육 카테고리
    "특수교육": "교육보육", "입학": "교육보육", "교육": "교육보육",
    
    # 가족 지원 카테고리
    "부모": "가족지원", "상담": "가족지원", "가족": "가족지원"
}

# [NEW] 제목 매칭을 위한 핵심 키워드 (이 키워드가 제목에 없으면 순위 하락)
TITLE_MATCH_KEYWORDS = {
    "검사": ["검사", "진단", "선별"],
    "치료": ["치료", "재활", "바우처"],
    "수당": ["수당", "급여", "지원금"]
}

def get_deterministic_category(question: str) -> str:
    """
    [NEW] 질문에서 키워드를 추출하여 확정적으로 카테고리를 반환합니다.
    LLM에 의존하지 않고, 정해진 규칙에 따라 카테고리를 결정합니다.
    
    Returns:
        str: 카테고리 이름 또는 None (매칭 키워드 없을 시)
    """
    question_lower = question.lower()
    for keyword, category in KEYWORD_CATEGORY_MAP.items():
        if keyword in question_lower:
            return category
    return None

def check_title_match(query: str, title: str) -> bool:
    """
    [NEW] 쿼리의 핵심 키워드가 제목에 포함되어 있는지 확인합니다.
    
    Returns:
        bool: 제목에 관련 키워드가 있으면 True
    """
    for query_keyword, title_keywords in TITLE_MATCH_KEYWORDS.items():
        if query_keyword in query:
            return any(tk in title for tk in title_keywords)
    return True  # 매핑된 키워드가 없으면 기본적으로 True

# --- 3. 클라이언트 초기화 ---
LLM_CLIENT = None
GROQ_CLIENT = None
GROQ_SYNC_CLIENT = None

# [신규] google.genai Client 초기화 (Lazy Loading)
# 전역에서 바로 실행하지 않고, 필요할 때 호출하거나 명시적으로 초기화합니다.
def get_llm_client():
    global LLM_CLIENT
    if LLM_CLIENT:
        return LLM_CLIENT
        
    if KEY_POOL and genai:
        try:
            # 첫 번째 키로 클라이언트 생성
            LLM_CLIENT = genai.Client(api_key=KEY_POOL[0])
            print("✅ Utils: Google GenAI Client (gemini-2.5-flash) 초기화 완료")
            return LLM_CLIENT
        except Exception as e:
            print(f"⚠️ Utils: Google GenAI Client 초기화 실패: {e}")
            return None
    return None

# 하위 호환성을 위해 전역 변수는 None으로 시작
# LLM_MODEL = LLM_CLIENT (여기서는 아직 None)

# 기존 코드와의 호환성을 위해 LLM_MODEL 별칭 유지 (그러나 이제는 Client 객체임)
LLM_MODEL = LLM_CLIENT

# [신규] Groq 초기화 (Sync/Async 둘 다)
if GROQ_API_KEY and AsyncGroq and Groq:
    try:
        GROQ_CLIENT = AsyncGroq(api_key=GROQ_API_KEY)
        GROQ_SYNC_CLIENT = Groq(api_key=GROQ_API_KEY)
        print("✅ Utils: Groq (Llama-3.3) 하이브리드 클라이언트 초기화 완료")
    except Exception as e:
        print(f"⚠️ Utils: Groq 초기화 실패: {e}")
else:
    print("ℹ️ Utils: GROQ_API_KEY가 없거나 Groq 라이브러리가 없습니다. (백업 시스템 비활성)")

notion = NotionClient(auth=NOTION_KEY) if NOTION_KEY else None

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    try:
        supabase_async = create_async_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Utils: Supabase Async 클라이언트 초기화 완료")
    except Exception as e:
        print(f"⚠️ Utils: Supabase Async 클라이언트 초기화 실패: {e}")
        supabase_async = None
else:
    print("⚠️ Utils: Supabase 설정이 없습니다.")
    supabase = None
    supabase_async = None

# --- 4. Redis 클라이언트 초기화 ---
redis_client = None
redis_async_client = None
MAIN_ANSWER_CACHE_KEY = "chatbot:main_answers"
MAIN_ANSWER_CACHE_TTL = 3600

# [핵심] Vercel 환경에서는 Redis 완전 비활성화 (파일 디스크립터 고갈 방지)
_IS_VERCEL_ENV = os.getenv("VERCEL_ENV") or os.getenv("FORCE_SYNC_MODE")

if _IS_VERCEL_ENV:
    print("🔄 [Vercel] Redis 클라이언트 초기화 건너뜀 (서버리스 환경)")
    redis_client = None
    redis_async_client = None
elif redis:
    try:
        # [수정] Redis URL 형식 자동 감지 (redis://, rediss://)
        if REDIS_HOST.startswith("redis://") or REDIS_HOST.startswith("rediss://"):
            # 클라우드 Redis (Upstash, Redis Labs 등) - URL 형식
            print(f"🔗 Utils: Redis URL 형식 감지 (Cloud)")
            
            # 테스트 연결
            try:
                test_r = redis.from_url(REDIS_HOST, socket_timeout=2)
                if test_r.ping():
                    print("✅ Utils: Redis 연결 성공 (테스트 완료)")
                test_r.close()  # 테스트 연결 닫기
            except Exception:
                print("⚠️ Utils: Redis 초기 연결 테스트 실패 (무시하고 진행)")
            
            # 실제 사용용 클라이언트
            redis_client = redis.from_url(
                REDIS_HOST,
                decode_responses=False,
                socket_timeout=None
            )
            
            # 비동기 클라이언트
            redis_async_client = redis.asyncio.from_url(
                REDIS_HOST,
                decode_responses=False,
                socket_timeout=None
            )
        else:
            # 로컬 Redis - 호스트명만 제공된 경우
            print(f"🔗 Utils: Redis 호스트 형식 감지 (Local/Custom)")
            
            test_r = redis.Redis(host=REDIS_HOST, port=6379, db=0, socket_timeout=1)
            try:
                if test_r.ping():
                    print("✅ Utils: Redis 연결 성공 (테스트 완료)")
                test_r.close()  # 테스트 연결 닫기
            except Exception:
                print("⚠️ Utils: Redis 초기 연결 테스트 실패 (무시하고 진행)")
            
            redis_client = redis.Redis(
                host=REDIS_HOST, 
                port=6379, 
                db=0, 
                decode_responses=False, 
                socket_timeout=None
            )
            
            redis_async_client = redis.asyncio.Redis(
                host=REDIS_HOST,
                port=6379,
                db=0,
                decode_responses=False,
                socket_timeout=None
            )
        
        print("✅ Utils: Redis Async 연결 설정 완료")

    except Exception as e:
        print(f"⚠️ Utils: Redis 연결 실패 (캐시 기능 없이 동작합니다) - {e}")
        redis_client = None
        redis_async_client = None
else:
    print("⚠️ Utils: redis 라이브러리가 설치되지 않았습니다. (캐시 미사용)")

# --- [수정] 키 교체 함수 (Client 재생성) ---
def rotate_api_key():
    if not KEY_CYCLE: 
        print("⚠️ [Key Rotation] 교체할 키가 없습니다.")
        return
    
    try:
        next_key = next(KEY_CYCLE)
        
        masked_key = next_key[:4] + "****" + next_key[-4:] if len(next_key) > 8 else "****"
        print(f"🔄 [Key Rotation] API 키 교체 시도: {masked_key}")
        
        # [핵심] Client 객체 재생성
        global LLM_CLIENT, LLM_MODEL
        if genai:
            LLM_CLIENT = genai.Client(api_key=next_key)
            LLM_MODEL = LLM_CLIENT
        
        print("✅ [Key Rotation] GenAI Client 재설정 완료.")
        
    except Exception as e:
        print(f"❌ [Key Rotation] 키 교체 중 오류: {e}")

# --- 5. 시스템 명령어 ---
SYSTEM_INSTRUCTION_WORKER = (
    "당신은 검색된 정보를 있는 그대로 전달하는 정직한 메신저입니다. "
    "제공된 '검색된 컨텍스트(정보)'의 내용과 형식을 자의적으로 요약하거나 문장으로 바꾸지 마세요. "
    "반드시 원본의 **불렛 포인트(- 지원 내용, - 대상 등)** 형식을 그대로 유지하여 답변해야 합니다. "
    "각 검색 결과의 끝에는 반드시 [출처 번호]를 명시하세요."
)

# --- 6. 핵심 로직 함수들 ---

# [Vercel 환경 감지] 재시도 횟수 조정 (파일 디스크립터 고갈 방지)
_IS_VERCEL = os.getenv("VERCEL_ENV") or os.getenv("FORCE_SYNC_MODE")
_RETRY_ATTEMPTS = 2 if _IS_VERCEL else 5  # Vercel에서는 2번만, 로컬에서는 5번

# --- [수정] 임베딩 함수 (Client API 사용) ---
@lru_cache(maxsize=1000)
@retry(
    stop=stop_after_attempt(_RETRY_ATTEMPTS), 
    wait=wait_exponential(multiplier=1, min=1, max=5),  # 대기 시간도 단축
    retry=retry_if_exception_type(Exception)
)
def get_gemini_embedding(text: str, task_type: str = "SEMANTIC_SIMILARITY") -> Optional[List[float]]:
    client = get_llm_client() # Lazy Load (싱글톤)
    if not KEY_POOL or not client: 
        print("⚠️ Embed: No API keys or client not initialized")
        return None
    try:
        # Client 인스턴스 사용
        result = client.models.embed_content( # client 변수 사용
            model='models/text-embedding-004', 
            contents=text,
            config=types.EmbedContentConfig(task_type=task_type)
        )
        
        # 결과 처리 (Embedding 객체에서 values 추출)
        if hasattr(result, 'embeddings') and result.embeddings:
            return list(result.embeddings[0].values)
        if hasattr(result, 'embedding') and result.embedding:
            return list(result.embedding.values)
            
        # fallback for different response structure
        return list(result.embedding) if hasattr(result, 'embedding') else []
        
    except Exception as e:
        print(f"⚠️ Embed API 실패: {type(e).__name__}: {e}")
        rotate_api_key() 
        raise e

# --- [신규] 비동기 임베딩 함수 ---
async def get_gemini_embedding_async(text: str, task_type: str = "SEMANTIC_SIMILARITY") -> Optional[List[float]]:
    """비동기 버전의 임베딩 함수 (동기 함수를 비동기로 래핑)"""
    import asyncio
    if not KEY_POOL: return None
    
    try:
        # 동기 함수를 비동기로 래핑 (genai.Client는 sync-only)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, 
            lambda: get_gemini_embedding(text, task_type)
        )
        return result
        
    except Exception as e:
        print(f"⚠️ Embed API 실패 (async): {e}")
        raise e

# --- [수정] 콘텐츠 생성 함수 (Client API 사용) ---
@retry(
    stop=stop_after_attempt(_RETRY_ATTEMPTS),  # Vercel 환경에서 재시도 횟수 제한
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type(Exception)
)
def generate_content_safe(client, prompt, timeout=8, **kwargs): 
    # client 인자는 이제 LLM_CLIENT (Client 객체)입니다.
    
    # kwargs에서 설정값 추출하여 Config 객체 생성
    config_params = {}
    if 'safety_settings' in kwargs:
        config_params['safety_settings'] = kwargs.pop('safety_settings')
    if 'temperature' in kwargs:
        config_params['temperature'] = kwargs.pop('temperature')
    if 'top_p' in kwargs:
        config_params['top_p'] = kwargs.pop('top_p')
    if 'max_output_tokens' in kwargs:
        config_params['max_output_tokens'] = kwargs.pop('max_output_tokens')
    if 'response_mime_type' in kwargs:
        config_params['response_mime_type'] = kwargs.pop('response_mime_type')
        
    config = types.GenerateContentConfig(**config_params)
    
    for attempt in range(5):
        try:
            # 매 시도마다 최신 Client 객체 사용 (키 로테이션 반영)
            # 함수 인자로 받은 client보다 전역 LLM_CLIENT가 더 최신일 수 있음 (get_llm_client() 사용)
            global LLM_CLIENT
            current_client = LLM_CLIENT if LLM_CLIENT else client
            
            if not current_client:
                current_client = get_llm_client() # 없으면 생성 시도
            
            time.sleep(2) 
            
            # v1.0 동기 호출
            return current_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=config,
                # timeout은 별도 옵션일 수 있으나 여기서는 생략하거나 kwargs에 남은 것 사용
                **kwargs 
            )
            
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "Quota exceeded" in error_msg:
                print(f"🛑 [Quota Limit] 할당량 초과! ({attempt+1}/5)")
                rotate_api_key() 
                time.sleep(60) 
                continue 
            
            print(f"⚠️ API 호출 실패: {e}")
            rotate_api_key()
            time.sleep(5) 
            
    raise Exception("API 호출 5회 실패")

# --- [신규] Groq 백업 호출 함수 (모델 업데이트됨) ---
async def call_groq_backup(prompt):
    """
    Gemini가 죽었을 때 호출되는 Groq(Llama3) 백업 함수 (Async)
    """
    if not GROQ_CLIENT:
        print("❌ [Groq] 백업 클라이언트가 없습니다. (실패)")
        raise Exception("Gemini Quota Exceeded & No Groq Backup")
        
    print("🚑 [Groq] Llama-3.3-70b 백업 시스템 가동!")
    try:
        completion = await GROQ_CLIENT.chat.completions.create(
            model="llama-3.3-70b-versatile", # [수정] 백업용은 고성능 70B 모델 사용
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Answer strictly in JSON if requested."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=1024,
            top_p=1,
            stream=False,
            stop=None,
        )
        
        # 응답 포맷 맞추기 (Gemini와 호환되게 .text 속성 흉내)
        response_text = completion.choices[0].message.content
        
        class MockResponse:
            def __init__(self, text):
                self.text = text
                
        return MockResponse(response_text)
        
    except Exception as e:
        print(f"❌ [Groq] 백업 호출 실패: {e}")
        raise e

def call_groq_sync_simple(prompt, system_message="You are a helpful assistant."):
    """
    [신규] 간단한 작업을 위한 Groq 동기 호출 함수 (검색어 확장 등)
    """
    if not GROQ_SYNC_CLIENT: return None
    
    try:
        completion = GROQ_SYNC_CLIENT.chat.completions.create(
            model="llama-3.1-8b-instant", # [수정] 단순 작업은 초고속/대용량 8B 모델 사용
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=1024
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"⚠️ Groq Sync 호출 실패: {e}")
        return None

# --- [최적화] 비동기 콘텐츠 생성 함수 (Client API Async) ---
async def generate_content_safe_async(client, prompt, timeout=120, **kwargs): 
    """
    [성능 최적화] google.genai.Client.aio 사용
    """
    max_retries = 7
    consecutive_quota_errors = 0
    
    # Config 구성 (동기 함수와 동일)
    config_params = {}
    if 'safety_settings' in kwargs:
        config_params['safety_settings'] = kwargs.pop('safety_settings')
    if 'temperature' in kwargs:
        config_params['temperature'] = kwargs.pop('temperature')
    if 'top_p' in kwargs:
        config_params['top_p'] = kwargs.pop('top_p')
    if 'response_mime_type' in kwargs:
        config_params['response_mime_type'] = kwargs.pop('response_mime_type')
        
    config = types.GenerateContentConfig(**config_params)
    
    for attempt in range(max_retries):
        try:
            global LLM_CLIENT
            current_client = LLM_CLIENT if LLM_CLIENT else client
            
            if not current_client:
                 current_client = get_llm_client() # 없으면 생성 시도
            
            if not current_client:
                print("⚠️ [Async API] 클라이언트 객체가 없습니다. 로테이션 시도...")
                rotate_api_key()
                continue

            if attempt > 0:
                await asyncio.sleep(2)
            
            print(f"🚀 [Async API] 호출 시도 ({attempt+1}/{max_retries})")
            
            # [수정] v1.0 Async 호출: client.aio.models.generate_content
            # 주의: client.aio (AsyncClient) 속성을 사용해야 함
            result = await current_client.aio.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=config,
                **kwargs
            )
            
            consecutive_quota_errors = 0
            return result
            
        except Exception as e:
            error_msg = str(e)
            print(f"⚠️ [Async API] 호출 실패 ({attempt+1}/{max_retries}): {e}")
            
            if "429" in error_msg or "Quota exceeded" in error_msg:
                consecutive_quota_errors += 1
                
                retry_delay = 60
                try:
                    match = re.search(r'retry in ([\d.]+)s', error_msg)
                    if match:
                        retry_delay = max(1, min(int(float(match.group(1))), 60))
                        print(f"📊 [API] 권장 대기 시간: {retry_delay}초")
                except: pass
                
                if consecutive_quota_errors >= 2:
                    print(f"🛑 [Critical] Gemini 할당량 {consecutive_quota_errors}회 연속 초과 → Groq 전환")
                    return await call_groq_backup(prompt)

                print(f"🛑 [Async Quota Limit] 할당량 초과! {retry_delay}초 대기...")
                rotate_api_key()
                await asyncio.sleep(retry_delay)
                continue 
            
            rotate_api_key()
            await asyncio.sleep(5) 
            
    print("💀 [System] Gemini 모든 재시도 실패 → Groq 최종 호출")
    return await call_groq_backup(prompt)

def extract_info_from_question(question: str, chat_history: list[dict] = []) -> dict:
    history_formatted = "(이전 대화 없음)"
    if chat_history:
        recent_history = chat_history[-3:]
        history_formatted = "\n".join([f"  - {t['role']}: {t['content']}" for t in recent_history])

    cache_key = None
    if not chat_history:
        question_hash = hashlib.md5(question.encode('utf-8')).hexdigest()
        cache_key = f"extract_v2:{question_hash}"
        try:
            cached = redis_client.get(cache_key)
            if cached: return json.loads(cached.decode('utf-8'))
        except Exception: pass

    client = get_llm_client() # Lazy Load
    if not client: return {"error": "Gemini 모델 로드 실패"}

    # 2. 히스토리 요약 (최근 3개만)
    recent_history = chat_history[-3:] 
    history_str = "\n".join([f"{t['role']}: {t['content'][:300]}" for t in recent_history]) if recent_history else "None"

    # 3. [최종 최적화 프롬프트] 
    # 지시어는 영어(토큰 절약), 핵심 키워드는 한국어 예시(정확도 보장)
    prompt = f"""
    You are an intent classifier for a welfare chatbot.
    Analyze the user's input based on history and extract JSON.
    
    [History]
    {history_str}
    
    [Input]
    "{question}"

    [Task]
    Return ONLY a JSON object with keys: "intent", "category", "sub_category", "age" (int), "keywords" (list).

    [Rules]
    1. **intent**:
       - "show_more" (more info), "safety_block" (profanity), "exit", "reset", "out_of_scope" (weather, stocks), "small_talk".
       - "clarify_category": If input has age/target but NO service keyword (e.g., "6개월 아기", "장애 영유아").
       - null: Normal search.
    
    2. **age**:
       - Convert years('살') or 'dol'('돌') to **MONTHS**. (e.g., "3살" -> 36, "두 돌" -> 24).
       - If only months are given, use as is. Return integer or null.

    3. **category** (CRITICAL, Match specific keywords, else null):
       - ONLY assign a category for GENERIC queries (e.g., "병원비 지원", "보육료").
       - **IF the user asks for a SPECIFIC SERVICE NAME (e.g., "아동수당", "양육수당", "부모급여", "기저귀 바우처", "발달재활서비스", "아이돌봄"), SET "category" TO null.**
       - Reason: Specific services can belong to unexpected categories. Global search (null) is safer.
       
       - "의료/재활": 병원, 치료, 검사, 진단, 재활 (generic terms only).
       - "교육/보육": 어린이집, 유치원, 교육, 보육, 학습 (generic terms only).
       - "가족 지원": 상담, 부모, 가족 (generic terms only).
       - "돌봄/양육": 돌봄, 양육, 활동지원 (generic terms only).
       - "생활 지원": 바우처, 지원금, 수당, 셔틀, 교통, 차량, 기저귀, 통장 (generic terms only).
       
       * **Priority Rule:** If the input contains generic words like "복지(welfare)" or "서비스(service)" AND specific category keywords are absent, set "category" to null to broaden the search.

    4. **sub_category**:
       - Extract specific traits: "장애", "다문화", "한부모", "저소득", "발달지연".
       - **IGNORE** generic words like "아이", "아기", "영유아" (child, baby).
    
    5. **keywords**:
       - Extract core nouns for search.
       - Resolve pronouns ("그거", "거기") using [History].

    [Output Example]
    {{
        "intent": null,
        "category": "null",
        "sub_category": "null",
        "age": 24,
        "keywords": ["바우처", "신청"]
    }}
    """
    try:
        # [수정] google.genai.types.SafetySetting 객체 사용
        safety_settings = [
            types.SafetySetting(category=c, threshold="BLOCK_NONE")
            for c in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]
        ]
        
        # 앞서 추가한 generate_content_safe 함수 사용
        response = generate_content_safe(client, prompt, timeout=60, safety_settings=safety_settings) # client 전달
        # response.resolve() 제거 (v1.0에서는 불필요)

        
        response_text = response.text
        json_block_start = response_text.find('{')
        json_block_end = response_text.rfind('}') + 1
        
        if json_block_start != -1 and json_block_end != -1:
             # JSON 파싱
            json_string = response_text[json_block_start:json_block_end]
            default_info = {"age": None, "category": None, "sub_category": None, "intent": None, "keywords": None}
            extracted_info = json.loads(json_string)
            default_info.update(extracted_info)
             
            has_other_criteria = default_info.get("age") is not None or default_info.get("sub_category") is not None
            
            # [수정 2] if 문 아래 들여쓰기 수정
            if has_other_criteria and default_info.get("category") is None and default_info.get("intent") is None and not default_info.get("keywords"): 
                default_info["intent"] = "clarify_category"

            # [수정 3] 캐시 저장 로직 들여쓰기 맞춤
            if cache_key:
                try:
                     redis_client.set(cache_key, json.dumps(default_info).encode('utf-8'))
                except Exception: pass
                 
            return default_info
        
        else: 
             return {"error": "Gemini 응답 JSON 없음"}
             
    # [수정 4] try와 짝이 맞는 except 위치
    except Exception as e: 
        return {"error": f"질문 분석 중 오류: {e}"}

# --- [신규] Groq Async 호출 함수 (utils 내부용) ---
async def call_groq_async_simple(prompt: str, system_message: str = "You are a helpful assistant.", max_retries: int = 2) -> Optional[str]:
    """Helper for async Groq calls with retry"""
    if not GROQ_CLIENT: return None
    
    for attempt in range(max_retries):
        try:
            chat_completion = await GROQ_CLIENT.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt},
                ],
                model="llama-3.3-70b-versatile",
                temperature=0.1,
                max_tokens=1024,
            )
            return chat_completion.choices[0].message.content
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"⚠️ Groq Async Error (Final): {e}")
            else:
                await asyncio.sleep(1)
    return None

# --- [신규] Groq Sync 호출 함수 (run_indexer.py 등 동기 환경용) ---
def call_groq_sync_simple(prompt: str, system_message: str = "You are a helpful assistant.") -> Optional[str]:
    """Helper for sync Groq calls"""
    if not GROQ_SYNC_CLIENT: return None
    try:
        completion = GROQ_SYNC_CLIENT.chat.completions.create(
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=2048, # 번역은 길 수 있으므로 넉넉하게
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"⚠️ Groq Sync Error: {e}")
        return None

def translate_content_multilingual_sync(title: str, content: str) -> dict:
    """
    [Phase 3] 다국어 번역 (영어/중국어/베트남어) - JSON 반환
    Groq 우선 사용 -> Gemini 폴백
    """
    prompt = f"""
    You are a professional translator for a welfare chatbot.
    Translate the following Korean title and content into English, Chinese (Simplified), and Vietnamese.

    [Source]
    Title: {title}
    Content: {content}

    [Output Format]
    Return ONLY a JSON object with this exact structure:
    {{
      "en": {{ "title": "...", "content": "..." }},
      "zh": {{ "title": "...", "content": "..." }},
      "vi": {{ "title": "...", "content": "..." }}
    }}
    """
    
    # 1. Groq 시도
    if GROQ_SYNC_CLIENT:
        try:
            resp = call_groq_sync_simple(prompt, "You are a JSON translator.")
            if resp:
                 # JSON 추출
                json_start = resp.find('{')
                json_end = resp.rfind('}') + 1
                if json_start != -1 and json_end != -1:
                    return json.loads(resp[json_start:json_end])
        except Exception as e:
            print(f"⚠️ Groq Translation Failed: {e}")

    # 2. Gemini 폴백
    client = get_llm_client()
    if client:
        try:
            resp = generate_content_safe(client, prompt, timeout=40)
            text = resp.text if hasattr(resp, 'text') else str(resp)
            json_start = text.find('{')
            json_end = text.rfind('}') + 1
            if json_start != -1 and json_end != -1:
                return json.loads(text[json_start:json_end])
        except Exception as e:
            print(f"⚠️ Gemini Translation Failed: {e}")
            
    return {} # 실패 시 빈 딕셔너리


# --- [신규] 비동기 의도 분석 함수 ---
async def extract_info_from_question_async(question: str, chat_history: list[dict] = []) -> dict:
    history_formatted = "(이전 대화 없음)"
    if chat_history:
        recent_history = chat_history[-3:]
        history_formatted = "\n".join([f"  - {t['role']}: {t['content']}" for t in recent_history])

    cache_key = None
    if not chat_history:
        question_hash = hashlib.md5(question.encode('utf-8')).hexdigest()
        cache_key = f"extract_v2:{question_hash}"
        try:
            # [수정] 비동기 Redis 사용
            if redis_async_client:
                cached = await redis_async_client.get(cache_key)
                if cached: return json.loads(cached.decode('utf-8'))
        except Exception: pass

    if not LLM_MODEL and not get_llm_client(): return {"error": "Gemini 모델 로드 실패"} # check lazy

    recent_history = chat_history[-3:] 
    history_str = "\n".join([f"{t['role']}: {t['content'][:300]}" for t in recent_history]) if recent_history else "None"

    # 프롬프트는 기존과 동일하게 사용 (재사용성)
    prompt = f"""
    You are an intent classifier for a welfare chatbot.
    Analyze the user's input based on history and extract JSON.
    
    [History]
    {history_str}
    
    [Input]
    "{question}"

    [Task]
    Return ONLY a JSON object with keys: "intent", "category", "sub_category", "age" (int), "keywords" (list).

    [Rules]
    1. **intent**: "show_more", "safety_block", "exit", "reset", "out_of_scope", "small_talk", "clarify_category", null.
    2. **age**: Convert to MONTHS (int) or null.
    3. **category**: generic queries only (see utils.py rules). specific names -> null.
    4. **sub_category**: specific traits or null.
    5. **keywords**: extract core nouns.

    [Output Example]
    {{ "intent": null, "category": "null", "sub_category": "null", "age": 24, "keywords": ["바우처"] }}
    """
    
    try:
        safety_settings = [
            types.SafetySetting(category=c, threshold="BLOCK_NONE")
            for c in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]
        ]
        
        # [최적화] Groq 우선 시도 (Async)
        response_text = None
        if GROQ_CLIENT:
            try:
                # Groq는 빠르고 무료 티어 제한이 덜함
                groq_resp = await call_groq_async_simple(prompt, "You are a precise JSON extractor.")
                if groq_resp:
                    response_text = groq_resp
                    # print("⚡️ [Intent] Groq Fast Path Used") 
            except Exception as e:
                print(f"⚠️ Groq Intent Failed: {e}")

        # Groq 실패 시 Gemini Fallback
        if not response_text:
            # lazy load된 client 사용
            client = get_llm_client()
            response = await generate_content_safe_async(client, prompt, timeout=60, safety_settings=safety_settings)
            
            # 텍스트 추출
            if hasattr(response, 'text'):
                response_text = response.text
            else:
                response_text = str(response)
        


        json_block_start = response_text.find('{')
        json_block_end = response_text.rfind('}') + 1
        
        if json_block_start != -1 and json_block_end != -1:
            json_string = response_text[json_block_start:json_block_end]
            default_info = {"age": None, "category": None, "sub_category": None, "intent": None, "keywords": None}
            extracted_info = json.loads(json_string)
            default_info.update(extracted_info)
                
            has_other_criteria = default_info.get("age") is not None or default_info.get("sub_category") is not None
            
            if has_other_criteria and default_info.get("category") is None and default_info.get("intent") is None and not default_info.get("keywords"): 
                default_info["intent"] = "clarify_category"

            if cache_key and redis_async_client:
                try:
                        await redis_async_client.set(cache_key, json.dumps(default_info).encode('utf-8'))
                except Exception: pass
                    
            return default_info
        
        else: 
                return {"error": "Gemini 응답 JSON 없음"}
                
    except Exception as e: 
        return {"error": f"질문 분석 중 오류: {e}"}

def summarize_content_with_llm(context: str, original_question: str, chat_history: list[dict] = []) -> str:
    if not context: return ""
    
    # [수정] 언어 감지 로직 (느슨한 검사로 변경)
    # 괄호나 공백, 줄바꿈이 섞여도 핵심 단어만 있으면 언어를 인식하도록 수정합니다.
    target_lang = "Korean" 
    
    if "strictly in English" in original_question:
        target_lang = "English"
    elif "strictly in Vietnamese" in original_question:
        target_lang = "Vietnamese"
    elif "strictly in Chinese" in original_question:
        target_lang = "Chinese"
    
    # [중요] 캐시 키 버전을 v24로 변경 (80자 제한 추가)
    context_hash = hashlib.md5((context + target_lang).encode('utf-8')).hexdigest()
    cache_key = f"summary_v24_{target_lang}:{context_hash}"
    
    try:
        cached = redis_client.get(cache_key)
        if cached: return cached.decode('utf-8')
    except Exception: pass

    client = get_llm_client() # Lazy Load
    if not client: return "Gemini 모델 로드 실패"

    prompt = f"""
    # 사용자 원본 질문: "{original_question}"
        
    ---원본 텍스트---
    {context}

    ---
    # 지시사항:
    위 '원본 텍스트'를 바탕으로 사용자의 질문에 답변하기 위한 핵심 정보를 요약하세요.

    [★★★ 핵심 언어 규칙 ★★★]
    **결과물은 반드시 '{target_lang}'(으)로 작성해야 합니다.**
    - 헤더(항목 제목)와 내용 모두 해당 언어로 번역하세요.
    - 예: '지원 내용' -> 'Support Content' (영어일 경우)

    당신은 복지 정보 요약 전문가입니다.
        
    아래 "---원본 텍스트---"를 바탕으로 사용자의 질문에 맞춰 요약해 주세요.

    # ★★★ [Clean & Minimal Style] ★★★
    1. **간결성:** 각 항목은 명사형으로 짧고 깔끔하게 작성하세요. (~지원, ~제공)
    2. **문장 다듬기 (Polishing):** "상세 지원 내용"이 너무 길 경우, 단순히 자르지 말고 핵심 내용을 포함하여 자연스러운 문장으로 요약/정리하세요.
    3. **조건부 표시:** "신청 방법"과 "비용" 정보가 원문에 명확히 있을 때만 항목을 생성하세요. 없으면 생략하세요.
    4. **제외 대상:** '문의처', '연락처' 정보는 요약에서 **제외**하세요.
    5. **시각적 단순화:** 이모지(💵, ⛔️)를 절대 사용하지 마세요. 화면이 지저분해집니다.
    
    이 텍스트의 내용을 바탕으로, **사용자의 핵심 질문에 맞는 정보** 위주로 간결하게 요약해 주세요.

    # 추출 항목:
    1. 지원 내용 (Support Content) - **필수**
    2. 대상 (Target) - **필수**
    3. 신청 방법 (How to Apply) - **정보 있을 때만**
    4. 비용 (Cost) - **정보 있을 때만**
    
    # [출력 스타일 가이드]:
    1. **불렛 포인트:** 모든 항목은 `* ` (별표+공백)으로 시작.
    2. **헤더:** 항목 제목은 `**제목**:` 형식 사용. (예: `* **지원 내용** : ...`)
    3. **금지:** 대괄호 `[]`나 이모지를 쓰지 마세요.
    
    # [출력 예시]
    * **지원 내용** : 장애인 등록 진단서 발급비 및 검사비 지원 (최대 10만원)
    * **대상** : 도봉구 거주 영유아 (0~6세)
      * 의료급여수급자 및 차상위계층
    * **신청 방법** : 관할 보건소 방문 신청
    * **비용** : 무료 (소득 기준 충족 시)

    (여기서부터 요약을 시작하세요):
    """
    
    try:
        # 안전 설정 (의료 용어 차단 방지) - types.SafetySetting 사용
        safety_settings = [
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE")
        ]

        # [수정] safety_settings를 인자로 전달!
        # 이제 generate_content_safe가 **kwargs로 받아서 처리해 줄 거야.
        response = generate_content_safe(
            client, # client 전달 
            prompt, 
            timeout=30, 
            safety_settings=safety_settings # <--- 여기 추가!
        )
        
        # [수정] 응답 객체 처리 방식 변경
        # retry 데코레이터가 적용된 함수는 반환값을 그대로 넘깁니다.
        # generate_content의 반환값은 GenerateContentResponse 객체입니다.
        if hasattr(response, 'text'):
            summary = response.text.strip()
        else:
            summary = str(response).strip() # 혹시 문자열로 오면 그대로 사용
            
        # [Step 2] 이모지만 제거 (포맷팅 보존)
        # 1. 컬러 이모지 (Astral Plane: 💵, 😥 등)
        summary = re.sub(r'[\U0001F300-\U0001F9FF]', '', summary)
        # 2. 심볼 이모지 (⛔, ⚠️ 등)
        summary = re.sub(r'[\u2600-\u26FF]', '', summary)
        summary = re.sub(r'[\u2700-\u27BF]', '', summary)
        # 주의: 포맷팅 문자(*, -, :, [, ])는 보존
        
        try:
            redis_client.set(cache_key, summary.encode('utf-8'))
        except Exception: pass
        
        return summary

    except Exception as e: 
        print(f"⚠️ 요약 실패: {e}")
        return context[:300] + "..."

def expand_search_query(question: str) -> list:
    """
    [Upgrade Final] 다국어 질문 -> 한국어 검색어 변환 강제화
    1. (System: ...) 시스템 프롬프트 제거 (노이즈 방지 강화)
    2. 무조건 한국어 키워드로 변환하도록 프롬프트 강화 (중국어/베트남어 필수)
    """
    
    # ---------------------------------------------------------
    # 1. 노이즈 제거 (강력한 전처리)
    # ---------------------------------------------------------
    # [수정] 정규식 강화: 대소문자 무시, 공백 유연하게 처리
    clean_question = re.sub(r'\s*\(System[\s\S]*?\)', '', question, flags=re.IGNORECASE).strip()
    
    # 특수문자 제거
    clean_question = re.sub(r'[^\w\s]', '', clean_question) 
    
    # [업그레이드] 다국어 불용어 (Stop Words)
    STOP_WORDS = [
        # 한국어
        "있어", "있니", "있나요", "어디", "어디야", "알려줘", "해줘", "궁금해", 
        "무엇", "뭐야", "대한", "관한", "관련", "알고", "싶어", "해요", "되나요",
        "나와", "저기", "그거", "이거", "요", "좀", "수", "것", "등", "및", "자세히",
        "하는", "있는", "좋을", "같다고", "하셨는데", "하셨습니다", "가야하는지",
        "받아보는", "의심된다고", "같습니다", "합니다", "입니다",
        "선생님께서", "섲ㄴ생님꼐서", "어린이집에서", "아이를", "아이가", "키우고", "우리", "제가",
        
        # 영어
        "please", "answer", "strictly", "english", "in", "system", "what", "where", "how", "when", "why", 
        "can", "you", "tell", "me", "about", "is", "are", "the", "a", "an", "for", "to", "help",
        
        # 베트남어
        "là", "gì", "ở", "đâu", "như", "thế", "nào", "tại", "sao", "khi", 
        "có", "không", "của", "cho", "tôi", "hỏi", "xin", "vui", "lòng", 
        "làm", "ơn", "nhé", "ạ", "về", "cách", "được", "muốn", "biết",   
        "bạn", "chúng", "mình", "giúp", "với", "những", "các",           

        # 중국어
        "的", "了", "是", "我", "你", "他", "们", "在", "好", "吗",        
        "什么", "怎么", "如何", "请", "问", "哪里", "个", "这", "那",      
        "关于", "一下", "谢谢", "并没有", "可以", "想", "知道", "告诉",    
        "有没有", "哪里有", "什么时候", "为什么", "需要"                   
    ]
    
    # 사용자 입력 단어 1차 필터링
    raw_tokens = clean_question.split()
    refined_user_keywords = [
        k for k in raw_tokens 
        if len(k) >= 1 and k.lower() not in STOP_WORDS
    ]

    # ---------------------------------------------------------
    # 2. 비상용 키워드 (Rule Base) - 자주 검색되는 복지 용어
    # ---------------------------------------------------------
    fallback_keywords = []
    
    # 영어/한글 혼용 대응
    lower_q = question.lower()
    
    # [수정] 수당/급여 - 키워드 오염 방지 (구체적인 것만 매핑)
    if "양육수당" in clean_question:
        fallback_keywords.extend(["양육수당", "가정양육"])
    elif "부모급여" in clean_question:
        fallback_keywords.extend(["부모급여", "영아수당", "0세", "1세"])
    elif "아동수당" in clean_question:
        fallback_keywords.extend(["아동수당", "8세"])
    elif "수당" in clean_question: # 막연하게 '수당'이라고 했을 때만 전체 검색
        fallback_keywords.extend(["양육수당", "부모급여", "아동수당"])

    # [검사/진단 관련 - '지원' 단어 남발 금지]
    if "test" in lower_q or "check" in lower_q or "검사" in clean_question: 
        # '비용', '지원' 등은 질문에 포함되지 않았다면 굳이 넣지 않습니다.
        fallback_keywords.extend(["검사", "진단", "선별"])
        
    if "발달" in clean_question:
        fallback_keywords.extend(["발달", "영유아"]) # '검사'는 위에서 처리
        
    # [치료/재활 관련]
    if any(w in lower_q for w in ["therapy", "group", "social", "friend", "짝치료", "그룹"]):
        fallback_keywords.extend(["두리활동", "사회성"]) # '프로그램' 제거 (너무 흔함)
        
    if "치료" in clean_question or "재활" in clean_question:
        fallback_keywords.extend(["발달재활", "바우처", "언어치료"]) # '지원' 제거

    # ---------------------------------------------------------
    # 3. AI 확장 (Smart Expansion - Hybrid: Groq 1순위 -> Gemini 백업)
    # ---------------------------------------------------------
    ai_keywords = []
    
    # [프롬프트 공통 정의]
    expansion_prompt = f"""
    당신은 한국어 DB 검색을 위한 '다국어 통역기'입니다.
    사용자의 질문(영어/중국어/베트남어)을 분석하여, 반드시 **'한국어 핵심 키워드'**로 변환하세요.
    
    [사용자 질문]
    "{clean_question}"
    
    [★★★ 필수 변환 규칙 (어기면 안됨) ★★★]
    1. **무조건 한국어로 출력:** 질문이 외국어라도 검색 키워드는 **반드시 한국어**여야 합니다.
       - "儿童津贴" -> **"아동수당, 지급, 대상"** (O)
       - "Development test" -> **"발달, 검사, 영유아, 장애"** (O)
       
    2. **동의어 확장:**
       - "Allowance/津贴" -> "수당, 급여, 지원금"
       - "Center/中心" -> "센터, 복지관, 보육"
       - "Test/检查" -> "검사, 진단, 비용"

    3. **출력 형식:** - 설명 없이 오직 한국어 단어만 쉼표(,)로 구분하여 나열하세요.
    """

    # [1순위] Groq (Llama-3.3) 시도 - 속도 빠름
    if GROQ_SYNC_CLIENT:
        try:
            groq_response = call_groq_sync_simple(expansion_prompt, "You are a professional translator for welfare services.")
            if groq_response:
                # 마크다운 문자 제거 (**, *, : 등)
                clean_response = re.sub(r'\*+|[:\[\]]', '', groq_response)
                ai_keywords = [k.strip() for k in re.split(r'[,|\n]', clean_response) if k.strip() and len(k.strip()) > 1]
                print(f"⚡️ [Groq 확장] {ai_keywords}")
        except Exception as e:
            print(f"⚠️ Groq 확장 실패 (Gemini로 전환): {e}")

    # [2순위] Gemini 시도 (Groq 없거나 실패 시)
    if not ai_keywords and LLM_MODEL:
        try:
            response = generate_content_safe(LLM_MODEL, expansion_prompt, timeout=30)
            # 마크다운 문자 제거 (**, *, : 등)
            clean_response = re.sub(r'\*+|[:\[\]]', '', response.text)
            ai_keywords = [k.strip() for k in re.split(r'[,|\n]', clean_response) if k.strip() and len(k.strip()) > 1]
            print(f"🐢 [Gemini 확장] {ai_keywords}")
        except Exception as e:
            print(f"⚠️ AI 확장 실패: {e}")

    # ---------------------------------------------------------
    # 4. 최종 합체
    # ---------------------------------------------------------
    final_keywords = list(set(ai_keywords + fallback_keywords + refined_user_keywords))
    
    # [최종 필터링]
    # "지원", "서비스", "센터" 같은 너무나 일반적인 단어는
    # 다른 구체적인 키워드(예: "양육수당")가 있다면 제거합니다.
    # 그래야 검색 결과가 "지원"이라는 단어 하나 때문에 "특수교육 가족 지원" 같은 엉뚱한 걸 잡지 않습니다.
    GENERIC_TERMS = ["지원", "서비스", "센터", "복지", "신청", "방법", "문의", "대상"]
    
    filtered_keywords = [k for k in final_keywords if len(k) >= 1 and k.lower() not in STOP_WORDS]
    
    # 구체적인 키워드가 있는지 확인 (일반적이지 않은 단어)
    has_specific = any(k not in GENERIC_TERMS for k in filtered_keywords)
    
    if has_specific:
        # 구체적인 단어가 있다면 일반적인 단어 제거
        filtered_keywords = [k for k in filtered_keywords if k not in GENERIC_TERMS]
        
    return filtered_keywords


def rerank_search_results(question: str, candidates: list) -> list:
    """
    [Upgrade] 중복 정의 버그 수정 및 심사 기준 + 다국어 의도 파악 통합 버전
    """
    if not candidates or not LLM_MODEL: return candidates

    # [최적화] SQL에서 이미 키워드 가산점으로 정렬되었으므로 상위 15개만 봅니다.
    ranking_candidates = candidates[:15]
    
    # AI에게 보낼 후보 목록 텍스트 생성
    candidate_texts = []
    for i, doc in enumerate(ranking_candidates):
        meta = doc.get("metadata", {})
        title = meta.get("title", "")
        # 내용은 500자 요약
        content_preview = doc.get("content", "")[:500].replace("\n", " ")
        candidate_texts.append(f"[{i}] 제목: {title} | 내용: {content_preview}")

    candidates_str = "\n".join(candidate_texts)

    # [간소화된 리랭킹 프롬프트] - 일반 원칙에 집중
    prompt = f"""
    당신은 복지 정보 검색 결과의 순서를 정하는 심사위원입니다.

    사용자 질문: "{question}"

    [핵심 원칙]
    1. **제목 우선**: 질문의 핵심 단어가 **제목에 직접 포함된** 문서가 1순위입니다.
       - 예: "발달검사" 질문 → 제목에 "검사"가 있는 문서 우선
       - 예: "아동수당" 질문 → 제목에 "수당"이 있는 문서 우선
    
    2. **일반적 지원 프로그램 후순위**: 제목에 사용자가 묻는 키워드가 없고, "지원사업", "프로그램" 같은 포괄적 표현만 있으면 후순위입니다.

    3. **다국어 처리**: 외국어 질문도 의미가 맞는 한국어 문서와 매칭하세요.

    [후보 문서 목록]
    {candidates_str}

    [출력]
    가장 적합한 문서 번호(ID) 최대 3개를 쉼표로 구분하세요. (예: 3, 0, 5)
    관련 없는 문서만 있으면 아무것도 적지 마세요.
    """

    try:
        # 타임아웃 15초
        response = generate_content_safe(LLM_MODEL, prompt, timeout=120)
        
        # 숫자만 추출
        raw_indices = [int(s) for s in re.findall(r'\b\d+\b', response.text.strip())]
        
        final_results = []
        seen_indices = set()
        
        # 1. AI가 뽑은 순서대로 담기
        for idx in raw_indices:
            if idx not in seen_indices and 0 <= idx < len(ranking_candidates):
                final_results.append(ranking_candidates[idx])
                seen_indices.add(idx)
        
        # 2. AI가 선택하지 않은 나머지 문서들은 뒤에 붙이기 (혹시 모를 누락 방지)
        # (하지만 화면에는 상위 2개만 나가므로 AI의 선택이 결정적입니다)
        for i, doc in enumerate(ranking_candidates):
            if i not in seen_indices:
                final_results.append(doc)
        
        return final_results

    except Exception as e:
        print(f"⚠️ AI 랭킹 실패: {e}")
        # 실패하면 SQL 점수 순서 그대로 반환
        return candidates
    
# [utils.py] 파일 맨 아래에 추가

# --- 7. [신규] '더 보기' 및 포맷팅 헬퍼 함수 ---

import asyncio

def get_supabase_pages_by_ids(page_ids: list) -> list:
    """ID 목록으로 Supabase 데이터 조회 (동기 버전)"""
    if not page_ids or not supabase: return []
    try:
        response = supabase.table("site_pages").select("*").in_("page_id", page_ids).execute()
        
        # 중복 제거 및 정렬
        unique_pages = {item['page_id']: item['metadata'] for item in response.data}
        return [unique_pages[pid] for pid in page_ids if pid in unique_pages]
    except Exception as e:
        print(f"❌ Supabase 조회 오류: {e}")
        return []

async def get_supabase_pages_by_ids_async(page_ids: list) -> list:
    """ID 목록으로 Supabase 데이터 조회 (비동기 버전)"""
    if not page_ids or not supabase: return []
    
    # ThreadPoolExecutor로 동기 호출을 비동기처럼 실행
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, get_supabase_pages_by_ids, page_ids)
        return result
    except Exception as e:
        print(f"❌ Supabase 비동기 조회 오류: {e}")
        return []

# --- 8. 포맷팅 함수 ---

def clean_summary_text(text: str) -> str:
    """
    [수정] 불렛 스타일(* **제목**)을 인식하여
    헤더 앞줄을 띄워주고, 내용 없는 빈 헤더는 삭제합니다.
    
    [v2] 이모지/심볼 완전 제거 추가
    """
    if not text: return "요약 정보가 없습니다."
    
    # ============================================
    # [FIX] 이모지만 제거 (포맷팅 문자 보존)
    # 이전 버전이 너무 공격적이어서 불렛/화살표까지 지웠음
    # ============================================
    # 1. 컬러 이모지 (Astral Plane: 💵, 😥, 🔗 등)
    text = re.sub(r'[\U0001F300-\U0001F9FF]', '', text)
    # 2. 기타 심볼 이모지 (⛔, ⚠️, ✅ 등 - 구체적 범위만)
    text = re.sub(r'[\u2600-\u26FF]', '', text)  # Misc Symbols
    text = re.sub(r'[\u2700-\u27BF]', '', text)  # Dingbats
    text = re.sub(r'[\u2300-\u23FF]', '', text)  # Misc Technical
    # 3. 손가락/제스처 이모지
    text = re.sub(r'[\U0001F400-\U0001F4FF]', '', text)
    # ============================================

    lines = text.split('\n')
    
    # ============================================
    # [Notion 스타일 v3] 필수/조건부 섹션 관리
    # ============================================
    SHOW_SECTIONS = ["지원 내용", "대상", "신청 방법", "비용", "Support Content", "Target", "How to Apply", "Cost"]
    HIDE_KEYWORDS = [
        "문의처", "연락처", "전화번호", "문의", # 문의처 숨김
        "신청 기간", "신청 절차", "신청 장소", # 신청 방법으로 통합 유도
        "참고", "주의", "유의사항"
    ]
    
    MAX_LINES = 4  # 섹션당 최대 줄 수 (3->4로 늘려 정보량 확보)
    
    sections = {}  # {section_name: [content_lines]}
    current_section = None
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped in ["---", "***", "```"]: 
            continue
        
        # 숨길 키워드 체크
        if any(h in stripped for h in HIDE_KEYWORDS):
            current_section = None  # 해당 섹션 무시
            continue
        
        # 섹션 헤더 감지
        found_section = None
        for section in SHOW_SECTIONS:
            if section in stripped:
                found_section = section
                break
        
        if found_section:
            current_section = found_section
            if current_section not in sections:
                sections[current_section] = []
        elif current_section and len(sections.get(current_section, [])) < MAX_LINES:
            # 내용 줄 정리
            clean_line = re.sub(r'^[\s\*\-•①-⑮❶-❿0-9\.]+\s*', '', stripped)
            if clean_line and len(clean_line) > 5:
                sections[current_section].append(clean_line)
    
    # 빈 섹션 제거하고 출력 생성
    final_lines = []
    for section in SHOW_SECTIONS:
        if section in sections and sections[section]:
            final_lines.append(f"**{section}**")
            for content in sections[section][:MAX_LINES]:
                final_lines.append(f"• {content}")
    
    return "\n".join(final_lines).strip() if final_lines else "요약 정보가 없습니다."

def format_search_results(pages_metadata: list) -> str:
    cards_html = []
    
    # 1. [기존] Markdown 볼드체 패턴
    header_pattern_bold = re.compile(r'^\s*[\*\-•]?\s*\*\*(.+?)\*\*\s*:?\s*(.*)$')
    
    # 2. [기존] 이모지 헤더 패턴
    header_pattern_emoji = re.compile(r'^\s*[\*\-•]?\s*[✅💰📍📞💡📋🕒📝📌ℹ️✨⚠️🔴🔵📄🔗]\s*([^:\n]+)(?::\s*(.*))?$')

    # 3. [기존] 번호 목록 패턴
    numbered_pattern = re.compile(r'^\s*[\*\-•]?\s*(?:\*\*)?\s*([①-⑮❶-❿]|[0-9]+\.)\s*(.*)$')
    
    # 4. [신규] 당구장(참고) 패턴 (※)
    ref_pattern = re.compile(r'^\s*[\*\-•]?\s*※\s*(.*)$')

    for meta in pages_metadata:
        title = meta.get("title", "제목 없음")
        category = meta.get("category", "기타")
        summary_raw = clean_summary_text(meta.get("pre_summary", ""))
        url = meta.get("page_url", "")
        
        copy_text = f"[{category}] {title}\n\n{summary_raw}\n\n🔗 자세히 보기: {url}"
        safe_copy_text = copy_text.replace('"', '&quot;').replace("'", "&apos;")

        html_rows = []
        last_li_index = -1
        
        # [핵심] 현재 들여쓰기 레벨 상태 변수 (기본 20px)
        # 번호 항목(①...)을 만나면 35px로 늘어납니다.
        current_margin_left = "20px" 
        
        for line in summary_raw.split('\n'):
            line = line.strip()
            if not line: continue
            
            # 매칭 확인
            match_numbered = numbered_pattern.match(line)
            match_bold = header_pattern_bold.match(line)
            match_emoji = header_pattern_emoji.match(line)
            match_ref = ref_pattern.match(line)
            
            # (1) [Sub-Header] 번호 매기기 (①, 1. 등) -> 2번 사진처럼 진하게!
            if match_numbered:
                # 번호 항목이 나오면 들여쓰기 레벨을 깊게(35px) 변경할 준비를 합니다.
                full_content = f"{match_numbered.group(1)} {match_numbered.group(2)}".replace("**", "").strip()
                
                # 스타일: 검은색(#101828), 굵게(700), 들여쓰기는 상위 레벨(20px) 유지
                row = f"<li style='list-style: none; margin-bottom: 4px; margin-top: 8px; margin-left: 20px;'><span style='color: #101828; font-weight: 700;'>{full_content}</span></li>"
                html_rows.append(row)
                last_li_index = len(html_rows) - 1
                
                # ★ 핵심: 이 다음 줄부터는 들여쓰기를 더 깊게 합니다!
                current_margin_left = "35px"

            # (2) [Main Header] 헤더 (제목) -> 들여쓰기 초기화
            elif match_bold or match_emoji:
                match = match_bold if match_bold else match_emoji
                header_title = match.group(1).strip()
                content_text = match.group(2)
                content_text = content_text.strip() if content_text else ""
                
                # 새 주제가 시작되었으므로 들여쓰기 초기화 (20px)
                current_margin_left = "20px"
                
                row = f"<li style='list-style: none; margin-bottom: 6px; margin-top: 12px;'><span style='color: #101828; font-weight: 700; font-size: 1.05em;'>{header_title}</span></li>"
                html_rows.append(row)
                last_li_index = len(html_rows) - 1
                
                if content_text:
                    row_content = f"<li style='color: #475467; margin-bottom: 4px; margin-left: {current_margin_left};'>{content_text}</li>"
                    html_rows.append(row_content)
                    last_li_index = len(html_rows) - 1

            # (3) [Ref] 당구장 표시 (※) -> 깔끔한 참고 스타일
            elif match_ref:
                content = match_ref.group(1).strip()
                # 스타일: 약간 작은 글씨, 아이콘 느낌 추가
                row = f"<li style='color: #667085; font-size: 0.9em; margin-bottom: 4px; margin-left: {current_margin_left}; list-style: none;'>※ {content}</li>"
                html_rows.append(row)
                last_li_index = len(html_rows) - 1
            
            # (4) 일반 내용 (불렛 포인트 등)
            elif line.startswith("* ") or line.startswith("- ") or line.startswith("• "):
                content = re.sub(r'^[\*\-•]\s*', '', line).strip()
                # 현재 설정된 들여쓰기 값(current_margin_left)을 적용
                row = f"<li style='color: #475467; margin-bottom: 4px; margin-left: {current_margin_left};'>{content}</li>"
                html_rows.append(row)
                last_li_index = len(html_rows) - 1
            
            # (5) 끊긴 문장 이어 붙이기
            else:
                if last_li_index >= 0 and "margin-left" in html_rows[last_li_index]:
                    prev_row = html_rows[last_li_index]
                    if prev_row.endswith("</li>"):
                        new_content = prev_row[:-5] + " " + line + "</li>"
                        html_rows[last_li_index] = new_content
                    else:
                        html_rows.append(f"<li style='color: #475467; margin-left: {current_margin_left};'>{line}</li>")
                        last_li_index = len(html_rows) - 1
                else:
                    html_rows.append(f"<li style='color: #475467; margin-left: {current_margin_left};'>{line}</li>")
                    last_li_index = len(html_rows) - 1

        html_summary = f'<ul style="padding: 0; margin: 0;">{"".join(html_rows)}</ul>'

        card = f"""
        <div class="result-card">
            <div class="card-header-badge">{category}</div>
            <h3 class="card-title">{title}</h3>
            <div class="card-body">{html_summary}</div>
            <div class="card-footer">
                {f'<a href="{url}" target="_blank" class="detail-link">자세히 보기</a>' if url else ''}
                <button class="card-share-btn" data-copy="{safe_copy_text}">공유하기</button>
            </div>
        </div>
        """
        cards_html.append(card)
    
    return "".join(cards_html)
    
# --- 8.5 동기 함수들 (Worker 호환용) ---
# 주의: search_supabase, get_gemini_embedding의 진짜 동기 버전은 
# 이 파일의 다른 위치에 정의되어 있습니다. (중복 정의 제거됨)

def check_semantic_cache(query_embedding: list) -> str | None:
    """
    Worker용 동기 캐시 조회 함수
    """
    import asyncio
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(check_semantic_cache_async(query_embedding))
    finally:
        loop.close()

# [삭제됨] get_gemini_embedding 중복 정의 - 진짜 동기 버전은 파일 상단에 있음 (line ~270)

# --- 9. 의미 기반 캐시 (Semantic Cache) 함수 ---

async def check_semantic_cache_async(query_embedding: list) -> str | None:
    """
    Supabase에서 의미가 유사한(0.92 이상) 질문이 있었는지 확인하고,
    있다면 저장된 답변을 반환합니다. (비동기 버전)
    """
    try:
        # [★수정★] 기준을 0.92 -> 0.98로 대폭 상향합니다.
        # 0.98 이상이어야만 '같은 질문'으로 인정하고 캐시를 반환합니다.
        response = await supabase_async.rpc(
            "match_chat_cache",
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.92, # <--- 여기를 수정하세요!
                "match_count": 1
            }
        ).execute()
        
        if response.data and len(response.data) > 0:
            cached_answer = response.data[0]['answer']
            print(f"♻️ [Semantic Cache] 의미가 같은 질문 발견! (유사도: {response.data[0]['similarity']:.4f})")
            return cached_answer
            
    except Exception as e:
        print(f"⚠️ 캐시 확인 중 오류: {e}")
    
    return None

async def save_semantic_cache_async(question: str, answer: str, embedding: list):
    """
    새로운 질문과 답변, 벡터를 Supabase 캐시 테이블에 저장합니다. (비동기 버전)
    """
    try:
        data = {
            "question": question,
            "answer": answer,
            "embedding": embedding
        }
        await supabase_async.table("chat_cache").insert(data).execute()
        print("💾 [Semantic Cache] 새로운 대화 기억 저장 완료")
    except Exception as e:
        print(f"⚠️ 캐시 저장 실패: {e}")

def save_semantic_cache(question: str, answer: str, embedding: list):
    """
    새로운 질문과 답변, 벡터를 Supabase 캐시 테이블에 저장합니다. (동기 버전 - Worker용)
    """
    try:
        data = {
            "question": question,
            "answer": answer,
            "embedding": embedding
        }
        supabase.table("chat_cache").insert(data).execute()
        print("💾 [Semantic Cache] 새로운 대화 기억 저장 완료")
    except Exception as e:
        print(f"⚠️ 캐시 저장 실패: {e}")

# [utils.py] 맨 아래 search_supabase 함수 교체

# 원래 동기 함수 복구 (Worker 호환성)
def search_supabase(question: str, extracted_info: dict, keywords: list = []) -> list:
    """
    [Upgrade v2] 확정적 카테고리 매핑 + 제목 매칭 부스트
    """
    # 1. 임베딩 생성
    query_embedding = get_gemini_embedding(question)
    if not query_embedding: return []

    # 2. 검색어 확장
    if not keywords:
        keywords = expand_search_query(question)
    
    final_query_text = " ".join(keywords)
    
    # [NEW] 확정적 카테고리 우선 사용 (LLM 의존성 제거)
    deterministic_category = get_deterministic_category(question)
    ai_category = deterministic_category or extracted_info.get("category")
    
    print(f"🔍 [Search] 쿼리: {question} / 확정카테고리: {deterministic_category} / AI카테고리: {extracted_info.get('category')}")
    
    results = []
    
    # --- 1차 시도 (카테고리 필터 + 키워드 부스트) ---
    if ai_category:
        try:
            response = supabase.rpc(
                "hybrid_search_v3",
                {
                    "query_text": final_query_text,
                    "query_embedding": query_embedding,
                    "match_threshold": 0.45,
                    "match_count": 15,
                    "filter_category": ai_category,
                    "keywords_arr": keywords
                }
            ).execute()
            results = response.data
        except Exception as e:
            print(f"⚠️ 1차 검색 실패: {e}")

    # --- 2차 시도 (결과 부족 시 전체 검색) ---
    if not ai_category or len(results) < 3:
        try:
            response = supabase.rpc(
                "hybrid_search_v3",
                {
                    "query_text": final_query_text,
                    "query_embedding": query_embedding,
                    "match_threshold": 0.4, 
                    "match_count": 20,
                    "filter_category": None,
                    "keywords_arr": keywords
                }
            ).execute()
            
            existing_ids = {r['id'] for r in results}
            for doc in response.data:
                if doc['id'] not in existing_ids:
                    results.append(doc)
                    
        except Exception as e:
            print(f"⚠️ 2차 검색 실패: {e}")

        user_age = extracted_info.get("age")
    
        if user_age is not None and isinstance(user_age, int) and results:
            filtered_results = []
            for doc in results:
                meta = doc.get("metadata", {})
                start_age = meta.get("start_age")
                end_age = meta.get("end_age")
                doc_age_range = f"{start_age}-{end_age}" if start_age and end_age else None
                
                if doc_age_range:
                    try:
                        doc_start, doc_end = map(int, doc_age_range.split("-"))
                        if doc_start <= user_age <= doc_end:
                            filtered_results.append(doc)
                    except:
                        pass
            
            if filtered_results:
                results = filtered_results[:15]
    
    # ============================================
    # [NEW] 제목 매칭 기반 정렬 (관련성 높은 문서 상위 배치)
    # ============================================
    if results:
        matched_results = []
        unmatched_results = []
        
        for doc in results:
            title = doc.get("title", "") or doc.get("metadata", {}).get("title", "")
            if check_title_match(question, title):
                matched_results.append(doc)
            else:
                unmatched_results.append(doc)
        
        # 제목 매칭된 문서를 앞에 배치
        results = matched_results + unmatched_results
        print(f"📊 [Title Filter] 제목 매칭: {len(matched_results)}개 / 비매칭: {len(unmatched_results)}개")
    
    return results

async def search_supabase_async(question: str, extracted_info: dict, keywords: list = []) -> list:
    """
    [Upgrade] 키워드 리스트를 SQL에 직접 전달하여 정확도 향상
    """
    # 1. 임베딩 생성 (비동기)
    query_embedding = await get_gemini_embedding_async(question)
    if not query_embedding: return []

    # 2. 검색어 확장 (만약 입력된 keywords가 없으면 여기서 생성)
    if not keywords:
        keywords = expand_search_query(question)
    
    final_query_text = " ".join(keywords)
    ai_category = extracted_info.get("category")
    
    # 디버깅 출력
    print(f"🔍 [Search] 키워드: {keywords} / 카테고리: {ai_category}")

    results = []
    
    # --- 1차 시도 (카테고리 필터 + 키워드 부스트) ---
    if ai_category:
        try:
            response = await supabase_async.rpc(
                "hybrid_search_v3",
                {
                    "query_text": final_query_text,
                    "query_embedding": query_embedding,
                    "match_threshold": 0.45,  # 기준 점수
                    "match_count": 15,
                    "filter_category": ai_category,
                    "keywords_arr": keywords  # [핵심] 키워드 배열 전달
                }
            ).execute()
            results = response.data
        except Exception as e:
            print(f"⚠️ 1차 검색 실패: {e}")

    # --- 2차 시도 (결과 부족 시 전체 검색 + 키워드 부스트) ---
    if not ai_category or len(results) < 3:
        msg = "🔄 [Fallback] 전체 검색 진행..." if ai_category else "🌍 [Global] 전체 검색 진행..."
        print(msg)
        try:
            response = await supabase_async.rpc(
                "hybrid_search_v3",
                {
                    "query_text": final_query_text,
                    "query_embedding": query_embedding,
                    "match_threshold": 0.4, 
                    "match_count": 20,
                    "filter_category": None, # 필터 해제
                    "keywords_arr": keywords # [핵심] 키워드 배열 전달
                }
            ).execute()
            
            # 중복 제거 및 합치기
            existing_ids = {r['id'] for r in results}
            for doc in response.data:
                if doc['id'] not in existing_ids:
                    results.append(doc)
                    
        except Exception as e:
            print(f"⚠️ 2차 검색 실패: {e}")

        # [★신규 추가] 나이(월령) 기반 필터링 로직
        user_age = extracted_info.get("age")
    
        # 나이 정보가 있고, 검색 결과도 있다면 필터링 시도
        if user_age is not None and isinstance(user_age, int) and results:
            filtered_results = []
            for doc in results:
                meta = doc.get("metadata", {})
                start_age = meta.get("start_age")
                end_age = meta.get("end_age")
            
                # 나이 제한이 없는 문서(None)는 무조건 포함 (안전책)
                if start_age is None and end_age is None:
                    filtered_results.append(doc)
                    continue
                
                try:
                    s = int(start_age) if start_age is not None else 0
                    e = int(end_age) if end_age is not None else 1000
                
                    # 범위 안에 들면 합격
                    if s <= user_age <= e:
                        filtered_results.append(doc)
                except:
                    filtered_results.append(doc) # 에러나면 그냥 포함
        
            # [안전장치] 필터링했더니 결과가 남았다면 -> 교체
            if filtered_results:
                print(f"🧹 [Age Filter] {len(results)}개 -> {len(filtered_results)}개로 정제됨")
                results = filtered_results
            # 결과가 0개가 되어버렸다면? -> 원본 유지 (필터링 취소)
            else:
                print(f"⚠️ [Age Filter] 필터링 결과가 0개여서 원본 유지")

        return results

# --- 6. 헬퍼 함수들 ---

def _get_rich_text(properties, prop_name: str) -> str:
    prop = properties.get(prop_name, {}).get("rich_text", [])
    return "\n".join([text_part.get("plain_text", "") for text_part in prop]).strip()

def _get_number(properties, prop_name: str):
     return properties.get(prop_name, {}).get("number")

def _get_title(properties, prop_name: str) -> str:
    title_prop = properties.get(prop_name, {}).get("title", [])
    return title_prop[0].get("plain_text", "") if title_prop and title_prop[0] else "제목 없음"

def _get_select(properties, prop_name: str) -> str:
    category_prop = properties.get(prop_name, {}).get("select")
    return category_prop.get("name", "") if category_prop else "분류 없음"

def _get_multi_select(properties, prop_name: str) -> list:
    target_prop = properties.get(prop_name, {}).get("multi_select", [])
    return [item.get("name") for item in target_prop if item]

def _get_url(properties, prop_name: str) -> str:
     return properties.get(prop_name, {}).get("url", "")

# [삭제됨] expand_search_query 중복 정의 - 진짜 버전은 line ~851에 있음 (Gemini 기반)
# [삭제됨] rerank_search_results 중복 정의 - 진짜 버전은 line ~982에 있음 (AI 랭킹)


def summarize_content_with_llm(content: str, language: str = "ko") -> str:
    """다국어 번역 함수 (worker.py에서 본문 번역에 사용)"""
    client = get_llm_client()
    if not client:
        return content
    
    # 언어 코드 -> 전체 이름 매핑
    LANG_NAMES = {
        "ko": "한국어",
        "en": "English",
        "zh": "中文(简体)",
        "vi": "Tiếng Việt"
    }
    
    lang_name = LANG_NAMES.get(language, language)
    
    # 한국어면 번역 불필요
    if language == "ko":
        return content
    
    try:
        prompt = f"""다음 복지 서비스 설명을 {lang_name}로 번역해주세요. 
설명만 출력하고, 다른 말은 하지 마세요.

원문:
{content}

{lang_name} 번역:"""
        response = generate_content_safe(client, prompt, timeout=10)
        return response.text.strip() if hasattr(response, 'text') else str(response)
    except Exception as e:
        print(f"⚠️ 번역 실패: {e}")
        return content

# [삭제됨] search_supabase 중복 정의 - 진짜 동기 버전은 파일 중간에 있음 (line ~1383)
