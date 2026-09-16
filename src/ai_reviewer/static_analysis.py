"""Deterministic checks engine (Ruff, pytest, Python syntax check, secret scanning)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from ai_reviewer.config import AppConfig
from ai_reviewer.models.review import (
    CategoryEnum,
    ChangedFile,
    DeterministicCheckResult,
    ReviewFinding,
    SeverityEnum,
)
from ai_reviewer.security import scan_file_content_for_secrets


def run_python_syntax_check(changed_files: list[ChangedFile], repo_root: Path) -> DeterministicCheckResult:
    """Run compile() syntax check on all changed Python files."""
    findings: list[ReviewFinding] = []
    py_files = [f for f in changed_files if f.filename.endswith(".py") and f.status != "deleted"]

    if not py_files:
        return DeterministicCheckResult(
            name="Python Syntax Check",
            status="skipped",
            details="No Python files changed.",
            findings=[],
        )

    for f in py_files:
        file_path = repo_root / f.filename
        if not file_path.is_file():
            continue
        try:
            code = file_path.read_text(encoding="utf-8", errors="replace")
            compile(code, str(file_path), "exec")
        except SyntaxError as err:
            findings.append(
                ReviewFinding(
                    severity=SeverityEnum.CRITICAL,
                    category=CategoryEnum.CORRECTNESS,
                    title=f"SyntaxError in {f.filename}",
                    description=f"Python syntax compilation error on line {err.lineno}: {err.msg}",
                    file=f.filename,
                    line=err.lineno,
                    suggested_fix="Fix the syntax error so code can be parsed and executed.",
                    confidence=1.0,
                )
            )

    status = "failed" if findings else "passed"
    details = f"Scanned {len(py_files)} Python files; found {len(findings)} syntax error(s)."
    return DeterministicCheckResult(
        name="Python Syntax Check",
        status=status,
        details=details,
        findings=findings,
    )


def run_secret_scanner(changed_files: list[ChangedFile], repo_root: Path) -> DeterministicCheckResult:
    """Run regex-based secret scanning across changed files."""
    findings: list[ReviewFinding] = []
    scanned_count = 0

    for f in changed_files:
        if f.is_binary or f.is_ignored or f.status == "deleted":
            continue
        file_path = repo_root / f.filename
        if not file_path.is_file():
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            scanned_count += 1
            file_findings = scan_file_content_for_secrets(f.filename, content)
            findings.extend(file_findings)
        except Exception:
            pass

    status = "failed" if findings else "passed"
    details = f"Scanned {scanned_count} file(s); detected {len(findings)} potential secret(s)."
    return DeterministicCheckResult(
        name="Secret Scanner",
        status=status,
        details=details,
        findings=findings,
    )


def run_ruff_linter(changed_files: list[ChangedFile], repo_root: Path) -> DeterministicCheckResult:
    """Run Ruff on modified Python files if Ruff is available in PATH or virtualenv."""
    ruff_bin = shutil.which("ruff")
    if not ruff_bin:
        return DeterministicCheckResult(
            name="Ruff Linter",
            status="not_configured",
            details="Ruff is not installed or available in PATH.",
            findings=[],
        )

    py_files = [
        str(repo_root / f.filename)
        for f in changed_files
        if f.filename.endswith(".py") and f.status != "deleted" and (repo_root / f.filename).is_file()
    ]

    if not py_files:
        return DeterministicCheckResult(
            name="Ruff Linter",
            status="skipped",
            details="No modified Python files to lint.",
            findings=[],
        )

    cmd = [ruff_bin, "check", "--output-format=json", *py_files]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        findings: list[ReviewFinding] = []
        if res.stdout.strip():
            try:
                lint_records = json.loads(res.stdout)
                for rec in lint_records:
                    rel_file = os.path.relpath(rec["filename"], str(repo_root)).replace("\\", "/")
                    line = rec["location"]["row"]
                    rule_code = rec.get("code", "")
                    message = rec.get("message", "")
                    # Convert lint to finding
                    findings.append(
                        ReviewFinding(
                            severity=SeverityEnum.LOW if rule_code.startswith(("D", "W")) else SeverityEnum.MEDIUM,
                            category=CategoryEnum.MAINTAINABILITY,
                            title=f"Ruff Lint: {rule_code} - {message}",
                            description=f"Ruff rule {rule_code} violation at line {line}: {message}",
                            file=rel_file,
                            line=line,
                            suggested_fix=rec.get("fix", {}).get("message") if rec.get("fix") else None,
                            confidence=0.99,
                        )
                    )
            except json.JSONDecodeError:
                pass

        status = "failed" if findings else "passed"
        return DeterministicCheckResult(
            name="Ruff Linter",
            status=status,
            details=f"Linted {len(py_files)} file(s); found {len(findings)} issue(s).",
            findings=findings,
        )
    except Exception as err:
        return DeterministicCheckResult(
            name="Ruff Linter",
            status="failed",
            details=f"Ruff execution error: {err}",
            findings=[],
        )


def run_pytest_suite(repo_root: Path) -> DeterministicCheckResult:
    """Run pytest if configured in repository."""
    pytest_bin = shutil.which("pytest")
    if not pytest_bin:
        return DeterministicCheckResult(
            name="Pytest Suite",
            status="not_configured",
            details="Pytest is not installed or available in PATH.",
            findings=[],
        )

    has_tests = (repo_root / "tests").is_dir() or (repo_root / "test").is_dir()
    if not has_tests:
        return DeterministicCheckResult(
            name="Pytest Suite",
            status="skipped",
            details="No tests/ directory found.",
            findings=[],
        )

    if os.getenv("PYTEST_CURRENT_TEST"):
        return DeterministicCheckResult(
            name="Pytest Suite",
            status="skipped",
            details="Skipped nested pytest execution during test run.",
            findings=[],
        )

    try:
        res = subprocess.run(
            [pytest_bin, "-q", "--maxfail=5"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if res.returncode == 0:
            return DeterministicCheckResult(
                name="Pytest Suite",
                status="passed",
                details="All tests passed successfully.",
                findings=[],
            )
        else:
            first_fail_line = (res.stdout or res.stderr).splitlines()[:5]
            summary = "\n".join(first_fail_line)
            finding = ReviewFinding(
                severity=SeverityEnum.HIGH,
                category=CategoryEnum.TESTING,
                title="Pytest Suite Failed",
                description=f"Unit test suite exited with error code {res.returncode}:\n{summary}",
                file="tests",
                line=None,
                suggested_fix="Fix failing tests before merging pull request.",
                confidence=1.0,
            )
            return DeterministicCheckResult(
                name="Pytest Suite",
                status="failed",
                details=f"Tests failed (code {res.returncode}).",
                findings=[finding],
            )
    except subprocess.TimeoutExpired:
        return DeterministicCheckResult(
            name="Pytest Suite",
            status="failed",
            details="Pytest execution timed out after 60 seconds.",
            findings=[],
        )
    except Exception as err:
        return DeterministicCheckResult(
            name="Pytest Suite",
            status="failed",
            details=f"Pytest run error: {err}",
            findings=[],
        )


def run_all_deterministic_checks(
    changed_files: list[ChangedFile], config: AppConfig, repo_root: Path | None = None
) -> list[DeterministicCheckResult]:
    """Execute all configured deterministic checks."""
    root = repo_root or Path.cwd()
    results: list[DeterministicCheckResult] = []

    # 1. Syntax Check
    if config.deterministic_checks.run_compile_check:
        results.append(run_python_syntax_check(changed_files, root))

    # 2. Secret Scan
    if config.deterministic_checks.run_secret_scan:
        results.append(run_secret_scanner(changed_files, root))

    # 3. Ruff Linter
    if config.deterministic_checks.run_ruff:
        results.append(run_ruff_linter(changed_files, root))

    # 4. Pytest
    if config.deterministic_checks.run_pytest:
        results.append(run_pytest_suite(root))

    return results
