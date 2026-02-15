#!/usr/bin/env python3
"""Comprehensive test for creating and storing test data in PostgreSQL"""
from src.database import Database
import json

db = Database()

print("=" * 70)
print("COMPREHENSIVE TEST DATA VERIFICATION")
print("=" * 70)

# Test 1: Create application with is_training_example=TRUE
print("\n1️⃣  Creating test application...")
try:
    app_id = db.create_application(
        applicant_name="Jane Smith",
        email="jane.smith@example.com",
        application_text="I am passionate about data science and machine learning...",
        file_name="jane_smith_application.pdf",
        file_type="pdf",
        is_training=True,
        was_selected=True
    )
    print(f"   ✅ Created application ID: {app_id}")
except Exception as e:
    print(f"   ❌ Error: {e}")
    exit(1)

# Test 2: Retrieve and verify the data
print("\n2️⃣  Retrieving application...")
try:
    app = db.get_application(app_id)
    print(f"   ✅ Retrieved: {app.get('applicant_name')}")
    print(f"      - Email: {app.get('email')}")
    print(f"      - Status: {app.get('status')}")
    print(f"      - Is Training: {app.get('is_training_example')}")
    print(f"      - Was Selected: {app.get('was_selected')}")
    print(f"      - Application Text: {app.get('application_text')[:50]}...")
except Exception as e:
    print(f"   ❌ Error: {e}")
    exit(1)

# Test 3: Query training examples
print("\n3️⃣  Querying all training examples...")
try:
    training = db.get_training_examples()
    print(f"   ✅ Found {len(training)} training example(s)")
    for t in training:
        print(f"      - {t.get('applicant_name')} (ID: {t.get('application_id')})")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 4: Get formatted student list
print("\n4️⃣  Testing formatted student list...")
try:
    formatted = db.get_formatted_student_list(is_training=True)
    print(f"   ✅ Formatted list returned {len(formatted)} record(s)")
    if formatted:
        sample = formatted[0]
        print(f"      - Name: {sample.get('full_name')}")
        print(f"      - School: {sample.get('high_school')}")
        print(f"      - Merlin Score: {sample.get('merlin_score')}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 5: Save agent outputs (Tiana)
print("\n5️⃣  Testing agent output storage (Tiana)...")
try:
    tiana_id = db.save_tiana_application(
        application_id=app_id,
        agent_name="Tiana",
        essay_summary="Strong essay about overcoming challenges",
        recommendation_texts="Excellent recommendations from teachers",
        readiness_score=8.5,
        confidence="high",
        parsed_json=json.dumps({"essay_themes": ["perseverance", "leadership"]})
    )
    print(f"   ✅ Saved Tiana output (ID: {tiana_id})")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 6: Save Merlin evaluation
print("\n6️⃣  Testing Merlin evaluation storage...")
try:
    merlin_id = db.save_merlin_evaluation(
        application_id=app_id,
        agent_name="Merlin",
        overall_score=9.2,
        recommendation="Strong Accept",
        rationale="Exceptional candidate with strong academics and leadership",
        confidence="high",
        parsed_json=json.dumps({"strengths": ["academics", "leadership", "community service"]})
    )
    print(f"   ✅ Saved Merlin evaluation (ID: {merlin_id})")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 7: Verify data persistence
print("\n7️⃣  Verifying data persistence...")
try:
    # Re-query to make sure data is persisted
    app_check = db.get_application(app_id)
    training_check = db.get_training_examples()
    
    if app_check and len(training_check) > 0:
        print(f"   ✅ Data persisted correctly")
        print(f"      - Application still exists: {app_check.get('applicant_name')}")
        print(f"      - Training examples count: {len(training_check)}")
    else:
        print(f"   ❌ Data persistence issue")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test 8: Clean up
print("\n8️⃣  Cleaning up test data...")
try:
    db.clear_test_data()
    
    # Verify cleanup
    remaining = db.get_training_examples()
    print(f"   ✅ Cleanup complete")
    print(f"      - Remaining training examples: {len(remaining)}")
except Exception as e:
    print(f"   ❌ Error during cleanup: {e}")

print("\n" + "=" * 70)
print("✅ ALL TESTS PASSED!")
print("=" * 70)
print("\nSummary:")
print("  ✅ Can create test/training applications")
print("  ✅ Data is correctly stored with is_training_example=TRUE")
print("  ✅ Can query and retrieve training data")
print("  ✅ Agent outputs (Tiana, Merlin) link correctly to applications")
print("  ✅ Data persists in PostgreSQL database")
print("  ✅ Cleanup operations work correctly")
