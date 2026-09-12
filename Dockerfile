# Multi-stage Dockerfile for RPA Backend
# Stage 1: Build dependencies
FROM python:3.12-slim as builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim as runtime

# Create non-root user
RUN groupadd -r rpa && useradd -r -g rpa -d /app -s /sbin/nologin rpa

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/rpa_runs /app/artifacts /app/data \
    && chown -R rpa:rpa /app

# Switch to non-root user
USER rpa

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RPA_MODE=demo \
    PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8000/health'); assert r.status_code == 200"

# Run the application
CMD ["uvicorn", "rpa.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
