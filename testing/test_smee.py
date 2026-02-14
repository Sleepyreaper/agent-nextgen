"""Test script for Smee Orchestrator and Grade Report Reader agents."""

import asyncio
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from src.config import Config
from src.database import db
from src.agents.smee_orchestrator import SmeeOrchestrator
from src.agents.rapunzel_grade_reader import RapunzelGradeReader
from src.agents.moana_school_context import MoanaSchoolContext


# Sample high school transcript for testing
SAMPLE_TRANSCRIPT = """
WESTVIEW HIGH SCHOOL
TRANSCRIPT OF ACADEMIC RECORD
Student: Sarah Chen
Student ID: 29382910
Graduation Date: June 2024

CUMULATIVE GRADE POINT AVERAGE: 3.87 (Weighted)
Unweighted GPA: 3.82

CLASS STANDING: Top 5% of class (15/347 students)

ACADEMIC RECORD BY SEMESTER:

FRESHMAN YEAR (2020-2021):
- English I (Standard): A (9.5 points)
- Algebra II (Honors): A- (9.0 points)
- Biology (Honors): A (9.5 points)
- World History (Standard): A (9.5 points)
- Spanish 1 (Honors): A- (9.0 points)
- PE/Health: A (0 weighted points)

SOPHOMORE YEAR (2021-2022):
- English II (Honors): A (9.5 points)
- Geometry (Honors): A (9.5 points)
- Chemistry (Honors): A- (9.0 points)
- US History (Standard): A (9.5 points)
- Spanish 2 (Honors): A (9.5 points)
- Statistics (Standard): A+ (10.0 points)
- AP Computer Science Principles: A (10.5 points)

JUNIOR YEAR (2022-2023):
- AP English Literature: A- (10.0 points)
- Pre-Calculus (Honors): A (9.5 points)
- AP Chemistry: A (10.5 points)
- AP US History: A- (10.0 points)
- Spanish 3 (Honors): A (9.5 points)
- AP European History: A (10.5 points)
- Physics (Honors): A- (9.0 points)

SENIOR YEAR (2023-2024):
- AP English Language: A (10.5 points)
- Calculus (AP): A (10.5 points)
- AP Biology: A- (10.0 points)
- AP Spanish Language: A (10.5 points)
- Organic Chemistry (Honors): A- (9.0 points)
- Philosophy (Standard): A (9.5 points)

STANDARDIZED TEST SCORES:
- SAT (March 2023): 1520/1600 (Reading: 770, Math: 750)
- SAT (January 2024): 1540/1600 (Reading: 780, Math: 760)
- AP Exam Results:
  * AP Computer Science Principles (2022): 5
  * AP Chemistry (2023): 5
  * AP US History (2023): 4
  * AP European History (2023): 5
  * AP English Literature (2023): 5
  * AP English Language (2024): 5
  * AP Biology (2024): 4
  * AP Calculus (2024): 5
  * AP Spanish Language (2024): 4

ATTENDANCE: 99.7% average (2 excused absences total, 0 unexcused)

SPECIAL NOTATIONS:
- National Merit Scholar (2023)
- Science Olympiad Team Captain (Junior/Senior)
- Debate Team President (Senior)
- Volunteer: 200+ hours community service
- Student Athlete: Varsity Tennis (4 years)

RECOMMENDATIONS FROM TEACHERS:
"Sarah demonstrates exceptional dedication and intellectual curiosity across all subjects."
- English Department

"Consistently shows mastery of advanced mathematical concepts and creative problem-solving."
- Math Department
"""


async def main():
    """Run test of Smee orchestrator with Grade Report Reader."""
    
    print("\n" + "="*70)
    print("SMEE ORCHESTRATOR & GRADE REPORT READER - DEMONSTRATION")
    print("="*70 + "\n")
    
    # Initialize configuration and client
    config = Config(key_vault_name="nextgen-agents-kv")
    
    # Validate configuration
    if not config.validate():
        missing = config.get_missing_config()
        print("❌ Missing configuration:")
        for item in missing:
            print(f"  - {item}")
        return
    
    # Initialize Azure OpenAI client with Azure AD authentication
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default"
    )
    client = AzureOpenAI(
        azure_ad_token_provider=token_provider,
        api_version=config.api_version,
        azure_endpoint=config.azure_openai_endpoint
    )
    model = config.deployment_name
    
    print(f"✓ Azure OpenAI Client initialized")
    print(f"✓ Model: {model}")
    print(f"✓ Endpoint: {config.azure_openai_endpoint}\n")
    
    # Initialize Smee Orchestrator
    smee = SmeeOrchestrator(
        name="Smee",
        client=client,
        model=model,
        db_connection=db
    )
    print(f"✓ Initialized: {smee.name} (Orchestrator Agent)\n")
    
    # Initialize Rapunzel Grade Reader
    grade_reader = RapunzelGradeReader(
        name="Rapunzel Grade Reader",
        client=client,
        model=model
    )
    print(f"✓ Initialized: {grade_reader.name}")
    print(f"  Specialization: {grade_reader.get_specialization_info()['specialization']}\n")
    
    # Initialize Moana School Context Analyzer
    school_context = MoanaSchoolContext(
        name="Moana School Context",
        client=client,
        model=model,
        db_connection=db
    )
    print(f"✓ Initialized: {school_context.name}")
    print(f"  Specialization: School environment and program access analysis\n")
    
    # Register agents with Smee
    smee.register_agent("grade_reader", grade_reader)
    smee.register_agent("school_context", school_context)
    
    print("\nRegistered Agents with Smee:")
    for agent_id, agent_name in smee.get_registered_agents().items():
        print(f"  - {agent_id}: {agent_name}")
    
    # Create a test application
    test_application = {
        'ApplicationID': 1001,
        'ApplicantName': 'Sarah Chen',
        'ApplicationText': SAMPLE_TRANSCRIPT,
        'OriginalFileName': 'sarah_chen_transcript.pdf',
        'FileType': 'transcript'
    }
    
    print("\n" + "="*70)
    print("ORCHESTRATING EVALUATION FOR: Sarah Chen")
    print("="*70)
    
    # Coordinate evaluation through Smee
    results = await smee.coordinate_evaluation(
        application=test_application,
        evaluation_steps=["grade_reader", "school_context"]
    )
    
    # Display results
    print("\n" + "="*70)
    print("EVALUATION RESULTS SUMMARY")
    print("="*70)
    
    if results['results'].get('grade_reader', {}).get('status') == 'success':
        grade_data = results['results']['grade_reader']
        
        print(f"\n📊 GRADE REPORT ANALYSIS")
        print("-" * 50)
        print(f"Student: {grade_data['student_name']}")
        print(f"GPA: {grade_data['gpa']}")
        print(f"Academic Strength: {grade_data['academic_strength']}")
        print(f"Transcript Quality: {grade_data['transcript_quality']}")
        print(f"Confidence Level: {grade_data['confidence_level']}")
        
        if grade_data['course_levels']:
            print(f"\n📚 COURSE DISTRIBUTION")
            print("-" * 50)
            for level, description in grade_data['course_levels'].items():
                print(f"{level}: {description}")
        
        if grade_data['notable_patterns']:
            print(f"\n✨ NOTABLE PATTERNS")
            print("-" * 50)
            for pattern in grade_data['notable_patterns']:
                print(f"  • {pattern}")
        
        if grade_data['summary']:
            print(f"\n📝 ACADEMIC SUMMARY")
            print("-" * 50)
            print(grade_data['summary'])
    
    # Display Moana School Context Analysis
    school_context_result = results['results'].get('school_context', {})
    
    if school_context_result.get('status') == 'success':
        school_data = school_context_result
        
        print(f"\n\n🌊 SCHOOL CONTEXT ANALYSIS (Moana)")
        print("=" * 50)
        
        if school_data.get('school'):
            school = school_data['school']
            print(f"\nSchool Identified: {school['name']}")
            if school.get('city'):
                print(f"Location: {school['city']}, {school['state']}")
            print(f"Confidence: {school.get('identification_confidence', 0)*100:.0f}%")
        
        if school_data.get('ses_context'):
            ses = school_data['ses_context']
            print(f"\nSocioeconomic Context:")
            print(f"  SES Level: {ses.get('ses_level', 'Unknown')}")
            print(f"  Opportunity Level: {ses.get('opportunity_level', 'Unknown')}")
            if ses.get('median_household_income'):
                print(f"  Median Household Income: ${ses['median_household_income']:,}")
            if ses.get('free_lunch_percentage'):
                print(f"  Free Lunch %: {ses['free_lunch_percentage']}%")
        
        if school_data.get('program_participation'):
            prog = school_data['program_participation']
            print(f"\nProgram Participation:")
            print(f"  AP Courses: {len(prog.get('ap_courses_taken', []))} taken")
            print(f"  Honors Courses: {prog.get('honors_courses_taken', 0)} taken")
            print(f"  STEM Programs: {len(prog.get('stem_courses', []))} areas")
            print(f"  Total Advanced: {prog.get('total_advanced_courses', 0)} courses")
        
        if school_data.get('opportunity_scores'):
            scores = school_data['opportunity_scores']
            print(f"\nOpportunity Scores:")
            print(f"  Program Access Score: {scores.get('program_access_score', 0)}/100")
            print(f"  Participation Score: {scores.get('program_participation_score', 0)}/100")
            print(f"  Relative Advantage: {scores.get('relative_advantage_score', 0)}/100")
            print(f"  Overall Opportunity: {scores.get('overall_opportunity_score', 0)}/100")
            if scores.get('interpretation'):
                print(f"\nInterpretation: {scores['interpretation']}")
        
        if school_data.get('contextual_summary'):
            print(f"\nContextual Summary:")
            print("-" * 50)
            print(school_data['contextual_summary'])
    elif school_context_result.get('status') == 'incomplete' or school_context_result.get('status') == 'error':
        print(f"\n\n🌊 SCHOOL CONTEXT ANALYSIS (Moana)")
        print("=" * 50)
        print(f"\nStatus: {school_context_result.get('status')}")
        print(f"Note: {school_context_result.get('error', 'Analysis could not be completed')}")
    
    # Get workflow status
    status = smee.get_workflow_status()
    print(f"\n\n🤖 SMEE ORCHESTRATOR STATUS")
    print("-" * 50)
    print(f"State: {status['state']}")
    print(f"Registered Agents: {len(status['registered_agents'])}")
    
    print("\n" + "="*70)
    print("✓ ORCHESTRATION COMPLETE")
    print("="*70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
