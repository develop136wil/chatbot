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
_UTILS_VERSION = "2026.09.19-safety-v3"
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
import html
from copy import deepcopy
from runtime_policy import (CATEGORIES, INTENT_SCHEMA, SearchUnavailable, SearchResults,
    normalize_intent, fallback_intent, apply_search_filters, visible_question)
import unicodedata
import secrets  # [추가] 보안 토큰 생성용
import logging  # [추가] 구조화된 로깅
import httpx
from datetime import datetime, timedelta, timezone
# redis는 위에서 이미 import됨 (중복 제거)
import warnings

# [신규] 구조화된 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("utils")


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
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from notion_client import Client as NotionClient
from supabase import create_client, ClientOptions
from functools import lru_cache
from typing import Optional, List, Dict, Any, Tuple

# Groq import (사용 가능한 경우에만)
try:
    from groq import AsyncGroq, Groq
except ImportError:
    AsyncGroq = None
    Groq = None
    print("⚠️ Groq library not found. pip install groq")
    
# [Async] 클라이언트 초기화 Helper
def get_async_groq_client():
    return GROQ_CLIENT if GROQ_FALLBACK_ENABLED else None

# --- 1. 설정 로드 ---
load_dotenv()
# [Vercel 호환성] NOTION_API_KEY를 우선 확인하고, 로컬용 NOTION_KEY를 Fallback으로 사용
NOTION_KEY = os.getenv("NOTION_API_KEY", os.getenv("NOTION_KEY"))

# [수정] 설정값 로드 시 공백(.strip)을 제거하여 에러 방지
REDIS_URL = os.getenv("REDIS_URL", "").strip()
REDIS_HOST = REDIS_URL or os.getenv("REDIS_HOST", "localhost").strip()

# Supabase 설정 로드 (혹시 모를 공백 제거)
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
SUPABASE_CACHE_KEY = os.getenv("SUPABASE_CACHE_KEY", "").strip()
if len(SUPABASE_CACHE_KEY) >= 2 and SUPABASE_CACHE_KEY[0] == SUPABASE_CACHE_KEY[-1] in {"'", '"'}:
    # Vercel UI에 실수로 포함된 바깥쪽 따옴표는 API 키 일부가 아닙니다.
    SUPABASE_CACHE_KEY = SUPABASE_CACHE_KEY[1:-1].strip()
RESPONSE_CACHE_KEY_SOURCE = "SUPABASE_CACHE_KEY" if SUPABASE_CACHE_KEY else "SUPABASE_KEY (fallback)"
RESPONSE_CACHE_USE_DIRECT_REST = (SUPABASE_CACHE_KEY or SUPABASE_KEY).startswith("sb_secret_")
GEMINI_EMBEDDING_TIMEOUT_SECONDS = max(
    1, int(os.getenv("GEMINI_EMBEDDING_TIMEOUT_SECONDS", "15"))
)


def _env_flag(name: str, default: bool = False) -> bool:
    """환경변수의 boolean 값을 일관되게 해석합니다."""
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# 공급자 계정의 결제 상태는 코드로 확인할 수 없으므로, Gemini 키 순환은 막고
# 무료 Groq 계정으로의 단일 백업 경로만 명시적으로 관리합니다.
FREE_TIER_ONLY = _env_flag("FREE_TIER_ONLY", True)
GROQ_FALLBACK_ENABLED = (not FREE_TIER_ONLY) or _env_flag("ALLOW_FREE_TIER_GROQ_FALLBACK", True)
LIVE_TRANSLATION_ENABLED = (not FREE_TIER_ONLY) or _env_flag("ALLOW_LIVE_TRANSLATION", False)
GROQ_FAST_MODEL = os.getenv("GROQ_FAST_MODEL", "openai/gpt-oss-20b").strip() or "openai/gpt-oss-20b"
GROQ_QUALITY_MODEL = os.getenv("GROQ_QUALITY_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
FREE_TIER_TRANSLATION_MAX_TOKENS = max(512, min(int(os.getenv("FREE_TIER_TRANSLATION_MAX_TOKENS", "4096")), 8192))
SHARED_AI_BUDGET_ENABLED = _env_flag("SHARED_AI_BUDGET_ENABLED", True)
AI_DAILY_GLOBAL_LIMIT = max(1, int(os.getenv("AI_DAILY_GLOBAL_LIMIT", "100")))
AI_DAILY_CLIENT_LIMIT = max(1, int(os.getenv("AI_DAILY_CLIENT_LIMIT", "30")))
FREE_TIER_MAX_OUTPUT_TOKENS = max(64, min(int(os.getenv("FREE_TIER_MAX_OUTPUT_TOKENS", "400")), 1024))
RESPONSE_CACHE_ENABLED = _env_flag("ENABLE_RESPONSE_CACHE", True)
RESPONSE_CACHE_TABLE = "chatbot_response_cache"
RESPONSE_CACHE_TTL_SECONDS = max(
    300, min(int(os.getenv("CHAT_RESPONSE_CACHE_TTL_SECONDS", "7776000")), 15_552_000)
)
RESPONSE_CACHE_SCHEMA_VERSION = "v3"
RESPONSE_CACHE_SCOPE_TABLE = "chatbot_cache_scope_versions"
GLOBAL_CACHE_SCOPE = "__all__"
_response_cache_error_logged = False


class FreeTierQuotaExceeded(RuntimeError):
    """무료 티어 한도 초과 시 유료/다른 공급자 우회를 막기 위한 예외입니다."""


def is_quota_error(error: Exception | str) -> bool:
    message = str(error).lower()
    return "429" in message or "quota" in message or "resource_exhausted" in message

# [핵심] API 키 로테이션 로직 (단수/복수 모두 지원)
_keys_env = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY") # [신규] Groq 키 로드

# 콤마로 구분된 키를 리스트로 변환 (공백 제거)
KEY_POOL = [k.strip() for k in _keys_env.split(",") if k.strip()]

# 이전 환경변수 (GEMINI_API_KEY_1) 지원
for i in range(1, 10):
    env_k = os.getenv(f"GEMINI_API_KEY_{i}") or os.getenv(f"GEMINI_API_KEY{i}")
    if env_k and env_k.strip() not in KEY_POOL:
        KEY_POOL.append(env_k.strip())

if FREE_TIER_ONLY and len(KEY_POOL) > 1:
    # 여러 키 순환으로 무료 한도를 우회하지 않습니다.
    KEY_POOL = KEY_POOL[:1]
    print("🔒 [Free Tier] Gemini 키 순환 비활성화: 첫 번째 키만 사용합니다.")

# [★신규] 키를 순서대로 무한 반복해서 제공하는 이터레이터 (Round Robin)
# 랜덤이 아니므로, 1번->2번->3번... 순서가 보장되어 429 에러를 최소화합니다.
KEY_CYCLE = itertools.cycle(KEY_POOL) if KEY_POOL else None

SUPPORTED_LANGUAGE_CODES = {"ko", "en", "vi", "zh"}

# 결과 카드와 서버 안내 문구에서 공통으로 사용하는 다국어 표현입니다.
LOCALIZED_UI = {
    "ko": {
        "header_found": "🔎 <b>정보를 찾았습니다!</b>",
        "footer_more": "<p>🔍 <b>아직 결과가 더 남아있습니다.</b> '더 보여줘' 또는 '다음'을 입력해 보세요.</p>",
        "more_header": "🔎 <b>추가 정보 ({start}~{end}번째)</b>",
        "all_results": "✅ <b>모든 결과를 확인했습니다.</b>",
        "no_more": "더 이상 표시할 결과가 없습니다.",
        "not_found": "관련 정보를 찾지 못했습니다. 😥",
        "system_error": "시스템 오류가 발생했습니다. 😥",
        "free_tier_quota": "오늘의 무료 AI 처리 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.",
        "free_tier_daily_limit": "이 브라우저의 오늘 무료 질문 한도에 도달했습니다. 내일 다시 이용해 주세요.",
        "safety_block": "비속어는 삼가주세요. 😥 복지 정보에 대해 질문해 주세요.",
        "exit": "네, 알겠습니다. 언제든 다시 찾아주세요! 😊",
        "reset": "대화를 초기화했습니다. 무엇이 궁금하신가요? 🤖",
        "out_of_scope": "저는 영유아 복지 정보만 알려드릴 수 있어요. 😅",
        "small_talk": "안녕하세요! 도봉구 영유아 복지 챗봇입니다. 무엇을 도와드릴까요?",
        "thanks": "도움이 되어 기쁩니다! 😊",
        "clarify": "어떤 복지 정보가 궁금하신가요?",
        "cats": {},
    },
    "en": {
        "header_found": "🔎 <b>Here is the information I found!</b>",
        "footer_more": "<p>🔍 <b>There are more results.</b> Try typing 'Show more' or 'Next'.</p>",
        "more_header": "🔎 <b>Additional information ({start}–{end})</b>",
        "all_results": "✅ <b>You've viewed all results.</b>",
        "no_more": "There are no more results to display.",
        "not_found": "I couldn't find related information. 😥",
        "system_error": "A system error occurred. Please try again. 😥",
        "free_tier_quota": "Today's free AI capacity has been reached. Please try again later.",
        "free_tier_daily_limit": "This browser has reached its free daily question limit. Please try again tomorrow.",
        "safety_block": "Please avoid offensive language. 😥 Please ask about welfare information.",
        "exit": "Understood. Please visit again anytime! 😊",
        "reset": "The conversation has been reset. What would you like to know? 🤖",
        "out_of_scope": "I can provide information only about infant and child welfare. 😅",
        "small_talk": "Hello! I am the Dobong-gu infant and child welfare chatbot. How can I help?",
        "thanks": "I'm glad I could help! 😊",
        "clarify": "What welfare information would you like to know?",
        "cats": {"의료/재활": "Medical/Rehab", "교육/보육": "Edu/Care", "가족 지원": "Family Support", "돌봄/양육": "Childcare", "생활 지원": "Living Support", "기타": "Others"},
    },
    "vi": {
        "header_found": "🔎 <b>Tôi đã tìm thấy thông tin!</b>",
        "footer_more": "<p>🔍 <b>Vẫn còn kết quả.</b> Hãy thử nhập 'Xem thêm' hoặc 'Tiếp theo'.</p>",
        "more_header": "🔎 <b>Thông tin bổ sung ({start}–{end})</b>",
        "all_results": "✅ <b>Bạn đã xem tất cả kết quả.</b>",
        "no_more": "Không còn kết quả để hiển thị.",
        "not_found": "Không tìm thấy thông tin liên quan. 😥",
        "system_error": "Đã xảy ra lỗi hệ thống. Vui lòng thử lại. 😥",
        "free_tier_quota": "Đã đạt giới hạn xử lý AI miễn phí hôm nay. Vui lòng thử lại sau.",
        "free_tier_daily_limit": "Trình duyệt này đã đạt giới hạn câu hỏi miễn phí hôm nay. Vui lòng thử lại vào ngày mai.",
        "safety_block": "Vui lòng tránh dùng ngôn ngữ xúc phạm. 😥 Hãy hỏi về thông tin phúc lợi.",
        "exit": "Đã hiểu. Hãy quay lại bất cứ lúc nào! 😊",
        "reset": "Cuộc trò chuyện đã được đặt lại. Bạn muốn tìm hiểu gì? 🤖",
        "out_of_scope": "Tôi chỉ có thể cung cấp thông tin về phúc lợi cho trẻ sơ sinh và trẻ nhỏ. 😅",
        "small_talk": "Xin chào! Tôi là chatbot phúc lợi trẻ nhỏ của quận Dobong. Tôi có thể giúp gì cho bạn?",
        "thanks": "Rất vui vì đã giúp được bạn! 😊",
        "clarify": "Bạn muốn tìm hiểu thông tin phúc lợi nào?",
        "cats": {"의료/재활": "Y tế/PHCN", "교육/보육": "Giáo dục/Trông trẻ", "가족 지원": "Hỗ trợ gia đình", "돌봄/양육": "Chăm sóc", "생활 지원": "Hỗ trợ đời sống", "기타": "Khác"},
    },
    "zh": {
        "header_found": "🔎 <b>为您找到以下信息！</b>",
        "footer_more": "<p>🔍 <b>还有更多结果。</b> 请输入“更多”或“下一个”。</p>",
        "more_header": "🔎 <b>补充信息（第{start}–{end}项）</b>",
        "all_results": "✅ <b>您已查看全部结果。</b>",
        "no_more": "没有更多结果可显示。",
        "not_found": "未找到相关信息。😥",
        "system_error": "系统发生错误，请稍后重试。😥",
        "free_tier_quota": "今日免费 AI 处理额度已用完，请稍后再试。",
        "free_tier_daily_limit": "此浏览器今日的免费提问额度已用完，请明天再试。",
        "safety_block": "请避免使用不当语言。😥 请咨询福利信息。",
        "exit": "好的，随时欢迎您再次访问！😊",
        "reset": "对话已重置。您想了解什么？🤖",
        "out_of_scope": "我只能提供婴幼儿福利信息。😅",
        "small_talk": "您好！我是道峰区婴幼儿福利聊天机器人。有什么可以帮您？",
        "thanks": "很高兴能帮到您！😊",
        "clarify": "您想了解哪类福利信息？",
        "cats": {"의료/재활": "医疗/康复", "교육/보육": "教育/保育", "가족 지원": "家庭支持", "돌봄/양육": "照护/养育", "생활 지원": "生活支持", "기타": "其他"},
    },
}


for _lang, _notice in {
    "ko": "<p>현재 AI 사용이 제한되어 키워드 검색 결과를 제공합니다.</p>",
    "en": "<p>AI is currently limited. These are keyword search results.</p>",
    "vi": "<p>AI hiện bị giới hạn. Đây là kết quả tìm kiếm theo từ khóa.</p>",
    "zh": "<p>目前 AI 使用受限，以上为关键词搜索结果。</p>",
}.items():
    LOCALIZED_UI[_lang]["limited"] = _notice

def resolve_language(language: str | None = None, question: str = "") -> str:
    """명시 언어를 우선하고, 이전 클라이언트의 지시문도 호환합니다."""
    if language in SUPPORTED_LANGUAGE_CODES:
        return language
    if "strictly in English" in question:
        return "en"
    if "strictly in Vietnamese" in question:
        return "vi"
    if "strictly in Chinese" in question:
        return "zh"
    return "ko"

print(f"💳 [System] 로드된 Gemini API 키 개수: {len(KEY_POOL)}개")

# --- 2. 전역 변수 ---
# [최적화] Database IDs를 환경 변수로 관리 (Fallback 값 유지)
DATABASE_IDS = {
    "의료/재활": os.getenv("NOTION_DB_MEDICAL", "2738ade5021080b786b0d8b0c07c1ea2"),
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
    "검사": ["검사", "진단", "선별", "평가"],
    "치료": ["치료", "재활", "바우처", "서비스"],
    "수당": ["수당", "급여", "지원금", "현금"],
    "돌봄": ["돌봄", "보육", "케어", "양육"],
    "교육": ["교육", "특수", "학습", "발달"]
}

# [NEW] 언어 자동 감지 함수
def detect_language(text: str) -> str:
    """
    텍스트의 언어를 자동으로 감지합니다.
    
    Returns:
        str: 'ko', 'en', 'vi', 'zh' 중 하나
    """
    if not text:
        return 'ko'
    
    # 문자 유형별 카운트
    korean = sum(1 for c in text if '\uac00' <= c <= '\ud7a3' or '\u1100' <= c <= '\u11ff')
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    vietnamese = sum(1 for c in text if c in 'ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ')
    
    total = len(text)
    if total == 0:
        return 'ko'
    
    # 비율 계산
    if korean / total > 0.3:
        return 'ko'
    elif chinese / total > 0.3:
        return 'zh'
    elif vietnamese > 5:  # 베트남어 특수 문자가 5개 이상
        return 'vi'
    elif all(ord(c) < 128 or c.isspace() for c in text):  # ASCII only = English
        return 'en'
    
    return 'ko'  # 기본값

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

def check_title_match(query: str, title: str) -> float:
    """
    [IMPROVED] 쿼리의 핵심 키워드가 제목에 포함되어 있는지 확인합니다.
    
    Returns:
        float: 매칭 점수 (1.0 = 기본, 1.5 = 제목 매칭, 0.7 = 불일치)
    """
    query_lower = query.lower()
    title_lower = title.lower()
    
    for query_keyword, title_keywords in TITLE_MATCH_KEYWORDS.items():
        if query_keyword in query_lower:
            if any(tk in title_lower for tk in title_keywords):
                return 1.5  # 제목 매칭 시 50% 부스트
            else:
                return 0.7  # 불일치 시 30% 감점
    
    return 1.0  # 매핑된 키워드가 없으면 기본값


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
            LLM_CLIENT = genai.Client(api_key=KEY_POOL[0], http_options=types.HttpOptions(timeout=15000))
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
if GROQ_FALLBACK_ENABLED and GROQ_API_KEY and AsyncGroq and Groq:
    try:
        GROQ_CLIENT = AsyncGroq(api_key=GROQ_API_KEY, max_retries=0, timeout=10)
        GROQ_SYNC_CLIENT = Groq(api_key=GROQ_API_KEY, max_retries=0, timeout=40)
        print(f"✅ Utils: Groq 하이브리드 클라이언트 초기화 완료 (fast={GROQ_FAST_MODEL}, quality={GROQ_QUALITY_MODEL})")
    except Exception as e:
        print(f"⚠️ Utils: Groq 초기화 실패: {e}")
else:
    print("ℹ️ Utils: Groq 자동 전환이 비활성화되었습니다.")

notion = NotionClient(auth=NOTION_KEY) if NOTION_KEY else None

if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY, options=ClientOptions(postgrest_client_timeout=8))
    # [버그 수정] create_async_client는 async 함수라 await 없이 호출하면
    # 코루틴 객체가 반환됨 (RuntimeWarning: coroutine was never awaited 원인).
    # 동기 클라이언트를 재사용하고 run_in_executor로 비동기 처리합니다.
    supabase_async = supabase
    print("✅ Utils: Supabase Async 클라이언트 초기화 완료")
else:
    print("⚠️ Utils: Supabase 설정이 없습니다.")
    supabase = None
    supabase_async = None

# 응답 캐시는 RLS가 적용된 내부 테이블이므로 검색용 키와 분리할 수 있습니다.
# SUPABASE_CACHE_KEY가 없을 때만 기존 키로 폴백해 이전 배포와 호환합니다.
response_cache_client = None
if SUPABASE_URL and (SUPABASE_CACHE_KEY or SUPABASE_KEY):
    try:
        if RESPONSE_CACHE_USE_DIRECT_REST:
            # 새 Secret key는 아래의 전용 REST 요청에서 apikey 헤더만 사용합니다.
            print("✅ Utils: Supabase 응답 캐시 REST 초기화 완료 (SUPABASE_CACHE_KEY, apikey only)")
        else:
            response_cache_client = create_client(SUPABASE_URL, SUPABASE_CACHE_KEY or SUPABASE_KEY, options=ClientOptions(postgrest_client_timeout=8))
            print(f"✅ Utils: Supabase 응답 캐시 클라이언트 초기화 완료 ({RESPONSE_CACHE_KEY_SOURCE})")
    except Exception as error:
        logger.warning("응답 캐시 클라이언트 초기화 실패: %s", type(error).__name__)


def _normalize_cache_question(question: str) -> str:
    """표기 차이만 제거한 정확 일치 캐시용 질문입니다."""
    visible_question = re.sub(r"\s*\(System[\s\S]*?\)", "", question, flags=re.IGNORECASE)
    return " ".join(unicodedata.normalize("NFKC", visible_question).strip().casefold().split())


def build_response_cache_key(question: str, language: str) -> str:
    normalized_question = _normalize_cache_question(question)
    material = f"{RESPONSE_CACHE_SCHEMA_VERSION}|{language}|{normalized_question}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_response_cache_scopes(results, ai_category=None):
    # 실제 검색 범위만 사용. 출처가 없는 결과는 보수적으로 전체 범위.
    return sorted(set(getattr(results, "scopes", [GLOBAL_CACHE_SCOPE])))


def _is_valid_cached_response(response: Any) -> bool:
    if not isinstance(response, dict):
        return False
    if response.get("status") not in {"complete", "clarify"}:
        return False
    return isinstance(response.get("answer"), str)


def _log_response_cache_error_once(action: str, error: Exception) -> None:
    global _response_cache_error_logged
    if not _response_cache_error_logged:
        _response_cache_error_logged = True
        status = getattr(error, "code", None) or getattr(error, "status_code", None) or "unknown"
        logger.warning(
            "응답 캐시 %s을(를) 건너뜁니다: %s (키=%s, 상태=%s)",
            action,
            type(error).__name__,
            RESPONSE_CACHE_KEY_SOURCE,
            status,
        )


def _response_cache_is_available() -> bool:
    return bool(RESPONSE_CACHE_USE_DIRECT_REST or response_cache_client)


_cache_http_client = None

async def _secret_cache_rest_request_async(method, table, *, params=None, payload=None):
    global _cache_http_client
    if not SUPABASE_URL or not (SUPABASE_CACHE_KEY or SUPABASE_KEY):
        raise RuntimeError("Supabase server key missing")
    headers = {"apikey": SUPABASE_CACHE_KEY or SUPABASE_KEY, "Accept":"application/json"}
    if payload is not None:
        headers.update({"Content-Type":"application/json", "Prefer":"resolution=merge-duplicates,return=minimal"})
    if _cache_http_client is None or _cache_http_client.is_closed:
        _cache_http_client = httpx.AsyncClient(timeout=8.0)
    result = await _cache_http_client.request(method, f"{SUPABASE_URL.rstrip('/')}/rest/v1/{table}",
        headers=headers, params=params, json=payload)
    result.raise_for_status()
    return result.json() if result.content else []

def reserve_ai_budget_sync(actor, actor_limit=None):
    if not FREE_TIER_ONLY:
        return True
    if not SHARED_AI_BUDGET_ENABLED:
        # 무료 모드의 서버 예산을 비활성화하면 AI를 허용하지 않습니다.
        return False
    params = {"p_actor":actor, "p_global_limit":AI_DAILY_GLOBAL_LIMIT,
              "p_actor_limit":actor_limit or AI_DAILY_CLIENT_LIMIT}
    if RESPONSE_CACHE_USE_DIRECT_REST:
        response = httpx.post(f"{SUPABASE_URL.rstrip('/')}/rest/v1/rpc/chatbot_reserve_ai_request",
            headers={"apikey":SUPABASE_CACHE_KEY or SUPABASE_KEY}, json=params, timeout=8)
        response.raise_for_status()
        return response.json() is True
    if not response_cache_client:
        raise RuntimeError("Shared budget unavailable")
    return response_cache_client.rpc("chatbot_reserve_ai_request", params).execute().data is True

async def reserve_ai_budget_async(actor):
    try:
        return await asyncio.wait_for(asyncio.to_thread(reserve_ai_budget_sync, actor), 8)
    except Exception as error:
        # SQL 미적용/DB 장애 시 사용량을 알 수 없으므로 AI 호출 금지.
        logger.warning("공유 AI 예산 확인 불가: %s", type(error).__name__)
        return False

def require_runtime_schema(client):
    if client.rpc("chatbot_runtime_ready", {}).execute().data is not True:
        raise RuntimeError("Apply supabase/20260919_runtime_safety.sql before indexing")


async def get_response_cache_async(question: str, language: str) -> Optional[dict]:
    """AI 호출 전에 Supabase의 정확 일치 응답 캐시를 조회합니다."""
    if not RESPONSE_CACHE_ENABLED or not _response_cache_is_available():
        return None
    cache_key = build_response_cache_key(question, language)
    now = datetime.now(timezone.utc).isoformat()

    def _fetch() -> Optional[dict]:
        result = (
            response_cache_client.table(RESPONSE_CACHE_TABLE)
            .select("response,scope_versions,cache_version")
            .eq("cache_key", cache_key)
            .gt("expires_at", now)
            .limit(1)
            .execute()
        )
        data = result.data or []
        return data[0] if data else None

    try:
        if RESPONSE_CACHE_USE_DIRECT_REST:
            data = await _secret_cache_rest_request_async(
                "GET",
                RESPONSE_CACHE_TABLE,
                params={
                    "select": "response,scope_versions,cache_version",
                    "cache_key": f"eq.{cache_key}",
                    "expires_at": f"gt.{now}",
                    "limit": "1",
                },
            )
            cached_row = data[0] if data else None
        else:
            cached_row = await asyncio.wait_for(asyncio.to_thread(_fetch), 8)
        if not cached_row or cached_row.get("cache_version") != RESPONSE_CACHE_SCHEMA_VERSION:
            logger.info("[Response Cache] Miss: absent/expired/schema")
            return None
        response = cached_row.get("response")
        scope_versions = cached_row.get("scope_versions") or {}
        if not _is_valid_cached_response(response) or not isinstance(scope_versions, dict) or not scope_versions:
            return None
        current_versions = await get_response_cache_scope_versions_async(list(scope_versions))
        if current_versions is None:
            return None
        if any(current_versions.get(scope, 0) != int(version) for scope, version in scope_versions.items()):
            logger.info("[Response Cache] Miss: content changed")
            return None
        return response
    except Exception as error:
        _log_response_cache_error_once("조회", error)
        return None


async def get_response_cache_scope_versions_async(scopes: List[str]) -> Optional[Dict[str, int]]:
    """캐시가 의존하는 카테고리별 재색인 버전을 조회합니다."""
    if not scopes:
        return {}
    if not RESPONSE_CACHE_ENABLED or not _response_cache_is_available():
        return None

    def _fetch_versions() -> Dict[str, int]:
        result = (
            response_cache_client.table(RESPONSE_CACHE_SCOPE_TABLE)
            .select("scope,version")
            .in_("scope", scopes)
            .execute()
        )
        return {row["scope"]: int(row["version"]) for row in (result.data or [])}

    try:
        if RESPONSE_CACHE_USE_DIRECT_REST:
            loaded_rows = await _secret_cache_rest_request_async(
                "GET",
                RESPONSE_CACHE_SCOPE_TABLE,
                params={
                    "select": "scope,version",
                    "scope": f"in.({','.join(scopes)})",
                },
            )
            loaded_versions = {row["scope"]: int(row["version"]) for row in loaded_rows}
        else:
            loaded_versions = await asyncio.wait_for(asyncio.to_thread(_fetch_versions), 8)
        return {scope: loaded_versions.get(scope, 0) for scope in scopes}
    except Exception as error:
        _log_response_cache_error_once("버전 조회", error)
        return None


async def save_response_cache_async(question, language, response, scopes=None, expected_versions=None):
    if not RESPONSE_CACHE_ENABLED or not _response_cache_is_available() or not _is_valid_cached_response(response):
        return
    # 모든 캐시에 전역 버전이 필요하다는 뜻은 아닙니다. 검색 결과는 실제 범위를 전달합니다.
    scope_list = sorted(set(scopes or [GLOBAL_CACHE_SCOPE]))
    current = await get_response_cache_scope_versions_async(scope_list)
    if current is None:
        return
    if expected_versions is not None and any(current[s] != expected_versions.get(s) for s in scope_list):
        logger.info("[Response Cache] 데이터 변경 감지: 저장 생략")
        return
    record = {
        "cache_key": build_response_cache_key(question, language),
        "response": {k:v for k,v in response.items() if k != "job_id"},
        "expires_at": (datetime.now(timezone.utc)+timedelta(seconds=RESPONSE_CACHE_TTL_SECONDS)).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "cache_version": RESPONSE_CACHE_SCHEMA_VERSION,
        # 검색 이전 버전으로 저장. 저장 중 변경돼도 다음 조회에서 무효화됩니다.
        "scope_versions": {s:expected_versions[s] for s in scope_list} if expected_versions is not None else current,
    }
    try:
        if RESPONSE_CACHE_USE_DIRECT_REST:
            await _secret_cache_rest_request_async("POST", RESPONSE_CACHE_TABLE,
                params={"on_conflict":"cache_key"}, payload=record)
        else:
            await asyncio.wait_for(asyncio.to_thread(
                lambda: response_cache_client.table(RESPONSE_CACHE_TABLE).upsert(record, on_conflict="cache_key").execute()
            ), timeout=8)
        logger.info("[Response Cache] Saved (scopes=%s)", len(scope_list))
    except Exception as error:
        _log_response_cache_error_once("저장", error)


def invalidate_response_cache(client=None) -> bool:
    """재색인 성공 뒤 캐시를 비워 오래된 복지 정보를 반환하지 않게 합니다."""
    database_client = client or response_cache_client
    if not RESPONSE_CACHE_ENABLED or not database_client:
        return False
    try:
        # cache_key는 SHA-256 해시라 빈 값이 될 수 없습니다. PostgREST 삭제에는 필터가 필요합니다.
        database_client.table(RESPONSE_CACHE_TABLE).delete().neq("cache_key", "").execute()
        logger.info("응답 캐시 무효화 완료")
        return True
    except Exception as error:
        _log_response_cache_error_once("무효화", error)
        return False


def bump_response_cache_scope_versions(client, scopes: List[str]) -> bool:
    """변경된 카테고리만 원자적으로 버전 증가시켜 관련 캐시만 만료시킵니다."""
    if not RESPONSE_CACHE_ENABLED or not client or not scopes:
        return False
    unique_scopes = sorted(set(scopes) | {GLOBAL_CACHE_SCOPE})
    try:
        client.rpc(
            "bump_chatbot_cache_scope_versions",
            {"p_scopes": unique_scopes},
        ).execute()
        logger.info("응답 캐시 범위 버전 갱신 완료 (범위=%s)", len(unique_scopes))
        return True
    except Exception as error:
        _log_response_cache_error_once("범위 버전 갱신", error)
        return False


def purge_expired_response_cache(client=None) -> bool:
    """TTL이 지난 행만 정리합니다. TTL은 신선도 판단이 아닌 저장공간 정리용입니다."""
    database_client = client or response_cache_client
    if not RESPONSE_CACHE_ENABLED or not database_client:
        return False
    try:
        database_client.table(RESPONSE_CACHE_TABLE).delete().lt(
            "expires_at", datetime.now(timezone.utc).isoformat()
        ).execute()
        return True
    except Exception as error:
        _log_response_cache_error_once("만료 행 정리", error)
        return False

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
                socket_timeout=3,
                socket_connect_timeout=3,
            )
            
            # 비동기 클라이언트
            redis_async_client = redis.asyncio.from_url(
                REDIS_HOST,
                decode_responses=False,
                socket_timeout=3,
                socket_connect_timeout=3,
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
                socket_timeout=3,
                socket_connect_timeout=3,
            )
            
            redis_async_client = redis.asyncio.Redis(
                host=REDIS_HOST,
                port=6379,
                db=0,
                decode_responses=False,
                socket_timeout=3,
                socket_connect_timeout=3,
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
    if FREE_TIER_ONLY:
        # 무료 전용 모드에서는 다른 키로 한도를 우회하지 않습니다.
        return
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
# --- 6. 핵심 로직 함수들 ---

# [Vercel 환경 감지] 재시도 횟수 조정 (파일 디스크립터 고갈 방지)
_IS_VERCEL = os.getenv("VERCEL_ENV") or os.getenv("FORCE_SYNC_MODE")
_RETRY_ATTEMPTS = 2 if _IS_VERCEL else 5  # Vercel에서는 2번만, 로컬에서는 5번

# --- [수정] 임베딩 함수 (Client API 사용) ---
@lru_cache(maxsize=1000)
@retry(
    stop=stop_after_attempt(_RETRY_ATTEMPTS), 
    wait=wait_exponential(multiplier=1, min=1, max=5),  # 대기 시간도 단축
    retry=retry_if_exception(lambda error: not isinstance(error, FreeTierQuotaExceeded))
)
def get_gemini_embedding(text: str, task_type: str = "SEMANTIC_SIMILARITY") -> Optional[List[float]]:
    client = get_llm_client() # Lazy Load (싱글톤)
    if not KEY_POOL or not client: 
        print("⚠️ Embed: No API keys or client not initialized")
        return None
    try:
        # Client 인스턴스 사용
        result = client.models.embed_content( # client 변수 사용
            model='models/gemini-embedding-001', 
            contents=text,
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=768)
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
        if FREE_TIER_ONLY and is_quota_error(e):
            raise FreeTierQuotaExceeded("Gemini 무료 할당량을 모두 사용했습니다.") from e
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
        print(f"[Embedding] request started (timeout={GEMINI_EMBEDDING_TIMEOUT_SECONDS}s)")
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: get_gemini_embedding(text, task_type)
            ),
            timeout=GEMINI_EMBEDDING_TIMEOUT_SECONDS,
        )
        print("[Embedding] request completed")
        return result
    except asyncio.TimeoutError:
        print(f"[Embedding] request timed out after {GEMINI_EMBEDDING_TIMEOUT_SECONDS}s")
        raise RuntimeError("Gemini embedding request timed out")
    except Exception as e:
        print(f"⚠️ Embed API 실패 (async): {e}")
        raise e

# --- [수정] 콘텐츠 생성 함수 (Client API 사용) ---
def _generation_config(kwargs):
    translation = kwargs.pop("task", "") == "translation"
    fields = ("safety_settings", "temperature", "top_p", "max_output_tokens",
              "response_mime_type", "response_json_schema")
    params = {k:kwargs.pop(k) for k in fields if k in kwargs}
    cap = FREE_TIER_TRANSLATION_MAX_TOKENS if translation else FREE_TIER_MAX_OUTPUT_TOKENS
    if FREE_TIER_ONLY:
        params["max_output_tokens"] = min(int(params.get("max_output_tokens", cap)), cap)
    params["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return params

def _usable_response(response):
    if not getattr(response, "text", None):
        raise ValueError("Empty model response")
    for candidate in getattr(response, "candidates", None) or []:
        if "MAX_TOKENS" in str(getattr(candidate, "finish_reason", "")):
            raise ValueError("Truncated model response")
    return response

def generate_content_safe(client, prompt, timeout=8, **kwargs):
    params = _generation_config(kwargs)
    params["http_options"] = types.HttpOptions(timeout=max(1, int(timeout*1000)))
    current_client = LLM_CLIENT or client or get_llm_client()
    if not current_client:
        raise RuntimeError("Gemini client unavailable")
    # SDK HTTP 제한 1회. 외부·내부 재시도 중첩과 고정 sleep 제거.
    try:
        return _usable_response(current_client.models.generate_content(
            model="gemini-2.5-flash", contents=prompt,
            config=types.GenerateContentConfig(**params), **kwargs))
    except Exception as error:
        if is_quota_error(error):
            raise FreeTierQuotaExceeded("Gemini quota exhausted") from error
        raise

# --- [신규] Groq 백업 호출 함수 (모델 업데이트됨) ---
async def call_groq_backup(prompt):
    if not GROQ_FALLBACK_ENABLED or not GROQ_CLIENT:
        raise FreeTierQuotaExceeded("No permitted backup")
    try:
        completion = await GROQ_CLIENT.chat.completions.create(
            model=GROQ_QUALITY_MODEL, messages=[{"role":"user","content":prompt}],
            temperature=0.1, max_completion_tokens=1024, reasoning_effort="low", timeout=8)
        choice = completion.choices[0]
        if choice.finish_reason == "length" or not choice.message.content:
            raise ValueError("Incomplete backup output")
        from types import SimpleNamespace
        return SimpleNamespace(text=choice.message.content)
    except Exception as error:
        if is_quota_error(error):
            raise FreeTierQuotaExceeded("Backup quota exhausted") from error
        raise

def call_groq_sync_fast(prompt, system_message="You are a helpful assistant."):
    if not GROQ_SYNC_CLIENT:
        return None
    try:
        completion = GROQ_SYNC_CLIENT.chat.completions.create(
            model=GROQ_FAST_MODEL, messages=[{"role":"system","content":system_message},
                {"role":"user","content":prompt}],
            temperature=0.0, max_completion_tokens=512, reasoning_effort="low", timeout=8)
        choice = completion.choices[0]
        return choice.message.content if choice.finish_reason != "length" else None
    except Exception as error:
        logger.warning("Groq 보조 작업 실패: %s", type(error).__name__)
        return None

# --- [최적화] 비동기 콘텐츠 생성 함수 (Client API Async) ---
async def generate_content_safe_async(client, prompt, timeout=15, **kwargs):
    allow_groq_backup = kwargs.pop("allow_groq_backup", True)
    params = _generation_config(kwargs)
    current_client = LLM_CLIENT or client or get_llm_client()
    if not current_client:
        raise RuntimeError("Gemini client unavailable")
    try:
        return _usable_response(await asyncio.wait_for(
            current_client.aio.models.generate_content(
                model="gemini-2.5-flash", contents=prompt,
                config=types.GenerateContentConfig(**params), **kwargs),
            timeout=max(1,float(timeout))))
    except Exception as error:
        if is_quota_error(error):
            if allow_groq_backup and GROQ_FALLBACK_ENABLED:
                return await call_groq_backup(prompt)
            raise FreeTierQuotaExceeded("Gemini quota exhausted") from error
        raise

# --- [신규] Groq Async 호출 함수 (utils 내부용) ---
async def call_groq_async_simple(prompt, system_message="You are a helpful assistant.",
                                 max_retries=1, json_mode=False):
    if not GROQ_CLIENT:
        return None
    options = {}
    if json_mode:
        options["response_format"] = {"type":"json_schema", "json_schema":{
            "name":"welfare_intent", "strict":True, "schema":INTENT_SCHEMA}}
    try:
        result = await GROQ_CLIENT.chat.completions.create(
            model=GROQ_FAST_MODEL, messages=[{"role":"system","content":system_message},
                {"role":"user","content":prompt}],
            temperature=0.0, max_completion_tokens=1024, reasoning_effort="low",
            timeout=8, **options)
        if result.choices[0].finish_reason == "length":
            return None
        return result.choices[0].message.content
    except Exception as error:
        logger.warning("Groq 의도 분석 실패: %s", type(error).__name__)
        return None

# --- [신규] Groq Sync 호출 함수 (run_indexer.py 등 동기 환경용) ---
def call_groq_sync_robust(prompt, system_message="You are a helpful assistant.", *, max_tokens=2048, json_mode=False):
    if not GROQ_SYNC_CLIENT:
        return None
    try:
        options = {"response_format":{"type":"json_object"}} if json_mode else {}
        completion = GROQ_SYNC_CLIENT.chat.completions.create(
            model=GROQ_QUALITY_MODEL, messages=[{"role":"system","content":system_message},
                {"role":"user","content":prompt}],
            temperature=0.0, max_completion_tokens=min(max_tokens, FREE_TIER_TRANSLATION_MAX_TOKENS),
            reasoning_effort="low", timeout=35, **options)
        choice = completion.choices[0]
        if choice.finish_reason == "length":
            return None
        return choice.message.content
    except Exception as error:
        logger.warning("Groq 번역 실패: %s", type(error).__name__)
        return None

def translate_content_multilingual_sync(title, content, languages=("en","zh","vi")):
    languages = [lang for lang in languages if lang in ("en","zh","vi")]
    if not languages:
        return {}
    prompt = f"""Translate this Korean welfare title and content into {', '.join(languages)}.
Return a JSON object whose language keys each contain string title and content.
Preserve all amounts, ages, qualifications and exclusions. Do not add or omit conditions.
Title: {title}
Content: {content}
"""
    output = {}
    def accept(text):
        try:
            parsed = json.loads(text)
        except (ValueError,TypeError):
            return
        if not isinstance(parsed,dict):
            return
        for lang in languages:
            value = parsed.get(lang)
            if isinstance(value,dict) and all(isinstance(value.get(k),str) and value[k].strip() for k in ("title","content")):
                output[lang] = {"title":value["title"].strip(),"content":value["content"].strip()}
    accept(call_groq_sync_robust(prompt, "Return complete JSON only.",
                               max_tokens=FREE_TIER_TRANSLATION_MAX_TOKENS, json_mode=True))
    missing = [lang for lang in languages if lang not in output]
    if missing:
        try:
            schema = {"type":"object","properties":{lang:{"type":"object","properties":{
                "title":{"type":"string"},"content":{"type":"string"}},
                "required":["title","content"],"additionalProperties":False} for lang in missing},
                "required":missing,"additionalProperties":False}
            reply = generate_content_safe(get_llm_client(), prompt+"\nReturn only: "+", ".join(missing),
                timeout=35, task="translation", max_output_tokens=FREE_TIER_TRANSLATION_MAX_TOKENS,
                response_mime_type="application/json", response_json_schema=schema)
            accept(reply.text)
        except Exception as error:
            logger.warning("미완료 번역: %s (languages=%s)",type(error).__name__,",".join(missing))
    return output


# --- [신규] 비동기 의도 분석 함수 ---
def _fallback_question_info(question):
    return fallback_intent(question)


async def extract_info_from_question_async(question, chat_history=None):
    history = chat_history or []
    clean = visible_question(question)
    prompt = f"""
Classify a welfare information question. Return the required JSON object.
Categories must be null or one of: {json.dumps(CATEGORIES, ensure_ascii=False)}.
Specific service names: category=null. Never invent category names.
age: integer months, or null when unknown. sub_category: explicit trait or null.
keywords: up to 8 core nouns. intent: null for a welfare search.
Allowed other intents: show_more, safety_block, exit, reset, out_of_scope, small_talk, clarify_category.
search_query: a standalone question in the user's language.
Use history ONLY to resolve explicit follow-up references. Preserve age, target and constraints.
For independent questions keep the original question. Do not add unsupported facts.
History: {json.dumps(history[-4:], ensure_ascii=False)}
Question: {clean}
"""
    if GROQ_FALLBACK_ENABLED and GROQ_CLIENT:
        text = await call_groq_async_simple(prompt, "Return valid JSON matching the schema.", json_mode=True)
        if text:
            try:
                return normalize_intent(json.loads(text), clean)
            except (ValueError, TypeError):
                logger.warning("Groq 의도 JSON 검증 실패")
    try:
        response = await generate_content_safe_async(get_llm_client(), prompt, timeout=8,
            response_mime_type="application/json", response_json_schema=INTENT_SCHEMA,
            allow_groq_backup=False)
        return normalize_intent(json.loads(response.text), clean)
    except Exception as error:
        logger.warning("의도 분석 대체 경로: %s", type(error).__name__)
        return fallback_intent(clean)

def generate_answer_from_context(context: str, original_question: str, chat_history: list[dict] = []) -> str:
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
            redis_client.set(cache_key, summary.encode('utf-8'), ex=MAIN_ANSWER_CACHE_TTL)
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

    # [1순위] Groq 빠른 모델 시도
    if GROQ_SYNC_CLIENT:
        try:
            groq_response = call_groq_sync_fast(expansion_prompt, "You are a professional translator for welfare services.")
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

def get_supabase_pages_by_ids(page_ids):
    if not page_ids:
        return []
    if not supabase:
        raise SearchUnavailable("Database unavailable")
    response = supabase.table("site_pages").select("page_id,metadata").in_("page_id",page_ids).execute()
    pages = {row["page_id"]:row["metadata"] for row in response.data}
    return [pages[pid] for pid in page_ids if pid in pages]

async def get_supabase_pages_by_ids_async(page_ids):
    return await asyncio.wait_for(asyncio.to_thread(get_supabase_pages_by_ids, page_ids), 8)

# --- 8. 포맷팅 함수 ---

def clean_summary_text(text: str, language: str = "ko") -> str:
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
    SHOW_SECTIONS = [
        "지원 내용", "대상", "신청 방법", "비용",
        "Support Content", "Target", "How to Apply", "Cost",
        "Nội dung hỗ trợ", "Đối tượng", "Cách đăng ký", "Chi phí",
        "支持内容", "对象", "申请方法", "费用",
    ]
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
            # "**Support Content**: ..."처럼 헤더와 내용이 같은 줄에
            # 있는 번역 결과도 버리지 않고 카드 본문에 유지합니다.
            inline_content = stripped.split(found_section, 1)[1].strip(" *:-：")
            if inline_content and len(inline_content) > 2:
                sections[current_section].append(inline_content)
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
    
    if final_lines:
        return "\n".join(final_lines).strip()
    empty_messages = {
        "ko": "요약 정보가 없습니다.",
        "en": "No summary information is available.",
        "vi": "Không có thông tin tóm tắt.",
        "zh": "暂无摘要信息。",
    }
    return empty_messages.get(language, empty_messages["ko"])

def format_search_results(pages_metadata: list, language: str = "ko") -> str:
    cards_html = []
    labels = {
        "ko": ("자세히 보기", "공유하기"), "en": ("View Details", "Share"),
        "vi": ("Xem chi tiết", "Chia sẻ"), "zh": ("查看详情", "分享"),
    }
    detail_label, share_label = labels.get(language, labels["ko"])
    
    # 1. [기존] Markdown 볼드체 패턴
    header_pattern_bold = re.compile(r'^\s*[\*\-•]?\s*\*\*(.+?)\*\*\s*:?\s*(.*)$')
    
    # 2. [기존] 이모지 헤더 패턴
    header_pattern_emoji = re.compile(r'^\s*[\*\-•]?\s*[✅💰📍📞💡📋🕒📝📌ℹ️✨⚠️🔴🔵📄🔗]\s*([^:\n]+)(?::\s*(.*))?$')

    # 3. [기존] 번호 목록 패턴
    numbered_pattern = re.compile(r'^\s*[\*\-•]?\s*(?:\*\*)?\s*([①-⑮❶-❿]|[0-9]+\.)\s*(.*)$')
    
    # 4. [신규] 당구장(참고) 패턴 (※)
    ref_pattern = re.compile(r'^\s*[\*\-•]?\s*※\s*(.*)$')
    
    # ============================================
    # 5. [신규] 동적 소제목 감지 - 다국어 헤더 키워드
    # ============================================
    HEADER_KEYWORDS = [
        # ============ 한국어 ============
        # 복합 키워드 우선 (긴 것 먼저)
        "지원 금액/규모", "금액/규모", "지원금액/규모",
        "지원 내용", "지원내용", "지원 금액", "지원금액", 
        "지원 대상", "지원대상", "신청 대상", "대상",
        "비용 부담", "본인부담금", "비용",
        "신청 방법", "신청방법", "신청 절차", "신청절차", "이용 방법", "이용방법",
        "신청 기간", "신청기간", "접수 기간",
        "서비스 내용", "서비스내용", "주요 내용",
        "참고 사항", "참고사항", "주의사항", "유의사항", 
        "금액", "규모", "기타",
        
        # ============ English ============
        "Support Content", "Service Content", "Service Details", "What's Included",
        "Support Amount/Scale", "Amount/Scale", "Support Amount", "Amount", "Scale",
        "Target Audience", "Eligibility", "Who Can Apply", "Target",
        "Cost Information", "Cost/Fee", "User Fee", "Cost", "Fee",
        "How to Apply", "Application Method", "Application Process", "How to Use",
        "Application Period", "Registration Period",
        "Important Notes", "Caution", "Notes", "Reference",
        
        # ============ Vietnamese (Tiếng Việt) ============
        "Nội dung hỗ trợ", "Nội dung dịch vụ", "Chi tiết dịch vụ",
        "Số tiền hỗ trợ", "Số tiền/Quy mô", "Số tiền", "Quy mô",
        "Đối tượng hỗ trợ", "Đối tượng đăng ký", "Đối tượng",
        "Chi phí", "Phí dịch vụ", "Phí",
        "Cách đăng ký", "Phương pháp đăng ký", "Quy trình đăng ký", "Cách sử dụng",
        "Thời gian đăng ký", "Kỳ đăng ký",
        "Lưu ý", "Chú ý", "Ghi chú", "Tham khảo",
        
        # ============ Chinese (中文) ============
        "支持内容", "服务内容", "服务详情", "包含内容",
        "支持金额/规模", "金额/规模", "支持金额", "金额", "规模",
        "支持对象", "申请对象", "目标人群", "对象",
        "费用信息", "费用/收费", "用户费用", "费用", "收费",
        "申请方法", "如何申请", "申请流程", "使用方法",
        "申请期间", "登记期间",
        "注意事项", "注意", "备注", "参考"
    ]
    # [수정] 키워드를 길이 내림차순으로 정렬 (긴 것이 먼저 매칭되도록)
    sorted_keywords = sorted(HEADER_KEYWORDS, key=len, reverse=True)
    subheader_keywords_pattern = '|'.join(re.escape(k) for k in sorted_keywords)
    subheader_pattern = re.compile(
        rf'^[\s•*\-]*({subheader_keywords_pattern})[\s:]*(.*)$', re.IGNORECASE
    )

    for meta in pages_metadata:
        raw_title = str(meta.get("title", "제목 없음"))
        raw_category = str(meta.get("category", "기타"))
        # DB와 번역 모델의 텍스트는 신뢰하지 않고 HTML로 이스케이프합니다.
        title = html.escape(raw_title)
        category = html.escape(raw_category)
        summary_raw = html.escape(clean_summary_text(meta.get("pre_summary", ""), language))
        raw_url = str(meta.get("page_url", "")).strip()
        url = raw_url if raw_url.startswith(("https://", "http://")) else ""
        safe_url = html.escape(url, quote=True)
        
        copy_text = f"[{raw_category}] {raw_title}\n\n{clean_summary_text(meta.get('pre_summary', ''), language)}\n\n🔗 {detail_label}: {url}"
        safe_copy_text = html.escape(copy_text, quote=True)

        html_rows = []
        current_margin_left = "20px"
        last_li_index = -1
        for line in summary_raw.split('\n'):

            line = line.strip()
            if not line: continue
            
            # 매칭 확인
            match_numbered = numbered_pattern.match(line)
            match_bold = header_pattern_bold.match(line)
            match_emoji = header_pattern_emoji.match(line)
            match_ref = ref_pattern.match(line)
            match_subheader = subheader_pattern.match(line)  # [신규] 동적 소제목 매칭
            
            # (1) [Sub-Header] 번호 매기기 (①, 1. 등) -> 2번 사진처럼 진하게!
            if match_numbered:
                # 번호 항목이 나오면 들여쓰기 레벨을 깊게(35px) 변경할 준비를 합니다.
                full_content = f"{match_numbered.group(1)} {match_numbered.group(2)}".replace("**", "").strip()
                
                # 스타일: CSS 클래스로 분리 (다크모드 지원)
                row = f"<li style='list-style: none; margin-bottom: 4px; margin-top: 8px; margin-left: 20px;'><span class='card-list-numbered'>{full_content}</span></li>"
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
                
                row = f"<li style='list-style: none; margin-bottom: 6px; margin-top: 12px;'><span class='card-list-header'>{header_title}</span></li>"
                html_rows.append(row)
                last_li_index = len(html_rows) - 1
                
                if content_text:
                    row_content = f"<li class='card-list-text' style='margin-bottom: 4px; margin-left: {current_margin_left};'>{content_text}</li>"
                    html_rows.append(row_content)
                    last_li_index = len(html_rows) - 1

            # (3) [Ref] 당구장 표시 (※) -> 깔끔한 참고 스타일
            elif match_ref:
                content = match_ref.group(1).strip()
                # 스타일: 약간 작은 글씨, 아이콘 느낌 추가 (클래스로 분리)
                row = f"<li class='card-list-ref' style='margin-bottom: 4px; margin-left: {current_margin_left};'>※ {content}</li>"
                html_rows.append(row)
                last_li_index = len(html_rows) - 1
            
            # (3.5) [신규] 동적 소제목 감지 - 다국어 헤더 키워드 매칭
            elif match_subheader:
                header_title = match_subheader.group(1).strip()
                content_text = match_subheader.group(2).strip() if match_subheader.group(2) else ""
                # 새 주제가 시작되었으므로 들여쓰기 초기화 (20px)
                current_margin_left = "20px"
                
                # [수정] 짧은 보조 텍스트(괄호, 20자 이하)는 헤더와 같은 줄에 표시
                if content_text and len(content_text) <= 20 and (content_text.startswith("(") or content_text.startswith("：")):
                    # 헤더 + 보조 텍스트를 한 줄에 표시
                    row = f"<li style='list-style: none; margin-bottom: 6px; margin-top: 12px;'><span class='card-list-header'>{header_title}</span> <span class='card-list-header-aux'>{content_text}</span></li>"
                    html_rows.append(row)
                    last_li_index = len(html_rows) - 1
                else:
                    # 볼드 스타일 적용 (Main Header와 동일한 스타일)
                    row = f"<li style='list-style: none; margin-bottom: 6px; margin-top: 12px;'><span class='card-list-header'>{header_title}</span></li>"
                    html_rows.append(row)
                    last_li_index = len(html_rows) - 1
                    
                    # 헤더 뒤에 긴 내용이 있으면 별도 항목으로 추가
                    if content_text:
                        row_content = f"<li class='card-list-text' style='margin-bottom: 4px; margin-left: {current_margin_left};'>{content_text}</li>"
                        html_rows.append(row_content)
                        last_li_index = len(html_rows) - 1
            
            # (4) 일반 내용 (불렛 포인트 등)
            elif line.startswith("* ") or line.startswith("- ") or line.startswith("• "):
                content = re.sub(r'^[\*\-•]\s*', '', line).strip()
                # 현재 설정된 들여쓰기 값(current_margin_left)을 적용
                row = f"<li class='card-list-text' style='margin-bottom: 4px; margin-left: {current_margin_left};'>{content}</li>"
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
                        html_rows.append(f"<li class='card-list-text' style='margin-left: {current_margin_left};'>{line}</li>")
                        last_li_index = len(html_rows) - 1
                else:
                    html_rows.append(f"<li class='card-list-text' style='margin-left: {current_margin_left};'>{line}</li>")
                    last_li_index = len(html_rows) - 1

        html_summary = f'<ul style="padding: 0; margin: 0;">{"".join(html_rows)}</ul>'

        card = f"""
        <div class="result-card">
            <div class="card-header-badge">{category}</div>
            <h3 class="card-title">{title}</h3>
            <div class="card-body">{html_summary}</div>
            <div class="card-footer">
                {f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" class="detail-link">{detail_label}</a>' if url else ''}
                <button class="card-share-btn" data-copy="{safe_copy_text}">{share_label}</button>
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

# 원래 동기 함수 복구 (Worker 호환성)
def search_supabase(question: str, extracted_info: dict, keywords: list = []) -> list:
    """
    [Upgrade v2] 확정적 카테고리 매핑 + 제목 매칭 부스트
    """
    # 1. 임베딩 생성
    # [핵심 수정] 인덱싱(RETRIEVAL_DOCUMENT) ↔ 검색(RETRIEVAL_QUERY) 벡터 공간 일치
    query_embedding = get_gemini_embedding(question, task_type="RETRIEVAL_QUERY")
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

async def _lexical_search(question, info, keywords):
    if not supabase_async:
        raise SearchUnavailable("Database unavailable")
    tokens = list(dict.fromkeys(keywords or visible_question(question).split()))[:6]
    tokens = [re.sub(r'[%_(),"\\]', " ", str(t)).strip()[:80] for t in tokens]
    tokens = [t for t in tokens if len(t)>1]
    if not tokens:
        return SearchResults([], cacheable=False)
    # ilike 인수는 따옴표로 감싸 PostgREST 논리식 경계를 고정합니다.
    expressions = [f"{field}.ilike.{json.dumps('%'+token+'%', ensure_ascii=False)}"
        for token in tokens for field in ("content", "metadata->>title_en", "metadata->>title_vi", "metadata->>title_zh")]
    try:
        response = await asyncio.wait_for(asyncio.to_thread(lambda:
            supabase_async.table("site_pages").select("page_id,metadata").or_(",".join(expressions)).limit(20).execute()), 8)
        return SearchResults(apply_search_filters(response.data or [], info), cacheable=False)
    except Exception as error:
        raise SearchUnavailable("Keyword search failed") from error

async def search_supabase_async(question, extracted_info, keywords=None, allow_ai=True):
    info = normalize_intent(extracted_info, question)
    if not allow_ai:
        return await _lexical_search(question, info, keywords)
    try:
        embedding = await get_gemini_embedding_async(question, task_type="RETRIEVAL_QUERY")
    except Exception as error:
        logger.warning("임베딩 대체(키워드 검색): %s", type(error).__name__)
        return await _lexical_search(question, info, keywords)
    if not embedding:
        return await _lexical_search(question, info, keywords)
    if not supabase_async:
        raise SearchUnavailable("Database unavailable")
    keywords = keywords or info["keywords"] or visible_question(question).split()
    category = info["category"]
    async def query(category_filter, threshold, count):
        try:
            response = await asyncio.wait_for(asyncio.to_thread(lambda:
                supabase_async.rpc("hybrid_search_v3", {
                    "query_text":" ".join(keywords), "query_embedding":embedding,
                    "match_threshold":threshold, "match_count":count,
                    "filter_category":category_filter, "keywords_arr":keywords,
                }).execute()), 8)
            if not isinstance(response.data, list):
                raise ValueError("Invalid search result")
            return response.data
        except Exception as error:
            raise SearchUnavailable("Database search failed") from error
    rows = await query(category, 0.45, 15) if category else []
    scopes = [category] if category else [GLOBAL_CACHE_SCOPE]
    if not category or len(apply_search_filters(rows, info)) < 3:
        global_rows = await query(None, 0.4, 20)
        scopes = [GLOBAL_CACHE_SCOPE]
        def identity(row):
            return row.get("id") or row.get("page_id") or (row.get("metadata") or {}).get("page_id")
        seen = {identity(r) for r in rows}
        for row in global_rows:
            if identity(row) not in seen:
                rows.append(row)
                seen.add(identity(row))
    return SearchResults(apply_search_filters(rows, info), scopes=scopes)

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




def translate_content_simple(content: str, language: str = "ko") -> str:
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

async def translate_content_simple_async(content: str, language: str = "ko") -> str:
    """[Async] 다국어 번역 함수"""
    client = get_llm_client()
    if not client: return content
    
    LANG_NAMES = {
        "ko": "한국어", "en": "English",
        "zh": "中文(简体)", "vi": "Tiếng Việt"
    }
    lang_name = LANG_NAMES.get(language, language)
    
    if language == "ko": return content
    
    try:
        prompt = f"""다음 복지 서비스 설명을 {lang_name}로 번역해주세요. 
설명만 출력하고, 다른 말은 하지 마세요.

원문:
{content}

{lang_name} 번역:"""
        
        # Async Generate
        response = await generate_content_safe_async(client, prompt, timeout=10, temperature=0.0)
        return response.text.strip() if hasattr(response, 'text') else str(response)
    except Exception as e:
        logger.warning(f"⚠️ Async Translate Error: {e}")
        return content


async def translate_titles_batch_async(titles: List[str], language: str) -> List[str]:
    """결과 카드 제목을 한 요청으로 번역하고 원래 순서를 보존합니다."""
    if not titles or language == "ko":
        return titles

    client = get_llm_client()
    if not client:
        return titles

    language_name = {"en": "English", "vi": "Vietnamese", "zh": "Chinese (Simplified)"}.get(language)
    if not language_name:
        return titles

    prompt = f"""
Translate the following welfare service titles into {language_name}.
[Input Titles]
{json.dumps(titles, ensure_ascii=False)}
[Rules]
1. Return ONLY a valid JSON list of strings.
2. Maintain the exact same order.
3. No explanations.
"""
    try:
        response = await generate_content_safe_async(client, prompt, timeout=10, temperature=0.0)
        translated_text = response.text.strip() if hasattr(response, "text") else str(response).strip()
        if translated_text.startswith("```"):
            translated_text = translated_text.split("\n", 1)[1]
            if translated_text.endswith("```"):
                translated_text = translated_text.rsplit("\n", 1)[0]
        translated = json.loads(translated_text)
        return translated if isinstance(translated, list) and len(translated) == len(titles) else titles
    except Exception as e:
        logger.warning(f"⚠️ 카드 제목 번역 실패: {e}")
        return titles


async def localize_result_pages_async(pages_metadata: List[Dict[str, Any]], language: str, *, allow_live: bool = True) -> List[Dict[str, Any]]:
    """일반 검색과 '더 보여줘'가 동일한 카드 현지화 경로를 사용하게 합니다."""
    language = resolve_language(language)
    pages_metadata = deepcopy(pages_metadata)
    if language == "ko" or not pages_metadata:
        return pages_metadata

    ui_text = LOCALIZED_UI[language]
    title_targets: List[Tuple[int, str]] = []
    summary_targets: List[Tuple[int, Any]] = []

    for index, page in enumerate(pages_metadata):
        if not isinstance(page, dict):
            continue
        # 검색 결과는 {metadata: {...}} 형태이고, '더 보여줘' 조회는
        # metadata 자체를 반환합니다. 두 형식을 모두 지원합니다.
        metadata = page.get("metadata", page)
        if not isinstance(metadata, dict):
            continue

        translated_title = metadata.get(f"title_{language}")
        if translated_title:
            metadata["title"] = translated_title
        else:
            title_targets.append((index, metadata.get("title", "")))

        original_category = metadata.get("category", "기타")
        metadata["category"] = ui_text["cats"].get(original_category, original_category)

        translated_summary = metadata.get(f"pre_summary_{language}")
        if translated_summary:
            metadata["pre_summary"] = translated_summary
        elif LIVE_TRANSLATION_ENABLED and allow_live:
            summary_targets.append((index, translate_content_simple_async(metadata.get("pre_summary", ""), language)))

    # 인덱싱 때 저장된 다국어 필드는 그대로 사용합니다. 실시간 번역은 카드마다
    # 추가 토큰을 쓰므로 무료 전용 모드에서는 명시적으로 켜지 않은 한 수행하지 않습니다.
    if not LIVE_TRANSLATION_ENABLED or not allow_live:
        return pages_metadata

    tasks: List[Any] = []
    if title_targets:
        tasks.append(translate_titles_batch_async([title for _, title in title_targets], language))
    if summary_targets:
        tasks.append(asyncio.gather(*[task for _, task in summary_targets]))

    if not tasks:
        return pages_metadata

    translated_groups = await asyncio.gather(*tasks)
    group_index = 0
    if title_targets:
        translated_titles = translated_groups[group_index]
        group_index += 1
        for (page_index, _), translated_title in zip(title_targets, translated_titles):
            page = pages_metadata[page_index]
            metadata = page.get("metadata", page)
            metadata["title"] = translated_title

    if summary_targets:
        translated_summaries = translated_groups[group_index]
        for (page_index, _), translated_summary in zip(summary_targets, translated_summaries):
            page = pages_metadata[page_index]
            metadata = page.get("metadata", page)
            metadata["pre_summary"] = translated_summary

    return pages_metadata

# ============================================
# [Phase 4] Async Functions
# ============================================
# [버그 수정] search_supabase_async와 get_gemini_embedding_async의
# 중복 정의를 제거하였습니다. (위 1652, 408라인의 정의를 사용합니다.)
# 중복 정의 시 Python은 마지막 정의로 덮어쓰는 문제가 있었습니다.

async def rerank_search_results_async(question, results):
    if not results:
        return []
    candidates = results[:5]
    text = "\n".join(f"[{i}] {d.get('metadata',{}).get('title','')}\n{str(d.get('metadata',{}).get('pre_summary',''))[:1800]}"
                     for i,d in enumerate(candidates))
    response = await generate_content_safe_async(get_llm_client(),
        f"질문: {question}\n관련성 높은 문서 번호만 JSON 배열로 반환. 후보:\n{text}", timeout=8, temperature=0.0)
    match = re.search(r"\[.*?\]", response.text, re.S)
    if not match:
        raise ValueError("Invalid ranking output")
    values = json.loads(match.group(0))
    if not isinstance(values, list) or any(type(i) is not int or i<0 or i>=len(candidates) for i in values):
        raise ValueError("Invalid ranking indices")
    indices = list(dict.fromkeys(values))
    return [candidates[i] for i in indices] + [d for i,d in enumerate(candidates) if i not in indices] + results[5:]

async def expand_search_query_async(question):
    clean = visible_question(question)
    prompt = f"한국어 복지 DB 검색 키워드를 최대 6개 쉼표로만 출력. 외국어를 한국어로 변환. 질문: {clean}"
    client = get_async_groq_client()
    if client:
        try:
            result = await client.chat.completions.create(
                model=GROQ_FAST_MODEL, messages=[{"role":"user","content":prompt}],
                temperature=0, max_completion_tokens=512, reasoning_effort="low", timeout=5)
            if result.choices[0].finish_reason != "length":
                text = result.choices[0].message.content or ""
                terms = [t.strip(" *\n") for t in re.split(r"[,\n]",text) if t.strip()]
                if terms:
                    return list(dict.fromkeys(t[:100] for t in terms))[:6]
        except Exception as error:
            logger.warning("키워드 확장 생략: %s", type(error).__name__)
    # 분석용 보조 단계 실패로 추가 AI 호출을 연쇄하지 않습니다.
    return clean.split()[:8]
