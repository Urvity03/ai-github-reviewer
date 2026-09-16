"""Tests for GitHub REST API client."""

from unittest.mock import MagicMock, patch

from ai_reviewer.github_client import GitHubClient
from ai_reviewer.github_comments import SUMMARY_MARKER
from ai_reviewer.models.review import CheckStatusEnum


def test_github_client_init():
    client = GitHubClient(token="ghp_mocktoken")
    assert client.token == "ghp_mocktoken"
    assert "Bearer ghp_mocktoken" in client.session.headers["Authorization"]


@patch("requests.Session.get")
def test_get_pull_request(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"number": 12, "title": "Test PR", "body": "PR description"}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    client = GitHubClient(token="mock")
    pr = client.get_pull_request("owner", "repo", 12)
    assert pr["number"] == 12
    assert pr["title"] == "Test PR"


@patch("requests.Session.get")
@patch("requests.Session.patch")
def test_post_or_update_summary_comment_updates_existing(mock_patch, mock_get):
    # Mock finding existing comment
    mock_get_resp = MagicMock()
    mock_get_resp.json.return_value = [
        {"id": 101, "body": "Regular user comment"},
        {"id": 102, "body": f"Old review\n{SUMMARY_MARKER}"},
    ]
    mock_get_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_get_resp

    mock_patch_resp = MagicMock()
    mock_patch_resp.json.return_value = {"id": 102, "body": f"Updated review\n{SUMMARY_MARKER}"}
    mock_patch_resp.raise_for_status.return_value = None
    mock_patch.return_value = mock_patch_resp

    client = GitHubClient(token="mock")
    res = client.post_or_update_summary_comment("owner", "repo", 1, f"Updated review\n{SUMMARY_MARKER}")

    assert res["id"] == 102
    assert mock_patch.called


@patch("requests.Session.post")
def test_create_check_run_fallback_to_status(mock_post):
    # First post (check-runs) returns 403 (unauthorized)
    mock_check_resp = MagicMock(status_code=403)
    # Second post (statuses) returns 201 (success)
    mock_status_resp = MagicMock(status_code=201)
    mock_post.side_effect = [mock_check_resp, mock_status_resp]

    client = GitHubClient(token="mock")
    ok = client.create_check_run_or_status("owner", "repo", "sha123", CheckStatusEnum.PASS, "All clear")
    assert ok is True
    assert mock_post.call_count == 2
