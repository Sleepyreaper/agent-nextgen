#!/usr/bin/env python3
"""Check test student field population."""
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import db

test_apps = db.execute_query('''
    SELECT application_id, applicant_name, 
           (application_text IS NOT NULL AND application_text != '') as has_app,
           (transcript_text IS NOT NULL AND transcript_text != '') as has_trans,
           (recommendation_text IS NOT NULL AND recommendation_text != '') as has_rec,
           status
    FROM applications 
    WHERE is_test_data = TRUE
    ORDER BY application_id DESC
    LIMIT 2
''')

print("\nTEST STUDENT FIELD STATUS:")
for app in test_apps:
    print(f"\n{app['applicant_name']} (ID {app['application_id']}):")
    print(f"  application_text:     {'✓' if app['has_app'] else '✗'}")
    print(f"  transcript_text:       {'✓' if app['has_trans'] else '✗'}")
    print(f"  recommendation_text:   {'✓' if app['has_rec'] else '✗'}")
    print(f"  Status: {app['status']}")
