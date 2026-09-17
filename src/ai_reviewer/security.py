"""Security scanning, secret detection, and credential sanitization."""

from __future__ import annotations

import re

from ai_reviewer.models.review import CategoryEnum, ReviewFinding, SeverityEnum

# Regex patterns for detecting sensitive credentials
SECRET_PATTERNS = [
    (
        "Private Key",
        re.compile(r"-----BEGIN\s+(?:RSA|DSA|EC|OPENSSH|PGP)?\s*PRIVATE KEY-----"),
        SeverityEnum.CRITICAL,
    ),
    (
        "AWS Access Key ID",
        re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
        SeverityEnum.CRITICAL,
    ),
    (
        "GitHub Token",
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{36,255}|github_pat_[A-Za-z0-9_]{82})\b"),
        SeverityEnum.CRITICAL,
    ),
    (
        "OpenAI API Key",
        re.compile(r"\b(sk-[A-Za-z0-9]{32,}|sk-proj-[A-Za-z0-9\-_]{64,})\b"),
        SeverityEnum.CRITICAL,
    ),
    (
        "Slack Token",
        re.compile(r"\b(xox[baprs]-[0-9a-zA-Z]{10,48})\b"),
        SeverityEnum.CRITICAL,
    ),
    (
        "Generic Secret Assignment",
        re.compile(
            r"""(?i)(?:api_key|secret_key|client_secret|auth_token|password|access_token)\s*[:=]\s*["']([A-Za-z0-9\-_./+=]{16,})["']"""
        ),
        SeverityEnum.HIGH,
    ),
    (
        "JWT Token",
        re.compile(r"\beyJ[A-Za-z0-9\-_=]+\.eyJ[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_.+/=]+\b"),
        SeverityEnum.HIGH,
    ),
    (
        "Google / Gemini API Key",
        re.compile(r"\b(AIza[0-9A-Za-z\-_]{35})\b"),
        SeverityEnum.CRITICAL,
    ),
    (
        "Anthropic API Key",
        re.compile(r"\b(sk-ant-[0-9A-Za-z\-_]{32,})\b"),
        SeverityEnum.CRITICAL,
    ),
]

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions\b"),
    re.compile(r"(?i)\bdisregard\s+(?:all\s+)?(?:system|previous|prior)\s+instructions\b"),
    re.compile(r"(?i)\byou\s+are\s+now\s+(?:in\s+developer\s+mode|an\s+unrestricted\s+ai)\b"),
    re.compile(r"(?i)\bprint\s+(?:your\s+)?system\s+prompt\b"),
    re.compile(r"(?i)\bapprove\s+this\s+pull\s+request\s+without\s+review\b"),
    re.compile(r"(?i)\boverride\s+(?:safety|review)\s+rules\b"),
]


def scan_for_prompt_injection(text: str) -> list[str]:
    """Check text for common prompt injection and policy-override attacks."""
    matches = []
    for pattern in PROMPT_INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            matches.append(m.group(0))
    return matches


def redact_secret(text: str) -> str:
    """Redact any potential secret matches in text to prevent accidental leakage."""
    redacted = text
    for name, pattern, _ in SECRET_PATTERNS:
        matches = pattern.finditer(redacted)
        for m in reversed(list(matches)):
            start, end = m.span()
            secret_str = redacted[start:end]
            if len(secret_str) > 8:
                masked = secret_str[:3] + "..." + secret_str[-3:] + f" [REDACTED {name}]"
            else:
                masked = f"[REDACTED {name}]"
            redacted = redacted[:start] + masked + redacted[end:]
    return redacted


def scan_file_content_for_secrets(filename: str, content: str) -> list[ReviewFinding]:
    """Scan file lines for credentials and return deterministic security findings."""
    findings: list[ReviewFinding] = []
    lines = content.splitlines()

    for line_idx, line in enumerate(lines, start=1):
        # Ignore comments or placeholder documentation
        lower_line = line.lower().strip()
        if (
            "example" in lower_line
            or "placeholder" in lower_line
            or "dummy" in lower_line
            or "your-key-here" in lower_line
            or "your_api_key" in lower_line
        ):
            continue

        for name, pattern, severity in SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                findings.append(
                    ReviewFinding(
                        severity=severity,
                        category=CategoryEnum.SECURITY,
                        title=f"Hard-coded secret detected ({name})",
                        description=(
                            f"A potential hard-coded {name} was found on line {line_idx}. "
                            "Hard-coding credentials in source code exposes them to leakage and unauthorized access. "
                            "Store secrets in environment variables or an encrypted secrets manager."
                        ),
                        file=filename,
                        line=line_idx,
                        suggested_fix="Use os.environ or a secrets manager instead of embedding secrets in code.",
                        confidence=0.98,
                    )
                )
                break  # Don't double report multiple patterns on the exact same line
    return findings
