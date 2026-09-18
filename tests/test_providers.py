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
    mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps(sample_output)))]
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


def test_gemini_provider_missing_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cfg = AppConfig()
    with pytest.raises(ValueError, match="GEMINI_API_KEY environment variable is not set"):
        from ai_reviewer.providers.gemini import GeminiReviewer

        GeminiReviewer(cfg, api_key="")


@patch("google.genai.Client")
def test_gemini_provider_successful_review(mock_genai_client_cls):
    from ai_reviewer.providers.gemini import GeminiReviewer

    cfg = AppConfig()
    mock_client = MagicMock()
    mock_genai_client_cls.return_value = mock_client

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
    mock_response.text = json.dumps(sample_output)
    mock_response.usage_metadata = MagicMock(
        prompt_token_count=80,
        candidates_token_count=45,
        total_token_count=125,
    )
    mock_client.models.generate_content.return_value = mock_response

    reviewer = GeminiReviewer(cfg, api_key="AIzaSyMockKeyForTesting")
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
    assert result.token_usage == {"prompt_tokens": 80, "completion_tokens": 45, "total_tokens": 125}


@patch("google.genai.Client")
def test_gemini_provider_retry_on_malformed_json(mock_genai_client_cls):
    from ai_reviewer.providers.gemini import GeminiReviewer

    cfg = AppConfig()
    mock_client = MagicMock()
    mock_genai_client_cls.return_value = mock_client

    mock_resp1 = MagicMock()
    mock_resp1.text = "Not a valid JSON"
    mock_resp1.usage_metadata = None

    valid_json = {
        "summary": "Clean code",
        "decision": "approve",
        "findings": [],
    }
    mock_resp2 = MagicMock()
    mock_resp2.text = json.dumps(valid_json)
    mock_resp2.usage_metadata = None

    mock_client.models.generate_content.side_effect = [mock_resp1, mock_resp2]

    reviewer = GeminiReviewer(cfg, api_key="AIzaSyMockKeyForTesting")
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
    assert mock_client.models.generate_content.call_count == 2


def test_extract_retry_delay_from_various_sources():
    from google.genai.errors import ClientError

    from ai_reviewer.providers.gemini import extract_retry_delay

    # 1. Structured details with retryDelay
    err_dict = {
        "error": {
            "code": 429,
            "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "25s"}],
        }
    }
    client_err = ClientError(429, response_json=err_dict)
    assert extract_retry_delay(client_err) == 25.0

    # 2. HTTP response header
    mock_resp = MagicMock()
    mock_resp.headers = {"Retry-After": "15"}
    client_err_header = ClientError(429, response_json={})
    client_err_header.response = mock_resp
    assert extract_retry_delay(client_err_header) == 15.0

    # 3. String regex fallback
    generic_err = Exception("Quota exceeded. Please retry in 32.5s.")
    assert extract_retry_delay(generic_err) == 32.5

    # 4. No delay present
    no_delay_err = Exception("Internal server error")
    assert extract_retry_delay(no_delay_err) is None


def test_is_transient_error_classification():
    from google.genai.errors import ClientError, ServerError

    from ai_reviewer.providers.gemini import is_transient_error

    # Transient errors
    assert (
        is_transient_error(
            ServerError(503, response_json={"error": {"code": 503, "status": "UNAVAILABLE"}})
        )
        is True
    )
    assert (
        is_transient_error(
            ClientError(429, response_json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}})
        )
        is True
    )
    assert (
        is_transient_error(
            ServerError(500, response_json={"error": {"code": 500, "status": "INTERNAL"}})
        )
        is True
    )
    assert is_transient_error(ServerError(502, response_json={"error": {"code": 502}})) is True
    assert is_transient_error(ServerError(504, response_json={"error": {"code": 504}})) is True
    assert is_transient_error(TimeoutError("Connection timed out")) is True
    assert is_transient_error(ConnectionError("Connection reset by peer")) is True
    assert (
        is_transient_error(
            Exception("503 UNAVAILABLE: This model is currently experiencing high demand")
        )
        is True
    )

    # Non-transient errors (fail fast)
    assert (
        is_transient_error(
            ClientError(400, response_json={"error": {"code": 400, "status": "INVALID_ARGUMENT"}})
        )
        is False
    )
    assert (
        is_transient_error(
            ClientError(401, response_json={"error": {"code": 401, "status": "UNAUTHENTICATED"}})
        )
        is False
    )
    assert (
        is_transient_error(
            ClientError(403, response_json={"error": {"code": 403, "status": "PERMISSION_DENIED"}})
        )
        is False
    )
    assert (
        is_transient_error(
            ClientError(404, response_json={"error": {"code": 404, "status": "NOT_FOUND"}})
        )
        is False
    )
    assert (
        is_transient_error(
            Exception("API_KEY_INVALID: API key not valid. Please pass a valid API key.")
        )
        is False
    )


def test_compute_backoff_delay_behavior():
    from ai_reviewer.providers.gemini import compute_backoff_delay

    # Server delay respected with small jitter
    server_delay = 20.0
    delay = compute_backoff_delay(1, server_delay=server_delay)
    assert 20.5 <= delay <= 22.0

    # Exponential backoff without server delay
    d1 = compute_backoff_delay(1)
    assert 5.0 <= d1 <= 10.0

    d2 = compute_backoff_delay(2)
    assert 10.0 <= d2 <= 20.0

    d3 = compute_backoff_delay(3)
    assert 20.0 <= d3 <= 40.0

    d4 = compute_backoff_delay(4)
    assert 40.0 <= d4 <= 60.0


@patch("time.sleep")
@patch("google.genai.Client")
def test_gemini_provider_retries_on_503_and_succeeds(mock_genai_client_cls, mock_sleep):
    from google.genai.errors import ServerError

    from ai_reviewer.providers.gemini import GeminiReviewer

    cfg = AppConfig()
    mock_client = MagicMock()
    mock_genai_client_cls.return_value = mock_client

    err_503 = ServerError(
        503,
        response_json={"error": {"code": 503, "message": "High demand", "status": "UNAVAILABLE"}},
    )

    valid_json = {
        "summary": "Recovered after 503",
        "decision": "approve",
        "findings": [],
    }
    mock_resp_success = MagicMock()
    mock_resp_success.text = json.dumps(valid_json)
    mock_resp_success.usage_metadata = None

    mock_client.models.generate_content.side_effect = [err_503, mock_resp_success]

    reviewer = GeminiReviewer(cfg, api_key="AIzaSyMockKeyForTesting")
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
    assert result.summary == "Recovered after 503"
    assert mock_client.models.generate_content.call_count == 2
    assert mock_sleep.call_count == 1
    # First attempt wait should be roughly 5-10s
    slept = mock_sleep.call_args[0][0]
    assert 5.0 <= slept <= 10.0


@patch("time.sleep")
@patch("google.genai.Client")
def test_gemini_provider_retries_on_429_with_server_delay(mock_genai_client_cls, mock_sleep):
    from google.genai.errors import ClientError

    from ai_reviewer.providers.gemini import GeminiReviewer

    cfg = AppConfig()
    mock_client = MagicMock()
    mock_genai_client_cls.return_value = mock_client

    err_429 = ClientError(
        429,
        response_json={
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "24s"}
                ],
            }
        },
    )

    valid_json = {
        "summary": "Recovered after 429 with delay",
        "decision": "approve",
        "findings": [],
    }
    mock_resp_success = MagicMock()
    mock_resp_success.text = json.dumps(valid_json)
    mock_resp_success.usage_metadata = None

    mock_client.models.generate_content.side_effect = [err_429, mock_resp_success]

    reviewer = GeminiReviewer(cfg, api_key="AIzaSyMockKeyForTesting")
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
    assert mock_client.models.generate_content.call_count == 2
    assert mock_sleep.call_count == 1
    slept = mock_sleep.call_args[0][0]
    # Server requested 24s, with jitter should be 24.5 - 26s
    assert 24.5 <= slept <= 26.5


@patch("time.sleep")
@patch("google.genai.Client")
def test_gemini_provider_fails_fast_on_non_transient_401(mock_genai_client_cls, mock_sleep):
    from google.genai.errors import ClientError

    from ai_reviewer.providers.gemini import GeminiReviewer

    cfg = AppConfig()
    mock_client = MagicMock()
    mock_genai_client_cls.return_value = mock_client

    err_401 = ClientError(
        401,
        response_json={
            "error": {"code": 401, "message": "API key not valid", "status": "UNAUTHENTICATED"}
        },
    )
    mock_client.models.generate_content.side_effect = err_401

    reviewer = GeminiReviewer(cfg, api_key="AIzaSyMockKeyForTesting")
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

    with pytest.raises(RuntimeError, match="Gemini review failed after 4 attempts"):
        reviewer.review(ctx, "sys prompt", "user prompt")

    # Fail fast: only 1 attempt made, 0 sleeps
    assert mock_client.models.generate_content.call_count == 1
    assert mock_sleep.call_count == 0


@patch("time.sleep")
@patch("google.genai.Client")
def test_gemini_provider_all_transient_retries_fail_raises_runtime_error(
    mock_genai_client_cls, mock_sleep
):
    from google.genai.errors import ServerError

    from ai_reviewer.providers.gemini import GeminiReviewer

    cfg = AppConfig()
    mock_client = MagicMock()
    mock_genai_client_cls.return_value = mock_client

    err_503 = ServerError(
        503,
        response_json={
            "error": {"code": 503, "message": "Model overloaded", "status": "UNAVAILABLE"}
        },
    )
    mock_client.models.generate_content.side_effect = err_503

    reviewer = GeminiReviewer(cfg, api_key="AIzaSyMockKeyForTesting")
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

    with pytest.raises(RuntimeError, match="Gemini review failed after 4 attempts"):
        reviewer.review(ctx, "sys prompt", "user prompt")

    # Budget of 4 attempts, 3 sleeps between attempts
    assert mock_client.models.generate_content.call_count == 4
    assert mock_sleep.call_count == 3
