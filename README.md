# 도봉구 영유아 복지톡 👶

**도봉구 영유아 복지 정보를 쉽고 빠르게 찾아주는 AI 챗봇 서비스**

이 프로젝트는 Notion에 저장된 복지 정보를 **RAG (Retrieval-Augmented Generation)** 기술을 활용해 검색하고, **Google Gemini 2.5** 및 **Llama 3.3** 모델을 통해 사용자 친화적인 답변으로 제공하는 하이브리드 AI 챗봇입니다.

---

## 🌟 주요 기능

- **🤖 AI 기반 지능형 검색**: 단순 키워드 매칭을 넘어, 질문의 의도를 파악하고 Notion 데이터베이스에서 가장 적합한 복지 정보를 찾아냅니다.
- **🌍 다국어 지원**: 한국어뿐만 아니라 **영어(English), 베트남어(Tiếng Việt), 중국어(中文)** 질문을 자동으로 감지하고 해당 언어로 답변합니다.
- **📄 Notion 연동 (CMS)**: 복지 담당자가 Notion에 정보를 업데이트하면, 챗봇이 이를 자동으로 인덱싱하여 최신 정보를 반영합니다.
- **⚡ 하이브리드 아키텍처**:
    - **FastAPI (Async)**: 빠른 API 응답 처리.
    - **Redis Queue**: 트래픽이 몰릴 때 요청을 대기열에서 안정적으로 처리.
    - **Fallback Mode**: Redis 장애 시 또는 Vercel(Serverless) 환경에서는 즉시 동기 모드(Synchronous)로 전환되어 중단 없는 서비스 제공.
- **🛡️ 안정성 및 보안**:
    - **Rate Limiting**: 도배 방지 기능 내장.
    - **Key Rotation**: 여러 API 키를 순환 사용하여 초당 요청 제한(Rate Limit) 회피.
    - **Feedback System**: 사용자의 좋아요/싫어요 피드백을 Notion에 실시간 저장.

---

## 🛠️ 시스템 아키텍처

```mermaid
graph TD
    User[사용자] -->|질문| FastAPI[FastAPI (main.py)]
    FastAPI -->|의도 파악| Gemini[Google Gemini 2.5]
    FastAPI -->|도배 방지| Redis[(Redis)]
    
    subgraph "검색 파이프라인 (Worker)"
    FastAPI -- "Queue (Async)" --> Redis
    Redis -- "Job Consuming" --> Worker[Worker (worker.py)]
    Worker -->|Vector Search| Supabase[(Supabase PGVector)]
    Worker -->|Reranking| Gemini
    end
    
    subgraph "데이터 파이프라인 (Indexer)"
    Notion[Notion DB] -->|Sync| Indexer[Indexer (run_indexer.py)]
    Indexer -->|Embedding| Gemini
    Indexer -->|Upsert| Supabase
    end
    
    FastAPI -- "Fallback (Sync)" --> Worker
```

---

## 💻 기술 스택

| 구분 | 기술 | 설명 |
|------|------|------|
| **Backend** | ![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi) | 비동기 Python 웹 프레임워크 |
| **LLM** | ![Gemini](https://img.shields.io/badge/Google%20Gemini-8E75B2?style=flat&logo=google) | 메인 AI 모델 (Gemini 2.5 Flash) |
| **Backup LLM** | ![Groq](https://img.shields.io/badge/Groq-F55036?style=flat) | Gemini 장애 시 백업 모델 (Llama 3.3) |
| **Database** | ![Supabase](https://img.shields.io/badge/Supabase-3ECF8E?style=flat&logo=supabase) | pgvector를 활용한 벡터 데이터베이스 |
| **CMS** | ![Notion](https://img.shields.io/badge/Notion-000000?style=flat&logo=notion) | 데이터 관리 및 피드백/로그 저장 |
| **Queue/Cache** | ![Redis](https://img.shields.io/badge/Redis-DC382D?style=flat&logo=redis) | 작업 대기열 및 응답 캐싱 |
| **Deployment** | ![Vercel](https://img.shields.io/badge/Vercel-000000?style=flat&logo=vercel) | Serverless 배포 환경 |

---

## 📂 프로젝트 구조

```bash
chatbot/
├── main.py               # 🚀 API 진입점 (엔드포인트, 미들웨어, 스케줄러)
├── worker.py             # ⚙️ 백그라운드 워커 (검색, 랭킹, 답변 생성 핵심 로직)
├── utils.py              # 🔧 공통 유틸리티 (LLM 래퍼, DB 클라이언트, 임베딩, 키 관리)
├── run_indexer.py        # 🔄 데이터 인덱서 (Notion -> Supabase 동기화)
├── sync_notion.py        # 📋 (구버전) Notion 동기화 스크립트
├── requirements.txt      # 📦 Python 의존성 목록
├── vercel.json           # ☁️ Vercel 배포 설정
├── static/               # 🎨 프론트엔드 정적 파일 (HTML/CSS/JS)
└── .env.example          # 🔐 환경 변수 예시
```

---

## 🚀 시작 가이드

### 1. 사전 준비
- Python 3.9 이상
- Supabase 계정 및 프로젝트
- Notion API Key 및 데이터베이스 ID
- Google AI Studio (Gemini) API Key

### 2. 환경 변수 설정
`.env` 파일을 생성하고 다음 정보를 입력하세요 (참고: `.env.example`).

```ini
# Supabase
SUPABASE_URL="your-supabase-url"
SUPABASE_KEY="your-supabase-anon-key"

# AI Models
GEMINI_API_KEYS="key1,key2,key3"  # 쉼표로 구분하여 여러 개 입력 가능 (로테이션)
GROQ_API_KEY="your-groq-key"      # (선택) 백업용

# Notion
NOTION_API_KEY="your-notion-secret"

# Redis (선택 - 없으면 로컬 메모리/동기 모드 사용)
REDIS_HOST="localhost"

# Security
ADMIN_SECRET_KEY="admin-password"
SESSION_SECRET_KEY="complex-session-key"
```

### 3. 설치 및 실행

#### 의존성 설치
```bash
pip install -r requirements.txt
```

#### 로컬 서버 실행 (FastAPI)
```bash
# 개발 모드 (코드가 변경되면 자동 재시작)
uvicorn main:app --reload --port 8000
```
브라우저에서 `http://localhost:8000`으로 접속하여 테스트할 수 있습니다.

#### 워커 실행 (선택 - 로컬 Redis 사용 시)
비동기 큐 처리를 테스트하려면 Redis를 실행한 상태에서 별도 터미널에 워커를 띄웁니다.
```bash
python worker.py
```
*(참고: Vercel 배포 환경이나 Redis가 없는 경우 `main.py`가 자동으로 동기 모드로 작동하므로 워커 실행이 필수는 아닙니다.)*

---

## 🔄 데이터 인덱싱 (Notion → AI)

Notion에 새로운 복지 정책을 추가했나요? 챗봇이 알 수 있도록 인덱싱을 수행해야 합니다.

```bash
python run_indexer.py
```
> **팁**: 로컬 서버(`main.py`)가 실행 중이면 `APScheduler`에 의해 매일 00:00에 자동으로 실행됩니다.

---

## ☁️ 배포 지침 (Vercel)

이 프로젝트는 Vercel Serverless Function으로 최적화되어 있습니다.

1. GitHub 리포지토리에 코드를 푸시합니다.
2. Vercel 대시보드에서 새 프로젝트를 생성하고 리포지토리를 연결합니다.
3. `.env`의 내용을 Vercel **Environment Variables**에 등록합니다.
4. 배포가 완료되면 자동으로 `api/index.py` (Vercel Entrypoint)를 통해 서비스됩니다.

> **주의**: Vercel 환경에서는 `worker.py`가 백그라운드 프로세스로 돌지 않고, `main.py`에서 요청을 받아 동기적으로 처리합니다 (Fallback Mode).

---

## 📝 라이선스

© 2026 도봉구 영유아 복지톡. All rights reserved.