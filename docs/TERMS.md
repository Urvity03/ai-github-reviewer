# Terms of Service for JIAN 鉴

**Effective Date:** September 17, 2026  
**Last Updated:** September 17, 2026  

*Notice: These Terms of Service outline the terms and conditions governing the use of JIAN 鉴. They are provided for transparency to developers and repository maintainers and do not constitute formal legal counsel.*

---

## 1. Agreement to Terms

By installing the **JIAN 鉴** GitHub App on your GitHub account or repository, you agree to be bound by these Terms of Service. If you do not agree with these terms, do not install or use the App.

---

## 2. Description of Service

JIAN 鉴 is an automated software tool that analyzes code changes in GitHub Pull Requests using static analysis and generative AI models (Google Gemini). It publishes advisory feedback, code quality suggestions, inline comments, and check runs.

To provide these reviews, repository content (including git diffs, changed file snippets, and PR descriptions) is transmitted over TLS to third-party infrastructure (Render hosting and Google Gemini API).

---

## 3. Important AI Disclaimer: Advisory Nature of Outputs

> [!IMPORTANT]
> **ALL OUTPUTS PRODUCED BY JIAN 鉴 ARE ADVISORY ONLY.**
> 
> Generative AI models can occasionally make mistakes, misunderstand architectural intent, or produce inaccurate suggestions (hallucinations).
> 
> - **Human Responsibility**: You (and your engineering team) remain solely responsible for reviewing, testing, verifying, and deciding whether to merge or reject any code or recommendations provided by JIAN.
> - **No Replacement for Human Review**: JIAN is designed to assist human code reviewers, not replace critical human engineering judgment, security audits, or comprehensive test suites.
> - **Zero Liability for Merged Code**: Under no circumstances shall JIAN or its authors be liable for any defects, bugs, outages, security vulnerabilities, or damages resulting from code written, modified, or merged based on JIAN recommendations.

---

## 4. Acceptable Use

When using JIAN 鉴, you agree that you will not:
1. Submit code or comments intentionally designed to perform prompt injection attacks, jailbreaks, or bypass review policies.
2. Abuse, flood, or trigger excessive automated webhooks designed to overload our backend infrastructure (rate limits are enforced).
3. Use JIAN to process code that violates applicable laws, contains malware, or infringes intellectual property rights.

---

## 5. Modifications and Service Availability

- We reserve the right to modify, suspend, or discontinue JIAN 鉴 at any time without prior notice.
- JIAN 鉴 is provided on a best-effort basis without uptime guarantees or Service Level Agreements (SLAs). The public demonstration instance is hosted on Render's free tier, which may spin down during periods of inactivity and incur cold start latency, temporary unavailability, or rate limits.

---

## 6. Disclaimer of Warranties

JIAN 鉴 IS PROVIDED \"AS IS\" AND \"AS AVAILABLE\", WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.

---

## 7. Limitation of Liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW, IN NO EVENT SHALL JIAN 鉴, ITS CREATORS, OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES ARISING OUT OF OR IN CONNECTION WITH YOUR USE OF THE SERVICE.

---

## 8. Termination

You may terminate these terms at any time simply by uninstalling JIAN 鉴 from your GitHub account. Upon uninstallation, all access permissions are terminated immediately by GitHub.

---

## 9. Contact

If you have questions about these Terms of Service, please contact us via our GitHub repository:  
https://github.com/Urvity03/ai-github-reviewer/issues
