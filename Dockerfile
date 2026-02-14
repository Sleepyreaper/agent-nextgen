FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Run with Gunicorn
CMD ["gunicorn", "--workers=1", "--threads=2", "--worker-class=gthread", "--timeout=60", "--bind=0.0.0.0:8000", "--access-logfile=-", "--error-logfile=-", "wsgi:app"]
