# ── Build stage ──
# Install build tools and compile pip packages; these won't ship to production.
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ──
FROM python:3.11-slim

WORKDIR /app

# Only runtime libs — no compilers, no dev headers
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built Python packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Run as non-root user (fixes #38 — container previously ran as root)
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser \
    && chown -R appuser:appgroup /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Gunicorn — single worker for container mode (scale via replicas).
# Override defaults from gunicorn.conf.py via environment variables.
ENV GUNICORN_WORKERS=1 GUNICORN_THREADS=2
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
