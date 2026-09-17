from __future__ import annotations

import logging
from typing import Any

from ai_reviewer.app.auth import GitHubAppAuth
from ai_reviewer.app.coordinator import PRReviewCoordinator
from ai_reviewer.app.webhook import WebhookIssueCommentEvent, WebhookPREvent
from ai_reviewer.commands import CommandDispatcher
from ai_reviewer.config import AppConfig, load_config, load_config_from_yaml
from ai_reviewer.context import ContextBuilder
from ai_reviewer.github_client import GitHubClient
from ai_reviewer.models.review import CheckStatusEnum, ReviewResult
from ai_reviewer.reviewer import ReviewOrchestrator

logger = logging.getLogger("ai_reviewer.app.service")

# Global singleton coordinator for active and completed PR review debouncing
default_coordinator = PRReviewCoordinator()


def process_pull_request_event(
    event: WebhookPREvent,
    auth: GitHubAppAuth | None = None,
    custom_config: AppConfig | None = None,
    orchestrator_override: ReviewOrchestrator | None = None,
    coordinator: PRReviewCoordinator | None = None,
) -> tuple[ReviewResult, CheckStatusEnum] | None:
    """
    Process a GitHub App pull request event:
    1. Coordinates concurrency and prevents duplicate in-flight reviews for the same commit.
    2. Obtains short-lived installation access token.
    3. Fetches PR diff, changed files, and file contents remotely.
    4. Loads repository-level .ai-reviewer.yml if present.
    5. Executes deterministic checks and AI review.
    6. Publishes inline comments, summary comment, and check run status.
    7. Provides graceful Check Run error reporting if an unexpected failure occurs.
    """
    owner = event.repo_owner
    repo = event.repo_name
    pr_num = event.pr_number
    head_sha = event.head_sha

    coord = coordinator or default_coordinator
    if not coord.should_review(owner, repo, pr_num, head_sha):
        logger.info(
            "Skipping duplicate/in-flight review for %s/%s PR #%d @ %s",
            owner,
            repo,
            pr_num,
            head_sha[:8] if len(head_sha) >= 8 else head_sha,
        )
        return None

    pr_lock = coord.get_pr_lock(owner, repo, pr_num)
    with pr_lock:
        coord.mark_started(owner, repo, pr_num, head_sha)
        gh_client: GitHubClient | None = None
        try:
            logger.info(
                "Starting background review for %s/%s PR #%d (%s) at commit %s",
                owner,
                repo,
                pr_num,
                event.action,
                head_sha[:8] if len(head_sha) >= 8 else head_sha,
            )

            # 1. Obtain installation access token
            token = None
            if auth:
                try:
                    token = auth.get_installation_token(event.installation_id)
                except Exception as err:
                    logger.error("Failed to obtain installation token for installation %d: %s", event.installation_id, err)
                    return None

            gh_client = GitHubClient(token=token)

            # 2. Check for repository configuration file in PR head commit
            app_config = custom_config
            if app_config is None:
                raw_cfg = gh_client.get_file_content(owner, repo, ".ai-reviewer.yml", ref=head_sha)
                if not raw_cfg:
                    raw_cfg = gh_client.get_file_content(owner, repo, ".github/.ai-reviewer.yml", ref=head_sha)

                if raw_cfg:
                    app_config = load_config_from_yaml(raw_cfg)
                else:
                    app_config = load_config()

            # 3. Retrieve changed files and their remote content
            changed_files = gh_client.get_pull_request_files(
                owner=owner,
                repo=repo,
                pull_number=pr_num,
                head_sha=head_sha,
                fetch_content=True,
            )

            if not changed_files:
                logger.info("No changed files found for %s/%s PR #%d. Skipping review.", owner, repo, pr_num)
                return None

            # 4. Build ReviewContext
            ctx_builder = ContextBuilder(app_config)
            context = ctx_builder.build_review_context(
                repo_owner=owner,
                repo_name=repo,
                pr_number=pr_num,
                pr_title=event.pr_title,
                pr_description=event.pr_description,
                base_branch=event.base_branch,
                head_branch=event.head_branch,
                commit_sha=head_sha,
                changed_files=changed_files,
            )

            # 5. Execute review via ReviewOrchestrator
            orchestrator = orchestrator_override or ReviewOrchestrator(
                config=app_config,
                github_client=gh_client,
            )

            result, status = orchestrator.run_review(context, dry_run=False)
            logger.info(
                "Completed review for %s/%s PR #%d: Decision=%s, Status=%s",
                owner,
                repo,
                pr_num,
                result.decision.value,
                status.value,
            )
            return result, status
        except Exception as err:
            logger.error("Error during review execution for PR #%d: %s", pr_num, err)
            if gh_client:
                try:
                    gh_client.create_check_run_or_status(
                        owner=owner,
                        repo=repo,
                        commit_sha=head_sha,
                        status=CheckStatusEnum.ERROR,
                        title="JIAN 鉴 — AI Code Review",
                        summary=(
                            f"⚠️ **JIAN Review Execution Notice**\n\n"
                            f"An unexpected error occurred during automated review of commit `{head_sha[:8]}`.\n\n"
                            f"**Error Details:** `{type(err).__name__}: {str(err)[:200]}`\n\n"
                            f"You can request a retry by commenting `@JIAN /review` on this PR."
                        ),
                    )
                except Exception:
                    pass
            return None
        finally:
            coord.mark_completed(owner, repo, pr_num, head_sha)


def process_issue_comment_event(
    event: WebhookIssueCommentEvent,
    auth: GitHubAppAuth | None = None,
    custom_config: AppConfig | None = None,
    orchestrator_override: ReviewOrchestrator | None = None,
    dispatcher_override: CommandDispatcher | None = None,
) -> dict[str, Any] | None:
    """
    Process a GitHub App issue_comment event:
    1. Obtains short-lived installation access token for the installation.
    2. Instantiates GitHubClient with that scoped installation token.
    3. Builds ReviewOrchestrator and CommandDispatcher with the scoped client.
    4. Dispatches the command (/ping, /help, /review, /explain).
    """
    owner = event.repo_owner
    repo = event.repo_name
    issue_num = event.issue_number

    logger.info(
        "Processing issue_comment event for %s/%s #%d (comment %d) by @%s",
        owner,
        repo,
        issue_num,
        event.comment_id,
        event.sender_login,
    )

    # 1. Obtain installation access token
    token = None
    if auth:
        try:
            token = auth.get_installation_token(event.installation_id)
        except Exception as err:
            logger.error(
                "Failed to obtain installation token for installation %d: %s",
                event.installation_id,
                err,
            )
            return None

    gh_client = GitHubClient(token=token)
    app_config = custom_config or load_config()

    orchestrator = orchestrator_override or ReviewOrchestrator(
        config=app_config,
        github_client=gh_client,
    )

    dispatcher = dispatcher_override or CommandDispatcher(
        config=app_config,
        github_client=gh_client,
        orchestrator=orchestrator,
    )

    try:
        result = dispatcher.handle_event(event.raw_payload)
        logger.info(
            "Command processing completed for %s/%s #%d: %s",
            owner,
            repo,
            issue_num,
            result,
        )
        return result
    except Exception as err:
        logger.error(
            "Error during command execution for %s/%s #%d: %s",
            owner,
            repo,
            issue_num,
            err,
        )
        return None
