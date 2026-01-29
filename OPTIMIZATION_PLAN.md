# Codebase Optimization Analysis Report (Zero Cost Focus)

Based on the static analysis and architectural review of `main.py`, `worker.py`, and `utils.py`, here are the identified optimization opportunities.

## 1. **Gemini API & Prompt Engineering (Latency & Token Efficiency)**

*   **Issue**: `utils.py:187` `extract_info_from_question` uses a large prompt with few-shot examples for intent classification every time.
*   **Optimization**:
    *   **Prompt Compression**: The prompt can be significantly shortened. System instructions are free, but input tokens add latency.
    *   **Keyword Extraction**: Currently, `extract_info_from_question` and `expand_search_query` (utils.py:410) are separate calls. **Merge these into a single LLM call** to save ~1-2 seconds of latency per request.
    *   **Caching**: `utils.py:193` already uses Redis caching, but the cache key `extract_v2:{hash}` could be smarter. Normalize text more aggressively (remove all spaces/punctuation) to increase cache hit rate.

## 2. **Redis & Supabase Interactions (Network Overhead)**

*   **Issue**: `worker.py:158` iterates through `display_results` and calls `translate_title_simple` (LLM call) *sequentially* for each document if the language is not Korean.
    *   **Impact**: If user asks in English and there are 3 results, it waits for 3 separate LLM calls (30s timeout each). This is a HUGE bottleneck.
*   **Optimization**:
    *   **Parallel Execution**: Use `asyncio.gather` (if async) or `ThreadPoolExecutor` (if sync worker) to run translation tasks in parallel.
    *   **Batch Translation**: Send ALL titles to Gemini in a *single* prompt: "Translate these 3 titles to English...". This reduces 3 round-trips to 1. **(Strongly Recommended)**

*   **Issue**: `utils.py:877` `search_supabase` executes 2 queries sequentially (Category search -> Global search fallback).
*   **Optimization**:
    *   This logic is actually sound for accuracy. However, `utils.py:821` `check_semantic_cache` runs *before* this. Ensure the semantic cache threshold (0.92) is tuned correctly. If too low, it returns bad cached answers; if too high, it's useless. *Analysis suggests 0.95+ is safer for "exact match" caching.*

## 3. **Async/Sync Mixing (Blocking the Event Loop)**

*   **Issue**: `main.py` is an Async FastAPI app, but it calls `utils.extract_info_from_question` (`main.py:191`) which calls `generate_content_safe` (`utils.py:152`).
    *   **Critical Flaw**: `generate_content_safe` uses `time.sleep(2)` and synchronous `model.generate_content`. This **BLOCKS the entire FastAPI event loop** for 2+ seconds per request. If 5 people chat at once, the 5th person waits 10+ seconds just for the server to acknowledge.
*   **Optimization**:
    *   **Make LLM calls Async**: Use `model.generate_content_async` and `await`.
    *   **Make Utils Async**: Refactor `extract_info_from_question` and `expand_search_query` to be `async def`.
    *   **Redis Check**: `redis_client` operations in `main.py` (e.g., `redis_client.get`) are synchronous (using `redis` lib, not `redis.asyncio`). This also blocks. Switch to `redis.asyncio` or run in threadpool.

## 4. **Code Quality & Maintenance**

*   **Issue**: `utils.py:209` Prompt definition inside function.
*   **Optimization**: Move large prompts to a separate `prompts.py` or constant strings at top of file for readability.
*   **Issue**: `utils.py:104` `rotate_api_key` relies on a global `KEY_CYCLE` iterator. This works for a single worker process but might be tricky if you scale to multiple workers (though for free tier single worker, it's fine).

## 5. **Specific "Zero Cost" Enhancements**

*   **Aggressive Caching**:
    *   Use **In-Memory LRU Cache** (`functools.lru_cache`) for `extract_info_from_question` in *addition* to Redis. Redis has network latency; RAM is instant.
    *   Cache *negative* results too (e.g., "invalid intent") to prevent repeated LLM abuse.

## Action Plan (Prioritized)

1.  **[Critical] Fix Async Blocking**: Refactor `main.py` and `utils.py` to use `async` Gemini/Redis calls. This is the biggest performance win.
2.  **[High] Batch Translation**: Modify `worker.py` to translate titles in a single batch request instead of a loop.
3.  **[Medium] Merge Intent/Keyword LLM**: Combine the two LLM calls in `utils.py` into one to halve the pre-processing time.

Would you like me to start with **Action 1 (Async Refactoring)** or **Action 2 (Batch Translation)**?
