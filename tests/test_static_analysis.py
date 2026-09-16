"""Tests for deterministic static analysis checks."""

from pathlib import Path

from ai_reviewer.models.review import ChangedFile, SeverityEnum
from ai_reviewer.static_analysis import (
    run_python_syntax_check,
    run_secret_scanner,
)


def test_python_syntax_check_detects_syntax_error(tmp_path: Path):
    broken_py = tmp_path / "broken.py"
    broken_py.write_text("def faulty_function(\n    print('missing closing paren')\n", encoding="utf-8")

    cf = ChangedFile(filename="broken.py", additions=2, deletions=0)
    result = run_python_syntax_check([cf], tmp_path)

    assert result.status == "failed"
    assert len(result.findings) == 1
    assert result.findings[0].severity == SeverityEnum.CRITICAL
    assert "SyntaxError in broken.py" in result.findings[0].title


def test_python_syntax_check_passes_on_valid_code(tmp_path: Path):
    valid_py = tmp_path / "valid.py"
    valid_py.write_text("def valid_function():\n    return 42\n", encoding="utf-8")

    cf = ChangedFile(filename="valid.py", additions=2, deletions=0)
    result = run_python_syntax_check([cf], tmp_path)

    assert result.status == "passed"
    assert len(result.findings) == 0


def test_secret_scanner_integration(tmp_path: Path):
    secret_file = tmp_path / "creds.py"
    secret_file.write_text("API_SECRET = 'AKIAABCDEFGHIJKLMNOP'\n", encoding="utf-8")

    cf = ChangedFile(filename="creds.py", additions=1, deletions=0)
    result = run_secret_scanner([cf], tmp_path)

    assert result.status == "failed"
    assert len(result.findings) == 1
    assert "AWS Access Key ID" in result.findings[0].title
