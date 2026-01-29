import os
import json
import time
import traceback
import gc
import logging
from typing import List, Dict, Any, Tuple, Optional
from supabase import create_client
from dotenv import load_dotenv

# 기본 utils 임포트
try:
    from utils import (
        search_supabase,       
        expand_search_query,   
        rerank_search_results, 
        format_search_results, 
        get_llm_client,
        generate_content_safe,
        redis_client,
        supabase,
        notion
    )
    print("✅ utils 임포트 성공")
except ImportError as e:
    print(f"❌ utils 임포트 실패: {e}")
    # Vercel에서는 sys.exit() 대신 에러를 기록하고 계속 진행
    logger.error(f"Utils import failed: {e}")
    search_supabase = None
    expand_search_query = None
    rerank_search_results = None
    format_search_results = None
    get_llm_client = None
    generate_content_safe = None
    redis_client = None
    supabase = None
    notion = None

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

logger.info("[Worker] 클라이언트 초기화 중...")
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    logger.error(f"[Worker] Supabase 초기화 실패: {e}")
    supabase = None

logger.info("[Worker] 초기화 완료. 작업 대기 시작.")

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

# [★수정] 제목 일괄 번역 함수 (Batch Processing)
def translate_titles_batch(titles: List[str], target_lang_code: str) -> List[str]:
    """
    여러 개의 제목을 한 번에 번역하여 API 호출 횟수를 1/N로 줄입니다.
    """
    client = get_llm_client()
    if not titles or not client: return titles
    
    lang_map = {"en": "English", "vi": "Vietnamese", "zh": "Chinese (Simplified)"}
    target_lang = lang_map.get(target_lang_code, "Korean")
    
    # JSON 포맷을 강제하여 파싱하기 쉽게 만듦
    prompt = f"""
    Translate the following list of welfare service titles into {target_lang}.
    
    [Input Titles]
    {json.dumps(titles, ensure_ascii=False)}
    
    [Rules]
    1. Return ONLY a valid JSON list of strings.
    2. Maintain the exact same order.
    3. No explanations, no markdown code blocks. Just the raw JSON list.
    
    [Output Example]
    ["Translated Title 1", "Translated Title 2"]
    """
    
    try:
        # 타임아웃 40초 (내용이 좀 더 많으므로)
        response = generate_content_safe(client, prompt, timeout=40)
        
        # [수정] 응답 객체 처리 방식 통일
        if hasattr(response, 'text'):
            response_text = response.text.strip()
        else:
            response_text = str(response).strip()
        
        # Markdown code block 제거 (`json ... `)
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            if response_text.endswith("```"):
                response_text = response_text.rsplit("\n", 1)[0]
        
        translated_list = json.loads(response_text)
        
        if isinstance(translated_list, list) and len(translated_list) == len(titles):
            return translated_list
        else:
            logger.warning("⚠️ [Batch Translation] 개수 불일치 또는 포맷 오류. 원본 제목을 사용합니다.")
            return titles
            
    except Exception as e:
        logger.warning(f"⚠️ 제목 일괄 번역 실패: {e}")
        return titles

# --- 메인 처리 함수 ---
def process_job(job_data: Dict[str, Any]) -> Tuple[str, List[str], int]:
    start_time = time.time()
    question = job_data.get("question", "")
    ai_category = job_data.get("ai_category")

    logger.info(f"▶️ 작업 시작: {question}")

    try:
        # [Step 1] 키워드 추출
        try:
            target_keywords = expand_search_query(question)
        except Exception as e:
            logger.error(f"❌ 키워드 확장 실패: {e}")
            target_keywords = []

        # 원본 질문의 단어도 키워드에 추가 (보완책)
        for word in question.split():
            if len(word) > 1 and word not in target_keywords:
                target_keywords.append(word)
        logger.info(f"🗝️ [검색 키워드] {target_keywords}")

        # [Step 2] 검색
        extracted_info_mock = {"category": ai_category}
        try:
            raw_results = search_supabase(question, extracted_info_mock, keywords=target_keywords)
        except Exception as e:
            logger.error(f"❌ Supabase 검색 실패: {e}")
            return "시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요. 😥", [], 0

        if not raw_results: 
            return "관련 정보를 찾지 못했습니다. 😥", [], 0

        # [Step 3] 중복 제거
        seen_ids = set()
        unique_results = []
        for doc in raw_results:
            meta = doc.get("metadata", {})
            pid = meta.get("page_id") or meta.get("page_url") or meta.get("title")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                unique_results.append(doc)
        candidates = unique_results

        # [Step 4] AI 랭킹
        logger.info(f"🤖 Gemini에게 {len(candidates)}개 문서의 랭킹을 요청합니다.")
        try:
            reranked_results = rerank_search_results(question, candidates)
            if not reranked_results:
                logger.warning("⚠️ AI 랭킹 결과 없음 -> 검색 엔진(SQL) 순서 사용")
                reranked_results = candidates
        except Exception as e:
            logger.error(f"❌ AI 랭킹 중 오류: {e}")
            reranked_results = candidates

        # [Step 5] 최종 결과 조립
        display_count = min(len(reranked_results), 2)
        display_results = reranked_results[:display_count]
        
        # 언어 감지 로직
        target_lang_code = "ko" 
        if "strictly in English" in question: target_lang_code = "en"
        elif "strictly in Vietnamese" in question: target_lang_code = "vi"
        elif "strictly in Chinese" in question: target_lang_code = "zh"
        
        ui_text = UI_TRANSLATIONS.get(target_lang_code, UI_TRANSLATIONS["ko"])

        # ==================================================================
        # [다국어 번역 적용] 본문 + 카테고리 + ★제목(Batch)★
        # ==================================================================
        if target_lang_code != "ko":
            logger.info(f"🌍 [Worker] 언어 감지: {target_lang_code} -> 내용/제목/UI 번역 시작")
            
            # 1. 제목 일괄 수집
            original_titles = [doc.get("metadata", {}).get("title", "") for doc in display_results]
            
            # 2. 제목 일괄 번역 실행 (1회 호출)
            translated_titles = translate_titles_batch(original_titles, target_lang_code)
            
            # 3. 결과 적용 및 나머지 번역
            for i, doc in enumerate(display_results):
                meta = doc.get("metadata", {})
                original_summary = meta.get("pre_summary", "")
                original_category = meta.get("category", "기타")
                original_title = meta.get("title", "")
                
                # 1. 카테고리 이름 번역 (사전 매핑)
                translated_cat = ui_text["cats"].get(original_category, original_category)
                doc["metadata"]["category"] = translated_cat

                # 2. [제목 번역 적용] Batch 결과 사용
                new_title = translated_titles[i] if i < len(translated_titles) else original_title
                doc["metadata"]["title"] = new_title

                # 3. 본문 요약 번역
                try:
                    translated_summary = summarize_content_with_llm(
                        content=original_summary,  
                        language="ko"
                    )
                    doc["metadata"]["pre_summary"] = translated_summary
                    logger.debug(f"   -> '{original_title}' => '{new_title}' (번역 완료)")
                except Exception as e:
                    logger.warning(f"   ⚠️ 본문 번역 실패: {e}")
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
        logger.info(f"✅ 답변 조립 완료 (소요시간: {elapsed:.2f}초)")
        
        # 로그 저장 (비동기적으로 실패해도 메인 로직 영향 없도록 함)
        if notion and NOTION_LOG_DB_ID:
            try:
                final_category = ai_category if ai_category else "미분류"
                notion.pages.create(
                    parent={"database_id": NOTION_LOG_DB_ID},
                    properties={
                        "질문": {"title": [{"text": {"content": question}}]},
                        "카테고리": {"select": {"name": final_category}},
                        "키워드": {"multi_select": [{"name": k} for k in target_keywords[:5]]}
                    }
                )
            except Exception as e:
                logger.warning(f"⚠️ Notion 로그 저장 실패: {e}")
                
        return final_answer, all_page_ids, len(all_page_ids)

    except Exception as e:
        logger.error(f"🔥 작업 처리 중 치명적 오류: {e}")
        traceback.print_exc()
        return "죄송합니다. 오류가 발생하여 답변을 드릴 수 없습니다. 😥", [], 0

# --- 메인 루프 ---
def start_worker():
    logger.info(f"🚀 Worker 가동! (PID: {os.getpid()})")
    
    # Redis 연결 재시도 로직
    while True:
        try:
            if redis_client.ping():
                break
        except Exception:
            logger.warning("⏳ Redis 연결 대기 중...")
            time.sleep(2)
            
    while True:
        try:
            # 타임아웃 1초로 설정하여 주기적으로 루프 탈출 (종료 시그널 처리 등 가능)
            result = redis_client.blpop(JOB_QUEUE_KEY, timeout=1)
            if result:
                _, job_json = result
                job_data = json.loads(job_json.decode('utf-8'))
                
                answer_text, all_ids, total_found = process_job(job_data)

                final_result = {
                    "status": "complete",
                    "answer": answer_text,
                    "last_result_ids": all_ids, 
                    "total_found": total_found 
                }
                
                # 결과 저장 시 만료 시간(TTL) 설정 권장 (예: 1시간)
                job_id = job_data.get("job_id")
                redis_client.hset(JOB_RESULTS_KEY, job_id, json.dumps(final_result).encode('utf-8'))
                # redis_client.expire(f"job:{job_id}", 3600) # (선택사항)
                
                logger.info(f"💾 완료: {job_data.get('question')}")

                del job_data, answer_text, final_result
                gc.collect()

        except Exception as e:
            logger.error(f"🔥 Worker Loop Error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    start_worker()