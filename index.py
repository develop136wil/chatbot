import os
import json
import time
import traceback
import logging
from typing import Dict, Any, List, Optional
from supabase import create_client
from notion_client import Client as NotionClient
from dotenv import load_dotenv
from utils import (
    get_llm_client, # [수정] Lazy Loader Import
    summarize_content_with_llm, 
    _get_title, 
    _get_number, 
    _get_rich_text,
    _get_url,
    get_gemini_embedding,
    _get_multi_select
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info("[Indexer] 설정 로드 중...")
load_dotenv()

# [수정] 전역 변수 초기화 (Lazy Loading)
NOTION_KEY = None
SUPABASE_URL = None
SUPABASE_KEY = None
notion = None
supabase = None

def init_clients():
    global NOTION_KEY, SUPABASE_URL, SUPABASE_KEY, notion, supabase
    
    NOTION_KEY = os.getenv("NOTION_API_KEY", os.getenv("NOTION_KEY"))
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")

    if not NOTION_KEY: 
        logger.critical("❌ NOTION_KEY 설정 필요")
        raise ValueError("NOTION_KEY 설정 필요")
    if not SUPABASE_URL or not SUPABASE_KEY: 
        logger.critical("❌ SUPABASE 설정 필요")
        raise ValueError("SUPABASE 설정 필요")

    logger.info("[Indexer] 클라이언트 초기화 중...")
    try:
        notion = NotionClient(auth=NOTION_KEY)
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        logger.critical(f"❌ 클라이언트 초기화 실패: {e}")
        raise e

    logger.info("[Indexer] 초기화 완료.")

DATABASE_IDS = {
    "의료/재활": "2738ade5021080b786b0d8b0c07c1ea2",
    "교육/보육": "2738ade5021080339203d7148d7d943b",
    "가족 지원": "2738ade502108041a4c7f5ec4c3b8413",
    "돌봄/양육": "2738ade5021080cf842df820fdbeb709",
    "생활 지원": "2738ade5021080579e5be527ff1e80b2"
}
NOTION_PROPERTY_NAMES = {
    "title": "사업명", "category": "분류", "sub_category": "대상 특성",
    "start_age": "시작 월령(개월)", "end_age": "종료 월령(개월)", "support_detail": "상세 지원 내용",
    "contact": "문의처", "url1": "관련 홈페이지 1", "url2": "관련 홈페이지 2",
    "url3": "관련 홈페이지 3", "extra_req": "추가 자격요건",
    "cost_info": "비용 부담", "notes": "주의사항"
}

STATE_FILE_PATH = "./chroma-data/indexing_state.json"

def load_state() -> Dict[str, str]:
    if os.path.exists(STATE_FILE_PATH):
        try:
            with open(STATE_FILE_PATH, "r", encoding="utf-8") as f: return json.load(f)
        except Exception as e:
            logger.warning(f"⚠️ 상태 파일 로드 실패: {e}")
    return {}

def save_state(state: Dict[str, str]):
    try:
        os.makedirs(os.path.dirname(STATE_FILE_PATH), exist_ok=True)
        with open(STATE_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"❌ 상태 파일 저장 실패: {e}")

def run_indexing():
    # [수정] 실행 시점에 초기화 수행
    init_clients()
    
    logger.info("\n🔥🔥🔥 [업데이트] 문서 임베딩(RETRIEVAL_DOCUMENT) 최적화 인덱싱 시작 🔥🔥🔥\n")
    
    client = get_llm_client()
    if not client:
        logger.critical("❌ FATAL: Gemini 모델 로드 실패. 인덱싱을 중단합니다.")
        return

    prev_state = load_state()  # 증분 업데이트 활성화
    # prev_state = {}          # 전체 재인덱싱 (필요시 사용) 
    current_state = {}
    total_processed = 0
    total_skipped = 0
    has_critical_error = False
    
    for category_name, db_id in DATABASE_IDS.items():
        logger.info(f"\n[Indexer] '{category_name}' DB 확인 중...")
        try:
            results = []
            
            # [수정 2] 안전한 페이지네이션(Pagination) 로직
            has_more = True
            next_cursor = None
            
            while has_more:
                query_params = {"database_id": db_id}
                if next_cursor: query_params["start_cursor"] = next_cursor
                
                try:
                    response = notion.databases.query(**query_params)
                    results.extend(response.get("results", []))
                    has_more = response.get("has_more")
                    next_cursor = response.get("next_cursor")
                    time.sleep(0.3) # API 속도 제한 준수
                except Exception as e:
                    logger.error(f"❌ Notion API 호출 실패: {e}")
                    has_more = False
            
            logger.info(f" - {len(results)}개 페이지 발견.")

            for page in results:
                page_id = page.get("id")
                last_edited = page.get("last_edited_time")
                if not page_id: continue
                
                current_state[page_id] = last_edited

                if page_id in prev_state and prev_state[page_id] == last_edited:
                    total_skipped += 1
                    continue

                logger.info(f"⚡️ 처리 시작 (ID: {page_id})")

                try:
                    supabase.table("site_pages").delete().eq("page_id", page_id).execute()
                except Exception as e:
                    logger.warning(f"⚠️ 기존 데이터 삭제 실패 (무시됨): {e}")

                # 데이터 추출
                try:
                    props = page.get("properties", {})
                    title = _get_title(props, NOTION_PROPERTY_NAMES["title"])
                    support_detail = _get_rich_text(props, NOTION_PROPERTY_NAMES["support_detail"])
                    extra_req = _get_rich_text(props, NOTION_PROPERTY_NAMES["extra_req"])
                    contact = _get_rich_text(props, NOTION_PROPERTY_NAMES["contact"])
                    
                    cost_info = _get_rich_text(props, NOTION_PROPERTY_NAMES["cost_info"]) if NOTION_PROPERTY_NAMES.get("cost_info") in props else ""
                    notes = _get_rich_text(props, NOTION_PROPERTY_NAMES["notes"]) if NOTION_PROPERTY_NAMES.get("notes") in props else ""
                    page_url = page.get("url", "")
                    
                    start_age = _get_number(props, NOTION_PROPERTY_NAMES["start_age"])
                    end_age = _get_number(props, NOTION_PROPERTY_NAMES["end_age"])
                    if end_age == -1: end_age = 99999
    
                    targets = _get_multi_select(props, NOTION_PROPERTY_NAMES["sub_category"])
                    targets_text = ", ".join(targets) if targets else ""
                    
                    age_text = ""
                    if start_age is not None and start_age != -1:
                        if end_age is not None and end_age != 99999: age_text = f"{int(start_age)}~{int(end_age)}개월"
                        else: age_text = f"{int(start_age)}개월 이상"
                    elif end_age is not None and end_age != 99999: age_text = f"~{int(end_age)}개월"
                    
                    final_target = f"{age_text} ({targets_text})" if targets_text else age_text
    
                    # [1] 요약용 텍스트
                    text_parts = [
                        f"사업명: {title}",
                        f"대상: {final_target}",
                        support_detail,
                        f"추가 자격요건: {extra_req}",
                        f"문의처: {contact}",
                        f"비용 부담: {cost_info}" if cost_info and cost_info != "—" else "",
                        f"주의사항: {notes}" if notes and notes != "—" else ""
                    ]
                    full_text_for_summary = "\n".join([p.strip() for p in text_parts if p and p.strip()])
    
                    # [2] 임베딩용 텍스트 (가중치 적용)
                    search_keywords = f"{title} {category_name} {targets_text}".replace(" ", ", ")
                    req_text = f"자격요건: {extra_req}" if extra_req and extra_req != "—" else ""
                    
                    weight_title = 3
                    weight_target = 2
                    weight_req = 1
                    weight_cost = 2
                    
                    title_repeats = [f"문서제목: {title}" for _ in range(weight_title)]
                    target_repeats = [f"대상특성: {targets_text}" for _ in range(weight_target)] if targets_text else []
                    req_repeats = [f"자격요건: {req_text}" for _ in range(weight_req)] if req_text else []
                    cost_repeats = [f"비용주의: {cost_info} {notes}" for _ in range(weight_cost)] if (cost_info and cost_info != "—") or (notes and notes != "—") else []
                    
                    embedding_parts = [
                        f"핵심키워드: {search_keywords}",
                        f"카테고리: {category_name}",
                        f"대상: {final_target}",
                        f"내용: {support_detail}",
                    ] + title_repeats + target_repeats + req_repeats + cost_repeats
                    
                    full_text_for_embedding = "\n".join([p.strip() for p in embedding_parts if p and p.strip()])
                except Exception as e:
                    logger.error(f"❌ 데이터 파싱 중 오류 (ID:{page_id}): {e}")
                    continue

                if total_processed == 0: 
                     logger.debug(f"🔍 [X-RAY] 가중치 적용된 검색 데이터 예시:\n{full_text_for_embedding[:300]}...")
                
                # 청크 처리 및 저장
                chunks = [full_text_for_summary] 
                records_to_insert = []
                
                for i, chunk_text in enumerate(chunks):
                    if len(chunk_text.strip()) < 10: continue
                    chunk_id = f"{page_id}_{i}"

                    logger.info(f"   ... 요약 및 임베딩 생성 중 ('{title}')")
                    
                    try:
                        # 1. 요약
                        pre_summary = summarize_content_with_llm(chunk_text, title, [])

                        # 2. 임베딩
                        embedding = get_gemini_embedding(
                            full_text_for_embedding, 
                            task_type="RETRIEVAL_DOCUMENT"
                        )

                        if not embedding:
                            logger.warning(f"❌ 임베딩 생성 실패! 건너뜀.")
                            continue

                        metadata = {
                            "page_id": page_id,
                            "category": category_name,
                            "sub_category_list": targets,
                            "start_age": start_age,
                            "end_age": end_age,
                            "title": title,
                            "page_url": page_url,
                            "pre_summary": pre_summary
                        }

                        records_to_insert.append({
                            "id": chunk_id,
                            "page_id": page_id,
                            "content": full_text_for_summary,
                            "metadata": metadata,
                            "embedding": embedding
                        })
                    except Exception as e:
                        logger.error(f"❌ LLM/임베딩 처리 중 오류: {e}")
                        continue

                if records_to_insert:
                    try:
                        supabase.table("site_pages").upsert(records_to_insert).execute()
                        total_processed += 1
                    except Exception as e:
                        logger.error(f"❌ Supabase 저장 실패: {e}")

        except Exception as e:
            logger.error(f"❌ 카테고리 '{category_name}' 처리 중 치명적 오류: {e}")
            traceback.print_exc()
            has_critical_error = True

    # 삭제 처리 로직
    if has_critical_error:
        logger.warning("\n[Indexer] ⚠️ 오류 발생으로 삭제 단계 건너뜀.")
    else:
        deleted_ids = list(set(prev_state.keys()) - set(current_state.keys()))
        if deleted_ids:
            logger.info(f"\n[Indexer] 🗑️ 삭제된 페이지 {len(deleted_ids)}건 정리 중...")
            for del_id in deleted_ids:
                try:
                    supabase.table("site_pages").delete().eq("page_id", del_id).execute()
                except Exception as e:
                    logger.warning(f"⚠️ 삭제 실패: {e}")
        
        save_state(current_state)
        logger.info(f"\n[Indexer] ✨ 완료. (업데이트: {total_processed}, 건너뜀: {total_skipped})")

if __name__ == "__main__":
    run_indexing()