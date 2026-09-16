"""GitHub App authentication manager (JWT generation & installation access tokens)."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

import jwt
import requests


class GitHubAppAuth:
    """Manages GitHub App authentication: creates RS256 JWTs and exchanges them for installation tokens."""

    def __init__(
        self,
        app_id: str | int | None = None,
        private_key: str | None = None,
        base_url: str = "https://api.github.com",
    ):
        self.app_id = str(app_id or os.getenv("GITHUB_APP_ID", "")).strip()
        self.base_url = base_url.rstrip("/")
        self._raw_private_key = (
            private_key
            or os.getenv("GITHUB_PRIVATE_KEY")
            or os.getenv("GITHUB_APP_PRIVATE_KEY")
        )
        self._private_key_path = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
        # Thread-safe in-memory token cache: installation_id -> (token, expires_at_timestamp)
        self._token_cache: dict[int, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get_private_key(self) -> str:
        """Resolve private key from raw string, environment, or file path, normalizing format."""
        raw_key: str | None = None
        if self._raw_private_key:
            raw_key = self._raw_private_key.strip()
        elif self._private_key_path:
            p = Path(self._private_key_path)
            if p.is_file():
                raw_key = p.read_text(encoding="utf-8").strip()
            else:
                raise FileNotFoundError(f"GitHub App private key file not found: {self._private_key_path}")

        if not raw_key:
            raise ValueError(
                "GitHub App private key is not configured. "
                "Set GITHUB_PRIVATE_KEY, GITHUB_APP_PRIVATE_KEY, or GITHUB_APP_PRIVATE_KEY_PATH."
            )

        # Handle escaped newlines (e.g. \\n from environment variables)
        if "\\n" in raw_key:
            raw_key = raw_key.replace("\\n", "\n")

        # Handle base64 encoded private key if not starting with PEM header
        if not raw_key.startswith("-----BEGIN"):
            import base64
            try:
                decoded = base64.b64decode(raw_key).decode("utf-8")
                if "-----BEGIN" in decoded:
                    raw_key = decoded.strip()
            except Exception:
                pass

        return raw_key.strip()

    def create_jwt(self, expiration_seconds: int = 540) -> str:
        """
        Generate an RS256 JWT signed with the App's private key.
        GitHub requires JWT expiration <= 10 minutes (600s). Default is 9 mins (540s).
        """
        if not self.app_id:
            raise ValueError("GITHUB_APP_ID is not configured.")

        key = self.get_private_key()
        now = int(time.time())
        payload = {
            # Issued at time (60 seconds in the past to allow for clock drift)
            "iat": now - 60,
            # Expiration time
            "exp": now + expiration_seconds,
            # Issuer (App ID)
            "iss": self.app_id,
        }

        return jwt.encode(payload, key, algorithm="RS256")

    def get_installation_token(self, installation_id: int) -> str:
        """
        Get a short-lived installation access token for a repository installation.
        Uses in-memory cache to reuse valid tokens before expiration.
        """
        now = time.time()
        with self._lock:
            cached = self._token_cache.get(installation_id)
            # Reuse cached token if it has at least 5 minutes remaining
            if cached and cached[1] > (now + 300):
                return cached[0]

        jwt_token = self.create_jwt()
        url = f"{self.base_url}/app/installations/{installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "AI-GitHub-Reviewer-Bot",
        }

        res = requests.post(url, headers=headers, timeout=30)
        res.raise_for_status()
        data: dict[str, Any] = res.json()

        token = data["token"]
        # Default expiration is 1 hour (3600 seconds)
        expires_at_timestamp = now + 3600
        with self._lock:
            self._token_cache[installation_id] = (token, expires_at_timestamp)

        return token
