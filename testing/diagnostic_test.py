#!/usr/bin/env python3
"""Diagnostic test - what's really happening with name extraction and agent processing."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.database import db
from src.config import config
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from src.agents.belle_document_analyzer import BelleDocumentAnalyzer
from src.test_data_generator import test_data_generator

def get_ai_client():
    """Get Azure OpenAI client."""
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        azure_ad_token_provider=token_provider,
        api_version=config.api_version,
        azure_endpoint=config.azure_openai_endpoint
    )

print("\n" + "="*70)
print("DIAGNOSTIC TEST: Name Extraction & Agent Status")
print("="*70)

# Step 1: Generate a test student
print("\n1️⃣ GENERATING TEST STUDENT...")
student = test_data_generator.generate_student('high')
print(f"   Name: {student['name']}")
print(f"   Email: {student['email']}")
print(f"   App text first 200 chars: {student['application_text'][:200]}")

# Step 2: Test Belle's name extraction
print("\n2️⃣ TESTING BELLE NAME EXTRACTION...")
client = get_ai_client()
belle = BelleDocumentAnalyzer(client=client, model=config.deployment_name)

# Test pattern matching first
pattern_result = belle._extract_name_pattern(student['application_text'])
print(f"   Pattern extraction result: {pattern_result}")

# Test with AI
analysis = belle.analyze_document(student['application_text'], 'test.txt')
print(f"   Belle student_info keys: {list(analysis.get('student_info', {}).keys())}")
print(f"   Belle extracted name: {analysis.get('student_info', {}).get('name', 'NOT FOUND')}")
print(f"   Actual name: {student['name']}")

if analysis.get('student_info', {}).get('name') == student['name']:
    print("   ✅ NAME EXTRACTION CORRECT")
else:
    print("   ❌ NAME EXTRACTION WRONG")

# Step 3: Check database agent output tables
print("\n3️⃣ CHECKING DATABASE FOR AGENT OUTPUT...")
app = db.get_application(1)
if app:
    print(f"   Test application exists: {app.get('applicant_name')}")
    
    # Check which agents have output
    tiana = db.execute_query("SELECT COUNT(*) as count FROM tiana_applications LIMIT 1")
    merlin = db.execute_query("SELECT COUNT(*) as count FROM merlin_evaluations LIMIT 1")
    mulan = db.execute_query("SELECT COUNT(*) as count FROM mulan_recommendations LIMIT 1")
    moana = db.execute_query("SELECT COUNT(*) as count FROM student_school_context LIMIT 1")
    
    print(f"   Tiana records: {tiana[0].get('count') if tiana else 0}")
    print(f"   Merlin records: {merlin[0].get('count') if merlin else 0}")
    print(f"   Mulan records: {mulan[0].get('count') if mulan else 0}")
    print(f"   Moana records: {moana[0].get('count') if moana else 0}")
else:
    print("   ⚠️ No test applications in database")

print("\n" + "="*70)
print("END DIAGNOSTIC TEST")
print("="*70)
