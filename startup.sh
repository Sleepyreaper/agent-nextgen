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

# Install packages to a writable target directory
PACKAGES_DIR="/home/site/wwwroot/.python_packages/lib/site-packages"
mkdir -p "$PACKAGES_DIR"
export PYTHONPATH="$PACKAGES_DIR:$PYTHONPATH"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Installing dependencies to $PACKAGES_DIR..."
$PIP_EXE install --target="$PACKAGES_DIR" --upgrade -r requirements.txt 2>&1 | tail -5 || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: pip install had errors, trying --user fallback..."
    $PIP_EXE install --user -r requirements.txt 2>&1 | tail -5 || true
}

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Verifying key packages..."
$PYTHON_EXE -c "import requests; print('  requests OK')" || echo "  requests MISSING"
$PYTHON_EXE -c "import flask; print('  flask OK')" || echo "  flask MISSING"

# Set up any required environment
export PYTHONUNBUFFERED=1

# Start gunicorn
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting gunicorn..."
exec gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 2 --threads 4 --worker-class=gthread wsgi:app
