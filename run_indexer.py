import os
import json
import time
import traceback
import sys
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from typing import Dict, Any, List, Optional
from supabase import create_client
from notion_client import Client as NotionClient
from dotenv import load_dotenv
from utils import (
    get_llm_client, # [수정] Lazy Loader Import
    translate_content_simple, 
    _get_title, 
    _get_number, 
    _get_rich_text,
    _get_url,
    get_gemini_embedding,
    _get_multi_select,
    translate_content_multilingual_sync, # [신규]
    DATABASE_IDS,
    require_runtime_schema,
    reserve_ai_budget_sync,
    AI_DAILY_GLOBAL_LIMIT,
    purge_expired_response_cache,
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 외부 API가 무한정 대기하지 않도록 인덱서 실행 시간을 제한합니다.
NOTION_REQUEST_TIMEOUT_SECONDS = 30

logger.info("[Indexer] 설정 로드 중...")
load_dotenv()

# [수정] 전역 변수 초기화 (Lazy Loading)
NOTION_KEY = None
SUPABASE_URL = None
SUPABASE_KEY = None
notion = None
supabase = None


def has_complete_multilingual_metadata(metadata: Dict[str, Any]) -> bool:
    """영어·중국어·베트남어 제목과 요약이 모두 있을 때만 번역 완료로 봅니다."""
    return all(
        isinstance(metadata.get(field), str) and metadata[field].strip()
        for language in ("en", "zh", "vi")
        for field in (f"title_{language}", f"pre_summary_{language}")
    )

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

NOTION_PROPERTY_NAMES = {
    "title": "사업명", "support_detail": "상세 지원 내용", "extra_req": "추가 자격요건",
    "contact": "문의처", "start_age": "시작 월령(개월)", "end_age": "종료 월령(개월)",
    "sub_category": "대상 특성",
    "cost_info": "비용 부담", "notes": "주의사항"
}

def send_email_alert(subject: str, body: str):
    """
    [신규] 인덱싱 실패 시 이메일 알림 발송 (Gmail SMTP)
    """
    smtp_user = os.getenv("SMTP_USER")       # 보내는 사람 이메일 (예: chanyoung@develop136.com)
    smtp_password = os.getenv("SMTP_PASSWORD") # 앱 비밀번호 (Google App Password)
    recipient = os.getenv("ALERT_EMAIL_RECIPIENT", smtp_user) # 받는 사람 (기본값: 보내는사람 본인)
    
    if not smtp_user or not smtp_password:
        logger.warning("📧 [Email] SMTP 설정이 없어 알림을 건너뜠습니다. (SMTP_USER, SMTP_PASSWORD 확인 필요)")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = recipient
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Gmail SMTP 서버 (보안 연결)
        # 587: TLS (starttls 필요), 465: SSL
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
            
        logger.info(f"📧 [Email] 알림 발송 완료: {recipient}")
        
    except Exception as e:
        logger.error(f"❌ [Email] 알림 발송 실패: {e}")

class IndexingIncomplete(RuntimeError):
    def __init__(self, summary):
        self.summary = summary
        super().__init__("Indexing incomplete: "+json.dumps(summary,ensure_ascii=False))

def load_state_from_db():
    state = {}
    offset = 0
    while True:
        # 조회 실패를 초기 DB로 오해하여 전체 재색인하지 않습니다.
        response = supabase.table("site_pages").select("page_id,metadata").order("page_id").range(offset,offset+499).execute()
        rows = response.data or []
        for row in rows:
            meta = row.get("metadata") or {}
            state[row["page_id"]] = {
                "last_edited_time":meta.get("last_edited_time"), "category":meta.get("category"),
                "translations_complete":has_complete_multilingual_metadata(meta), "metadata":meta,
            }
        if len(rows)<500:
            break
        offset += len(rows)
    logger.info("기존 인덱싱 상태 로드: %s건",len(state))
    return state

def run_indexing():
    # [수정] 실행 시점에 초기화 수행
    init_clients()
    
    logger.info("\n🔥🔥🔥 [업데이트] 문서 임베딩(RETRIEVAL_DOCUMENT) 최적화 인덱싱 시작 🔥🔥🔥\n")
    
    # 문서 쓰기와 무효화가 원자적인 스키마인지 먼저 확인합니다.
    require_runtime_schema(supabase)

    # [수정] DB 기반 상태 로드 (GitHub Actions 등 비상태 환경 대응)
    prev_state = load_state_from_db()
    
    current_state = {}
    total_processed = 0
    total_skipped = 0
    translation_pending_pages = []
    has_critical_error = False
    failed_pages = set()
    deferred_pages = set()
    total_found = 0
    
    for category_name, db_id in DATABASE_IDS.items():
        logger.info(f"\n[Indexer] '{category_name}' DB 확인 중...")
        try:
            results = []
            
            # [수정 2] 안전한 페이지네이션(Pagination) 로직
            has_more = True
            next_cursor = None
            fetch_failed = False
            seen_cursors = set()
            
            while has_more:
                query_params = {"database_id": db_id}
                if next_cursor: query_params["start_cursor"] = next_cursor
                
                try:
                    # [Fix] notion-client SDK 호환성 문제 -> 직접 HTTP 요청으로 대체
                    headers = {
                        "Authorization": f"Bearer {NOTION_KEY}",
                        "Notion-Version": "2022-06-28", # Stable Version
                        "Content-Type": "application/json"
                    }
                    url = f"https://api.notion.com/v1/databases/{db_id}/query"
                    payload = {}
                    if next_cursor: payload["start_cursor"] = next_cursor
                    
                    resp = requests.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=NOTION_REQUEST_TIMEOUT_SECONDS,
                    )
                    resp.raise_for_status()
                    response = resp.json()
                    
                    if not isinstance(response.get("results"), list) or type(response.get("has_more")) is not bool:
                        raise RuntimeError("Invalid Notion pagination response")
                    results.extend(response["results"])
                    has_more = response.get("has_more")
                    next_cursor = response.get("next_cursor")
                    if has_more:
                        if not next_cursor or next_cursor in seen_cursors:
                            raise RuntimeError("Notion pagination cursor missing/repeated")
                        seen_cursors.add(next_cursor)
                    time.sleep(0.3) 
                except Exception as e:
                    logger.error(f"❌ Notion API 호출 실패: {e}")
                    fetch_failed = True
                    has_more = False

            # 일부 페이지만 가져온 상태에서 삭제 정리를 진행하면 기존 문서가
            # 대량 삭제될 수 있으므로, 해당 카테고리 전체를 실패로 처리합니다.
            if fetch_failed:
                raise RuntimeError("Notion 페이지 조회가 완료되지 않았습니다.")
            
            logger.info(f" - {len(results)}개 페이지 발견.")

            total_found += len(results)
            for page in results:
                page_id = page.get("id")
                last_edited = page.get("last_edited_time")
                if not page_id:
                    has_critical_error = True
                    failed_pages.add("missing-page-id")
                    continue
                
                current_state[page_id] = last_edited

                # [비교] DB에 있는 시간과 Notion 시간이 같으면 건너뜀
                if (
                    page_id in prev_state
                    and prev_state[page_id].get("last_edited_time") == last_edited
                    and prev_state[page_id].get("translations_complete")
                    and prev_state[page_id].get("category") == category_name
                ):
                    total_skipped += 1
                    continue

                # 수정/번역 보완 문서만 공용 예산 1단위를 사용합니다.
                try:
                    allowed = reserve_ai_budget_sync("indexer", AI_DAILY_GLOBAL_LIMIT)
                except Exception:
                    allowed = False
                if not allowed:
                    deferred_pages.add(page_id)
                    continue
                translation_only = (
                    page_id in prev_state
                    and prev_state[page_id].get("last_edited_time") == last_edited
                    and prev_state[page_id].get("category") == category_name
                )
                logger.info(f"⚡️ 처리 시작 (ID: {page_id}, translation_only={translation_only})")

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
                    logger.error("데이터 파싱 실패: %s", type(e).__name__)
                    failed_pages.add(page_id)
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

                        # 1. 요약 (한국어) - [수정] utils Signature에 맞춤
                        try:
                            pre_summary = translate_content_simple(chunk_text, language="ko")
                        except TypeError:
                            # 만약 utils가 수정되지 않았을 경우를 대비한 안전장치
                            pre_summary = translate_content_simple(chunk_text)

                        # [신규] 다국어 번역 (Phase 3)
                        previous = prev_state.get(page_id, {}).get("metadata", {}) if translation_only else {}
                        languages = [lang for lang in ("en","zh","vi") if not all(
                            isinstance(previous.get(field),str) and previous[field].strip()
                            for field in (f"title_{lang}",f"pre_summary_{lang}"))]
                        transl_dict = translate_content_multilingual_sync(title, pre_summary, languages)
                        for lang in ("en","zh","vi"):
                            if lang not in languages:
                                transl_dict[lang] = {"title":previous[f"title_{lang}"],"content":previous[f"pre_summary_{lang}"]}
                        
                        # 번역 결과 추출 (실패 시 빈값)
                        en_data = transl_dict.get("en", {})
                        zh_data = transl_dict.get("zh", {})
                        vi_data = transl_dict.get("vi", {})
                        translations_complete = all(
                            isinstance(data.get(field), str) and data[field].strip()
                            for data in (en_data, zh_data, vi_data)
                            for field in ("title", "content")
                        )
                        if not translations_complete:
                            logger.warning(
                                "⚠️ 다국어 번역 미완료 (다음 실행에서 재시도): %s",
                                title,
                            )

                        # 2. 임베딩
                        embedding = None if translation_only else get_gemini_embedding(
                            full_text_for_embedding, task_type="RETRIEVAL_DOCUMENT")
                        if not translation_only and not embedding:
                            logger.warning(f"❌ 임베딩 생성 실패! 건너뜀.")
                            continue

                        metadata = {
                            "page_id": page_id,
                            "last_edited_time": last_edited, # [신규] 상태 관리를 위한 필드
                            "category": category_name,
                            "sub_category_list": targets,
                            "start_age": start_age,
                            "end_age": end_age,
                            "title": title,
                            "page_url": page_url,
                            "pre_summary": pre_summary,
                            # [신규] 다국어 필드 추가
                            "title_en": en_data.get("title", ""),
                            "pre_summary_en": en_data.get("content", ""),
                            "title_zh": zh_data.get("title", ""),
                            "pre_summary_zh": zh_data.get("content", ""),
                            "title_vi": vi_data.get("title", ""),
                            "pre_summary_vi": vi_data.get("content", ""),
                            "translations_complete": translations_complete,
                        }

                        records_to_insert.append({
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
                        if translation_only:
                            # 기존 임베딩은 변경하지 않습니다.
                            supabase.table("site_pages").update({"metadata":metadata}).eq("page_id",page_id).execute()
                        else:
                            supabase.table("site_pages").upsert(records_to_insert, on_conflict="page_id").execute()
                        total_processed += 1
                        # DB trigger가 old/new 카테고리와 전체 범위를 같은 트랜잭션에서 갱신.
                        if not metadata.get("translations_complete"):
                            translation_pending_pages.append(title)
                        
                        # [변경] DB 상태 관리는 upsert 시 즉시 반영되므로 별도 save_state 불필요
                        # 로깅만 수행
                        if total_processed % 10 == 0:
                            logger.info(f"💾 [Progress] {total_processed}건 처리 중...")
                            
                    except Exception as e:
                        logger.error(f"❌ Supabase 저장 실패: {e}")
                        # 저장 실패 시 삭제 정리까지 수행하면 별도 문서까지 잃을 수 있습니다.
                        has_critical_error = True
                        failed_pages.add(page_id)
                else:
                    failed_pages.add(page_id)

        except Exception as e:
            error_msg = f"❌ 카테고리 '{category_name}' 처리 중 치명적 오류: {e}\n{traceback.format_exc()}"
            logger.error(error_msg)
            has_critical_error = True
            send_email_alert(f"[Chatbot Indexer] 인덱싱 실패 알림 ({category_name})", error_msg)

    # 삭제 처리 로직
    deleted_count = 0
    deleted_success = 0
    # 원본 DB 설정 오류 등을 빈 DB로 오해해 전체 삭제하지 않습니다.
    if prev_state and not total_found:
        has_critical_error = True
        logger.error("원본 전체 0건: 전체 삭제 차단")
    if has_critical_error:
        logger.warning("\n[Indexer] ⚠️ 오류 발생으로 삭제 단계 건너뜀.")
    else:
        # [수정] DB 상태 기반 삭제 감지
        # prev_state(DB에 있던 것) - current_state(Notion에서 가져온 것) = 삭제된 것
        deleted_ids = list(set(prev_state.keys()) - set(current_state.keys()))
        deleted_count = len(deleted_ids)
        if deleted_ids:
            logger.info(f"\n[Indexer] 🗑️ 삭제된 페이지 {len(deleted_ids)}건 정리 중...")
            for del_id in deleted_ids:
                try:
                    supabase.table("site_pages").delete().eq("page_id", del_id).execute()
                    deleted_success += 1
                    # 삭제의 캐시 무효화도 DB trigger에서 수행합니다.
                except Exception as e:
                    logger.warning("삭제 실패: %s",type(e).__name__)
                    has_critical_error = True
        
        # save_state(current_state) # 불필요 (DB metadata에 저장됨)
        purge_expired_response_cache(supabase)
        # 개별 쓰기에 trigger가 적용되어 부분 성공도 이미 무효화되어 있습니다.
        # 성공 알림 (옵션: 너무 자주 오면 귀찮으므로 주석 처리하거나, 요약 리포트로 발송 가능)
        # send_email_alert("[Chatbot Indexer] 인덱싱 완료", f"총 {total_processed}건 업데이트됨.")
        if translation_pending_pages:
            logger.warning(
                "[Indexer] 다국어 번역 보류 %s건: 다음 실행에서 재시도합니다. (%s)",
                len(translation_pending_pages),
                ", ".join(translation_pending_pages[:5]),
            )


    summary = {
        "found":total_found, "updated":total_processed, "skipped":total_skipped,
        "failed":len(failed_pages), "deferred":len(deferred_pages),
        "translation_pending":len(translation_pending_pages),
        "delete_candidates":deleted_count, "deleted":deleted_success, "critical_error":has_critical_error,
    }
    logger.info("INDEXING_SUMMARY %s",json.dumps(summary,ensure_ascii=False))
    if has_critical_error or failed_pages or deferred_pages or translation_pending_pages:
        raise IndexingIncomplete(summary)
    logger.info("인덱싱 전체 완료: 발견 문서 모두 처리/검증됨")
    return summary

if __name__ == "__main__":
    run_indexing()
