#!/usr/bin/env python3
"""Check what data is in test students."""
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import db

# Get the 2 most recent test students
test_apps = db.execute_query('''
    SELECT application_id, applicant_name, email, 
           application_text, transcript_text, recommendation_text,
           status
    FROM applications 
    WHERE is_test_data = TRUE
    ORDER BY application_id DESC
    LIMIT 2
''')

print("\nRECENT TEST STUDENT DATA:\n")
for i, app in enumerate(test_apps, 1):
    print(f"{i}. {app['applicant_name']} (ID {app['application_id']})")
    print(f"   Status: {app['status']}")
    app_text = app['application_text']
    trans_text = app['transcript_text'] 
    rec_text = app['recommendation_text']
    print(f"   - application_text: {'✓ YES (' + str(len(app_text)) + ' chars)' if app_text else '✗ NO'}")
    print(f"   - transcript_text: {'✓ YES (' + str(len(trans_text)) + ' chars)' if trans_text else '✗ NO'}")
    print(f"   - recommendation_text: {'✓ YES (' + str(len(rec_text)) + ' chars)' if rec_text else '✗ NO'}")
    if app_text:
        print(f"     Excerpt: {app_text[:100]}...")
    if trans_text:
        print(f"     Excerpt: {trans_text[:100]}...")
    if rec_text:
        print(f"     Excerpt: {rec_text[:100]}...")
    print()
