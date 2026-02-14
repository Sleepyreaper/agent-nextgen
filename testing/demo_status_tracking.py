#!/usr/bin/env python3
"""
Demonstration of the Agent Status Tracking System.

Shows how Smee determines what information is needed and which agents can work.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.database import db
from src.config import config
from openai import AzureOpenAI
from src.agents.smee_orchestrator import SmeeOrchestrator
from src.agents.tiana_application_reader import TianaApplicationReader
from src.agents.rapunzel_grade_reader import RapunzelGradeReader
from src.agents.mulan_recommendation_reader import MulanRecommendationReader
from src.agents.moana_school_context import MoanaSchoolContext
from src.agents.merlin_student_evaluator import MerlinStudentEvaluator


def demo_status_tracking():
    """Demonstrate the agent status tracking system."""
    
    print("\n" + "=" * 80)
    print("AGENT STATUS TRACKING SYSTEM DEMO")
    print("=" * 80)
    print()
    
    # Create mock applications to show different scenarios
    test_cases = [
        {
            'applicationid': 999001,
            'applicantname': 'Alex - Essay Only',
            'applicationtext': 'My name is Alex. This is my personal statement... I believe education is important.',
            'email': 'alex@example.com',
            'description': 'Only application essay (missing grades, school info, recommendations)'
        },
        {
            'applicationid': 999002,
            'applicantname': 'Jordan - With Grades',
            'applicationtext': '''
            Personal Statement from Jordan:
            I am a dedicated student from Lincoln High School.
            
            TRANSCRIPT:
            GPA: 3.8
            Courses: AP Biology (A), AP Chemistry (A-), Calculus (A)
            
            I have a passion for STEM fields.
            ''',
            'email': 'jordan@example.com',
            'description': 'Essay + grades + school info (missing recommendations)'
        },
        {
            'applicationid': 999003,
            'applicantname': 'Casey - Minimal Info',
            'applicationtext': 'I want to apply to your program.',
            'email': 'casey@example.com',
            'description': 'Minimal information (almost everything missing)'
        }
    ]
    
    # Initialize Smee with database connection
    # Note: Using Azure AD authentication - no API key needed
    client = AzureOpenAI(
        api_version=config.api_version,
        azure_endpoint=config.azure_openai_endpoint,
        azure_ad_token_provider=lambda: ""  # Would be set by DefaultAzureCredential in production
    )
    
    smee = SmeeOrchestrator(
        name="Smee - Orchestrator",
        client=client,
        model=config.deployment_name,
        db_connection=db
    )
    
    # Process each test case
    for test_case in test_cases:
        print("\n" + "-" * 80)
        print(f"📋 CASE: {test_case['description']}")
        print("-" * 80)
        print(f"Student: {test_case['applicantname']}")
        print(f"Application Length: {len(test_case['applicationtext'])} characters")
        print()
        
        # Check requirements
        status = smee.check_application_requirements(test_case)
        
        # Display readiness
        readiness = status['readiness']
        print(f"📊 OVERALL READINESS: {readiness['overall_status'].upper()}")
        print(f"   Ready: {readiness['ready_count']}/{readiness['total_count']} agents ({readiness['percentage']}%)")
        print(f"   Can Proceed: {'✅ YES' if status['can_proceed'] else '❌ NO (need more info)'}")
        print()
        
        # Agent-by-agent breakdown
        print("🤖 AGENT STATUS BREAKDOWN:")
        print()
        for agent_id, agent_info in status['agents'].items():
            status_icon = '✅' if agent_info['status'] == 'ready' else '⏳' if agent_info['status'] == 'waiting' else '⚠️'
            print(f"   {status_icon} {agent_info['agent_name']}")
            print(f"      Status: {agent_info['status'].upper()}")
            print(f"      Needs: {', '.join(agent_info['required'])}")
            
            if agent_info['data_source']:
                source = agent_info['data_source'].replace('_', ' ')
                print(f"      Found: {source}")
            
            if agent_info['missing']:
                print(f"      ❌ Missing: {', '.join(agent_info['missing'])}")
            else:
                print(f"      ✅ All required info available")
            print()
        
        # Missing information
        if status['missing_information']:
            print("📤 MISSING INFORMATION TO UPLOAD:")
            for item in status['missing_information']:
                print(f"   • {item}")
            print()
        
        # Recommendation
        print(f"💡 RECOMMENDATION: {status['recommendation']}")
        print()


if __name__ == '__main__':
    try:
        demo_status_tracking()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
