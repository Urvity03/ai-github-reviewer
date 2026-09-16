"""OpenAI provider implementation with structured output, retries, and error handling."""

from __future__ import annotations

import json
import os
import time

from openai import OpenAI
from pydantic import ValidationError

from ai_reviewer.config import AppConfig
from ai_reviewer.models.review import ReviewContext, ReviewResult
from ai_reviewer.providers.base import AIReviewer


class OpenAIReviewer(AIReviewer):
    """Production OpenAI provider with structured outputs and resilience."""

    def __init__(self, config: AppConfig, api_key: str | None = None):
        super().__init__(config)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("OPENAI_BASE_URL")
        self.model = os.getenv("OPENAI_MODEL", config.review.model)
        self.timeout = float(os.getenv("OPENAI_TIMEOUT", "90.0"))

        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable is not set. "
                "Please configure OPENAI_API_KEY in your GitHub Secrets or environment."
            )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url or None,
            timeout=self.timeout,
        )

    def review(self, context: ReviewContext, system_prompt: str, user_prompt: str) -> ReviewResult:
        """Call OpenAI with system instructions, user PR context, and structured output."""
        max_retries = 3
        delay = 2.0
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=self.config.review.temperature,
                )

                raw_text = response.choices[0].message.content or ""
                token_usage = {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                }

                # Parse JSON
                parsed_json = json.loads(raw_text)

                # Validate with Pydantic
                result = ReviewResult.model_validate(parsed_json)
                result.token_usage = token_usage
                result.raw_output = raw_text
                return result

            except (json.JSONDecodeError, ValidationError) as validation_err:
                last_error = validation_err
                print(f"[WARN] OpenAI returned invalid structured schema (attempt {attempt}/{max_retries}): {validation_err}")
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2
                    user_prompt += "\n\nCRITICAL ERROR: Your previous response was not valid JSON conforming to the requested schema. Please fix and output strictly valid JSON only."
            except Exception as err:
                last_error = err
                print(f"[WARN] OpenAI API request failed (attempt {attempt}/{max_retries}): {err}")
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2

        # If all retries failed, raise or return error review result
        raise RuntimeError(f"OpenAI review failed after {max_retries} attempts. Last error: {last_error}")
