"""Main review orchestrator coordinating diffs, checks, AI engine, and GitHub."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from ai_reviewer.config import AppConfig, load_config
from ai_reviewer.diff import is_line_in_diff, snap_finding_line
from ai_reviewer.github_client import GitHubClient
from ai_reviewer.github_comments import format_inline_comment, format_summary_comment
from ai_reviewer.ml_analysis import is_ml_related_file, run_heuristic_ml_checks
from ai_reviewer.models.review import (
    CheckStatusEnum,
    DecisionEnum,
    ReviewContext,
    ReviewFinding,
    ReviewResult,
    SeverityEnum,
)
from ai_reviewer.providers.base import AIReviewer
from ai_reviewer.providers.gemini import GeminiReviewer
from ai_reviewer.providers.openai import OpenAIReviewer
from ai_reviewer.rules import build_system_prompt, build_user_prompt
from ai_reviewer.static_analysis import run_all_deterministic_checks
from ai_reviewer.validation import FindingValidator

console = Console()


class ReviewOrchestrator:
    """End-to-end pipeline orchestrating deterministic checks, AI review, and GitHub reporting."""

    def __init__(
        self,
        config: AppConfig | None = None,
        provider: AIReviewer | None = None,
        github_client: GitHubClient | None = None,
        repo_root: Path | None = None,
    ):
        self.config = config or load_config()
        self.repo_root = repo_root or Path.cwd()
        self.github_client = github_client or GitHubClient()
        self.provider = provider

    def _get_provider(self) -> AIReviewer:
        if self.provider:
            return self.provider
        prov_name = self.config.review.provider.lower()
        if prov_name == "gemini":
            return GeminiReviewer(self.config)
        elif prov_name == "openai":
            return OpenAIReviewer(self.config)
        raise ValueError(f"Unsupported AI provider: {prov_name}. Supported providers: ['gemini', 'openai']")

    def run_review(
        self,
        context: ReviewContext,
        dry_run: bool = False,
    ) -> tuple[ReviewResult, CheckStatusEnum]:
        """Execute the full review pipeline."""
        console.print(f"[bold blue]Starting review for PR #{context.pr_number}: {context.pr_title}[/bold blue]")

        all_findings: list[ReviewFinding] = []

        # 1. Run deterministic checks
        console.print("[dim]Executing deterministic checks (compile check, secret scanner, ruff, pytest)...[/dim]")
        det_results = run_all_deterministic_checks(
            context.changed_files, self.config, self.repo_root
        )
        context.deterministic_results = det_results

        for det in det_results:
            all_findings.extend(det.findings)

        # 2. Heuristic ML checks on modified files
        if self.config.rules.ml:
            for cf in context.changed_files:
                if cf.filename.endswith(".py") and cf.content_after:
                    if is_ml_related_file(cf.filename, cf.content_after):
                        ml_findings = run_heuristic_ml_checks(cf.filename, cf.content_after)
                        all_findings.extend(ml_findings)

        # 3. Check for size limits / truncation
        ai_result: ReviewResult | None = None
        if context.truncated:
            console.print(f"[bold yellow]PR exceeds configured limits:[/bold yellow] {context.truncation_reason}")
            ai_result = ReviewResult(
                summary=(
                    f"Automated review skipped for AI analysis because {context.truncation_reason} "
                    "Deterministic checks were executed."
                ),
                decision=DecisionEnum.COMMENT,
                findings=[],
            )
        elif self.config.review.enabled:
            try:
                provider = self._get_provider()
                system_prompt = build_system_prompt(self.config)
                user_prompt = build_user_prompt(context)

                console.print("[dim]Querying AI provider with structured output...[/dim]")
                ai_result = provider.review(context, system_prompt, user_prompt)
                all_findings.extend(ai_result.findings)
            except Exception as err:
                console.print(f"[bold red]AI Reviewer Provider Error:[/bold red] {err}")
                err_msg = str(err).strip()
                import re
                err_msg = re.sub(r"(key|token|auth)=([A-Za-z0-9_\-]+)", r"\1=[REDACTED]", err_msg, flags=re.IGNORECASE)
                err_summary = err_msg.splitlines()[0] if err_msg else "Unknown provider error"
                if len(err_summary) > 200:
                    err_summary = err_summary[:197] + "..."
                ai_result = ReviewResult(
                    summary=(
                        f"JIAN 鉴 could not complete the AI analysis because the configured AI provider was temporarily unavailable. "
                        f"Deterministic checks that completed are reported below. This result should not be interpreted as an all-clear AI review. "
                        f"Error: {err_summary}"
                    ),
                    decision=DecisionEnum.COMMENT,
                    findings=[],
                    is_error=True,
                    error_message=err_summary,
                )
        else:
            ai_result = ReviewResult(
                summary="AI review is disabled in repository configuration.",
                decision=DecisionEnum.COMMENT,
                findings=[],
            )

        # 4. Anti-hallucination validation & deduplication
        validator = FindingValidator(self.config, context.changed_files, self.repo_root)
        valid_findings, rejection_reasons = validator.validate_and_filter(all_findings)

        for reason in rejection_reasons:
            console.print(f"[dim yellow]Validation Filter: {reason}[/dim yellow]")

        # 5. Determine overall check status
        ai_failed = bool(ai_result and ai_result.is_error)
        check_status = CheckStatusEnum.WARN if ai_failed else CheckStatusEnum.PASS
        if any(self.config.should_fail_on(f.severity) for f in valid_findings):
            check_status = CheckStatusEnum.FAIL
        elif any(f.severity == SeverityEnum.MEDIUM for f in valid_findings):
            check_status = CheckStatusEnum.WARN

        # Update review result summary if needed
        final_summary = ai_result.summary if ai_result else "Review completed."
        if context.truncated or ai_failed:
            final_decision = (
                DecisionEnum.REQUEST_CHANGES
                if check_status == CheckStatusEnum.FAIL
                else DecisionEnum.COMMENT
            )
        else:
            final_decision = (
                DecisionEnum.REQUEST_CHANGES
                if check_status == CheckStatusEnum.FAIL
                else (DecisionEnum.APPROVE if check_status == CheckStatusEnum.PASS and not valid_findings else DecisionEnum.COMMENT)
            )

        final_result = ReviewResult(
            summary=final_summary,
            decision=final_decision,
            findings=valid_findings,
            token_usage=ai_result.token_usage if ai_result else None,
            is_error=ai_failed,
            error_message=ai_result.error_message if ai_result else None,
        )

        # 6. Report to GitHub (if not dry-run and GitHub token provided)
        if dry_run or not self.github_client.token:
            console.print("[green]Dry run mode or no GITHUB_TOKEN: Skipping GitHub API comment publishing.[/green]")
            return final_result, check_status

        self._publish_github_feedback(context, final_result, check_status)
        return final_result, check_status

    def _publish_github_feedback(
        self,
        context: ReviewContext,
        result: ReviewResult,
        status: CheckStatusEnum,
    ) -> None:
        """Publish inline comments, summary comment, and check run / status to GitHub."""
        owner = context.repo_owner
        repo = context.repo_name
        pr_number = context.pr_number
        commit_sha = context.commit_sha

        # Separate inline-eligible findings vs unattached
        files_map = {f.filename.replace("\\", "/"): f for f in context.changed_files}
        inline_payloads: list[dict] = []
        unattached_findings: list[ReviewFinding] = []

        # Fetch existing comments to avoid duplicate inline comments across commits
        existing_comments = self.github_client.get_existing_review_comments(owner, repo, pr_number)
        existing_keys = {
            f"{c.get('path')}:{c.get('line') or c.get('original_line')}"
            for c in existing_comments
        }

        for finding in result.findings:
            norm_file = finding.file.replace("\\", "/").lstrip("./")
            cf = files_map.get(norm_file)
            can_inline = (
                finding.line is not None
                and cf is not None
                and is_line_in_diff(cf, finding.line)
                and self.config.should_post_inline(finding.severity)
            )

            if can_inline:
                # Snap to nearest non-blank added line to avoid commenting on
                # trailing blank lines when the AI reports a slightly off line.
                target_line = snap_finding_line(cf, finding.line)
                key = f"{norm_file}:{target_line}"
                if key not in existing_keys:
                    inline_payloads.append(
                        {
                            "path": norm_file,
                            "line": target_line,
                            "side": "RIGHT",
                            "body": format_inline_comment(finding),
                        }
                    )
            else:
                unattached_findings.append(finding)

        # 1. Post batch inline review comments if any
        if inline_payloads:
            try:
                console.print(f"Posting {len(inline_payloads)} inline review comment(s)...")
                self.github_client.post_review_comments(
                    owner=owner,
                    repo=repo,
                    pull_number=pr_number,
                    commit_sha=commit_sha,
                    inline_comments=inline_payloads,
                )
            except Exception as err:
                console.print(f"[bold red]Failed to post inline comments:[/bold red] {err}")
                # Fallback: present all findings in summary if inline posting failed
                unattached_findings = list(result.findings)

        # 2. Post or update the summary comment
        summary_markdown = format_summary_comment(
            result=result,
            deterministic_results=context.deterministic_results,
            commit_sha=commit_sha,
            unattached_findings=unattached_findings,
            check_status=status,
        )
        try:
            console.print("Updating bot summary comment on PR...")
            self.github_client.post_or_update_summary_comment(
                owner=owner,
                repo=repo,
                pull_number=pr_number,
                summary_body=summary_markdown,
            )
        except Exception as err:
            console.print(f"[bold red]Failed to update summary comment:[/bold red] {err}")

        # 3. Create Check Run or Commit Status
        try:
            console.print(f"Setting GitHub Check status: {status.value}...")
            self.github_client.create_check_run_or_status(
                owner=owner,
                repo=repo,
                commit_sha=commit_sha,
                status=status,
                summary=result.summary,
            )
        except Exception as err:
            console.print(f"[bold red]Failed to set check run:[/bold red] {err}")
