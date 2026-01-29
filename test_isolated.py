# utils.py 의존 오류 임시 완화용 파일
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# UTF-8 설정
if hasattr(sys.stdout, 'reconfigure') and sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from utils import search_supabase
    print("SUCCESS: search_supabase import 성공")
    
    # 간단 테스트
    result = search_supabase("의료비 지원", {"category": "의료/재활"}, ["의료", "지원"])
    print(f"SUCCESS: 검색 결과 {len(result)}개")
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()