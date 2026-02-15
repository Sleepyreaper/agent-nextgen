#!/usr/bin/env python
"""Debug script to test database operations."""

from src.database import Database

# Test 1: Can we create a Database instance?
db = Database()
print("✓ Database instance created")

# Test 2: Can we query for application 8?
try:
    app = db.get_application(8)
    if app:
        print("✓ Application 8 found in database")
        print(f"  - Name: {app.get('ApplicantName')}")
        print(f"  - Status: {app.get('Status')}")
        print(f"  - Type of 'Status': {type(app.get('Status'))}")
        print(f"  - Bool value: {bool(app)}")
    else:
        print("✗ Application 8 returned None")
except Exception as e:
    print(f"✗ Error querying application 8: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Check if database connection is working
try:
    result = db.execute_query("SELECT COUNT(*) as cnt FROM Applications", ())
    if result:
        print(f"✓ Database queries work. Total applications: {result[0].get('cnt')}")
except Exception as e:
    print(f"✗ Database query error: {e}")
    
# Test 4: Test the Flask route directly
try:
    from app import app as flask_app
    with flask_app.test_client() as client:
        response = client.get('/application/8')
        print(f"Flask test response status: {response.status_code}")
        if response.status_code == 302:
            print(f"  Redirecting to: {response.location}")
        else:
            print(f"  Response content (first 200 chars): {response.data[:200]}")
except Exception as e:
    print(f"✗ Flask test error: {e}")
    import traceback
    traceback.print_exc()
