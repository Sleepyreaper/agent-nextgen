#!/usr/bin/env python
"""Test the student_detail route directly."""

from app import app as flask_app
from src.database import Database

db = Database()

# Test the database return value
application = db.get_application(8)
print(f"Database result: {application is not None}")

if application:
    print(f"ApplicationID: {application.get('ApplicationID')}")
print("Keys in application:", list(application.keys()) if application else [])

# Now test the Flask route
try:
    with flask_app.test_client() as client:
        response = client.get('/application/8', follow_redirects=False)
        print(f"\nFlask route test:")
        print(f"Status: {response.status_code}")
        if response.status_code == 302:
            print(f"Redirects to: {response.headers.get('Location')}")
            # Get the error message from flask
            if 'session' in response.headers:
                print("Flask set a session cookie (likely contains error)")
        elif response.status_code == 200:
            if b'Alice Chen' in response.data:
                print("✅ Success! Alice Chen found")
            else:
                print("⚠️ Status 200 but no content found")
except Exception as e:
    print(f"Exception: {e}")
    import traceback
    traceback.print_exc()
