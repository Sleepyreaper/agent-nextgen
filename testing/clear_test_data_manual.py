#!/usr/bin/env python3
"""Manual script to clear test data from the database."""

from src.database import Database
from dotenv import load_dotenv

load_dotenv('.env.local')

db = Database()

# Check current test data
print("=== Current Test Data ===")
test_apps = db.execute_query("""
    SELECT applicationid, applicantname, email, istrainingexample
    FROM applications
    WHERE istrainingexample = TRUE
    ORDER BY applicantname
""")

for app in test_apps:
    print(f" {app.get('applicantname')} - {app.get('email')} (ID: {app.get('applicationid')})")

print(f"\nTotal test records: {len(test_apps)}")

# Now clear them
if len(test_apps) > 0:
    print("\n=== Clearing Test Data ===")
    test_app_ids = [app.get('applicationid') for app in test_apps]
    
    # Delete related data (in correct order for foreign keys)
    for app_id in test_app_ids:
        try:
            # Delete audit logs first (has FK to applications)
            db.execute_non_query("DELETE FROM agentauditlogs WHERE applicationid = %s", (app_id,))
            # Delete from agent-specific tables
            db.execute_non_query("DELETE FROM tianaapplications WHERE applicationid = %s", (app_id,))
            db.execute_non_query("DELETE FROM mulanrecommendations WHERE applicationid = %s", (app_id,))
            db.execute_non_query("DELETE FROM merlinevaluations WHERE applicationid = %s", (app_id,))
            db.execute_non_query("DELETE FROM auroraevaluations WHERE applicationid = %s", (app_id,))
            db.execute_non_query("DELETE FROM studentschoolcontext WHERE applicationid = %s", (app_id,))
            db.execute_non_query("DELETE FROM grades WHERE applicationid = %s", (app_id,))
            db.execute_non_query("DELETE FROM aievaluations WHERE applicationid = %s", (app_id,))
            db.execute_non_query("DELETE FROM selectiondecisions WHERE applicationid = %s", (app_id,))
        except Exception as e:
            print(f"  Warning for app {app_id}: {e}")
    
    # Delete applications
    db.execute_non_query("DELETE FROM applications WHERE istrainingexample = TRUE")
    db.execute_non_query("DELETE FROM testsubmissions")
    
    print(f"✅ Cleared {len(test_app_ids)} test applications")
    
    # Verify
    remaining = db.execute_query("SELECT COUNT(*) as cnt FROM applications WHERE istrainingexample = TRUE")
    print(f"Remaining test records: {remaining[0].get('cnt')}")
else:
    print("\n✅ No test data to clear")
