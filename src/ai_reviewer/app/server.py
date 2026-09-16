"""FastAPI webhook server for GitHub App."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, status

from ai_reviewer import __version__
from ai_reviewer.app.auth import GitHubAppAuth
from ai_reviewer.app.service import process_issue_comment_event, process_pull_request_event
from ai_reviewer.app.webhook import WebhookDeliveryCache, WebhookHandler
from ai_reviewer.commands import is_bot_comment

logger = logging.getLogger("ai_reviewer.app.server")


def create_app(
    auth: GitHubAppAuth | None = None,
    webhook_secret: str | None = None,
    delivery_cache: WebhookDeliveryCache | None = None,
) -> FastAPI:
    """Create and configure the FastAPI GitHub App webhook server."""
    app = FastAPI(
        title="JIAN 鉴 — AI Code Reviewer GitHub App",
        description="Automated, production-ready AI Code Review bot for GitHub Pull Requests.",
        version=__version__,
    )

    auth_instance = auth or GitHubAppAuth()
    secret = webhook_secret or os.getenv("GITHUB_WEBHOOK_SECRET")
    webhook_handler = WebhookHandler(secret=secret)
    dedup_cache = delivery_cache or WebhookDeliveryCache()

    @app.get("/health", tags=["Monitoring"])
    def health_check() -> dict[str, str]:
        """Health check endpoint for container / load-balancer monitoring."""
        return {
            "status": "healthy",
            "app": "ai-github-reviewer",
            "version": __version__,
        }

    @app.post(
        "/webhooks/github",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["Webhooks"],
        summary="GitHub Webhook Receiver (Primary)",
    )
    @app.post(
        "/api/webhooks/github",
        status_code=status.HTTP_202_ACCEPTED,
        include_in_schema=False,
    )
    @app.post(
        "/webhook",
        status_code=status.HTTP_202_ACCEPTED,
        include_in_schema=False,
    )
    async def handle_github_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
        x_github_event: str | None = Header(None, alias="X-GitHub-Event"),
        x_github_delivery: str | None = Header(None, alias="X-GitHub-Delivery"),
    ) -> dict[str, Any]:
        """
        Verify GitHub signature, prevent duplicate deliveries, parse event,
        enqueue job in background, and return 202 Accepted.
        """
        raw_body = await request.body()

        # 1. Signature verification (mandatory when secret is configured)
        if webhook_handler.secret:
            if not x_hub_signature_256:
                logger.warning("Rejected webhook request: Missing X-Hub-Signature-256 header.")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing X-Hub-Signature-256 header.",
                )
            if not webhook_handler.verify_signature(raw_body, x_hub_signature_256):
                logger.warning("Rejected webhook request: Invalid HMAC signature.")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid HMAC SHA256 signature.",
                )

        # 2. Check for duplicate deliveries (e.g. GitHub retries)
        if x_github_delivery and dedup_cache.is_duplicate(x_github_delivery):
            logger.info("Ignored duplicate delivery ID: %s", x_github_delivery)
            return {
                "status": "ignored",
                "reason": "duplicate_delivery",
                "delivery_id": x_github_delivery,
            }

        # 3. Parse JSON payload
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as err:
            logger.error("Failed to parse webhook JSON payload: %s", err)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Malformed JSON payload: {err}",
            )

        # 4. Handle pull_request events
        if x_github_event == "pull_request":
            pr_event = webhook_handler.parse_pull_request_event(payload)
            if not pr_event:
                action = payload.get("action", "unknown")
                is_draft = payload.get("pull_request", {}).get("draft", False)
                logger.info("Ignored PR event (action: %s, draft: %s)", action, is_draft)
                return {"status": "ignored", "reason": f"Action '{action}' or draft PR ignored."}

            background_tasks.add_task(process_pull_request_event, pr_event, auth_instance)
            logger.info(
                "Accepted PR #%d event (%s) for %s/%s. Enqueued background review task.",
                pr_event.pr_number,
                pr_event.action,
                pr_event.repo_owner,
                pr_event.repo_name,
            )
            return {
                "status": "accepted",
                "event": "pull_request",
                "pr_number": pr_event.pr_number,
                "action": pr_event.action,
                "repository": f"{pr_event.repo_owner}/{pr_event.repo_name}",
            }

        # 5. Handle issue_comment events (for @JIAN /review, /explain, /ping, /help)
        elif x_github_event == "issue_comment":
            comment_event = webhook_handler.parse_issue_comment_event(payload)
            if not comment_event:
                action = payload.get("action", "unknown")
                logger.info("Ignored issue_comment event (action: %s)", action)
                return {"status": "ignored", "reason": f"Action '{action}' or non-issue ignored."}

            # Filter bot comments before background task
            comment_data = payload.get("comment", {})
            sender_data = payload.get("sender", {})
            if is_bot_comment(comment_data, sender_data):
                logger.info("Ignored issue_comment by bot or self: @%s", comment_event.sender_login)
                return {"status": "ignored", "reason": "bot_comment"}

            background_tasks.add_task(process_issue_comment_event, comment_event, auth_instance)
            logger.info(
                "Accepted issue_comment #%d for %s/%s. Enqueued background command task.",
                comment_event.comment_id,
                comment_event.repo_owner,
                comment_event.repo_name,
            )
            return {
                "status": "accepted",
                "event": "issue_comment",
                "comment_id": comment_event.comment_id,
                "issue_number": comment_event.issue_number,
                "is_pull_request": comment_event.is_pull_request,
                "repository": f"{comment_event.repo_owner}/{comment_event.repo_name}",
            }

        # 6. Other GitHub events (ping, installation, etc.) acknowledged with 200/202
        logger.info("Acknowledged non-target event: %s", x_github_event)
        return {"status": "ignored", "event": x_github_event or "unknown"}

    return app
