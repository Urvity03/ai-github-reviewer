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
    assert parse_command("@JIAN ping") == "ping"
    assert parse_command("/ping") == "ping"
    assert parse_command("@ai-reviewer /ping") == "ping"

    # Help variants
    assert parse_command("@JIAN /help") == "help"
    assert parse_command("@jian /help") == "help"
    assert parse_command("@JIAN help") == "help"
    assert parse_command("/help") == "help"

    # Review variants
    assert parse_command("@JIAN /review") == "review"
    assert parse_command("@jian /review") == "review"
    assert parse_command("@JIAN review") == "review"
    assert parse_command("/review") == "review"

    # Explain variants
    assert parse_command("@JIAN /explain") == "explain"
    assert parse_command("@jian /explain") == "explain"
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
    assert "Review Triggered via Command!" in body
    assert "abc12345" in body


def test_dispatcher_explain_command_on_pr():
    mock_gh = MagicMock()
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
        "comment": {"id": 1005, "body": "@JIAN /explain", "user": {"type": "User", "login": "developer"}},
        "sender": {"type": "User", "login": "developer"},
    }

    res = dispatcher.handle_event(payload)
    assert res["status"] == "success"
    assert res["command"] == "explain"
    assert res["findings_explained"] == 1

    mock_gh.create_issue_comment.assert_called_once()
    body = mock_gh.create_issue_comment.call_args[0][3]
    assert "JIAN Explanation" in body
    assert "ZeroDivisionError risk" in body
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
