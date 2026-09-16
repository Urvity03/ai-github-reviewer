"""Tests for CLI entrypoints."""

from pathlib import Path

from typer.testing import CliRunner

from ai_reviewer.cli import app

runner = CliRunner()


def test_cli_doctor():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "AI Reviewer — System Diagnostics" in result.stdout
    assert "Python Version" in result.stdout


def test_cli_config():
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "Active AI Reviewer Configuration" in result.stdout
    assert "openai" in result.stdout


def test_cli_review_file_dry_run(tmp_path: Path):
    test_py = tmp_path / "hello.py"
    test_py.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    # Reviewing a single clean file with dry run and disabled AI
    result = runner.invoke(app, ["review", "--file", str(test_py), "--dry-run"])
    assert result.exit_code == 0
    assert "Local File Review" in result.stdout
