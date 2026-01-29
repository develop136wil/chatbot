# 빠른 Worker 테스트용 임시 파일
import sys
sys.path.append('D:\\coding\\chatbot')

try:
    from utils import search_supabase
    print("✅ search_supabase import 성공")
    
    # 간단 테스트
    result = search_supabase("의료비 지원", {"category": "의료/재활"}, ["의료", "지원"])
    print(f"✅ 검색 결과: {len(result)}개")
    
except Exception as e:
    print(f"❌ 오류: {e}")
    import traceback
    traceback.print_exc()