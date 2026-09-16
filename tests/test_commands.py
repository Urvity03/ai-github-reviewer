"""Tests for interactive command parsing, bot filtering, and command dispatching."""

from unittest.mock import MagicMock

from ai_reviewer.commands import (
    COMMAND_REPLY_MARKER,
    CommandDispatcher,
    is_bot_comment,
    parse_command,
)
from ai_reviewer.config import AppConfig
from ai_reviewer.models.review import (
    CategoryEnum,
    CheckStatusEnum,
    DecisionEnum,
    ReviewFinding,
    ReviewResult,
    SeverityEnum,
)


def test_command_parsing():
    # Ping variants
    assert parse_command("@JIAN /ping") == "ping"
    assert parse_command("@jian /ping") == "ping"
    assert parse_command("@jian-jian /ping") == "ping"
    assert parse_command("@jian-jian[bot] /ping") == "ping"
    assert parse_command("@jian-ai-reviewer /ping") == "ping"
    assert parse_command("@JIAN ping") == "ping"
    assert parse_command("/ping") == "ping"
    assert parse_command("@ai-reviewer /ping") == "ping"

    # Help variants
    assert parse_command("@JIAN /help") == "help"
    assert parse_command("@jian /help") == "help"
    assert parse_command("@jian-app /help") == "help"
    assert parse_command("@JIAN help") == "help"
    assert parse_command("/help") == "help"

    # Review variants
    assert parse_command("@JIAN /review") == "review"
    assert parse_command("@jian /review") == "review"
    assert parse_command("@jian-jian[bot] /review") == "review"
    assert parse_command("@JIAN review") == "review"
    assert parse_command("/review") == "review"

    # Explain variants
    assert parse_command("@JIAN /explain") == "explain"
    assert parse_command("@jian /explain") == "explain"
    assert parse_command("@jian-jian /explain") == "explain"
    assert parse_command("@JIAN explain") == "explain"
    assert parse_command("/explain") == "explain"

    # Non-commands and unrelated text
    assert parse_command("Looks good to me, LGTM!") is None
    assert parse_command("@alice can you review this?") is None
    assert parse_command("Just fixed the bug in /routes/api.py") is None
    assert parse_command("") is None
    assert parse_command("<!-- hidden comment -->") is None


def test_bot_comment_filtering():
    # User type is Bot
    assert is_bot_comment({"user": {"type": "Bot", "login": "some-bot"}}) is True

    # User login ends with [bot]
    assert is_bot_comment({"user": {"type": "User", "login": "github-actions[bot]"}}) is True
    assert is_bot_comment({"user": {"type": "User", "login": "dependabot[bot]"}}) is True
    assert is_bot_comment({"user": {"type": "User", "login": "github-actions"}}) is True
    assert is_bot_comment({"user": {"type": "User", "login": "jian-ai-code-reviewer"}}) is True
    assert is_bot_comment({"user": {"type": "User", "login": "jian-ai-code-reviewer[bot]"}}) is True

    # Sender is Bot
    assert is_bot_comment({"user": {"type": "User", "login": "dev"}}, {"type": "Bot", "login": "bot"}) is True

    # Comment contains JIAN command reply marker
    assert is_bot_comment({"user": {"type": "User", "login": "dev"}, "body": f"{COMMAND_REPLY_MARKER} Pong!"}) is True

    # Genuine human user
    assert is_bot_comment({"user": {"type": "User", "login": "developer"}, "body": "@JIAN /ping"}) is False


def test_dispatcher_ping_command():
    mock_gh = MagicMock()
    dispatcher = CommandDispatcher(github_client=mock_gh)

    payload = {
        "repository": {"full_name": "Urvity03/ai-github-reviewer"},
        "issue": {"number": 42},
        "comment": {"id": 1001, "body": "@JIAN /ping", "user": {"type": "User", "login": "developer"}},
        "sender": {"type": "User", "login": "developer"},
    }

    res = dispatcher.handle_event(payload)
    assert res["status"] == "success"
    assert res["command"] == "ping"

    mock_gh.create_issue_comment.assert_called_once()
    args, _ = mock_gh.create_issue_comment.call_args
    assert args[0] == "Urvity03"
    assert args[1] == "ai-github-reviewer"
    assert args[2] == 42
    assert "Pong!" in args[3]
    assert COMMAND_REPLY_MARKER in args[3]


def test_dispatcher_help_command():
    mock_gh = MagicMock()
    dispatcher = CommandDispatcher(github_client=mock_gh)

    payload = {
        "repository": {"full_name": "Urvity03/ai-github-reviewer"},
        "issue": {"number": 42},
        "comment": {"id": 1002, "body": "@JIAN /help", "user": {"type": "User", "login": "developer"}},
        "sender": {"type": "User", "login": "developer"},
    }

    res = dispatcher.handle_event(payload)
    assert res["status"] == "success"
    assert res["command"] == "help"

    mock_gh.create_issue_comment.assert_called_once()
    _, body = mock_gh.create_issue_comment.call_args[0][:3], mock_gh.create_issue_comment.call_args[0][3]
    assert "/ping" in body
    assert "/review" in body
    assert "/explain" in body
    assert "/help" in body


def test_dispatcher_pr_only_commands_rejected_on_issues():
    mock_gh = MagicMock()
    dispatcher = CommandDispatcher(github_client=mock_gh)

    # Issue without pull_request object
    payload = {
        "repository": {"full_name": "Urvity03/ai-github-reviewer"},
        "issue": {"number": 10},  # Pure issue, not PR
        "comment": {"id": 1003, "body": "@JIAN /review", "user": {"type": "User", "login": "developer"}},
        "sender": {"type": "User", "login": "developer"},
    }

    res = dispatcher.handle_event(payload)
    assert res["status"] == "rejected"
    assert res["reason"] == "not_a_pull_request"

    mock_gh.create_issue_comment.assert_called_once()
    body = mock_gh.create_issue_comment.call_args[0][3]
    assert "only supported on Pull Requests" in body


def test_dispatcher_review_command_on_pr():
    mock_gh = MagicMock()
    mock_gh.get_pull_request.return_value = {
        "head": {"sha": "abc123456789", "ref": "feature-x"},
        "base": {"ref": "main"},
        "title": "Add feature X",
        "body": "PR description",
    }
    mock_gh.get_pull_request_files.return_value = []

    mock_orchestrator = MagicMock()
    mock_orchestrator.run_review.return_value = (
        ReviewResult(summary="Clean code", decision=DecisionEnum.APPROVE, findings=[]),
        CheckStatusEnum.PASS,
    )

    dispatcher = CommandDispatcher(
        config=AppConfig(), github_client=mock_gh, orchestrator=mock_orchestrator
    )

    payload = {
        "repository": {"full_name": "Urvity03/ai-github-reviewer"},
        "issue": {"number": 8, "pull_request": {"url": "https://api.github.com/..."}},
        "comment": {"id": 1004, "body": "@JIAN /review", "user": {"type": "User", "login": "developer"}},
        "sender": {"type": "User", "login": "developer"},
    }

    res = dispatcher.handle_event(payload)
    assert res["status"] == "success"
    assert res["command"] == "review"
    assert res["decision"] == "approve"

    mock_orchestrator.run_review.assert_called_once()
    mock_gh.create_issue_comment.assert_called_once()
    body = mock_gh.create_issue_comment.call_args[0][3]
    assert "Review Triggered via JIAN 鉴!" in body
    assert "abc12345" in body


def test_dispatcher_explain_reads_prior_summary_with_findings():
    """Regression: /explain must read existing JIAN summary rather than re-reviewing."""
    mock_gh = MagicMock()
    # Simulate a prior JIAN summary comment that contains medium findings
    prior_summary_body = (
        "<!-- ai-reviewer-summary -->\n"
        "## JIAN Review Summary\n\n"
        "**Decision**: REQUEST_CHANGES\n\n"
        "### Findings\n\n"
        "🟡 **Fragile ID parsing** (`examples/sample_feature.py:18`)\n"
        "- medium severity finding about regex\n\n"
        "🟡 **Missing unit tests** (`examples/sample_feature.py`)\n"
        "- medium severity finding about test coverage\n"
    )
    mock_gh.get_pr_review_summary_comment.return_value = prior_summary_body

    dispatcher = CommandDispatcher(config=AppConfig(), github_client=mock_gh)

    payload = {
        "repository": {"full_name": "Urvity03/ai-github-reviewer"},
        "issue": {"number": 1, "pull_request": {"url": "https://api.github.com/..."}},
        "comment": {"id": 2001, "body": "@JIAN /explain", "user": {"type": "User", "login": "developer"}},
        "sender": {"type": "User", "login": "developer"},
    }

    res = dispatcher.handle_event(payload)
    assert res["status"] == "success"
    assert res["command"] == "explain"
    assert res["source"] == "prior_summary"

    # Must NOT call orchestrator.run_review (no live re-review)
    # orchestrator is not injected, so any call would raise AttributeError — that
    # itself proves the live path wasn't taken; but also verify the reply is correct.
    mock_gh.create_issue_comment.assert_called_once()
    body = mock_gh.create_issue_comment.call_args[0][3]
    assert "JIAN 鉴 Explanation" in body
    assert prior_summary_body in body
    # Must NOT claim "no issues" when summary contains findings
    assert "no issues" not in body.lower() or "no issues" in prior_summary_body.lower()


def test_dispatcher_explain_blocking_severity_label():
    """Regression: /explain labels findings as blocking when HIGH/CRITICAL present."""
    mock_gh = MagicMock()
    prior_summary_body = (
        "<!-- ai-reviewer-summary -->\n"
        "## JIAN Review Summary\n\n"
        "🔴 **Critical null-pointer dereference** — high severity issue\n"
    )
    mock_gh.get_pr_review_summary_comment.return_value = prior_summary_body

    dispatcher = CommandDispatcher(config=AppConfig(), github_client=mock_gh)

    payload = {
        "repository": {"full_name": "Urvity03/ai-github-reviewer"},
        "issue": {"number": 2, "pull_request": {"url": "https://api.github.com/..."}},
        "comment": {"id": 2002, "body": "@JIAN /explain", "user": {"type": "User", "login": "dev"}},
        "sender": {"type": "User", "login": "dev"},
    }

    res = dispatcher.handle_event(payload)
    assert res["status"] == "success"
    body = mock_gh.create_issue_comment.call_args[0][3]
    # Must surface "blocking" label
    assert "blocking" in body.lower()


def test_dispatcher_explain_no_findings_in_summary():
    """Regression: /explain says 'no issues' only when the summary truly has none."""
    mock_gh = MagicMock()
    prior_summary_body = (
        "<!-- ai-reviewer-summary -->\n"
        "## JIAN Review Summary\n\n"
        "**Decision**: APPROVE\n\n"
        "No findings detected. All checks passed. ✅"
    )
    mock_gh.get_pr_review_summary_comment.return_value = prior_summary_body

    dispatcher = CommandDispatcher(config=AppConfig(), github_client=mock_gh)

    payload = {
        "repository": {"full_name": "Urvity03/ai-github-reviewer"},
        "issue": {"number": 3, "pull_request": {"url": "https://api.github.com/..."}},
        "comment": {"id": 2003, "body": "@JIAN /explain", "user": {"type": "User", "login": "dev"}},
        "sender": {"type": "User", "login": "dev"},
    }

    res = dispatcher.handle_event(payload)
    assert res["status"] == "success"
    body = mock_gh.create_issue_comment.call_args[0][3]
    assert "no issues" in body.lower()


def test_dispatcher_explain_falls_back_to_live_review_when_no_summary():
    """Regression: /explain runs live review when no prior summary comment exists."""
    mock_gh = MagicMock()
    mock_gh.get_pr_review_summary_comment.return_value = None
    mock_gh.get_pull_request.return_value = {
        "head": {"sha": "fedcba987654", "ref": "bugfix"},
        "base": {"ref": "main"},
        "title": "Fix division",
        "body": "PR description",
    }
    mock_gh.get_pull_request_files.return_value = []

    mock_orchestrator = MagicMock()
    finding = ReviewFinding(
        severity=SeverityEnum.HIGH,
        category=CategoryEnum.RELIABILITY,
        title="ZeroDivisionError risk",
        description="List is empty before dividing total by length.",
        file="src/calc.py",
        line=15,
        suggested_fix="if not values:\n    return 0.0",
    )
    mock_orchestrator.run_review.return_value = (
        ReviewResult(summary="Potential division issue", decision=DecisionEnum.REQUEST_CHANGES, findings=[finding]),
        CheckStatusEnum.FAIL,
    )

    dispatcher = CommandDispatcher(
        config=AppConfig(), github_client=mock_gh, orchestrator=mock_orchestrator
    )

    payload = {
        "repository": {"full_name": "Urvity03/ai-github-reviewer"},
        "issue": {"number": 12, "pull_request": {"url": "https://api.github.com/..."}},
        "comment": {"id": 2004, "body": "@JIAN /explain", "user": {"type": "User", "login": "developer"}},
        "sender": {"type": "User", "login": "developer"},
    }

    res = dispatcher.handle_event(payload)
    assert res["status"] == "success"
    assert res["command"] == "explain"
    assert res["source"] == "live_review"
    assert res["findings_explained"] == 1

    mock_orchestrator.run_review.assert_called_once()
    mock_gh.create_issue_comment.assert_called_once()
    body = mock_gh.create_issue_comment.call_args[0][3]
    assert "JIAN 鉴 Explanation" in body
    assert "ZeroDivisionError risk" in body
    assert "blocking" in body.lower()
    assert "Why this matters" in body
    assert "Recommended Fix" in body

def test_duplicate_comment_prevention():
    mock_gh = MagicMock()
    dispatcher = CommandDispatcher(github_client=mock_gh)

    payload = {
        "repository": {"full_name": "Urvity03/ai-github-reviewer"},
        "issue": {"number": 42},
        "comment": {"id": 5555, "body": "@JIAN /ping", "user": {"type": "User", "login": "developer"}},
        "sender": {"type": "User", "login": "developer"},
    }

    # First attempt succeeds
    res1 = dispatcher.handle_event(payload)
    assert res1["status"] == "success"
    assert mock_gh.create_issue_comment.call_count == 1

    # Second attempt with identical comment ID is ignored as duplicate
    res2 = dispatcher.handle_event(payload)
    assert res2["status"] == "ignored"
    assert res2["reason"] == "already_processed"
    assert mock_gh.create_issue_comment.call_count == 1  # No extra comment created
