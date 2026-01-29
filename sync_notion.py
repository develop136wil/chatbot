import os
import time
import hashlib
import json
from datetime import datetime
from dotenv import load_dotenv

# 우리가 만든 utils.py에서 강력한 기능들을 가져옵니다.
from utils import (
    notion, supabase, get_gemini_embedding, 
    DATABASE_IDS, NOTION_PROPERTY_NAMES,
    _get_rich_text, _get_title, _get_select, _get_multi_select, _get_url, _get_number
)

load_dotenv()

# --- 설정 ---
# 노션 데이터베이스 ID (utils.py에 있는 것 사용)
TARGET_DB_IDS = DATABASE_IDS.values()

def generate_content_hash(content: str) -> str:
    """내용이 변했는지 확인하기 위한 지문(Hash) 생성"""
    return hashlib.md5(content.encode('utf-8')).hexdigest()

def fetch_and_sync():
    print(f"🔄 [Sync] 동기화 작업 시작... ({datetime.now()})")
    
    total_synced = 0
    total_skipped = 0
    
    for category_name, db_id in DATABASE_IDS.items():
        print(f"\n📂 카테고리 스캔 중: {category_name}...")
        
        try:
            # 1. Notion에서 데이터 가져오기 (쿼리)
            response = notion.databases.query(database_id=db_id)
            pages = response.get("results", [])
            
            # 페이지가 많을 경우 페이지네이션 처리 (필요시 추가)
            while response.get("has_more"):
                response = notion.databases.query(
                    database_id=db_id, 
                    start_cursor=response["next_cursor"]
                )
                pages.extend(response.get("results", []))

            print(f"   - 발견된 문서: {len(pages)}개")

            for page in pages:
                page_id = page["id"]
                props = page["properties"]
                
                # --- 데이터 추출 (utils.py 헬퍼 함수 활용) ---
                title = _get_title(props, "사업명")
                if not title: continue # 제목 없으면 스킵

                sub_category = _get_multi_select(props, "대상 특성") # 리스트
                support_detail = _get_rich_text(props, "상세 지원 내용")
                
                # 메타데이터 구성
                metadata = {
                    "title": title,
                    "category": category_name, # Notion 카테고리 대신 DB 매핑 이름 사용
                    "sub_category": ", ".join(sub_category) if sub_category else "",
                    "start_age": _get_number(props, "시작 월령(개월)"),
                    "end_age": _get_number(props, "종료 월령(개월)"),
                    "support_detail": support_detail,
                    "contact": _get_rich_text(props, "문의처"),
                    "page_url": page["url"],
                    "pre_summary": support_detail[:1000] # 요약용 앞부분
                }

                # --- 임베딩을 위한 텍스트 조립 ---
                # 검색 AI가 읽을 텍스트 (제목 + 카테고리 + 내용 + 대상)
                text_to_embed = f"""
                사업명: {title}
                분류: {category_name}
                대상: {metadata['sub_category']} ({metadata['start_age']}~{metadata['end_age']}개월)
                내용: {support_detail}
                """
                
                # 내용의 지문(Hash) 생성
                current_hash = generate_content_hash(text_to_embed)

                # --- 2. Supabase 확인 (이미 있는지, 변했는지) ---
                existing = supabase.table("site_pages").select("content_hash").eq("page_id", page_id).execute()
                
                if existing.data:
                    db_hash = existing.data[0].get("content_hash")
                    if db_hash == current_hash:
                        print(f"   PASS (변경 없음): {title}")
                        total_skipped += 1
                        continue # 내용이 같으면 건너뜀 (API 절약)

                # --- 3. 변경되었거나 신규라면 -> 임베딩 생성 및 저장 ---
                print(f"   ✨ UPDATE (임베딩 생성): {title}")
                
                embedding = get_gemini_embedding(text_to_embed)
                
                if embedding:
                    data = {
                        "page_id": page_id,
                        "content": text_to_embed,
                        "metadata": metadata,
                        "embedding": embedding, # 벡터 데이터
                        "content_hash": current_hash, # 다음 비교를 위해 저장
                        "url": page["url"]
                    }
                    
                    # Upsert (있으면 수정, 없으면 추가)
                    supabase.table("site_pages").upsert(data).execute()
                    total_synced += 1
                else:
                    print(f"   ⚠️ 임베딩 실패로 스킵: {title}")

        except Exception as e:
            print(f"   ❌ 오류 발생 ({category_name}): {e}")

    print(f"\n✅ 동기화 완료! (업데이트: {total_synced}건, 패스: {total_skipped}건)")

if __name__ == "__main__":
    fetch_and_sync()