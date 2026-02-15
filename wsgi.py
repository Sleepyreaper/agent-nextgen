"""WSGI entry point for deployments."""

import os
import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent))

# Import Flask app
from app import app

# Export for WSGI servers (gunicorn, waitress, etc.)
__all__ = ['app']

if __name__ == "__main__":
    port = int(os.getenv('PORT', 5002))
    app.run(host='0.0.0.0', port=port)
