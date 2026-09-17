"""Data models for review requests, diff representations, findings, and results."""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SeverityEnum(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def level(self) -> int:
        levels = {
            SeverityEnum.CRITICAL: 5,
            SeverityEnum.HIGH: 4,
            SeverityEnum.MEDIUM: 3,
            SeverityEnum.LOW: 2,
            SeverityEnum.INFO: 1,
        }
        return levels[self]

    @property
    def emoji(self) -> str:
        emojis = {
            SeverityEnum.CRITICAL: "🛑",
            SeverityEnum.HIGH: "🔴",
            SeverityEnum.MEDIUM: "🟡",
            SeverityEnum.LOW: "🔵",
            SeverityEnum.INFO: "ℹ️",
        }
        return emojis[self]


class CategoryEnum(str, Enum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    RELIABILITY = "reliability"
    TESTING = "testing"
    PERFORMANCE = "performance"
    ARCHITECTURE = "architecture"
    MAINTAINABILITY = "maintainability"
    ML = "ml"
    DOCUMENTATION = "documentation"

    @property
    def display_name(self) -> str:
        names = {
            CategoryEnum.CORRECTNESS: "Correctness",
            CategoryEnum.SECURITY: "Security",
            CategoryEnum.RELIABILITY: "Reliability",
            CategoryEnum.TESTING: "Testing",
            CategoryEnum.PERFORMANCE: "Performance",
            CategoryEnum.ARCHITECTURE: "Architecture",
            CategoryEnum.MAINTAINABILITY: "Maintainability",
            CategoryEnum.ML: "ML / AI",
            CategoryEnum.DOCUMENTATION: "Documentation",
        }
        return names.get(self, self.value.capitalize())


class DecisionEnum(str, Enum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    COMMENT = "comment"


class CheckStatusEnum(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    ERROR = "ERROR"


class ReviewFinding(BaseModel):
    severity: SeverityEnum
    category: CategoryEnum
    title: str = Field(..., min_length=3, max_length=200)
    description: str = Field(..., min_length=5)
    file: str = Field(..., min_length=1)
    line: int | None = Field(default=None, ge=1)
    suggested_fix: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str) -> str:
        return v.strip().replace("\n", " ")

    @property
    def fingerprint(self) -> str:
        """Create a deterministic fingerprint for deduplication across commits."""
        norm_title = re.sub(r"[^a-zA-Z0-9]", "", self.title.lower())
        norm_file = self.file.replace("\\", "/").strip().lower()
        line_str = str(self.line) if self.line is not None else "0"
        raw = f"{norm_file}:{line_str}:{self.category.value}:{norm_title}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ReviewResult(BaseModel):
    summary: str
    decision: DecisionEnum
    findings: list[ReviewFinding] = Field(default_factory=list)
    token_usage: dict[str, int] | None = None
    raw_output: str | None = None
    is_error: bool = False
    error_message: str | None = None


class DiffHunk(BaseModel):
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    header: str
    lines: list[str] = Field(default_factory=list)
    # 1-indexed line numbers in the new file that were added or modified in this hunk
    added_new_lines: set[int] = Field(default_factory=set)
    # all valid new line numbers present in this hunk (including context lines)
    valid_new_lines: set[int] = Field(default_factory=set)


class ChangedFile(BaseModel):
    filename: str
    status: str = "modified"  # added, modified, deleted, renamed
    old_filename: str | None = None
    additions: int = 0
    deletions: int = 0
    patch: str | None = None
    hunks: list[DiffHunk] = Field(default_factory=list)
    is_binary: bool = False
    is_ignored: bool = False
    content_before: str | None = None
    content_after: str | None = None

    def get_valid_lines(self) -> set[int]:
        valid: set[int] = set()
        for hunk in self.hunks:
            valid.update(hunk.valid_new_lines)
        return valid

    def get_added_or_modified_lines(self) -> set[int]:
        valid: set[int] = set()
        for hunk in self.hunks:
            valid.update(hunk.added_new_lines)
        return valid


class DeterministicCheckResult(BaseModel):
    name: str
    status: str  # "passed", "failed", "skipped", "not_configured"
    details: str
    findings: list[ReviewFinding] = Field(default_factory=list)


class ReviewContext(BaseModel):
    repo_owner: str
    repo_name: str
    pr_number: int
    pr_title: str
    pr_description: str
    base_branch: str
    head_branch: str
    commit_sha: str
    changed_files: list[ChangedFile] = Field(default_factory=list)
    total_additions: int = 0
    total_deletions: int = 0
    custom_rules: list[str] = Field(default_factory=list)
    deterministic_results: list[DeterministicCheckResult] = Field(default_factory=list)
    truncated: bool = False
    truncation_reason: str | None = None
    extra_context: dict[str, Any] = Field(default_factory=dict)
