#!/bin/bash
# Startup script for Azure App Service
# Ensures Python packages are installed before starting gunicorn

set -e

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting application startup script..."

# Use Python from the App Service environment if available
if [ -f "/opt/python/3.11.14/bin/python" ]; then
    PYTHON_EXE="/opt/python/3.11.14/bin/python"
    PIP_EXE="/opt/python/3.11.14/bin/pip"
elif [ -f "/usr/bin/python3" ]; then
    PYTHON_EXE="/usr/bin/python3"
    PIP_EXE="/usr/bin/pip3"
else
    PYTHON_EXE="python"
    PIP_EXE="pip"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Using Python: $PYTHON_EXE"

# Install packages from requirements.txt (skip if already installed)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Ensuring Python dependencies are installed..."
$PIP_EXE install -q --no-cache-dir -r requirements.txt 2>/dev/null || true

# Set up any required environment
export PYTHONUNBUFFERED=1

# Start gunicorn
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting gunicorn..."
exec gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 2 --threads 4 --worker-class=gthread wsgi:app
