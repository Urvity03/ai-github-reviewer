"""GitHub Webhook receiver, HMAC-SHA256 signature verification, and event router."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from pydantic import BaseModel, Field


class WebhookPREvent(BaseModel):
    """Structured representation of a pull request webhook event."""

    action: str
    installation_id: int
    repo_owner: str
    repo_name: str
    pr_number: int
    pr_title: str
    pr_description: str = ""
    base_branch: str
    head_branch: str
    head_sha: str
    is_draft: bool = False
    sender_login: str = ""
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class WebhookHandler:
    """Handles GitHub webhook signature verification and pull_request event parsing."""

    SUPPORTED_PR_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}

    def __init__(self, secret: str | None = None):
        self.secret = secret or os.getenv("GITHUB_WEBHOOK_SECRET")

    def verify_signature(self, payload_bytes: bytes, signature_header: str | None) -> bool:
        """
        Verify the GitHub X-Hub-Signature-256 HMAC SHA256 signature.
        Uses constant-time comparison to prevent timing attacks.
        """
        if not self.secret:
            raise ValueError("GITHUB_WEBHOOK_SECRET is not configured.")

        if not signature_header or not signature_header.startswith("sha256="):
            return False

        expected_sig = signature_header.split("sha256=", 1)[1].strip()
        computed_sig = hmac.new(
            self.secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_sig, computed_sig)

    def parse_pull_request_event(self, payload: dict[str, Any]) -> WebhookPREvent | None:
        """
        Parse and filter a pull_request webhook payload.
        Returns WebhookPREvent if actionable, or None if the event should be ignored (e.g. draft PR or unsupported action).
        """
        action = payload.get("action")
        if action not in self.SUPPORTED_PR_ACTIONS:
            return None

        pr_data = payload.get("pull_request")
        if not pr_data:
            return None

        # Ignore draft PRs unless transitioning to ready_for_review
        is_draft = pr_data.get("draft", False)
        if is_draft and action != "ready_for_review":
            return None

        installation = payload.get("installation")
        if not installation or "id" not in installation:
            return None
        installation_id = installation["id"]

        repo = payload.get("repository", {})
        owner_info = repo.get("owner", {})
        owner = owner_info.get("login") or owner_info.get("name") or ""
        repo_name = repo.get("name") or ""

        if not owner or not repo_name:
            return None

        base_ref = pr_data.get("base", {}).get("ref", "main")
        head_ref = pr_data.get("head", {}).get("ref", "head")
        head_sha = pr_data.get("head", {}).get("sha", "HEAD")

        return WebhookPREvent(
            action=action,
            installation_id=installation_id,
            repo_owner=owner,
            repo_name=repo_name,
            pr_number=pr_data.get("number", 0),
            pr_title=pr_data.get("title", ""),
            pr_description=pr_data.get("body") or "",
            base_branch=base_ref,
            head_branch=head_ref,
            head_sha=head_sha,
            is_draft=is_draft,
            sender_login=payload.get("sender", {}).get("login", ""),
            raw_payload=payload,
        )
