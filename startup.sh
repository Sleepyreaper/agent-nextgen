#!/bin/bash
# Startup script for Azure App Service
# Ensures Python packages are installed before starting gunicorn

set -e

echo "Starting application startup script..."

# Install packages from requirements.txt if they're not already installed
echo "Installing Python dependencies..."
python -m pip install -q --no-cache-dir -r requirements.txt

# Set up any required environment
export PYTHONUNBUFFERED=1

# Start gunicorn
echo "Starting gunicorn..."
exec gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 2 --threads 4 --worker-class=gthread wsgi:app
