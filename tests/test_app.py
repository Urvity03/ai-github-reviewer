"""Unit and integration tests for GitHub App authentication, webhook handling, and server."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ai_reviewer.app.auth import GitHubAppAuth
from ai_reviewer.app.server import create_app
from ai_reviewer.app.service import process_pull_request_event
from ai_reviewer.app.webhook import WebhookHandler, WebhookPREvent
from ai_reviewer.models.review import (
    CheckStatusEnum,
    DecisionEnum,
    ReviewResult,
)
from ai_reviewer.reviewer import ReviewOrchestrator


@pytest.fixture(scope="module")
def rsa_test_key_pem() -> str:
    """Generate a valid RSA private key for testing RS256 JWT generation."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem_bytes.decode("utf-8")


def test_webhook_signature_verification():
    """Verify HMAC SHA-256 signature verification behavior."""
    secret = "test_webhook_secret_123"
    handler = WebhookHandler(secret=secret)

    payload = b'{"action":"opened","number":1}'
    valid_sig = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    invalid_sig = "sha256=badbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadb"

    assert handler.verify_signature(payload, valid_sig) is True
    assert handler.verify_signature(payload, invalid_sig) is False
    assert handler.verify_signature(payload, "") is False
    assert handler.verify_signature(payload, None) is False
    assert handler.verify_signature(payload, "invalid_prefix_without_sha256") is False


def test_webhook_event_parsing_and_filtering():
    """Verify filtering of pull_request actions, drafts, and required metadata."""
    handler = WebhookHandler(secret="secret")

    base_payload = {
        "action": "opened",
        "installation": {"id": 12345},
        "repository": {"name": "test-repo", "owner": {"login": "test-owner"}},
        "pull_request": {
            "number": 42,
            "title": "Add feature",
            "body": "PR description",
            "draft": False,
            "base": {"ref": "main"},
            "head": {"ref": "feature", "sha": "abc123456789"},
        },
    }

    # 1. Action: opened (valid)
    event = handler.parse_pull_request_event(base_payload)
    assert event is not None
    assert event.action == "opened"
    assert event.pr_number == 42
    assert event.installation_id == 12345
    assert event.repo_owner == "test-owner"
    assert event.repo_name == "test-repo"
    assert event.head_sha == "abc123456789"

    # 2. Action: synchronize (valid, new commit pushed)
    sync_payload = dict(base_payload)
    sync_payload["action"] = "synchronize"
    event_sync = handler.parse_pull_request_event(sync_payload)
    assert event_sync is not None
    assert event_sync.action == "synchronize"

    # 3. Action: reopened (valid)
    reopen_payload = dict(base_payload)
    reopen_payload["action"] = "reopened"
    assert handler.parse_pull_request_event(reopen_payload) is not None

    # 4. Draft PR with opened action -> MUST be ignored
    draft_payload = json.loads(json.dumps(base_payload))
    draft_payload["pull_request"]["draft"] = True
    assert handler.parse_pull_request_event(draft_payload) is None

    # 5. Draft PR becoming ready_for_review -> MUST be accepted
    ready_payload = json.loads(json.dumps(draft_payload))
    ready_payload["action"] = "ready_for_review"
    event_ready = handler.parse_pull_request_event(ready_payload)
    assert event_ready is not None
    assert event_ready.action == "ready_for_review"

    # 6. Unsupported action (e.g. labeled) -> MUST be ignored
    labeled_payload = dict(base_payload)
    labeled_payload["action"] = "labeled"
    assert handler.parse_pull_request_event(labeled_payload) is None

    # 7. Missing installation -> MUST be ignored
    no_install_payload = dict(base_payload)
    del no_install_payload["installation"]
    assert handler.parse_pull_request_event(no_install_payload) is None


def test_github_app_jwt_generation(rsa_test_key_pem):
    """Verify RS256 JWT generation using App ID and private key."""
    auth = GitHubAppAuth(app_id="123456", private_key=rsa_test_key_pem)
    jwt_str = auth.create_jwt(expiration_seconds=300)
    assert isinstance(jwt_str, str)
    assert len(jwt_str) > 20

    # Verify that JWT contains expected claims
    import jwt as pyjwt

    decoded = pyjwt.decode(jwt_str, options={"verify_signature": False})
    assert decoded["iss"] == "123456"
    assert "iat" in decoded
    assert "exp" in decoded
    assert decoded["exp"] > decoded["iat"]


@patch("requests.post")
def test_github_app_token_exchange_and_caching(mock_post, rsa_test_key_pem):
    """Verify installation token exchange and in-memory caching."""
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "token": "ghs_installation_test_token_999",
        "expires_at": "2026-09-16T12:00:00Z",
    }
    mock_resp.raise_for_status.return_value = None
    mock_post.return_value = mock_resp

    auth = GitHubAppAuth(app_id="123456", private_key=rsa_test_key_pem)

    # First fetch: calls GitHub API
    token1 = auth.get_installation_token(installation_id=777)
    assert token1 == "ghs_installation_test_token_999"
    assert mock_post.call_count == 1

    # Second fetch: reuses cached token (no extra API call)
    token2 = auth.get_installation_token(installation_id=777)
    assert token2 == "ghs_installation_test_token_999"
    assert mock_post.call_count == 1


def test_fastapi_server_endpoints():
    """Verify FastAPI server webhook receiving, signature checks, and healthcheck."""
    secret = "my_app_webhook_secret"
    app = create_app(webhook_secret=secret)
    client = TestClient(app)

    # 1. Health check
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"

    # 2. Missing signature header -> 401
    res_no_sig = client.post(
        "/api/webhooks/github",
        content=b"{}",
        headers={"X-GitHub-Event": "pull_request"},
    )
    assert res_no_sig.status_code == 401

    # 3. Invalid signature -> 401
    res_bad_sig = client.post(
        "/api/webhooks/github",
        content=b"{}",
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=invalid"},
    )
    assert res_bad_sig.status_code == 401

    # 4. Non-PR event (e.g. ping) -> 200 Accepted / Ignored
    ping_payload = b'{"zen":"Keep it logically awesome."}'
    ping_sig = "sha256=" + hmac.new(secret.encode("utf-8"), ping_payload, hashlib.sha256).hexdigest()
    res_ping = client.post(
        "/api/webhooks/github",
        content=ping_payload,
        headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": ping_sig},
    )
    assert res_ping.status_code == 202
    assert res_ping.json()["status"] == "ignored"

    # 5. Valid PR event -> 202 Accepted
    pr_payload_dict = {
        "action": "opened",
        "installation": {"id": 112233},
        "repository": {"name": "app-repo", "owner": {"login": "test-org"}},
        "pull_request": {
            "number": 10,
            "title": "New feature",
            "body": "PR description",
            "draft": False,
            "base": {"ref": "main"},
            "head": {"ref": "feature", "sha": "sha999888"},
        },
    }
    pr_payload_bytes = json.dumps(pr_payload_dict).encode("utf-8")
    pr_sig = "sha256=" + hmac.new(secret.encode("utf-8"), pr_payload_bytes, hashlib.sha256).hexdigest()

    with patch("ai_reviewer.app.server.process_pull_request_event") as mock_process:
        res_pr = client.post(
            "/api/webhooks/github",
            content=pr_payload_bytes,
            headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": pr_sig},
        )
        assert res_pr.status_code == 202
        data = res_pr.json()
        assert data["status"] == "accepted"
        assert data["pr_number"] == 10
        assert data["action"] == "opened"
        assert mock_process.called


@patch("ai_reviewer.github_client.GitHubClient.get_file_content")
@patch("ai_reviewer.github_client.GitHubClient.get_pull_request_files")
def test_service_process_pull_request_event(mock_get_files, mock_get_content):
    """Verify end-to-end background service processing for a PR event."""
    from ai_reviewer.models.review import ChangedFile, DiffHunk

    mock_get_content.return_value = None  # No custom config on remote repo, uses default
    mock_get_files.return_value = [
        ChangedFile(
            filename="src/main.py",
            status="modified",
            additions=1,
            deletions=0,
            patch="@@ -1,1 +1,2 @@\n+x = 1\n",
            hunks=[
                DiffHunk(
                    old_start=1,
                    old_lines=1,
                    new_start=1,
                    new_lines=2,
                    header="@@ -1,1 +1,2 @@",
                    valid_new_lines={1, 2},
                    added_new_lines={2},
                )
            ],
            content_after="x = 1\n",
        )
    ]

    event = WebhookPREvent(
        action="opened",
        installation_id=999,
        repo_owner="test-owner",
        repo_name="test-repo",
        pr_number=5,
        pr_title="Add variable x",
        pr_description="Simple change",
        base_branch="main",
        head_branch="patch-1",
        head_sha="commit_sha_123",
    )

    mock_auth = MagicMock(spec=GitHubAppAuth)
    mock_auth.get_installation_token.return_value = "mock_ghs_token"

    mock_orchestrator = MagicMock(spec=ReviewOrchestrator)
    mock_orchestrator.run_review.return_value = (
        ReviewResult(summary="Clean change", decision=DecisionEnum.APPROVE, findings=[]),
        CheckStatusEnum.PASS,
    )

    result, status = process_pull_request_event(
        event=event,
        auth=mock_auth,
        orchestrator_override=mock_orchestrator,
    )

    assert result is not None
    assert result.decision == DecisionEnum.APPROVE
    assert status == CheckStatusEnum.PASS
    assert mock_auth.get_installation_token.called
    assert mock_orchestrator.run_review.called
