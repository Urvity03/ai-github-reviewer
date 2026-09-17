# Privacy Policy for JIAN 鉴

**Effective Date:** September 17, 2026  
**Last Updated:** September 17, 2026  

*Notice: This Privacy Policy outlines the data handling and technical architecture of JIAN 鉴. It is provided for complete transparency to repository owners and developers and does not constitute formal legal counsel.*

---

## 1. Overview

JIAN 鉴 (\"we\", \"our\", or \"the App\") is an automated AI-powered GitHub Pull Request reviewer. This policy explains what information JIAN processes when installed on your GitHub repositories, how that information is used, and how it is protected.

JIAN operates on a **zero-retention, ephemeral-processing principle**: your repository source code and commit contents are **never stored permanently** in databases or on physical disks by JIAN.

---

## 2. Information We Access and Process

When you install JIAN on a repository and open or update a Pull Request, GitHub transmits webhook events to our backend. JIAN accesses only the information necessary to perform code reviews:

1. **Webhook Metadata**:
   - Repository name, owner login, pull request number, and commit SHA.
   - GitHub installation ID (used exclusively to generate temporary, installation-scoped access tokens).
   - Pull request titles, descriptions, and comments mentioning @JIAN.
2. **Pull Request Content**:
   - Git diffs and patch contents for modified files.
   - File contents of changed files (fetched via GitHub REST API to perform syntax compilation and AST analysis).
3. **Information We Do NOT Collect**:
   - We do not access, clone, or read files outside the modified pull request.
   - We do not access non-installed repositories.
   - We do not collect personal identifying information (PII) beyond public GitHub usernames associated with PR events.
   - We do not access private repository secrets or CI/CD secrets.

---

## 3. How Information Is Used

Data received by JIAN is used strictly for:
- Generating automated code review comments and inline line annotations on the Pull Request.
- Publishing GitHub Check Runs (JIAN 鉴 — AI Code Review) reflecting review status.
- Responding to interactive commands (@JIAN /ping, @JIAN /help, @JIAN /review, @JIAN /explain).

---

## 4. AI Sub-processors (Google Gemini)

To provide code analysis, JIAN transmits the pull request metadata, git diff hunks, and relevant source snippets to **Google Gemini** (gemini-3.6-flash) via the official Google GenAI SDK:

- **Transmission**: Data is sent over encrypted TLS connections directly to Google's generative language endpoints.
- **Prompt Isolation**: Diff contents are wrapped in explicit untrusted fences (<UNTRUSTED_PR_CONTENT>) with delimiter neutralization to prevent prompt injection.
- **Model Training**: JIAN configures standard API calls. Under Google's enterprise and API terms of service, API inputs are not used to train generative models without customer consent.

---

## 5. Data Retention and Storage

- **Source Code**: **Zero permanent storage.** Changed files and diffs exist only in memory during the execution of the review job (typically 10–30 seconds) and are immediately discarded by Python garbage collection upon job completion.
- **Tokens**: GitHub App installation access tokens (ghs_...) are cached in memory for up to 60 minutes strictly to satisfy GitHub rate limits, protected by thread-safe memory locks, and are never written to disk or logs.
- **Logs**: Backend server logs record only delivery GUIDs, repository names, PR numbers, action types, and timing metrics. **Source code, secrets, API keys, and authorization tokens are strictly redacted from logs.**

---

## 6. Data Security and Isolation

- **Tenant Isolation**: Tokens and reviews are strictly partitioned by GitHub installation_id. Installation A can never access or view repositories belonging to Installation B.
- **HMAC Signature Verification**: All incoming webhooks are validated using constant-time HMAC-SHA256 comparison against a secret known only to GitHub and JIAN.
- **Transport Encryption**: All communication with GitHub and Google Gemini uses HTTPS (TLS 1.3/1.2).

---

## 7. How to Revoke Access & Uninstall

You have complete, immediate control over JIAN's access:
1. Navigate to **GitHub Settings > Applications > Installed GitHub Apps > JIAN 鉴**.
2. Click **Uninstall**.
3. GitHub immediately revokes the installation ID. JIAN can no longer generate access tokens, receive webhooks, or interact with your repositories. Because JIAN stores no repository code, no data deletion request is necessary.

---

## 8. Contact & Security Inquiries

For questions regarding this privacy policy or data handling practices, please open an issue on our GitHub repository:  
https://github.com/Urvity03/ai-github-reviewer/issues
