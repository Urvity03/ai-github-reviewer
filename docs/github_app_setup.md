# JIAN 鉴 — GitHub App Configuration & Deployment Guide

This guide walks you through registering, configuring, and deploying **JIAN 鉴** as a public, installable GitHub App.

---

## 1. Registering the GitHub App on GitHub

1. Navigate to your GitHub account or organization settings:
   - Personal account: **GitHub Settings** → **Developer Settings** → **GitHub Apps** → **New GitHub App**
   - Organization: **Organization Settings** → **Developer Settings** → **GitHub Apps** → **New GitHub App**
2. Fill in **Basic Information**:
   - **GitHub App name**: `JIAN 鉴` (or `JIAN 鉴 — AI Code Reviewer` if the short name is taken in your scope)
   - **Homepage URL**: `https://github.com/Urvity03/ai-github-reviewer`
   - **Description**: `AI-powered GitHub Pull Request Reviewer`
3. Upload **App Avatar (Profile Picture)**:
   - Click **Upload a logo...** and select `assets/jian_avatar.png` (candidate avatar).
   - > [!WARNING]
   > **Candidate Avatar Licensing Notice**: The candidate test avatar depicts Gian (Takeshi Gouda) from *Doraemon* (© Fujiko F. Fujio / Shogakukan). While suitable for internal and controlled testing, an original custom mascot must replace it prior to broad commercial/public distribution.
4. Configure **Webhook**:
   - **Active**: Check `[x] Active`
   - **Webhook URL**: `https://<your-domain>/webhooks/github` (or your tunneling URL for local dev)
   - **Webhook secret**: Generate a cryptographically secure random string (e.g., `openssl rand -hex 32`) and save it.
   - **SSL verification**: Select `Enable SSL verification` (mandatory in production).

---

## 1.1 Automated Registration via GitHub App Manifest

Alternatively, you can create the App with all permissions and events pre-filled using `app.manifest.json`:
1. Open the [app.manifest.json](../app.manifest.json) file.
2. Replace `YOUR-DEPLOYED-DOMAIN` with your actual public HTTPS domain.
3. Submit the manifest to GitHub via the GitHub App Manifest flow to register in one click.

---

## 2. Repository Permissions & Rationale

JIAN follows the principle of least privilege. Configure the following permissions under **Repository permissions**:

| Permission | Access | Why It Is Needed |
| :--- | :--- | :--- |
| **Pull requests** | **Read & write** | Required to read PR diffs, changed files, and publish inline review annotations and PR reviews. |
| **Issues** | **Read & write** | **Crucial:** GitHub delivers PR discussion comments (`@JIAN /review`, `@JIAN /explain`, `@JIAN /ping`, `@JIAN /help`) under the `issue_comment` event. Read & write access allows receiving these events and posting conversational replies. |
| **Checks** | **Read & write** | Allows JIAN to create Check Runs (`AI Code Review`) on pull request commits with pass/fail/warn conclusions and diagnostic annotations. |
| **Contents** | **Read-only** | Allows JIAN to fetch file contents at specific commit SHAs and read `.ai-reviewer.yml` repository configuration. |
| **Metadata** | **Read-only** | Automatically set by GitHub for all Apps to access basic repository information. |
| **Commit statuses** | **Read & write** | Used as an automated fallback when Check Run creation is restricted or commit statuses are explicitly preferred. |

> [!IMPORTANT]
> **No other permissions are required.** All other permissions (Administration, Actions, Workflows, Secrets, Deployments, Packages, Code scanning alerts, Dependabot alerts, Organization permissions) must remain **None / Disabled**.

---

## 3. Webhook Event Subscriptions

Under **Subscribe to events**, select:
- `[x] Pull request` (triggers automatic review on `opened`, `synchronize`, `reopened`, `ready_for_review`)
- `[x] Issue comment` (triggers interactive slash commands `@JIAN /ping`, `@JIAN /help`, `@JIAN /review`, `@JIAN /explain`)

---

## 4. Installation Scope (Multi-Tenancy & Public Access)

Under **Where can this GitHub App be installed?**:
- Select **Any account** to allow public installation by any GitHub user or organization.

After creating the app:
1. Note the numeric **App ID** displayed on the General settings page (e.g., `123456`).
2. Scroll to **Private keys** and click **Generate a private key**.
3. Download the generated `.pem` file.

---

## 5. Environment Variables

Configure the following environment variables on your server or container:

```bash
# GitHub App Credentials
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nMIIEpgIBAAKCAQEA..."
GITHUB_WEBHOOK_SECRET="your-webhook-secret"

# AI Provider (Google Gemini Free Tier)
GEMINI_API_KEY="AIzaSy..."
GEMINI_MODEL="gemini-3.6-flash"  # Default: gemini-3.6-flash

# Server Configuration (Optional)
HOST="0.0.0.0"
PORT="8000"
```

> [!NOTE]
> `GITHUB_PRIVATE_KEY` supports raw PEM strings, PEM strings with literal `\n` line breaks, base64-encoded PEM strings, or path-based loading via `GITHUB_APP_PRIVATE_KEY_PATH`.

---

## 6. Local Development & Testing via HTTPS Tunnel

For local development, expose the FastAPI server using a secure tunneling tool (such as [ngrok](https://ngrok.com) or [Cloudflare Tunnel](https://developers.cloudflare.com/pages/how-to/preview-with-cloudflare-tunnel/)):

```
GitHub Webhook
      │
      ▼ (HTTPS)
https://xyz.ngrok-free.app/webhooks/github
      │
      ▼ (HTTP)
http://localhost:8000/webhooks/github
      │
      ▼
FastAPI Server (uvicorn)
```

### Step 1: Start the JIAN server locally
```powershell
ai-reviewer serve --host 0.0.0.0 --port 8000 --reload
# Or directly via uvicorn:
uvicorn ai_reviewer.app.server:create_app --host 0.0.0.0 --port 8000 --reload --factory
```

### Step 2: Open an HTTPS tunnel
```bash
ngrok http 8000
```
Copy the forwarding HTTPS URL (e.g., `https://abcdef123456.ngrok-free.app`).

### Step 3: Update Webhook URL in GitHub App Settings
Set the Webhook URL to:
```
https://abcdef123456.ngrok-free.app/webhooks/github
```

### Step 4: Test Endpoints
Verify health check:
```bash
curl http://localhost:8000/health
# Response: {"status":"healthy","app":"ai-github-reviewer","version":"0.1.0"}
```

---

## 7. Production Deployment (Docker)

JIAN includes an optimized, production-ready `Dockerfile` with non-root security and a container health check.

### Build the image:
```bash
docker build -t jian-reviewer:latest .
```

### Run the container:
```bash
docker run -d \
  --name jian-reviewer \
  -p 8000:8000 \
  -e GITHUB_APP_ID="123456" \
  -e GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..." \
  -e GITHUB_WEBHOOK_SECRET="your-webhook-secret" \
  -e GEMINI_API_KEY="AIzaSy..." \
  -e GEMINI_MODEL="gemini-3.6-flash" \
  jian-reviewer:latest
```

### Health Check:
The container automatically monitors server liveness via `GET /health`:
```bash
docker inspect --format='{{json .State.Health.Status}}' jian-reviewer
# Output: "healthy"
```

---

## 8. Multi-Tenant Installation Isolation

When users install JIAN on their repositories:
1. GitHub sends a webhook with `installation.id`.
2. JIAN authenticates as the GitHub App using RS256 JWTs and requests an **installation access token** strictly scoped to that installation ID.
3. The token is cached safely in-memory with automatic refresh when expiring.
4. Tenant A's reviews and commands **never** use Tenant B's credentials or repository access.
