# PROJECT KNOWLEDGE BASE

**Generated:** 2026-01-26
**Verified against code:** 2026-11-11
**Framework:** FastAPI + Redis + Supabase + Gemini

## OVERVIEW
FastAPI 기반 다국어 복지정보 챗봇. `main.py`가 요청·캐시·의도 분석을 처리하고,
`worker.py`가 Supabase 검색·순위 조정·결과 조립을 담당한다. Vercel/강제 직접 실행 환경에서는
Redis 큐를 우회하여 async worker를 직접 실행한다. 일반 서버의 Redis 경로와 fallback도 유지한다.
Gemini/Groq 호출과 임베딩·번역·캐시 클라이언트는 `utils.py`에 모여 있다.

## STRUCTURE
```
.
├── main.py             # API Gateway, Rate Limiting, Redis/Sync Dispatch
├── worker.py           # Async Job Consumer, Search Logic, RAG Pipeline
├── utils.py            # LLM wrappers, DB clients, embedding, translation, response cache
├── run_indexer.py      # Notion -> Supabase indexing + translation backfill + summary
├── static/             # Frontend Assets (HTML/JS/CSS)
└── requirements.txt    # Dependencies
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| **API Endpoints** | `main.py` | `/chat`, `/get_result`, `/health`; `/feedback`는 410 반환 |
| **Search Logic** | `worker.py` -> `process_job_async` | Search -> Rerank -> Format |
| **LLM Calls** | `utils.py` -> `generate_content_safe`, `generate_content_safe_async` | 공통 설정·timeout·무료 한도·fallback 처리 |
| **DB Clients** | `utils.py` | Redis, Supabase, Notion, Gemini |
| **Prompt Eng** | `utils.py`, `worker.py` | Search logic in `worker`, Expansion in `utils` |
| **Indexing** | `run_indexer.py`, `.github/workflows/daily_indexing.yml` | 실제 `[Indexer Summary]`의 실패·보류까지 확인 |
| **Regression** | `tests/`, `.github/workflows/no-sql-tests.yml` | 오프라인·브라우저·격리 Redis/SQL 검사 구분 |

## KEY PATTERNS & CONVENTIONS
*   **Redis Fallback**: Vercel에서는 직접 async worker 경로를 사용한다. 직접 실행을 동기 SDK 호출과 혼동하지 않는다.
*   **LLM Safety**: Gemini 생성은 기존 `utils.generate_content_safe()`/`generate_content_safe_async()` 등 공통 래퍼를 사용한다. 번역도 `utils.py`의 기존 번역 래퍼·호출 예산을 유지한다.
*   **Free Tier**: 무료 한도 사용을 유지한다. `FREE_TIER_ONLY`에서는 첫 번째 Gemini 키만 사용하며 `rotate_api_key()`는 순환하지 않는다. 키를 바꿔 한도를 우회하거나 유료 모델로 자동 변경하지 않는다.
*   **Model Configuration**: 실제 모델·출력 상한·fallback 설정은 `utils.py`를 확인한다. 스킬 권고만으로 모델·임베딩·차원을 바꾸지 않는다.
*   **Multilingual**: KO/EN/VI/ZH/JA 지원. 서버 UI 문자열은 `utils.LOCALIZED_UI`, 프런트엔드 문자열은 `static/`에서 확인한다.
*   **Rate Limiting**: Custom implementation in `main.py` (`check_rate_limit`) using Redis + In-memory fallback.
*   **Language Rule**: All analysis results, explanations, and responses provided by the agent MUST be in **Korean** (한국어), regardless of the input language, unless explicitly requested otherwise.

## ANTI-PATTERNS (THIS PROJECT)
*   **Direct API Calls**: Do not bypass the existing sync/async generation, embedding or translation wrappers in `utils.py`.
*   **Circular Imports**: `worker.py` imports `utils`. `main.py` imports both. Be careful when importing `main` into `worker`.
*   **Hardcoded Secrets**: 설정은 환경변수/로컬 `.env`를 사용하고 값을 출력하지 않는다. `ADMIN_SECRET_KEY`에 기본 비밀값을 추가하지 않는다. 현재는 미설정 시 관리자 접근을 차단한다.
*   **Blocking Code**: async 요청 경로에 동기 네트워크 작업을 직접 추가하지 않는다. 기존 async 래퍼 또는 명시적 스레드 분리를 유지한다.
*   **Scope**: 점검 요청만으로 SQL·운영 데이터·키·예약·배포를 변경하거나 인덱싱/메일 발송을 실행하지 않는다. Chatbot 요청을 supabase-keeper 변경으로 확대하지 않는다.

## COMMANDS
```bash
# Start API
uvicorn main:app --reload --port 8080

# Start Worker
python worker.py

# Offline regression (prepared test environment; no production keys)
python -m unittest discover -s tests -p 'test_*.py'
node --test tests/frontend.test.cjs tests/analytics_dashboard.test.cjs
```

`python run_indexer.py`는 운영 데이터를 갱신하는 수동 인덱싱 명령이다.
테스트 명령이 아니며, 명시적으로 승인된 인덱싱 작업에만 사용한다.
루트의 오래된 `test_*.py` 대신 `tests/`의 격리된 회귀 검사를 사용한다.

## NOTES
*   **Schedules**: Vercel/강제 직접 실행 환경에서는 앱 내부 스케줄러를 시작하지 않는다. 일반 서버 스케줄러와 GitHub Actions 예약을 구분하고 중복 실행을 만들지 않는다.
*   **Daily Indexing**: `.github/workflows/daily_indexing.yml`에서 KST 04:00(UTC 19:00) 예약. Actions 성공만으로 완료 판정하지 않고 `[Indexer Summary]`의 번역 보류·실패·캐시 오류를 확인한다.
*   **Feedback**: 문의는 이메일로 안내한다. 이전 `/feedback` 엔드포인트는 410을 반환하며 Notion에 저장하지 않는다.
*   **Timezone**: 앱 내부 cron의 시간대는 `Asia/Seoul`; GitHub cron은 UTC 기준이다.
*   **Skills**: `skills/chatbot-ops-verification/`가 프로젝트 스킬 원본이다. 설치본과의 차이·인식 여부는 파일 존재만으로 추정하지 않는다.


## UI DESIGN CONTRACT
- UI/UX 변경 전 저장소 루트의 `DESIGN.md`를 읽고 기존 정체성과 사용자 선택을 보존한다.
- `docs/design-review-20260921.md`의 확인 범위와 미검증 항목을 구분한다.
- UI 변경 시 `tests/frontend.test.cjs`와 `tests/ui_design.browser.cjs`를 사용해 회귀를 확인한다.
- 외부 디자인 스킬의 일반 권고만으로 캐릭터·국기·폰트·글라스 효과를 교체하지 않는다.
