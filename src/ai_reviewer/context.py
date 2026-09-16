"""Intelligent context selection, AST inspection, and repository awareness."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from ai_reviewer.config import AppConfig
from ai_reviewer.diff import is_line_in_diff
from ai_reviewer.models.review import ChangedFile, ReviewContext


def extract_python_symbols_and_imports(
    source_code: str,
) -> tuple[list[str], list[str], list[tuple[str, int, int]]]:
    """
    Extract imports, top-level definitions, and line ranges of functions/classes.
    Returns: (imported_modules, symbol_names, list of (name, start_line, end_line))
    """
    imports: list[str] = []
    symbols: list[str] = []
    ranges: list[tuple[str, int, int]] = []

    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return imports, symbols, ranges

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
            if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                ranges.append((node.name, node.lineno, node.end_lineno or node.lineno))

    return imports, symbols, ranges


def find_related_test_files(source_filename: str, repo_root: Path) -> list[str]:
    """Find potential test files associated with a source code file."""
    src_path = Path(source_filename)
    stem = src_path.stem
    candidates = [
        f"tests/test_{stem}.py",
        f"tests/{stem}_test.py",
        f"tests/unit/test_{stem}.py",
        f"test/test_{stem}.py",
        f"tests/{src_path.parent}/test_{stem}.py",
    ]

    matched: list[str] = []
    for rel_path in candidates:
        full_path = repo_root / rel_path
        if full_path.is_file():
            matched.append(rel_path.replace("\\", "/"))

    return matched


class ContextBuilder:
    """Builds optimized and token-conscious context for AI review."""

    def __init__(self, config: AppConfig, repo_root: Path | None = None):
        self.config = config
        self.repo_root = repo_root or Path.cwd()

    def build_review_context(
        self,
        repo_owner: str,
        repo_name: str,
        pr_number: int,
        pr_title: str,
        pr_description: str,
        base_branch: str,
        head_branch: str,
        commit_sha: str,
        changed_files: list[ChangedFile],
    ) -> ReviewContext:
        """Constructs ReviewContext while filtering ignored files and checking size limits."""
        total_additions = sum(f.additions for f in changed_files)
        total_deletions = sum(f.deletions for f in changed_files)
        total_lines = total_additions + total_deletions

        # Check for huge PR limits
        truncated = False
        truncation_reason: str | None = None

        if len(changed_files) > self.config.limits.max_changed_files:
            truncated = True
            truncation_reason = (
                f"PR touches {len(changed_files)} files, which exceeds the limit of "
                f"{self.config.limits.max_changed_files} files."
            )
        elif total_lines > self.config.limits.max_diff_lines:
            truncated = True
            truncation_reason = (
                f"PR diff has {total_lines} changed lines, exceeding limit of "
                f"{self.config.limits.max_diff_lines} lines."
            )

        processed_files: list[ChangedFile] = []
        extra_context: dict[str, Any] = {
            "related_tests": {},
            "changed_symbols": {},
        }

        for file_obj in changed_files:
            # Check if file path is ignored
            if self.config.is_path_ignored(file_obj.filename):
                file_obj.is_ignored = True
                continue

            # Don't analyze deleted files in deep AI review
            if file_obj.status == "deleted":
                processed_files.append(file_obj)
                continue

            # Check for binary files
            if file_obj.is_binary:
                processed_files.append(file_obj)
                continue

            # If the file exists on disk, extract symbols and test relations
            local_file = self.repo_root / file_obj.filename
            if local_file.is_file() and file_obj.filename.endswith(".py"):
                try:
                    content = local_file.read_text(encoding="utf-8", errors="replace")
                    file_obj.content_after = content
                    imports, symbols, symbol_ranges = extract_python_symbols_and_imports(content)

                    # Identify which symbols were modified in this PR
                    modified_symbols: list[str] = []
                    for sym_name, start, end in symbol_ranges:
                        for line_no in range(start, end + 1):
                            if is_line_in_diff(file_obj, line_no, require_modified=True):
                                modified_symbols.append(sym_name)
                                break

                    if modified_symbols:
                        extra_context["changed_symbols"][file_obj.filename] = modified_symbols

                    # Find related tests
                    related_tests = find_related_test_files(file_obj.filename, self.repo_root)
                    if related_tests:
                        extra_context["related_tests"][file_obj.filename] = related_tests

                except Exception:
                    # Non-fatal if AST parse or file reading fails
                    pass

            processed_files.append(file_obj)

        return ReviewContext(
            repo_owner=repo_owner,
            repo_name=repo_name,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_description=pr_description,
            base_branch=base_branch,
            head_branch=head_branch,
            commit_sha=commit_sha,
            changed_files=processed_files,
            total_additions=total_additions,
            total_deletions=total_deletions,
            custom_rules=self.config.custom_rules,
            truncated=truncated,
            truncation_reason=truncation_reason,
            extra_context=extra_context,
        )
