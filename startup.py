#!/usr/bin/env python
"""
Startup script for Azure Web App.
This script is called by the Azure Web App to start the Flask application.
"""

import os
import sys
from pathlib import Path

# Set working directory
os.chdir(Path(__file__).parent)

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Import and run gunicorn
from gunicorn.app.wsgiapp import run

if __name__ == '__main__':
    sys.argv = [
        'gunicorn',
        '--workers=4',
        '--worker-class=sync',
        '--threads=2',
        '--timeout=60',
        '--bind=0.0.0.0:' + os.getenv('PORT', '8000'),
        '--access-logfile=-',
        '--error-logfile=-',
        'wsgi:app'
    ]
    sys.exit(run())
