"""Privacy-safe duration measurements; no credentials, prompts or responses."""
import asyncio
import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from functools import wraps

logger = logging.getLogger("chatbot.performance")
_request_id = ContextVar("chatbot_request_id", default=None)


def current_request_id():
    return _request_id.get()


def _emit(stage, started, outcome, **fields):
    # Only constants, generated IDs and numeric timing/status reach this logger.
    try:
        logger.info("[Performance] %s", json.dumps({
            "request_id": current_request_id(),
            "stage": stage,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "outcome": outcome,
            **fields,
        }, separators=(",", ":")))
    except Exception:
        # Logging failure must never break a chat response.
        pass


def timed_async(stage):
    """Measure one call, preserve its return value, exceptions and cancellation.

    'returned' means the function returned, NOT that its business result succeeded.
    Stages can nest; their times must not be added to calculate total latency.
    """
    def decorate(fn):
        @wraps(fn)
        async def measured(*args, **kwargs):
            started = time.perf_counter()
            outcome = "returned"
            try:
                return await fn(*args, **kwargs)
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            except BaseException:
                outcome = "raised"
                raise
            finally:
                _emit(stage, started, outcome)
        return measured
    return decorate


def traced_job(fn):
    """Keep the API trace across Redis jobs, without logging the job payload."""
    @wraps(fn)
    async def wrapped(job_data, *args, **kwargs):
        trace_id = job_data.get("trace_id")
        if not isinstance(trace_id, str) or not re.fullmatch(r"[0-9a-f]{32}", trace_id):
            trace_id = current_request_id() or uuid.uuid4().hex
        token = _request_id.set(trace_id)
        try:
            return await fn(job_data, *args, **kwargs)
        finally:
            _request_id.reset(token)
    return wrapped


class ChatTimingMiddleware:
    """Pure ASGI middleware: measure /chat, preserving body and status.

    Total stops after the response body is sent. Server-Timing stops at headers.
    The request ID is server-generated; incoming headers are never trusted.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/chat":
            return await self.app(scope, receive, send)
        token = _request_id.set(uuid.uuid4().hex)
        started = time.perf_counter()
        status = None
        outcome = "returned"

        async def measured_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", current_request_id().encode("ascii")),
                    (b"server-timing", ("chat_headers;dur=%.2f" %
                     ((time.perf_counter() - started) * 1000)).encode("ascii")),
                ]
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except BaseException:
            outcome = "raised"
            raise
        finally:
            _emit("chat_total", started, outcome, http_status=status)
            _request_id.reset(token)
