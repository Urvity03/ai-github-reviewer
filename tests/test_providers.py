"""Tests for AI Reviewer provider implementations and retries."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ai_reviewer.config import AppConfig
from ai_reviewer.models.review import (
    DecisionEnum,
    ReviewContext,
    SeverityEnum,
)
from ai_reviewer.providers.openai import OpenAIReviewer


def test_openai_provider_missing_api_key():
    cfg = AppConfig()
    with pytest.raises(ValueError, match="OPENAI_API_KEY environment variable is not set"):
        OpenAIReviewer(cfg, api_key="")


@patch("ai_reviewer.providers.openai.OpenAI")
def test_openai_provider_successful_review(mock_openai_cls):
    cfg = AppConfig()
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    sample_output = {
        "summary": "Looks good with minor security concern",
        "decision": "request_changes",
        "findings": [
            {
                "severity": "high",
                "category": "security",
                "title": "SQL Injection",
                "description": "Unescaped SQL query",
                "file": "src/db.py",
                "line": 42,
                "suggested_fix": "Use parameterized query",
                "confidence": 0.95,
            }
        ],
    }

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps(sample_output)))
    ]
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    mock_client.chat.completions.create.return_value = mock_response

    reviewer = OpenAIReviewer(cfg, api_key="sk-test-mock-key")
    ctx = ReviewContext(
        repo_owner="org",
        repo_name="repo",
        pr_number=1,
        pr_title="PR",
        pr_description="",
        base_branch="main",
        head_branch="patch",
        commit_sha="abcdef",
        changed_files=[],
    )

    result = reviewer.review(ctx, "sys prompt", "user prompt")
    assert result.decision == DecisionEnum.REQUEST_CHANGES
    assert len(result.findings) == 1
    assert result.findings[0].severity == SeverityEnum.HIGH
    assert result.findings[0].file == "src/db.py"
    assert result.findings[0].line == 42


@patch("ai_reviewer.providers.openai.OpenAI")
def test_openai_provider_retry_on_malformed_json(mock_openai_cls):
    cfg = AppConfig()
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client

    # First attempt: malformed JSON; Second attempt: valid JSON
    mock_resp1 = MagicMock()
    mock_resp1.choices = [MagicMock(message=MagicMock(content="Malformed Non-JSON"))]
    mock_resp1.usage = None

    valid_json = {
        "summary": "Clean code",
        "decision": "approve",
        "findings": [],
    }
    mock_resp2 = MagicMock()
    mock_resp2.choices = [MagicMock(message=MagicMock(content=json.dumps(valid_json)))]
    mock_resp2.usage = None

    mock_client.chat.completions.create.side_effect = [mock_resp1, mock_resp2]

    reviewer = OpenAIReviewer(cfg, api_key="sk-test-mock-key")
    ctx = ReviewContext(
        repo_owner="org",
        repo_name="repo",
        pr_number=1,
        pr_title="PR",
        pr_description="",
        base_branch="main",
        head_branch="patch",
        commit_sha="abcdef",
        changed_files=[],
    )

    result = reviewer.review(ctx, "sys prompt", "user prompt")
    assert result.decision == DecisionEnum.APPROVE
    assert len(result.findings) == 0
    assert mock_client.chat.completions.create.call_count == 2
