#!/usr/bin/env python3
"""Test Moana's Georgia school data integration."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from src.config import config
from src.agents.moana_school_context import MoanaSchoolContext


# Sample Georgia school transcript
GA_TRANSCRIPT = """
NORTH ATLANTA HIGH SCHOOL
4111 Northside Parkway NW, Atlanta, GA 30327
Official Transcript for: Alex Johnson
Student ID: 789012
Grade Level: 11 (Junior)

=== Academic Record ===

9th Grade (2022-2023):
- English 9 Honors: A
- Algebra II Honors: A-
- Biology Honors: A
- World History: A
- Spanish II: B+
- Introduction to Computer Science: A+
GPA: 3.85

10th Grade (2023-2024):
- English 10 Honors: A
- Pre-Calculus Honors: A
- Chemistry Honors: A-
- AP World History: A
- Spanish III: A-
- AP Computer Science Principles: A+
GPA: 3.92

11th Grade (Fall 2024):
- AP English Language: A
- AP Calculus BC: A
- AP Physics C: A-
- AP US History: A-
- Spanish IV Honors: A
- AP Computer Science A: A+
GPA: 3.96

Cumulative GPA: 3.91 (Unweighted)
Cumulative GPA: 4.38 (Weighted)
Class Rank: 18 out of 512 students (Top 4%)

AP Scores:
- AP World History: 5
- AP Computer Science Principles: 5

Activities:
- FIRST Robotics Team
- Math Honor Society
- Student Government
- Volunteer Tutor

Awards:
- FIRST Robotics Regional Finalist
- National Merit Semifinalist
- Principal's Honor Roll (all semesters)
- Georgia Certificate of Merit
"""

# Sample Non-Georgia school transcript
CA_TRANSCRIPT = """
LINCOLN HIGH SCHOOL
1234 Main Street, San Jose, CA 95123
Official Transcript for: Maria Garcia
Student ID: 456789
Grade Level: 11 (Junior)

9th Grade (2022-2023):
- English 9: A
- Algebra I: A-
- Biology: A
GPA: 3.8

10th Grade (2023-2024):
- English 10 Honors: A
- Geometry Honors: A
- Chemistry: A
GPA: 3.9

Cumulative GPA: 3.85
"""


async def test_georgia_detection():
    """Test that Moana correctly detects Georgia schools."""
    
    print("\n" + "="*70)
    print("Testing Moana's Georgia School Data Integration")
    print("="*70)
    
    # Initialize client
    print("\n🔌 Initializing Azure OpenAI client...")
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default"
    )
    client = AzureOpenAI(
        azure_ad_token_provider=token_provider,
        api_version=config.api_version,
        azure_endpoint=config.azure_openai_endpoint
    )
    print("   ✅ Client initialized")
    
    # Initialize Moana
    print("\n🌊 Initializing Moana...")
    moana = MoanaSchoolContext(
        name="Moana",
        client=client,
        model=config.deployment_name
    )
    print("   ✅ Moana initialized")
    print(f"   ✅ Georgia data source configured: {moana.georgia_data_source}")
    
    # Test 1: Georgia school
    print("\n" + "="*70)
    print("TEST 1: Georgia School (North Atlanta High School)")
    print("="*70)
    
    ga_application = {
        "ApplicationID": 1001,
        "ApplicantName": "Alex Johnson",
        "Email": "alex@example.com",
        "ApplicationText": "I am a junior at North Atlanta High School..."
    }
    
    ga_result = await moana.analyze_student_school_context(
        ga_application,
        GA_TRANSCRIPT
    )
    
    if ga_result.get('status') == 'success':
        print("\n✅ Georgia school analysis SUCCESSFUL")
        school = ga_result.get('school', {})
        resources = ga_result.get('school_resources', {})
        
        print(f"\nSchool Details:")
        print(f"  • Name: {school.get('name')}")
        print(f"  • City: {school.get('city')}")
        print(f"  • State: {school.get('state')}")
        
        if resources.get('georgia_data_available'):
            print(f"\n✅ GEORGIA DATA SOURCE DETECTED!")
            print(f"  • Data URL: {resources.get('data_source_url')}")
            print(f"  • Notes: {resources.get('comparison_notes')}")
            
            # Get lookup instructions
            instructions = moana.get_georgia_school_data_instructions(school.get('name'))
            print(f"\n📋 Georgia Data Lookup Instructions Available:")
            print(f"  • School: {instructions['school_name']}")
            print(f"  • Data Points: {len(instructions['data_points'])} metrics")
            print(f"  • URL: {instructions['data_source']}")
        else:
            print(f"\n⚠️  Georgia data source NOT detected (expected for GA school)")
            return False
    else:
        print(f"\n❌ Georgia school analysis FAILED: {ga_result.get('error')}")
        return False
    
    # Test 2: Non-Georgia school
    print("\n" + "="*70)
    print("TEST 2: Non-Georgia School (California)")
    print("="*70)
    
    ca_application = {
        "ApplicationID": 1002,
        "ApplicantName": "Maria Garcia",
        "Email": "maria@example.com",
        "ApplicationText": "I am a junior at Lincoln High School in California..."
    }
    
    ca_result = await moana.analyze_student_school_context(
        ca_application,
        CA_TRANSCRIPT
    )
    
    if ca_result.get('status') == 'success':
        print("\n✅ California school analysis SUCCESSFUL")
        school = ca_result.get('school', {})
        resources = ca_result.get('school_resources', {})
        
        print(f"\nSchool Details:")
        print(f"  • Name: {school.get('name')}")
        print(f"  • City: {school.get('city')}")
        print(f"  • State: {school.get('state')}")
        
        if not resources.get('georgia_data_available'):
            print(f"\n✅ Correctly identified as NON-Georgia school")
            print(f"  • No Georgia data source flagged (as expected)")
        else:
            print(f"\n⚠️  Georgia data incorrectly flagged for CA school")
            return False
    else:
        print(f"\n❌ California school analysis FAILED: {ca_result.get('error')}")
        return False
    
    # Final summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print("✅ Georgia school detection: PASSED")
    print("✅ Georgia data source integration: WORKING")
    print("✅ Non-Georgia school handling: PASSED")
    print(f"\n🎉 Moana can now identify Georgia schools and reference")
    print(f"   public data at: {moana.georgia_data_source}")
    print("="*70)
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_georgia_detection())
    sys.exit(0 if success else 1)
