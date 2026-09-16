"""GitHub REST API client for pull requests, comments, and check runs."""

from __future__ import annotations

import base64
import os
from typing import Any

import requests

from ai_reviewer.diff import parse_patch_to_hunks
from ai_reviewer.github_comments import SUMMARY_MARKER
from ai_reviewer.models.review import ChangedFile, CheckStatusEnum


class GitHubClient:
    """Client for interacting with the GitHub REST API v3."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str = "https://api.github.com",
    ):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "AI-GitHub-Reviewer-Bot",
            }
        )
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    def get_file_content(
        self, owner: str, repo: str, path: str, ref: str | None = None
    ) -> str | None:
        """Fetch raw text content of a file from repository via GitHub API."""
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path.lstrip('/')}"
        params = {"ref": ref} if ref else {}
        try:
            res = self.session.get(url, params=params, timeout=30)
            if res.status_code == 404:
                return None
            res.raise_for_status()
            data = res.json()
            if isinstance(data, dict) and "content" in data:
                raw_b64 = data["content"]
                return base64.b64decode(raw_b64).decode("utf-8", errors="replace")
            return None
        except Exception:
            return None

    def get_pull_request(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        """Fetch pull request metadata."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pull_number}"
        res = self.session.get(url, timeout=30)
        res.raise_for_status()
        return res.json()

    def get_pull_request_files(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        head_sha: str | None = None,
        fetch_content: bool = False,
    ) -> list[ChangedFile]:
        """Fetch list of changed files with diff patches and optional file contents."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pull_number}/files"
        files: list[ChangedFile] = []
        page = 1

        while True:
            res = self.session.get(url, params={"page": page, "per_page": 100}, timeout=30)
            res.raise_for_status()
            data = res.json()
            if not data:
                break

            for item in data:
                patch_str = item.get("patch", "")
                hunks = parse_patch_to_hunks(patch_str) if patch_str else []
                is_binary = item.get("status") == "modified" and not patch_str and item.get("additions", 0) == 0

                content_after = None
                if fetch_content and head_sha and not is_binary and item.get("status") != "deleted":
                    content_after = self.get_file_content(owner, repo, item["filename"], ref=head_sha)

                cf = ChangedFile(
                    filename=item["filename"],
                    status=item.get("status", "modified"),
                    old_filename=item.get("previous_filename"),
                    additions=item.get("additions", 0),
                    deletions=item.get("deletions", 0),
                    patch=patch_str,
                    hunks=hunks,
                    is_binary=is_binary,
                    content_after=content_after,
                )
                files.append(cf)

            page += 1

        return files

    def get_existing_review_comments(self, owner: str, repo: str, pull_number: int) -> list[dict[str, Any]]:
        """Fetch existing PR review inline comments."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pull_number}/comments"
        comments: list[dict[str, Any]] = []
        page = 1

        while True:
            res = self.session.get(url, params={"page": page, "per_page": 100}, timeout=30)
            if res.status_code != 200:
                break
            data = res.json()
            if not data:
                break
            comments.extend(data)
            page += 1

        return comments

    def post_review_comments(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        commit_sha: str,
        inline_comments: list[dict[str, Any]],
        body: str | None = None,
    ) -> dict[str, Any]:
        """Create PR review comments, falling back to individual line comments on batch failure."""
        if not inline_comments and not body:
            return {}

        # Ensure side is specified for each comment
        for c in inline_comments:
            if "side" not in c:
                c["side"] = "RIGHT"

        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pull_number}/reviews"
        payload: dict[str, Any] = {
            "commit_id": commit_sha,
            "event": "COMMENT",
        }
        if body:
            payload["body"] = body
        if inline_comments:
            payload["comments"] = inline_comments

        try:
            res = self.session.post(url, json=payload, timeout=30)
            if res.status_code in (200, 201):
                return res.json()
            # If batch fails (e.g. 422), attempt individual comment fallback below
        except Exception:
            pass

        # Fallback: post comments individually so one bad line doesn't block the rest
        posted_comments = []
        indiv_url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pull_number}/comments"
        for c in inline_comments:
            indiv_payload = {
                "body": c["body"],
                "commit_id": commit_sha,
                "path": c["path"],
                "line": c["line"],
                "side": c.get("side", "RIGHT"),
            }
            try:
                indiv_res = self.session.post(indiv_url, json=indiv_payload, timeout=30)
                if indiv_res.status_code in (200, 201):
                    posted_comments.append(indiv_res.json())
            except Exception:
                pass

        return {"comments": posted_comments}

    def post_or_update_summary_comment(
        self, owner: str, repo: str, pull_number: int, summary_body: str
    ) -> dict[str, Any]:
        """Create or update existing bot summary comment on the PR discussion."""
        comments_url = f"{self.base_url}/repos/{owner}/{repo}/issues/{pull_number}/comments"
        existing_comment_id = None
        page = 1

        while True:
            res = self.session.get(comments_url, params={"page": page, "per_page": 100}, timeout=30)
            res.raise_for_status()
            comments = res.json()
            if not comments:
                break

            for comment in comments:
                if SUMMARY_MARKER in comment.get("body", ""):
                    existing_comment_id = comment["id"]
                    break

            if existing_comment_id:
                break
            page += 1

        if existing_comment_id:
            # Update existing comment
            update_url = f"{self.base_url}/repos/{owner}/{repo}/issues/comments/{existing_comment_id}"
            up_res = self.session.patch(update_url, json={"body": summary_body}, timeout=30)
            up_res.raise_for_status()
            return up_res.json()
        else:
            # Create new comment
            post_res = self.session.post(comments_url, json={"body": summary_body}, timeout=30)
            post_res.raise_for_status()
            return post_res.json()

    def create_check_run_or_status(
        self,
        owner: str,
        repo: str,
        commit_sha: str,
        status: CheckStatusEnum,
        summary: str,
        title: str = "AI Code Review",
    ) -> bool:
        """
        Create a GitHub Check Run, or fall back to Commit Status if Check Runs are unauthorized.
        """
        # Try Check Run API first
        conclusion_map = {
            CheckStatusEnum.PASS: "success",
            CheckStatusEnum.WARN: "neutral",
            CheckStatusEnum.FAIL: "failure",
            CheckStatusEnum.ERROR: "action_required",
        }
        check_url = f"{self.base_url}/repos/{owner}/{repo}/check-runs"
        check_payload = {
            "name": title,
            "head_sha": commit_sha,
            "status": "completed",
            "conclusion": conclusion_map.get(status, "neutral"),
            "output": {
                "title": f"{title} — {status.value}",
                "summary": summary[:65535],
            },
        }

        try:
            res = self.session.post(check_url, json=check_payload, timeout=30)
            if res.status_code in (200, 201):
                return True
        except Exception:
            pass

        # Fallback to Commit Status API
        state_map = {
            CheckStatusEnum.PASS: "success",
            CheckStatusEnum.WARN: "success",  # Commit status does not have neutral/warn, use success with warning desc
            CheckStatusEnum.FAIL: "failure",
            CheckStatusEnum.ERROR: "error",
        }
        status_url = f"{self.base_url}/repos/{owner}/{repo}/statuses/{commit_sha}"
        status_payload = {
            "state": state_map.get(status, "success"),
            "context": title,
            "description": f"{status.value}: {summary[:100]}",
        }
        try:
            st_res = self.session.post(status_url, json=status_payload, timeout=30)
            return st_res.status_code in (200, 201)
        except Exception as err:
            print(f"[WARN] Failed to create commit status: {err}")
            return False
