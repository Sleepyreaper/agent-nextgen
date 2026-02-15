#!/usr/bin/env python
"""Test if the application page loads correctly."""

import requests
import sys

try:
    response = requests.get('http://localhost:5001/application/8', timeout=10, allow_redirects=False)
    print(f'Status: {response.status_code}')
    
    if response.status_code == 302:
        print('❌ Page is redirecting (student not found)')
        print(f'Location: {response.headers.get("Location")}')
        sys.exit(1)
    elif response.status_code == 200:
        if 'Alice Chen' in response.text:
            print('✅ Application page loaded successfully!')
            print('✅ Found student name "Alice Chen" in page')
            sys.exit(0)
        elif 'Application #8' in response.text:
            print('✅ Application detail page loaded!')
            print('⚠️ But student name not found - data might not be in response')
            sys.exit(1)
        else:
            print('⚠️ Page loaded but content unexpected')
            print('First 500 chars:', response.text[:500])
            sys.exit(1)
    else:
        print(f'❌ Page returned unexpected status {response.status_code}')
        sys.exit(1)
except Exception as e:
    print(f'❌ Error: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
