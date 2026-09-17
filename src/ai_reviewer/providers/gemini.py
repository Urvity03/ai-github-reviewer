"""Google Gemini provider implementation using official Google GenAI Python SDK."""

from __future__ import annotations

import json
import os
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

    def review(
        self,
        context: ReviewContext,
        system_prompt: str,
        user_prompt: str,
    ) -> ReviewResult:
        """
        Call Google Gemini with system instructions, user PR context,
        and structured JSON output.

        Transient Gemini/API failures such as 429 and 503 are retried
        with exponential backoff. Non-transient failures fail immediately.
        """

        max_retries = 3

        # Give overloaded/rate-limited Gemini enough time to recover.
        retry_delays = [2.0, 5.0, 10.0]

        last_error: Exception | None = None

        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=AIReviewOutput,
            temperature=self.config.review.temperature,
        )

        for attempt in range(1, max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=gen_config,
                )

                raw_text = response.text or ""

                if not raw_text.strip():
                    raise ValueError(
                        "Gemini returned an empty response."
                    )

                # Extract token usage metadata from Gemini response if available.
                token_usage = None

                if (
                    hasattr(response, "usage_metadata")
                    and response.usage_metadata
                ):
                    meta = response.usage_metadata

                    token_usage = {
                        "prompt_tokens": getattr(
                            meta,
                            "prompt_token_count",
                            0,
                        )
                        or 0,
                        "completion_tokens": getattr(
                            meta,
                            "candidates_token_count",
                            0,
                        )
                        or 0,
                        "total_tokens": getattr(
                            meta,
                            "total_token_count",
                            0,
                        )
                        or 0,
                    }

                # Parse Gemini's structured JSON response.
                parsed_json = json.loads(raw_text)

                # Validate the response against the Pydantic schema.
                output = AIReviewOutput.model_validate(parsed_json)

                return ReviewResult(
                    summary=output.summary,
                    decision=output.decision,
                    findings=output.findings,
                    token_usage=token_usage,
                    raw_output=raw_text,
                )

            except (json.JSONDecodeError, ValidationError) as validation_err:
                last_error = validation_err

                print(
                    f"[WARN] Gemini returned invalid structured schema "
                    f"(attempt {attempt}/{max_retries}): {validation_err}"
                )

                if attempt < max_retries:
                    wait = retry_delays[attempt - 1]

                    print(
                        f"[INFO] Retrying structured Gemini response "
                        f"in {wait:.0f}s..."
                    )

                    time.sleep(wait)

                    # Help Gemini correct a malformed structured response.
                    user_prompt += (
                        "\n\nCRITICAL ERROR: Your previous response was "
                        "not valid JSON conforming to the requested schema. "
                        "Please fix the response and output ONLY valid JSON "
                        "matching the provided response schema."
                    )

            except Exception as err:
                last_error = err
                error_text = str(err)

                # Gemini transient errors that are worth retrying.
                transient_markers = (
                    "429",
                    "500",
                    "502",
                    "503",
                    "504",
                    "RESOURCE_EXHAUSTED",
                    "UNAVAILABLE",
                    "INTERNAL",
                    "overloaded",
                    "high demand",
                    "rate limit",
                    "temporarily unavailable",
                    "service unavailable",
                )

                is_transient = any(
                    marker.lower() in error_text.lower()
                    for marker in transient_markers
                )

                if not is_transient:
                    print(
                        f"[ERROR] Gemini non-transient API failure: {err}"
                    )
                    break

                print(
                    f"[WARN] Gemini transient API failure "
                    f"(attempt {attempt}/{max_retries}): {err}"
                )

                if attempt < max_retries:
                    wait = retry_delays[attempt - 1]

                    print(
                        f"[INFO] Retrying Gemini request "
                        f"in {wait:.0f}s..."
                    )

                    time.sleep(wait)

        raise RuntimeError(
            f"Gemini review failed after {max_retries} attempts. "
            f"Last error: {last_error}"
        ) from last_error