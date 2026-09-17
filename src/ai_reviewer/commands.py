"""Interactive command dispatcher for JIAN bot mentions and slash commands."""

from __future__ import annotations

import re
from typing import Any

from ai_reviewer.config import AppConfig, load_config
from ai_reviewer.context import ContextBuilder
from ai_reviewer.github_client import GitHubClient
from ai_reviewer.reviewer import ReviewOrchestrator

COMMAND_REPLY_MARKER = "<!-- jian-command-reply -->"
BOT_LOGINS = {
    "github-actions",
    "github-actions[bot]",
    "jian",
    "jian[bot]",
    "jian-jian",
    "jian-jian[bot]",
    "jian-ai-reviewer",
    "jian-ai-reviewer[bot]",
    "jian-ai-code-reviewer",
    "jian-ai-code-reviewer[bot]",
}


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

    first_line = cleaned.splitlines()[0].strip()
    match = re.match(
        r"^(?:@(?:jian[\w\-\[\]]*|ai-reviewer[\w\-\[\]]*|bot)\s+)?/?(ping|help|review|explain)(?:\s+.*)?$",
        first_line,
        re.IGNORECASE,
    )
    if not match:
        return None

    return match.group(1).lower()


def is_bot_comment(comment_data: dict[str, Any], sender_data: dict[str, Any] | None = None) -> bool:
    """Determine whether a comment was authored by a bot or by JIAN itself."""
    user = comment_data.get("user") or {}
    user_type = user.get("type", "").lower()
    user_login = user.get("login", "").lower()

    if user_type == "bot":
        return True

    if user_login.endswith("[bot]"):
        return True

    if user_login in BOT_LOGINS:
        return True

    if sender_data:
        sender_type = sender_data.get("type", "").lower()
        sender_login = sender_data.get("login", "").lower()
        if sender_type == "bot" or sender_login.endswith("[bot]") or sender_login in BOT_LOGINS:
            return True

    # Check if comment already has our reply marker (prevent echoing)
    body = comment_data.get("body") or ""
    if COMMAND_REPLY_MARKER in body:
        return True

    return False


class CommandDispatcher:
    """Dispatches @JIAN slash commands and posts responses to GitHub."""

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
            "🏓 **Pong!** JIAN 鉴 is online, healthy, and ready to assist.\n\n"
            f"*Provider:* `{self.config.review.provider}` ({self.config.review.model})  •  "
            "Type `@JIAN /help` to see available commands."
        )
        self.github_client.create_issue_comment(owner, repo, issue_number, reply)
        return {"status": "success", "command": "ping"}

    def _handle_help(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        """Respond with available command menu."""
        reply = (
            f"{COMMAND_REPLY_MARKER}\n"
            "### 🤖 JIAN 鉴 — Interactive Commands\n\n"
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

        verdict = (
            "🟢 **SAFE TO MERGE**"
            if review_result.decision.value.lower() == "approve"
            and status.value.lower() == "passed"
            and not review_result.findings
            else "🟡 **REVIEW FINDINGS BEFORE MERGING**"
        )

        confirm_msg = (
            f"{COMMAND_REPLY_MARKER}\n"
            "🚀 **Review Triggered via JIAN 鉴!**\n\n"
            f"### {verdict}\n\n"
            f"Successfully evaluated commit `{head_sha[:8]}`.\n\n"
            f"**Summary:** {review_result.summary}\n\n"
            f"**Decision:** `{review_result.decision.value.upper()}`  \n"
            f"**Status:** `{status.value}`  \n"
            f"**Findings:** {len(review_result.findings)}\n\n"
            "The detailed review summary and inline annotations are also available above."
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
        """Explain current review findings in natural, educational language.

        First attempts to retrieve and explain findings from the existing JIAN
        summary comment.  Falls back to a live re-review only when no prior
        summary exists.
        """
        if not is_pr:
            msg = (
                f"{COMMAND_REPLY_MARKER}\n"
                "⚠️ **The `/explain` command is only supported on Pull Requests.**\n\n"
                "To explain code findings, mention `@JIAN /explain` inside a Pull Request thread."
            )
            self.github_client.create_issue_comment(owner, repo, issue_number, msg)
            return {"status": "rejected", "reason": "not_a_pull_request", "command": "explain"}

        # ── Step 1: look for an existing JIAN summary comment ─────────────────
        prior_summary = self.github_client.get_pr_review_summary_comment(
            owner, repo, issue_number
        )

        if prior_summary is not None:
            # Build explanation from the existing summary text; we don't re-review.
            reply = self._build_explain_reply_from_summary(
                prior_summary, owner, repo, issue_number
            )
            self.github_client.create_issue_comment(owner, repo, issue_number, reply)
            return {
                "status": "success",
                "command": "explain",
                "source": "prior_summary",
                "findings_explained": None,  # count not trivially parseable from markdown
            }

        # ── Step 2: no prior summary — fall back to a live review ─────────────
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
        reply = self._build_explain_reply_from_findings(
            review_result.findings, review_result.summary, head_sha, issue_number
        )
        self.github_client.create_issue_comment(owner, repo, issue_number, reply)
        return {
            "status": "success",
            "command": "explain",
            "source": "live_review",
            "findings_explained": len(review_result.findings),
        }

    # ── helpers ────────────────────────────────────────────────────────────────

    def _build_explain_reply_from_summary(
        self,
        summary_body: str,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> str:
        """Compose an /explain reply based on an existing JIAN summary comment body."""
        # Determine severity from keywords present in the summary
        body_lower = summary_body.lower()
        has_blocking = any(
            kw in body_lower
            for kw in ("🔴", "🟠", "critical", "high", "request_changes", "request changes")
        )
        has_warnings = any(
            kw in body_lower
            for kw in ("🟡", "medium", "low", "warning")
        )
        no_findings = "no findings" in body_lower or "no issues" in body_lower or (
            not has_blocking and not has_warnings
            and "finding" not in body_lower
            and "issue" not in body_lower
        )

        intro: str
        if no_findings:
            intro = (
                "✅ The latest JIAN 鉴 review found **no issues** in this Pull Request. "
                "The changes adhere to clean code standards and pass all automated checks. 🎉"
            )
        elif has_blocking:
            intro = (
                "🔴 The latest JIAN 鉴 review found **blocking findings** that should be "
                "addressed before merging. See the detailed findings below."
            )
        else:
            intro = (
                "🟡 The latest JIAN 鉴 review found **non-blocking warnings** (no blocking "
                "defects). These are worth addressing but will not block the merge."
            )

        return (
            f"{COMMAND_REPLY_MARKER}\n"
            f"### 🎓 JIAN 鉴 Explanation for PR #{issue_number}\n\n"
            f"{intro}\n\n"
            "---\n"
            "**Latest JIAN 鉴 Review Summary:**\n\n"
            f"{summary_body}\n\n"
            "---\n"
            "*To re-run the review after committing new changes, reply with `@JIAN /review`.*"
        )

    def _build_explain_reply_from_findings(
        self,
        findings: list,
        summary: str,
        head_sha: str,
        issue_number: int,
    ) -> str:
        """Compose an /explain reply from a list of ReviewFinding objects."""
        if not findings:
            return (
                f"{COMMAND_REPLY_MARKER}\n"
                "### 🎓 JIAN 鉴 Explanation\n\n"
                f"✅ No prior JIAN 鉴 review exists, so I ran a live review of commit "
                f"`{head_sha[:8]}` and found **no issues**. "
                "The changes look clean. 🎉"
            )

        # Determine overall severity
        severity_levels = [f.severity.level for f in findings]
        max_level = max(severity_levels)
        if max_level >= 4:  # HIGH or CRITICAL
            verdict = "🔴 **Blocking findings detected** — these should be resolved before merging."
        else:
            verdict = "🟡 **Non-blocking warnings** — worth addressing but not blocking the merge."

        parts = [
            f"{COMMAND_REPLY_MARKER}\n",
            f"### 🎓 JIAN 鉴 Explanation for PR #{issue_number} (`{head_sha[:8]}`)\n\n",
            f"> **Summary**: {summary}\n\n",
            f"{verdict}\n\n",
            "Here is an in-depth explanation of each finding:\n\n",
        ]
        for i, finding in enumerate(findings, 1):
            location = f"`{finding.file}:{finding.line}`" if finding.line else f"`{finding.file}`"
            parts.append(
                f"#### {i}. {finding.severity.emoji} {finding.title} ({location})\n"
                f"- **Category**: `{finding.category.display_name}`\n"
                f"- **Why this matters**: {finding.description}\n"
            )
            if finding.suggested_fix:
                parts.append(
                    f"- **Recommended Fix**:\n```python\n{finding.suggested_fix}\n```\n"
                )
            parts.append("\n")

        parts.append(
            "---\n*To re-run the review after committing changes, reply with `@JIAN /review`.*"
        )
        return "".join(parts)
