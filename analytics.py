"""Minimal first-party statistics. No question/answer text or IP is persisted."""
import asyncio
import hashlib
import hmac
import logging
import os
import time
import uuid
from datetime import date
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("chatbot.analytics")
CATEGORIES = {"의료/재활", "교육/보육", "가족 지원", "돌봄/양육", "생활 지원", "복합", "미분류"}
SOURCES = {"direct", "website", "qr", "partner", "unknown"}
INPUTS = {"typed", "suggestion", "clarification", "unknown"}
KIND_MAP = {"health": "의료/재활", "education": "교육/보육", "family": "가족 지원"}
_failures = 0
_saved = 0


def enabled():
    return (os.getenv("ENABLE_CHAT_ANALYTICS", "false").lower() == "true"
            and os.getenv("VERCEL_ENV") == "production"
            and bool(os.getenv("SESSION_SECRET_KEY")))


def category(value):
    if not isinstance(value, str):
        return "미분류"
    value = KIND_MAP.get(value, value)
    return value if value in CATEGORIES else "미분류"


def category_from_results(rows):
    values = {category(row.get("metadata", row).get("category")) for row in rows}
    values.discard("미분류")
    return next(iter(values)) if len(values) == 1 else "복합" if values else "미분류"


def note(request, **fields):
    state = getattr(request.state, "analytics", None)
    if state:
        state.update(fields)


def credentials():
    # Dedicated server key is optional. No anonymous/public key fallback.
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = (os.getenv("SUPABASE_ANALYTICS_KEY") or os.getenv("SUPABASE_KEY") or "").strip()
    if not url.startswith("https://") or not key:
        raise RuntimeError("analytics configuration missing")
    return url, key


async def rpc(name, payload, *, required=False):
    global _failures, _saved
    if not required and not enabled():
        return None
    try:
        url, key = credentials()
        # Use apikey only: sb_secret keys are not JWT bearer tokens.
        async with asyncio.timeout(8 if required else 1.5):
            async with httpx.AsyncClient(timeout=7 if required else 1.2) as client:
                headers = {"apikey": key, "Content-Type": "application/json"}
                if key.startswith("eyJ"):
                    headers["Authorization"] = "Bearer " + key
                response = await client.post(url + "/rest/v1/rpc/" + name,
                    headers=headers, json=payload)
                response.raise_for_status()
                value = response.json() if response.content else None
        _saved += 1
        return value
    except Exception as error:
        _failures += 1
        logger.warning("[Analytics] storage_failed operation=%s type=%s", name, type(error).__name__)
        if required:
            raise HTTPException(503, "통계 저장소에 연결하지 못했습니다. 프로젝트·키·SQL 적용 상태를 확인하세요.") from None
        return None


def _secret():
    return os.getenv("SESSION_SECRET_KEY", "").encode()


def click_token(record_id):
    value = f"{record_id}.{int(time.time())+86400}"
    signature = hmac.new(_secret(), value.encode(), hashlib.sha256).hexdigest()
    return value + "." + signature


def verify_click_token(token):
    try:
        record_id, expiry, signature = token.split(".")
        uuid.UUID(record_id)
        if not _secret() or not int(time.time()) <= int(expiry) <= int(time.time())+86400:
            return None
        expected = hmac.new(_secret(), f"{record_id}.{expiry}".encode(), hashlib.sha256).hexdigest()
        return record_id if hmac.compare_digest(expected, signature) else None
    except (ValueError, TypeError):
        return None


async def begin(chat, request):
    if not enabled():
        return None
    now = time.time()
    session = request.session
    if now - session.get("analytics_seen", 0) > 1800 or not session.get("analytics_session"):
        session["analytics_session"] = uuid.uuid4().hex
    session["analytics_seen"] = now
    sid = session["analytics_session"]
    client_id = str(getattr(chat, "analytics_id", None) or uuid.uuid4())
    record_id = str(uuid.uuid5(uuid.NAMESPACE_URL, sid + ":" + client_id))
    attempt = str(uuid.uuid4())
    state = {"id": record_id, "attempt": attempt, "started": now,
             "kind": "more" if chat.action == "more" else "question",
             "category": "미분류", "cache_hit": False, "cache_eligible": False}
    saved = await rpc("chatbot_analytics_begin", {
        "p_id": record_id, "p_attempt": attempt,
        "p_session": hmac.new(_secret(), sid.encode(), hashlib.sha256).hexdigest(),
        "p_kind": state["kind"], "p_language": chat.language,
        "p_source": getattr(chat, "entry_source", "unknown"),
        "p_input": getattr(chat, "input_method", "unknown"),
    })
    if saved != attempt:
        # Never manufacture a successful collection record after a write failure or duplicate.
        return None
    request.state.analytics = state
    return state


def outcome(response):
    if response.get("status") == "error":
        return "limited" if response.get("code") in {"daily_limit", "provider_limit"} else "error"
    if response.get("status") == "clarify":
        return "clarify"
    if response.get("status") != "complete":
        return "pending"
    return "answered" if response.get("total_found", 0) else "empty"


async def finish(state, response):
    if not state:
        return None
    result = outcome(response)
    if result == "pending":
        return None  # Durable start remains pending until the Redis worker completes.
    if state["kind"] == "other" and result not in {"error", "limited"}:
        result = "other"
    saved = await rpc("chatbot_analytics_finish", {
        "p_id": state["id"], "p_attempt": state["attempt"], "p_kind": state["kind"],
        "p_outcome": result, "p_category": category(state.get("category")),
        "p_cache_hit": bool(state.get("cache_hit")), "p_cache_eligible": bool(state.get("cache_eligible")),
        "p_duration": max(0, min(600000, round((time.time()-state["started"])*1000))),
    })
    return click_token(state["id"]) if saved and result == "answered" else None


def install(app, check_rate_limit):
    router = APIRouter()

    async def authenticate(request):
        await check_rate_limit(request, limit=10, window=60, scope="analytics-admin")
        secret = os.getenv("ADMIN_SECRET_KEY", "")
        provided = request.headers.get("X-Admin-Secret", "")
        if not secret:
            raise HTTPException(404, "Not Found")
        if not provided or not hmac.compare_digest(provided.encode(), secret.encode()):
            raise HTTPException(401, "Unauthorized")

    @router.get("/admin/analytics", include_in_schema=False)
    async def dashboard():
        # Public login shell only; all data endpoints enforce header authentication.
        return FileResponse("dashboard/analytics.html", headers={
            "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        })

    @router.get("/admin/analytics/data")
    async def report(request: Request, start: date, end: date):
        await authenticate(request)
        if start > end or (end-start).days > 729:
            raise HTTPException(422, "기간은 최대 730일입니다.")
        data = await rpc("chatbot_analytics_report",
            {"p_start": start.isoformat(), "p_end": end.isoformat()}, required=True)
        if not isinstance(data, dict) or not isinstance(data.get("days"), list):
            raise HTTPException(503, "통계 응답 형식이 올바르지 않습니다.")
        from fastapi.responses import JSONResponse
        return JSONResponse({**data, "enabled": enabled(),
            "project_host": urlparse(os.getenv("SUPABASE_URL", "")).hostname,
            "process_storage_failures": _failures,
            "process_storage_successes": _saved,
            "measurement": "서버가 접수한 유효한 요청 기준. 방문자 수·지원 수혜·정확도가 아닙니다."},
            headers={"Cache-Control": "no-store"})

    class ClickRequest(BaseModel):
        token: str = Field(min_length=1, max_length=150)

    @router.post("/analytics/source-click", status_code=204)
    async def source_click(body: ClickRequest, request: Request):
        await check_rate_limit(request, limit=30, window=60, scope="analytics-click")
        if not enabled():
            return
        # Reject cross-site browser submission. The token is bound to one saved response.
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Forbidden")
        record_id = verify_click_token(body.token)
        if not record_id:
            raise HTTPException(422, "Invalid token")
        await rpc("chatbot_analytics_click", {"p_id": record_id})

    app.include_router(router)
