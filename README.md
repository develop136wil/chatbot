# 도봉구 영유아 복지톡 👶

도봉구 영유아 복지 정보를 AI 챗봇을 통해 쉽게 찾아볼 수 있는 서비스입니다.

## 🌟 주요 기능

- **AI 기반 검색**: Gemini를 활용한 지능형 복지 정보 검색
- **다국어 지원**: 한국어, 영어, 베트남어, 중국어
- **Notion 연동**: Notion 데이터베이스에서 자동으로 복지 정보 인덱싱
- **실시간 응답**: 질문에 맞는 복지 정보를 카드 형태로 제공

## 🛠️ 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | FastAPI (Python) |
| AI/LLM | Google Gemini 2.5, Groq (Llama 3.3) |
| Database | Supabase (PostgreSQL + pgvector) |
| Hosting | Vercel (Serverless) |
| Data Source | Notion API |

## 📦 설치 및 실행

### 1. 환경 변수 설정

`.env.example`을 참고하여 `.env` 파일을 생성하세요:

```bash
cp .env.example .env
```

필수 환경 변수:
- `SUPABASE_URL` - Supabase 프로젝트 URL
- `SUPABASE_KEY` - Supabase 서비스 키
- `GEMINI_API_KEYS` - Google Gemini API 키 (쉼표로 구분하여 여러 개 가능)
- `NOTION_API_KEY` - Notion Integration 토큰

### 2. 의존성 설치

```bash
pip install -r requirements.txt
```

### 3. 로컬 실행

```bash
uvicorn main:app --reload --port 8000
```

브라우저에서 `http://localhost:8000` 접속

## 🚀 배포

Vercel에 자동 배포됩니다. `main` 브랜치에 푸시하면 자동으로 배포됩니다.

```bash
git push origin main
```

## 📁 프로젝트 구조

```
chatbot/
├── api/
│   └── index.py          # Vercel 진입점
├── static/
│   ├── index.html        # 메인 페이지
│   ├── style.css         # 스타일시트
│   └── script.js         # 클라이언트 스크립트
├── main.py               # FastAPI 앱
├── worker.py             # 챗봇 처리 로직
├── utils.py              # 유틸리티 함수
├── run_indexer.py        # Notion → Supabase 인덱싱
└── requirements.txt      # Python 의존성
```

## 🔗 링크

- **라이브 서비스**: [chatbot-tau-bay.vercel.app](https://chatbot-tau-bay.vercel.app)
- **데이터 소스**: Notion 영유아 복지 데이터베이스

## 📝 라이선스

© 2026 도봉구 영유아 복지톡. All rights reserved.