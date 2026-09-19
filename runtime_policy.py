"""외부 연결이 없는 요청 검증 및 검색 조건 정책."""
import re
from typing import Any

CATEGORIES = ('의료/재활', '교육/보육', '가족 지원', '돌봄/양육', '생활 지원')
CATEGORY_ALIASES = {
    'health': '의료/재활', 'medical': '의료/재활', '의료재활': '의료/재활',
    'education': '교육/보육', '교육보육': '교육/보육',
    'family': '가족 지원', '가족지원': '가족 지원',
    'care': '돌봄/양육', 'childcare': '돌봄/양육', '돌봄양육': '돌봄/양육',
    'living': '생활 지원', '생활지원': '생활 지원',
}
INTENTS = ('show_more', 'safety_block', 'exit', 'reset', 'out_of_scope', 'small_talk', 'clarify_category')
INTENT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['intent', 'category', 'sub_category', 'age', 'keywords', 'search_query'],
    'properties': {
        'intent': {'type': ['string', 'null'], 'enum': [None, *INTENTS]},
        'category': {'type': ['string', 'null'], 'enum': [None, *CATEGORIES]},
        'sub_category': {'type': ['string', 'null']},
        'age': {'type': ['integer', 'null']},
        'keywords': {'type': 'array', 'items': {'type': 'string'}},
        'search_query': {'type': 'string'},
    },
}

class SearchUnavailable(RuntimeError):
    """검색 장애. 실제 검색 결과 0건과 구분합니다."""

class SearchResults(list):
    def __init__(self, rows=(), *, scopes=('__all__',), cacheable=True):
        super().__init__(rows)
        self.scopes = list(scopes)
        self.cacheable = cacheable

def visible_question(question):
    return re.sub(r'\s*\(System[\s\S]*?\)', '', question, flags=re.I).strip()

def normalize_intent(data: Any, question: str) -> dict:
    if not isinstance(data, dict):
        raise ValueError('intent must be an object')
    result = {'intent': None, 'category': None, 'sub_category': None, 'age': None,
              'keywords': [], 'search_query': visible_question(question)}
    for field in ('intent', 'category', 'sub_category'):
        value = data.get(field)
        if isinstance(value, str) and value.strip().lower() not in ('', 'null', 'none'):
            result[field] = value.strip()[:100]
    result['category'] = CATEGORY_ALIASES.get(result['category'], result['category'])
    if result['category'] not in CATEGORIES:
        result['category'] = None
    if result['intent'] not in INTENTS:
        result['intent'] = None
    age = data.get('age')
    if isinstance(age, str) and age.isdigit():
        age = int(age)
    if type(age) is int and 0 <= age <= 1200:
        result['age'] = age
    keywords = data.get('keywords')
    if isinstance(keywords, list):
        result['keywords'] = list(dict.fromkeys(k.strip()[:100] for k in keywords if isinstance(k, str) and k.strip()))[:8]
    query = data.get('search_query')
    if isinstance(query, str) and query.strip():
        result['search_query'] = visible_question(query)[:2000]
    return result

def fallback_intent(question):
    clean = visible_question(question)
    # 불명확한 자연어는 임의 자격 조건으로 바꾸지 않습니다.
    months = re.search(r'(\d{1,3})\s*(?:개월|months?\b|tháng|个月)', clean, re.I)
    years = re.search(r'(\d{1,2})\s*(?:세|years?\b|tuổi|岁)', clean, re.I)
    age = int(months.group(1)) if months else int(years.group(1))*12 if years else None
    intent = 'reset' if clean.lower().replace(' ', '') in {
        '초기화', '처음부터', 'reset', 'startover', 'đặtlại', '重置', '重新开始'} else None
    return normalize_intent({'intent': intent, 'age': age, 'keywords': re.findall(r'\w{2,}', clean)[:8]}, clean)

def apply_search_filters(rows, info):
    """월령 범위를 벗어난 결과는 제외. 대상특성은 명시된 메타데이터만 검사."""
    result = []
    age = info.get('age')
    trait = info.get('sub_category')
    for row in rows:
        meta = row.get('metadata') or {}
        if type(age) is int:
            try:
                lower, upper = meta.get('start_age'), meta.get('end_age')
                if lower is not None and float(lower) >= 0 and age < float(lower):
                    continue
                if upper is not None and float(upper) >= 0 and age > float(upper):
                    continue
            except (ValueError, TypeError):
                # 판독 불가능한 연령 조건을 적합하다고 확정하지 않습니다.
                continue
        # 대상 특성은 자유 서술일 수 있어 임의 탈락 대신 정확 일치를 우선합니다.
        result.append(row)
    if trait:
        result.sort(key=lambda r: trait not in ((r.get('metadata') or {}).get('sub_category_list') or []))
    return result
