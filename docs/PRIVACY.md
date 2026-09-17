# Privacy Policy for JIAN 鉴

**Effective Date:** September 17, 2026  
**Last Updated:** September 17, 2026  

> [!NOTE]
> **Operational Transparency Notice**: This document is an operational policy provided by the project maintainers to clearly disclose technical data flows, third-party sub-processors, and hosting characteristics. It is not formal legal counsel and does not represent a certified compliance audit (such as SOC 2, ISO 27001, or GDPR certification).

---

## 1. Overview & Principles

**JIAN 鉴** ("we", "our", or "the App") is an automated GitHub Pull Request review tool. This Privacy Policy details how data flows when JIAN is installed on your GitHub repositories, what data JIAN itself handles, and how third-party infrastructure and AI sub-processors handle transmitted code.

Key architectural distinctions:
- **JIAN Application Storage**: JIAN itself does not persist or store repository source code, diffs, or secrets in any database or disk storage. All processing within JIAN occurs ephemerally in volatile memory.
- **Third-Party AI Transmission**: To generate code reviews, pull request metadata, diffs, and relevant source snippets are transmitted over TLS to the configured AI provider (currently Google Gemini).

---

## 2. Infrastructure & Third-Party Sub-processors

When JIAN processes a Pull Request, data interacts with three external platforms:

### A. GitHub (Source & Destination)
- **Role**: Source of repository metadata, webhook deliveries, and pull request diffs; destination for posted check runs, inline line annotations, and review summaries.
- **Data Shared**: Pull request metadata (titles, descriptions, comments, commit SHAs) and file diffs.
- **Terms**: Governed by the [GitHub Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-privacy-statement).

### B. Render (Cloud Hosting Infrastructure)
- **Role**: Hosts the JIAN container runtime and receives inbound HTTPS webhooks from GitHub.
- **Hosting Tier**: The public demonstration backend is hosted on **Render's Free Tier**, which spins down after 15 minutes of inactivity. The first request following an idle period may experience approximately one minute of cold-start latency.
- **Data Handled**: Inbound webhook payloads are received in memory. Render captures standard network and container execution logs (such as request timestamps, client IP addresses, HTTP status codes, and container stdout).
- **Terms**: Governed by the [Render Privacy Policy](https://render.com/privacy).

### C. Google Gemini API (AI Provider)
- **Role**: Provides generative machine learning analysis on code diffs to detect bugs, architectural defects, and security issues.
- **API Version**: Google Gemini API via official Google GenAI SDK.
- **Usage Limits**: Gemini API usage limits vary by model and usage tier. The public demonstration deployment currently uses the Gemini API Free Tier. For higher-volume usage, migrate the deployment to a paid Gemini API usage tier and monitor the model/project-specific quotas in Google AI Studio.
- **Important Data-Use Distinction (Free Tier vs. Paid Tier)**:
  - **Current Public Deployment (Free Tier)**: The public demonstration instance of JIAN currently utilizes Google's **Gemini API Free of Charge Tier**. According to [Google's Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms#data-use) and [Google Privacy Policy](https://policies.google.com/privacy), data submitted through the Free Tier may be read by human reviewers and used by Google to provide, maintain, improve, and develop Google products, services, and machine learning technologies. Identifier-stripping is applied by Google, but repository content submitted through the Free Tier is not exempt from model training or improvement.
  - **Self-Hosted / Paid Tier**: When self-hosting JIAN or configuring a paid Gemini API key (or Google Cloud Vertex AI), Google's Paid Service terms apply. Under Google's Paid Service terms, prompts and generated responses are not used to train Google foundational models.
  - **Recommendation**: If your repository contains proprietary, confidential, or sensitive intellectual property, do not install the public Free Tier demonstration instance. Instead, self-host JIAN using your own organization's paid Gemini API key or private LLM provider.

---

## 3. What JIAN Itself Stores vs. What It Does Not Store

### What JIAN Does NOT Persist
- **No Database**: JIAN operates without any relational database (e.g., PostgreSQL, MySQL), document store (e.g., MongoDB), or vector database.
- **No Persistent File Storage**: JIAN does not clone entire repositories, does not write code diffs to disk, and does not maintain persistent caches of your source code.
- **No Secret Storage**: JIAN never stores your repository's internal secrets, environment variables, or private keys.

### What JIAN Stores (Temporarily in Memory)
- **Ephemeral RAM Execution**: Git diffs and changed file contents fetched via the GitHub API exist solely in RAM during review execution (typically 10–30 seconds) and are immediately discarded by Python runtime garbage collection upon job completion.
- **Webhook Delivery Deduplication Cache**: Webhook delivery UUIDs (`X-GitHub-Delivery`) are tracked in an in-memory LRU/TTL cache for up to 1 hour strictly to reject duplicate webhook deliveries caused by network retries.
- **Rate Limiting State**: In-memory sliding-window request timestamps are maintained per repository/installation identifier to mitigate denial-of-service attempts.
- **Short-Lived Installation Tokens**: Temporary GitHub App installation access tokens (`ghs_...`) are cached in memory for up to 60 minutes to respect GitHub rate limits, protected by thread-safe locks, and discarded upon expiry.
- **Application Logs**: Container stdout logs record sanitized execution metadata (e.g., repository name, pull request number, delivery UUID, elapsed time, error codes). Source code, diffs, API keys, and authorization tokens are scrubbed and redacted from log output.

---

## 4. Information Accessed and Processed

When a Pull Request event occurs, JIAN accesses:
1. **Repository & PR Metadata**: Repository full name, PR number, base/head commit SHAs, PR title, and description.
2. **Changed Files & Diffs**: The git patch hunks for files altered in the PR, plus file contents fetched at the head commit for deterministic checks (Python AST parsing, compile checks, Ruff linting).
3. **Comment Content**: Issue/PR comments that explicitly mention `@JIAN` or `@jian-ai-code-reviewer` to execute supported slash commands (`/ping`, `/help`, `/review`, `/explain`).

JIAN does **not**:
- Access or read uninstalled repositories.
- Access untouched repository files outside the pull request scope.
- Read or collect personal user data beyond the public GitHub usernames present in the PR webhook.
- Inspect or modify repository settings or branch protection rules.

---

## 5. Security & Tenant Isolation

- **Tenant Isolation**: Temporary GitHub installation tokens are strictly partitioned by `installation.id`. Installation A has no ability to view or access repositories from Installation B.
- **HMAC Verification**: All incoming webhooks are validated using constant-time HMAC-SHA256 comparison against the configured GitHub webhook secret.
- **Prompt Isolation**: Untrusted pull request content is fenced within `<UNTRUSTED_PR_CONTENT>` tags with delimiter neutralization to prevent prompt injection from executing unauthorized instructions.
- **Encrypted Transport**: All communication with GitHub, Render, and Google Gemini uses TLS 1.2 or TLS 1.3 encryption in transit.

---

## 6. Data Revocation & Uninstallation

You maintain complete, immediate control over JIAN's access:
1. Navigate to **GitHub Settings > Applications > Installed GitHub Apps > JIAN 鉴**.
2. Click **Uninstall**.
3. GitHub immediately revokes the installation access token and stops delivering webhook events to JIAN.
4. Because JIAN does not maintain persistent customer databases or retained code archives on its own servers, no separate data deletion request is required on JIAN's infrastructure. Any data previously processed by external third parties (Render, Google) remains subject to their respective retention and deletion policies.

---

## 7. Contact & Questions

If you have questions about JIAN's architecture or data handling, please open an issue on our GitHub repository:  
https://github.com/Urvity03/ai-github-reviewer/issues
