"""FastAPI webhook server for GitHub App."""

from __future__ import annotations

import json
import logging
import os

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, status

from ai_reviewer import __version__
from ai_reviewer.app.auth import GitHubAppAuth
from ai_reviewer.app.service import process_pull_request_event
from ai_reviewer.app.webhook import WebhookHandler

logger = logging.getLogger("ai_reviewer.app.server")


def create_app(
    auth: GitHubAppAuth | None = None,
    webhook_secret: str | None = None,
) -> FastAPI:
    """Create and configure the FastAPI GitHub App webhook server."""
    app = FastAPI(
        title="AI Pull Request Reviewer GitHub App",
        description="Automated, production-ready AI Code Review bot for GitHub Pull Requests.",
        version=__version__,
    )

    auth_instance = auth or GitHubAppAuth()
    secret = webhook_secret or os.getenv("GITHUB_WEBHOOK_SECRET")
    webhook_handler = WebhookHandler(secret=secret)

    @app.get("/health", tags=["Monitoring"])
    def health_check() -> dict[str, str]:
        """Health check endpoint for container / load-balancer monitoring."""
        return {
            "status": "healthy",
            "app": "ai-github-reviewer",
            "version": __version__,
        }

    @app.post(
        "/api/webhooks/github",
        status_code=status.HTTP_202_ACCEPTED,
        tags=["Webhooks"],
        summary="GitHub Webhook Receiver",
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
    ) -> dict[str, str | int]:
        """
        Verify GitHub signature, parse event, enqueue review job in background, and return 202 Accepted.
        """
        raw_body = await request.body()

        # 1. Signature verification (mandatory in production)
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

        # 2. Filter event type
        if x_github_event != "pull_request":
            # GitHub sends ping, installation, etc. We acknowledge with 200 OK
            return {"status": "ignored", "event": x_github_event or "unknown"}

        # 3. Parse JSON payload
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as err:
            logger.error("Failed to parse webhook JSON payload: %s", err)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Malformed JSON payload: {err}",
            )

        # 4. Filter pull_request action and draft status
        event = webhook_handler.parse_pull_request_event(payload)
        if not event:
            action = payload.get("action", "unknown")
            is_draft = payload.get("pull_request", {}).get("draft", False)
            logger.info("Ignored PR event (action: %s, draft: %s)", action, is_draft)
            return {"status": "ignored", "reason": f"Action '{action}' or draft PR ignored."}

        # 5. Enqueue background review execution
        background_tasks.add_task(process_pull_request_event, event, auth_instance)

        logger.info(
            "Accepted PR #%d event (%s) for %s/%s. Enqueued background review task.",
            event.pr_number,
            event.action,
            event.repo_owner,
            event.repo_name,
        )
        return {
            "status": "accepted",
            "pr_number": event.pr_number,
            "action": event.action,
            "repository": f"{event.repo_owner}/{event.repo_name}",
        }

    return app
