# Production-ready, secure Docker container for AI Reviewer
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install git for diff parsing and curl for healthchecks
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -g 1001 reviewer && \
    useradd -u 1001 -g reviewer -s /bin/bash -m reviewer

WORKDIR /app

# Copy project metadata and application source code
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install application and production runtime dependencies
RUN pip install --no-cache-dir .

# Switch to non-root user
USER reviewer

# Expose default webhook server port
EXPOSE 8000

# Container healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Default entrypoint to start webhook server
ENTRYPOINT ["ai-reviewer"]
CMD ["serve", "--host", "0.0.0.0"]
