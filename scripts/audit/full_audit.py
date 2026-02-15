#!/usr/bin/env python3
"""Complete audit of database schema, agent requirements, and student creation flow."""

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import db
from src.agents.agent_requirements import AgentRequirements
import json

print("\n" + "="*80)
print("🔍 COMPLETE SYSTEM AUDIT")
print("="*80)

# ===== PART 1: DATABASE SCHEMA =====
print("\n1️⃣ DATABASE SCHEMA")
print("-" * 80)

try:
    tables = db.execute_query("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' 
        ORDER BY table_name
    """)
    
    if tables:
        for t in tables:
            table_name = t.get('table_name')
            cols = db.execute_query(f"""
                SELECT column_name, data_type FROM information_schema.columns 
                WHERE table_name = '{table_name}' 
                ORDER BY ordinal_position
            """)
            print(f"\n📋 {table_name.upper()}:")
            for col in cols:
                print(f"   {col.get('column_name'):<30} {col.get('data_type')}")
    else:
        print("❌ No tables found")
except Exception as e:
    print(f"❌ Error querying database: {e}")

# ===== PART 2: AGENT REQUIREMENTS =====
print("\n\n2️⃣ AGENT REQUIREMENTS")
print("-" * 80)

agents = ['application_reader', 'grade_reader', 'school_context', 'recommendation_reader', 'student_evaluator']
for agent_id in agents:
    req = AgentRequirements.get_agent_requirements(agent_id)
    print(f"\n🤖 {agent_id.upper().replace('_', ' ')}:")
    if req:
        print(f"   Required fields: {req.get('required_fields', [])}")
        print(f"   DB field name: {req.get('field_name', 'N/A')}")
        print(f"   Questions: {req.get('questions', [])[:1]}")
    else:
        print("   ❌ NOT CONFIGURED")

# ===== PART 3: TEST DATA IN DATABASE =====
print("\n\n3️⃣ TEST DATA STATUS")
print("-" * 80)

try:
    test_apps = db.execute_query("""
        SELECT application_id, applicant_name, email, status, is_test_data, student_id
        FROM applications 
        WHERE is_test_data = TRUE
        ORDER BY application_id DESC
        LIMIT 5
    """)
    
    if test_apps:
        print(f"Found {len(test_apps)} test student(s):")
        for app in test_apps:
            print(f"\n   ID: {app.get('application_id')}")
            print(f"   Name: {app.get('applicant_name')}")
            print(f"   Email: {app.get('email')}")
            print(f"   Status: {app.get('status')}")
            print(f"   Student ID: {app.get('student_id')}")
    else:
        print("No test students in database")
except Exception as e:
    print(f"❌ Error: {e}")

# ===== PART 4: AGENT OUTPUT TABLES =====
print("\n\n4️⃣ AGENT OUTPUT TABLES STATUS")
print("-" * 80)

agent_tables = [
    'tiana_applications',
    'rapunzel_grades', 
    'student_school_context',
    'mulan_recommendations',
    'merlin_evaluations',
    'aurora_evaluations'
]

for table in agent_tables:
    try:
        result = db.execute_query(f"SELECT COUNT(*) as count FROM {table}")
        count = result[0].get('count') if result else 0
        print(f"   {table:<35} {count} records")
    except:
        print(f"   {table:<35} ❌ ERROR OR NOT EXISTS")

print("\n" + "="*80)
print("✅ AUDIT COMPLETE")
print("="*80 + "\n")
