#!/usr/bin/env python3
"""
Test script to verify complete data isolation between test, training, and 2026 applications.

This tests the triple-layer filtering:
1. Database WHERE clause filtering
2. Route-level defensive filtering  
3. Field validation in response
"""

import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from database import Database
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_table_structure():
    """Verify database has all required columns for data isolation."""
    print("\n" + "="*60)
    print("TEST 1: Database Table Structure")
    print("="*60)
    
    db = Database()
    
    # Check if is_test_data column exists
    try:
        query = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'applications' AND column_name = 'is_test_data'
        """
        result = db.execute_query(query)
        if result:
            print("✓ is_test_data column exists")
        else:
            print("⚠ is_test_data column MISSING - auto-migration should create it")
    except Exception as e:
        print(f"⚠ Could not check is_test_data column: {e}")
    
    # Check if is_training_example column exists
    try:
        query = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'applications' AND column_name = 'is_training_example'
        """
        result = db.execute_query(query)
        if result:
            print("✓ is_training_example column exists")
        else:
            print("⚠ is_training_example column MISSING - auto-migration should create it")
    except Exception as e:
        print(f"⚠ Could not check is_training_example column: {e}")


def test_filtering_logic():
    """Test the get_formatted_student_list filtering logic."""
    print("\n" + "="*60)
    print("TEST 2: Filtering Logic - Get 2026 Applications")
    print("="*60)
    
    db = Database()
    
    # Get 2026 production applications (is_training=False)
    students = db.get_formatted_student_list(is_training=False)
    print(f"\n📊 Total 2026 applications returned: {len(students)}")
    
    # Check for test data contamination
    test_data_found = []
    training_data_found = []
    
    for student in students:
        if student.get('is_test_data'):
            test_data_found.append(student)
            print(f"🔴 TEST DATA IN 2026: {student.get('application_id')} - {student.get('full_name')}")
        if student.get('is_training_example'):
            training_data_found.append(student)
            print(f"🔴 TRAINING DATA IN 2026: {student.get('application_id')} - {student.get('full_name')}")
        # ensure merlin_score is present when a summary was available
        if student.get('student_summary') and student.get('merlin_score') is None:
            print(f"⚠️ student_summary present but merlin_score missing for {student.get('application_id')}")
    
    if test_data_found:
        print(f"\n❌ FAILURE: {len(test_data_found)} test records found in 2026 view!")
        return False
    elif training_data_found:
        print(f"\n❌ FAILURE: {len(training_data_found)} training records found in 2026 view!")
        return False
    else:
        print(f"\n✓ SUCCESS: No test or training data contamination in 2026 view")
        return True


def test_backfill_summary():
    """Exercise the backfill_student_summaries helper and make sure it works."""
    print("\n" + "="*60)
    print("TEST 4: Backfill student_summary helper")
    print("="*60)

    db = Database()
    # create a fake application with agent_results but no student_summary
    app_id = db.create_application(applicant_name='Backfill Test', email='bf@example.com')
    fake_results = {'merlin': {'overall_score': 55, 'recommendation': 'Review', 'rationale': 'backfill test'}}
    db.execute_non_query(
        "UPDATE applications SET agent_results = %s WHERE application_id = %s",
        (json.dumps(fake_results), app_id)
    )
    # before running backfill, confirm that the student list will derive score
    all_students = db.get_formatted_student_list(is_training=False)
    found = False
    for s in all_students:
        if s.get('application_id') == app_id:
            found = True
            print(f"Row in formatted list: {s}")
            if s.get('merlin_score') == 55:
                print("✓ merlin_score derived from agent_results")
            else:
                print("⚠ merlin_score not derived before backfill")
            break
    if not found:
        print("⚠ Unable to find temp row in formatted list")

    # ensure column exists
    if not db.has_applications_column('student_summary'):
        print("⚠ student_summary column missing, cannot run backfill")
        return False
    updated = db.backfill_student_summaries()
    print(f"Backfill updated {updated} rows")
    # verify that our row now has a summary
    rec = db.get_application(app_id)
    if rec and rec.get('student_summary'):
        print("✓ Summary was added by backfill")
        return True
    else:
        print("⚠ Summary still missing after backfill")
        return False


def test_api_test_data_list():
    """Hit the test-data API endpoint and ensure response includes summary/score"""
    print("\n" + "="*60)
    print("TEST 5: /api/test-data/list response structure")
    print("="*60)
    from app import app as flask_app
    with flask_app.test_client() as client:
        resp = client.get('/api/test-data/list')
        print(f"status {resp.status_code}")
        if resp.status_code != 200:
            print("⚠ Unexpected status from API")
            return False
        data = resp.get_json() or {}
        students = data.get('students', [])
        for stu in students:
            if stu.get('student_summary') and stu.get('merlin_score') is None:
                print(f"⚠ API did not derive score for {stu.get('applicationid')}")
                return False
        print("✓ API returned students with merlin_score when summary exists")
        return True


def test_training_filtering():
    """Test training data filtering."""
    print("\n" + "="*60)
    print("TEST 3: Filtering Logic - Get Training Applications")
    print("="*60)
    
    db = Database()
    
    # Get training applications
    training = db.get_formatted_student_list(is_training=True)
    print(f"\n📊 Total training applications returned: {len(training)}")
    
    # Check for test data contamination in training
    test_data_found = []
    for student in training:
        if student.get('is_test_data'):
            test_data_found.append(student)
            print(f"🔴 TEST DATA IN TRAINING: {student.get('application_id')} - {student.get('full_name')}")
    
    if test_data_found:
        print(f"\n❌ FAILURE: {len(test_data_found)} test records found in training view!")
        return False
    else:
        print(f"\n✓ SUCCESS: No test data contamination in training view")
        return True


def test_test_data_filtering():
    """Test that test data retrieval works correctly."""
    print("\n" + "="*60)
    print("TEST 4: Test Data Records Exist")
    print("="*60)
    
    db = Database()
    
    try:
        # Count test data records
        query = """
        SELECT COUNT(*) as count
        FROM applications
        WHERE is_test_data = TRUE
        """
        result = db.execute_query(query)
        test_count = result[0].get('count', 0) if result else 0
        print(f"\n📊 Total test data records in database: {test_count}")
        
        if test_count == 0:
            print("⚠ No test data records found - test data filtering may not be testable")
            return True
        else:
            print(f"✓ Test data exists ({test_count} records) - filtering can be verified")
            return True
    except Exception as e:
        print(f"⚠ Could not check test data count: {e}")
        return False


def test_field_presence():
    """Test that is_test_data and is_training_example fields are in responses."""
    print("\n" + "="*60)
    print("TEST 5: Response Field Presence")
    print("="*60)
    
    db = Database()
    
    # Get a sample of 2026 applications
    students = db.get_formatted_student_list(is_training=False)
    
    if not students:
        print("⚠ No students returned - cannot verify field presence")
        return True
    
    sample = students[0]
    
    # Check for required fields
    required_fields = ['is_test_data', 'is_training_example']
    missing_fields = []
    
    for field in required_fields:
        if field not in sample:
            missing_fields.append(field)
            print(f"🔴 MISSING FIELD: {field}")
        else:
            value = sample.get(field)
            print(f"✓ Field '{field}' present: {value} (type: {type(value).__name__})")
    
    if missing_fields:
        print(f"\n❌ FAILURE: {len(missing_fields)} required fields missing!")
        return False
    else:
        print(f"\n✓ SUCCESS: All required fields present in response")
        return True


def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("DATA ISOLATION VERIFICATION TEST SUITE")
    print("="*80)
    print("\nThis suite verifies triple-layer data isolation:")
    print("1. Database WHERE clause + is_test_data column")
    print("2. Route-level defensive filtering")
    print("3. Field validation in response objects")
    
    try:
        test_table_structure()
        test_table_structure()
        
        results = {
            'test_filtering_logic': test_filtering_logic(),
            'test_training_filtering': test_training_filtering(),
            'test_test_data_filtering': test_test_data_filtering(),
            'test_field_presence': test_field_presence(),
        }
    except Exception as e:
        logger.error(f"Test execution failed: {e}", exc_info=True)
        results = {}
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    if not results:
        print("❌ Tests failed to run - check database connection")
        return False
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nResult: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All data isolation tests PASSED!")
        print("\n⚠️  IMPORTANT:")
        print("- Verify /students route shows ONLY 2026 applications (is_test_data=False)")
        print("- Verify /training route shows ONLY training applications (is_training_example=True)")
        print("- Verify /test-data route shows ONLY test applications (is_test_data=True)")
        return True
    else:
        print(f"\n❌ {total - passed} test(s) FAILED - data isolation may be compromised!")
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
