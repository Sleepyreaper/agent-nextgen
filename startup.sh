#!/bin/bash
# Startup script for Azure App Service
# Oryx build installs packages into antenv; this script activates it and starts gunicorn

set -e

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting application startup script..."

# Activate the Oryx-built virtual environment if it exists
ANTENV="/home/site/wwwroot/antenv"
ORYX_PKG="/home/site/wwwroot/__oryx_packages__"

if [ -d "$ANTENV" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Activating antenv virtual environment..."
    source "$ANTENV/bin/activate"
elif [ -d "$ORYX_PKG" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Using Oryx packages directory..."
    export PYTHONPATH="$ORYX_PKG/lib/python3.11/site-packages:$PYTHONPATH"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No antenv found — installing packages with pip..."
    pip install --user -r requirements.txt 2>&1 | tail -10
    export PYTHONPATH="$HOME/.local/lib/python3.11/site-packages:$PYTHONPATH"
fi

# Verify key imports
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Verifying key packages..."
python -c "import requests; print('  requests OK')" || echo "  requests MISSING"
python -c "import flask; print('  flask OK')" || echo "  flask MISSING"

export PYTHONUNBUFFERED=1

# Start gunicorn
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting gunicorn..."
exec gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 2 --threads 4 --worker-class=gthread wsgi:app
