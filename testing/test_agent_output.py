#!/usr/bin/env python3
"""Direct test of agent functionality and database output storage."""

import asyncio
import sys
import json
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.database import db
from src.config import config
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from src.agents import (
    TianaApplicationReader,
    RapunzelGradeReader,
    MoanaSchoolContext,
    MulanRecommendationReader,
    MerlinStudentEvaluator,
    AuroraAgent,
    SmeeOrchestrator
)

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

async def test_agents():
    """Test each agent individually."""
    
    print("\n" + "="*70)
    print("🧪 AGENT OUTPUT STORAGE TEST")
    print("="*70)
    
    client = get_ai_client()
    
    # Create test application
    print("\n📝 Creating test application in database...")
    test_app = {
        'applicant_name': 'Test Student Agent',
        'email': 'test@example.com',
        'application_text': '''
My name is Test Student and I am applying for your program.

I graduated from Lincoln High School in 2024 with a 3.85 GPA.

I am interested in engineering and technology fields.
My strengths include mathematics, problem-solving, and leadership.
        ''',
        'is_test_data': True,
        'student_id': 'test_agent_12345'
    }
    
    app_id = db.create_application(**test_app)
    print(f"✓ Created test application ID: {app_id}")
    
    # Retrieve it to verify
    app = db.get_application(app_id)
    print(f"✓ Retrieved application: {app.get('applicant_name')}")
    
    # Test 1: Tiana (Application Reader)
    print("\n" + "-"*70)
    print("TEST 1: Tiana Application Reader")
    print("-"*70)
    
    try:
        tiana = TianaApplicationReader(client=client, model=config.deployment_name)
        result = await tiana.parse_application(app)
        print(f"✓ Tiana processed application")
        print(f"  Status: {result.get('status')}")
        print(f"  Keys: {list(result.keys())}")
        
        if result.get('status') == 'success':
            # Check if it was saved
            saved = db.get_tiana_evaluation(app_id)
            if saved:
                print(f"  ✓ Result saved to database!")
            else:
                print(f"  ⚠ Result NOT saved to database")
    except Exception as e:
        print(f"✗ Tiana error: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 2: Merlin (Student Evaluator)
    print("\n" + "-"*70)
    print("TEST 2: Merlin Student Evaluator")
    print("-"*70)
    
    try:
        merlin = MerlinStudentEvaluator(client=client, model=config.deployment_name, db_connection=db)
        result = await merlin.evaluate_student(
            application=app,
            agent_results={}
        )
        print(f"✓ Merlin processed application")
        print(f"  Status: {result.get('status')}")
        print(f"  Keys: {list(result.keys())}")
        
        if result.get('status') == 'success':
            # Check if it was saved
            saved = db.get_merlin_evaluation(app_id)
            if saved:
                print(f"  ✓ Result saved to database!")
            else:
                print(f"  ⚠ Result NOT saved to database")
    except Exception as e:
        print(f"✗ Merlin error: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 3: Check database state
    print("\n" + "-"*70)
    print("TEST 3: Database Tables Status")
    print("-"*70)
    
    tables_to_check = [
        'tiana_applications',
        'merlin_evaluations',
        'mulan_recommendations',
        'student_school_context',
        'aurora_evaluations',
        'rapunzel_grades',
        'applications'
    ]
    
    for table in tables_to_check:
        try:
            result = db.execute_query(f"SELECT COUNT(*) as count FROM {table}")
            count = result[0].get('count', 0) if result else 0
            print(f"  {table}: {count} records")
        except Exception as e:
            print(f"  {table}: ⚠ ERROR - {str(e)[:50]}")
    
    # Test 4: Full Smee Orchestrator
    print("\n" + "-"*70)
    print("TEST 4: Smee Orchestrator Coordination")
    print("-"*70)
    
    try:
        orchestrator = SmeeOrchestrator(
            name="Smee",
            client=client,
            model=config.deployment_name,
            db_connection=db
        )
        
        # Register agents
        orchestrator.register_agent('application_reader', TianaApplicationReader(client=client, model=config.deployment_name))
        orchestrator.register_agent('student_evaluator', MerlinStudentEvaluator(client=client, model=config.deployment_name, db_connection=db))
        
        result = await orchestrator.coordinate_evaluation(
            application=app,
            evaluation_steps=['application_reader', 'student_evaluator']
        )
        
        print(f"✓ Orchestrator completed")
        print(f"  Status: {result.get('status')}")
        
        # Check final counts
        try:
            result = db.execute_query("SELECT COUNT(*) as count FROM applications WHERE is_test_data = TRUE")
            count = result[0].get('count', 0) if result else 0
            print(f"  Test applications in DB: {count}")
        except:
            pass
            
    except Exception as e:
        print(f"✗ Orchestrator error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*70)
    print("✅ TEST COMPLETE")
    print("="*70)

if __name__ == '__main__':
    asyncio.run(test_agents())
