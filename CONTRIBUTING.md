# Contributing to JIAN 鉴

Thank you for your interest in improving **JIAN 鉴**! We welcome bug reports, feature requests, documentation improvements, and code contributions.

---

## Code of Conduct

Please be respectful, constructive, and collaborative in all discussions and pull requests.

---

## Local Development Setup

### 1. Prerequisites
- Python 3.11+
- Git
- (Optional) Docker

### 2. Clone and Install
`ash
git clone https://github.com/Urvity03/ai-github-reviewer.git
cd ai-github-reviewer

# Create and activate virtual environment
python -m venv .venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1

# Install in editable mode with development dependencies
pip install -e .[dev]
`

### 3. Running Linters and Tests
Before opening a pull request, ensure all linters and tests pass cleanly:
`ash
# Run Ruff linter
python -m ruff check .

# Run pytest suite
python -m pytest tests/ -q
`

---

## Pull Request Guidelines

1. **Focused Changes**: Keep PRs focused on a single feature, bug fix, or improvement.
2. **Add Tests**: All bug fixes and new features must include regression unit tests in 	ests/.
3. **Preserve Compatibility**: Do not break existing /ping, /help, /review, /explain commands or webhook schemas.
4. **No Secrets**: Never commit private keys, .pem files, API keys, or credentials.
