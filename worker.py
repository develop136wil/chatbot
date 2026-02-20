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
        get_llm_client,
        generate_content_safe,
        translate_content_simple_async, # [Async]
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
    translate_content_simple_async = None

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
NOTION_LOG_DB_ID = "2bf8ade502108000b6d6f4ad4d4d52b2"

# Redis 연결 설정
REDIS_HOST = os.getenv("REDIS_HOST", "localhost").strip()
REDIS_PORT = 6379 

logger.info("[Worker] 클라이언트 초기화 중...")

# [기존 유지] 고정 멘트 다국어 사전
UI_TRANSLATIONS = {
    "ko": {
        "header_found": "🔎 <b>정보를 찾았습니다!</b>",
        "footer_more": "<p>🔍 <b>아직 결과가 더 남아있습니다.</b> '더 보여줘' 또는 '다음'을 입력해 보세요.</p>",
        "cats": {} 
    },
    "en": {
        "header_found": "🔎 <b>Here is the information I found!</b>",
        "footer_more": "<p>🔍 <b>There are more results.</b> Try typing 'Show more' or 'Next'.</p>",
        "cats": {
            "의료/재활": "Medical/Rehab", "교육/보육": "Edu/Care", "가족 지원": "Family Support",
            "돌봄/양육": "Childcare", "생활 지원": "Living Support", "기타": "Others"
        }
    },
    "vi": {
        "header_found": "🔎 <b>Tôi đã tìm thấy thông tin!</b>",
        "footer_more": "<p>🔍 <b>Vẫn còn kết quả.</b> Hãy thử nhập 'Xem thêm' hoặc 'Tiếp theo'.</p>",
        "cats": {
            "의료/재활": "Y tế/PHCN", "교육/보육": "Giáo dục/Trông trẻ", "가족 지원": "Hỗ trợ gia đình",
            "돌봄/양육": "Chăm sóc", "생활 지원": "Hỗ trợ đời sống", "기타": "Khác"
        }
    },
    "zh": {
        "header_found": "🔎 <b>为您找到以下信息！</b>",
        "footer_more": "<p>🔍 <b>还有更多结果。</b> 请输入“更多”或“下一个”。</p>",
        "cats": {
            "의료/재활": "医疗/康复", "교육/보육": "教育/保育", "가족 지원": "家庭支持",
            "돌봄/양육": "照护/养育", "생활 지원": "生活支持", "기타": "其他"
        }
    }
}

# [★신규] 제목 일괄 번역 함수 (Async Version)
async def translate_titles_batch_async(titles: List[str], target_lang_code: str) -> List[str]:
    """ [Async] 제목 일괄 번역 """
    client = get_llm_client()
    if not titles or not client: return titles
    
    lang_map = {"en": "English", "vi": "Vietnamese", "zh": "Chinese (Simplified)"}
    target_lang = lang_map.get(target_lang_code, "Korean")
    
    prompt = f"""
    Translate the following list of welfare service titles into {target_lang}.
    [Input Titles]
    {json.dumps(titles, ensure_ascii=False)}
    [Rules]
    1. Return ONLY a valid JSON list of strings.
    2. Maintain the exact same order.
    3. No explanations.
    """
    
    try:
        from google.genai import types
        response = await client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0)
        )
        
        response_text = response.text.strip() if hasattr(response, 'text') else str(response).strip()
        
        # Markdown 제거
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            if response_text.endswith("```"):
                response_text = response_text.rsplit("\n", 1)[0]
        
        translated_list = json.loads(response_text)
        if isinstance(translated_list, list) and len(translated_list) == len(titles):
            return translated_list
        return titles
    except Exception as e:
        logger.warning(f"⚠️ [Async] 제목 일괄 번역 실패: {e}")
        return titles

# --- 메인 처리 함수 (Async) ---
async def process_job_async(job_data: Dict[str, Any]) -> Tuple[str, List[str], int]:
    start_time = time.time()
    question = job_data.get("question", "")
    ai_category = job_data.get("ai_category")
    
    logger.info(f"▶️ [Async] 작업 시작: {question}")

    try:
        # [Step 1] 키워드 추출 (Async)
        try:
            target_keywords = await expand_search_query_async(question)
        except Exception as e:
            logger.error(f"❌ 키워드 확장 실패: {e}")
            target_keywords = []

        # 원본 보완
        for word in question.split():
            if len(word) > 1 and word not in target_keywords:
                target_keywords.append(word)
        logger.info(f"🗝️ [검색 키워드] {target_keywords}")

        # [Step 2] 검색 (Async)
        extracted_info_mock = {"category": ai_category}
        try:
            raw_results = await search_supabase_async(question, extracted_info_mock, keywords=target_keywords)
        except Exception as e:
            logger.error(f"❌ Supabase 검색 실패: {e}")
            return f"시스템 오류가 발생했습니다. 😥", [], 0

        if not raw_results: 
            return "관련 정보를 찾지 못했습니다. 😥", [], 0

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
        
        # 언어 감지
        target_lang_code = "ko" 
        if "strictly in English" in question: target_lang_code = "en"
        elif "strictly in Vietnamese" in question: target_lang_code = "vi"
        elif "strictly in Chinese" in question: target_lang_code = "zh"
        
        ui_text = UI_TRANSLATIONS.get(target_lang_code, UI_TRANSLATIONS["ko"])

        # ==================================================================
        # [Async] 다국어 번역 (Parallel Execution)
        # ==================================================================
        if target_lang_code != "ko":
            logger.info(f"🌍 [Worker] 언어 감지: {target_lang_code} -> 병렬 번역 시작")
            
            # 1. 제목 번역 준비
            docs_needing_title = []
            for i, doc in enumerate(display_results):
                meta = doc.get("metadata", {})
                pre_title = meta.get(f"title_{target_lang_code}")
                if pre_title:
                    doc["metadata"]["title"] = pre_title
                else:
                    docs_needing_title.append((i, meta.get("title", "")))

            # 2. 본문/카테고리 번역 준비 (Coroutine List)
            summary_tasks = []
            for i, doc in enumerate(display_results):
                meta = doc.get("metadata", {})
                
                # 카테고리 번역 (즉시 처리)
                original_category = meta.get("category", "기타")
                doc["metadata"]["category"] = ui_text["cats"].get(original_category, original_category)
                
                # 본문 번역
                pre_summary_val = meta.get(f"pre_summary_{target_lang_code}")
                if pre_summary_val:
                    doc["metadata"]["pre_summary"] = pre_summary_val
                    summary_tasks.append(None) # Task Placeholder (이미 완료)
                else:
                    # Async Task 생성
                    original_summary = meta.get("pre_summary", "")
                    summary_tasks.append(
                        translate_content_simple_async(original_summary, target_lang_code)
                    )

            # 3. 비동기 병렬 실행 (제목 Batch + 본문 개별)
            tasks_to_await = []
            
            # (A) 제목 Batch
            if docs_needing_title:
                titles_to_translate = [t[1] for t in docs_needing_title]
                tasks_to_await.append(translate_titles_batch_async(titles_to_translate, target_lang_code))
            else:
                tasks_to_await.append(None) # Placeholder

            # (B) 본문 Tasks (None 제외)
            real_summary_tasks = [t for t in summary_tasks if t is not None]
            if real_summary_tasks:
                tasks_to_await.append(asyncio.gather(*real_summary_tasks))
            else:
                tasks_to_await.append(None) 
            
            # ★ Await All ★
            results_gathered = await asyncio.gather(*[t for t in tasks_to_await if t is not None])
            
            # 결과 적용
            result_idx = 0
            
            # (A) 제목 적용
            if docs_needing_title:
                translated_titles = results_gathered[result_idx]
                result_idx += 1
                for (idx, _), new_title in zip(docs_needing_title, translated_titles):
                    display_results[idx]["metadata"]["title"] = new_title
            
            # (B) 본문 적용
            if real_summary_tasks:
                translated_summaries = results_gathered[result_idx]
                # 원래 인덱스와 매칭
                summary_result_ptr = 0
                for i, task in enumerate(summary_tasks):
                    if task is not None:
                        display_results[i]["metadata"]["pre_summary"] = translated_summaries[summary_result_ptr]
                        summary_result_ptr += 1

        # ==================================================================
        
        all_page_ids = [r.get("metadata", {}).get("page_id") for r in reranked_results]
        final_display_metadata = [res.get("metadata", {}) for res in display_results]
        
        try:
            body = format_search_results(final_display_metadata)
        except Exception as e:
            logger.error(f"❌ 결과 포맷팅 실패: {e}")
            body = "결과를 표시하는 중 오류가 발생했습니다."
        
        header = ui_text["header_found"]
        final_answer = f"{header}<hr>{body}"

        if len(reranked_results) > display_count:
            final_answer += f"<hr>{ui_text['footer_more']}"

        elapsed = time.time() - start_time
        logger.info(f"✅ [Async] 답변 조립 완료 (소요시간: {elapsed:.2f}초)")
        
        # 로그 저장 (Notion은 Sync이므로 run_in_executor 사용 권장하나, 여기선 생략하고 Fire & Forget 흉내)
        # 실제로는 별도 Task로 띄울 수 있음
        if notion and NOTION_LOG_DB_ID:
            asyncio.create_task(save_notion_log_async(question, ai_category, target_keywords))
                
        return final_answer, all_page_ids, len(all_page_ids)

    except Exception as e:
        logger.error(f"🔥 작업 처리 중 치명적 오류: {e}")
        traceback.print_exc()
        return "죄송합니다. 오류가 발생하여 답변을 드릴 수 없습니다. 😥", [], 0

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
async def handle_job(redis_client, queue_item):
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
        await redis_client.hset(JOB_RESULTS_KEY, job_id, json.dumps(final_result).encode('utf-8'))
        # await redis_client.expire(f"job:{job_id}", 3600) # Optional
        
        logger.info(f"💾 완료: {job_data.get('question')}")
        
    except Exception as e:
        logger.error(f"Handler Error: {e}")

# --- 메인 루프 (Async) ---
async def start_worker_async():
    logger.info(f"🚀 Worker (Async) 가동! (PID: {os.getpid()})")
    
    # Redis Async Connection
    r = redis.from_url(f"redis://{REDIS_HOST}:{REDIS_PORT}", decode_responses=False)
    
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
        try:
            # Async BLPOP
            result = await r.blpop(JOB_QUEUE_KEY, timeout=1)
            if result:
                # Fire and Forget (Concurrency!)
                # 각 작업은 독립된 Task로 실행되어, 다음 BLPOP을 즉시 수행함
                asyncio.create_task(handle_job(r, result))
                
        except Exception as e:
            logger.error(f"🔥 Worker Loop Error: {e}")
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(start_worker_async())