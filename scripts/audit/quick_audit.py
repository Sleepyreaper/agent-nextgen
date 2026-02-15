#!/usr/bin/env python3
"""Quick diagnostic of current system state."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import db

print("\n" + "="*80)
print("QUICK SYSTEM AUDIT")
print("="*80)

# Test students
print("\n1. TEST STUDENTS IN DATABASE:")
test_apps = db.execute_query('''
    SELECT application_id, applicant_name, email, status, student_id
    FROM applications 
    WHERE is_test_data = TRUE
    ORDER BY application_id DESC
    LIMIT 10
''')

print(f"   Total test students: {len(test_apps)}")
if test_apps:
    print("\n   Recent test students:")
    for app in test_apps:
        print(f"   - ID {app['application_id']}: {app['applicant_name']} ({app['email']}) | Status: {app['status']}")

# Check for duplicates
print("\n2. DUPLICATE TEST STUDENTS (same name/email):")
dups = db.execute_query('''
    SELECT applicant_name, email, COUNT(*) as cnt, array_agg(application_id) as ids
    FROM applications 
    WHERE is_test_data = TRUE
    GROUP BY applicant_name, email
    HAVING COUNT(*) > 1
''')
if dups:
    print(f"   Found {len(dups)} duplicate combinations:")
    for dup in dups:
        print(f"   - {dup['applicant_name']} ({dup['email']}): {dup['cnt']} records (IDs: {dup['ids']})")
else:
    print("   No duplicates found")

# Agent output status
print("\n3. AGENT OUTPUT COUNTS:")
agent_tables = {
    'tiana_applications': 'Tiana (Application Reader)',
    'rapunzel_grades': 'Rapunzel (Grade Reader)',
    'student_school_context': 'Moana (School Context)',
    'mulan_recommendations': 'Mulan (Recommendation Reader)',
    'merlin_evaluations': 'Merlin (Evaluator)',
    'aurora_evaluations': 'Aurora (Presenter)',
}

for table, name in agent_tables.items():
    try:
        result = db.execute_query(f"SELECT COUNT(*) as cnt FROM {table}")
        count = result[0]['cnt'] if result else 0
        status = "✓" if count > 0 else "✗"
        print(f"   {status} {name}: {count} records")
    except Exception as e:
        print(f"   ? {name}: Error - {e}")

# Check agent requirements config
print("\n4. AGENT REQUIREMENTS CONFIG:")
from src.agents.agent_requirements import AgentRequirements
agents_to_check = ['application_reader', 'grade_reader', 'school_context', 'recommendation_reader', 'student_evaluator']
for agent_id in agents_to_check:
    req = AgentRequirements.get_agent_requirements(agent_id)
    if req:
        print(f"   ✓ {agent_id}: requires {req.get('required_fields', [])}")
    else:
        print(f"   ✗ {agent_id}: NOT CONFIGURED")

# Check if recent test has transcript or recommendation fields
print("\n5. CHECKING RECENT TEST STUDENT DATA:")
if test_apps:
    latest = test_apps[0]
    app_id = latest['application_id']
    app_detail = db.execute_query(f"""
        SELECT 
            application_id, applicant_name, 
            application_essay, transcript_text, recommendation_text,
            school_name
        FROM applications 
        WHERE application_id = {app_id}
    """)
    if app_detail:
        app = app_detail[0]
        print(f"   Latest test student (ID {app_id}, {app['applicant_name']}):")
        print(f"   - application_essay: {'✓ Present' if app['application_essay'] else '✗ Missing'}")
        print(f"   - transcript_text: {'✓ Present' if app['transcript_text'] else '✗ Missing'}")
        print(f"   - recommendation_text: {'✓ Present' if app['recommendation_text'] else '✗ Missing'}")
        print(f"   - school_name: {'✓ Present' if app['school_name'] else '✗ Missing'}")

print("\n" + "="*80 + "\n")
