"""Abstract base class for AI Reviewer providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ai_reviewer.config import AppConfig
from ai_reviewer.models.review import ReviewContext, ReviewResult


class AIReviewer(ABC):
    """Abstract interface for AI review engines."""

    def __init__(self, config: AppConfig):
        self.config = config

    @abstractmethod
    def review(self, context: ReviewContext, system_prompt: str, user_prompt: str) -> ReviewResult:
        """
        Execute AI code review and return validated ReviewResult.
        Must raise an exception or return ReviewResult with error summary on fatal failure.
        """
