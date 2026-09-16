"""Interactive command dispatcher for JIAN bot mentions and slash commands."""

from __future__ import annotations

import re
from typing import Any

from ai_reviewer.config import AppConfig, load_config
from ai_reviewer.context import ContextBuilder
from ai_reviewer.github_client import GitHubClient
from ai_reviewer.reviewer import ReviewOrchestrator

COMMAND_REPLY_MARKER = "<!-- jian-command-reply -->"
BOT_LOGINS = {"github-actions", "github-actions[bot]", "jian", "jian[bot]"}


def parse_command(text: str) -> str | None:
    """Parse mention or slash command from a comment body.

    Supports:
      @JIAN /ping, @jian /ping, @ai-reviewer /ping, /ping, @JIAN ping
      @JIAN /help, @jian /help, /help, @JIAN help
      @JIAN /review, @jian /review, /review, @JIAN review
      @JIAN /explain, @jian /explain, /explain, @JIAN explain
    """
    if not text:
        return None

    cleaned = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
    if not cleaned:
        return None

    pattern = r"^(?:@(?:jian|ai-reviewer|bot)\s+)?/?(ping|help|review|explain)(?:\s+.*)?$"
    first_line = cleaned.splitlines()[0].strip()
    match = re.search(pattern, first_line, re.IGNORECASE)
    if match:
        return match.group(1).lower()

    return None


def is_bot_comment(comment_data: dict[str, Any], sender_data: dict[str, Any] | None = None) -> bool:
    """Check if comment was authored by a bot or automated workflow to prevent recursive loops."""
    user = comment_data.get("user", {}) or {}
    user_type = (user.get("type") or "").lower()
    login = (user.get("login") or "").lower()

    if user_type == "bot" or login.endswith("[bot]") or login in BOT_LOGINS:
        return True

    if sender_data:
        s_type = (sender_data.get("type") or "").lower()
        s_login = (sender_data.get("login") or "").lower()
        if s_type == "bot" or s_login.endswith("[bot]") or s_login in BOT_LOGINS:
            return True

    # Check if comment already has our reply marker (prevent echoing)
    body = comment_data.get("body") or ""
    if COMMAND_REPLY_MARKER in body:
        return True

    return False


class CommandDispatcher:
    """Dispatches interactive bot commands on GitHub issues and pull requests."""

    def __init__(
        self,
        config: AppConfig | None = None,
        github_client: GitHubClient | None = None,
        orchestrator: ReviewOrchestrator | None = None,
    ):
        self.config = config or load_config()
        self.github_client = github_client or GitHubClient()
        self.orchestrator = orchestrator or ReviewOrchestrator(
            config=self.config, github_client=self.github_client
        )
        self._processed_comment_ids: set[int] = set()

    def handle_event(self, event_payload: dict[str, Any]) -> dict[str, Any]:
        """Process an issue_comment event payload and dispatch appropriate command."""
        comment = event_payload.get("comment", {})
        comment_id = comment.get("id")
        issue = event_payload.get("issue", {})
        repository = event_payload.get("repository", {})
        sender = event_payload.get("sender", {})

        repo_full_name = repository.get("full_name") or ""
        if "/" not in repo_full_name:
            return {"status": "error", "message": "Invalid repository name in event payload"}

        owner, repo = repo_full_name.split("/", 1)
        issue_number = issue.get("number")
        if not issue_number:
            return {"status": "error", "message": "Missing issue number in event payload"}

        # 1. Prevent duplicate execution for already handled comment ID
        if comment_id and comment_id in self._processed_comment_ids:
            return {"status": "ignored", "reason": "already_processed", "comment_id": comment_id}

        # 2. Ignore bot comments to prevent recursive loops
        if is_bot_comment(comment, sender):
            return {"status": "ignored", "reason": "bot_comment"}

        # 3. Parse command
        body = comment.get("body", "")
        cmd = parse_command(body)
        if not cmd:
            return {"status": "ignored", "reason": "no_command"}

        if comment_id:
            self._processed_comment_ids.add(comment_id)

        is_pull_request = "pull_request" in issue and bool(issue["pull_request"])

        # 4. Dispatch command
        if cmd == "ping":
            return self._handle_ping(owner, repo, issue_number)
        elif cmd == "help":
            return self._handle_help(owner, repo, issue_number)
        elif cmd == "review":
            return self._handle_review(owner, repo, issue_number, is_pull_request)
        elif cmd == "explain":
            return self._handle_explain(owner, repo, issue_number, is_pull_request)

        return {"status": "ignored", "reason": f"unrecognized_command_{cmd}"}

    def _handle_ping(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        """Respond with online health confirmation."""
        reply = (
            f"{COMMAND_REPLY_MARKER}\n"
            "🏓 **Pong!** JIAN AI Code Reviewer is online, healthy, and ready to assist.\n\n"
            f"*Provider:* `{self.config.review.provider}` ({self.config.review.model})  •  "
            "Type `@JIAN /help` to see available commands."
        )
        self.github_client.create_issue_comment(owner, repo, issue_number, reply)
        return {"status": "success", "command": "ping"}

    def _handle_help(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        """Respond with available command menu."""
        reply = (
            f"{COMMAND_REPLY_MARKER}\n"
            "### 🤖 JIAN AI Reviewer — Interactive Commands\n\n"
            "Mention `@JIAN` with any of the following commands in an issue or pull request discussion:\n\n"
            "| Command | Scope | Description |\n"
            "| :--- | :--- | :--- |\n"
            "| `@JIAN /ping` | Issues & PRs | Check if JIAN is online and responding. |\n"
            "| `@JIAN /help` | Issues & PRs | Display this help reference. |\n"
            "| `@JIAN /review` | Pull Requests only | Trigger a full automated code review on the latest PR commit. |\n"
            "| `@JIAN /explain` | Pull Requests only | Explain current review findings and suggestions in plain language. |\n\n"
            f"*AI Provider:* `Google Gemini Free Tier` (`{self.config.review.model}`)"
        )
        self.github_client.create_issue_comment(owner, repo, issue_number, reply)
        return {"status": "success", "command": "help"}

    def _handle_review(
        self, owner: str, repo: str, issue_number: int, is_pr: bool
    ) -> dict[str, Any]:
        """Trigger code review on the pull request."""
        if not is_pr:
            msg = (
                f"{COMMAND_REPLY_MARKER}\n"
                "⚠️ **The `/review` command is only supported on Pull Requests.**\n\n"
                "To review code changes, mention `@JIAN /review` inside a Pull Request thread."
            )
            self.github_client.create_issue_comment(owner, repo, issue_number, msg)
            return {"status": "rejected", "reason": "not_a_pull_request", "command": "review"}

        # Fetch PR details
        pr_data = self.github_client.get_pull_request(owner, repo, issue_number)
        head_sha = pr_data["head"]["sha"]
        base_ref = pr_data["base"]["ref"]
        head_ref = pr_data["head"]["ref"]
        pr_title = pr_data.get("title", "")
        pr_body = pr_data.get("body", "") or ""

        # Fetch changed files
        changed_files = self.github_client.get_pull_request_files(
            owner, repo, issue_number, head_sha=head_sha, fetch_content=True
        )

        builder = ContextBuilder(self.config)
        context = builder.build_review_context(
            repo_owner=owner,
            repo_name=repo,
            pr_number=issue_number,
            pr_title=pr_title,
            pr_description=pr_body,
            base_branch=base_ref,
            head_branch=head_ref,
            commit_sha=head_sha,
            changed_files=changed_files,
        )

        review_result, status = self.orchestrator.run_review(context)

        confirm_msg = (
            f"{COMMAND_REPLY_MARKER}\n"
            f"🚀 **Review Triggered via Command!**\n\n"
            f"Successfully evaluated commit `{head_sha[:8]}`.\n"
            f"- **Decision**: `{review_result.decision.value.upper()}`\n"
            f"- **Status**: `{status.value}`\n"
            f"- **Findings**: {len(review_result.findings)} issue(s) detected.\n\n"
            "See the main review summary and inline annotations for details."
        )
        self.github_client.create_issue_comment(owner, repo, issue_number, confirm_msg)

        return {
            "status": "success",
            "command": "review",
            "decision": review_result.decision.value,
            "findings_count": len(review_result.findings),
        }

    def _handle_explain(
        self, owner: str, repo: str, issue_number: int, is_pr: bool
    ) -> dict[str, Any]:
        """Explain current review findings in natural, educational language using Gemini provider."""
        if not is_pr:
            msg = (
                f"{COMMAND_REPLY_MARKER}\n"
                "⚠️ **The `/explain` command is only supported on Pull Requests.**\n\n"
                "To explain code findings, mention `@JIAN /explain` inside a Pull Request thread."
            )
            self.github_client.create_issue_comment(owner, repo, issue_number, msg)
            return {"status": "rejected", "reason": "not_a_pull_request", "command": "explain"}

        # Fetch PR details and changed files
        pr_data = self.github_client.get_pull_request(owner, repo, issue_number)
        head_sha = pr_data["head"]["sha"]
        base_ref = pr_data["base"]["ref"]
        head_ref = pr_data["head"]["ref"]
        pr_title = pr_data.get("title", "")
        pr_body = pr_data.get("body", "") or ""

        changed_files = self.github_client.get_pull_request_files(
            owner, repo, issue_number, head_sha=head_sha, fetch_content=True
        )

        builder = ContextBuilder(self.config)
        context = builder.build_review_context(
            repo_owner=owner,
            repo_name=repo,
            pr_number=issue_number,
            pr_title=pr_title,
            pr_description=pr_body,
            base_branch=base_ref,
            head_branch=head_ref,
            commit_sha=head_sha,
            changed_files=changed_files,
        )

        review_result, _ = self.orchestrator.run_review(context)

        if not review_result.findings:
            reply = (
                f"{COMMAND_REPLY_MARKER}\n"
                "### 🎓 JIAN Explanation\n\n"
                f"I reviewed commit `{head_sha[:8]}` and found **no blocking issues or defects**! "
                "The changes adhere to clean code standards and pass automated deterministic checks. 🎉"
            )
        else:
            explanation_parts = [
                f"{COMMAND_REPLY_MARKER}\n",
                f"### 🎓 JIAN Explanation for PR #{issue_number} (`{head_sha[:8]}`)\n\n",
                f"> **Summary**: {review_result.summary}\n\n",
                "Here is an in-depth explanation of the findings and recommended resolutions:\n\n",
            ]
            for i, finding in enumerate(review_result.findings, 1):
                location = f"`{finding.file}:{finding.line}`" if finding.line else f"`{finding.file}`"
                explanation_parts.append(
                    f"#### {i}. {finding.severity.emoji} {finding.title} ({location})\n"
                    f"- **Category**: `{finding.category.display_name}`\n"
                    f"- **Why this matters**: {finding.description}\n"
                )
                if finding.suggested_fix:
                    explanation_parts.append(
                        f"- **Recommended Fix**:\n```python\n{finding.suggested_fix}\n```\n"
                    )
                explanation_parts.append("\n")

            explanation_parts.append(
                "---\n*To re-run the review after committing changes, reply with `@JIAN /review`.*"
            )
            reply = "".join(explanation_parts)

        self.github_client.create_issue_comment(owner, repo, issue_number, reply)
        return {
            "status": "success",
            "command": "explain",
            "findings_explained": len(review_result.findings),
        }
