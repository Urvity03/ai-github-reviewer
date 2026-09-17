# JIAN 鉴 — AI-Powered GitHub Pull Request Reviewer

[![Install JIAN 鉴](https://img.shields.io/badge/GitHub%20App-Install%20JIAN%20%E9%89%B4-2ea44f?style=for-the-badge&logo=github)](https://github.com/apps/jian-ai-code-reviewer)
[![Production Status](https://img.shields.io/badge/Production%20Backend-Render-brightgreen?style=flat-square)](https://jian-ai-reviewer.onrender.com/health)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg?style=flat-square)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json&style=flat-square)](https://github.com/astral-sh/ruff)

**JIAN 鉴** is a production-grade, public GitHub App that performs automated, intelligent AI code reviews on GitHub Pull Requests.

It combines **deterministic static checks** (AST parsing, Python compilation, secret scanning, Ruff linting, test suite discovery) with **Google Gemini 3.6 Flash** analysis, an **anti-hallucination diff validator**, **prompt-injection defenses**, and an **interactive bot command interface**.

---

## ⚡ Quick Start: Install JIAN 鉴

You do **not** need to configure API keys, write YAML workflows, or manage Personal Access Tokens (PATs).

👉 **[Click Here to Install JIAN 鉴 on GitHub](https://github.com/apps/jian-ai-code-reviewer)**

1. Click **Install** and choose your personal account or organization.
2. Select **All repositories** or pick specific repositories.
3. Open or update a Pull Request. JIAN automatically reviews your changes within seconds!

---

## 🤖 Important AI Advisory Disclaimer

> [!IMPORTANT]
> **ALL CODE REVIEWS AND RECOMMENDATIONS PRODUCED BY JIAN 鉴 ARE ADVISORY ONLY.**
> 
> JIAN 鉴 is designed to augment human code review, catch common bugs, and accelerate engineering velocity. It does **not** replace human engineering judgment, dedicated security audits, or comprehensive test suites.
> 
> Developers and repository maintainers are solely responsible for reviewing, testing, verifying, and deciding whether to merge or reject any code or recommendations provided by JIAN.

---

## 🌟 Key Features

- **Automated Pull Request Reviews**: Automatically reviews on `opened`, `synchronize`, `reopened`, and `ready_for_review`.
- **Ephemeral In-Memory Processing**: Diffs and code changes are processed strictly in volatile memory by JIAN and are **never stored in databases or on disk by JIAN**.
- **Anti-Hallucination Guardrails**: Every finding is validated against real lines within actual git diff hunks. Hallucinated line numbers or imaginary functions are stripped before publication.
- **Prompt-Injection Defense**: Diffs, commit messages, and PR descriptions are isolated within `<UNTRUSTED_PR_CONTENT>` fences with delimiter neutralization. Attempts to override review guidelines are trapped and flagged as critical security findings.
- **Deterministic Pre-Checks**: Catches Python syntax compilation errors, hard-coded secrets (AWS, GitHub, Google/Gemini, Anthropic, OpenAI, JWTs), and Ruff lint violations alongside LLM analysis.
- **Deduplicated Feedback**: Updates a single consolidated review summary across pushes rather than spamming conversation timelines with duplicate comments.
- **Official GitHub Checks**: Publishes check runs (`JIAN 鉴 — AI Code Review`) with `success`, `failure`, or `neutral` conclusions directly in GitHub's PR merge box.
- **Interactive Slash Commands**: Developers can query JIAN directly in PR discussions using `@JIAN /ping`, `@JIAN /help`, `@JIAN /review`, and `@JIAN /explain`.

---

## 🔄 Automatic PR Review Flow

```text
Developer Opens or Updates Pull Request
               │
               ▼ (HMAC-SHA256 Webhook Event)
JIAN Production Backend (Render HTTPS)
   ├── Verifies signature using constant-time HMAC-SHA256
   ├── Debounces duplicate deliveries via X-GitHub-Delivery ID
   ├── Rate-limits per installation (sliding-window DDoS protection)
   └── Coordinates concurrency per PR using thread-safe locks
               │
               ▼
Review Pipeline Execution
   ├── 1. Generates short-lived installation access token (scoped to repo only)
   ├── 2. Fetches remote git diff and changed files
   ├── 3. Executes deterministic checks (Syntax, Secrets, Ruff linter)
   ├── 4. Extracts AST context and maps related test suites
   ├── 5. Queries Google Gemini 3.6 Flash with structured Pydantic schema
   └── 6. Validates all findings against actual diff hunks (Anti-hallucination)
               │
               ▼
GitHub Pull Request Interface
   • Inline review comments posted on exact modified lines
   • Single consolidated summary table posted/updated
   • Check Run updated to SUCCESS or FAILURE
   • Visibly stamped as: jian-ai-code-reviewer [bot]
```

---

## 💬 Supported Interactive Commands

Mention JIAN in any issue or Pull Request discussion:

| Command | Scope | Description |
| :--- | :--- | :--- |
| `@JIAN /ping` | Issues & PRs | Confirms that JIAN 鉴 is alive, reports active AI provider, and measures latency. |
| `@JIAN /help` | Issues & PRs | Displays the interactive command reference and supported options. |
| `@JIAN /review` | PRs only | Manually triggers a fresh review of the PR head commit. |
| `@JIAN /explain` | PRs only | Explains existing findings in plain English. Reuses the latest JIAN summary without wasting extra Gemini tokens. |

*Note: Command parsing is case-insensitive and supports `@JIAN`, `@jian`, and `@jian-ai-code-reviewer`.*

---

## 🔒 Security & Data Handling

JIAN 鉴 is engineered around strict zero-trust and least-privilege principles:

- **JIAN Application Storage**: Your code is never written to a database or stored on disk by JIAN. It exists strictly in volatile memory during review execution and is discarded immediately upon completion.
- **Strict Multi-Tenant Isolation**: GitHub App access tokens are scoped exclusively to the specific `installation_id`. Installation A can never access or view repositories belonging to Installation B.
- **Credential Redaction**: All comments and summary outputs pass through an automated credential redactor before being posted to GitHub.
- **AI Sub-processor & Data Handling**:
  - Pull request diffs, changed file snippets, and descriptions are transmitted over TLS to Google Gemini for review inference.
  - **Free Tier Notice**: The public demonstration deployment operates on the [Google Gemini API Free Tier](https://ai.google.dev/gemini-api/terms#data-use). Under Google's Free Tier terms, submitted prompts and responses may be processed and used by Google to improve and train its products and services.
  - **Enterprise / Paid Tier**: When self-hosting JIAN with a paid Google Gemini API key or Vertex AI, Google's Paid Service terms apply, under which customer data is not used for model training.
  - See our [Privacy Policy](docs/PRIVACY.md) and [Google's Gemini API Terms](https://ai.google.dev/gemini-api/terms#data-use) for full details.

---

## 📋 Minimal Required GitHub Permissions

JIAN requests only the minimal permissions required to review pull requests:

| Permission | Access | Justification |
| :--- | :--- | :--- |
| **Pull requests** | Read & write | Fetch diffs and publish inline review comments. |
| **Checks** | Read & write | Publish JIAN 鉴 — AI Code Review check runs. |
| **Issues** | Read & write | Receive command events and reply to interactive commands (/ping, /explain). |
| **Contents** | Read-only | Read file contents at commit SHAs to run AST and syntax checks. |
| **Metadata** | Read-only | Mandatory base permission for all GitHub Apps to resolve repo names. |
| **Commit statuses** | Read & write | Fallback check status reporting if repository restricts Check Runs. |

*All other permissions (Administration, Workflows, Secrets, Packages, Deployments) are **Disabled**.*

---

## ⚙️ Optional Repository Configuration (.ai-reviewer.yml)

You can customize JIAN's review policies by adding an optional .ai-reviewer.yml file to your repository root:

`yaml
review:
  fail_on_severity: high       # critical, high, medium, low, none
  post_inline_comments: true
  min_inline_severity: medium
  max_inline_comments: 10

rules:
  syntax: true
  secrets: true
  ruff: true
  pytest: false
  ml: true

custom_rules:
  - \"Ensure all public API endpoints require authentication.\"
  - \"Do not allow raw SQL queries without parameterized inputs.\"

ignore_paths:
  - \"vendor/**\"
  - \"**/*.min.js\"
  - \"dist/**\"
`

---

## ⚠️ Limitations

- **Render Free Tier Spin-Down & Cold Starts**: The public demonstration backend is hosted on Render's Free tier, which spins down after 15 minutes of inactivity. The first webhook or request following an idle period may take 30–50 seconds to complete cold boot.
- **Large PR Truncation**: PRs modifying more than 100 files or 2,000 diff lines are truncated to protect model context windows and execution deadlines. Deterministic checks continue to run on modified files.
- **Draft PRs**: Draft PRs are automatically ignored until marked as "Ready for review".
- **Binary Files**: Images, compiled binaries, and lockfiles are ignored during AI analysis.

---

## 🔧 Troubleshooting

- **Bot does not comment on new PR**:
  - Verify that the PR is not in **Draft** state.
  - Verify that JIAN is installed on the repository via **Settings > Installed GitHub Apps**.
  - Check backend status at https://jian-ai-reviewer.onrender.com/health (allow 30-50s if the service is waking up from spin-down).
- **Bot does not respond to comments**:
  - Ensure your comment mentions @JIAN or @jian-ai-code-reviewer and includes a supported command like /ping or /review.
  - Bot-authored comments and automated bot replies are deliberately ignored to prevent infinite event loops.

---

## 🗑️ How to Uninstall

You can uninstall JIAN 鉴 at any time:
1. Go to your repository or account **Settings > Installed GitHub Apps > JIAN 鉴**.
2. Click **Uninstall**.
3. GitHub instantly revokes all access permissions. Because JIAN does not persist repository code or maintain a database, no data deletion request is necessary on JIAN's infrastructure.

---

## 📚 Legal & Policies

- [Privacy Policy](docs/PRIVACY.md) (https://jian-ai-reviewer.onrender.com/privacy)
- [Terms of Service](docs/TERMS.md) (https://jian-ai-reviewer.onrender.com/terms)
- [Security Policy & Vulnerability Reporting](SECURITY.md)
- [Contributing Guidelines](CONTRIBUTING.md)

---

## 📄 License

Distributed under the [MIT License](LICENSE).
