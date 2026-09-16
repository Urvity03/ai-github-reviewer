"""Configuration loader and schema definition for .ai-reviewer.yml."""

from __future__ import annotations

import os
from pathlib import Path

import pathspec
import yaml
from pydantic import BaseModel, Field

from ai_reviewer.models.review import SeverityEnum

DEFAULT_EXCLUDED_PATTERNS = [
    ".git/**",
    ".github/**",
    "*.lock",
    "package-lock.json",
    "poetry.lock",
    "Pipfile.lock",
    "uv.lock",
    "pnpm-lock.yaml",
    "dist/**",
    "build/**",
    "__pycache__/**",
    "*.pyc",
    "*.min.js",
    "*.min.css",
    "vendor/**",
    "node_modules/**",
    ".venv/**",
    "venv/**",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.ico",
    "*.svg",
    "*.pdf",
    "*.zip",
    "*.tar.gz",
    "*.whl",
    "*.ipynb",
    # Sensitive credential files are always ignored
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
    "credentials*.json",
    "secrets/**",
]


class ReviewConfigSection(BaseModel):
    enabled: bool = True
    language: str = "auto"
    provider: str = "openai"
    model: str = "gpt-4o"
    temperature: float = 0.1
    confidence_threshold: float = 0.7


class SeverityConfig(BaseModel):
    fail_on: list[SeverityEnum] = Field(
        default_factory=lambda: [SeverityEnum.CRITICAL, SeverityEnum.HIGH]
    )
    inline_comment_severities: list[SeverityEnum] = Field(
        default_factory=lambda: [SeverityEnum.CRITICAL, SeverityEnum.HIGH, SeverityEnum.MEDIUM]
    )


class PathsConfig(BaseModel):
    ignore: list[str] = Field(default_factory=list)

    def get_effective_ignore_patterns(self) -> list[str]:
        # Merge default system ignores with user configured patterns
        patterns = list(DEFAULT_EXCLUDED_PATTERNS)
        for pattern in self.ignore:
            if pattern not in patterns:
                patterns.append(pattern)
        return patterns


class LimitsConfig(BaseModel):
    max_changed_files: int = 100
    max_diff_lines: int = 10000
    max_context_tokens: int = 32000


class RulesConfig(BaseModel):
    correctness: bool = True
    security: bool = True
    reliability: bool = True
    tests: bool = True
    performance: bool = True
    architecture: bool = True
    maintainability: bool = True
    documentation: bool = True
    ml: bool = True


class DeterministicChecksConfig(BaseModel):
    run_ruff: bool = True
    run_pytest: bool = True
    run_compile_check: bool = True
    run_secret_scan: bool = True


class AppConfig(BaseModel):
    review: ReviewConfigSection = Field(default_factory=ReviewConfigSection)
    severity: SeverityConfig = Field(default_factory=SeverityConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    deterministic_checks: DeterministicChecksConfig = Field(default_factory=DeterministicChecksConfig)
    custom_rules: list[str] = Field(default_factory=list)

    def is_path_ignored(self, file_path: str) -> bool:
        normalized = file_path.replace("\\", "/")
        normalized = normalized.removeprefix("./")
        patterns = self.paths.get_effective_ignore_patterns()
        spec = pathspec.PathSpec.from_lines("gitignore", patterns)
        return spec.match_file(normalized)

    def should_fail_on(self, severity: SeverityEnum) -> bool:
        return severity in self.severity.fail_on

    def should_post_inline(self, severity: SeverityEnum) -> bool:
        return severity in self.severity.inline_comment_severities


def load_config(config_path: str | None = None) -> AppConfig:
    """Load configuration from .ai-reviewer.yml or return defaults."""
    candidates = [
        config_path,
        os.getenv("AI_REVIEWER_CONFIG_PATH"),
        ".ai-reviewer.yml",
        ".ai-reviewer.yaml",
        ".github/.ai-reviewer.yml",
    ]

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                return AppConfig.model_validate(data)
            except Exception as err:
                print(f"[WARN] Error reading config file {candidate}: {err}. Using defaults.")

    return AppConfig()
