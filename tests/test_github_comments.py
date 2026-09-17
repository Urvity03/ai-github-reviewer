"""Tests for GitHub comment formatting."""

from ai_reviewer.github_comments import (
    SUMMARY_MARKER,
    format_inline_comment,
    format_summary_comment,
)
from ai_reviewer.models.review import (
    CategoryEnum,
    CheckStatusEnum,
    DecisionEnum,
    DeterministicCheckResult,
    ReviewFinding,
    ReviewResult,
    SeverityEnum,
)


def test_format_inline_comment():
    finding = ReviewFinding(
        severity=SeverityEnum.HIGH,
        category=CategoryEnum.SECURITY,
        title="Unsanitized Subprocess Input",
        description="Shell injection risk",
        file="src/sh.py",
        line=42,
        suggested_fix="subprocess.run(['ls', arg], check=True)",
        confidence=0.95,
    )
    text = format_inline_comment(finding)
    assert "🔴 **HIGH — Security**" in text
    assert "Unsanitized Subprocess Input" in text
    assert "```suggestion" in text
    assert "subprocess.run(['ls', arg], check=True)" in text


def test_format_summary_comment():
    result = ReviewResult(
        summary="PR contains 1 critical issue and 1 low issue.",
        decision=DecisionEnum.REQUEST_CHANGES,
        findings=[
            ReviewFinding(
                severity=SeverityEnum.CRITICAL,
                category=CategoryEnum.SECURITY,
                title="Private Key in Repository",
                description="RSA private key committed",
                file="certs/id_rsa",
                line=1,
                confidence=1.0,
            ),
            ReviewFinding(
                severity=SeverityEnum.LOW,
                category=CategoryEnum.MAINTAINABILITY,
                title="Variable naming",
                description="Use snake_case",
                file="src/foo.py",
                line=5,
                confidence=0.8,
            ),
        ],
    )
    det_checks = [
        DeterministicCheckResult(name="Python Syntax Check", status="passed", details="Valid", findings=[]),
        DeterministicCheckResult(name="Secret Scanner", status="failed", details="Key found", findings=[]),
    ]

    summary_text = format_summary_comment(
        result=result,
        deterministic_results=det_checks,
        commit_sha="abcdef123456789",
        unattached_findings=[],
        check_status=CheckStatusEnum.FAIL,
    )

    assert SUMMARY_MARKER in summary_text
    assert "❌ **Changes Requested / Check Failed**" in summary_text
    assert "🛑 1 Critical" in summary_text
    assert "🔵 1 Low" in summary_text
    assert "Private Key in Repository" in summary_text
    assert "Secret Scanner" in summary_text
    assert "Reviewed commit: `abcdef12`" in summary_text


def test_format_summary_comment_on_ai_failure():
    result = ReviewResult(
        summary="JIAN 鉴 could not complete the AI analysis because the configured AI provider was temporarily unavailable. Deterministic checks that completed are reported below. This result should not be interpreted as an all-clear AI review. Error: 503 UNAVAILABLE",
        decision=DecisionEnum.COMMENT,
        findings=[],
        is_error=True,
        error_message="503 UNAVAILABLE",
    )
    det_checks = [
        DeterministicCheckResult(name="Python Syntax Check", status="passed", details="Valid", findings=[]),
    ]

    summary_text = format_summary_comment(
        result=result,
        deterministic_results=det_checks,
        commit_sha="abcdef123456789",
        unattached_findings=[],
        check_status=CheckStatusEnum.WARN,
    )

    # Must display incomplete warning
    assert "⚠️ **AI Analysis Incomplete**" in summary_text
    # Must NOT emit all-clear or clean code celebrations
    assert "✅ **All Checks Passed**" not in summary_text
    assert "🎉 No issues identified! Code is clean." not in summary_text
    # Must inform that deterministic checks completed and no deterministic issues were found
    assert "⚠️ AI analysis could not be completed. No deterministic issues identified." in summary_text
    assert "Python Syntax Check" in summary_text
    assert "✅ Passed" in summary_text


def test_format_summary_comment_clean_review():
    result = ReviewResult(
        summary="All code looks good!",
        decision=DecisionEnum.APPROVE,
        findings=[],
        is_error=False,
    )
    det_checks = [
        DeterministicCheckResult(name="Python Syntax Check", status="passed", details="Valid", findings=[]),
    ]

    summary_text = format_summary_comment(
        result=result,
        deterministic_results=det_checks,
        commit_sha="abcdef123456789",
        unattached_findings=[],
        check_status=CheckStatusEnum.PASS,
    )

    assert "✅ **All Checks Passed**" in summary_text
    assert "🎉 No issues identified! Code is clean." in summary_text
