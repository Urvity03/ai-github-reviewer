"""Command Line Interface for AI Pull Request Reviewer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_reviewer.config import load_config
from ai_reviewer.context import ContextBuilder
from ai_reviewer.diff import parse_patch_to_hunks, parse_unified_diff
from ai_reviewer.github_client import GitHubClient
from ai_reviewer.models.review import ChangedFile, CheckStatusEnum
from ai_reviewer.reviewer import ReviewOrchestrator

app = typer.Typer(
    name="ai-reviewer",
    help="Production-ready GitHub AI Pull Request Reviewer CLI.",
    add_completion=False,
)
console = Console()


@app.command()
def doctor() -> None:
    """Verify environment, dependencies, configuration, and API connectivity."""
    console.print(Panel.fit("[bold blue]AI Reviewer — System Diagnostics (Doctor)[/bold blue]"))

    table = Table(title="System & Dependency Health", show_header=True, header_style="bold magenta")
    table.add_column("Component", style="dim", width=25)
    table.add_column("Status", width=12)
    table.add_column("Details")

    # 1. Python version
    py_ver = sys.version.split()[0]
    py_ok = sys.version_info >= (3, 11)
    table.add_row(
        "Python Version",
        "[green]PASS[/green]" if py_ok else "[red]FAIL[/red]",
        f"v{py_ver} (>= 3.11 required)",
    )

    # 2. Git setup
    git_bin = shutil.which("git")
    if git_bin:
        try:
            res = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, check=False)
            is_repo = res.stdout.strip() == "true"
            branch_res = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, check=False)
            branch = branch_res.stdout.strip() or "HEAD (detached)"
            table.add_row(
                "Git Repository",
                "[green]PASS[/green]" if is_repo else "[yellow]WARN[/yellow]",
                f"Branch: {branch}" if is_repo else "Not inside a Git repository",
            )
        except Exception as e:
            table.add_row("Git Repository", "[red]FAIL[/red]", f"Git error: {e}")
    else:
        table.add_row("Git Installation", "[red]FAIL[/red]", "Git not found in PATH")

    # 3. AI Provider Keys (Gemini default, OpenAI optional)
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        masked_key = gemini_key[:3] + "..." + gemini_key[-4:] if len(gemini_key) > 8 else "***"
        table.add_row("GEMINI_API_KEY (Default)", "[green]CONFIGURED[/green]", f"Key present ({masked_key})")
    else:
        table.add_row("GEMINI_API_KEY (Default)", "[yellow]NOT SET[/yellow]", "Required for Free Tier Gemini AI reviews. Export GEMINI_API_KEY.")

    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        masked_open = openai_key[:3] + "..." + openai_key[-4:] if len(openai_key) > 8 else "***"
        table.add_row("OPENAI_API_KEY (Optional)", "[green]CONFIGURED[/green]", f"Key present ({masked_open})")
    else:
        table.add_row("OPENAI_API_KEY (Optional)", "[dim]NOT SET[/dim]", "Optional alternative provider.")

    # 4. GitHub Token presence
    gh_token = os.getenv("GITHUB_TOKEN")
    if gh_token:
        masked_gh = gh_token[:3] + "..." + gh_token[-4:] if len(gh_token) > 8 else "***"
        table.add_row("GITHUB_TOKEN", "[green]CONFIGURED[/green]", f"Token present ({masked_gh})")
    else:
        table.add_row("GITHUB_TOKEN", "[dim]NOT SET[/dim]", "Optional locally. Required for PR posting in GitHub Actions.")

    # 5. GitHub App Settings (for standalone App / Webhook server)
    app_id = os.getenv("GITHUB_APP_ID")
    app_key = os.getenv("GITHUB_PRIVATE_KEY") or os.getenv("GITHUB_APP_PRIVATE_KEY") or os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
    wh_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if app_id:
        table.add_row("GITHUB_APP_ID", "[green]CONFIGURED[/green]", f"App ID: {app_id}")
    else:
        table.add_row("GITHUB_APP_ID", "[dim]NOT SET[/dim]", "Optional for Actions; required for GitHub App")

    if app_key:
        table.add_row("GITHUB_PRIVATE_KEY", "[green]CONFIGURED[/green]", "Private key is configured")
    else:
        table.add_row("GITHUB_PRIVATE_KEY", "[dim]NOT SET[/dim]", "Optional for Actions; required for GitHub App")

    if wh_secret:
        table.add_row("GITHUB_WEBHOOK_SECRET", "[green]CONFIGURED[/green]", "Secret is configured")
    else:
        table.add_row("GITHUB_WEBHOOK_SECRET", "[dim]NOT SET[/dim]", "Optional for Actions; required for Webhook verification")

    # 6. Configuration file
    config_file = Path(".ai-reviewer.yml")
    if config_file.is_file():
        table.add_row("Repository Config", "[green]FOUND[/green]", ".ai-reviewer.yml present")
    else:
        table.add_row("Repository Config", "[dim]DEFAULT[/dim]", "No .ai-reviewer.yml found; using production defaults")

    # 7. Optional Tools
    for tool_name in ["ruff", "pytest", "docker"]:
        tool_path = shutil.which(tool_name)
        status_str = "[green]AVAILABLE[/green]" if tool_path else "[dim]NOT FOUND[/dim]"
        table.add_row(f"Tool: {tool_name}", status_str, tool_path or f"{tool_name} not in PATH")

    console.print(table)


@app.command()
def config() -> None:
    """Display the active configuration."""
    cfg = load_config()
    console.print(Panel.fit("[bold blue]Active AI Reviewer Configuration[/bold blue]"))
    console.print(json.dumps(cfg.model_dump(mode="json"), indent=2))


@app.command()
def review(
    base: str | None = typer.Option(None, "--base", "-b", help="Base git branch to diff against (e.g. main)"),
    file: str | None = typer.Option(None, "--file", "-f", help="Review a single file locally"),
    pr_number: int | None = typer.Option(None, "--pr", help="Pull request number (for GitHub API mode)"),
    repo: str | None = typer.Option(None, "--repo", help="Repository slug in format 'owner/repo'"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run review without posting comments to GitHub"),
) -> None:
    """Run code review on a pull request, git branch diff, or specific file."""
    app_config = load_config()
    repo_root = Path.cwd()

    # 1. Determine environment (GitHub Actions vs Local CLI)
    env_repo = repo or os.getenv("GITHUB_REPOSITORY")
    env_pr = pr_number or (int(os.getenv("GITHUB_PULL_REQUEST_NUMBER", "0")) if os.getenv("GITHUB_PULL_REQUEST_NUMBER") else None)

    # Check GITHUB_EVENT_PATH if running in GitHub Actions pull_request event
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).is_file() and not env_pr:
        try:
            with open(event_path, "r", encoding="utf-8") as f:
                event_data = json.load(f)
            if "pull_request" in event_data:
                env_pr = event_data["pull_request"]["number"]
                if not env_repo:
                    env_repo = event_data["repository"]["full_name"]
        except Exception:
            pass

    owner = "local"
    repo_name = "workspace"
    if env_repo and "/" in env_repo:
        owner, repo_name = env_repo.split("/", 1)

    changed_files = []
    head_sha = os.getenv("GITHUB_HEAD_SHA") or "HEAD"
    base_branch = base or os.getenv("GITHUB_BASE_REF") or "main"
    head_branch = os.getenv("GITHUB_HEAD_REF") or "current"
    pr_title = "Local Code Changes"
    pr_description = "Local developer review execution"

    gh_client = GitHubClient()

    # If running in GitHub Actions with PR number and GitHub token
    if env_pr and gh_client.token and not file and not dry_run:
        console.print(f"Fetching PR #{env_pr} data from GitHub API ({owner}/{repo_name})...")
        try:
            pr_data = gh_client.get_pull_request(owner, repo_name, env_pr)
            pr_title = pr_data.get("title", "")
            pr_description = pr_data.get("body", "") or ""
            base_branch = base or os.getenv("GITHUB_BASE_REF") or pr_data.get("base", {}).get("ref", "main")
            head_branch = os.getenv("GITHUB_HEAD_REF") or pr_data.get("head", {}).get("ref", "head")
            head_sha = os.getenv("GITHUB_HEAD_SHA") or pr_data.get("head", {}).get("sha", "HEAD")
            changed_files = gh_client.get_pull_request_files(owner, repo_name, env_pr)
        except Exception as err:
            console.print(f"[bold red]Failed to fetch PR from GitHub API: {err}. Falling back to local git diff.[/bold red]")

    # If changed files not yet populated (local CLI mode)
    if not changed_files:
        if file:
            target_path = Path(file)
            if not target_path.is_file():
                console.print(f"[bold red]Error: Specified file '{file}' does not exist.[/bold red]")
                raise typer.Exit(code=1)
            content = target_path.read_text(encoding="utf-8", errors="replace")
            # Create synthetic diff hunk for single file
            lines = content.splitlines()
            fake_patch = f"@@ -1,1 +1,{len(lines)} @@\n" + "\n".join(f"+{line_str}" for line_str in lines)
            hunks = parse_patch_to_hunks(fake_patch)
            changed_files.append(
                ChangedFile(
                    filename=file.replace("\\", "/"),
                    status="modified",
                    additions=len(lines),
                    deletions=0,
                    patch=fake_patch,
                    hunks=hunks,
                )
            )
            pr_title = f"Local File Review: {file}"
        else:
            # Run git diff against base branch or HEAD
            diff_ref = base_branch
            if base or os.getenv("GITHUB_BASE_REF"):
                check_local = subprocess.run(["git", "rev-parse", "--verify", diff_ref], capture_output=True, text=True, check=False)
                if check_local.returncode != 0:
                    check_remote = subprocess.run(["git", "rev-parse", "--verify", f"origin/{diff_ref}"], capture_output=True, text=True, check=False)
                    if check_remote.returncode == 0:
                        diff_ref = f"origin/{diff_ref}"
                git_diff_cmd = ["git", "diff", f"{diff_ref}...HEAD"]
            else:
                git_diff_cmd = ["git", "diff", "HEAD"]

            try:
                diff_res = subprocess.run(git_diff_cmd, capture_output=True, text=True, check=False)
                raw_diff = diff_res.stdout
                if not raw_diff.strip():
                    # Check working tree vs index
                    diff_res2 = subprocess.run(["git", "diff"], capture_output=True, text=True, check=False)
                    raw_diff = diff_res2.stdout
                changed_files = parse_unified_diff(raw_diff)
            except Exception as e:
                console.print(f"[bold red]Git command failed: {e}[/bold red]")
                raise typer.Exit(code=1)

            # Get current commit SHA if not set
            if head_sha == "HEAD":
                try:
                    sha_res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
                    if sha_res.returncode == 0:
                        head_sha = sha_res.stdout.strip()
                except Exception:
                    pass

    if not changed_files:
        console.print("[green]No changes detected to review.[/green]")
        raise typer.Exit(code=0)

    # Build review context
    ctx_builder = ContextBuilder(app_config, repo_root)
    context = ctx_builder.build_review_context(
        repo_owner=owner,
        repo_name=repo_name,
        pr_number=env_pr or 0,
        pr_title=pr_title,
        pr_description=pr_description,
        base_branch=base_branch,
        head_branch=head_branch,
        commit_sha=head_sha,
        changed_files=changed_files,
    )

    orchestrator = ReviewOrchestrator(
        config=app_config,
        github_client=gh_client,
        repo_root=repo_root,
    )

    result, status = orchestrator.run_review(context, dry_run=dry_run or (not gh_client.token))

    # Display results in CLI
    console.print("\n")
    console.print(Panel.fit(f"[bold]Review Decision: {result.decision.value.upper()} | Status: {status.value}[/bold]"))
    console.print(f"[italic]{result.summary}[/italic]\n")

    if result.findings:
        table = Table(title="Review Findings", show_header=True, header_style="bold cyan")
        table.add_column("Severity", width=12)
        table.add_column("Category", width=15)
        table.add_column("Location", width=25)
        table.add_column("Title")

        for f in result.findings:
            loc = f"{f.file}:{f.line}" if f.line is not None else f.file
            sev_style = "bold red" if f.severity in ("critical", "high") else ("yellow" if f.severity == "medium" else "blue")
            table.add_row(
                f"[{sev_style}]{f.severity.emoji} {f.severity.value.upper()}[/{sev_style}]",
                f.category.display_name,
                loc,
                f.title,
            )
        console.print(table)
    else:
        console.print("[bold green]No issues identified by reviewer.[/bold green]")

    if status == CheckStatusEnum.FAIL:
        raise typer.Exit(code=1)


@app.command(name="handle-comment")
def handle_comment(
    event_path: Path | None = typer.Option(
        None,
        "--event-path",
        "-e",
        help="Path to GitHub Actions event payload JSON file ($GITHUB_EVENT_PATH).",
    ),
) -> None:
    """Process an issue_comment event payload and dispatch JIAN interactive commands."""
    from ai_reviewer.commands import CommandDispatcher

    path_str = os.getenv("GITHUB_EVENT_PATH")
    path = event_path or (Path(path_str) if path_str else None)
    if not path or not path.is_file():
        console.print("[red]Error: GITHUB_EVENT_PATH not set or file does not exist.[/red]")
        raise typer.Exit(code=1)

    try:
        with open(path, encoding="utf-8") as f:
            event_payload = json.load(f)
    except Exception as err:
        console.print(f"[red]Error parsing event JSON: {err}[/red]")
        raise typer.Exit(code=1)

    dispatcher = CommandDispatcher()
    res = dispatcher.handle_event(event_payload)
    console.print(f"[green]Command processing result: {res}[/green]")


@app.command()
def dispatch() -> None:
    """Automatically detect event type from GITHUB_EVENT_NAME and execute review or command."""
    event_name = os.getenv("GITHUB_EVENT_NAME", "pull_request")
    if event_name == "issue_comment":
        handle_comment(None)
    else:
        review()


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind server to"),
    port: int | None = typer.Option(None, "--port", "-p", help="Port to listen on (defaults to $PORT or 8000)"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for local development"),
) -> None:
    """Start the GitHub App webhook receiver server."""
    import uvicorn

    actual_port = port if port is not None else int(os.getenv("PORT", "8000"))
    console.print(Panel.fit(f"[bold blue]Starting GitHub App Webhook Server on {host}:{actual_port}[/bold blue]"))
    uvicorn.run("ai_reviewer.app.server:create_app", host=host, port=actual_port, factory=True, reload=reload)


def main() -> None:
    app()


if __name__ == "__main__":
    main()

