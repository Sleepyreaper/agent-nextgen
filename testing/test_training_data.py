#!/usr/bin/env python3
"""Test creating and retrieving test data in PostgreSQL"""
from src.database import Database

db = Database()

print("Testing database INSERT with is_training_example=TRUE...\n")

try:
    # Create a test application
    app_id = db.create_application(
        applicant_name="Test Student",
        email="test@example.com",
        application_text="This is a test application for training purposes.",
        file_name="test_application.pdf",
        file_type="pdf",
        is_training=True,
        was_selected=None
    )
    
    print(f"✅ Created test application with ID: {app_id}")
    
    # Verify it was created
    app = db.get_application(app_id)
    if app:
        print(f"✅ Retrieved application: {app.get('applicant_name')}")
        print(f"   Is training: {app.get('is_training_example')}")
        print(f"   Email: {app.get('email')}")
        print(f"   Status: {app.get('status')}")
    
    # Test querying training examples
    training_examples = db.get_training_examples()
    print(f"\n✅ Found {len(training_examples)} training examples in database")
    
    # Test formatted student list
    formatted = db.get_formatted_student_list(is_training=True)
    print(f"✅ Formatted student list returned {len(formatted)} records")
    if formatted:
        print(f"   Sample: {formatted[0]}")
    
    # Clean up
    db.execute_non_query("DELETE FROM Applications WHERE application_id = %s", (app_id,))
    print(f"\n✅ Cleaned up test data")
    
    print("\n✅ ALL TEST DATA OPERATIONS WORK CORRECTLY!")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
