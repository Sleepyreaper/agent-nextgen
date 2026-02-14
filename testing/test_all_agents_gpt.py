#!/usr/bin/env python3
"""Test all Disney agents can connect to Azure OpenAI and reason about students."""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from src.config import config
from src.agents.tiana_application_reader import TianaApplicationReader
from src.agents.rapunzel_grade_reader import RapunzelGradeReader
from src.agents.moana_school_context import MoanaSchoolContext
from src.agents.mulan_recommendation_reader import MulanRecommendationReader
from src.agents.merlin_student_evaluator import MerlinStudentEvaluator
from src.agents.smee_orchestrator import SmeeOrchestrator


# Sample student application data
SAMPLE_APPLICATION = {
    "ApplicationID": 9999,
    "ApplicantName": "Test Student",
    "Email": "test@example.com",
    "Position": "Software Engineering Intern",
    "ApplicationText": """
    My name is Test Student and I am a junior at Lincoln High School in Seattle, WA.
    I have been passionate about computer science since I built my first website in 9th grade.
    
    Throughout high school, I have maintained a 3.9 GPA while taking challenging courses including
    AP Computer Science, AP Calculus BC, and AP Physics. I founded our school's first robotics club
    and served as team captain for two years. Our team competed in the FIRST Robotics Competition
    and placed 3rd in regionals.
    
    I have completed two internships: one at a local startup where I developed mobile apps,
    and another at a non-profit where I built their volunteer management system. I also volunteer
    teaching coding to elementary school students on weekends.
    
    I am most proud of creating an app that helps students with disabilities navigate our school
    building. This project combined my technical skills with my passion for accessibility and
    social impact. I want to pursue a career in software engineering to create technology that
    makes a positive difference in people's lives.
    """,
    "OriginalFileName": "test_application.txt",
    "FileType": "text/plain"
}

SAMPLE_TRANSCRIPT = """
LINCOLN HIGH SCHOOL
1234 Main Street, Seattle, WA 98101
Official Transcript for: Test Student
Student ID: 12345
Grade Level: 11 (Junior)

=== Academic Record ===

9th Grade (2022-2023):
- English 9 Honors: A
- Algebra II Honors: A-
- Biology: A
- World History: A
- Spanish I: B+
- Introduction to Computer Science: A+
GPA: 3.85

10th Grade (2023-2024):
- English 10 Honors: A
- Pre-Calculus Honors: A
- Chemistry Honors: A-
- AP World History: A
- Spanish II: A-
- AP Computer Science Principles: A+
GPA: 3.92

11th Grade (Fall 2024):
- AP English Language: A
- AP Calculus BC: A
- AP Physics C: A-
- AP US History: A-
- Spanish III: A
- AP Computer Science A: A+
GPA: 3.96

Cumulative GPA: 3.91 (Unweighted)
Cumulative GPA: 4.38 (Weighted)
Class Rank: 12 out of 387 students (Top 3%)

AP Scores:
- AP World History: 5
- AP Computer Science Principles: 5

Activities:
- Robotics Club (Founder & Captain)
- Math Team
- National Honor Society
- Volunteer Coding Instructor

Awards:
- FIRST Robotics Regional 3rd Place
- National Merit Commended Scholar
- Principal's Honor Roll (all semesters)
"""

SAMPLE_RECOMMENDATION = """
To Whom It May Concern:

It is my great pleasure to write this recommendation for Test Student. I have had the privilege
of teaching Test for the past two years in AP Computer Science Principles and AP Computer Science A.
In my 15 years of teaching computer science, Test stands out as one of the most talented and
dedicated students I have encountered.

Test demonstrates exceptional technical skills, but what truly sets them apart is their ability
to apply these skills to solve real-world problems. When they noticed our school lacked accessible
navigation for students with disabilities, they didn't just identify the problem – they built a
complete mobile application solution. This required not only programming skills but also
empathy, user research, and project management abilities far beyond what I typically see in
high school students.

As the founder and captain of our robotics team, Test has shown remarkable leadership. They
mentored newer team members patiently, organized our team's structure, and maintained morale
even when our robot failed spectacularly at our first competition. Their ability to learn from
failure and persist is a quality that will serve them well in any engineering career.

Test is also genuinely kind and collaborative. They spend weekends teaching coding to elementary
school students and regularly help classmates understand difficult concepts. They are the student
others turn to for help, and they always make time to support their peers.

Without reservation, I give Test my highest recommendation. They have the technical skills,
work ethic, creativity, and character to excel in any software engineering program. I am
confident they will make meaningful contributions to your organization.

Please feel free to contact me if you need any additional information.

Sincerely,
Dr. Sarah Martinez
Computer Science Department Chair
Lincoln High School
smartinez@lincolnhs.edu
(206) 555-0123
"""


async def test_agent(agent_name: str, agent, test_func):
    """Test a single agent."""
    print(f"\n{'='*70}")
    print(f"Testing {agent_name}")
    print(f"{'='*70}")
    
    try:
        result = await test_func(agent)
        
        if result.get('status') == 'error':
            print(f"❌ {agent_name} FAILED: {result.get('error')}")
            return False
        else:
            print(f"✅ {agent_name} SUCCESS")
            print(f"   Response preview: {str(result)[:200]}...")
            return True
            
    except Exception as e:
        print(f"❌ {agent_name} EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Test all agents with Azure OpenAI."""
    
    print("\n" + "="*70)
    print("Azure OpenAI Multi-Agent System Test")
    print("="*70)
    
    # 1. Verify configuration
    print("\n📋 Configuration Check:")
    print(f"   Endpoint: {config.azure_openai_endpoint[:50]}...")
    print(f"   Deployment: {config.deployment_name}")
    print(f"   API Version: {config.api_version}")
    
    # 2. Initialize Azure OpenAI client
    print("\n🔌 Initializing Azure OpenAI client...")
    try:
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
    except Exception as e:
        print(f"   ❌ Client initialization failed: {e}")
        return False
    
    # 3. Test basic GPT connection
    print("\n🧪 Testing basic GPT connection...")
    try:
        response = client.chat.completions.create(
            model=config.deployment_name,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say 'Hello from Azure OpenAI' in exactly those words."}
            ],
            max_completion_tokens=50,
            temperature=1
        )
        message = response.choices[0].message.content
        print(f"   ✅ GPT Response: {message}")
    except Exception as e:
        print(f"   ❌ GPT connection failed: {e}")
        return False
    
    # 4. Initialize all agents
    print("\n👥 Initializing Disney Agents...")
    
    tiana = TianaApplicationReader(
        name="Tiana",
        client=client,
        model=config.deployment_name
    )
    print("   ✅ Tiana (Application Reader)")
    
    rapunzel = RapunzelGradeReader(
        name="Rapunzel",
        client=client,
        model=config.deployment_name
    )
    print("   ✅ Rapunzel (Grade Reader)")
    
    moana = MoanaSchoolContext(
        name="Moana",
        client=client,
        model=config.deployment_name
    )
    print("   ✅ Moana (School Context)")
    
    mulan = MulanRecommendationReader(
        name="Mulan",
        client=client,
        model=config.deployment_name
    )
    print("   ✅ Mulan (Recommendation Reader)")
    
    merlin = MerlinStudentEvaluator(
        name="Merlin",
        client=client,
        model=config.deployment_name
    )
    print("   ✅ Merlin (Student Evaluator)")
    
    smee = SmeeOrchestrator(
        name="Smee",
        client=client,
        model=config.deployment_name
    )
    print("   ✅ Smee (Orchestrator)")
    
    # 5. Test each agent individually
    print("\n\n" + "="*70)
    print("INDIVIDUAL AGENT TESTS")
    print("="*70)
    
    results = {}
    
    # Test Tiana
    results['tiana'] = await test_agent(
        "Tiana (Application Reader)",
        tiana,
        lambda agent: agent.parse_application(SAMPLE_APPLICATION)
    )
    
    # Test Rapunzel
    results['rapunzel'] = await test_agent(
        "Rapunzel (Grade Reader)",
        rapunzel,
        lambda agent: agent.parse_grades(SAMPLE_TRANSCRIPT, "Test Student")
    )
    
    # Test Mulan
    results['mulan'] = await test_agent(
        "Mulan (Recommendation Reader)",
        mulan,
        lambda agent: agent.parse_recommendation(SAMPLE_RECOMMENDATION, "Test Student")
    )
    
    # Test Moana (depends on rapunzel output)
    async def test_moana(agent):
        rapunzel_data = await rapunzel.parse_grades(SAMPLE_TRANSCRIPT, "Test Student")
        return await agent.analyze_student_school_context(
            SAMPLE_APPLICATION,
            SAMPLE_TRANSCRIPT,
            rapunzel_data
        )
    
    results['moana'] = await test_agent(
        "Moana (School Context)",
        moana,
        test_moana
    )
    
    # Test Merlin (depends on all outputs)
    async def test_merlin(agent):
        tiana_output = await tiana.parse_application(SAMPLE_APPLICATION)
        rapunzel_output = await rapunzel.parse_grades(SAMPLE_TRANSCRIPT, "Test Student")
        mulan_output = await mulan.parse_recommendation(SAMPLE_RECOMMENDATION, "Test Student")
        
        agent_outputs = {
            'tiana': tiana_output,
            'rapunzel': rapunzel_output,
            'mulan': mulan_output
        }
        
        return await agent.evaluate_student(SAMPLE_APPLICATION, agent_outputs)
    
    results['merlin'] = await test_agent(
        "Merlin (Student Evaluator)",
        merlin,
        test_merlin
    )
    
    # 6. Test orchestrator
    print("\n\n" + "="*70)
    print("ORCHESTRATOR TEST")
    print("="*70)
    
    smee.register_agent('tiana', tiana)
    smee.register_agent('rapunzel', rapunzel)
    smee.register_agent('mulan', mulan)
    smee.register_agent('moana', moana)
    smee.register_agent('merlin', merlin)
    
    try:
        orchestrator_result = await smee.coordinate_evaluation(
            SAMPLE_APPLICATION,
            ['tiana', 'rapunzel', 'mulan', 'moana', 'merlin']
        )
        results['smee'] = True
        print(f"\n✅ Smee orchestration SUCCESS")
        print(f"   Coordinated {len(orchestrator_result.get('results', {}))} agents")
    except Exception as e:
        results['smee'] = False
        print(f"\n❌ Smee orchestration FAILED: {e}")
    
    # 7. Final summary
    print("\n\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    total_tests = len(results)
    passed_tests = sum(1 for r in results.values() if r)
    
    for agent_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   {agent_name.upper():15} {status}")
    
    print(f"\n   Total: {passed_tests}/{total_tests} agents passed")
    
    if passed_tests == total_tests:
        print("\n🎉 ALL AGENTS CAN USE AZURE OPENAI GPT INSTANCE!")
        print("   Your Disney multi-agent system is ready to evaluate students.")
        return True
    else:
        print(f"\n⚠️  {total_tests - passed_tests} agent(s) failed")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
