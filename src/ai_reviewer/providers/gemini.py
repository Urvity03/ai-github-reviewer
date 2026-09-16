"""Google Gemini provider implementation using official Google GenAI Python SDK."""

from __future__ import annotations

import json
import os
import time

from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from ai_reviewer.config import AppConfig
from ai_reviewer.models.review import DecisionEnum, ReviewContext, ReviewFinding, ReviewResult
from ai_reviewer.providers.base import AIReviewer


class AIReviewOutput(BaseModel):
    """Clean structured schema strictly conforming to Gemini response_schema requirements."""

    summary: str
    decision: DecisionEnum
    findings: list[ReviewFinding] = Field(default_factory=list)


class GeminiReviewer(AIReviewer):
    """Production Google Gemini provider using official google-genai SDK (Free Tier compatible)."""

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

    def review(self, context: ReviewContext, system_prompt: str, user_prompt: str) -> ReviewResult:
        """Call Google Gemini with system instructions, user PR context, and structured output."""
        max_retries = 3
        delay = 2.0
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

                # Extract token usage metadata from Gemini response if available
                token_usage = None
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    meta = response.usage_metadata
                    token_usage = {
                        "prompt_tokens": getattr(meta, "prompt_token_count", 0) or 0,
                        "completion_tokens": getattr(meta, "candidates_token_count", 0) or 0,
                        "total_tokens": getattr(meta, "total_token_count", 0) or 0,
                    }

                # Parse JSON string
                parsed_json = json.loads(raw_text)

                # Validate with Pydantic model
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
                    f"[WARN] Gemini returned invalid structured schema (attempt {attempt}/{max_retries}): {validation_err}"
                )
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2
                    user_prompt += (
                        "\n\nCRITICAL ERROR: Your previous response was not valid JSON conforming to the requested schema. "
                        "Please fix and output strictly valid JSON conforming to ReviewResult schema only."
                    )
            except Exception as err:
                last_error = err
                print(f"[WARN] Gemini API request failed (attempt {attempt}/{max_retries}): {err}")
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2

        raise RuntimeError(f"Gemini review failed after {max_retries} attempts. Last error: {last_error}")
