"""Concurrency, debouncing, and rate-limiting coordinator for PR reviews."""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict

logger = logging.getLogger("ai_reviewer.app.coordinator")


class PRReviewCoordinator:
    """
    Thread-safe coordinator for pull request review jobs:
    1. Prevents duplicate reviews for the exact same commit SHA.
    2. Serializes reviews on the same PR using per-PR locks to avoid race conditions.
    3. Tracks recently completed reviews with TTL.
    """

    def __init__(self, completion_ttl: float = 120.0):
        self.completion_ttl = completion_ttl
        self._pr_locks: dict[tuple[str, str, int], threading.Lock] = {}
        self._active_reviews: dict[tuple[str, str, int], str] = {}
        self._completed_reviews: OrderedDict[tuple[str, str, int, str], float] = OrderedDict()
        self._lock = threading.Lock()

    def get_pr_lock(self, owner: str, repo: str, pr_number: int) -> threading.Lock:
        """Get or create a dedicated lock for a specific pull request."""
        key = (owner.lower(), repo.lower(), pr_number)
        with self._lock:
            if key not in self._pr_locks:
                self._pr_locks[key] = threading.Lock()
            return self._pr_locks[key]

    def should_review(self, owner: str, repo: str, pr_number: int, head_sha: str) -> bool:
        """
        Return True if this commit SHA should be reviewed.
        Returns False if the exact same commit is currently in-flight or recently completed.
        """
        pr_key = (owner.lower(), repo.lower(), pr_number)
        commit_key = (owner.lower(), repo.lower(), pr_number, head_sha)
        now = time.time()

        with self._lock:
            # Clean expired completions
            while self._completed_reviews:
                oldest_key, timestamp = next(iter(self._completed_reviews.items()))
                if now - timestamp > self.completion_ttl:
                    self._completed_reviews.popitem(last=False)
                else:
                    break

            # If this exact commit was recently reviewed, skip
            if commit_key in self._completed_reviews:
                logger.info(
                    "Skipping review for %s/%s PR #%d @ %s: already completed recently.",
                    owner,
                    repo,
                    pr_number,
                    head_sha[:8],
                )
                return False

            # If this exact commit is already currently in-flight, skip
            if self._active_reviews.get(pr_key) == head_sha:
                logger.info(
                    "Skipping review for %s/%s PR #%d @ %s: review already in progress.",
                    owner,
                    repo,
                    pr_number,
                    head_sha[:8],
                )
                return False

            return True

    def mark_started(self, owner: str, repo: str, pr_number: int, head_sha: str) -> None:
        """Mark review as actively in progress."""
        pr_key = (owner.lower(), repo.lower(), pr_number)
        with self._lock:
            self._active_reviews[pr_key] = head_sha

    def mark_completed(self, owner: str, repo: str, pr_number: int, head_sha: str) -> None:
        """Mark review as completed and record timestamp."""
        pr_key = (owner.lower(), repo.lower(), pr_number)
        commit_key = (owner.lower(), repo.lower(), pr_number, head_sha)
        now = time.time()
        with self._lock:
            if self._active_reviews.get(pr_key) == head_sha:
                del self._active_reviews[pr_key]
            self._completed_reviews[commit_key] = now


class WebhookRateLimiter:
    """
    Thread-safe sliding-window rate limiter per installation or repository.
    Protects the webhook server from event floods or infinite loops.
    """

    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_rate_limited(self, identifier: str) -> bool:
        """
        Return True if identifier has exceeded rate limit in the current sliding window.
        Otherwise records the request timestamp and returns False.
        """
        if not identifier:
            return False

        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            timestamps = self._events.get(identifier, [])
            # Keep only events within window
            timestamps = [t for t in timestamps if t > window_start]

            if len(timestamps) >= self.max_requests:
                self._events[identifier] = timestamps
                return True

            timestamps.append(now)
            self._events[identifier] = timestamps
            return False

    def clear(self) -> None:
        """Clear all rate-limiting state."""
        with self._lock:
            self._events.clear()
