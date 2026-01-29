# PROJECT KNOWLEDGE BASE

**Generated:** 2026-01-26
**Framework:** FastAPI + Redis + Supabase + Gemini

## OVERVIEW
Hybrid Async/Sync Chatbot. Frontend talks to FastAPI (`main.py`), which pushes jobs to Redis. `worker.py` consumes jobs, queries Supabase (Vector Search), and uses Gemini for RAG. Fallback to synchronous mode if Redis is down.

## STRUCTURE
```
.
├── main.py             # API Gateway, Rate Limiting, Redis/Sync Dispatch
├── worker.py           # Async Job Consumer, Search Logic, RAG Pipeline
├── utils.py            # Shared Lib: LLM wrappers, DB clients, Embedding, Key Rotation
├── index.py            # Notion -> Supabase Indexer (ETL)
├── static/             # Frontend Assets (HTML/JS/CSS)
└── requirements.txt    # Dependencies
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| **API Endpoints** | `main.py` | `/chat`, `/get_result`, `/feedback` |
| **Search Logic** | `worker.py` -> `process_job` | Search -> Rerank -> Format |
| **LLM Calls** | `utils.py` -> `generate_content_safe` | Handles Retries & Key Rotation |
| **DB Clients** | `utils.py` | Redis, Supabase, Notion, Gemini |
| **Prompt Eng** | `utils.py`, `worker.py` | Search logic in `worker`, Expansion in `utils` |

## KEY PATTERNS & CONVENTIONS
*   **Redis Fallback**: `main.py` checks `is_redis_down`. If True, imports `worker.process_job` and runs synchronously.
*   **LLM Safety**: NEVER call `genai.generate_content` directly. ALWAYS use `utils.generate_content_safe()` for retry/rotation.
*   **Key Rotation**: `utils.py` implements Round Robin for multiple Gemini keys.
*   **Multilingual**: `worker.py` handles KO/EN/VI/ZH. UI strings in `UI_TRANSLATIONS`.
*   **Rate Limiting**: Custom implementation in `main.py` (`check_rate_limit`) using Redis + In-memory fallback.
*   **Language Rule**: All analysis results, explanations, and responses provided by the agent MUST be in **Korean** (한국어), regardless of the input language, unless explicitly requested otherwise.

## ANTI-PATTERNS (THIS PROJECT)
*   **Direct API Calls**: Do not bypass `generate_content_safe` or `get_gemini_embedding`.
*   **Circular Imports**: `worker.py` imports `utils`. `main.py` imports both. Be careful when importing `main` into `worker`.
*   **Hardcoded Secrets**: Use `.env`. (Note: `main.py` has a default fallback for ADMIN_KEY, use with caution).
*   **Blocking Code**: `main.py` is Async, but `worker.py` logic is largely Sync (CPU bound). Keep them separate.

## COMMANDS
```bash
# Start API
uvicorn main:app --reload --port 8080

# Start Worker
python worker.py

# Manual Indexing
python index.py
```

## NOTES
*   **Supabase Keep-Alive**: `main.py` has a scheduler to wake up Supabase every 12h.
*   **Feedback**: Stored in Notion (`FEEDBACK_DB_ID`).
*   **Timezone**: Explicitly set to `Asia/Seoul` in schedulers.
