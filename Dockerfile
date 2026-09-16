# Production-ready, secure Docker container for AI Reviewer
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install git for diff parsing
RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -g 1001 reviewer && \
    useradd -u 1001 -g reviewer -s /bin/bash -m reviewer

WORKDIR /app

# Copy dependency definition
COPY pyproject.toml .

# Install dependencies including ruff and pytest
RUN pip install --no-cache-dir .[dev]

# Copy application source code
COPY src/ /app/src/
RUN pip install --no-cache-dir -e .

# Switch to non-root user
USER reviewer

# Expose default webhook server port
EXPOSE 8000

# Default entrypoint to start webhook server
ENTRYPOINT ["ai-reviewer"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
