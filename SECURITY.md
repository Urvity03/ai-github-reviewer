# Security Policy for JIAN 鉴

The JIAN 鉴 engineering team takes the security of our GitHub App and the repositories it inspects very seriously.

---

## 1. Supported Versions

We actively support and provide security patches for the latest version running on origin/master and our production Render deployment:

| Version | Supported |
| :--- | :---: |
| Latest (master) | ✅ Yes |
| Production Container (jian-ai-reviewer.onrender.com) | ✅ Yes |
| Legacy / Older Commits | ❌ No |

---

## 2. Reporting a Vulnerability

If you discover a security vulnerability, please do **NOT** open a public issue.

Instead, please report it privately:
1. **GitHub Private Vulnerability Reporting**:
   Navigate to the [Security Advisories](https://github.com/Urvity03/ai-github-reviewer/security/advisories/new) tab on our repository and click **Report a vulnerability**.
2. **Direct Email**:
   Send an email with details, reproduction steps, and potential impact to:  
   📧 	yagiurvi26@gmail.com

---

## 3. What to Include in Your Report

To help us triage and resolve the issue quickly, please provide:
- A clear description of the vulnerability.
- Steps to reproduce the issue (proof of concept, curl command, or sample PR).
- Potential impact (e.g., credential exposure, prompt injection breakout, denial of service).
- Any proposed remediations if available.

---

## 4. Our Commitment

- We will acknowledge receipt of your vulnerability report within **48 hours**.
- We will provide a timeline for assessing and fixing the issue.
- Once fixed, we will deploy the remediation to production and publish an advisory crediting your responsible disclosure (unless you prefer anonymity).
