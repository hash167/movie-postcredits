# Simple single-stage Dockerfile (easier to debug)
# Use this if the multi-stage build has issues

FROM python:3.9-slim

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip list | grep gunicorn

# Copy application code
COPY --chown=appuser:appuser . .

# Create exports directory
RUN mkdir -p /app/exports && chown appuser:appuser /app/exports

# Switch to non-root user
USER appuser

# Environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision=$GIT_SHA \
      org.opencontainers.image.source=https://github.com/hash167/movie-postcredits

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Live API process. Pass --build-arg GIT_SHA=$(git rev-parse HEAD).
CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]

