"""Formatting utilities for GitHub inline comments and markdown summary comments."""

from __future__ import annotations

from ai_reviewer.models.review import (
    CheckStatusEnum,
    DeterministicCheckResult,
    ReviewFinding,
    ReviewResult,
    SeverityEnum,
)

SUMMARY_MARKER = "<!-- ai-reviewer-summary -->"


def format_inline_comment(finding: ReviewFinding) -> str:
    """Format an inline review finding for GitHub PR line comments."""
    emoji = finding.severity.emoji
    sev_str = finding.severity.value.upper()
    cat_str = finding.category.display_name

    body = f"{emoji} **{sev_str} — {cat_str}**\n\n"
    body += f"### {finding.title}\n\n"
    body += f"{finding.description}\n\n"

    if finding.suggested_fix:
        body += f"**Suggested Fix:**\n```suggestion\n{finding.suggested_fix}\n```\n"

    body += f"\n*Reviewed by JIAN 鉴 • Confidence: {int(finding.confidence * 100)}% | [Rule: {finding.category.value}]*"
    return body


def format_summary_comment(
    result: ReviewResult,
    deterministic_results: list[DeterministicCheckResult],
    commit_sha: str,
    unattached_findings: list[ReviewFinding],
    check_status: CheckStatusEnum,
) -> str:
    """Format the full bot summary comment in GitHub Flavored Markdown."""
    lines: list[str] = [SUMMARY_MARKER]
    lines.append("## 🤖 JIAN 鉴 — AI Code Review")
    lines.append("")

    # 1. Overall Status
    status_icons = {
        CheckStatusEnum.PASS: "✅ **All Checks Passed**",
        CheckStatusEnum.WARN: "⚠️ **Warnings Found**",
        CheckStatusEnum.FAIL: "❌ **Changes Requested / Check Failed**",
        CheckStatusEnum.ERROR: "🚨 **Review Execution Error**",
    }
    lines.append("### Overall")
    lines.append(status_icons.get(check_status, "💬 **Review Completed**"))
    lines.append("")
    lines.append(f"> {result.summary.strip()}")
    lines.append("")

    # 2. Findings Count Breakdown
    counts: dict[SeverityEnum, int] = {
        SeverityEnum.CRITICAL: 0,
        SeverityEnum.HIGH: 0,
        SeverityEnum.MEDIUM: 0,
        SeverityEnum.LOW: 0,
        SeverityEnum.INFO: 0,
    }
    for f in result.findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    total_findings = sum(counts.values())
    lines.append("### Findings")
    if total_findings == 0:
        lines.append("🎉 No issues identified! Code is clean.")
    else:
        lines.append(
            f"{SeverityEnum.CRITICAL.emoji} {counts[SeverityEnum.CRITICAL]} Critical &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"{SeverityEnum.HIGH.emoji} {counts[SeverityEnum.HIGH]} High &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"{SeverityEnum.MEDIUM.emoji} {counts[SeverityEnum.MEDIUM]} Medium &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"{SeverityEnum.LOW.emoji} {counts[SeverityEnum.LOW]} Low &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"{SeverityEnum.INFO.emoji} {counts[SeverityEnum.INFO]} Info"
        )
    lines.append("")

    # 3. Highlighted Findings (grouped by severity)
    for sev in [SeverityEnum.CRITICAL, SeverityEnum.HIGH, SeverityEnum.MEDIUM, SeverityEnum.LOW, SeverityEnum.INFO]:
        sev_findings = [f for f in result.findings if f.severity == sev]
        if sev_findings:
            lines.append(f"### {sev.emoji} {sev.value.capitalize()} Issues")
            for f in sev_findings:
                loc = f"`{f.file}:{f.line}`" if f.line is not None else f"`{f.file}`"
                lines.append(f"**{f.title}** ({loc})")
                lines.append(f"{f.description}")
                if f.suggested_fix:
                    lines.append(f"💡 *Fix*: `{f.suggested_fix}`")
                lines.append("")

    # 4. Unattached / File-level Findings Note
    if unattached_findings:
        lines.append("<details><summary>📁 File-level / General Observations</summary>")
        lines.append("")
        for f in unattached_findings:
            lines.append(f"- **[{f.severity.value.upper()}] {f.title}** (`{f.file}`): {f.description}")
        lines.append("</details>")
        lines.append("")

    # 5. Deterministic Checks Table
    lines.append("### Automated Checks")
    lines.append("| Check | Status | Details |")
    lines.append("| :--- | :--- | :--- |")
    status_emojis = {
        "passed": "✅ Passed",
        "failed": "❌ Failed",
        "skipped": "⏭️ Skipped",
        "not_configured": "⚪ Not Configured",
    }
    for check in deterministic_results:
        disp_status = status_emojis.get(check.status, check.status.capitalize())
        lines.append(f"| **{check.name}** | {disp_status} | {check.details} |")
    lines.append("")

    # 6. Footer & Commit Info
    short_sha = commit_sha[:8] if len(commit_sha) >= 8 else commit_sha
    lines.append("---")
    lines.append(f"Reviewed commit: `{short_sha}`  •  *JIAN 鉴 AI-generated review — human validation is still recommended.*")

    return "\n".join(lines)
