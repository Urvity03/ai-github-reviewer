"""Tests for the end-to-end ReviewOrchestrator pipeline."""

from ai_reviewer.config import AppConfig
from ai_reviewer.models.review import (
    CategoryEnum,
    ChangedFile,
    CheckStatusEnum,
    DecisionEnum,
    DiffHunk,
    ReviewContext,
    ReviewFinding,
    ReviewResult,
    SeverityEnum,
)
from ai_reviewer.providers.base import AIReviewer
from ai_reviewer.reviewer import ReviewOrchestrator


class MockAIProvider(AIReviewer):
    def __init__(self, config, findings=None, summary="Mock review summary"):
        super().__init__(config)
        self.findings = findings or []
        self.summary = summary

    def review(self, context, system_prompt, user_prompt):
        decision = DecisionEnum.REQUEST_CHANGES if any(f.severity in ("critical", "high") for f in self.findings) else DecisionEnum.APPROVE
        return ReviewResult(
            summary=self.summary,
            decision=decision,
            findings=self.findings,
        )


def test_orchestrator_clean_pr():
    cfg = AppConfig()
    provider = MockAIProvider(cfg, findings=[], summary="Code is clean and ready.")
    orchestrator = ReviewOrchestrator(config=cfg, provider=provider)

    hunk = DiffHunk(
        old_start=1, old_lines=5, new_start=1, new_lines=6, header="",
        lines=["@@ -1,5 +1,6 @@"], added_new_lines={6}, valid_new_lines={1, 2, 3, 4, 5, 6}
    )
    cf = ChangedFile(filename="src/app.py", additions=1, deletions=0, hunks=[hunk])
    ctx = ReviewContext(
        repo_owner="test", repo_name="repo", pr_number=1, pr_title="Clean PR",
        pr_description="", base_branch="main", head_branch="feat", commit_sha="123",
        changed_files=[cf]
    )

    result, status = orchestrator.run_review(ctx, dry_run=True)
    assert status == CheckStatusEnum.PASS
    assert result.decision == DecisionEnum.APPROVE
    assert len(result.findings) == 0


def test_orchestrator_fails_on_critical_finding():
    cfg = AppConfig()
    critical_finding = ReviewFinding(
        severity=SeverityEnum.CRITICAL,
        category=CategoryEnum.SECURITY,
        title="RCE vulnerability",
        description="Arbitrary code execution via eval",
        file="src/eval.py",
        line=10,
        confidence=0.98,
    )
    provider = MockAIProvider(cfg, findings=[critical_finding])
    orchestrator = ReviewOrchestrator(config=cfg, provider=provider)

    hunk = DiffHunk(
        old_start=1, old_lines=5, new_start=1, new_lines=12, header="",
        lines=["@@ -1,5 +1,12 @@"], added_new_lines={10}, valid_new_lines=set(range(1, 13))
    )
    cf = ChangedFile(filename="src/eval.py", additions=7, deletions=0, hunks=[hunk])
    ctx = ReviewContext(
        repo_owner="test", repo_name="repo", pr_number=2, pr_title="Dangerous PR",
        pr_description="", base_branch="main", head_branch="feat", commit_sha="456",
        changed_files=[cf]
    )

    result, status = orchestrator.run_review(ctx, dry_run=True)
    assert status == CheckStatusEnum.FAIL
    assert result.decision == DecisionEnum.REQUEST_CHANGES
    assert len(result.findings) == 1


class FailingAIProvider(AIReviewer):
    def review(self, context, system_prompt, user_prompt):
        raise RuntimeError("503 UNAVAILABLE: This model is currently experiencing high demand.")


def test_orchestrator_ai_provider_failure_returns_warn_and_comment():
    cfg = AppConfig()
    provider = FailingAIProvider(cfg)
    orchestrator = ReviewOrchestrator(config=cfg, provider=provider)

    hunk = DiffHunk(
        old_start=1, old_lines=5, new_start=1, new_lines=6, header="",
        lines=["@@ -1,5 +1,6 @@"], added_new_lines={6}, valid_new_lines={1, 2, 3, 4, 5, 6}
    )
    cf = ChangedFile(filename="src/app.py", additions=1, deletions=0, hunks=[hunk])
    ctx = ReviewContext(
        repo_owner="test", repo_name="repo", pr_number=3, pr_title="Test PR",
        pr_description="", base_branch="main", head_branch="feat", commit_sha="789",
        changed_files=[cf]
    )

    result, status = orchestrator.run_review(ctx, dry_run=True)
    # AI failure must never result in PASS or APPROVE
    assert status == CheckStatusEnum.WARN
    assert result.decision == DecisionEnum.COMMENT
    assert result.is_error is True
    assert "could not complete the AI analysis" in result.summary
    assert "503 UNAVAILABLE" in result.summary
    assert len(result.findings) == 0
