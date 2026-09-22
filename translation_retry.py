"""Pure helpers for the single-process, offline indexer (no SDK/network imports)."""
import json
import logging
import math
import re
import time
from email.utils import parsedate_to_datetime

logger = logging.getLogger("chatbot.translation")


class TranslationFailure(RuntimeError):
    def __init__(self, reason, retryable=False):
        self.reason = reason
        self.retryable = retryable
        super().__init__(reason)


def seconds(value):
    """Accept provider durations (2m3.5s, 300ms), seconds, or HTTP dates."""
    if value is None:
        return None
    text = str(value).strip()
    try:
        number = float(text)
        return max(0.0, number) if math.isfinite(number) else None
    except ValueError:
        pass
    if re.fullmatch(r"(?:\d+(?:\.\d+)?(?:ms|s|m|h))+", text):
        units = {"ms": .001, "s": 1, "m": 60, "h": 3600}
        return sum(float(n) * units[u] for n, u in re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)", text))
    try:
        return max(0.0, parsedate_to_datetime(text).timestamp() - time.time())
    except (ValueError, TypeError, OverflowError):
        return None


def token_estimate(text, output_tokens):
    # Conservative heuristic, not a tokenizer or an organization-wide reservation.
    return math.ceil(sum(.25 if ord(c) < 128 else 1.5 for c in text)) + output_tokens


class TranslationRateGate:
    """Pace serial indexing only; honor headers shared with other account traffic."""
    def __init__(self, tpm=8000, max_wait=90, clock=None, sleep=None):
        self.tpm = tpm
        self.max_wait = max_wait
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.next_at = 0.0
        self.reset_at = 0.0
        self.remaining = None
        self.disabled = False

    def observe(self, headers):
        h = {str(k).lower(): str(v) for k, v in headers.items()}
        try:
            limit = float(h.get("x-ratelimit-limit-tokens", self.tpm))
            if math.isfinite(limit) and limit > 0:
                self.tpm = min(self.tpm, limit)
            remaining = float(h["x-ratelimit-remaining-tokens"])
            if math.isfinite(remaining):
                self.remaining = max(0, remaining)
                self.reset_at = self.clock() + (seconds(h.get("x-ratelimit-reset-tokens")) or 60)
        except (KeyError, ValueError):
            pass
        if h.get("x-ratelimit-remaining-requests") == "0":
            self.disabled = True  # Groq documents this header as the daily limit.

    def before(self, estimate):
        if self.disabled:
            raise TranslationFailure("provider_disabled_for_run")
        # Estimates are deliberately conservative; let the provider decide whether
        # a single request fits, reserving at most one whole minute locally.
        estimate = min(estimate, self.tpm)
        now = self.clock()
        target = self.next_at
        if self.remaining is not None and estimate > self.remaining and self.reset_at > now:
            target = max(target, self.reset_at + .25)
        delay = max(0.0, target - now)
        if delay > self.max_wait:
            raise TranslationFailure("provider_cooldown")
        if delay:
            logger.info("[Translation Wait] seconds=%.2f", delay)
            remaining_delay = delay
            while remaining_delay > 0:
                part = min(60.0, remaining_delay)
                self.sleep(part)
                remaining_delay -= part
        now = self.clock()
        if now >= self.reset_at:
            self.remaining = None
        # Reserve even when a request fails, so a retry cannot burst immediately.
        self.next_at = now + max(2.0, estimate / self.tpm * 60)

    def on_error(self, error):
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", {}) or {}
        self.observe(headers)
        status = getattr(error, "status_code", None)
        if status in (401, 403, 404):
            self.disabled = True
            return TranslationFailure("provider_configuration")
        if status == 429:
            h = {str(k).lower(): v for k, v in headers.items()}
            # Read provider error for timing only; never log raw error/body/prompt.
            message = str(error)
            match = re.search(r"try again in\s*([\d.]+)s", message, re.I)
            delay = seconds(h.get("retry-after"))
            if delay is None and match:
                delay = seconds(match.group(1))
            if delay is None:
                delay = seconds(h.get("x-ratelimit-reset-tokens"))
            delay = 60 if delay is None else delay
            if re.search(r"tokens per day|requests per day|\bTPD\b|\bRPD\b", message, re.I):
                self.disabled = True
            self.next_at = max(self.next_at, self.clock() + delay + .25)
            return TranslationFailure("rate_limited", not self.disabled and delay + .25 <= self.max_wait)
        if status is None or status in (408, 409) or (isinstance(status, int) and status >= 500):
            return TranslationFailure("provider_transient", True)
        return TranslationFailure("provider_rejected")


def translation_json(text, languages):
    if not isinstance(text, str) or not text.strip():
        raise TranslationFailure("empty_response", True)
    candidate = text.strip()
    # Accept a complete fenced object, never a substring of truncated output.
    if candidate.startswith("```"):
        candidate = re.sub(r"^\u0060{3}(?:json)?\s*|\s*\u0060{3}$", "", candidate, flags=re.I).strip()
    try:
        payload = json.loads(candidate)
    except (ValueError, TypeError):
        raise TranslationFailure("invalid_json", True) from None
    if not isinstance(payload, dict):
        raise TranslationFailure("invalid_schema", True)
    valid = {}
    for lang in languages:
        item = payload.get(lang)
        if not isinstance(item, dict):
            continue
        fields = {key: value.strip() for key in ("title", "content")
                  if isinstance((value := item.get(key)), str) and value.strip()}
        if fields:
            valid[lang] = fields
    if not valid:
        raise TranslationFailure("missing_fields", True)
    return valid


def missing_languages(result, languages):
    return [lang for lang in languages if not all(result.get(lang, {}).get(k) for k in ("title", "content"))]
