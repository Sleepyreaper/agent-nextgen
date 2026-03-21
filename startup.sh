#!/bin/bash
# Startup script for Azure App Service
# Oryx build installs packages into antenv; this script activates it and starts gunicorn

# Do NOT use set -e — optional steps (ffmpeg, opencv) failing must not crash the app
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting application startup script..."

# Activate the Oryx-built virtual environment if it exists
ANTENV="/home/site/wwwroot/antenv"
ORYX_PKG="/home/site/wwwroot/__oryx_packages__"

# Detect Python version for fallback paths
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "3.12")

if [ -d "$ANTENV" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Activating antenv virtual environment..."
    source "$ANTENV/bin/activate"
elif [ -d "$ORYX_PKG" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Using Oryx packages directory..."
    export PYTHONPATH="$ORYX_PKG/lib/python${PY_VER}/site-packages:$PYTHONPATH"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No antenv found — installing packages with pip..."
    pip install --user -r requirements.txt 2>&1 | tail -10 || echo "  pip install had errors"
    export PYTHONPATH="$HOME/.local/lib/python${PY_VER}/site-packages:$PYTHONPATH"
fi

# Verify key imports
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Verifying key packages..."
python -c "import requests; print('  requests OK')" || echo "  requests MISSING"
python -c "import flask; print('  flask OK')" || echo "  flask MISSING"
python -c "import cv2; print('  opencv OK')" || echo "  opencv MISSING (video analysis unavailable)"

# Ensure ffmpeg is available for Mirabel video audio extraction (best-effort, non-fatal)
if command -v ffmpeg &>/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ffmpeg available: $(ffmpeg -version 2>&1 | head -1)"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ffmpeg not found — attempting install (non-fatal)..."
    (apt-get update -qq && apt-get install -y -qq ffmpeg 2>&1 | tail -3) || echo "  ffmpeg install failed (audio transcription unavailable — non-fatal)"
fi

# Increase nginx client_max_body_size so chunked video upload endpoint
# is not blocked even if a single chunk somehow exceeds the default limit.
# (Each chunk is ≤4 MB but this adds a safety margin.)
NGINX_CONF="/etc/nginx/sites-available/default"
if [ -f "$NGINX_CONF" ]; then
    if ! grep -q 'client_max_body_size 100M' "$NGINX_CONF" 2>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Increasing nginx client_max_body_size to 100 MB..."
        sed -i '/server {/a\    client_max_body_size 100M;' "$NGINX_CONF" 2>/dev/null || true
        nginx -s reload 2>/dev/null || true
    fi
fi

export PYTHONUNBUFFERED=1

# Start gunicorn
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting gunicorn..."
exec gunicorn -c gunicorn.conf.py wsgi:app
# restart trigger
