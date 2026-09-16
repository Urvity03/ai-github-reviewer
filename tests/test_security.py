"""Tests for secret detection, credential pattern scanning, and redaction."""

from ai_reviewer.models.review import CategoryEnum, SeverityEnum
from ai_reviewer.security import redact_secret, scan_file_content_for_secrets


def test_secret_detection_finds_real_keys():
    malicious_code = """
import os

AWS_KEY = "AKIA1234567890ABCDEF"
GITHUB_KEY = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
OPENAI_KEY = "sk-1234567890abcdef1234567890abcdef"
"""
    findings = scan_file_content_for_secrets("src/config.py", malicious_code)
    assert len(findings) == 3
    for f in findings:
        assert f.category == CategoryEnum.SECURITY
        assert f.severity == SeverityEnum.CRITICAL
        assert f.file == "src/config.py"


def test_secret_detection_ignores_placeholders():
    clean_code = """
OPENAI_KEY = "your-key-here"
AWS_KEY = "dummy-aws-token"
EXAMPLE = "example_secret_token"
"""
    findings = scan_file_content_for_secrets("src/example.py", clean_code)
    assert len(findings) == 0


def test_redact_secret():
    raw = "Found token: AKIA1234567890ABCDEF in production"
    redacted = redact_secret(raw)
    assert "AKIA1234567890ABCDEF" not in redacted
    assert "[REDACTED AWS Access Key ID]" in redacted
