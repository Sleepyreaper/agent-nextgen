#!/bin/bash
# Custom startup script for Azure App Service
# This ensures dependencies are installed before starting the app

echo "=== Custom Startup Script ==="
echo "Working directory: $(pwd)"
echo "Python version: $(python --version)"

# Check if packages are installed
if ! python -c "import openai" 2>/dev/null; then
    echo "⚠️  openai package not found, installing dependencies..."
    echo "Installing from requirements.txt..."
    
    # Install packages
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt --no-cache-dir
    
    echo "✓ Dependencies installed"
else
    echo "✓ Dependencies already installed"
fi

# Start gunicorn
echo "Starting gunicorn..."
gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 2 --threads 4 --worker-class=gthread wsgi:app
