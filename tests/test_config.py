"""Tests for configuration loading, schema validation, and path ignoring."""

from pathlib import Path

from ai_reviewer.config import AppConfig, load_config
from ai_reviewer.models.review import SeverityEnum


def test_default_config():
    cfg = AppConfig()
    assert cfg.review.enabled is True
    assert cfg.review.provider == "gemini"
    assert cfg.review.model == "gemini-3.6-flash"
    assert SeverityEnum.CRITICAL in cfg.severity.fail_on
    assert SeverityEnum.HIGH in cfg.severity.fail_on
    assert cfg.rules.correctness is True
    assert cfg.rules.ml is True


def test_path_ignoring():
    cfg = AppConfig()
    # Default ignored extensions and patterns
    assert cfg.is_path_ignored("poetry.lock") is True
    assert cfg.is_path_ignored("dist/bundle.js") is True
    assert cfg.is_path_ignored(".env") is True
    assert cfg.is_path_ignored(".env.local") is True
    assert cfg.is_path_ignored("id_rsa") is True
    assert cfg.is_path_ignored("certs/server.pem") is True
    assert cfg.is_path_ignored("app.min.js") is True
    assert cfg.is_path_ignored("notebook.ipynb") is True

    # Non-ignored source files
    assert cfg.is_path_ignored("src/utils.py") is False
    assert cfg.is_path_ignored("tests/test_routes.py") is False
    assert cfg.is_path_ignored("README.md") is False


def test_custom_rules_loading(tmp_path: Path):
    custom_yaml = """
review:
  enabled: false
  model: "gpt-4o-mini"

custom_rules:
  - "Never log GPS data."
  - "Require tests for safety algorithms."

severity:
  fail_on:
    - critical
"""
    config_file = tmp_path / ".ai-reviewer.yml"
    config_file.write_text(custom_yaml, encoding="utf-8")

    cfg = load_config(str(config_file))
    assert cfg.review.enabled is False
    assert cfg.review.model == "gpt-4o-mini"
    assert len(cfg.custom_rules) == 2
    assert "Never log GPS data." in cfg.custom_rules
    assert cfg.should_fail_on(SeverityEnum.CRITICAL) is True
    assert cfg.should_fail_on(SeverityEnum.HIGH) is False
