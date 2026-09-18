"""Google Gemini provider implementation using official Google GenAI Python SDK."""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from ai_reviewer.config import AppConfig
from ai_reviewer.models.review import (
    DecisionEnum,
    ReviewContext,
    ReviewFinding,
    ReviewResult,
)
from ai_reviewer.providers.base import AIReviewer

logger = logging.getLogger(__name__)

TRANSIENT_HTTP_CODES = {408, 429, 500, 502, 503, 504}
NON_TRANSIENT_HTTP_CODES = {400, 401, 403, 404, 405, 422}
TRANSIENT_STATUS_NAMES = {
    "RESOURCE_EXHAUSTED",
    "UNAVAILABLE",
    "INTERNAL",
    "DEADLINE_EXCEEDED",
}
NON_TRANSIENT_STATUS_NAMES = {
    "INVALID_ARGUMENT",
    "PERMISSION_DENIED",
    "NOT_FOUND",
    "UNAUTHENTICATED",
    "ALREADY_EXISTS",
    "FAILED_PRECONDITION",
}
TRANSIENT_SUBSTRINGS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "resource_exhausted",
    "unavailable",
    "internal",
    "overloaded",
    "high demand",
    "rate limit",
    "temporarily unavailable",
    "service unavailable",
    "deadline exceeded",
    "connection reset",
    "connection refused",
    "timed out",
    "timeout",
)


def extract_retry_delay(err: Exception) -> float | None:
    """
    Extract server-requested retry delay (in seconds) from Google GenAI error details,
    HTTP headers, or error message when available.
    """
    # 1. Structured details dictionary from google.genai.errors.APIError / ClientError
    details = getattr(err, "details", None)
    if isinstance(details, dict):
        err_obj = details.get("error", details)
        sub_details = err_obj.get("details", []) if isinstance(err_obj, dict) else []
        if isinstance(sub_details, list):
            for item in sub_details:
                if isinstance(item, dict):
                    delay_val = item.get("retryDelay")
                    if delay_val:
                        if isinstance(delay_val, str) and delay_val.endswith("s"):
                            delay_val = delay_val[:-1]
                        try:
                            val = float(delay_val)
                            if val > 0:
                                return val
                        except (ValueError, TypeError):
                            pass

    # 2. HTTP response headers (Retry-After)
    resp = getattr(err, "response", None)
    headers = getattr(resp, "headers", None) if resp else None
    if headers:
        retry_header = headers.get("retry-after") or headers.get("Retry-After")
        if retry_header:
            try:
                val = float(retry_header)
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass

    # 3. Fallback regex on error message (e.g. "Please retry in 26.7s")
    err_str = str(err)
    match = re.search(r"retry in\s+([0-9.]+)\s*s", err_str, re.IGNORECASE)
    if match:
        try:
            val = float(match.group(1))
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass

    return None


def is_transient_error(err: Exception) -> bool:
    """
    Determine whether an error is transient and retryable, preferring
    structured error information (code, status) with string fallback.
    """
    # Network / Timeout standard exceptions
    if isinstance(err, (TimeoutError, ConnectionError, OSError)):
        return True

    # Check for HTTP status code on exception
    code = getattr(err, "code", None) or getattr(err, "status_code", None)
    if code is not None:
        try:
            code_int = int(code)
            if code_int in NON_TRANSIENT_HTTP_CODES:
                return False
            if code_int in TRANSIENT_HTTP_CODES:
                return True
        except (ValueError, TypeError):
            pass

    # Check for gRPC / Google RPC status name
    status = getattr(err, "status", None)
    if isinstance(status, str):
        status_upper = status.upper()
        if status_upper in NON_TRANSIENT_STATUS_NAMES:
            return False
        if status_upper in TRANSIENT_STATUS_NAMES:
            return True

    # Fallback to message string analysis
    err_lower = str(err).lower()
    if any(
        m in err_lower
        for m in (
            "invalid api key",
            "api_key_invalid",
            "permission_denied",
            "unauthenticated",
            "invalid argument",
        )
    ):
        return False

    return any(marker in err_lower for marker in TRANSIENT_SUBSTRINGS)


def compute_backoff_delay(
    attempt: int,
    server_delay: float | None = None,
    base_delay: float = 5.0,
    max_delay: float = 60.0,
) -> float:
    """
    Compute backoff sleep duration in seconds.
    If server_delay is provided, respect it with small positive jitter.
    Otherwise, apply exponential backoff with jitter:
      attempt 1: ~5-10s
      attempt 2: ~10-20s
      attempt 3: ~20-40s
      attempt 4: ~40-60s
    """
    if server_delay is not None and server_delay > 0:
        jitter = random.uniform(0.5, 2.0)
        return min(max_delay, max(1.0, server_delay + jitter))

    exp_factor = 2 ** (attempt - 1)
    base = base_delay * exp_factor
    jitter = random.uniform(base * 0.2, base * 0.8)
    return min(max_delay, max(1.0, base + jitter))


class AIReviewOutput(BaseModel):
    """Clean structured schema strictly conforming to Gemini response_schema requirements."""

    summary: str
    decision: DecisionEnum
    findings: list[ReviewFinding] = Field(default_factory=list)


class GeminiReviewer(AIReviewer):
    """Production Google Gemini provider using official google-genai SDK."""

    def __init__(self, config: AppConfig, api_key: str | None = None):
        super().__init__(config)

        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_MODEL", config.review.model)

        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY environment variable is not set. "
                "Please configure GEMINI_API_KEY in your GitHub Secrets or environment."
            )

        self.client = genai.Client(api_key=self.api_key)

    def _sanitize_error(self, message: str) -> str:
        """Strip sensitive credentials from error messages before logging or raising."""
        if not message:
            return ""
        if self.api_key and self.api_key in message:
            message = message.replace(self.api_key, "[REDACTED]")
        message = re.sub(r"AIza[0-9A-Za-z-_]{35}", "[REDACTED_API_KEY]", message)
        return message.strip()

    def review(
        self,
        context: ReviewContext,
        system_prompt: str,
        user_prompt: str,
    ) -> ReviewResult:
        """
        Call Google Gemini with system instructions, user PR context,
        and structured JSON output.

        Transient Gemini/API failures (such as 429, 503, timeouts) are retried
        with server-informed backoff and exponential jitter across up to 4 attempts.
        Non-transient failures (400, 401, 403) fail fast immediately.
        """
        max_api_retries = 4
        max_schema_retries = 2
        last_error: Exception | None = None

        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=AIReviewOutput,
            temperature=self.config.review.temperature,
        )

        schema_attempt = 0
        current_user_prompt = user_prompt

        for attempt in range(1, max_api_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=current_user_prompt,
                    config=gen_config,
                )
            except Exception as err:
                last_error = err
                sanitized_err = self._sanitize_error(str(err))

                if not is_transient_error(err):
                    print(f"[ERROR] Gemini non-transient API failure: {sanitized_err}")
                    break

                print(
                    f"[WARN] Gemini transient API failure "
                    f"(attempt {attempt}/{max_api_retries}): {sanitized_err}"
                )

                if attempt < max_api_retries:
                    server_delay = extract_retry_delay(err)
                    wait = compute_backoff_delay(attempt, server_delay=server_delay)
                    print(f"[INFO] Retrying Gemini request in {wait:.0f}s...")
                    time.sleep(wait)
                continue

            raw_text = response.text or ""
            if not raw_text.strip():
                last_error = ValueError("Gemini returned an empty response.")
                print(
                    f"[WARN] Gemini transient API failure "
                    f"(attempt {attempt}/{max_api_retries}): Gemini returned an empty response."
                )
                if attempt < max_api_retries:
                    wait = compute_backoff_delay(attempt)
                    print(f"[INFO] Retrying Gemini request in {wait:.0f}s...")
                    time.sleep(wait)
                continue

            # Parse and validate structured JSON output
            try:
                parsed_json = json.loads(raw_text)
                output = AIReviewOutput.model_validate(parsed_json)
            except (json.JSONDecodeError, ValidationError) as val_err:
                schema_attempt += 1
                sanitized_val_err = self._sanitize_error(str(val_err))
                print(
                    f"[WARN] Gemini returned invalid structured schema "
                    f"(schema attempt {schema_attempt}/{max_schema_retries}): {sanitized_val_err}"
                )
                if schema_attempt < max_schema_retries:
                    # Bounded prompt correction without compounding multiple errors
                    current_user_prompt = (
                        f"{user_prompt}\n\nCRITICAL ERROR: Your previous response was "
                        f"not valid JSON conforming to the requested schema. "
                        f"Please fix the response and output ONLY valid JSON "
                        f"matching the provided response schema."
                    )
                    time.sleep(1.0)
                    continue
                last_error = val_err
                break

            # Extract token usage metadata from Gemini response if available
            token_usage = None
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                meta = response.usage_metadata
                token_usage = {
                    "prompt_tokens": getattr(meta, "prompt_token_count", 0) or 0,
                    "completion_tokens": getattr(meta, "candidates_token_count", 0) or 0,
                    "total_tokens": getattr(meta, "total_token_count", 0) or 0,
                }

            return ReviewResult(
                summary=output.summary,
                decision=output.decision,
                findings=output.findings,
                token_usage=token_usage,
                raw_output=raw_text,
            )

        sanitized_last_error = self._sanitize_error(str(last_error))
        raise RuntimeError(
            f"Gemini review failed after {max_api_retries} attempts. "
            f"Last error: {sanitized_last_error}"
        ) from last_error
