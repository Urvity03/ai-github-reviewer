"""Tests for context builder, AST symbol resolution, and large PR handling."""

from pathlib import Path

from ai_reviewer.config import AppConfig
from ai_reviewer.context import (
    ContextBuilder,
    extract_python_symbols_and_imports,
    find_related_test_files,
)
from ai_reviewer.models.review import ChangedFile


def test_ast_symbol_and_import_extraction():
    sample_code = """
import os
import sys
from pathlib import Path

class UserService:
    def authenticate(self, user: str) -> bool:
        return True

def standalone_helper():
    pass
"""
    imports, symbols, ranges = extract_python_symbols_and_imports(sample_code)
    assert "os" in imports
    assert "sys" in imports
    assert "pathlib" in imports
    assert "UserService" in symbols
    assert "authenticate" in symbols
    assert "standalone_helper" in symbols
    assert len(ranges) >= 3


def test_find_related_tests(tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_auth.py"
    test_file.write_text("def test_dummy(): pass", encoding="utf-8")

    matches = find_related_test_files("src/auth.py", tmp_path)
    assert len(matches) == 1
    assert "tests/test_auth.py" in matches


def test_large_pr_truncation(tmp_path: Path):
    cfg = AppConfig()
    cfg.limits.max_changed_files = 3
    builder = ContextBuilder(cfg, tmp_path)

    files = [
        ChangedFile(filename=f"src/file_{i}.py", status="modified", additions=10, deletions=5)
        for i in range(5)
    ]

    ctx = builder.build_review_context(
        repo_owner="owner",
        repo_name="repo",
        pr_number=42,
        pr_title="Big feature",
        pr_description="Changes many files",
        base_branch="main",
        head_branch="feature",
        commit_sha="abcdef123456",
        changed_files=files,
    )

    assert ctx.truncated is True
    assert "exceeds the limit of 3 files" in ctx.truncation_reason
